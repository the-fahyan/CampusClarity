"""Generation: Gemini/Gemma REST call, retries + fallback, MOCK_LLM, parsing.

Responsibility (DESIGN.md §1.2, §6.5, §6.6): transport to the model via `httpx`,
fault handling (NFR-02), a deterministic canned mode (FR-21), and parsing of the
model output into grounded, validated citation indices. Deciding the final status
is the service layer's job — this module returns a parsed result.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import httpx

from backend.config import Settings
from backend.prompts import (
    SENTINEL,
    SOURCES_PREFIX,
    build_system_instruction,
    build_user_message,
)
from backend.textutils import text_preview, tokenize


class UpstreamError(RuntimeError):
    """Raised when the model API fails after retry + fallback (→ HTTP 502)."""


# --- Data returned to the service layer ------------------------------------ #
@dataclass
class RawOutput:
    text: str
    model: str
    mode: str  # "live" | "mock"


@dataclass
class ParsedResponse:
    is_sentinel: bool
    answer: str
    cited_indices: list[int] = field(default_factory=list)

    @property
    def has_factual_content(self) -> bool:
        return bool(self.answer.strip())


_MARKER = re.compile(r"\[(\d+)\]")
_SOURCES_LINE = re.compile(r"^\s*Sources:\s*(.*)$", re.IGNORECASE | re.MULTILINE)

# Common English words excluded from mock keyword matching (keeps the canned,
# grounded answer tied to content words actually present in the passages).
_STOPWORDS = {
    "what", "when", "where", "which", "who", "whom", "how", "why", "there",
    "their", "this", "that", "these", "those", "does", "have", "has", "had",
    "with", "from", "into", "about", "would", "could", "should", "please",
    "campus", "university", "college", "tell", "give", "know", "many", "much",
    "need", "want", "long", "time", "cost", "price", "charge",
}

# Prompt-injection phrases the mock refuses (mirrors the system-prompt stance).
_INJECTION_TRIGGERS = (
    "your own knowledge", "from your knowledge", "ignore the sources",
    "ignore the passages", "ignore all", "invent", "make up", "makeup",
    "pretend", "disregard", "guess the",
)


# --------------------------------------------------------------------------- #
# Parsing (DESIGN.md §6.6 parse rules)
# --------------------------------------------------------------------------- #
def parse_response(text: str, retrieved_numbers: Sequence[int]) -> ParsedResponse:
    """Parse raw model text into answer + validated citation indices (FR-04/FR-06)."""
    raw = (text or "").strip()
    valid = set(retrieved_numbers)

    if raw.upper().startswith(SENTINEL):
        remainder = raw[len(SENTINEL):].strip()
        return ParsedResponse(is_sentinel=True, answer=remainder)

    # Extract the trailing "Sources: [...]" line.
    cited: list[int] = []
    match = _SOURCES_LINE.search(raw)
    if match:
        cited = [int(n) for n in _MARKER.findall(match.group(1))]
        body = raw[: match.start()].strip()
    else:
        body = raw

    # Citations = indices ∩ retrieved set (drop invalid, dedupe, keep order).
    seen: set[int] = set()
    validated: list[int] = []
    for idx in cited:
        if idx in valid and idx not in seen:
            seen.add(idx)
            validated.append(idx)

    # Sanitize inline markers: only keep [n] whose n is a valid retrieved passage.
    def _clean_marker(m: re.Match) -> str:
        return m.group(0) if int(m.group(1)) in valid else ""

    answer = _MARKER.sub(_clean_marker, body).strip()
    return ParsedResponse(is_sentinel=False, answer=answer, cited_indices=validated)


# --------------------------------------------------------------------------- #
# MOCK_LLM — deterministic, grounded, no network (FR-21)
# --------------------------------------------------------------------------- #
def _mock_snippet(chunk_text: str, keywords: Sequence[str]) -> str:
    """Pick the sentence in the passage that best matches the query keywords."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", chunk_text) if s.strip()]
    if not sentences:
        return text_preview(chunk_text, 200)
    best_i, best_hits = 0, 0
    for i, sentence in enumerate(sentences):
        low = sentence.lower()
        hits = sum(1 for kw in keywords if kw in low)
        if hits > best_hits:  # first sentence with the most matches wins
            best_i, best_hits = i, hits
    if best_hits == 0:
        return text_preview(chunk_text, 200)
    snippet = sentences[best_i]
    # Add the next sentence when the best one is short (more context, still <120 words).
    if len(snippet) < 110 and best_i + 1 < len(sentences):
        snippet = f"{snippet} {sentences[best_i + 1]}"
    return text_preview(snippet, 300)


def _mock_generate(question: str, passages: Iterable) -> str:
    """Keyword-grounded canned response text: quote the best passage or refuse."""
    lowered = question.lower()
    # Mirror the system prompt's injection stance (AGENTS §11): scoped to passages.
    if any(trigger in lowered for trigger in _INJECTION_TRIGGERS):
        return (
            f"{SENTINEL} I can only answer from the campus sources I am given, "
            "so I won't invent an answer."
        )
    q_tokens = {t for t in tokenize(question) if len(t) >= 4 and t not in _STOPWORDS}
    best = None
    best_score = 0
    for p in passages:
        p_tokens = set(tokenize(p.chunk["text"]))
        overlap = len(q_tokens & p_tokens)
        if overlap > best_score:
            best_score = overlap
            best = p
    if best is None or best_score == 0:
        return f"{SENTINEL} I couldn't find that in the campus sources I can see."
    snippet = _mock_snippet(best.chunk["text"], sorted(q_tokens, key=len, reverse=True))
    n = best.number
    return f"{snippet} [{n}]\n\n{SOURCES_PREFIX} [{n}]"


# --------------------------------------------------------------------------- #
# Live transport (DESIGN.md §6.5)
# --------------------------------------------------------------------------- #
class Generator:
    """Gemma generation client with retry + model fallback (NFR-02, D-10)."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._transport = transport

    # -- public API --
    def generate(self, question: str, passages: Sequence) -> RawOutput:
        if self.settings.MOCK_LLM:
            text = _mock_generate(question, passages)
            return RawOutput(text=text, model=self.settings.GEMMA_MODEL_ID, mode="mock")
        return self._live(question, passages)

    # -- internals --
    def _live(self, question: str, passages: Sequence) -> RawOutput:
        models = [self.settings.GEMMA_MODEL_ID]
        if self.settings.GEMMA_FALLBACK_MODEL_ID not in models:
            models.append(self.settings.GEMMA_FALLBACK_MODEL_ID)

        user_message = build_user_message(passages, question)
        last_error = "unknown"

        for model in models:
            for attempt in range(2):  # first try + 1 retry on retryable faults
                try:
                    text = self._call(model, user_message)
                    return RawOutput(text=text, model=model, mode="live")
                except _RetryableError as exc:
                    last_error = f"{model}: {exc}"
                    if attempt == 0:
                        time.sleep(0.5)
                        continue
                    break  # exhausted retries for this model → fallback
                except _FatalUpstreamError as exc:
                    raise UpstreamError(f"{model}: {exc}") from exc
        raise UpstreamError(f"model call failed after retry+fallback ({last_error})")

    def _call(self, model: str, user_message: str) -> str:
        url = f"{self.settings.GEMINI_API_BASE}/models/{model}:generateContent"
        payload = {
            "system_instruction": {"parts": [{"text": build_system_instruction()}]},
            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
                "topP": 0.95,
            },
        }
        headers = {
            "x-goog-api-key": self.settings.GEMINI_API_KEY,
            "content-type": "application/json",
        }
        kwargs = {"timeout": httpx.Timeout(20.0)}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        try:
            with httpx.Client(**kwargs) as client:
                resp = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise _RetryableError("timeout") from exc
        except httpx.HTTPError as exc:
            raise _RetryableError(f"network error: {exc}") from exc

        if resp.status_code == 429 or resp.status_code >= 500:
            raise _RetryableError(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise _FatalUpstreamError(f"HTTP {resp.status_code}")
        return self._extract_text(resp)

    @staticmethod
    def _extract_text(resp: httpx.Response) -> str:
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise _RetryableError("invalid JSON from model") from exc
        candidates = data.get("candidates") or []
        if not candidates:
            raise _RetryableError("no candidates in model response")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise _RetryableError("empty text in model response")
        return text


class _RetryableError(Exception):
    """Transient upstream failure: retry once, then try the fallback model."""


class _FatalUpstreamError(Exception):
    """Non-retryable upstream failure (e.g., 400/403): fail to a 502 immediately."""
