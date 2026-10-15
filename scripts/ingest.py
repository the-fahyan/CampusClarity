"""Knowledge-base ingestion: manifest → normalize → dedupe → chunk → index.

Responsibility (DESIGN.md §1.2, §6.3): validate `data/sources/manifest.json`,
read listed files, normalize (FR-10), remove exact duplicate page content,
chunk (FR-11), and write the generated artifacts `index/chunks.json` +
`index/bm25.pkl`. No network calls to any LLM.

Run: python scripts/ingest.py
"""
from __future__ import annotations

import json
import pickle
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Make the project root importable when run as a script (python scripts/ingest.py).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

from backend.textutils import PAGE_MARKER, normalize_text, tokenize  # noqa: E402

# --- Chunking parameters (DESIGN.md D-8 / FR-11) ---
TARGET_CHARS = 600
OVERLAP_CHARS = 100
MIN_CHARS = 200
MAX_CHARS = 900

VALID_TYPES = {"prospectus", "handbook", "notice", "syllabus", "regulation", "sample"}


class IngestionError(RuntimeError):
    """Raised on manifest/file validation failures (fails fast, FR-09/FR-12)."""


@dataclass
class Source:
    source_id: str
    title: str
    file: str
    type: str
    verified: bool
    is_sample: bool
    notes: str = ""
    added_on: str = ""


@dataclass
class Unit:
    """A chunkable paragraph with its originating PDF page and nearest heading."""

    page: int
    text: str
    section: str | None


@dataclass
class ChunkingStats:
    pages_seen: int = 0
    pages_deduped: int = 0
    short_pages: list[int] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Manifest validation
# --------------------------------------------------------------------------- #
def load_manifest(sources_dir: Path) -> list[Source]:
    manifest_path = sources_dir / "manifest.json"
    if not manifest_path.exists():
        raise IngestionError(f"manifest not found: {manifest_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IngestionError(f"manifest is not valid JSON: {exc}") from exc

    entries = raw.get("sources")
    if not isinstance(entries, list):
        raise IngestionError("manifest must contain a 'sources' array")

    sources: list[Source] = []
    seen_ids: set[str] = set()
    for entry in entries:
        for key in ("source_id", "title", "file", "type", "is_sample"):
            if key not in entry:
                raise IngestionError(f"manifest entry missing '{key}': {entry}")
        sid = str(entry["source_id"])
        if sid in seen_ids:
            raise IngestionError(f"duplicate source_id: {sid}")
        seen_ids.add(sid)
        if entry["type"] not in VALID_TYPES:
            raise IngestionError(
                f"source '{sid}' has invalid type '{entry['type']}' "
                f"(allowed: {sorted(VALID_TYPES)})"
            )
        is_sample = bool(entry["is_sample"])
        filename = str(entry["file"])
        # FR-12: is_sample MUST equal file.startswith("sample-")
        if is_sample != filename.startswith("sample-"):
            raise IngestionError(
                f"source '{sid}': is_sample={is_sample} but file '{filename}' "
                f"does not match the 'sample-' prefix rule (FR-12)"
            )
        sources.append(
            Source(
                source_id=sid,
                title=str(entry["title"]),
                file=filename,
                type=str(entry["type"]),
                verified=bool(entry.get("verified", False)),
                is_sample=is_sample,
                notes=str(entry.get("notes", "")),
                added_on=str(entry.get("added_on", "")),
            )
        )
    return sources


def warn_unlisted_files(sources_dir: Path, sources: list[Source]) -> list[str]:
    """FR-09: files present but not listed in the manifest are ignored (warned)."""
    listed = {s.file for s in sources}
    warnings: list[str] = []
    for path in sorted(sources_dir.iterdir()):
        if path.is_dir() or path.name == "manifest.json":
            continue
        if path.name not in listed:
            warnings.append(path.name)
    return warnings


# --------------------------------------------------------------------------- #
# Page parsing + normalization + dedupe
# --------------------------------------------------------------------------- #
def split_pages(text: str) -> dict[int, str]:
    """Split on `===== PAGE n =====` markers → {page_number: page_text}."""
    pages: dict[int, str] = {}
    matches = list(PAGE_MARKER.finditer(text))
    if not matches:
        # No markers: treat the whole file as page 1.
        return {1: text}
    for idx, match in enumerate(matches):
        page_no = int(match.group(1))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        pages[page_no] = text[start:end]
    return pages


def dedupe_pages(pages: dict[int, str], stats: ChunkingStats) -> dict[int, str]:
    """Remove pages whose normalized text exactly duplicates an earlier page."""
    seen: dict[str, int] = {}
    result: dict[int, str] = {}
    for page_no in sorted(pages):
        normalized = normalize_text(pages[page_no]).strip()
        stats.pages_seen += 1
        if not normalized:
            continue
        key = normalized
        if key in seen:
            stats.pages_deduped += 1
            continue
        seen[key] = page_no
        result[page_no] = normalized
        if len(normalized) < 50:
            stats.short_pages.append(page_no)
    return result


# --------------------------------------------------------------------------- #
# Section (heading) detection — best-effort, never fabricated
# --------------------------------------------------------------------------- #
def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not (4 <= len(stripped) <= 80):
        return False
    if stripped.endswith((".", ",", ";", ":")):
        return False
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) < 3:
        return False
    # Mostly uppercase (with digits/punct allowed) ⇒ probable heading.
    return sum(1 for c in letters if c.isupper()) / len(letters) >= 0.7


def build_units(pages: dict[int, str]) -> list[Unit]:
    """Turn pages into paragraph units annotated with the nearest detected heading."""
    units: list[Unit] = []
    current_section: str | None = None
    for page_no in sorted(pages):
        page_text = pages[page_no]
        for raw_line in page_text.split("\n"):
            if _looks_like_heading(raw_line):
                current_section = " ".join(raw_line.split())[:80]
                break
        # Paragraphs are separated by blank lines.
        for block in page_text.split("\n\n"):
            para = " ".join(block.split())
            if not para:
                continue
            if _looks_like_heading(block.split("\n")[0]) and len(para) <= 80:
                # A paragraph that is itself a heading holds no answer content.
                current_section = para[:80]
                continue
            units.append(Unit(page=page_no, text=para, section=current_section))
    return units


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #
def _slice_long_unit(unit: Unit) -> list[Unit]:
    text = unit.text
    if len(text) <= MAX_CHARS:
        return [unit]
    slices: list[Unit] = []
    start = 0
    while start < len(text):
        end = min(start + TARGET_CHARS, len(text))
        if end < len(text):
            # Prefer the last sentence boundary within the window.
            window = text[start:end]
            for sep in (". ", "! ", "? ", "; "):
                pos = window.rfind(sep)
                if pos > TARGET_CHARS // 2:
                    end = start + pos + len(sep)
                    break
        slices.append(Unit(page=unit.page, text=text[start:end].strip(), section=unit.section))
        if end >= len(text):
            break
        start = max(end - OVERLAP_CHARS, start + 1)
    return [s for s in slices if s.text]


def chunk_units(units: list[Unit]) -> list[list[Unit]]:
    """Greedy paragraph packing with unit-level overlap (FR-11)."""
    expanded: list[Unit] = []
    for unit in units:
        expanded.extend(_slice_long_unit(unit))

    groups: list[list[Unit]] = []
    i = 0
    n = len(expanded)
    while i < n:
        group: list[Unit] = []
        length = 0
        j = i
        while j < n:
            candidate = expanded[j]
            addition = len(candidate.text) + 2
            if group and length + addition > MAX_CHARS:
                break
            group.append(candidate)
            length += addition
            j += 1
            if length >= TARGET_CHARS:
                break
        if not group:  # safety for a single oversize unit
            group = [expanded[i]]
            j = i + 1
        groups.append(group)
        if j >= n:
            break
        # Overlap: carry back trailing units worth ~OVERLAP_CHARS.
        back = 0
        carry = 0
        while j - 1 - back > i and carry < OVERLAP_CHARS:
            carry += len(expanded[j - 1 - back].text) + 2
            back += 1
        i = max(j - back, i + 1)
    return groups


def build_chunks(source: Source, pages: dict[int, str]) -> list[dict]:
    units = build_units(pages)
    chunks: list[dict] = []
    for group in chunk_units(units):
        text = "\n\n".join(u.text for u in group).strip()
        if not text:
            continue
        page_start = min(u.page for u in group)
        page_end = max(u.page for u in group)
        section = next((u.section for u in group if u.section), None)
        chunks.append(
            {
                "source_id": source.source_id,
                "source_title": source.title,
                "source_type": source.type,
                "is_sample": source.is_sample,
                "page_start": page_start,
                "page_end": page_end,
                "section": section,
                "text": text,
            }
        )
    return chunks


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def ingest(sources_dir: Path, index_dir: Path) -> dict:
    sources = load_manifest(sources_dir)
    warnings = warn_unlisted_files(sources_dir, sources)
    for name in warnings:
        print(f"WARNING: unlisted file ignored (FR-09): {name}")

    all_chunks: list[dict] = []
    stats = ChunkingStats()
    for source in sources:
        path = sources_dir / source.file
        if not path.exists():
            raise IngestionError(f"source file missing: {path}")
        text = normalize_text(path.read_text(encoding="utf-8"))
        pages = split_pages(text)
        pages = dedupe_pages(pages, stats)
        source_chunks = build_chunks(source, pages)
        all_chunks.extend(source_chunks)
        print(
            f"  source={source.source_id} pages={len(pages)} chunks={len(source_chunks)}"
        )

    # Assign global, stable-per-build chunk ids; drop degenerate empties.
    clean: list[dict] = []
    for i, chunk in enumerate(all_chunks):
        if not chunk["text"].strip():
            continue
        chunk["chunk_id"] = len(clean)
        clean.append(chunk)

    if not clean:
        raise IngestionError("ingestion produced zero chunks — check the sources")

    index_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = index_dir / "chunks.json"
    chunks_path.write_text(
        json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    tokenized = [tokenize(c["text"]) for c in clean]
    try:
        from rank_bm25 import BM25Okapi
    except ImportError as exc:  # pragma: no cover
        raise IngestionError(
            "rank-bm25 is required (pip install -r requirements.txt)"
        ) from exc
    bm25 = BM25Okapi(tokenized, k1=1.5, b=0.75)
    with (index_dir / "bm25.pkl").open("wb") as fh:
        pickle.dump(
            {
                "bm25": bm25,
                "tokenized": tokenized,
                "chunk_ids": [c["chunk_id"] for c in clean],
            },
            fh,
        )

    samples = sum(1 for c in clean if c["is_sample"])
    summary = {
        "chunks": len(clean),
        "duplicates_removed": stats.pages_deduped,
        "samples": samples,
        "pages_seen": stats.pages_seen,
        "short_pages": stats.short_pages,
    }
    print(
        f"chunks={summary['chunks']} duplicates_removed={summary['duplicates_removed']} "
        f"samples={summary['samples']} pages_seen={summary['pages_seen']}"
    )
    if stats.short_pages:
        print(f"NOTE: {len(stats.short_pages)} sparce pages (<50 chars): {stats.short_pages}")
    return summary


def main() -> int:
    sources_dir = ROOT / "data" / "sources"
    index_dir = ROOT / "index"
    try:
        ingest(sources_dir, index_dir)
    except IngestionError as exc:
        print(f"INGESTION ERROR: {exc}")
        return 1
    print(f"index written to {index_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
