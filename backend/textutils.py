"""Shared text normalization and tokenization.

Responsibility: single source of truth for (a) corpus normalization (FR-10) and
(b) the BM25 tokenizer used by BOTH ingestion and runtime retrieval (DESIGN.md §6.4).
Keeping one implementation guarantees an identical token space at index and query time.
"""
from __future__ import annotations

import re
import unicodedata

# Ligatures explicitly named by FR-10/§6.3.
_LIGATURES = {
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb00": "ff",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}

# Control chars except tab/newline; used to strip PDF extraction noise (FR-10).
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Stray backtick (or acute accents) immediately before a digit → rupee sign (FR-10).
_BACKTICK_BEFORE_DIGIT = re.compile(r"[`\u00b4\u2018\u2019]\s?(?=\d)")

_BLANK_RUN = re.compile(r"\n{3,}")

# Numeric run possibly containing Indian-digit-group commas and a decimal part.
_NUMBER_RUN = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORD = re.compile(r"[a-z0-9]+")

PAGE_MARKER = re.compile(r"^=====\s*PAGE\s+(\d+)\s*=====\s*$", re.MULTILINE)


def normalize_text(text: str) -> str:
    """Normalize extracted corpus text (FR-10). Pure function, unit-tested."""
    if not text:
        return ""
    # Unicode NFC first, then explicit ligature replacement for PDF artifacts.
    text = unicodedata.normalize("NFC", text)
    for lig, repl in _LIGATURES.items():
        text = text.replace(lig, repl)
    text = _CONTROL_CHARS.sub("", text)
    # Normalize Windows/old-Mac line endings.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _BACKTICK_BEFORE_DIGIT.sub("\u20b9", text)  # ₹
    # Collapse runs of >2 blank lines to a single blank line.
    text = _BLANK_RUN.sub("\n\n", text)
    return text


def tokenize(text: str) -> list[str]:
    """Tokenize text for BM25 (DESIGN.md §6.4).

    Rules: lowercase + NFKC first; keep numeric runs with commas/periods but ALSO
    emit a comma-stripped variant (`1,05,000` → `1,05,000` and `105000`);
    alphanumeric word tokens of length ≥ 2.
    """
    if not text:
        return []
    text = unicodedata.normalize("NFKC", text).lower()

    tokens: list[str] = []
    for match in _NUMBER_RUN.finditer(text):
        raw = match.group(0)
        tokens.append(raw)
        stripped = raw.replace(",", "")
        if stripped != raw:
            tokens.append(stripped)
        # Integer core without a trailing decimal point artifact.
        if "." in stripped:
            head = stripped.split(".", 1)[0]
            if head and head != stripped:
                tokens.append(head)

    for match in _WORD.finditer(text):
        tok = match.group(0)
        if len(tok) >= 2:
            tokens.append(tok)
            # Light plural normalization (no full stemmer): "siblings"→"sibling",
            # "fees"→"fee", "rooms"→"room" — improves recall on natural phrasing
            # without pulling in an extra dependency (AGENTS §6).
            if len(tok) >= 4 and tok.endswith("s") and not tok.endswith("ss"):
                tokens.append(tok[:-1])

    return tokens


def text_preview(text: str, length: int = 150) -> str:
    """Collapse whitespace and truncate for snippets/previews."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= length:
        return collapsed
    return collapsed[: length - 1].rstrip() + "\u2026"
