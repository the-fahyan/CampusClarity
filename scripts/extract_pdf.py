"""PDF → extracted text utility (build-time only, not on the runtime path).

Usage: python scripts/extract_pdf.py <input.pdf> <output.txt>

Emits the page markers consumed by `scripts/ingest.py`:
    ===== PAGE n =====
Uses pypdf; writes UTF-8; reconfigures stdout so Unicode corpus text is safe on
Windows consoles (NFR-06). This is a one-time helper — the main corpus for this
project was already extracted with this format.
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - platform dependent
        pass


def extract(pdf_path: Path, out_path: Path) -> int:
    """Extract text page-by-page; return page count."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "pypdf is required for extraction (pip install -r requirements.txt)"
        ) from exc

    reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        parts.append(f"===== PAGE {i} =====\n{text}\n")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts), encoding="utf-8")
    return len(reader.pages)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python scripts/extract_pdf.py <input.pdf> <output.txt>")
        return 2
    pdf_path = Path(argv[1])
    out_path = Path(argv[2])
    if not pdf_path.exists():
        print(f"error: input not found: {pdf_path}")
        return 1
    pages = extract(pdf_path, out_path)
    print(f"extracted {pages} pages -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
