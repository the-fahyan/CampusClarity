"""Retrieval: index load, BM25 search, and the layer-1 abstention gate.

Responsibility (DESIGN.md §1.2, §6.4): load `index/chunks.json` + `index/bm25.pkl`,
run BM25 search with the shared tokenizer, and expose the deterministic threshold
decision. Contains no generation and no ingestion logic.
"""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path

from backend.textutils import tokenize


class KnowledgeBaseError(RuntimeError):
    """Raised when the index is missing or unreadable (→ health `degraded`)."""


@dataclass
class Passage:
    """A retrieved chunk with its BM25 score and its 1-based prompt position."""

    number: int
    chunk: dict
    score: float

    @property
    def chunk_id(self) -> int:
        return int(self.chunk["chunk_id"])

    @property
    def page(self) -> int:
        return int(self.chunk["page_start"])


@dataclass
class SearchResult:
    passages: list[Passage] = field(default_factory=list)
    top_score: float = 0.0

    @property
    def chunk_ids(self) -> set[int]:
        return {p.chunk_id for p in self.passages}


class RetrievalIndex:
    """Loaded BM25 index bound to its chunk metadata."""

    def __init__(self, chunks: list[dict], bm25, tokenized: list[list[str]]):
        self.chunks = chunks
        self.bm25 = bm25
        self.tokenized = tokenized
        self._by_id = {int(c["chunk_id"]): c for c in chunks}

    @classmethod
    def load(cls, index_dir: Path) -> "RetrievalIndex":
        chunks_path = Path(index_dir) / "chunks.json"
        bm25_path = Path(index_dir) / "bm25.pkl"
        if not chunks_path.exists() or not bm25_path.exists():
            raise KnowledgeBaseError(
                f"index not found in '{index_dir}'. Run: python scripts/ingest.py"
            )
        try:
            chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
            with bm25_path.open("rb") as fh:
                payload = pickle.load(fh)
        except (json.JSONDecodeError, pickle.UnpicklingError, OSError) as exc:
            raise KnowledgeBaseError(f"index unreadable: {exc}") from exc
        return cls(chunks, payload["bm25"], payload.get("tokenized", []))

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    def get_chunk(self, chunk_id: int) -> dict | None:
        return self._by_id.get(chunk_id)

    def search(self, question: str, k: int = 5) -> SearchResult:
        tokens = tokenize(question)
        if not tokens or not self.chunks:
            return SearchResult(passages=[], top_score=0.0)
        scores = self.bm25.get_scores(tokens)
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        passages = [
            Passage(number=idx + 1, chunk=self.chunks[i], score=float(scores[i]))
            for idx, i in enumerate(order)
        ]
        top = float(max(scores)) if len(scores) else 0.0
        return SearchResult(passages=passages, top_score=top)


# --- Module-level lazy singleton (runtime path uses settings.INDEX_DIR) ------- #
_INDEX: RetrievalIndex | None = None


def load_index(index_dir: Path) -> RetrievalIndex:
    """Load and cache the global index (raises KnowledgeBaseError if missing)."""
    global _INDEX
    if _INDEX is None:
        _INDEX = RetrievalIndex.load(Path(index_dir))
    return _INDEX


def reset_index() -> None:
    """Drop the cached index (tests and post-ingest reloads)."""
    global _INDEX
    _INDEX = None


def index_ready(index_dir: Path) -> bool:
    """True when both generated artifacts exist (health `index_ready`)."""
    d = Path(index_dir)
    return (d / "chunks.json").exists() and (d / "bm25.pkl").exists()


def below_threshold(top_score: float, threshold: float) -> bool:
    """Layer-1 gate: a top score below the threshold refuses without any model call."""
    return top_score < threshold
