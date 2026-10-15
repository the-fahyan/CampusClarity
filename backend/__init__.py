"""CampusMate AI backend package.

Modules:
    config     — environment settings + fail-fast validation (DESIGN.md §6.2)
    schemas    — Pydantic request/response/error contracts (§5, §8)
    textutils  — shared normalization + tokenization (used by ingest and retrieval)
    retrieval  — index load, BM25 search, threshold gate (§6.4)
    prompts    — prompt templates + sentinel/citation constants (§6.6)
    generator  — Gemini REST call, retries/fallback, MOCK_LLM, parsing (§6.5)
    ratelimit  — in-memory fixed-window per-IP limiter (§6.7)
    service    — the ask-pipeline orchestration (§6.1)
    main       — FastAPI app, routes, middleware, static mount, handlers (§6.8)

The package docstring lists one-line responsibilities matching DESIGN.md §1.2.
"""
