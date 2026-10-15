"""Unit tests for ingestion: manifest validation, normalization, dedupe, chunking."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.textutils import normalize_text, tokenize
from scripts.ingest import (
    IngestionError,
    Source,
    build_chunks,
    dedupe_pages,
    ingest,
    load_manifest,
    split_pages,
    warn_unlisted_files,
    ChunkingStats,
)


def _write_source(tmp_path: Path, name: str, text: str) -> Path:
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    (sources / name).write_text(text, encoding="utf-8")
    return sources


def _write_manifest(sources: Path, entries: list[dict]) -> None:
    (sources / "manifest.json").write_text(
        json.dumps({"sources": entries}), encoding="utf-8"
    )


# --- normalization (FR-10) -------------------------------------------------- #
def test_normalize_ligatures():
    assert normalize_text("ef\ufb01cient \ufb02ow") == "efficient flow"


def test_normalize_backtick_before_digit_becomes_rupee():
    assert "\u20b9" in normalize_text("Fees ` 1,05,000/-")


def test_normalize_strips_control_chars_and_collapses_blanks():
    assert normalize_text("a\x00b\x07c") == "abc"
    assert normalize_text("a\n\n\n\n\nb") == "a\n\nb"


# --- tokenizer (DESIGN.md §6.4) -------------------------------------------- #
def test_tokenizer_number_equivalence():
    assert "105000" in tokenize("1,05,000")
    assert "1,05,000" in tokenize("1,05,000")
    assert set(tokenize("105000")) & set(tokenize("1,05,000"))


def test_tokenizer_plural_normalization():
    assert "sibling" in tokenize("siblings")


# --- manifest validation (FR-09 / FR-12) ----------------------------------- #
def test_manifest_requires_is_sample_prefix_match(tmp_path: Path):
    sources = _write_source(tmp_path, "sample-x.txt", "hello world content")
    _write_manifest(
        sources,
        [{"source_id": "x", "title": "X", "file": "sample-x.txt", "type": "sample", "is_sample": False}],
    )
    with pytest.raises(IngestionError):
        load_manifest(sources)


def test_manifest_invalid_type(tmp_path: Path):
    sources = _write_source(tmp_path, "a.txt", "content here")
    _write_manifest(
        sources,
        [{"source_id": "a", "title": "A", "file": "a.txt", "type": "bogus", "is_sample": False}],
    )
    with pytest.raises(IngestionError):
        load_manifest(sources)


def test_unlisted_file_is_warned_not_ingested(tmp_path: Path):
    sources = _write_source(tmp_path, "prospectus.txt", "content")
    (sources / "stray.txt").write_text("not in manifest", encoding="utf-8")
    _write_manifest(
        sources,
        [{"source_id": "prospectus", "title": "P", "file": "prospectus.txt", "type": "prospectus", "is_sample": False}],
    )
    entries = load_manifest(sources)
    warnings = warn_unlisted_files(sources, entries)
    assert "stray.txt" in warnings
    assert "prospectus.txt" not in warnings


# --- dedupe + chunking (FR-10 / FR-11) ------------------------------------- #
def test_dedupe_identical_pages():
    pages = {1: "Same page text here.", 2: "Same page text here.", 3: "Different content."}
    stats = ChunkingStats()
    result = dedupe_pages(pages, stats)
    assert set(result.keys()) == {1, 3}
    assert stats.pages_deduped == 1


def test_chunk_bounds_and_page_spans(tmp_path: Path):
    long_para = "This is a sentence about university policy. " * 20
    text = f"===== PAGE 1 =====\n{long_para}\n===== PAGE 3 =====\nShort page text."
    pages = dedupe_pages(split_pages(normalize_text(text)), ChunkingStats())
    src = Source("prospectus", "P", "prospectus.txt", "prospectus", True, False)
    chunks = build_chunks(src, pages)
    assert chunks, "expected chunks"
    for c in chunks:
        assert c["page_start"] <= c["page_end"]
        assert len(c["text"]) <= 900  # bounded (FR-11)
    assert chunks[0]["page_start"] == 1


def test_ingest_end_to_end(tmp_path: Path):
    body = "===== PAGE 1 =====\nHostel fee is 1,05,000 per year. " * 6
    sources = _write_source(tmp_path, "prospectus.txt", body)
    _write_manifest(
        sources,
        [{"source_id": "prospectus", "title": "P", "file": "prospectus.txt", "type": "prospectus", "is_sample": False}],
    )
    index_dir = tmp_path / "index"
    summary = ingest(sources, index_dir)
    assert summary["chunks"] > 0
    data = json.loads((index_dir / "chunks.json").read_text(encoding="utf-8"))
    keys = set(data[0].keys())
    assert {"chunk_id", "source_id", "page_start", "is_sample"} <= keys
    assert (index_dir / "bm25.pkl").exists()


def test_ingest_fails_on_missing_file(tmp_path: Path):
    sources = tmp_path / "sources"
    sources.mkdir()
    _write_manifest(
        sources,
        [{"source_id": "p", "title": "P", "file": "missing.txt", "type": "prospectus", "is_sample": False}],
    )
    with pytest.raises(IngestionError):
        ingest(sources, tmp_path / "index")
