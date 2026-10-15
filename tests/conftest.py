"""Shared pytest fixtures: settings, a tiny synthetic index, and a TestClient.

Rules (DESIGN.md §15): no network, no real key, fixtures never touch the real
`index/` or `data/` — everything is built under `tmp_path`.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.retrieval import RetrievalIndex, reset_index
from backend.textutils import tokenize


def make_settings(**overrides) -> Settings:
    base = dict(
        MOCK_LLM=True,
        GEMINI_API_KEY="",
        BM25_MIN_SCORE=10.5,
        BM25_TOP_K=5,
        RATE_LIMIT_PER_MINUTE=60,
        INDEX_DIR="index",
        SOURCES_DIR="data/sources",
        FRONTEND_DIR="frontend",
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# Synthetic chunks: enough to exercise ranking, the gate, tokenizer numbers,
# and sample labelling. Text is invented *for tests only* (not university data).
TINY_CHUNKS = [
    {
        "chunk_id": 0,
        "source_id": "prospectus",
        "source_title": "Integral University Prospectus",
        "source_type": "prospectus",
        "is_sample": False,
        "page_start": 45,
        "page_end": 45,
        "section": "Fees",
        "text": "Hostel fee single occupancy room is 1,05,000 rupees per annum for hostellers.",
    },
    {
        "chunk_id": 1,
        "source_id": "prospectus",
        "source_title": "Integral University Prospectus",
        "source_type": "prospectus",
        "is_sample": False,
        "page_start": 10,
        "page_end": 10,
        "section": "Library",
        "text": "The central library is open from eight in the morning until eight in the evening on all working days.",
    },
    {
        "chunk_id": 2,
        "source_id": "sample-notice",
        "source_title": "Sample Notice",
        "source_type": "sample",
        "is_sample": True,
        "page_start": 1,
        "page_end": 1,
        "section": None,
        "text": "SAMPLE DOCUMENT. The sports complex opens at seven in the morning on weekdays.",
    },
    {
        "chunk_id": 3,
        "source_id": "prospectus",
        "source_title": "Integral University Prospectus",
        "source_type": "prospectus",
        "is_sample": False,
        "page_start": 46,
        "page_end": 46,
        "section": "Fees",
        "text": "The hostel security deposit is five thousand rupees and is refundable.",
    },
]


def build_tiny_index(index_dir: Path, chunks: list[dict] | None = None) -> Path:
    """Write a minimal chunks.json + bm25.pkl under `index_dir`."""
    from rank_bm25 import BM25Okapi

    chunks = chunks if chunks is not None else TINY_CHUNKS
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False), encoding="utf-8"
    )
    tokenized = [tokenize(c["text"]) for c in chunks]
    bm25 = BM25Okapi(tokenized, k1=1.5, b=0.75)
    with (index_dir / "bm25.pkl").open("wb") as fh:
        pickle.dump(
            {"bm25": bm25, "tokenized": tokenized, "chunk_ids": [c["chunk_id"] for c in chunks]},
            fh,
        )
    return index_dir


@pytest.fixture(autouse=True)
def _clear_index_cache():
    reset_index()
    yield
    reset_index()


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def tmp_index(tmp_path: Path) -> RetrievalIndex:
    index_dir = build_tiny_index(tmp_path / "index")
    return RetrievalIndex.load(index_dir)


@pytest.fixture
def client(tmp_index: RetrievalIndex, tmp_path: Path) -> TestClient:
    """TestClient wired to the tiny synthetic index (mock LLM)."""
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "manifest.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "prospectus",
                        "title": "Integral University Prospectus",
                        "type": "prospectus",
                        "verified": True,
                        "is_sample": False,
                        "file": "prospectus.txt",
                    },
                    {
                        "source_id": "sample-notice",
                        "title": "Sample Notice",
                        "type": "sample",
                        "verified": False,
                        "is_sample": True,
                        "file": "sample-notice.txt",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = make_settings(SOURCES_DIR=str(sources_dir), BM25_MIN_SCORE=1.0)
    from backend.main import create_app  # imported lazily (needs the full app)

    app = create_app(settings=settings, index=tmp_index)
    return TestClient(app)
