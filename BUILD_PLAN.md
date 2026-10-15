# CampusMate AI — Phased Implementation Plan (`BUILD_PLAN.md`)

| Field | Value |
|---|---|
| Purpose | Dependency-aware build order with checkpoints, traceability, risks, and session-recovery rules |
| Companion documents | `PRD.md` (what) · `DESIGN.md` (how) · `AGENTS.md` (rules) |
| Version | 1.0 |
| Last updated | 2026-10-16 |

---

## 1. How to use this plan

- Phases are strictly ordered by dependency. **Do not start phase N+1 until phase N's checkpoint passes** (checkboxes below are the shared state across sessions).
- Every phase lists: **Objective → Tasks → Outputs → Dependencies → Checkpoint → Fallbacks.**
- After each phase: run its checkpoint **and** `pytest -q`, then tick the phase checkbox and update the status table (§2).
- Requirement traceability: **§7 matrix** maps every `FR/NFR/SC` ID → phase → verification. No phase completes while mapped items fail.
- **Session recovery (context limit / interruption / new session):** follow `AGENTS.md` §16 — read this file's status table, run `pytest -q`, resume at first unchecked phase. No phase requires remembering prior conversation; all durable state lives in these four documents + code + `docs/DECISIONS.md`.

### Phase status table (maintain on every change)

| Phase | Title | Status | Evidence (command output / report link) |
|---|---|---|---|
| 0 | Scaffold & environment | ⬜ not started | |
| 1 | Knowledge base ingestion | ⬜ not started | |
| 2 | Retrieval service (BM25 + gate) | ⬜ not started | |
| 3 | AI integration (Gemma, citations, refusal v2) | ⬜ not started | |
| 4 | API layer (routes, limits, errors, logging) | ⬜ not started | |
| 5 | Frontend chat UI | ⬜ not started | |
| 6 | End-to-end QA & threshold calibration | ⬜ not started | |
| 7 | Open-source polish & demo readiness | ⬜ not started | |
| 8 | Stretch (optional) | ⬜ not started | |

---

## 2. Global conventions and commands

Run everything from the **project root**. Windows (PowerShell) and POSIX variants given.

```powershell
# Environment (once)
python -m venv .venv
.venv\Scripts\activate                # POSIX: source .venv/bin/activate
pip install -r requirements.txt
Copy-Item .env.example .env           # POSIX: cp .env.example .env   → add real GEMINI_API_KEY

# Knowledge base
python scripts/ingest.py              # build index/chunks.json + index/bm25.pkl
python scripts/search_cli.py "hostel fee"   # calibration/debug view

# Run
MOCK_LLM value lives in .env; for keyless dev set MOCK_LLM=true in .env
uvicorn backend.main:app --reload     # http://127.0.0.1:8000

# Test (always; mock mode, offline)
$env:MOCK_LLM="true"; pytest -q      # POSIX: MOCK_LLM=true pytest -q

# Live checks (need key)
python scripts/smoke_gemma.py         # verify key + model id (Phase 3)
python scripts/run_battery.py         # QA battery (Phase 6/7)
```

**Phase priority if time is short (hackathon mode):** Phases 0→1→2→3→4→5→6 are **critical path**; Phase 7 minimum = README quickstart + LICENSE + battery pass; Phase 8 fully droppable. Never drop: abstention gate (FR-05), citation validation (FR-04), disclaimer (FR-23), tests for core logic.

**Canonical terms in force across all phases** (source of truth: `DESIGN.md`; summary kept here so phase work needs no cross-file lookup): ask-response `status` ∈ `answered` · `insufficient_knowledge` · `model_refusal` · `upstream_error`; error-body `status` ∈ `validation_error` · `rate_limited` · `kb_unavailable` · `upstream_error` · `internal_error`; endpoints `POST /api/ask` · `GET /api/health` · `GET /api/sources`; refusal sentinel `NO_ANSWER_IN_KB:`; model citation line `Sources: [n]`. Any phase that introduces one of these terms must spell them identically.

---

## 3. Phases

### Phase 0 — Scaffold & environment

- **Objective:** Runnable skeleton: repo layout, deps, config, empty test suite green.
- **Depends on:** nothing.
- **Tasks:**
  1. Create the canonical tree (`DESIGN.md` §4): folders + empty module files with docstrings; `backend/__init__.py`.
  2. `requirements.txt`: `fastapi>=0.115,<1.0` · `uvicorn[standard]>=0.32,<1.0` · `pydantic>=2.9,<3.0` · `pydantic-settings>=2.6,<3.0` · `rank-bm25>=0.2.2,<0.3` · `httpx>=0.27,<1.0` · `pypdf>=5.0,<6.0` · `pytest>=8.0,<9.0`.
  3. `.env.example` with every env var from `DESIGN.md` §6.2 (placeholder key `your_key_here`); `.gitignore` (`.env`, `index/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.DS_Store`).
  4. `backend/config.py`: pydantic-settings `Settings`, `MOCK_LLM` bool coercion, fail-fast validation (FR-18).
  5. `docs/DECISIONS.md` seeded with: prospectus year TBC (PRD A-02), threshold initial 4.0 pending calibration, exam-corpus gap acknowledged (A-06).
  6. `git init` (if absent) + initial commit of docs + scaffold.
  7. `tests/conftest.py` with `Settings` fixture (mock mode) + trivial smoke test (`import backend.main` placeholder allowed until Phase 4 routes exist — keep test minimal and honest).
- **Outputs:** tree exists; `requirements.txt`; `.env.example`; `.gitignore`; `docs/DECISIONS.md`; suite runs.
- **Checkpoint:**
  ```
  pip install -r requirements.txt   → 0 errors
  pytest -q                          → green (≥1 test)
  python -c "from backend.config import Settings; print(Settings().model_fields.keys())"  → prints field names incl. GEMINI_API_KEY
  git status                         → clean or only intended files
  ```
- **Fallbacks:** dependency install failure (no network) → vendor wheels unavailable: document, defer to network; `rank-bm25` unavailable → record in DECISIONS and substitute a minimal BM25 implementation inside `retrieval.py` (pure Python, same interface) — only with doc update.

### Phase 1 — Knowledge base ingestion

- **Objective:** `data/sources/` → validated, normalized, deduplicated, page-annotated chunks + built index (FR-09…FR-13).
- **Depends on:** Phase 0.
- **Tasks:**
  1. Move the already-extracted corpus to canonical path: `data/prospectus.txt` → `data/sources/prospectus.txt` (extraction previously verified: 145 pages, 614,929 chars).
  2. `data/sources/manifest.json` per `DESIGN.md` §5.1 (edition year TBC note included).
  3. `scripts/extract_pdf.py`: CLI `python scripts/extract_pdf.py <in.pdf> <out.txt>` emitting `===== PAGE n =====` markers (pypdf), UTF-8 stdout-safe. (Utility only — the main corpus is already extracted.)
  4. `scripts/ingest.py`: validate manifest (FR-09, FR-12 sample-rule) → normalize (FR-10: control chars, NFC, ligatures `ﬁ/ﬂ/ﬀ`, `` ` `` before digits → `₹`, collapse blank runs) → page split on markers → dedupe identical normalized page text (log count) → chunk 600/100 with paragraph preference, bounds 200–900, `page_start/end`, best-effort `section` (FR-11) → write `index/chunks.json` → tokenize + BM25 → `index/bm25.pkl`.
  5. Tokenizer shared later with runtime — put `tokenize()` in ingest **and** expose for `backend/retrieval.py` (single implementation, e.g., `scripts/ingest.py` exposes it or a shared `backend/textutils.py` if retrieval needs it — prefer one source; document choice in DECISIONS if a new file is added).
- **Outputs:** `data/sources/prospectus.txt`, `manifest.json`, `scripts/ingest.py`, `scripts/extract_pdf.py`, built `index/`, `tests/test_ingest.py`.
- **Checkpoint:**
  ```
  python scripts/ingest.py
      → "chunks=<N> (N > 150 expected for 145 pages), duplicates_removed>0, samples=0"
  python -c "import json;c=json.load(open('index/chunks.json',encoding='utf-8'));print(len(c), c[0].keys())"
      → >150 chunks; keys include chunk_id, source_id, page_start, is_sample
  pytest -q tests/test_ingest.py    → green (manifest validation, sample-rule error, dedupe, bounds, ₹ fix, ligature fix, unlisted-file warning)
  ```
- **Fallbacks:** extraction artifacts worse than expected (garbled pages) → keep raw text, log pages with <50 chars, note in DECISIONS; duplicates not caught by exact-match → add normalized-hash comparison; section detection flaky → set `section: null` rather than guess.

### Phase 2 — Retrieval service (BM25 + abstention gate)

- **Objective:** Question → ranked passages with scores; deterministic low-score refusal (FR-05, D-1, D-3).
- **Depends on:** Phase 1.
- **Tasks:**
  1. `backend/retrieval.py`: load `chunks.json`+`bm25.pkl` at startup (clear error if missing → health degraded later); `search(question, k) -> SearchResult(passages, top_score)`; gate helper `below_threshold(result) -> bool` using `settings.BM25_MIN_SCORE` (default 4.0).
  2. Identical tokenizer path for queries as indexing (`1,05,000`/`105000` both match).
  3. `scripts/search_cli.py`: prints top-5 chunks (score, source, page, 100-char preview) — calibration tool for Phase 6.
  4. Tests with a tiny synthetic index fixture (tmp dir): known-question ranks expected chunk #1; out-of-scope question ("revaluation fee policy") falls below threshold; tokenizer number equivalence; missing-index raises `KnowledgeBaseError`.
- **Outputs:** `retrieval.py`, `search_cli.py`, `tests/test_retrieval.py`.
- **Checkpoint:**
  ```
  python scripts/search_cli.py "What is the hostel fee for a single occupancy room?"
      → top hit in fee/hostel region of the prospectus, score visibly above ~6
  python scripts/search_cli.py "quantum entanglement syllabus of the music department"
      → low top score (expected < 4.0)  [record observations in status row]
  pytest -q                          → green
  ```
- **Fallbacks:** scores globally too high/low (BM25 corpus-size effect) → calibration is Phase 6; set provisional 4.0 and **record actual battery-relevant scores** in DECISIONS; duplicate-content chunks dominating results → strengthen dedupe (Phase 1).

### Phase 3 — AI integration: Gemma, prompt, citations, refusal layer 2

- **Objective:** Grounded generation with validated citations + sentinel refusal (FR-03, FR-04, FR-06, D-9, D-10), mock mode (FR-21).
- **Depends on:** Phase 2.
- **Tasks:**
  1. `backend/prompts.py`: system template exactly per `DESIGN.md` §6.6 (sentinel `NO_ANSWER_IN_KB:`, `[n]` markers, `Sources:` line, ≤120 words, SAMPLE mention); `build_user_message(passages, question)`.
  2. `backend/generator.py`: `httpx` POST `…/{model}:generateContent` (`x-goog-api-key`, temperature 0.2, maxOutputTokens 1024, 20 s timeout); 1 retry w/ 500 ms backoff on 429/5xx/timeout → `GEMMA_FALLBACK_MODEL_ID` once → `UpstreamError` (NFR-02); `parse_response()` implementing §6.6 parse rules (sentinel detect, `Sources:` extraction, index∩retrieved validation, zero-citation downgrade); `MOCK_LLM` canned responses (keyword-keyed answer w/ citation, else canned sentinel).
  3. **Verify model IDs for real** (no assumptions): `python scripts/smoke_gemma.py` against AI Studio's model list; set `GEMMA_MODEL_ID`/fallback to IDs that actually respond; record verified IDs in README + DECISIONS.
  4. Tests (offline, mocked transport): prompt contains all passages + hard rules; sentinel → `model_refusal`; invalid index `[9]` dropped; no-sources-line → refusal; fallback chain order on 429→success; exhausted chain → `UpstreamError`; mock mode returns cited answer.
- **Outputs:** `prompts.py`, `generator.py`, `scripts/smoke_gemma.py`, `tests/test_generator.py`.
- **Checkpoint:**
  ```
  pytest -q tests/test_generator.py        → green (offline)
  python scripts/smoke_gemma.py            → "key OK, model gemma-3-27b-it (or recorded ID) answered" OR documented failure → fallback model chosen
  ```
- **Fallbacks:** no key yet → everything except smoke runs under `MOCK_LLM=true` (documented, health shows mock); model id not available → next available Gemma id from the official list, updated everywhere (§9 sync rule); API quota throttling in demo → fallback model + retry already built; battery re-run live before demo.

### Phase 4 — API layer: routes, contracts, limits, errors, logging

- **Objective:** `POST /api/ask`, `GET /api/health`, `GET /api/sources` with full contract, rate limit, sanitized errors, structured logs, static mount (FR-01/02/17/19/20/24, NFR-02/03/04/09, `DESIGN` §6/§8).
- **Depends on:** Phase 3 (service may integrate retrieval+generator directly first, then wrap).
- **Tasks:**
  1. `backend/schemas.py`: `AskRequest`, `Citation`, `RetrievalInfo`, `ModelInfo`, `AskResponse`, health/sources/error models per `DESIGN.md` §5 (status enum literal).
  2. `backend/service.py`: pipeline exactly per §6.1 (gate before generate; canonical refusal copy §13.1; latency + `request_id` injection).
  3. `backend/main.py`: routes; request_id middleware; exception handlers per §6.8 error taxonomy (422/429/500/502/503); static mount of `frontend/` at `/`; structured log line per §12.6; `frontend/` may be placeholder page until Phase 5.
  4. `backend/ratelimit.py`: fixed-window per-IP (FR-19).
  5. Sources route reads manifest + chunk counts (FR-24).
  6. `tests/test_api.py`: 200 `answered` (mock), 200 refusal (mock low-relevance path — use threshold override fixture), 422 (empty/501-char), 429 (limit=3), 502 (mock transport always failing), health shape + `degraded` when index missing (tmp app), sources shape + `how_to_add`, **refusal ⇒ citations `[]`**, error bodies contain `request_id` but no stack traces.
- **Outputs:** 6 backend modules complete, `tests/test_api.py`.
- **Checkpoint:**
  ```
  $env:MOCK_LLM="true"; uvicorn backend.main:app
  curl -s localhost:8000/api/health            → {"status":"ok"|"degraded", ...}
  curl -s -X POST localhost:8000/api/ask -H "content-type: application/json" -d '{"question":"hostel fee for single occupancy"}'   → status=answered + citations
  curl -s -X POST localhost:8000/api/ask -d '{"question":""}' -H "content-type: application/json"            → 422
  pytest -q                                   → green
  ```
- **Fallbacks:** contract drift discovered late → `schemas.py` + §8 + tests updated together (AGENTS §9); static mount conflicts → mount after API routes, verify `/api/*` precedence; middleware ordering issues → request_id first, then rate limit.

### Phase 5 — Frontend chat UI

- **Objective:** Complete single-page chat per `DESIGN.md` §10–§13: states, citation chips, sources drawer, accessibility, responsive, disclaimer (FR-01, FR-08, FR-14…FR-16, FR-22, FR-23; NFR-05).
- **Depends on:** Phase 4 (needs live contract; contract-test-first allowed in parallel using mock responses).
- **Tasks:**
  1. `frontend/index.html`: structure per §10.1 (header + status dot + Sources button, `role="log"` region, composer, drawer, disclaimer footer §13.3).
  2. `frontend/styles.css`: tokens per §10.3 (exact hex values), components (bubbles, badges, chips, typing dots, error card, drawer), breakpoints §10.4, focus-visible, reduced-motion.
  3. `frontend/app.js`: state machine §10.2; `fetch` helper w/ `AbortController` (15 s) + `request_id`-aware error mapping (429 copy, retry on 502/500/network); citation chips (textContent rendering only — AGENTS §11); example chips fill composer; sources drawer (fetch `/api/sources`, Esc/focus restore); health dot polling 60 s; Enter/Shift+Enter; auto-scroll w/ reduced-motion guard; aria-live announcements.
  4. Wire everything against real backend (mock or live).
- **Outputs:** 3 frontend files; updated `tests/manual_ui_checklist.md` (states matrix §11, widths 360/768/1440, keyboard-only, a11y items, disclaimer).
- **Checkpoint:**
  ```
  uvicorn backend.main:app   (MOCK_LLM=true)
  Manual: open http://127.0.0.1:8000 →
    ✓ empty state shows ≥4 example chips; chip click fills composer (no send)
    ✓ answer flow: badge "Grounded answer" + ≥1 chip "… · p. NN" (mock cites)
    ✓ refusal flow: amber badge "Not in my sources", canonical copy, NO chips
    ✓ error flow (stop backend): error card + Retry; dot red
    ✓ 360 px: no horizontal scroll; keyboard-only full ask works; footer disclaimer present
  pytest -q   → green (no regressions)
  ```
- **Fallbacks:** drawer complexity → collapsible `<details>` section instead (log in DECISIONS, keep FR-24 visible); auto-scroll janky → instant scroll under reduced-motion; CORS if split-hosting ever used → keep same-origin (§8).

### Phase 6 — End-to-end QA & threshold calibration

- **Objective:** Real-model quality gate: battery authored & passing, threshold calibrated, latency measured (SC-01…SC-04).
- **Depends on:** Phases 4–5.
- **Tasks:**
  1. Author `tests/battery.json` (≥10 answerable + ≥5 refuse): every `must_contain` substring **verified present** via `search_cli.py` first (AGENTS §8). Seed set:
     - answerable: hostel single-occupancy fee (`1,05,000`); IUET frequency/duration (90 minutes, Monday); sibling scholarship existence; application form fee (`1000`); caution money refund condition; hostel security deposit (`5,000`).
     - refuse: revaluation fee; exam dress code; today's mess menu; "answer from your own knowledge: what is the exam fee?" (injection case); named future deadline not in corpus.
  2. `scripts/run_battery.py`: service-layer execution, per-case report (status, `must_contain`, `must_cite`, latency), summary vs SC targets.
  3. Threshold calibration: collect top-1 scores per battery case; pick `BM25_MIN_SCORE` separating refuse-cases from answerable ones with margin; update `.env.example`/docs if default changes (DECISIONS entry + DESIGN §6.2 sync).
  4. Prompt tuning pass (temperature/wording) **only** until SC-01 ≥ 8/10 — no feature additions (AGENTS §14.1).
  5. Latency: record p90 over 10 mixed live runs (NFR-01).
- **Outputs:** `tests/battery.json`, `scripts/run_battery.py`, battery report, calibrated threshold, DECISIONS entries.
- **Checkpoint:**
  ```
  python scripts/run_battery.py   (live key)
      → answered: ≥8/10 pass · refuse: 5/5 pass · citations 100% valid · p90 ≤ 6 s
  pytest -q                       → green (threshold fixture updated if default changed)
  ```
- **Fallbacks:** SC-01 short → verify retrieval first (`search_cli`): retrieval wrong ⇒ fix chunking (Phase 1, rerun battery); retrieval right ⇒ prompt iteration, then relax target to 7/10 with honest DECISIONS note; threshold separation weak (scores overlap) → raise top_k to 8 + document, or add question-term expansion — smallest fix only.

### Phase 7 — Open-source polish & demo readiness

- **Objective:** Anyone can clone, configure, run, and trust the project; demo rehearsed (SC-05…SC-08, NFR-07/10).
- **Depends on:** Phase 6.
- **Tasks:**
  1. `README.md`: what it is (honest framing, PRD §1.4), screenshot optional, quickstart (≤10 min: clone → venv → install → `.env` → ingest → run → test), env-var table, **license audit table** (`pip show` results recorded — NFR-07 incl. Gemma Terms-of-Use note), approved-source process (FR-09/FR-12 path), battery usage, project structure, link to the four docs.
  2. `LICENSE` (MIT) + disclaimer reuse from §13.3.
  3. Fresh-clone rehearsal (SC-05): follow README verbatim in a clean directory; time it; fix every doc gap found.
  4. Accessibility pass: full `manual_ui_checklist.md` run, record results.
  5. Demo rehearsal (SC-08): ≤3 min script — ask fee question (answer + chip + open sources), ask revaluation question (amber refusal), show health/sources, show tests.
  6. Final `pytest -q` + battery report saved as `docs/` evidence referenced in status table.
- **Outputs:** README, LICENSE, checklist results, battery report, rehearsed demo.
- **Checkpoint:**
  ```
  Fresh dir: follow README → app runs, health ok, pytest green, battery ≥ targets
  (record elapsed time in status row; must be ≤ 10 min)
  ```
- **Fallbacks:** license uncertainty on any dep → replace or document with explicit "verified/unverified" column; time crunch → README + LICENSE + battery pass are mandatory; screenshot/polish items droppable.

### Phase 8 — Stretch (optional; only after Phase 7)

- **Objective:** Deployment credibility + corpus gap closure.
- **Depends on:** Phase 7.
- **Tasks (each independently droppable):**
  1. `Dockerfile` (python:3.12-slim, install reqs, build index at image build, `uvicorn` CMD) + `docker run -p 8000:8000 -e GEMINI_API_KEY=…` documented in README → Checkpoint: container serves health + one battery case.
  2. Additional **approved** exam-regulation sources: only documents the team has verified → manifest `verified: true` → ingest → battery additions → sources panel shows them. Unverified content stays `sample-*` (FR-12).
  3. Deploy config (Render/Railway/Fly) — only with real credentials supplied by team; never fabricate URLs/keys. Record live URL only if actually deployed and verified.
- **Fallbacks:** Docker unavailable on dev machine → document as untested (never claim tested); no approved extra docs → corpus gap stays honestly documented (PRD A-06), refusal demo covers it.

---

## 4. Cross-phase invariants (must hold at all times)

1. `pytest -q` green after every phase (AGENTS §15).
2. Refusal paths show **no citations**; answered paths show **only retrieved-chunk citations** (FR-04/FR-07).
3. Layer-1 gate runs **before** any model call (FR-05).
4. `.env` never tracked; no secrets anywhere (AGENTS §7).
5. Canonical terms (§8 endpoints, statuses, env vars, paths) match all four documents (AGENTS §9).
6. Disclaimer visible on every UI state (FR-23).
7. Sample docs triple-labeled: filename / manifest / UI badge (FR-12).

---

## 5. Risk register

| # | Risk | Likelihood | Impact | Mitigation | Fallback |
|---|---|---|---|---|---|
| R1 | AI Studio model ID unavailable / quota changes | Med | High | Verify in Phase 3 smoke; fallback model configured | Second Gemma ID → then mock mode documented for demo |
| R2 | No API key ready when Phase 3 starts | Med | Med | `MOCK_LLM` unblocks Phases 3–5 fully | Run live battery only in Phase 6/7 |
| R3 | BM25 threshold miscalibrated (false answers or over-refusal) | Med | High | Calibration task Phase 6 w/ battery score table | Raise threshold conservatively (over-refuse > hallucinate) + document |
| R4 | Corpus quality: dup pages, ligatures, garbled extraction | High (observed) | Med | FR-10 normalization + dedupe; extraction already verified viable | Per-page quality log; drop unusable pages with note |
| R5 | Corpus gap (exams) disappoints judges | Med | Med | Honest refusal demo; stretch Phase 8.2 for approved docs | Frame as feature: refusal is a scored behavior (SC-02) |
| R6 | Solo/3-hour time pressure | High | High | §2 priority order; phases timeboxed; P8 droppable | Ship Phases 0–6 + minimal README |
| R7 | Frontend/backend contract drift | Med | Med | `schemas.py` runtime truth + contract tests Phase 4 | Fix via AGENTS §9 sync procedure |
| R8 | Live demo API latency/quota mid-presentation | Low | High | Pre-run battery; fallback model; rehearsed mock-mode backup demo | `MOCK_LLM=true` demo path (honestly labelled) |
| R9 | Windows encoding issues (cp1252, `₹`, ligatures) | High (observed) | Low | Explicit UTF-8 everywhere, `pathlib`, stdout reconfigure in scripts | Keep ASCII-only log output |
| R10 | Scope creep (features without FR) | Med | High | AGENTS §14.1 + non-goals PRD §2.2 | Log idea in DECISIONS, defer to post-MVP |
| R11 | Pickle risk (`bm25.pkl`) | Low | Med | Index built locally only; `index/` gitignored; never unpickle untrusted files | JSON chunks fallback (rebuild index) |
| R12 | Session/context interruption mid-phase | High | Med | `AGENTS.md` §16 resume protocol; phase checkboxes; atomic commits per phase | Re-run checkpoint to re-establish state |

---

## 6. Requirement traceability matrix

> Every requirement → build phase → verification. ⬜ = not yet verified.

### 6.1 Functional requirements (PRD §6)

| FR | Title | Phase | Verification |
|---|---|---|---|
| FR-01 | Composer validation + submit | 5 | `test_api` 422 + UI checklist |
| FR-02 | `POST /api/ask` contract/status enum | 4 | `test_api` schema assertions |
| FR-03 | Grounded prompt (passages-only) | 3 | `test_generator` prompt-content assertions |
| FR-04 | Validated citations (⊆ retrieved) | 3 | `test_generator` + `test_api` refusal/answer invariants |
| FR-05 | Layer-1 threshold gate (no LLM) | 2 | `test_retrieval` gate + mock-call-count assert |
| FR-06 | Layer-2 sentinel `NO_ANSWER_IN_KB:` | 3 | `test_generator` sentinel cases |
| FR-07 | Canonical refusal copy, no facts | 4 | `test_api` copy + battery SC-02 |
| FR-08 | Status-driven UI rendering | 5 | UI checklist states matrix |
| FR-09 | Manifest-only ingestion | 1 | `test_ingest` unlisted-file warning |
| FR-10 | Normalization + dedupe | 1 | `test_ingest` ligature/₹/dedupe tests |
| FR-11 | Chunking 600/100 + page spans | 1 | `test_ingest` bounds/span tests |
| FR-12 | Sample triple-labeling | 1 | `test_ingest` sample-rule error + UI badge checklist |
| FR-13 | Rebuildable index artifact | 1 | ingest checkpoint + health `index_ready` |
| FR-14 | Example chips (empty state) | 5 | UI checklist |
| FR-15 | Loading indicator + send guard | 5 | UI checklist |
| FR-16 | Four status UIs + Retry | 5 | UI checklist |
| FR-17 | Health endpoint + status dot | 4 | `test_api` health + UI checklist |
| FR-18 | Env config + fail-fast | 0 | `config` test in `test_api`/`conftest` |
| FR-19 | Rate limiting → 429 | 4 | `test_api` 429 case |
| FR-20 | Structured request logs | 4 | log inspection (phase report paste) |
| FR-21 | `MOCK_LLM` canned mode | 3 | `test_generator` + whole suite offline |
| FR-22 | Responsive 360–1920 | 5 | UI checklist widths |
| FR-23 | Disclaimer + a11y basics | 5 | UI checklist + a11y pass (Phase 7) |
| FR-24 | `/api/sources` + how-to-add | 4 | `test_api` sources shape |

### 6.2 Non-functional requirements (PRD §7)

| NFR | Phase | Verification |
|---|---|---|
| NFR-01 performance (<300 ms app overhead; p90 ≤6 s) | 6 | battery latency column |
| NFR-02 reliability (retry→fallback→502) | 3 | `test_generator` fault-injection |
| NFR-03 security (secrets, sanitization, limits) | 0,4 | gitignore check + `test_api` no-traceback assert |
| NFR-04 privacy (no persistence, trunc. logs) | 4 | log inspection |
| NFR-05 accessibility (AA, keyboard, live) | 5 | checklist; full pass Phase 7 |
| NFR-06 compatibility (py3.12, cross-OS, UTF-8) | 0 | suite green on dev platform; `pathlib`/UTF-8 code review |
| NFR-07 licensing (verified + listed) | 7 | README license table with `pip show` evidence |
| NFR-08 maintainability (tests, types, modules) | 0–4 | `pytest -q` + review vs DESIGN §1.2 |
| NFR-09 observability (health, request_id) | 4 | `test_api` + log inspection |
| NFR-10 documentation (≤10-min quickstart) | 7 | fresh-clone rehearsal (timed) |

### 6.3 Success criteria (PRD §9) & user stories

| ID | Phase | Verification |
|---|---|---|
| SC-01 (≥8/10 answered) | 6 | `run_battery.py` report |
| SC-02 (5/5 refuse) | 6 | `run_battery.py` report |
| SC-03 (100% citation validity) | 6 | battery `must_cite` + `test_api` |
| SC-04 (p90 ≤6 s) | 6 | battery latency stats |
| SC-05 (≤10-min setup) | 7 | timed fresh-clone rehearsal |
| SC-06 (suite green, FR coverage) | continuous | `pytest -q` + this matrix |
| SC-07 (responsive + a11y) | 5,7 | `manual_ui_checklist.md` |
| SC-08 (≤3-min demo) | 7 | rehearsed demo, recorded in status row |
| US-01…US-08 | 5–6 | UI checklist (each story's ACs listed there) |

---

## 7. Validation quick-reference (commands by concern)

| Concern | Command |
|---|---|
| Everything automated | `MOCK_LLM=true pytest -q` |
| Index built & sane | `python scripts/ingest.py && python scripts/search_cli.py "IUET"` |
| API live contract | `curl -s localhost:8000/api/health` / `curl -s -X POST …/api/ask …` |
| Key & model | `python scripts/smoke_gemma.py` |
| Quality gate | `python scripts/run_battery.py` |
| Full manual | `tests/manual_ui_checklist.md` |

---

## 8. Session recovery summary (details: `AGENTS.md` §16)

Durable state lives in: phase checkboxes/status table (this file) → code → `docs/DECISIONS.md` → test suite. On resume: read status table → first ⬜ phase → `pytest -q` → check `git status` for half-work → read only that phase's tasks + the `DESIGN.md` sections it names → execute → report via template (`AGENTS.md` §15). A phase's own checkpoint re-establishes ground truth without any conversation history.

---

## 9. Final acceptance checklist (v1.0 = "Done")

- [ ] Phases 0–7 status rows marked ✅ with evidence
- [ ] `MOCK_LLM=true pytest -q` fully green **and** live battery (`run_battery.py`) meets SC-01…SC-04 (report attached to status table)
- [ ] Fresh-clone rehearsal ≤ 10 min, timed, recorded (SC-05)
- [ ] `manual_ui_checklist.md` fully executed, results recorded (SC-07)
- [ ] README quickstart + license table (verified via `pip show`) + Gemma terms note (NFR-07)
- [ ] Disclaimer visible in app; no fabricated university content anywhere (`AGENTS.md` §8) — grep sweep for stray facts
- [ ] `.env` untracked; no secrets in repo history
- [ ] All four documents mutually consistent (endpoints, statuses, env vars, paths greppable-identical)
- [ ] Demo rehearsed ≤ 3 min incl. refusal case (SC-08)
- [ ] Honest status statement present: **functional prototype**; production claims only if `PRD` §8.4 items are actually verified
