# CampusMate AI — Product Requirements Document (PRD)

| Field | Value |
|---|---|
| Product | CampusMate AI |
| Tagline | Your Campus. Your Answers. |
| Version | 1.0 |
| Status | Approved for implementation |
| Related documents | `DESIGN.md` (how), `AGENTS.md` (agent rules), `BUILD_PLAN.md` (build order) |
| Last updated | 2026-10-16 |

> **Document role:** This PRD defines **what** the application must do. Implementation details live in `DESIGN.md`. Rules for AI coding agents live in `AGENTS.md`. Sequencing lives in `BUILD_PLAN.md`. Requirement IDs defined here (`FR-xx`, `NFR-xx`, `US-xx`, `SC-xx`) are the canonical cross-reference keys used by all four documents.

---

## 1. Product overview

### 1.1 Problem statement

Students at Integral University wait days for answers to recurring questions about examinations, fees, registration, and course material.

The information needed to answer these questions already exists in institutional documents (the university prospectus, handbooks, and notices). The problem is **findability**: students cannot efficiently search those documents, so they wait for a human intermediary to answer questions that are asked repeatedly.

### 1.2 Proposed product

An open-source AI assistant that answers student questions using a campus knowledge base, cites the source documents supporting its answers, and explicitly acknowledges when the available information is insufficient to answer reliably.

### 1.3 Product vision

Give every Integral University student an instant, honest, source-backed answer desk that is available 24/7 — eliminating the multi-day wait for recurring factual questions, while never inventing institutional facts.

### 1.4 Product boundary (important)

- CampusMate AI is an **independent, open-source student aid tool**. It is **not** an official university system and is not affiliated with or endorsed by Integral University.
- Responses are **informational, not authoritative**. Official records, notifications, and fee circulars always take precedence.
- The UI must display a persistent disclaimer stating this (see `FR-23`).
- The tool must never imply official status, and must never present unverified content as university policy (see §11, Data integrity).

---

## 2. Goals and non-goals

### 2.1 Goals

| # | Goal |
|---|---|
| G1 | Answer recurring student questions **instantly** from the campus knowledge base |
| G2 | Cite the **source document and page** for every factual answer |
| G3 | **Refuse honestly** when the knowledge base does not support an answer — zero invented policies, dates, fees, or requirements |
| G4 | Be **open-source**: open-weight model, permissively licensed dependencies, public repository |
| G5 | Be **responsive and accessible** on desktop, tablet, and mobile |
| G6 | Be **maintainable**: modular, tested, documented, extendable by new contributors |

### 2.2 Non-goals (explicitly out of scope)

- Personal student records (marks, attendance, fee dues, login/accounts of any kind)
- Acting as an official or authoritative university communication channel
- Complex multi-turn advisory conversations (course planning, counselling)
- Automatic crawling of the public web or uncontrolled ingestion of unapproved sources
- Voice input/output, mobile-native apps
- Machine translation / Hinglish support in MVP (candidate for post-MVP; see §8)
- Any storage of personal or sensitive student data

---

## 3. Target users and personas

> All personas are **illustrative composites** created for planning purposes, not real individuals.

### 3.1 Primary user — "Aditya", first-year B.Tech student

- **Context:** New on campus, does not know which office handles what. Asks on WhatsApp groups and waits.
- **Questions:** "What is the hostel fee for a single occupancy room?", "When is IUET held?", "Which documents do I need at admission?"
- **Pain:** Gets conflicting answers from seniors; official PDFs are long and hard to search on a phone.
- **Need:** A fast, trustworthy answer he can verify by tapping the cited source.

### 3.2 Primary user — "Sana", final-year B.Pharm student

- **Context:** Busy, often asking from a phone between classes.
- **Questions:** Exam-related procedures, registration deadlines, scholarship renewals, course requirements.
- **Pain:** Repeated queries to the department office take days; answers vary by who is on duty.
- **Need:** Immediate answers with page-level citations she can screenshot and forward.

### 3.3 Secondary stakeholder — University staff (registry / department offices)

- **Context:** Handle high volumes of the same recurring questions.
- **Need (indirect):** Fewer repetitive inquiries; students arrive already informed. (CampusMate AI does not integrate with staff systems; the benefit is demand reduction.)

### 3.4 Usage contexts

- Mobile browsers on campus (dominant), desktop browsers in labs/hostels
- Primarily **English** (MVP); questions are short and factual (single-sentence)
- Network: campus Wi-Fi / mobile data — API latency and graceful offline/error behavior matter

---

## 4. Core product principles

Each principle below is operational — it maps to enforceable requirements.

| # | Principle | Operational meaning |
|---|---|---|
| P1 | **Knowledge-grounded answers** | Generated answers may only use content retrieved from the campus knowledge base (`FR-03`); model world-knowledge is excluded by prompt and validated by retrieval |
| P2 | **Source citations** | Every factual answer includes ≥1 citation with document title and PDF page (`FR-04`) |
| P3 | **Honest uncertainty** | No invented policies, dates, fees, deadlines, or requirements — enforced by a **two-layer abstention mechanism** (`FR-05`, `FR-06`) and verified by test battery (`SC-02`) |
| P4 | **Transparent limitations** | Refusal messages clearly state the limitation and suggest a safe next step (`FR-07`) |
| P5 | **Open-source compatibility** | Open-weight model + permissive dependencies; licenses verified and listed, not assumed (`NFR-07`) |
| P6 | **Responsive experience** | Polished, accessible UI from 360 px upward (`FR-22`, `NFR-05`) |
| P7 | **Maintainability** | Modular single-responsibility backend, tested core logic, documentation updated with every change (`NFR-08`, `NFR-10`) |
| P8 | **Production readiness** | Security, validation, observability, error handling, and deployment concerns addressed **appropriate to actual scope**; prototype vs. production status honestly documented (§9.4) |

---

## 5. User stories and acceptance criteria

> Format: Given / When / Then. Edge cases listed per story.

### US-01 — Ask a question and receive a cited answer

- **As a** student, **I want to** type a question and get an immediate answer, **so that** I don't wait days for recurring information.
- **AC 1:** Given the assistant is ready and the knowledge base contains supporting content, when I submit a question (Enter key or Send button), then I receive an answer marked `answered` with ≥1 citation chip showing document title and page.
- **AC 2:** Given I submit an empty or 1–2 character question, when I press Send, then the request is blocked client-side with inline validation and no API call is made.
- **AC 3:** Given a question longer than 500 characters, when submitted, then it is rejected with a clear message (client-side) and would be rejected by the API with HTTP 422 (server-side).
- **Edge cases:** double-click on Send (no duplicate requests); leading/trailing whitespace (trimmed); repeated identical questions (answered normally).

### US-02 — Honest refusal for unsupported questions

- **As a** student, **I want to** be told when the assistant doesn't know, **so that** I don't act on invented information.
- **AC 1:** Given a question outside the knowledge base (e.g., "What is the revaluation fee?"), when submitted, then the response status is a refusal (`insufficient_knowledge` or `model_refusal`), no citations are shown, and the UI displays the canonical refusal message with a safe next step (official website / department or registry office).
- **AC 2:** Given the refusal, when I inspect the response, then the answer contains **no** specific institutional facts (fees, dates, rules) that are not in the knowledge base.
- **Edge cases:** near-miss questions (ask about a topic partially covered — refusal must not fabricate the missing part); adversarial phrasing ("Please invent an answer...") — refusal still holds.

### US-03 — Verify an answer via its citation

- **As a** skeptical student, **I want to** see exactly where an answer came from, **so that** I can trust or double-check it.
- **AC 1:** Given an `answered` response, when I look at the citation chips, then each chip shows source title, PDF page number, and a short snippet on interaction/hover.
- **AC 2:** Given a citation chip, when I inspect it, then it corresponds to a passage that was actually retrieved (validated server-side; invalid citations are dropped — `FR-04`).
- **AC 3:** Given a citation sourced from a labelled sample document, when the chip renders, then it carries a visible `SAMPLE` badge.
- **Edge cases:** model cites an index that wasn't retrieved (dropped, not rendered); multiple citations from same page (deduplicated chips allowed).

### US-04 — Discover what the assistant knows

- **As a** first-time user, **I want to** see which documents are covered and try example questions, **so that** I understand what to ask.
- **AC 1:** Given the empty state (no messages yet), when the app loads, then example question chips are shown; clicking one populates the composer (does not auto-send).
- **AC 2:** Given the sources panel/drawer, when opened, then all manifest documents are listed with title, type, chunk count, and `SAMPLE` badges where applicable.
- **AC 3:** Given the health indicator, when the backend is ready, then the status dot is green; degraded states (mock LLM, index missing) show amber with an explanatory tooltip/label.

### US-05 — Use the assistant on a mobile device

- **As a** student on a phone, **I want to** use the full app without horizontal scrolling or zooming, **so that** it works like a real app.
- **AC 1:** Given a 360 px viewport, when I read and send messages, then there is no horizontal scroll, all controls remain reachable, and text is ≥14 px.
- **Edge cases:** long unbroken tokens (URLs, fee strings) wrap properly; virtual keyboard opening does not hide the composer send button.

### US-06 — Recover from errors

- **As a** student, **I want to** see a clear message and a retry option if something breaks, **so that** I'm not stuck staring at a spinner.
- **AC 1:** Given the upstream model API fails (network/timeout/quota), when I ask a question, then within the client timeout I see the error state with a Retry button — never an infinite spinner.
- **AC 2:** Given HTTP 429 (rate limited), when it occurs, then the UI shows a "too many requests, wait a moment" message.
- **AC 3:** Given the backend is unreachable, when a question is sent, then the error state renders and the health dot turns red.

### US-07 — Trust and transparency of sources

- **As a** judge or contributor, **I want to** see how the knowledge base is assembled, **so that** I can trust it and extend it.
- **AC 1:** Given the sources panel, when reviewed, then real sources and sample sources are visually distinguished (`SAMPLE` badge), and a note explains how approved sources are added.
- **AC 2:** Given a sample document, when answers derive from it, then the UI never presents it as official university material.

### US-08 — Keyboard and assistive technology access

- **As a** user relying on a keyboard/screen reader, **I want to** operate the app without a mouse, **so that** the app is usable by everyone.
- **AC 1:** Given only a keyboard, when I Tab through the page, then all interactive elements have visible focus and logical order.
- **AC 2:** Given a new assistant message arrives, when a screen reader is active, then the message is announced via an `aria-live` region.

---

## 6. Functional requirements

> IDs are canonical. Every FR maps to a build phase and test in `BUILD_PLAN.md` (traceability matrix).

### 6.1 Question answering

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-01 | Chat composer accepts a question, validates length (3–500 chars after trim), submits via Enter (Shift+Enter = newline), blocks double-submission | Empty/short input → inline error, no request; oversize → inline error; double-click → single request |
| FR-02 | `POST /api/ask` accepts `{question}` and returns a response with `status ∈ {answered, insufficient_knowledge, model_refusal, upstream_error}` | Valid request returns 200 with schema-valid body; invalid question → 422 |
| FR-03 | Answers are generated **only** from the retrieved passages (top-k, default 5); the prompt instructs the model to ignore its own knowledge and refuse if passages are insufficient | Prompt includes numbered passages + grounding instructions; prompt-injection-style questions ("answer from your own knowledge") still yield grounded/refused output |
| FR-04 | Every `answered` response carries ≥1 citation (`source_title`, `page`, `snippet`, `chunk_id`, `score`) validated as a subset of retrieved chunks; unsupported citation indices are dropped; if no citation survives, status downgrades to `model_refusal` | 100% of rendered citations map to retrieved chunks (`SC-03`) |
| FR-05 | **Abstention layer 1 (deterministic):** if the top BM25 score < `BM25_MIN_SCORE`, return `insufficient_knowledge` **without calling the model** | Unit test: out-of-scope query below threshold returns refusal with zero model calls |
| FR-06 | **Abstention layer 2 (model sentinel):** the model must begin refusals with the sentinel `NO_ANSWER_IN_KB:`; detection of the sentinel yields `model_refusal` | Unit test: canned sentinel output → `model_refusal`, no citations |
| FR-07 | Refusal responses (`insufficient_knowledge`, `model_refusal`) render the canonical refusal copy + safe next step, and contain **no** citations and **no** institutional facts | Battery case: every refuse-expected case passes (`SC-02`) |
| FR-08 | Answered UI: assistant bubble + citation chips + status badge; refusal UI: distinct styling (amber) with "not covered in sources" badge; error UI: message + Retry button | UI state matrix in `DESIGN.md` §14 implemented for all four statuses |

### 6.2 Knowledge base

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-09 | Sources are **only** files listed in `data/sources/manifest.json`; ingestion fails fast on unlisted files | Test: adding an unlisted file is ignored with a warning |
| FR-10 | Ingestion normalizes text (UTF-8, ligature fixes `ﬁ→fi`, stray backtick-to-₹ before digits) and removes **exact duplicate page content** | Test: duplicate pages in raw corpus produce one chunk set; `₹` rendered correctly |
| FR-11 | Chunking: ~600 chars, 100 chars overlap, paragraph-boundary preference, each chunk stores `chunk_id`, `source_id`, `source_title`, `page_start`, `page_end`, `is_sample` | Test: chunk sizes bounded (200–900 chars except single short pages); page spans monotonic |
| FR-12 | Sample documents: filename must start with `sample-` **and** manifest entry `is_sample: true`; ingestion validates both; citations from samples show `SAMPLE` badge | Test: `sample-x.txt` with `is_sample:false` → ingestion error |
| FR-13 | `python scripts/ingest.py` builds `index/chunks.json` + `index/bm25.pkl`; index is a generated artifact (gitignored), rebuildable from sources | Fresh clone → ingest command succeeds; index absent → health shows degraded |
| FR-14 | Empty state shows ≥4 example chips (drawn from answerable battery questions); click populates composer only | Manual check `US-04` |
| FR-15 | Loading state: typing indicator while awaiting response; composer guarded against duplicate sends | Manual check; double-send test |
| FR-16 | Status-driven rendering for all four statuses + Retry on error | See `US-06`, `US-01` |
| FR-17 | `GET /api/health` reports `{status, index_ready, llm_mode, model}`; UI status dot reflects it (green ready / amber degraded / red down) | API test + manual dot check |
| FR-18 | All configuration via environment variables documented in `.env.example`; `.env` gitignored; app fails fast at startup if `GEMINI_API_KEY` missing and `MOCK_LLM` not enabled | Test: missing key + `MOCK_LLM=false` → startup error naming the variable |
| FR-19 | Per-IP rate limiting (default 60 req/min, configurable) returns HTTP 429 with structured error body | API test with low limit → 429 |
| FR-20 | Structured single-line log per request: timestamp, request_id, status, latency_ms, top_score, truncated question (DEBUG only) | Log inspection |
| FR-21 | `MOCK_LLM=true` returns deterministic canned grounded responses (with citations) and canned refusals — enables keyless development and CI | API tests run with no network/key |
| FR-22 | Responsive layout: usable 360 px → 1920 px, breakpoints at 640 px / 1024 px, chat column max-width 800 px | `US-05` checks at 360/768/1440 |
| FR-23 | Persistent disclaimer footer ("independent open-source project, not affiliated with Integral University; informational only") + accessibility basics (`aria-live` log, keyboard support, visible focus) | `US-08`; footer visible on all breakpoints |

### 6.3 `GET /api/sources`

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-24 | Returns manifest documents with `title`, `type`, `is_sample`, `chunk_count`, `file`, and a `how_to_add` note describing the approved-source process | API test; panel renders list with sample badges |

---

## 7. Non-functional requirements

| ID | Requirement | Verification |
|---|---|---|
| NFR-01 | **Performance:** application overhead (retrieval + orchestration, excluding LLM) < 300 ms; end-to-end p90 ≤ 6 s over a 10-question sample on a normal connection | Timed battery run; latency field logged per request |
| NFR-02 | **Reliability:** upstream failure → 1 retry with backoff → model-id fallback → `upstream_error` (HTTP 502) — never an unhandled crash; missing index → degraded health + clear client message | Fault-injection API test (mock transport raising errors) |
| NFR-03 | **Security:** secrets only via env (gitignored); no stack traces or internal messages to clients; request body ≤ 8 KB; dependency versions pinned in `requirements.txt`; no auth needed (stateless, no PII) | Code review rule (AGENTS) + tests |
| NFR-04 | **Privacy:** questions are never persisted; logs record full question only at DEBUG level, truncated to 120 chars; no third-party analytics | Log inspection |
| NFR-05 | **Accessibility:** WCAG 2.1 AA contrast for text/status colors; complete keyboard operability; `aria-live` message announcements; `prefers-reduced-motion` respected | Manual a11y checklist (`tests/manual_ui_checklist.md`) |
| NFR-06 | **Compatibility:** latest Chrome/Edge/Firefox/Safari; Python 3.12; Windows/macOS/Linux path handling (`pathlib`, explicit UTF-8) | CI/local suite on dev platform; code review |
| NFR-07 | **Licensing:** all runtime dependencies permissively licensed; licenses **verified** (e.g., `pip show <pkg>`, source repo) and listed in README; Gemma distributed under Google's **Gemma Terms of Use** (open-weight, not OSI-approved) — documented honestly; project licensed MIT | `BUILD_PLAN` Phase 7 license audit task |
| NFR-08 | **Maintainability:** single-responsibility modules; type hints on public functions; core logic (ingest/retrieval/citation/abstention/API) covered by automated tests | `pytest -q` green; module ownership per `DESIGN.md` §6 |
| NFR-09 | **Observability:** `/api/health` liveness; per-request `request_id` propagated to logs and error bodies; status/latency greppable in logs | API + log checks |
| NFR-10 | **Documentation:** README quickstart (fresh clone → running ≤ 10 min with an API key); any API/structure change updates the four docs in the same change | AGENTS enforcement; fresh-clone rehearsal |

---

## 8. MVP scope vs. future enhancements

### 8.1 MVP (v1.0 — build this)

All FRs above. Summary: chat UI · BM25 retrieval over approved sources · Gemma generation via Google AI Studio · two-layer abstention · validated page-level citations · sources panel with sample labelling · config via env · rate limiting · logging/health · tests + question battery · README/LICENSE.

### 8.2 Stretch (v1.0 optional, only after MVP checkpoints pass)

| Item | Value |
|---|---|
| Dockerfile + one-command container run | Deployment credibility |
| Additional **approved** official sources (e.g., examination-related pages, subject handouts) pending team verification | Closes the known exam-regulation corpus gap |
| Simple deploy config (e.g., Render/Railway/Fly) | Demo URL for judges |

### 8.3 Post-MVP candidates (do not build now)

- Hybrid retrieval (BM25 + dense embeddings, e.g., a small open embedding model — license to be verified before adoption)
- Multi-turn conversation memory (client-supplied history)
- Hinglish/Hindi query understanding
- Answer streaming (SSE) for perceived latency
- Analytics dashboard for unanswered-question mining
- Admin UI for knowledge-base curation; official university integration/approval
- Per-user personalization (would require auth and a privacy review)

### 8.4 Prototype vs. production readiness (honest statement)

This document specifies a **functional prototype of production quality** (tests, security hygiene, observability), **not** a production deployment. Genuinely claiming "production ready" additionally requires, at minimum: hosted deployment with TLS, DNS, uptime monitoring/alerting, a rate-limit design that survives multiple workers/instances (in-memory limiter does not scale horizontally), university approval for source content and naming, a data-governance review, load testing, and an incident runbook. These are **unverified and not part of MVP acceptance.**

---

## 9. Success criteria (measurable)

A question **battery** (`tests/battery.json`) of ≥10 answerable and ≥5 unanswerable questions is the shared acceptance instrument for SC-01…SC-04.

| ID | Criterion | Target |
|---|---|---|
| SC-01 | Answerable battery: correct, grounded, cited answers | ≥ 8 / 10 pass |
| SC-02 | Unanswerable battery: honest refusal, zero fabricated institutional facts | 5 / 5 pass |
| SC-03 | Citation validity: rendered citations ⊆ retrieved chunks, page numbers correct | 100 % |
| SC-04 | Latency: p90 end-to-end across 10 mixed questions | ≤ 6 s |
| SC-05 | Fresh-clone setup (docs only, with API key in hand) | ≤ 10 min, rehearsed once |
| SC-06 | Automated suite | `pytest -q` fully green; every FR has an automated test **or** a checklist item |
| SC-07 | Responsiveness + accessibility spot checks (360 px, keyboard-only full ask, contrast) | All pass (`tests/manual_ui_checklist.md`) |
| SC-08 | Live demo: answer + citation + refusal shown end-to-end | ≤ 3 min, no failures |

---

## 10. Testing expectations

| Layer | Scope | Location |
|---|---|---|
| Unit | Text normalization, dedupe, chunking bounds, BM25 search ranking on known queries, threshold refusal, sentinel detection, citation validation/dropping, rate limiter | `tests/test_ingest.py`, `tests/test_retrieval.py`, `tests/test_generator.py`, `tests/test_api.py` |
| API integration | FastAPI `TestClient` + `MOCK_LLM=true`: 200 answered/refused flows, 422 validation, 429 rate limit, 502 upstream failure, health/sources contracts | `tests/test_api.py` |
| Contract | Response schema fields/types match `DESIGN.md` §8 exactly (Pydantic model is the runtime source of truth) | `tests/test_api.py` |
| Battery (functional QA) | `tests/battery.json` executed via `scripts/run_battery.py`; reports pass/fail per case with `must_contain` substring + `must_cite` checks | `scripts/run_battery.py` |
| Manual UI checklist | All four UI states, mobile widths, keyboard-only flow, citation chips, sources panel, disclaimer, a11y | `tests/manual_ui_checklist.md` |

**Rule:** no phase in `BUILD_PLAN.md` is complete until its tests/checks pass (enforced by `AGENTS.md`).

---

## 11. Assumptions, dependencies, and data integrity

### 11.1 Assumptions

| ID | Assumption |
|---|---|
| A-01 | The team supplies a valid Google AI Studio API key via `.env` (`GEMINI_API_KEY`). **Keys are never committed or fabricated;** development/tests can proceed keyless with `MOCK_LLM=true`. |
| A-02 | The provided `Prospectus.pdf` (145 pages, extractable text — verified) is an official Integral University document supplied by the team. Its **edition/year is to be confirmed from the document**; until confirmed, it is referenced as "Integral University Prospectus" (no invented year). |
| A-03 | Citations use **PDF page numbers** (1-based position in the file). Printed folio numbers may differ from PDF page positions; this is documented and consistent. |
| A-04 | Internet access is available for the Gemini API during demos; otherwise `MOCK_LLM` degrades gracefully (never silently — health/dot show amber). |
| A-05 | English-only MVP; questions are short factual queries. |
| A-06 | The corpus gap on **examination regulations** is acknowledged; the assistant must refuse those questions until approved sources are added (never guess). |

### 11.2 External dependencies to be supplied separately

1. `GEMINI_API_KEY` (team-provided; `.env.example` contains placeholder only)
2. Approved university source documents (beyond the provided prospectus)
3. Hosting/domain if deployed (stretch)
4. University approval before any claim of official affiliation (explicitly out of scope)

### 11.3 Data integrity rules

- **Verified information:** content extracted from the team-provided Prospectus PDF; public domain facts (e.g., `iul.ac.in`, the admission contact printed in the prospectus).
- **Sample data:** any document not verified as official **must** be named `sample-*.txt`, flagged `is_sample: true` in the manifest, watermarked with a header line `SAMPLE DOCUMENT — NOT AN OFFICIAL UNIVERSITY SOURCE`, and carry a `SAMPLE` badge in every citation.
- **Never fabricate:** university policies, dates, fees, credentials, API keys, official endorsements, or statistics. Placeholders must be visibly marked (`TODO`, `your_key_here`).
- **Approved-source process:** place file in `data/sources/` → add manifest entry (with verification status) → run `python scripts/ingest.py` → verify via sources panel and battery. Documented in README and `FR-09`/`FR-12`.

---

## 12. Requirement traceability

Every FR/NFR/SC above is mapped to a build phase and a verification step in `BUILD_PLAN.md` → **Requirement Traceability Matrix**. No phase may be marked complete while any requirement mapped to it is unimplemented or failing.
