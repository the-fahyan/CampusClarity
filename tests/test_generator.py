"""Unit tests for generation: prompt, parsing, citations, retry/fallback, mock."""
from __future__ import annotations

import json

import httpx
import pytest

from backend.generator import Generator, UpstreamError, parse_response
from backend.prompts import SENTINEL, build_system_instruction, build_user_message
from backend.retrieval import Passage
from tests.conftest import TINY_CHUNKS, make_settings


def _passages(texts: list[str] | None = None) -> list[Passage]:
    chunks = TINY_CHUNKS if texts is None else [
        {**TINY_CHUNKS[0], "chunk_id": i, "text": t} for i, t in enumerate(texts)
    ]
    return [Passage(number=i + 1, chunk=c, score=20.0) for i, c in enumerate(chunks)]


# --- prompt (FR-03) --------------------------------------------------------- #
def test_prompt_contains_all_passages_and_rules():
    passages = _passages()
    msg = build_user_message(passages, "What is the hostel fee?")
    for p in passages:
        assert f"PASSAGE [{p.number}]" in msg
        assert p.chunk["text"][:20] in msg
    assert "What is the hostel fee?" in msg
    system = build_system_instruction()
    assert SENTINEL in system
    assert "Sources:" in system


def test_prompt_marks_sample_passage():
    passages = _passages([TINY_CHUNKS[2]["text"]])
    msg = build_user_message(passages, "q")
    assert "SAMPLE" in msg


# --- parsing (FR-04 / FR-06) ------------------------------------------------ #
def test_sentinel_detected():
    parsed = parse_response(f"{SENTINEL} Sorry, not in the sources.", [1, 2])
    assert parsed.is_sentinel
    assert "Sorry" in parsed.answer


def test_invalid_citation_index_dropped():
    parsed = parse_response("Fee is X [1]. Other is Y [9].\n\nSources: [1], [9]", [1, 2, 3])
    assert parsed.cited_indices == [1]
    assert "[9]" not in parsed.answer  # sanitized inline marker


def test_missing_sources_line_yields_no_citations():
    parsed = parse_response("The fee is 1,05,000 [1] with no sources line.", [1, 2])
    assert parsed.cited_indices == []


def test_sources_line_is_stripped_from_answer():
    parsed = parse_response("Fee is X [1].\n\nSources: [1]", [1])
    assert "Sources:" not in parsed.answer
    assert parsed.cited_indices == [1]


# --- mock mode (FR-21) ------------------------------------------------------ #
def test_mock_returns_cited_answer():
    settings = make_settings(MOCK_LLM=True)
    gen = Generator(settings)
    raw = gen.generate("single occupancy hostel fee", _passages())
    assert raw.mode == "mock"
    assert "Sources:" in raw.text


# --- live transport: retry + fallback (NFR-02) ------------------------------ #
def _ok_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
    )


def _model_of(request: httpx.Request) -> str:
    # .../v1beta/models/{model}:generateContent
    return request.url.path.split("/models/")[1].split(":")[0]


def test_fallback_on_429_then_success(monkeypatch):
    monkeypatch.setattr("backend.generator.time.sleep", lambda *_: None)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = _model_of(request)
        calls.append(model)
        if model == "primary-model":
            return httpx.Response(429, json={"error": "quota"})
        return _ok_response("Answer [1]\n\nSources: [1]")

    settings = make_settings(
        MOCK_LLM=False,
        GEMINI_API_KEY="test_key",
        GEMMA_MODEL_ID="primary-model",
        GEMMA_FALLBACK_MODEL_ID="fallback-model",
    )
    gen = Generator(settings, transport=httpx.MockTransport(handler))
    raw = gen.generate("q", _passages())
    assert raw.model == "fallback-model"
    # primary tried twice (retry), then fallback once → order preserved.
    assert calls == ["primary-model", "primary-model", "fallback-model"]


def test_exhausted_chain_raises_upstream_error(monkeypatch):
    monkeypatch.setattr("backend.generator.time.sleep", lambda *_: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    settings = make_settings(
        MOCK_LLM=False, GEMINI_API_KEY="test_key",
        GEMMA_MODEL_ID="m1", GEMMA_FALLBACK_MODEL_ID="m2",
    )
    gen = Generator(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamError):
        gen.generate("q", _passages())


def test_non_retryable_status_fails_immediately():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(_model_of(request))
        return httpx.Response(403, json={"error": "forbidden"})

    settings = make_settings(
        MOCK_LLM=False, GEMINI_API_KEY="test_key",
        GEMMA_MODEL_ID="m1", GEMMA_FALLBACK_MODEL_ID="m2",
    )
    gen = Generator(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamError):
        gen.generate("q", _passages())
    assert calls == ["m1"]  # no retry, no fallback on a fatal error
