"""Top-k passage viewer for a query — calibration/debugging tool (Phase 2/6).

Usage: python scripts/search_cli.py "hostel fee for single occupancy"
Prints score, source, page, and a 100-char preview per passage.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

from backend.retrieval import KnowledgeBaseError, RetrievalIndex  # noqa: E402
from backend.textutils import text_preview  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('usage: python scripts/search_cli.py "your question"')
        return 2
    question = " ".join(argv[1:])
    index_dir = ROOT / "index"
    try:
        index = RetrievalIndex.load(index_dir)
    except KnowledgeBaseError as exc:
        print(f"ERROR: {exc}")
        return 1

    result = index.search(question, k=5)
    print(f"query: {question!r}")
    print(f"top_score: {result.top_score:.4f}  (chunks in index: {index.chunk_count})")
    print("-" * 72)
    for p in result.passages:
        c = p.chunk
        span = (
            f"p.{c['page_start']}"
            if c["page_start"] == c["page_end"]
            else f"p.{c['page_start']}-{c['page_end']}"
        )
        sample = " [SAMPLE]" if c["is_sample"] else ""
        print(f"[{p.number}] score={p.score:8.4f}  {c['source_id']} {span}{sample}")
        print(f"     {text_preview(c['text'], 100)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
