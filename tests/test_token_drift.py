"""AVR-362, narrow slice: the portal, the Kindle connector and the Audible connector must keep
agreeing on the house-style tokens. Stdlib only; nothing is imported from the services (their inline
STYLE strings are read with ast) and no service is changed.

Reference: docs/design/foundation/tokens.json when it exists (the design team's PR #3), else the
services against each other. Known differences are in tests/ui/harness/token_drift_allowlist.json;
a divergence that is not listed fails. UI_HARNESS_STRICT_BASELINE=1 also fails on allow-list entries
that no longer occur, so the list can be emptied as AVR-362 converges the services.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "ui"))

from harness import token_drift as T  # noqa: E402

STRICT = os.environ.get("UI_HARNESS_STRICT_BASELINE", "") not in ("", "0")


def fmt(d):
    return f"{d['token']} in {d['service']} is {d['value']!r}, expected {d['expected']!r} (from {d['reference']})"


class TokenDriftTests(unittest.TestCase):
    def test_every_service_yields_the_core_tokens(self):
        per = T.run()["per_service"]
        for svc in T.SERVICES:
            for tok in ("color.surface", "color.on_surface", "color.on_surface_muted", "color.outline_quiet",
                        "font.family", "wordmark.tracking"):
                self.assertIn(tok, per[svc], f"{svc} no longer yields {tok}: has the stylesheet moved or the reader broken?")

    def test_no_new_divergence(self):
        r = T.run()
        print(f"\ntoken drift: reference={r['source']}, {len(r['divergences'])} divergences "
              f"({len(r['known'])} allow-listed, {len(r['new'])} new)")
        for d in r["known"]:
            print("  known:", fmt(d))
        for t in r["undefined"]:
            print(f"  not defined by any service yet: {t}")
        for a in r["unused"]:
            print(f"  allow-list entry no longer occurs: {a['token']} / {a['service']} / {a['value']}")
        self.assertEqual([fmt(d) for d in r["new"]], [], "new token divergence (fix the stylesheet, do not extend the allow-list)")
        if STRICT:
            self.assertEqual(r["unused"], [], "stale allow-list entries")

    def test_allowlist_is_well_formed(self):
        allow = T.load_allowlist()
        self.assertTrue(allow)
        keys = set()
        for a in allow:
            self.assertTrue(a["reason"].strip(), a)
            self.assertRegex(a["issue"], r"^AVR-\d+$")
            self.assertIn(a["service"], T.SERVICES)
            self.assertIn(a.get("reference", "any"), ("any", "tokens.json"))
            key = (a["token"], a["service"], a["value"])
            self.assertNotIn(key, keys)
            keys.add(key)

    def test_negative_a_new_divergence_is_caught(self):
        src = T.load_sources()
        # the dim text colour drifts in Kindle: #9a9a9a -> #999999
        drifted = src["kindle"].replace("--dim:#9a9a9a", "--dim:#999999")
        self.assertNotEqual(drifted, src["kindle"])
        r = T.run(overrides={"kindle": drifted})
        self.assertIn(("color.on_surface_muted", "kindle"), [(d["token"], d["service"]) for d in r["new"]])
        # a stray literal colour in the portal is caught too
        r = T.run(overrides={"portal": src["portal"] + "\n a.x{color:#abcdef}"})
        self.assertIn(("literal.colour", "portal", "#abcdef"), [(d["token"], d["service"], d["value"]) for d in r["new"]])

    def test_tokens_json_is_the_reference_when_present(self):
        tokens = {"themes": {"media": {"color": {"surface": "#000000", "on_surface": "#ffffff",
                                                 "on_surface_muted": "#aaaaaa", "outline_quiet": "#474747",
                                                 "outline_control": "#6e6e6e", "outline_strong": "#999999"},
                                       "type": {"interface": "Times New Roman, Times, serif"}}}}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tokens.json"
            p.write_text(json.dumps(tokens), encoding="utf-8")
            r = T.run(tokens_path=p, allowlist=[])
        self.assertEqual(r["source"], "tokens.json")
        muted = [d for d in r["divergences"] if d["token"] == "color.on_surface_muted"]
        self.assertEqual({d["service"] for d in muted}, set(T.SERVICES))      # every service differs from the file
        self.assertIn("color.outline_control", r["undefined"])               # no service defines the Control Rule yet
        self.assertFalse([d for d in r["divergences"] if d["token"] == "font.family"])

    def test_missing_tokens_file_falls_back_to_peers(self):
        r = T.run(tokens_path=Path("does-not-exist.json"))
        self.assertEqual(r["source"], "peers")


if __name__ == "__main__":
    unittest.main()
