"""Unit tests for retrieval: ranking, threshold gate, tokenizer, missing index."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.retrieval import (
    KnowledgeBaseError,
    RetrievalIndex,
    below_threshold,
)


def test_known_question_ranks_expected_chunk_first(tmp_index: RetrievalIndex):
    result = tmp_index.search("single occupancy hostel fee", k=3)
    assert result.passages, "expected passages"
    assert result.passages[0].chunk_id == 0


def test_number_query_matches_comma_variant(tmp_index: RetrievalIndex):
    # "105000" (no commas) must match the chunk containing "1,05,000".
    result = tmp_index.search("105000", k=3)
    assert result.passages[0].chunk_id == 0


def test_out_of_scope_question_scores_low(tmp_index: RetrievalIndex):
    result = tmp_index.search("quantum entanglement in the music department", k=3)
    assert result.top_score < 10.5


def test_gate_refuses_below_threshold(tmp_index: RetrievalIndex):
    # A query with no corpus vocabulary yields a zero score.
    result = tmp_index.search("zzzqqq", k=3)
    assert below_threshold(result.top_score, 1.0) is True


def test_gate_passes_in_scope(tmp_index: RetrievalIndex):
    result = tmp_index.search("hostel security deposit", k=3)
    assert below_threshold(result.top_score, 1.0) is False


def test_missing_index_raises(tmp_path: Path):
    with pytest.raises(KnowledgeBaseError):
        RetrievalIndex.load(tmp_path / "nope")


def test_sample_chunk_is_flagged(tmp_index: RetrievalIndex):
    result = tmp_index.search("sports complex opening", k=3)
    top = result.passages[0].chunk
    assert top["is_sample"] is True
