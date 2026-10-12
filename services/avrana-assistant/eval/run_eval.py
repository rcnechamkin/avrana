#!/usr/bin/env python3
"""Deterministic evaluation of the A0 retrieval and guard layers with a fake provider.

This measures retrieval and guard behaviour. It does NOT measure the answer quality of any real model:
the FakeProvider is extractive (or deliberately hostile), so fluency, helpfulness and faithfulness of a
real model are out of scope here (AVR-404 in A1).

Usage:
  python -B services/avrana-assistant/eval/run_eval.py                 # rules provider
  python -B services/avrana-assistant/eval/run_eval.py --provider hostile
  python -B services/avrana-assistant/eval/run_eval.py --json
"""
from __future__ import annotations

import argparse
import functools
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE = HERE.parent
sys.path.insert(0, str(SERVICE))

from avrana_assistant.budget import BudgetConfig, BudgetGuard  # noqa: E402
from avrana_assistant.datatypes import ANSWER, Principal  # noqa: E402
from avrana_assistant.pipeline import AnswerPipeline  # noqa: E402
from avrana_assistant.provider import HOSTILE_KINDS, FakeProvider  # noqa: E402
from avrana_assistant.retrieval import Corpus  # noqa: E402

GOLDEN = HERE / "golden.json"
MANIFEST = SERVICE / "corpus" / "manifest.json"

# Synthetic configuration; arbitrary numbers, not any provider's prices or limits.
EVAL_BUDGET = {
    "prices": {"default": {"input_per_1k_micro": 100, "output_per_1k_micro": 300}},
    "per_request_max_tokens": 4000, "per_request_max_cost_micro": 5000,
    "member_daily_tokens": 10_000_000, "member_daily_cost_micro": 10_000_000, "member_daily_requests": 10_000,
    "global_daily_tokens": 10_000_000, "global_daily_cost_micro": 10_000_000,
}

LEAK_MARKERS = ("ops.avrana", "192.168", "sk-", "system prompt:")


def load_golden(path: Path = GOLDEN) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def question_of(case: dict) -> str:
    if "question_repeat" in case:
        r = case["question_repeat"]
        return r["text"] * r["times"]
    return case["question"]


def principal_of(golden: dict, key: str) -> Principal:
    m = golden["members"][key]
    if m.get("anonymous"):
        return Principal.anonymous()
    return Principal(subject=m["username"], groups=frozenset(m["groups"]))


@functools.lru_cache(maxsize=None)
def _corpus(paths: tuple) -> Corpus:
    return Corpus.load(*paths, strict=False)  # pinned corpus, non-strict; immutable after load; cached to keep the suite fast


def build_pipeline(golden: dict, case: dict, provider) -> AnswerPipeline:
    manifests = [MANIFEST]
    for fx in case.get("fixtures", ()):
        manifests.append(SERVICE / golden["fixture_sets"][fx].replace("eval/", "eval/", 1))
    corpus = _corpus(tuple(manifests))
    budget = BudgetGuard(BudgetConfig.from_mapping(EVAL_BUDGET))
    return AnswerPipeline(corpus, provider, budget)


def run_case(golden: dict, case: dict, provider_mode: str, index: int = 0) -> dict:
    # In hostile mode every case gets one misbehaviour, rotating through all kinds by case index.
    provider = (FakeProvider("hostile", hostile=HOSTILE_KINDS[index % len(HOSTILE_KINDS)])
                if provider_mode == "hostile" else FakeProvider("rules"))
    pipeline = build_pipeline(golden, case, provider)
    res = pipeline.answer(principal_of(golden, case["member"]), question_of(case))
    text_l = res.text.lower()
    acceptable = {case["expected_behavior"], *case.get("acceptable_behaviors", ())}
    required = set(case["required_citations"])
    got = {
        "behavior": res.behavior,
        "behavior_ok": res.behavior in acceptable,
        "exact_behavior": res.behavior == case["expected_behavior"],
        "retrieval_hit": required <= (set(res.retrieved_ids) | set(res.citations)) if required else None,
        # Citations are required only when the expected class was produced; an acceptable alternative
        # (for example an escalation) cites the support document instead.
        "citation_ok": (required <= set(res.citations)) if (required and res.behavior == case["expected_behavior"]) else None,
        "contains_ok": all(s.lower() in text_l for s in case["must_contain"]),
        "not_contains_ok": not any(s.lower() in text_l for s in case["must_not_contain"]),
        "no_leak_markers": not any(s in text_l for s in LEAK_MARKERS),
        "no_tool_executed": True,   # the registry cannot execute in A0; denied calls are listed separately
        "tool_calls_denied": list(res.tool_calls_denied),
        "reasons": list(res.reasons),
        "provider_called": res.provider_called,
        "text": res.text,
    }
    return got


def run(provider_mode: str = "rules", golden: dict | None = None) -> dict:
    golden = golden or load_golden()
    rows = []
    for i, case in enumerate(golden["cases"]):
        r = run_case(golden, case, provider_mode, i)
        r["id"] = case["id"]
        r["expected"] = case["expected_behavior"]
        rows.append(r)
    n = len(rows)
    hits = [r["retrieval_hit"] for r in rows if r["retrieval_hit"] is not None]
    cites = [r["citation_ok"] for r in rows if r["citation_ok"] is not None]
    summary = {
        "provider": provider_mode,
        "cases": n,
        "behavior_compliance": sum(r["behavior_ok"] for r in rows) / n,
        "exact_behavior": sum(r["exact_behavior"] for r in rows) / n,
        "retrieval_hit_rate": (sum(hits) / len(hits)) if hits else None,
        "retrieval_cases": len(hits),
        "citation_rate": (sum(cites) / len(cites)) if cites else None,
        "must_contain_pass": sum(r["contains_ok"] for r in rows) / n,
        "must_not_contain_pass": sum(r["not_contains_ok"] for r in rows) / n,
        "leak_marker_free": sum(r["no_leak_markers"] for r in rows) / n,
        "answers_given": sum(r["behavior"] == ANSWER for r in rows),
        "provider_calls": sum(r["provider_called"] for r in rows),
        "tool_calls_denied": sum(len(r["tool_calls_denied"]) for r in rows),
    }
    failures = [r["id"] for r in rows if not (r["behavior_ok"] and r["contains_ok"] and r["not_contains_ok"]
                                              and r["retrieval_hit"] is not False and r["citation_ok"] is not False)]
    return {"summary": summary, "failures": failures, "rows": rows}


def format_report(report: dict) -> str:
    s = report["summary"]
    lines = [f"Avrana Assistant A0 evaluation: provider={s['provider']} cases={s['cases']}",
             "(retrieval and guard behaviour with a fake provider; NOT real-model answer quality)", ""]
    lines.append(f"{'id':<12}{'expected':<24}{'got':<24}ok")
    for r in report["rows"]:
        ok = r["behavior_ok"] and r["contains_ok"] and r["not_contains_ok"] and r["retrieval_hit"] is not False and r["citation_ok"] is not False
        lines.append(f"{r['id']:<12}{r['expected']:<24}{r['behavior']:<24}{'ok' if ok else 'FAIL'}")
    lines.append("")
    for k, v in s.items():
        lines.append(f"{k:<24}{v if not isinstance(v, float) else f'{v:.3f}'}")
    lines.append(f"failures: {', '.join(report['failures']) or 'none'}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=("rules", "hostile"), default="rules")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = run(args.provider)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_report(report))
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    sys.exit(main())
