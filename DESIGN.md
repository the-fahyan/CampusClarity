# CampusMate AI — Design and Technical Architecture Document

| Field | Value |
|---|---|
| Product | CampusMate AI — *Your Campus. Your Answers.* |
| Version | 1.0 |
| Role | Defines **how** the application is structured and implemented. Companion to `PRD.md` (what), `AGENTS.md` (rules), `BUILD_PLAN.md` (order). |
| Last updated | 2026-10-16 |

> **Terminology lock:** endpoint names, status values, file paths, env vars, and data models defined here are **canonical**. The other three documents must use them verbatim. Changing any canonical term requires updating all four documents in the same change (`AGENTS.md` §Conflicts).

---

## 1. System architecture

### 1.1 High-level diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Browser (frontend/index.html + styles.css + app.js — no build step)   │
│   chat UI · citation chips · sources drawer · states: idle/load/ans/rf │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ HTTP (same origin, JSON)
┌──────────────────────────────▼──────────────────────────────────────────┐
│  FastAPI app (backend/main.py)                                          │
│   routes: POST /api/ask · GET /api/health · GET /api/sources            │
│   middleware: request_id · rate limit (ratelimit.py) · error handler    │
│        │                                                                │
│        ▼ backend/service.py  (orchestration pipeline)                   │
│   1) retrieval.py   → BM25 top-k passages + top score                   │
│   2) gate           → score < BM25_MIN_SCORE ?  ──yes──▶ refusal (no LLM)│
│   3) generator.py   → Gemma via Gemini API (prompt in prompts.py)       │
│   4) parse/validate → sentinel? citations ⊆ retrieved ?                 │
│   5) respond        → AskResponse (schemas.py)                          │
└───────────────┬─────────────────────────────┬───────────────────────────┘
                │                             │
   ┌────────────▼──────────┐     ┌────────────▼─────────────────────────┐
   │ Generated index (disk)│     │ Google AI Studio — Gemini API        │
   │  index/chunks.json    │     │ model: gemma-3-27b-it (fallback      │
   │  index/bm25.pkl       │     │ gemma-3-12b-it) · MOCK_LLM=true →    │
   │  built by scripts/    │     │ canned responses (no network)        │
   │  ingest.py from data/ │     └──────────────────────────────────────┘
   │  sources/manifest     │
   └───────────────────────┘
```

### 1.2 Component responsibilities

| Component | File(s) | Responsibility | Must NOT do |
|---|---|---|---|
| Frontend | `frontend/index.html`, `styles.css`, `app.js` | Rendering, input validation, state display, citation chips, sources drawer, disclaimer, a11y | Any retrieval/prompt logic; storing secrets; deciding truth of answers |
| API layer | `backend/main.py` | Routes, request_id, rate limit, exception→HTTP mapping, static hosting | Business logic (delegates to `service.py`) |
| Orchestration | `backend/service.py` | The ask-pipeline: retrieve → gate → generate → validate → build `AskResponse` | HTTP concerns; direct model/HTTP calls (delegates) |
| Retrieval | `backend/retrieval.py` | Load index, BM25 search, threshold decision, passage selection | Generation; file ingestion |
| Generation | `backend/generator.py` | Gemini REST call via `httpx`, retries/fallback, MOCK_LLM, response parsing | Retrieval; deciding status (returns raw parsed result to service) |
| Prompts | `backend/prompts.py` | Prompt templates + sentinel/citation format constants | Logic beyond string building |
| Schemas | `backend/schemas.py` | Pydantic request/response/error models — **runtime contract source of truth** | Side effects |
| Config | `backend/config.py` | Env loading (`.env` via pydantic-settings), fail-fast validation | Hardcoded secrets/defaults that mask misconfig |
| Rate limiter | `backend/ratelimit.py` | In-memory fixed-window per-IP counter | Persistence |
| Ingestion | `scripts/ingest.py` | Validate manifest → read → normalize → dedupe → chunk → write index | Network calls to LLM |
| PDF utility | `scripts/extract_pdf.py` | One-time PDF → UTF-8 text helper (pypdf) | Part of runtime path |
| Smoke test | `scripts/smoke_gemma.py` | Verify API key + model id with one real call | Used in CI/tests |
| Battery | `scripts/run_battery.py` | Run `tests/battery.json` through the service layer, print pass/fail report | Modifying the index |
| CLI search | `scripts/search_cli.py` | Print top-k passages for a query (debugging/calibration) | — |

---

## 2. Key architectural decisions (ADR-style)

> Every significant decision: **decision → why → trade-offs**. IDs referenced by other documents (D-1…D-10).

### D-1 — Retrieval: BM25 lexical search (`rank_bm25`), no vector store

- **Why:** Campus queries are short and keyword-heavy ("hostel fee", "IUET date"), which BM25 handles excellently; zero model downloads, zero embedding API cost, millisecond latency, fully open-source (Apache-2.0 family — verify), deterministic results, trivially testable.
- **Trade-offs:** No semantic/paraphrase matching ("Is staying on campus expensive?" may miss "hostel fee"). Mitigation: synonym/light query expansion is a post-MVP hook (§16); battery questions use natural phrasing to catch failures. No vector DB dependency to maintain.

### D-2 — LLM: Gemma 3 (`gemma-3-27b-it`) via Google AI Studio Gemini API, fallback `gemma-3-12b-it`

- **Why:** Hackathon requires Gemma; AI Studio offers a free tier with Gemma over a stable REST API — no GPU, no weights hosting. Open-weight model satisfies the open-source-AI criterion (documented honestly under Gemma Terms of Use — `PRD` NFR-07).
- **Trade-offs:** Network dependency, free-tier rate limits, model id availability can change → **model IDs must be verified at Phase 3 against the AI Studio model list** (documented, not assumed); fallback chain + `MOCK_LLM` keep development unblocked. Self-hosting via Ollama (`gemma-3-4b-it`, ~4 GB RAM) documented as an alternative in README — not in MVP critical path.

### D-3 — Two-layer abstention (retrieval gate first, model sentinel second)

- **Why:** The determinable "I don't know" (score below `BM25_MIN_SCORE`) costs zero tokens and **cannot** hallucinate; the sentinel catches the residual case where passages are topically close but insufficient. Judges test refusal reliability; prompt-only refusal is the weakest option.
- **Trade-offs:** Threshold is corpus-dependent and must be calibrated (Phase 6 via `scripts/search_cli.py` + battery). Wrong threshold ⇒ false refusals (usable but unhelpful) or false answers (unacceptable) — calibration record kept in README.

### D-4 — Stateless API (no conversation memory, no database)

- **Why:** MVP queries are standalone factual lookups; statelessness removes sessions/auth/storage/PII entirely — a security and maintainability win, and simplifies horizontal scaling.
- **Trade-offs:** Follow-ups ("what about the second one?") lose context. Mitigation: frontend keeps display history and users restate context; multi-turn is a post-MVP item (`PRD` §8.3).

### D-5 — Static frontend (hand-written HTML/CSS/JS), served by FastAPI — no Node/bundler

- **Why:** One language less, no `node_modules`, instant load, no build-step failures, and the whole app runs with Python + a browser. Chat UI complexity here is modest (one page, fetch-based).
- **Trade-offs:** No component framework/hot reload; state management is manual (a tiny render function per status). Acceptable for a single-page app; `AGENTS.md` enforces plain-vanilla patterns.

### D-6 — FastAPI (vs. Flask/Django)

- **Why:** Pydantic request/response models **enforce the API contract at runtime** (contract tests derive from it), automatic validation (422s), OpenAPI docs at `/docs` for free, async-capable, MIT licensed, first-class `TestClient`.
- **Trade-offs:** Slightly more ceremony than Flask; irrelevant at this scale.

### D-7 — Index as generated artifacts (`index/chunks.json` + `index/bm25.pkl`), sources as source of truth

- **Why:** Reproducible builds — index rebuilds from `data/sources/` in seconds; git stays lean (artifacts gitignored); sources folder doubles as the auditable record of what the assistant knows.
- **Trade-offs:** Requires an explicit build step (documented; health endpoint reports `index_ready`). Pickle is Python-specific — acceptable because producer/consumer are the same codebase; a JSON sidecar keeps chunks human-inspectable.

### D-8 — Chunking: ~600 chars, 100 overlap, paragraph-boundary preference, PDF page spans

- **Why:** Prospectus prose runs in long numbered paragraphs; 600 chars keeps fee/policy items intact while staying within one topic. Overlap prevents boundary loss. Page spans enable page-level citations.
- **Trade-offs:** Very large fee tables may exceed 600 chars → bounded to ≤900 with table header injected into chunk text (normalization step, §10.4).

### D-9 — Citations derived from chunk IDs (mapped server-side), never trusted from the model verbatim

- **Why:** Model outputs `[1] [3]` against numbered passages; the backend maps IDs → chunk metadata and **drops anything not in the retrieved set** (FR-04). Grounded by construction — impossible to cite a non-retrieved page.
- **Trade-offs:** Model may omit citations for a true answer → then status downgrades to `model_refusal` (honesty preferred over a bare answer).

### D-10 — Transport: raw REST via `httpx` (no Google SDK)

- **Why:** One endpoint, one header (`x-goog-api-key`) — an SDK adds version churn and surface area. `httpx` gives timeouts, retry control, and easy transport mocking for tests.
- **Trade-offs:** We must maintain the request shape ourselves (small, documented in §12.3); SDK conveniences (streaming, safety settings) unused in MVP.

---

## 3. Technology stack

| Layer | Choice | Justification | License (verify before release) |
|---|---|---|---|
| Language | Python 3.12 | Matches dev environment; async support; typing | PSF |
| Web framework | FastAPI ≥0.115 | Contract-enforced schemas, validation, `/docs`, TestClient | MIT ✓ |
| Server | uvicorn ≥0.32 | Standard ASGI pairing | BSD-3 ✓ |
| Validation/config | pydantic ≥2.9, pydantic-settings ≥2.6 | Contract models + `.env` loading, fail-fast | MIT ✓ |
| Retrieval | rank-bm25 ≥0.2.2 | Pure-Python BM25, no downloads | Apache-2.0 *(verify: `pip show`)* |
| LLM transport | httpx ≥0.27 | Timeouts, retries, mockable transport | BSD-3 ✓ |
| PDF utility (build-time only) | pypdf ≥5 | Text extraction for `extract_pdf.py` | BSD-3 ✓ |
| Tests | pytest ≥8 | De-facto standard | MIT ✓ |
| Model | Gemma 3 (`gemma-3-27b-it`, fallback `gemma-3-12b-it`) via Gemini API | Open-weight Gemma; free-tier API; hackathon requirement | **Gemma Terms of Use (open-weight, not OSI)** — documented, not mislabeled as OSS |
| Frontend | Vanilla HTML/CSS/JS | No toolchain (D-5) | project MIT |
| Packaging | `requirements.txt` (bounded ranges, not unpinned-latest) | Reproducible, security-reviewable | — |

**Rejected alternatives:** vector DBs/FAISS (overkill — D-1), Flask (no contract models — D-6), Streamlit (framework-look, weak citation UX), Node/React (toolchain cost — D-5), Google GenAI SDK (D-10).

---

## 4. Project structure (canonical — additions require doc updates)

```
project-root/
├── PRD.md                    # what (requirements, IDs)
├── DESIGN.md                 # how (this document)
├── AGENTS.md                 # agent rules
├── BUILD_PLAN.md             # phased order + traceability matrix
├── README.md                 # quickstart, licenses, approved-source process
├── LICENSE                   # MIT
├── .env.example              # placeholder config (never real secrets)
├── .gitignore                # .env, index/, __pycache__, venv, caches
├── requirements.txt
├── docs/
│   └── DECISIONS.md          # ambiguity/decision log (seeded in Phase 0)
├── data/
│   └── sources/
│       ├── manifest.json     # source of truth: what the KB contains
│       └── prospectus.txt    # extracted text of the team-provided PDF
│       └── sample-*.txt      # clearly labelled sample docs (if needed)
├── index/                    # GENERATED, gitignored
│   ├── chunks.json           # human-readable chunk store
│   └── bm25.pkl              # pickled BM25 index
├── scripts/
│   ├── extract_pdf.py        # PDF → text (utility)
│   ├── ingest.py             # validate → normalize → dedupe → chunk → index
│   ├── search_cli.py         # top-k passages for a query (calibration)
│   ├── smoke_gemma.py        # one real API call to verify key/model
│   └── run_battery.py        # execute tests/battery.json, print report
├── backend/
│   ├── __init__.py
│   ├── main.py               # app, routes, middleware, static mount, handlers
│   ├── config.py             # Settings (env), startup validation
│   ├── schemas.py            # AskRequest/AskResponse/Citation/... contracts
│   ├── service.py            # ask-pipeline orchestration
│   ├── retrieval.py          # index load, BM25 search, threshold gate
│   ├── generator.py          # Gemini call, retries/fallback, MOCK_LLM, parsing
│   ├── prompts.py            # templates + SENTINEL/CITATION format constants
│   └── ratelimit.py          # fixed-window per-IP limiter
├── frontend/
│   ├── index.html            # single page
│   ├── styles.css            # design tokens + components
│   └── app.js                # fetch, state machine, rendering
└── tests/
    ├── conftest.py           # fixtures: tmp index, mock settings, TestClient
    ├── test_ingest.py
    ├── test_retrieval.py
    ├── test_generator.py
    ├── test_api.py
    ├── battery.json          # machine-readable QA battery
    └── manual_ui_checklist.md
```

---

## 5. Data models

### 5.1 Source manifest — `data/sources/manifest.json`

```json
{
  "sources": [
    {
      "source_id": "prospectus",
      "title": "Integral University Prospectus",
      "file": "prospectus.txt",
      "type": "prospectus",
      "verified": true,
      "is_sample": false,
      "notes": "Text extracted from the team-provided official PDF (145 pages). Edition year TBC — do not state a year until confirmed.",
      "added_on": "2026-10-16"
    }
  ]
}
```

Field rules: `source_id` unique kebab-case; `type ∈ {prospectus, handbook, notice, syllabus, regulation, sample}`; `verified` = team confirmed official origin; `is_sample` must equal `file.startswith("sample-")` (validated by ingest, FR-12).

### 5.2 Chunk (`index/chunks.json`)

```json
{
  "chunk_id": 12,
  "source_id": "prospectus",
  "source_title": "Integral University Prospectus",
  "source_type": "prospectus",
  "is_sample": false,
  "page_start": 45,
  "page_end": 45,
  "section": "Important Information",
  "text": "Single Occupancy Room ₹1,05,000/- p.a. ..."
}
```

`chunk_id` is a global integer (0-based, stable per index build). `section` is best-effort (nearest detected heading, else `null`) — display-only, never fabricated.

### 5.3 API request — `AskRequest`

```json
{ "question": "What is the hostel fee for a single occupancy room?" }
```

Constraints: trimmed non-empty, length 3–500 (`FR-01/02`).

### 5.4 API response — `AskResponse`

```json
{
  "request_id": "8f2a1c9e-7d3b-4a01-9e2b-5c6d7e8f9a0b",
  "status": "answered",
  "answer": "A single occupancy hostel room costs ₹1,05,000 per annum, excluding optional AC charges [1].",
  "citations": [
    {
      "citation_id": "c1",
      "chunk_id": 12,
      "source_id": "prospectus",
      "source_title": "Integral University Prospectus",
      "page": 45,
      "snippet": "Hostel & Mess Fee (If the facility is availed) Single Occupancy Room ₹1,05,000/- p.a. ...",
      "score": 11.42,
      "is_sample": false
    }
  ],
  "retrieval": { "top_score": 11.42, "threshold": 10.5, "passages_considered": 5 },
  "model": { "name": "gemma-3-27b-it", "provider": "Google AI Studio (Gemini API)", "mode": "live" },
  "latency_ms": 2310
}
```

**Status enum (canonical):** `answered` · `insufficient_knowledge` · `model_refusal` · `upstream_error`.

**Rules:** refusal statuses ⇒ `citations: []`, `answer` contains no institutional facts (canonical copy, §13.2). `upstream_error` is returned with HTTP 502 (body still schema-shaped). Every response carries `request_id`.

### 5.5 Health — `GET /api/health` → `200`

```json
{ "status": "ok", "index_ready": true, "chunk_count": 412, "source_count": 1,
  "llm_mode": "live", "model": "gemma-3-27b-it", "version": "1.0.0" }
```

`status: "degraded"` when index missing or `llm_mode: "mock"`. UI maps: green=ok, amber=degraded, red=unreachable.

### 5.6 Sources — `GET /api/sources` → `200`

```json
{ "sources": [ { "source_id": "prospectus", "title": "Integral University Prospectus",
    "type": "prospectus", "verified": true, "is_sample": false,
    "file": "prospectus.txt", "chunk_count": 412, "pages": 145 } ],
  "how_to_add": "Add an approved .txt file to data/sources/, register it in manifest.json, run python scripts/ingest.py, then re-run scripts/run_battery.py." }
```

### 5.7 Error body (429 / 500 / 502)

```json
{ "request_id": "…", "status": "upstream_error",
  "message": "The assistant could not reach the language model. Please try again." }
```

Messages are **generic** — internals live only in server logs (NFR-03).

---

## 6. Backend architecture

### 6.1 The ask pipeline (`backend/service.py`)

```python
async def handle_ask(req: AskRequest) -> AskResponse:
    passages = retrieval.search(req.question, k=settings.BM25_TOP_K)
    if passages.top_score < settings.BM25_MIN_SCORE:            # Layer 1 — FR-05
        return refusal("insufficient_knowledge", passages)
    raw = generator.generate(question, passages)                # retries/fallback — D-10
    if raw.starts_with_sentinel:                                # Layer 2 — FR-06
        return refusal("model_refusal", passages)
    citations = validate_citations(raw.cited_indices, passages) # FR-04 — D-9
    if raw.has_factual_content and not citations:
        return refusal("model_refusal", passages)
    return answered(raw.answer_with_inline_markers, citations, passages)
```

*(Exact signatures in code; this is the authoritative control flow. Any deviation requires updating §6.1 and the traceability matrix.)*

### 6.2 Configuration (`backend/config.py`)

| Env var | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — (required unless mock) | API key; startup fails fast with named error if missing and `MOCK_LLM` false (FR-18) |
| `GEMMA_MODEL_ID` | `gemma-3-27b-it` | Primary model — **verify availability in Phase 3** |
| `GEMMA_FALLBACK_MODEL_ID` | `gemma-3-12b-it` | Fallback on 429/5xx/timeout (NFR-02) |
| `BM25_MIN_SCORE` | `10.5` | Abstention layer-1 threshold — calibrated in Phase 6 (`docs/DECISIONS.md`); original placeholder was `4.0` |
| `BM25_TOP_K` | `5` | Passages into prompt |
| `RATE_LIMIT_PER_MINUTE` | `60` | Per-IP window (FR-19) |
| `MOCK_LLM` | `false` | Canned deterministic responses (FR-21) |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | Bind address |
| `LOG_LEVEL` | `INFO` | `DEBUG` logs truncated question (NFR-04) |

`.env.example` documents all of these with placeholders. `requirements.txt` pins bounded ranges.

### 6.3 Ingestion pipeline (`scripts/ingest.py`)

```
manifest.json ──validate──▶ for each listed file (unlisted files: warn & skip, FR-09)
   │  • file exists, UTF-8 readable
   │  • is_sample ⇔ sample- prefix (FR-12)
   ▼
read text ──normalize (FR-10)──▶ dedupe ──chunk (FR-11)──▶ annotate ──▶ index/chunks.json
   │  • strip control chars; NFC normalize                       │
   │  • ligatures: ﬁ ﬂ ﬀ → fi fl ff                             │  per chunk:
   │  • "` 1,05,000" → "₹1,05,000" (backtick before digit)       │  chunk_id, source_*, page_start/end,
   │  • collapse >2 blank lines                                  │  section (best-effort heading), is_sample
   ▼                                                              ▼
dedupe: identical normalized page-text → keep first, log removed count   BM25 tokenize → pickle ──▶ index/bm25.pkl
```

Page detection: split on the `===== PAGE n =====` markers emitted by `extract_pdf.py` (raw extraction already verified for the provided prospectus).

### 6.4 Retrieval (`backend/retrieval.py`)

- Load `chunks.json` + `bm25.pkl` once at startup (startup fails with clear error if missing → health `degraded`).
- Tokenizer (index **and** queries, identical):
  1. lowercase, Unicode NFKC
  2. keep number runs with commas/periods but **also** emit a comma-stripped variant (`1,05,000` → tokens `1,05,000` **and** `105000`) — matches "105000" queries
  3. alphanumeric word tokens ≥ 2 chars
- BM25 (`k1=1.5`, `b=0.75` defaults), return top-k as `Passage(chunk, score)`.
- Gate: `top_score < BM25_MIN_SCORE` → refusal *without model call* (FR-05).
- `search_cli.py` prints top-5 with scores for threshold calibration.

### 6.5 Generation (`backend/generator.py`)

- **Request:** `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`, header `x-goog-api-key`, JSON: `contents[{role:"user", parts:[{text}]}]`, `generationConfig: {temperature: 0.2, maxOutputTokens: 1024, topP: 0.95}`.
- **Timeouts:** 20 s total. **Retries:** 1× retry with 500 ms backoff on 429/5xx/timeout; then switch to `GEMMA_FALLBACK_MODEL_ID` once; persistent failure → raise `UpstreamError` → HTTP 502 (`NFR-02`).
- **MOCK_LLM=true:** no network; deterministic canned answers keyed by simple keyword rules (e.g., question contains "hostel fee" → canned cited answer; otherwise sentinel refusal). Health reports `llm_mode: "mock"`; UI dot amber.

### 6.6 Prompt specification (`backend/prompts.py`)

**System instruction (template, exact behavior enforced by tests):**

```
You are CampusMate AI, an assistant for Integral University students.
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
6. End with a line exactly: Sources: [1], [2]   (the numbers you used)
```

**User message:** `PASSAGE [n] (source: {title}, pdf page {p}{, SAMPLE}): {text}` repeated for top-k, then `QUESTION: {question}`.

**Parse rules (`generator.py`):**
1. Sentiment of rule 2: answer starts with `NO_ANSWER_IN_KB:` → refusal (`FR-06`), strip sentinel for optional display.
2. Trailing `Sources: [...]` line parsed → integer indices.
3. Citations = indices **∩ retrieved set**; missing/invalid dropped (`FR-04`); duplicate pages deduped.
4. Factual content with zero surviving citations ⇒ downgrade to `model_refusal` (D-9).
5. Parse failures (no sources line, malformed) ⇒ `model_refusal` — never a bare ungrounded answer.

### 6.7 Rate limiting (`backend/ratelimit.py`)

Fixed window, in-memory dict `{ip: (window_start, count)}`; > `RATE_LIMIT_PER_MINUTE` ⇒ HTTP 429 error body (§5.7). Window cleanup on access. **Known limitation (documented):** per-process memory — ineffective across multiple workers/instances (see `PRD` §8.4).

### 6.8 Error taxonomy (`backend/main.py`)

| Condition | HTTP | `status` | Client message |
|---|---|---|---|
| Validation (length/empty/type) | 422 | `validation_error` | Field-level detail (FastAPI default shape + `request_id`) |
| Rate limit | 429 | `rate_limited` | "Too many requests — please wait a moment." |
| Index missing at request time | 503 | `kb_unavailable` | "Knowledge base is being built. Run python scripts/ingest.py." |
| Upstream exhausted after retry+fallback | 502 | `upstream_error` | "The assistant could not reach the language model. Please try again." |
| Unexpected exception | 500 | `internal_error` | "Something went wrong. Please try again." + `request_id` |

All mapped via exception handlers; stack traces logged server-side only.

---

## 7. Citation behavior (spec)

1. **Source of truth:** retrieved chunk metadata — model-provided indices are only ever a *selection* of retrieved passages (D-9).
2. **Chip display (answered):** `📄 {source_title} · p. {page}` + hover/focus popover with snippet (~150 chars) + `score`; `SAMPLE` badge if `is_sample`.
3. **Refusals:** `citations: []` — UI renders none (never pad a refusal with "related" passages).
4. **Page semantics:** 1-based **PDF page** (A-03). The UI popover adds "(PDF page)" when a printed folio is also known; MVP shows PDF page only — no invented folio mapping.
5. **Validation invariant:** `∀ c ∈ response.citations : c.chunk_id ∈ retrieved_chunk_ids` — enforced server-side; asserted by tests (SC-03).

---

## 8. API contracts (canonical)

| Method | Path | Purpose | Success | Errors |
|---|---|---|---|---|
| POST | `/api/ask` | Ask a question | 200 `AskResponse` | 422, 429, 500, 502, 503 |
| GET | `/api/health` | Liveness + readiness | 200 Health model | 500 |
| GET | `/api/sources` | KB inventory | 200 Sources model | 500 |
| GET | `/` `/assets…` | Static frontend | 200 HTML/CSS/JS | 404 |

- **Same-origin** (FastAPI serves `frontend/`) ⇒ no CORS middleware by default; if dev split-hosting is ever used, CORS stays deny-by-default with an explicit origin allowlist.
- **Versioning:** `/api` unversioned in v1; breaking changes ⇒ `/api/v2` (both mounted).
- **OpenAPI:** auto at `/docs` (dev convenience; harmless in prototype).
- Contract source of truth: `backend/schemas.py` (Pydantic) ≡ this section ≡ `PRD` FRs.

---

## 9. Application flows

### 9.1 Answered flow

```
User → app.js validate(3–500) → POST /api/ask → [request_id, rate check]
  → service: BM25 top-5 (11.42 ≥ 4.0) → prompt+passages → Gemma (2.1 s)
  → parse Sources [1] → citations validated → 200 {answered}
  → UI: bubble + chips + "grounded" badge, aria-live announce
```

### 9.2 Refusal flow (layer 1)

```
User → POST → BM25 top-1 = 1.7 < 4.0 → refusal("insufficient_knowledge")
  → 200 {citations: []} → UI: amber "Not covered in my sources" + next step
  (model never called: 0 tokens, deterministic — FR-05)
```

### 9.3 Upstream failure flow

```
User → POST → gate OK → Gemma 429 → retry 500 ms → 429 → fallback model → timeout
  → UpstreamError → 502 {upstream_error, request_id} → UI error + Retry
  (health dot may go amber if fallback persists — NFR-02)
```

---

## 10. Frontend architecture

### 10.1 Page structure (single page)

```
<header>  brand "CampusMate AI" · tagline · status dot · [Sources] button
<main>
  <section id="message-log" role="log" aria-live="polite">   ← messages
      [empty state: welcome + example chips]
      [user bubble] [assistant bubble + citation chips]
      [typing indicator] [error card + Retry]
  </section>
  <form id="composer">  <textarea>  [Send] </form>          ← sticky bottom
</main>
<aside id="sources-drawer" hidden>  manifest list + how-to-add note </aside>
<footer> disclaimer (FR-23) </footer>
```

### 10.2 State machine (`app.js`)

`idle → sending → (answered | refused | error) → idle` — one `render(state)` function; statuses map to UI variants:

| `status` | Badge | Bubble style | Extras |
|---|---|---|---|
| `answered` | "Grounded answer" (green) | white / brand left-border | citation chips below text |
| `insufficient_knowledge` / `model_refusal` | "Not in my sources" (amber) | amber tint, distinct icon | canonical refusal copy + next step; **no chips** |
| `upstream_error` / network fail | "Error" (red) | red tint | message + **Retry** button (re-sends last question) |
| sending | — | — | typing indicator (3 dots), composer guarded |
| initial | — | — | welcome text + ≥4 example chips (FR-14) |

**Other behaviors:** auto-scroll to newest (respect `prefers-reduced-motion`); Enter sends / Shift+Enter newline; chips fill composer without sending; health dot refresh every 60 s + on error; copy-answer button on assistant bubbles; no user data persisted (reload clears).

### 10.3 Design system (`styles.css` tokens — canonical)

**Color tokens**

| Token | Hex | Use |
|---|---|---|
| `--brand-600` | `#4F46E5` | primary actions, user bubble, focus ring |
| `--brand-700` | `#4338CA` | hover/pressed |
| `--bg` | `#F8FAFC` | page background |
| `--surface` | `#FFFFFF` | cards, composer, assistant bubble |
| `--text` | `#0F172A` | primary text (AA on surface ✓) |
| `--text-muted` | `#64748B` | meta (≥14 px only) |
| `--success-700` | `#15803D` | "grounded" badge text |
| `--success-bg` | `#F0FDF4` | grounded badge bg |
| `--warn-700` | `#B45309` | refusal badge text |
| `--warn-bg` | `#FFFBEB` | refusal bubble/badge bg |
| `--danger-700` | `#B91C1C` | error text |
| `--danger-bg` | `#FEF2F2` | error card bg |
| `--border` | `#E2E8F0` | hairlines |

**Type:** system stack `-apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif` (no external font CDN — offline-safe, no third-party requests). Scale: 12 (meta) / 14 (base, floor) / 16 (messages) / 20 (section) / 24 (page title). Weights 400/600.

**Spacing:** 4 px base — `4, 8, 12, 16, 24, 32, 48`. **Radius:** 8 (chips/badges) / 12 (bubbles, buttons) / 16 (cards). **Shadows:** `--shadow-1: 0 1px 2px rgb(15 23 42 / .06)`; `--shadow-2: 0 8px 24px rgb(15 23 42 / .10)` (drawer/menus).

**Layout:** chat column `max-width: 800px`, centered, `padding: 16px`; composer sticky bottom with safe-area inset; breakpoints **640 px** (tablet tweaks) and **1024 px** (drawer becomes overlay at <768 px); `touch-target ≥ 44px` for controls.

### 10.4 Responsive rules

| Width | Behavior |
|---|---|
| ≥1024 px | centered column; sources drawer as side panel (280–320 px) |
| 640–1023 px | centered column; drawer as right overlay |
| <640 px | full-bleed bubbles with 12 px gutters; header compresses (tagline hidden); drawer full-screen sheet; `env(safe-area-inset-bottom)` respected |

### 10.5 Accessibility requirements (NFR-05, FR-23)

- `role="log"` + `aria-live="polite"` on message region; each status has a **text** label (never color-only).
- Full keyboard: Tab order header → log → composer; visible `:focus-visible` ring (`--brand-600`, 2 px, 2 px offset); Enter/Shift+Enter handled on textarea.
- Contrast ≥ 4.5:1 for normal text (all token pairs verified — badges use 700-level text on pastel bg).
- `@media (prefers-reduced-motion: reduce)` disables transitions/typing animation (static text "Thinking…").
- Drawer: `aria-modal`, Esc closes, focus restored to trigger.

---

## 11. Loading, empty, and error states (matrix)

| State | Trigger | Visual | A11y | Recovery |
|---|---|---|---|---|
| Empty | first load | welcome + ≥4 example chips | announced as region content | click chip / type |
| Sending | request in flight | typing indicator; Send disabled; prior messages remain | status text "Thinking…" | n/a |
| Answered | `answered` | bubble + green badge + chips | `aria-live` announcement | — |
| Refused | `insufficient_knowledge` / `model_refusal` | amber bubble + canonical copy | announced with "not in sources" text | suggestion chips below (optional, answerable topics) |
| Rate limited | 429 | red notice "Too many requests — wait a moment" | announced | auto-clear after 60 s |
| Upstream error | 502/500/network | error card + Retry | announced | Retry re-sends last question |
| Degraded backend | health `degraded` (no index / mock) | amber dot + label ("Sample mode" / "Knowledge base building") | label text | run ingest / configure |
| Backend down | health unreachable | red dot + banner; composer still visible but send blocked with hint | announced | auto-retry health every 15 s |

---

## 12. Security, privacy, and observability

1. **Secrets:** `.env` only; `.gitignore`d; `.env.example` placeholders (`your_key_here`); startup fails fast naming the missing var; keys never appear in logs/responses/frontend (NFR-03, FR-18).
2. **Input hardening:** Pydantic length/pattern validation; body ≤ 8 KB; rate limit per IP; prompt treats question as data (prompt-injection: system prompt explicitly scopes to passages — tested by battery case).
3. **Output hardening:** generic client messages; exception handlers sanitize; no reflection of internals (§6.8).
4. **Privacy:** no persistence of questions; DEBUG logs truncate to 120 chars (NFR-04); no analytics/cookies; no PII collected.
5. **Dependencies:** bounded ranges in `requirements.txt`; license audit in Phase 7 (`pip show`), listed in README (NFR-07).
6. **Observability:** structured line per request: `ts=… rid=… route=/api/ask status=answered latency_ms=2310 top_score=11.42 model=…` + aggregate greppability (NFR-09); `/api/health` for probes.

---

## 13. Canonical copy (verbatim — frontend uses these)

### 13.1 Refusal (`insufficient_knowledge` / `model_refusal`)

> **Badge:** `Not in my sources`
> **Message:** "I couldn't find reliable information about this in the campus knowledge base, so I don't want to guess — a wrong institutional detail could cost you time. Please check the official university website at **iul.ac.in**, or contact your department office / the Registrar's office to confirm."
> **Next-step line:** "Tip: I currently know what's in my listed sources — open **Sources** to see them."

(Counts as "limitation + safe next step" — PRD P4/FR-07. Variation allowed only for tone, never substance; `model_refusal` may prepend "Your question touches my sources, but they don't fully answer it —".)

### 13.2 Error

> **Badge:** `Something went wrong` · **Message:** "I couldn't complete that request. Please try again in a moment." · **Action:** Retry

### 13.3 Disclaimer footer (FR-23)

> "CampusMate AI is an independent open-source project, not affiliated with or endorsed by Integral University. Answers are informational and may be incomplete — always verify against official university notifications."

---

## 14. Deployment and environments

| Aspect | Development | Test/CI | Prototype demo | Production (documented target, **not claimed**) |
|---|---|---|---|---|
| Run | `uvicorn backend.main:app --reload` | `MOCK_LLM=true pytest -q` | `uvicorn backend.main:app` behind LAN/tunnel | container + reverse proxy + TLS |
| LLM | live or mock | mock always | live (key in env) | live + quota monitoring |
| Rate limit | in-memory (single proc) | small limit for 429 test | 60/min | external gateway (limiter doesn't scale — §6.7) |
| Index | local build | fixture index in tmp dir | pre-built, verified | built at image build time |
| Extras | — | `run_battery.py` | rehearsed battery pass | monitoring, alerts, runbook, approval — **see `PRD` §8.4** |

Startup sequence: load settings (fail fast) → load index (missing ⇒ degraded + clear log) → mount routes/static → ready. `GET /api/health` reflects true state at all times.

---

## 15. Testing strategy

| Layer | Tooling | What it proves |
|---|---|---|
| Unit | pytest, tmp-path fixtures, tiny hand-built index (5–10 synthetic chunks incl. dup pages + sample doc) | normalization, dedupe, chunk bounds, ranking on known query, threshold gate, sentinel parse, citation validation/dropping, tokenizer (incl. `1,05,000`/`105000`), rate limiter |
| API | FastAPI `TestClient` + `MOCK_LLM=true` | all endpoint contracts (§8), status enum flows, 422/429/502 mappings, health/sources shapes, no-citation-on-refusal invariant |
| Battery | `scripts/run_battery.py` (+ live key, pre-demo) | SC-01…SC-04: real answer quality, refusals, citation validity, latency |
| Manual | `tests/manual_ui_checklist.md` | states matrix (§11), responsive (360/768/1440), keyboard-only, a11y, disclaimer |
| Smoke | `scripts/smoke_gemma.py` | key validity + model id availability (Phase 3 checkpoint) |

Test rules: deterministic (mock transport for retry/fallback paths), no network in `pytest`, no real key in CI, fixtures never mutate the real `index/`.

---

## 16. Post-MVP extension hooks (designed-in, not built)

- `retrieval.py` exposes a `search()` interface — hybrid/semantic retrievers can be added behind it without touching `service.py` (D-1 trade-off mitigation).
- `generator.py` isolates transport — swapping to self-hosted Ollama or another open model = config + one client branch.
- Prompt templates centralized in `prompts.py` — tone/language variants (Hinglish) are template-level changes.
- Manifest schema has `verified`/`type` fields ready for curated multi-source growth and a future admin UI.
