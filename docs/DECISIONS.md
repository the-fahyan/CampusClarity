# Decision & Assumption Log — CampusMate AI

> Per `AGENTS.md` §1/§2. Format: `ASSUMPTION:` / `DECISION:` / `CONFLICT:` with date, rationale, impact if wrong.
> Canonical source of truth is `DESIGN.md`; entries here record ambiguity resolutions and deviations only.

---

## Seeded entries (Phase 0)

### ASSUMPTION — Prospectus edition/year TBC (PRD A-02)

- **Date:** 2026-10-16
- **Context:** `PRD.md` A-02 requires the prospectus edition/year to be confirmed from the document before it is stated anywhere.
- **Decision:** Reference the source only as "Integral University Prospectus". No year is printed in the manifest, UI, README, or answers until confirmed.
- **Impact if wrong:** None — the conservative choice (omit the year) is always safe; adding a year is a later, additive change.

### ASSUMPTION — BM25 threshold starts at 4.0 (uncalibrated)

- **Date:** 2026-10-16
- **Context:** `DESIGN.md` §6.2 sets `BM25_MIN_SCORE` default `4.0`; `BUILD_PLAN.md` Phase 6 calibrates it against the battery.
- **Decision:** Ship provisional `4.0`; collect per-case top-1 scores in Phase 6 and adjust with a documented margin (prefer over-refusal to hallucination, R3).
- **Impact if wrong:** False refusals (unhelpful) or false answers (unacceptable) — mitigated by calibration + honest note.

### ASSUMPTION — Exam-regulation corpus gap acknowledged (PRD A-06)

- **Date:** 2026-10-16
- **Context:** The provided prospectus does not contain examination regulations; the assistant must refuse such questions.
- **Decision:** Refusal (both layers) is a **scored feature** (SC-02), not a defect; refusal demo covers the gap. Adding approved exam sources is deferred to Phase 8 (stretch).
- **Impact if wrong:** Judges misread a refusal as a failure — mitigated by framing plus a documented next-step in the refusal copy.

---

## Phase 1 — Knowledge base ingestion

### DECISION — Shared text utilities live in `backend/textutils.py`

- **Date:** 2026-10-16
- **Context:** `BUILD_PLAN.md` Phase 1 task 5 requires a **single** tokenizer/normalization implementation shared by ingestion and runtime retrieval; a new file needs a DECISIONS entry.
- **Decision:** Add `backend/textutils.py` holding `normalize_text()` and `tokenize()` (index + query use the identical path). `scripts/ingest.py` imports it rather than duplicating logic.
- **Impact if wrong:** Only a structural placement choice; no behavioral risk. Keeps FR-10/FR-11 logic in one place (AGENTS §14.2).

### DECISION — Page markers drive chunk page spans

- **Date:** 2026-10-16
- **Context:** The corpus was extracted with `===== PAGE n =====` markers (145 pages).
- **Decision:** `ingest.py` splits on those markers; page numbers are 1-based **PDF page positions** (PRD A-03). Printed folio numbers are not mapped.
- **Impact if wrong:** Citations use PDF page positions consistently, per design; no correctness risk.

---

## Phase 2 — Retrieval

### DECISION — Tokenizer number handling

- **Date:** 2026-10-16
- **Context:** `DESIGN.md` §6.4 requires `1,05,000` and `105000` to match.
- **Decision:** `tokenize()` emits each numeric run **and** its comma-stripped variant. Query and index use the same function.
- **Impact if wrong:** None — extra tokens only improve recall for numeric strings.

---

## Phase 3 — AI integration

### ASSUMPTION — Gemma model IDs unverified in this environment

- **Date:** 2026-10-16
- **Context:** `BUILD_PLAN.md` Phase 3 requires verifying real model IDs against AI Studio; no live `GEMINI_API_KEY` is available in the development environment at build time.
- **Decision:** Keep documented defaults `gemma-3-27b-it` / fallback `gemma-3-12b-it`; `scripts/smoke_gemma.py` verifies them the moment a key is supplied. All automated tests run under `MOCK_LLM=true` (FR-21); `.env` for local dev sets `MOCK_LLM=true` so the prototype runs without a key.
- **Impact if wrong:** Live mode requires a real key + confirming/updating the model IDs — the smoke script and README document this; nothing is fabricated.

---

## Phase 6 — Threshold calibration (record produced after battery run)

### DECISION — Calibrated `BM25_MIN_SCORE` = 10.5

- **Date:** 2026-10-16
- **Context:** Battery top-1 scores over the bundled 743-chunk prospectus index. The original
  placeholder `4.0` (DESIGN §6.2) is far below the observed score distribution:
  - in-scope examples: hostel single-occupancy fee `34.0`, refundable security fee `25.3`,
    caution money `24.7`, application form `21.4`, admission online `21.4`, IUET `20.0`,
    scholarship `17.0`, AC room `17.4`, laundry `29.4` (min in-scope ≈ 11.6).
  - out-of-scope examples: revaluation fee `10.0`, re-today's mess menu `7.1`,
    official transcript `10.5`, examination re-totaling `10.0`.
- **Decision:** Set `BM25_MIN_SCORE=10.5`. This refuses the clearly-unrelated tail at **layer 1
  (no model call)** while passing all answerable battery cases (min ≈ 11.6). Topically-close
  out-of-scope questions that score above the gate (e.g., "quantum entanglement syllabus…") are
  refused by **layer 2** (model sentinel) and by server-side citation validation — as designed
  (D-3). `BUILD_PLAN.md` Phase 2's illustrative expectation of "< 4.0" for the adversarial query
  was not attainable on a corpus this size; recorded here per AGENTS §1.
- **Trade-off:** Over-refusal is preferred to hallucination (R3); the threshold is corpus-specific
  and must be re-calibrated whenever the sources change (re-run `scripts/run_battery.py`).
- **Docs synced:** `DESIGN.md` §6.2 + §5.4 example; `.env.example`; `backend/config.py`.

### DECISION — `MOCK_LLM=true` is the default for local/keyless demos

- **Date:** 2026-10-16
- **Context:** No live `GEMINI_API_KEY` is available in the build environment; FR-18 requires
  fail-fast when live mode is requested without a key.
- **Decision:** Ship `.env` for the prototype with `MOCK_LLM=true` so the app runs immediately.
  Mock mode returns **grounded** canned answers (a sentence quoted from the retrieved passage,
  with a valid citation) or a sentinel refusal — never an ungrounded claim — and `/api/health`
  reports `llm_mode: "mock"` (amber dot). The full test suite and battery run keylessly.
- **Impact if wrong:** Live answer quality is unverified until a real key is supplied; this is
  stated in the README and phase report rather than claimed as tested.

### DECISION — Mock mode mirrors the prompt-injection stance

- **Date:** 2026-10-16
- **Context:** AGENTS §11 requires a battery case covering prompt injection; mock responses must
  not fabricate institutional facts either.
- **Decision:** The mock refuses (sentinel) when the question contains injection triggers
  ("from your own knowledge", "invent", "ignore the sources", …) and otherwise answers only by
  quoting a retrieved passage. Covered by battery case R5.

### ASSUMPTION — Live battery (SC-01…SC-04) still pending a key

- **Date:** 2026-10-16
- **Context:** The battery was executed in mock mode: SC-01 8/10, SC-02 5/5, SC-03 100% citation
  validity, SC-04 pass. Live-mode results depend on Gemma and cannot be produced without a key.
- **Decision:** Report mock results honestly; re-run `python scripts/run_battery.py` with
  `MOCK_LLM=false` and a real key before a live demo.
