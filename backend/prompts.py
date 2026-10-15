"""Prompt templates and format constants (DESIGN.md §6.6).

Responsibility: string building only — the system instruction, the numbered
passage block, and the sentinel/citation constants. No logic beyond string assembly.
"""
from __future__ import annotations

from typing import Iterable, Protocol


# --- Canonical format constants (must match DESIGN.md §6.6 / AGENTS.md §4) ---
SENTINEL = "NO_ANSWER_IN_KB:"
SOURCES_PREFIX = "Sources:"

SYSTEM_INSTRUCTION = """You are CampusMate AI, an assistant for Integral University students.
Answer ONLY from the numbered PASSAGES below using information they contain.

HARD RULES
1. Use only PASSAGES. Do not use prior knowledge about the university.
2. If the PASSAGES do not contain the information needed, reply with exactly:
   NO_ANSWER_IN_KB: <one polite sentence saying you could not find it>
   Do not guess fees, dates, deadlines, rules, or requirements.
3. Every factual sentence must end with a citation marker like [1] or [2][3]
   using ONLY passage numbers that were provided.
4. Quote figures (amounts, dates, page rules) exactly as written in the passage.
5. Keep the answer under 120 words. Plain text; no markdown headers; no lists
   longer than 3 items. If a passage is marked SAMPLE, mention that the
   information comes from a sample document.
6. End with a line exactly: Sources: [1], [2]   (the numbers you used)"""

# --- Canonical user-visible copy (DESIGN.md §13.1, §13.2 — verbatim) -------- #
REFUSAL_MESSAGE = (
    "I couldn't find reliable information about this in the campus knowledge base, "
    "so I don't want to guess — a wrong institutional detail could cost you time. "
    "Please check the official university website at iul.ac.in, or contact your "
    "department office / the Registrar's office to confirm."
)
REFUSAL_TIP = (
    "Tip: I currently know what's in my listed sources — open Sources to see them."
)
MODEL_REFUSAL_PREFIX = (
    "Your question touches my sources, but they don't fully answer it — "
)
ERROR_MESSAGE = "I couldn't complete that request. Please try again in a moment."


class HasPassageInfo(Protocol):
    """Minimal structural type the prompt builder needs from a retrieved passage."""

    number: int
    chunk: dict


def build_system_instruction() -> str:
    """Return the canonical system instruction (verbatim from DESIGN.md §6.6)."""
    return SYSTEM_INSTRUCTION


def build_passages_block(passages: Iterable[HasPassageInfo]) -> str:
    """Render the numbered PASSAGE block (used by the user message)."""
    lines: list[str] = []
    for p in passages:
        chunk = p.chunk
        sample = ", SAMPLE" if chunk.get("is_sample") else ""
        page = chunk.get("page_start")
        header = (
            f"PASSAGE [{p.number}] (source: {chunk.get('source_title')}, "
            f"pdf page {page}{sample}):"
        )
        lines.append(f"{header}\n{chunk.get('text', '').strip()}")
    return "\n\n".join(lines)


def build_user_message(passages: Iterable[HasPassageInfo], question: str) -> str:
    """Full user message: numbered passages followed by the question."""
    return f"{build_passages_block(passages)}\n\nQUESTION: {question.strip()}"
