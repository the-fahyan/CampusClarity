"""Pydantic request/response/error contracts — runtime source of truth (DESIGN.md §5, §8).

Responsibility: define the exact shapes served by the API. `backend/schemas.py`
≡ DESIGN.md §5–§8 ≡ PRD FRs. No side effects.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

AskStatus = Literal[
    "answered",
    "insufficient_knowledge",
    "model_refusal",
    "upstream_error",
]
ErrorStatus = Literal[
    "validation_error",
    "rate_limited",
    "kb_unavailable",
    "upstream_error",
    "internal_error",
]


class AskRequest(BaseModel):
    """POST /api/ask body (DESIGN.md §5.3); 3–500 chars after trim (FR-01/FR-02)."""

    question: str = Field(min_length=3, max_length=500)

    @field_validator("question", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


class Citation(BaseModel):
    citation_id: str
    chunk_id: int
    source_id: str
    source_title: str
    page: int
    snippet: str
    score: float
    is_sample: bool


class RetrievalInfo(BaseModel):
    top_score: float
    threshold: float
    passages_considered: int


class ModelInfo(BaseModel):
    name: str
    provider: str = "Google AI Studio (Gemini API)"
    mode: Literal["live", "mock"]


class AskResponse(BaseModel):
    """POST /api/ask 200 body (DESIGN.md §5.4)."""

    request_id: str
    status: AskStatus
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    retrieval: RetrievalInfo
    model: ModelInfo
    latency_ms: int


class HealthResponse(BaseModel):
    """GET /api/health 200 body (DESIGN.md §5.5)."""

    status: Literal["ok", "degraded"]
    index_ready: bool
    chunk_count: int
    source_count: int
    llm_mode: Literal["live", "mock"]
    model: str
    version: str


class SourceInfo(BaseModel):
    source_id: str
    title: str
    type: str
    verified: bool
    is_sample: bool
    file: str
    chunk_count: int
    pages: int


class SourcesResponse(BaseModel):
    """GET /api/sources 200 body (DESIGN.md §5.6)."""

    sources: list[SourceInfo]
    how_to_add: str


class ErrorResponse(BaseModel):
    """Error body for 429/500/502/503 (DESIGN.md §5.7)."""

    request_id: str
    status: ErrorStatus
    message: str
