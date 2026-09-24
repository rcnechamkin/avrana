#!/usr/bin/env python3
"""Verdict logic tests. Pure functions over synthetic distributions -- no ffmpeg, no media.

Every case encodes a failure mode that was actually hit while building this, so a regression
here means a verdict that was once wrong has become wrong again.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import imax_verify as iv  # noqa: E402


def dist(*pairs, requested=None):
    """(ar, count) pairs -> the shape analyse() produces."""
    total = sum(c for _, c in pairs)
    return {
        "usable_samples": total,
        "requested_samples": requested or total,
        "distribution": [
            {"ar": ar, "count": c, "share": round(c / total, 4), "approx_runtime_s": 60 * c}
            for ar, c in sorted(pairs, key=lambda p: -p[1])
        ],
    }


SOURCED_FULL = {"expected_ratio": 1.90, "mode": "full", "min_expanded_share": 0.80,
                "source_url": "https://example.invalid/ref", "confidence": "high"}
UNSOURCED_FULL = {"expected_ratio": 1.90, "mode": "full", "min_expanded_share": 0.80}
SOURCED_NONE = {"expected_ratio": 2.40, "mode": "none",
                "source_url": "https://example.invalid/ref", "confidence": "high"}

CASES = [
    # --- the primary path: the release claimed IMAX, the frames decide ---------------------
    ("claimed + variable expanded sequences", dist((2.40, 32), (1.78, 8)), None, True, "PASS"),
    ("claimed + constant expanded 1.90", dist((1.90, 40)), None, True, "PASS"),
    ("claimed + constant expanded 1.78", dist((1.78, 40)), None, True, "PASS"),
    ("claimed + scope throughout -> refuted", dist((2.39, 40)), None, True, "FAIL"),
    ("claimed + only a trace of expansion", dist((2.39, 39), (1.78, 1)), None, True, "FAIL"),

    # --- nothing to judge -------------------------------------------------------------------
    ("not claimed, nothing sourced", dist((2.39, 40)), None, False, "UNKNOWN"),
    ("no usable samples", {"usable_samples": 0, "requested_samples": 60, "distribution": []},
     None, True, "UNKNOWN"),
    ("too few usable samples to be conclusive",
     dist((2.39, 5), requested=60), None, True, "UNKNOWN"),

    # --- expectations are optional and must be attributable ---------------------------------
    ("sourced expectation may tighten to FAIL",
     dist((2.40, 32), (1.78, 8)), SOURCED_FULL, True, "FAIL"),
    ("UNSOURCED expectation must never cause FAIL",
     dist((2.40, 32), (1.78, 8)), UNSOURCED_FULL, True, "PASS"),
    ("sourced 'none' + scope as expected", dist((2.39, 40)), SOURCED_NONE, False, "PASS"),

    # --- regression: 4:3 academy is not IMAX expansion --------------------------------------
    # A 1440x1080 cartoon measured 1.33 and falsely PASSED an IMAX claim before the expanded
    # band gained a floor at 1.40.
    ("4:3 academy must not count as expanded", dist((1.33, 40)), None, True, "UNKNOWN"),
    ("1.43 full-IMAX still counts as expanded", dist((2.39, 30), (1.43, 10)), None, True, "PASS"),

    # --- regression: de-noised shares must be renormalised ----------------------------------
    # Scope-throughout content whose noise buckets were dropped measured 69% scope instead of
    # ~100% and came out UNKNOWN instead of FAIL.
    ("scope + dropped noise still reads as scope",
     dist((2.39, 11), (2.20, 1), (1.95, 1), (2.05, 1), (1.66, 1), (2.30, 1)), None, True, "FAIL"),

    # --- regression: lone dark-frame buckets must not decide --------------------------------
    ("isolated bad samples do not dominate",
     dist((2.39, 30), (1.45, 1), (1.66, 1), (1.22, 1)), None, True, "FAIL"),
    ("a real expanded block still counts",
     dist((2.39, 26), (1.78, 6)), None, True, "PASS"),
]


def main() -> int:
    bad = 0
    for name, analysis, exp, claimed, want in CASES:
        got = iv.classify(analysis, exp, claimed_imax=claimed)["verdict"]
        ok = got == want
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  want={want:<8} got={got:<8} {name}")
    print(f"\n  {len(CASES)-bad}/{len(CASES)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
