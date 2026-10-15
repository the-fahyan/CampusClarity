"""Verify the Gemini API key and model IDs with one real call (Phase 3 smoke).

Usage: python scripts/smoke_gemma.py
Never prints the key. Reports which configured model actually responds.
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

from backend.config import PLACEHOLDER_KEY, Settings  # noqa: E402
from backend.generator import Generator, UpstreamError  # noqa: E402
from backend.retrieval import Passage  # noqa: E402


def main() -> int:
    settings = Settings(MOCK_LLM=False)  # type: ignore[call-arg]
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == PLACEHOLDER_KEY:
        print("ERROR: GEMINI_API_KEY is not set (put a real key in .env). No key is fabricated.")
        return 1

    passage = Passage(
        number=1,
        chunk={
            "chunk_id": 0,
            "source_id": "smoke",
            "source_title": "Smoke Test",
            "source_type": "sample",
            "is_sample": True,
            "page_start": 1,
            "page_end": 1,
            "section": None,
            "text": "The campus library opens at 8:00 a.m. on working days.",
        },
        score=1.0,
    )
    gen = Generator(settings)
    models = [settings.GEMMA_MODEL_ID, settings.GEMMA_FALLBACK_MODEL_ID]
    for model in models:
        try:
            raw = gen._call(  # noqa: SLF001 - intentional single-shot verification
                model, "PASSAGE [1] (source: Smoke Test, pdf page 1, SAMPLE):\n"
                "The campus library opens at 8:00 a.m. on working days.\n\n"
                "QUESTION: When does the library open?"
            )
            print(f"key OK, model {model} answered:\n  {raw[:180]}")
            print(f"VERIFIED model id: {model}")
            return 0
        except UpstreamError as exc:
            print(f"model {model} failed: {exc}")
    print("FAILED: no configured Gemma model responded. Verify IDs against AI Studio.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
