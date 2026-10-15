"""Orchestration: the ask-pipeline (DESIGN.md §1.2, §6.1).

Responsibility: retrieve → layer-1 gate → generate → parse/validate → build the
`AskResponse`. Performs no HTTP handling and makes no direct model calls (it
delegates to `retrieval.py` and `generator.py`).
"""
from __future__ import annotations

import time

from backend.config import Settings
from backend.generator import Generator, parse_response
from backend.prompts import (
    MODEL_REFUSAL_PREFIX,
    REFUSAL_MESSAGE,
    REFUSAL_TIP,
)
from backend.retrieval import Passage, RetrievalIndex, SearchResult, below_threshold
from backend.schemas import (
    AskResponse,
    Citation,
    ModelInfo,
    RetrievalInfo,
)
from backend.textutils import text_preview


def _refusal_answer(status: str) -> str:
    body = REFUSAL_MESSAGE
    if status == "model_refusal":
        body = MODEL_REFUSAL_PREFIX + body
    return f"{body}\n\n{REFUSAL_TIP}"


def _build_citations(indices: list[int], passages: list[Passage]) -> list[Citation]:
    """Map validated passage numbers → citation metadata (FR-04, D-9).

    Chroma: duplicate pages are deduplicated (first wins).
    """
    by_number = {p.number: p for p in passages}
    citations: list[Citation] = []
    seen_pages: set[tuple[int, int]] = set()
    for n in indices:
        passage = by_number.get(n)
        if passage is None:
            continue
        page = passage.page
        key = (passage.chunk_id, page)
        if key in seen_pages:
            continue
        seen_pages.add(key)
        citations.append(
            Citation(
                citation_id=f"c{len(citations) + 1}",
                chunk_id=passage.chunk_id,
                source_id=passage.chunk["source_id"],
                source_title=passage.chunk["source_title"],
                page=page,
                snippet=text_preview(passage.chunk["text"], 150),
                score=round(passage.score, 4),
                is_sample=bool(passage.chunk["is_sample"]),
            )
        )
    return citations


class AnswerService:
    """Wraps retrieval + generation into the documented control flow (§6.1)."""

    def __init__(self, settings: Settings, index: RetrievalIndex, generator: Generator):
        self.settings = settings
        self.index = index
        self.generator = generator

    def ask(self, question: str, request_id: str) -> AskResponse:
        started = time.perf_counter()
        passages = self.index.search(question, k=self.settings.BM25_TOP_K)
        retrieval = RetrievalInfo(
            top_score=round(passages.top_score, 4),
            threshold=self.settings.BM25_MIN_SCORE,
            passages_considered=len(passages.passages),
        )

        # Layer 1 — deterministic gate, no model call (FR-05).
        if below_threshold(passages.top_score, self.settings.BM25_MIN_SCORE):
            return self._refuse(
                "insufficient_knowledge", request_id, retrieval, passages, started
            )

        raw = self.generator.generate(question, passages.passages)
        parsed = parse_response(raw.text, [p.number for p in passages.passages])

        # Layer 2 — model sentinel (FR-06).
        if parsed.is_sentinel:
            return self._refuse("model_refusal", request_id, retrieval, passages, started)

        citations = _build_citations(parsed.cited_indices, passages.passages)

        # Factual content with zero surviving citations ⇒ downgrade (D-9, §6.6).
        if parsed.has_factual_content and not citations:
            return self._refuse("model_refusal", request_id, retrieval, passages, started)

        latency_ms = int((time.perf_counter() - started) * 1000)
        return AskResponse(
            request_id=request_id,
            status="answered",
            answer=parsed.answer,
            citations=citations,
            retrieval=retrieval,
            model=ModelInfo(name=raw.model, mode=raw.mode),  # type: ignore[arg-type]
            latency_ms=latency_ms,
        )

    def _refuse(
        self,
        status: str,
        request_id: str,
        retrieval: RetrievalInfo,
        result: SearchResult,
        started: float,
    ) -> AskResponse:
        return AskResponse(
            request_id=request_id,
            status=status,  # type: ignore[arg-type]
            answer=_refusal_answer(status),
            citations=[],
            retrieval=retrieval,
            model=ModelInfo(
                name=self.settings.GEMMA_MODEL_ID, mode=self.settings.llm_mode
            ),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
