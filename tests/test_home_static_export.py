"""The static Home export (tests/ui/export_home_static.py): synthetic, offline, self-contained.

Skipped where FastAPI is not installed (the repo's stdlib-only runs). Never touches a network port
except the loopback mock services the export itself starts.
"""
import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HAVE = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx", "jinja2"))


@unittest.skipUnless(HAVE, "FastAPI, httpx and Jinja2 are not installed")
class StaticExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(REPO / "tests" / "ui"))
        import export_home_static
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "export"
        assert export_home_static.main(["--out", str(cls.out)]) == 0
        cls.files = sorted(p for p in cls.out.rglob("*") if p.is_file())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def pages(self):
        return [p for p in self.files if p.suffix == ".html"]

    def test_every_state_is_there(self):
        rel = {p.relative_to(self.out).as_posix() for p in self.files}
        for want in ("index.html", "not-in-export.html", "member-a/normal/home.html",
                     "member-b/normal/home.html", "member-a/one-down/home.html",
                     "member-b/all-down/home.html", "member-none/no-library/home.html",
                     "signed-out/signed-out/home.html", "member-a/normal/home-new-jellyfin.html",
                     "member-b/normal/home-new-calibre-web.html"):
            self.assertIn(want, rel)

    def test_states_say_what_they_should(self):
        read = lambda r: (self.out / r).read_text(encoding="utf-8")
        self.assertIn("Synthetic Film One", read("member-a/normal/home.html"))
        self.assertIn("unavailable right now", read("member-a/one-down/home.html"))
        self.assertIn("No library yet", read("member-none/no-library/home.html"))
        self.assertNotIn("Account<span", read("signed-out/signed-out/home.html"))
        self.assertNotIn("Synthetic Film One", read("member-a/all-down/home.html"))

    def test_self_contained_and_synthetic(self):
        for p in self.pages():
            text = p.read_text(encoding="utf-8")
            with self.subTest(page=p.name):
                self.assertNotRegex(text, r"(?i)<script")
                self.assertNotIn('src="/', text)                      # no route back to a server
                self.assertNotRegex(text, r'href="/')
                self.assertNotRegex(text, r'href="https?://(?!example\.)[^"]*avrana\.net')   # no live hand-off
                self.assertNotRegex(text, r"(?i)authentik|api[_-]?key|token")
                for ref in re.findall(r'(?:src|href)="(\.\./[^"#?]+|[a-z0-9-]+\.html)', text):
                    base = p.parent / ref
                    self.assertTrue(base.is_file(), f"{p.name}: {ref} is missing")

    def test_art_is_generated_svg_and_lf(self):
        arts = [p for p in self.files if p.parent.name == "art"]
        self.assertGreater(len(arts), 3)
        for p in arts:
            self.assertTrue(p.read_text(encoding="utf-8").startswith("<svg"))
        for p in self.files:
            self.assertNotIn(b"\r", p.read_bytes(), p.name)

    def test_refuses_a_foreign_folder(self):
        import export_home_static
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "keep.txt").write_text("x")
            self.assertEqual(2, export_home_static.main(["--out", d]))
            self.assertTrue((Path(d) / "keep.txt").exists())


if __name__ == "__main__":
    unittest.main()
