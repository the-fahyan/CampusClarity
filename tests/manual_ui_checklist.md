# CampusMate AI — Manual UI checklist

> Scope: `DESIGN.md` §10–§11 (states, responsive, a11y). Run against a live server
> (`MOCK_LLM=true python -m uvicorn backend.main:app`) in a browser. Record result per row.

## Setup

```
python scripts/ingest.py
$env:MOCK_LLM="true"; python -m uvicorn backend.main:app
open http://127.0.0.1:8000
```

## A. States matrix (§10.2, §11)

| # | State | Steps | Expected | Result |
|---|---|---|---|---|
| A1 | Empty | Load page | Welcome text + ≥4 example chips; disclaimer footer visible | |
| A2 | Example chip | Click a chip | Composer fills; **no** message sent | |
| A3 | Sending | Send a question | Typing indicator; Send disabled; prior messages remain; live region announces | |
| A4 | Answered | Send "What is the hostel fee for a single occupancy room?" | Green "Grounded answer" badge + ≥1 chip "📄 … · p.NN" + inline `[n]` marker | |
| A5 | Refused | Send "What is the revaluation fee policy?" | Amber "Not in my sources" badge; canonical copy + tip; **no chips** | |
| A6 | Error | Stop the backend, send a question | Error card + Retry; status dot red; Retry re-sends | |
| A7 | Rate limited | Send >60 requests/min (or set `RATE_LIMIT_PER_MINUTE=3`) | "Too many requests — wait a moment" | |
| A8 | Degraded | Run in mock mode | Amber dot + "Sample mode (mock)" label | |

## B. Citation & sources (US-03, US-04, US-07, FR-24)

| # | Check | Expected | Result |
|---|---|---|---|
| B1 | Citation chip content | Shows source title and PDF page | |
| B2 | Chip interaction | Focus/click reveals snippet popover (≈150 chars) + score | |
| B3 | Sample badge | A citation from a `sample-*` source shows a `SAMPLE` badge | |
| B4 | Sources drawer | Opens with Esc-to-close, focus returns to trigger; lists manifest docs with type/chunks/pages + how-to-add note | |
| B5 | Citations on refusal | Refusal turns contain **no** chips | |

## C. Responsive (US-05, FR-22)

| # | Width | Expected | Result |
|---|---|---|---|
| C1 | 360 px | No horizontal scroll; controls reachable; text ≥14 px; tagline hidden | |
| C2 | 768 px | Centered column; drawer overlay | |
| C3 | 1440 px | Centered 800 px column; drawer side panel | |
| C4 | Long unbroken token (fee string/URL) | Wraps without overflow | |

## D. Keyboard & accessibility (US-08, NFR-05, FR-23)

| # | Check | Expected | Result |
|---|---|---|---|
| D1 | Tab order | Header → log → composer; every control reachable | |
| D2 | Visible focus | `:focus-visible` ring on all interactive elements | |
| D3 | Text labels | No meaning conveyed by color alone (badges have text) | |
| D4 | Live region | New assistant message announced (`role="log"` `aria-live="polite"`) | |
| D5 | Enter / Shift+Enter | Enter sends; Shift+Enter inserts newline | |
| D6 | Reduced motion | `prefers-reduced-motion: reduce` disables typing animation/auto-scroll animation | |
| D7 | Disclaimer | Footer disclaimer visible on every state/breakpoint | |
| D8 | Skip link | Visible on focus; jumps to the question box | |

## E. Client validation (FR-01, US-01)

| # | Input | Expected | Result |
|---|---|---|---|
| E1 | Empty / 2 chars | Blocked with inline message; no API call | |
| E2 | 501 chars | Maxlength prevents typing past 500; 500 allowed | |
| E3 | Double-click Send | Only one request (Send disabled while sending) | |
| E4 | Whitespace around question | Trimmed before sending | |
