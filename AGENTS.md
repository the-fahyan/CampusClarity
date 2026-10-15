# CampusMate AI — AI Agent Development Rules (`AGENTS.md`)

| Field | Value |
|---|---|
| Purpose | Binding, enforceable rules for any AI coding agent (or human contributor) working on this repository |
| Companion documents | `PRD.md` (what) · `DESIGN.md` (how) · `BUILD_PLAN.md` (order) |
| Version | 1.0 |
| Last updated | 2026-10-16 |

These rules exist to prevent architectural drift, fabricated results, and undocumented changes. **Non-compliance blocks phase completion** (see §14).

---

## 1. Document precedence and conflict resolution

When documents appear to disagree, resolve in this order — and **never resolve silently**:

| Question type | Authority |
|---|---|
| *What must the product do?* (features, requirements, acceptance criteria) | `PRD.md` |
| *How is it implemented?* (structure, endpoints, schemas, tech choices, design tokens) | `DESIGN.md` |
| *What process must be followed?* (this file) | `AGENTS.md` |
| *In what order / what phase?* | `BUILD_PLAN.md` |
| Canonical terms (endpoint names, status values, env vars, paths, IDs) | The file in which they are defined; all others must match it |

**Conflict procedure (mandatory):**

1. Stop work on the conflicting change.
2. Record the conflict in `docs/DECISIONS.md`: date, documents/lines, nature, proposed resolution, rationale.
3. Apply the precedence table above. If the conflict reveals a genuine requirement gap, treat it as "missing requirement" (§2).
4. Fix the *losing* document so all four describe one application, in the same change as the code fix.
5. Report the conflict and resolution in the phase report (§15).

**Missing or ambiguous requirements:**

- Make the most practical conservative assumption **consistent with the PRD's product principles** (knowledge grounding, honest uncertainty, open-source, no fabrication).
- Log it in `docs/DECISIONS.md` as `ASSUMPTION:` with rationale and impact if wrong.
- If the ambiguity affects observable behavior (copy text, endpoints, statuses, acceptance criteria), update `PRD.md`/`DESIGN.md` accordingly and mention it in the phase report.
- **Never** invent product behavior that no document covers without logging it as a decision.

---

## 2. Session start protocol (every session, no exceptions)

1. **Read, in order:** `BUILD_PLAN.md` (find first incomplete phase via checkboxes), `PRD.md` §6–§7 (active requirement IDs), `DESIGN.md` sections named by that phase.
2. **Inspect before editing:** open every file you intend to modify and read it fully (plus neighbors named in `DESIGN.md` §1 §1's component table). Never edit a file you have not read this session. Never assume a file's contents.
3. **Establish baseline:** run `pytest -q` and record the result. If the suite was red at session start, say so — do not attribute pre-existing failures to your changes.
4. **Check `docs/DECISIONS.md`** for unresolved assumptions.
5. **Work only on the current phase's tasks.** Do not pre-build later phases or opportunistically refactor unrelated code.

---

## 3. Architectural boundaries

- **Module responsibilities are fixed by `DESIGN.md` §1.2.** Routes do not contain business logic; `service.py` does not perform HTTP calls; `generator.py` does not retrieve; frontend does no truth-deciding logic (it renders statuses).
- **The ask-pipeline control flow in `DESIGN.md` §6.1 is authoritative.** Changes require updating that section and the traceability matrix in `BUILD_PLAN.md`.
- **Layer-1 abstention must never call the model** (FR-05). Do not "simplify" by merging the gate into prompting.
- **Citations must be validated server-side against retrieved chunk IDs** (D-9, FR-04). Never render model-supplied citation data directly.
- **No new services, databases, queues, frameworks, or background workers** unless a phase task requires them and the design documents are updated first.

---

## 4. File organization and naming

- Use the **canonical tree** in `DESIGN.md` §4. Place files where that tree says — no new top-level directories, no dumping files at root, no renaming without updating all four documents.
- Python modules: `snake_case.py`, one primary responsibility each, each file in `backend/` has a module docstring stating its responsibility (match the table in `DESIGN.md` §1.2).
- Tests: `tests/test_<module>.py` mirroring the module under test. Fixtures in `tests/conftest.py`.
- Env vars, statuses, endpoint paths, schema fields: **verbatim from `DESIGN.md`** (§6.2 config table, §5.4 status enum, §8 endpoints). No local spellings, no variants.

**Canonical terms quick-reference** (DESIGN.md remains the source of truth; this table exists so the rules here are enforceable without opening another file — if they ever diverge, DESIGN.md wins and this table must be updated in the same change):

| Kind | Canonical values |
|---|---|
| Ask-response `status` enum | `answered` · `insufficient_knowledge` · `model_refusal` · `upstream_error` |
| Error-body `status` values | `validation_error` · `rate_limited` · `kb_unavailable` · `upstream_error` · `internal_error` |
| Endpoints | `POST /api/ask` · `GET /api/health` · `GET /api/sources` |
| Refusal sentinel (model output) | `NO_ANSWER_IN_KB:` |
| Citation line (model output) | `Sources: [n], [m]` |
| Core env vars | `GEMINI_API_KEY` · `GEMMA_MODEL_ID` · `GEMMA_FALLBACK_MODEL_ID` · `BM25_MIN_SCORE` · `BM25_TOP_K` · `RATE_LIMIT_PER_MINUTE` · `MOCK_LLM` · `APP_HOST` · `APP_PORT` · `LOG_LEVEL` |
| Generated artifacts (never commit) | `index/chunks.json` · `index/bm25.pkl` |

- Requirement references in comments/tests: use PRD IDs (`FR-05`, `NFR-02`) so traceability stays greppable.

---

## 5. Coding conventions

**Python (3.12)**

- Type hints on all public function signatures; Pydantic models for any external data (env, files, API).
- Follow the existing style of the file you are in. Formatting must stay consistent (if a formatter is adopted, it applies to the whole repo in one change).
- Prefer small pure functions for logic (normalization, parsing, gating) — they are the unit-tested core.
- Strings that users see come from **`DESIGN.md` §13 canonical copy** or `prompts.py` — not ad-hoc literals scattered across files.
- Use `pathlib.Path` and explicit `encoding="utf-8"` on all file I/O (Windows-safe, NFR-06). Reconfigure stdout to UTF-8 in scripts that print corpus text.
- Raise typed exceptions (`UpstreamError`, `KnowledgeBaseError`, `ConfigError`) — never bare `except:` and never `except Exception: pass`.

**JavaScript / HTML / CSS (vanilla, no build step — D-5)**

- `app.js`: one `render(state)`-style path per UI state as in `DESIGN.md` §10.2; `fetch` with explicit timeout via `AbortController`; all API calls through a single small helper.
- No frameworks, no CDN scripts, no external font requests (`DESIGN.md` §10.3) — the page must work offline-served.
- All visual values (colors, spacing, radii, breakpoints) come from `styles.css` tokens — **no ad-hoc hex colors or magic pixel values in components**.
- Semantic HTML (`role="log"`, `aria-live`, headings, labels); every interactive element keyboard-reachable.

---

## 6. Dependency management

1. Before adding any dependency: **can the standard library or an existing dependency do this?** If yes, do not add it.
2. New dependencies require, in the same change: a `requirements.txt` update with a **bounded range** (`>=X,<Y`), a one-line justification, license verification (`pip show <pkg>` → record in README license table), and a note in the phase report.
3. No unpinned `pip install <latest>` sprawl, no dependency for a ten-line utility, no abandoned/unlicensed packages.
4. Dev-only tools (pytest) stay in the dependency list but must not be imported outside `tests/` and `scripts/` QA tooling.
5. Removing a dependency: update `requirements.txt` + README license table + any docs that mention it.

---

## 7. Secrets and configuration

- **Never hardcode, fabricate, or commit secrets** — API keys, tokens, passwords. `.env` is gitignored; `.env.example` holds placeholders (`your_key_here`).
- Never paste a real key into chat, code, tests, fixtures, logs, docs, or commit messages. If a key is discovered in tracked files: stop and report immediately.
- Configuration differences between environments are expressed **only** through the env vars listed in `DESIGN.md` §6.2. No hidden config files.
- Code may reference `settings.GEMINI_API_KEY`; tests use `MOCK_LLM=true` and require no key.

---

## 8. Data integrity and university content (highest-severity rule)

- **Never fabricate university information** — policies, dates, fees, deadlines, exam rules, contacts, statistics, rankings, official names, or endorsements. Not in code, tests, sample answers, docs, UI copy, or demo material.
- Verified content comes only from team-provided source files in `data/sources/`. Everything else is a **sample** and must be labeled on all three levels: filename `sample-*`, manifest `is_sample: true`, and UI `SAMPLE` badge (FR-12).
- Sample documents must carry the header line `SAMPLE DOCUMENT — NOT AN OFFICIAL UNIVERSITY SOURCE` and must never be described as official in UI or docs.
- Test/battery questions that expect answers must contain expected substrings **actually present in the corpus** (e.g., `1,05,000`) — verify with `scripts/search_cli.py` before asserting; never assert a "fact" you haven't seen in a source.
- Do not state the prospectus's edition/year anywhere until confirmed from the document (PRD A-02).
- Product framing stays per PRD §1.4: independent, unofficial, informational. Do not add UI text or README claims implying university affiliation.
- Placeholders must be visibly marked (`TODO`, `your_key_here`, `TBC`).

---

## 9. API contract and documentation sync

Any change to endpoints, schemas, statuses, env vars, file paths, or user-visible copy **must**, in the same change:

1. Update `backend/schemas.py` (runtime truth),
2. Update `DESIGN.md` (§5–§8, §13 as applicable),
3. Grep `PRD.md` for affected FR/NFR/SC IDs and reconcile,
4. Confirm `BUILD_PLAN.md` phases/tests still describe reality,
5. Mention the sync in the phase report.

Adding **new** product behavior without a PRD requirement is prohibited (log in `docs/DECISIONS.md` and get it into `PRD.md` first).

---

## 10. Error handling and edge cases

- Every external boundary (model API, index files, manifest) has explicit failure handling mapped per `DESIGN.md` §6.8 (status → HTTP → message). Client messages come from that table — never raw exception text.
- Handle: empty/oversized input, missing index, malformed manifest, unreadable source file, upstream timeout/429/5xx, JSON parse failure in model output, citation parse failure, rate limit hit. Unhandled exceptions must still return the sanitized 500 body with `request_id`.
- Never swallow errors (`pass`), never bare `except:`; log with `request_id`, respond generically.
- Fail fast at startup for configuration errors (missing key without mock) with a message naming the variable.

---

## 11. Security

- Treat model output and retrieved document text as **untrusted display data**: render assistant output as text (DOM `textContent`, never `innerHTML` for model/corpus strings).
- The prompt-injection stance is fixed: system prompt scopes answers to passages (DESIGN §6.6); do not weaken it; keep a battery case covering it.
- No secrets in frontend code; no eval; no `innerHTML` interpolation of user/API data; no new network origins (same-origin only).
- Body-size and length limits enforced server-side regardless of client checks.
- Do not add authentication/authorization layers without a PRD update (explicitly out of scope).

---

## 12. Accessibility (must accompany any UI change)

- New/changed UI: keyboard operable, visible focus, text labels (never color-only meaning), contrast ≥ 4.5:1, `aria-live` announcements for new messages/errors, `prefers-reduced-motion` respected, 360 px no horizontal scroll.
- Update `tests/manual_ui_checklist.md` when states/flows change; run the affected checklist items before phase completion.

---

## 13. Testing and debugging rules

- **Every phase's tests pass before its checkbox is checked.** Run `pytest -q` before claiming any work complete; include real output in the report.
- New logic ships with tests in the same change (normalization, parsing, gating, endpoints). Reuse `tests/conftest.py` fixtures; build tiny synthetic indexes in tmp dirs — **never mutate the real `index/` or `data/`**.
- Tests are deterministic and offline: `MOCK_LLM=true`, mocked transports for retry/fallback/error paths, no live API in `pytest`.
- **Never weaken, skip, or delete a test to make the suite green.** If a test is wrong, fix the test *and justify it in the report*. Never fabricate test output or claim runs you did not perform.
- Debugging: reproduce first (CLI/script), isolate (unit test reproducing the bug), fix, then regression-test. Log with `request_id`; do not add `print()` debugging to committed code (scripts may print intentional output).
- Faults to exercise intentionally: missing index, wrong key, upstream 429/500/timeout (mock transport), oversized question, malformed manifest, duplicate source entries.

---

## 14. Prohibitions (explicit)

Do **not**:

1. Add dependencies, endpoints, files, or features not required by a phase task or PRD FR.
2. Duplicate logic that exists elsewhere (normalization/tokenization/copy live in one place each — reuse or refactor into that place).
3. Hardcode secrets or commit `.env`.
4. Fabricate university data, credentials, keys, or official policies (§8).
5. Weaken/skip tests, or report results not actually observed.
6. Bypass the abstention gate, citation validation, or disclaimer to make a demo "look better".
7. Make undocumented architectural changes or rename canonical terms (§9).
8. Commit generated artifacts (`index/`), virtualenvs, caches, or OS junk (respect `.gitignore`; add patterns if missing).
9. Use `innerHTML`/`eval` on untrusted strings; disable accessibility features for convenience.
10. Silently resolve document conflicts or leave `docs/DECISIONS.md` entries stale without a note.
11. Touch files outside the current phase's scope without stating why in the report.
12. Claim "production ready" — the honest status is "functional prototype" until `PRD` §8.4 is satisfied.

---

## 15. Verification and completion reporting (phase report template)

At the end of every phase (or session), verify then report. Verification minimum: run the phase's checkpoint commands **plus** full `pytest -q`, and confirm the health endpoint manually when applicable.

```markdown
## Phase Report — Phase <n> (<date>)
- **Implemented:** <files created/changed, mapped to FR/NFR IDs>
- **Verified:** <commands run and their ACTUAL outcomes — paste key output lines>
- **Tests:** <pytest summary line: e.g. "24 passed"> · new tests added: <list>
- **Checklist:** <manual items run: e.g. UI checklist §states at 360px — pass/fail>
- **Deviations:** <anything differing from PRD/DESIGN, with DECISIONS.md entry ID; or "none">
- **Incomplete / next:** <remaining tasks for the phase or the next phase's entry state>
- **Docs updated:** <which of the four documents changed, or "no sync needed">
```

**Definition of Done (phase):** tasks complete + checkpoint commands pass + `pytest -q` green + report issued + checkboxes/status table updated in `BUILD_PLAN.md`.

**Definition of Done (v1.0):** `BUILD_PLAN.md` §9 final acceptance checklist fully checked.

---

## 16. Resuming work (context limits, interruptions, new session)

Follow §2, then:

1. Read `BUILD_PLAN.md` **status table** + first unchecked phase; read `docs/DECISIONS.md`.
2. Run `pytest -q` and `python -c "from pathlib import Path; print('index ok' if Path('index/chunks.json').exists() else 'index MISSING')"` to ground reality.
3. `git status`/`git log --oneline -5` if a repo exists — identify half-finished work; finish or revert it before starting new tasks (no orphan half-changes).
4. Re-read only the design sections the current phase needs — do not re-read everything.
5. Resume at the first incomplete task of the first incomplete phase; update its checkbox and status row as you complete items.
6. If the last session's work conflicts with documents, follow §1 conflict procedure before building on it.
