# CampusMate AI

> **Your Campus. Your Answers.** — an independent, open-source campus question-answering
> assistant that answers student questions **only** from a campus knowledge base, **cites the
> source page** for every factual answer, and **honestly refuses** when the knowledge base does
> not contain the information.

CampusMate AI is an **independent student-aid project**. It is **not** an official Integral
University system and is **not affiliated with or endorsed by** Integral University. Answers are
informational, not authoritative — official records, notifications, and fee circulars always take
precedence. (See `PRD.md` §1.4.)

> **Honest status: functional prototype.** It is built to production *quality* (typed modules,
> tests, retries, sanitized errors, observability) but it is **not** a production deployment. See
> `PRD.md` §8.4 for what "production ready" would additionally require.

---

## What it does

- **Grounded answers:** retrieval (BM25) selects passages from the knowledge base; the model may
  answer **only** from those passages (system prompt + server-side validation).
- **Validated citations:** every `answered` response carries ≥1 citation (`source_title`, PDF
  `page`, `snippet`, `score`). Citations are derived **server-side** from retrieved chunk IDs, so
  the model can never cite a page that wasn't retrieved (`FR-04`).
- **Two-layer abstention:** (1) a deterministic BM25 score gate that refuses **without calling the
  model**; (2) a model sentinel (`NO_ANSWER_IN_KB:`) for topically-close-but-insufficient cases.
- **Responsive, accessible chat UI:** vanilla HTML/CSS/JS, no build step; keyboard operable,
  `aria-live` announcements, 360 px → 1920 px.
- **Keyless development:** `MOCK_LLM=true` returns deterministic, grounded canned answers so the
  whole app and test suite run with **no API key and no network**.

## Architecture

```
Browser (frontend/)  ──HTTP same-origin──▶  FastAPI (backend/main.py)
                                              │  request_id · rate limit · error handlers
                                              ▼  backend/service.py (ask pipeline)
                                         retrieval.py → gate → generator.py → validate
                                              │
                              index/ (chunks.json, bm25.pkl)   Google AI Studio (Gemma)
```

Full detail: `DESIGN.md` §1, §6. Canonical terms (endpoints, statuses, env vars) live in
`DESIGN.md` and are mirrored by `backend/schemas.py` (runtime source of truth).

## Quickstart (≈5 minutes, keyless)

Requires **Python 3.12**.

```powershell
# 1. environment
python -m venv .venv
.venv\Scripts\activate            # POSIX: source .venv/bin/activate
pip install -r requirements.txt

# 2. configuration (keyless dev: MOCK_LLM=true)
Copy-Item .env.example .env       # POSIX: cp .env.example .env
#   edit .env only if you want live answers (set a real GEMINI_API_KEY, MOCK_LLM=false)

# 3. build the knowledge base index
python scripts/ingest.py          # writes index/chunks.json + index/bm25.pkl

# 4. run
python -m uvicorn backend.main:app --reload
#   open http://127.0.0.1:8000
```

Try:

- **Answered:** "What is the hostel fee for a single occupancy room?" → grounded answer + a
  citation chip ("Integral University Prospectus · p.45").
- **Refused:** "What is the revaluation fee policy?" → amber "Not in my sources" message,
  **no citations**.

### Run the tests

```powershell
$env:MOCK_LLM="true"; python -m pytest -q      # POSIX: MOCK_LLM=true python -m pytest -q
```

### Run the QA battery

```powershell
python scripts/run_battery.py                  # honours MOCK_LLM from .env
```

### Verify a real key + model (live mode)

```powershell
python scripts/smoke_gemma.py                  # one real call; confirms the key and model ID
```

## Configuration

All configuration is via environment variables (`.env`, gitignored). `.env.example` documents
every variable. Source of truth: `DESIGN.md` §6.2.

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — (required unless mock) | API key; startup fails fast naming the variable if missing and `MOCK_LLM` is false |
| `GEMMA_MODEL_ID` | `gemma-3-27b-it` | Primary model (**verify with `smoke_gemma.py`**) |
| `GEMMA_FALLBACK_MODEL_ID` | `gemma-3-12b-it` | Fallback on 429/5xx/timeout |
| `BM25_MIN_SCORE` | `10.5` | Abstention layer-1 threshold (calibrated — see `docs/DECISIONS.md`) |
| `BM25_TOP_K` | `5` | Passages sent to the model |
| `RATE_LIMIT_PER_MINUTE` | `60` | Per-IP fixed window |
| `MOCK_LLM` | `false` | Deterministic canned mode, no key needed |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | Bind address |
| `LOG_LEVEL` | `INFO` | `DEBUG` logs the (truncated) question |

## Approved-source process (how to extend the knowledge base)

The assistant can only ever answer from files registered in `data/sources/manifest.json`
(`FR-09`).

1. Place an **approved** `.txt` file in `data/sources/` (use `scripts/extract_pdf.py` to convert
   a PDF to text with `===== PAGE n =====` markers).
2. Add a manifest entry (`source_id`, `title`, `file`, `type`, `verified`, `is_sample`). Anything
   not verified as official **must** be named `sample-*.txt` **and** have `is_sample: true`
   (`FR-12`); ingestion fails if the two disagree.
3. Run `python scripts/ingest.py`.
4. Verify via the **Sources** drawer and re-run `python scripts/run_battery.py`.

## Project structure

```
backend/     config · schemas · textutils · retrieval · prompts · generator · ratelimit · service · main
frontend/    index.html · styles.css · app.js        (vanilla, no build step)
scripts/     ingest · extract_pdf · search_cli · smoke_gemma · run_battery
tests/       unit + API tests · battery.json · manual_ui_checklist.md
data/sources/ manifest.json + source .txt files (source of truth)
index/       GENERATED artifacts (gitignored) — rebuild with scripts/ingest.py
docs/        DECISIONS.md (decision/assumption log)
```

## License audit (`NFR-07`)

Licenses verified from installed package metadata (`importlib.metadata`).

| Package | Version | License (verified) |
|---|---|---|
| fastapi | 0.143.2 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| pydantic | 2.14.1 | MIT |
| pydantic-settings | 2.16.0 | MIT |
| rank-bm25 | 0.2.2 | Apache-2.0 |
| httpx | 0.28.1 | BSD-3-Clause |
| pypdf | 5.9.0 | BSD-3-Clause |
| pytest | 8.4.2 | MIT |
| starlette (transitive) | 1.8.0 | BSD-3-Clause |

**Model:** Gemma is distributed under **Google's Gemma Terms of Use** — open-weight, but **not**
an OSI-approved open-source license. This is stated honestly rather than mislabeled (`PRD`
NFR-07). The project itself is licensed **MIT** (`LICENSE`).

## Known limitations (honest)

- **Corpus gap:** the provided prospectus has **no examination-regulation content**; the assistant
  refuses those questions by design (`PRD` A-06). Adding approved exam sources is a stretch item.
- **Layer-1 gate is a coarse filter.** BM25 raw scores are corpus-size dependent and do not fully
  separate in-scope from out-of-scope questions; correctness is enforced primarily by the model
  sentinel (layer 2) and by server-side citation validation. The threshold is calibrated for the
  bundled corpus (`docs/DECISIONS.md`).
- **Mock mode is not a quality substitute.** `MOCK_LLM=true` returns grounded-but-canned snippets
  for development/CI; real answer quality requires a live `GEMINI_API_KEY`.
- **Model IDs unverified live:** `gemma-3-27b-it` / `gemma-3-12b-it` are the documented defaults;
  run `scripts/smoke_gemma.py` with a key to confirm them against AI Studio.
- **Rate limiter is per-process** (does not scale horizontally — `DESIGN.md` §6.7).
- No authentication, no persistence, no user accounts (out of scope by design).

## Documentation

`PRD.md` (what) · `DESIGN.md` (how) · `AGENTS.md` (agent rules) · `BUILD_PLAN.md` (build order) ·
`docs/DECISIONS.md` (decisions/assumptions).

## License

MIT — see `LICENSE`. CampusMate AI is an independent project with no university affiliation.
