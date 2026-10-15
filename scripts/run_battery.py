"""Run the QA battery (tests/battery.json) through the service layer.

Responsibility (DESIGN.md §1.2, §10): execute the answerable/refuse battery, check
`must_contain` + `must_cite` per case, print a pass/fail report with statuses,
citation validity, and latency, and summarise against the SC targets.

Usage: python scripts/run_battery.py            # honours MOCK_LLM from .env
       MOCK_LLM=true python scripts/run_battery.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

from backend.config import Settings  # noqa: E402
from backend.generator import Generator  # noqa: E402
from backend.retrieval import RetrievalIndex  # noqa: E402
from backend.service import AnswerService  # noqa: E402


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((pct / 100) * len(ordered) + 0.5)) - 1))
    return float(ordered[k])


def main() -> int:
    battery_path = ROOT / "tests" / "battery.json"
    battery = json.loads(battery_path.read_text(encoding="utf-8"))
    settings = Settings()  # type: ignore[call-arg]
    index = RetrievalIndex.load(ROOT / "index")
    service = AnswerService(settings, index, Generator(settings))

    print(f"mode={settings.llm_mode}  threshold={settings.BM25_MIN_SCORE}  "
          f"top_k={settings.BM25_TOP_K}")
    print("=" * 78)

    latencies: list[int] = []
    invalid_citations = 0
    answered_pass = 0
    answerable = battery.get("answerable", [])
    for case in answerable:
        result = service.ask(case["question"], "battery")
        latencies.append(result.latency_ms)
        retrieved_ids = {p.chunk_id for p in index.search(case["question"], settings.BM25_TOP_K).passages}
        valid = all(c.chunk_id in retrieved_ids for c in result.citations)
        if not valid:
            invalid_citations += 1
        answer_lower = result.answer.lower()
        missing = [s for s in case.get("must_contain", []) if s.lower() not in answer_lower]
        cited_ok = (not case.get("must_cite", True)) or bool(result.citations)
        passed = result.status == "answered" and not missing and cited_ok and valid
        answered_pass += int(passed)
        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {case['id']} top={result.retrieval.top_score:7.2f} "
              f"{result.latency_ms:5d}ms status={result.status}")
        print(f"       Q: {case['question']}")
        if not passed:
            reasons = []
            if result.status != "answered":
                reasons.append(f"status={result.status}")
            if missing:
                reasons.append(f"missing={missing}")
            if not cited_ok:
                reasons.append("no citation")
            if not valid:
                reasons.append("invalid citation")
            print(f"       ! {', '.join(reasons)}")
        print(f"       A: {result.answer[:120]}")

    print("-" * 78)
    refuse = battery.get("refuse", [])
    refuse_pass = 0
    for case in refuse:
        result = service.ask(case["question"], "battery")
        latencies.append(result.latency_ms)
        refused = result.status in {"insufficient_knowledge", "model_refusal"}
        no_cites = len(result.citations) == 0
        passed = refused and no_cites
        refuse_pass += int(passed)
        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {case['id']} top={result.retrieval.top_score:7.2f} "
              f"{result.latency_ms:5d}ms status={result.status} cites={len(result.citations)}")
        print(f"       Q: {case['question']}")
        if not passed:
            print(f"       ! expected refusal with no citations")
        print(f"       A: {result.answer[:120]}")

    print("=" * 78)
    total_cases = len(answerable) + len(refuse)
    p90 = _percentile(latencies, 90)
    print("SUMMARY vs success criteria")
    print(f"  SC-01 answered:  {answered_pass}/{len(answerable)} "
          f"(target >= 8/10)  {'PASS' if answered_pass >= 8 else 'FAIL'}")
    print(f"  SC-02 refused:   {refuse_pass}/{len(refuse)} "
          f"(target 5/5)      {'PASS' if refuse_pass == len(refuse) else 'FAIL'}")
    print(f"  SC-03 citations: {100.0 - (invalid_citations / max(1, len(answerable)) * 100):.0f}% valid "
          f"(target 100%)     {'PASS' if invalid_citations == 0 else 'FAIL'}")
    print(f"  SC-04 p90 latency: {p90:.0f} ms over {total_cases} cases "
          f"(target <= 6000) {'PASS' if p90 <= 6000 else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
