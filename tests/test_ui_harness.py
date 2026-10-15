"""Layer 1 of the UI harness, run by tests/run_offline.py: stdlib only, no browser, no network.

Renders every registered page offline, runs the static accessibility / copy / leak checks and holds
them to the ratchet in tests/ui/harness/baseline.json: a finding that is not in the baseline fails
the run; a baseline entry that no longer occurs is printed (and fails only when
UI_HARNESS_STRICT_BASELINE=1). See tests/ui/README.md.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "ui"))

from harness import adapters, css, dom, pages, ratchet, static_checks  # noqa: E402

STRICT = os.environ.get("UI_HARNESS_STRICT_BASELINE", "") not in ("", "0")
_cache = {}


def registry():
    if "reg" not in _cache:
        _cache["reg"] = pages.build_registry()
        _cache["run"] = static_checks.run(_cache["reg"])
    return _cache["reg"]


def static_run():
    registry()
    return _cache["run"]


def assert_no_regressions(ids, baseline_section):
    """The ratchet itself, shared by the real test and the negative test."""
    new, stale = ratchet.compare(ids, baseline_section)
    if new:
        raise AssertionError(
            f"{len(new)} accessibility/copy/leak finding(s) are not in tests/ui/harness/baseline.json "
            f"(the baseline may only shrink; fix the page):\n  " + "\n  ".join(new[:40])
            + ("\n  ..." if len(new) > 40 else ""))
    return stale


def page(html, *, vis="authorized", identity="member", tags=(), forbid=(), status=200, css_extra=()):
    ident = pages.Identity(id=identity, klass="member", groups=("g",))
    return pages.Page("synthetic", "p", ident, vis, lambda: pages.Rendered(status, html, css=list(css_extra)),
                      tags=tags, forbid=forbid)


def findings_for(p):
    rendered, _ = p.produce()
    return static_checks.check_page(p, rendered)


CLEAN = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="dark">
<title>Clean</title><style>
:root{--bg:#000;--fg:#fff;--dim:#9a9a9a;--ctl:#6e6e6e}
body{background:var(--bg);color:var(--fg);font:17px/1.55 serif}
a.btn,button,input{display:inline-block;min-height:48px;padding:12px 20px;border:1px solid var(--ctl);color:var(--fg);background:transparent}
a.btn:focus-visible,button:focus-visible,input:focus-visible{box-shadow:0 0 0 2px #000,0 0 0 4px #fff;outline:2px solid transparent}
p.note{color:var(--dim)}
</style></head><body><main><h1>Clean</h1><h2>Topic</h2><p class="note">Plain copy for you.</p>
<nav aria-label="Main"><a class="btn" href="/x">Go</a></nav>
<form><label for="e">Email</label><input id="e" type="email"><button type="submit">Save</button></form>
<div class="banner" role="status">Saved.</div></main></body></html>"""

DEFECTS = """<!doctype html><html><head>
<meta http-equiv="refresh" content="10"><style>
body{background:#000;color:#fff}
a.t{display:block;padding:4px;border:1px solid rgba(255,255,255,0.28);color:#fff}
a.t:focus-visible{outline:none}
.dim{color:#333}
</style></head><body onload="x()"><h1>One</h1><h1>Two</h1><h4>Skipped</h4>
<a class="t" href="/a" target="_blank"></a><input type="text" name="q"><img src="a.png">
<p class="dim">We made this DASH for you</p><div class="banner">Oops</div><script>1</script>
<p>Kindle is here</p></body></html>""".replace("DASH", chr(0x2014))


class CssAndColourTests(unittest.TestCase):
    def test_contrast_math(self):
        self.assertAlmostEqual(css.contrast((255, 255, 255, 1), (0, 0, 0, 1)), 21.0, places=2)
        # the audit's number: rgba(255,255,255,.28) over black is #474747 at 2.3:1
        edge = css.composite(css.parse_color("rgba(255,255,255,0.28)"), (0, 0, 0, 1.0))
        self.assertEqual(css.to_hex(edge), "#474747")
        self.assertAlmostEqual(css.contrast(edge, (0, 0, 0, 1.0)), 2.27, places=1)
        self.assertGreaterEqual(css.contrast(css.parse_color("#6e6e6e"), (0, 0, 0, 1.0)), 3.0)   # Control Rule
        self.assertGreaterEqual(css.contrast(css.parse_color("#9a9a9a"), (0, 0, 0, 1.0)), 7.0)   # Ash

    def test_parse_colour_forms(self):
        self.assertEqual(css.parse_color("#fff"), (255, 255, 255, 1.0))
        self.assertEqual(css.parse_color("rgb(0 0 0 / 50%)")[3], 0.5)
        self.assertIsNone(css.parse_color("var(--x)"))

    def test_variables_selectors_and_cascade(self):
        doc = dom.parse('<html><body><a class="x" href="#">a</a><button class="ghost">b</button></body></html>')
        sheet = css.Stylesheet(":root{--c:#123456}"
                               "a.x{color:var(--c);outline:none}"
                               "a.x:focus-visible{box-shadow:0 0 0 2px #000}"
                               "button{outline:none}button:focus-visible{outline:none}button.ghost{box-shadow:none}"
                               "@media (max-width:5px){a.x{color:red}}")
        a = doc.all("a")[0]
        self.assertEqual(sheet.computed(a)["color"], "#123456")
        self.assertEqual(sheet.computed(a, "focus")["box-shadow"], "0 0 0 2px #000")
        self.assertNotIn("box-shadow", sheet.computed(a))
        self.assertEqual(sheet.computed(doc.all("button")[0], "focus")["outline-style"], "none")

    def test_shorthands(self):
        self.assertEqual(css.expand("outline", "none")["outline-style"], "none")
        self.assertEqual(css.expand("padding", "12px 20px")["padding-bottom"], "12px")
        self.assertEqual(css.expand("font", '17px/1.55 "Times New Roman",serif')["line-height"], "1.55")
        self.assertEqual(css.expand("border-bottom", "1px solid red"), {"border-bottom-width": "1px",
                                                                       "border-bottom-style": "solid",
                                                                       "border-bottom-color": "red"})
        self.assertEqual(css.to_px("1.5rem"), 24.0)
        self.assertIsNone(css.to_px("clamp(1rem,5vw,2rem)"))


class DetectorTests(unittest.TestCase):
    def test_clean_page_has_no_findings(self):
        got = findings_for(page(CLEAN, tags=("topic",)))
        self.assertEqual([f.id for f in got], [])

    def test_each_defect_is_detected(self):
        got = {f.rule for f in findings_for(page(DEFECTS, forbid=("Kindle",)))}
        expect = {"h1-count", "heading-skip", "link-name", "input-name", "img-alt", "target-blank-rel", "html-lang",
                  "viewport", "color-scheme", "meta-refresh", "inline-handler", "script-present", "focus-outline-none",
                  "focus-ring-missing", "contrast-control-edge", "contrast-text", "target-size", "status-role",
                  "dash-in-copy", "first-person", "leak", "landmark-main"}
        self.assertEqual(sorted(expect - got), [], "detectors that did not fire")

    def test_denied_page_status_is_checked(self):
        got = findings_for(page(CLEAN, vis="denied", status=403))
        self.assertIn("status", {f.rule for f in got})

    def test_finding_ids_are_stable_and_magnitude_free(self):
        a = [f.id for f in findings_for(page(DEFECTS))]
        b = [f.id for f in findings_for(page(DEFECTS.replace("#333", "#222")))]
        self.assertEqual(a, b)          # the contrast ratio changed, the id did not
        self.assertTrue(all(i.startswith("synthetic/p/member/") for i in a))

    def test_leak_is_case_sensitive_for_labels_only(self):
        p = page(CLEAN.replace("Plain copy", "Your books and COMICS"), forbid=("=Books", "comics"))
        self.assertEqual([f.detail for f in findings_for(p) if f.rule == "leak"], ["comics"])


class RegistryTests(unittest.TestCase):
    def test_registry_builds_and_covers_both_services(self):
        reg = registry()
        self.assertEqual(reg.load_errors, [])
        keys = [p.key for p in reg.pages()]
        self.assertEqual(len(keys), len(set(keys)))
        _findings, unavailable = static_run()
        print(f"\nui harness registry: {len(keys)} pages, {len(unavailable)} unavailable")
        by_service = {}
        for p in reg.pages():
            by_service.setdefault(p.service, []).append(f"{p.page}[{p.identity.id}:{p.visibility}]")
        for svc, items in sorted(by_service.items()):
            print(f"  {svc}: {len(items)} pages")
        self.assertIn("portal", by_service)
        self.assertIn("kindle", by_service)
        # on this tree both modules import, so nothing but a deliberate placeholder may be unavailable
        self.assertEqual([u for u in unavailable], [], "pages that could not be produced")

    def test_portal_identities_and_pages(self):
        reg = registry()
        have = {(p.page, p.identity.id) for p in reg.pages("portal")}
        for ident in ("none", "videos", "audiobooks", "comics", "books", "contributors", "admin", "multi"):
            self.assertIn(("home", ident), have)
        for needed in ("help-index", "account", "not-found"):
            self.assertTrue(any(pg == needed for pg, _ in have), needed)
        self.assertTrue(any(pg.startswith("chooser-") for pg, _ in have))
        self.assertTrue(any(pg.startswith("help-") and pg != "help-index" for pg, _ in have))
        self.assertTrue(any(pg.startswith("interstitial-") for pg, _ in have))

    def test_kindle_states(self):
        have = {p.page for p in registry().pages("kindle")}
        self.assertTrue({"form-empty", "form-values", "saved", "error-bad-address", "not-found"} <= have)

    def test_visibility_matches_the_rendered_status(self):
        findings, _ = static_run()
        mismatches = [f.id for f in findings if f.rule == "status" and f.service == "portal"]
        self.assertEqual(mismatches, [], "the portal answered a different status than its registry entry expects")

    def test_unavailable_is_reported_not_failed(self):
        reg = pages.Registry()

        def gone():
            raise pages.Unavailable("not merged yet")
        reg.add(pages.Page("future", "home", pages.Identity("m", "member"), "authorized", gone))
        findings, unavailable = static_checks.run(reg)
        self.assertEqual(findings, [])
        self.assertEqual(unavailable, [("future/home/m", "not merged yet")])

    def test_extra_hook_modules_are_loaded_and_broken_ones_reported(self):
        d = Path(tempfile.mkdtemp())
        try:
            good = d / "good.py"
            good.write_text(
                "from harness.pages import Page, Rendered, Identity\n"
                "def register(reg):\n"
                "    reg.add(Page('audible', 'connect', Identity('m', 'member'), 'authorized',\n"
                "                 lambda: Rendered(200, '<!doctype html><title>x</title>')))\n", encoding="utf-8")
            bad = d / "bad.py"
            bad.write_text("def register(reg):\n    raise RuntimeError('boom')\n", encoding="utf-8")
            old = os.environ.get("UI_HARNESS_EXTRA")
            os.environ["UI_HARNESS_EXTRA"] = os.pathsep.join([str(good), str(bad)])
            try:
                reg = pages.build_registry()
            finally:
                if old is None:
                    del os.environ["UI_HARNESS_EXTRA"]
                else:
                    os.environ["UI_HARNESS_EXTRA"] = old
            self.assertIn("audible/connect/m", [p.key for p in reg.pages()])
            self.assertEqual(len(reg.load_errors), 1)
            self.assertIn("boom", reg.load_errors[0])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_in_memory_driver_returns_status_and_body(self):
        from http.server import BaseHTTPRequestHandler

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self):
                body = self.headers.get("X-authentik-groups", "").encode()
                self.send_response(404)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        status, headers, body = adapters.call(H, "GET", "/x", {"X-authentik-groups": "a|b"})
        self.assertEqual((status, body), (404, "a|b"))


class RatchetTests(unittest.TestCase):
    def test_baseline_file_is_well_formed(self):
        data = ratchet.load()
        self.assertEqual(ratchet.validate(data), [])
        for sec in ratchet.SECTIONS:
            self.assertEqual(list(data[sec]), sorted(data[sec]), f"{sec} section is not sorted")
        raw = json.loads(ratchet.BASELINE_PATH.read_text(encoding="utf-8"))
        self.assertIn("may only shrink", raw["_comment"])
        issues = set(data["static"].values()) | set(data["browser"].values())
        self.assertLessEqual(issues, {"AVR-357", "AVR-358", "AVR-359", "AVR-430", "AVR-353"}, issues)

    def test_no_finding_outside_the_baseline(self):
        findings, _ = static_run()
        base = ratchet.load()["static"]
        stale = assert_no_regressions({f.id for f in findings}, base)
        by_issue = {}
        for f in findings:
            by_issue[base[f.id]] = by_issue.get(base[f.id], 0) + 1
        print("\nui harness static findings by fixing issue: "
              + ", ".join(f"{k}={v}" for k, v in sorted(by_issue.items())) + f" (total {len(findings)})")
        if stale:
            print(f"ui harness: {len(stale)} baseline entries no longer occur (shrink the baseline with "
                  "update_baseline.py --write):")
            for s in stale[:15]:
                print("  stale:", s)
        if STRICT:
            self.assertEqual(stale, [], "stale baseline entries (UI_HARNESS_STRICT_BASELINE is set)")

    def test_negative_a_new_violation_breaks_the_run(self):
        """Inject a defective page through the registry: the ratchet must reject it."""
        reg = pages.build_registry()
        reg.add(page(DEFECTS, forbid=("Kindle",)))
        findings, _ = static_checks.run(reg)
        base = ratchet.load()["static"]
        with self.assertRaises(AssertionError) as cm:
            assert_no_regressions({f.id for f in findings}, base)
        msg = str(cm.exception)
        self.assertIn("synthetic/p/member/", msg)
        self.assertIn("baseline may only shrink", msg)
        # and the same page does not slip through if its defects were "fixed" down to nothing new
        clean = pages.build_registry()
        clean.add(page(CLEAN, tags=("topic",)))
        ids = {f.id for f in static_checks.run(clean)[0]}
        self.assertFalse([i for i in ids if i.startswith("synthetic/")])
        assert_no_regressions(ids, base)

    def test_negative_a_regression_in_a_real_page_is_caught(self):
        """Take a real portal page and make it worse: a new h1 on one page is a new id."""
        reg = pages.build_registry()
        real = reg.pages("portal")[0]
        rendered, _ = real.produce()
        worse = pages.Rendered(rendered.status, rendered.html.replace("</main>", "<h1>Second</h1></main>"))
        ids = {f.id for f in static_checks.check_page(real, worse)}
        new, _stale = ratchet.compare(ids, ratchet.load()["static"])
        self.assertIn(f"{real.key}/h1-count/2 h1", new)

    def test_strict_mode_flags_stale_entries(self):
        base = {"portal/home/none/h1-count/2 h1": "AVR-357"}
        new, stale = ratchet.compare(set(), base)
        self.assertEqual((new, stale), ([], ["portal/home/none/h1-count/2 h1"]))

    def test_update_baseline_check_runs(self):
        res = subprocess.run([sys.executable, "-B", str(ROOT / "tests/ui/harness/update_baseline.py"), "--check"],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("0 new", res.stdout)


class BrowserLayerFilesTests(unittest.TestCase):
    def test_check_mjs_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed; the browser layer is a development tool")
        res = subprocess.run([node, "--check", str(ROOT / "tests/ui/harness/check.mjs")], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_screenshots_and_reports_are_ignored(self):
        text = (ROOT / "tests/ui/harness/.gitignore").read_text(encoding="utf-8")
        self.assertIn("out/", text)
        self.assertIn("*.png", text)


if __name__ == "__main__":
    unittest.main()
