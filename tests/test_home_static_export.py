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
                     "member-b/normal/home-new-calibre-web.html",
                     # The shell beyond Home, so check_home_export.mjs (axe, sideways scroll, focus) covers it too:
                     "member-a/normal/title-jellyfin-aaaa0000000000000000000000000001.html",
                     "member-b/normal/read.html", "member-a/normal/request.html", "member-a/normal/watch.html",
                     "member-a/normal/help-trouble.html", "member-a/normal/me.html", "member-a/normal/account.html",
                     # ...and the degraded states: a library not set up, one section down, a title unavailable.
                     "member-c/not-linked/home.html", "member-c/not-linked/search-results.html",
                     "member-c/not-linked/title-jellyfin-aaaa0000000000000000000000000001.html",
                     "member-a/one-section-down/home.html",
                     "member-a/one-down/title-jellyfin-aaaa0000000000000000000000000001.html"):
            self.assertIn(want, rel)
        titles = [r for r in rel if "/normal/title-" in r and r.startswith("member-a/")]
        self.assertLessEqual(len(titles), 4)               # at most one title page per library: the crawl is bounded

    def test_states_say_what_they_should(self):
        read = lambda r: (self.out / r).read_text(encoding="utf-8")
        self.assertIn("Synthetic Film One", read("member-a/normal/home.html"))
        self.assertIn("unavailable right now", read("member-a/one-down/home.html"))
        self.assertIn("No library yet", read("member-none/no-library/home.html"))
        self.assertNotIn("Account<span", read("signed-out/signed-out/home.html"))
        self.assertNotIn("Synthetic Film One", read("member-a/all-down/home.html"))
        unset = read("member-c/not-linked/home.html")
        self.assertIn('<h2 id="h-setup">Not set up yet</h2>', unset)
        self.assertIn('href="help-trouble.html#not-set-up"', unset)         # the next step is in the export too
        self.assertIn("Anything shown from them may be out of date.", read("member-a/one-section-down/home.html"))
        self.assertIn("The Movies and TV library is unavailable right now.",
                      read("member-a/one-down/title-jellyfin-aaaa0000000000000000000000000001.html"))
        self.assertIn("is not set up for your account yet.",
                      read("member-c/not-linked/title-jellyfin-aaaa0000000000000000000000000001.html"))
        self.assertIn('href="title-jellyfin-aaaa0000000000000000000000000001.html"',
                      read("member-a/normal/search-results.html"))       # search links reach the exported title

    def test_search_pages_are_there_for_every_state_and_say_what_they_should(self):
        read = lambda r: (self.out / r).read_text(encoding="utf-8")
        for who in ("member-a", "member-b"):
            for page in ("search", "search-results", "search-no-match", "search-invalid"):
                self.assertTrue((self.out / who / "normal" / f"{page}.html").is_file(), (who, page))
        self.assertRegex(read("member-a/normal/search-results.html"), r'id="h-outcome">\d+ results?<')
        self.assertIn('id="h-outcome">No results<', read("member-a/normal/search-no-match.html"))
        self.assertIn('aria-invalid="true"', read("member-a/normal/search-invalid.html"))
        down = read("member-b/one-down/search-results.html")
        self.assertIn("library could not be searched right now.", down)
        self.assertIn("Try again", down)
        self.assertIn("Search is not available on your account yet.", read("member-none/no-library/search.html"))
        self.assertNotIn("Synthetic Film One", read("member-a/all-down/search-results.html"))

    def test_every_page_has_the_skip_link_and_exactly_one_main(self):
        for p in self.pages():
            if p.name in ("index.html", "not-in-export.html"):
                continue
            text = p.read_text(encoding="utf-8")
            with self.subTest(page=str(p.relative_to(self.out))):
                self.assertIn('<a class="skip-link" href="#main">', text)
                self.assertEqual(1, len(re.findall(r"<main[\s>]", text)))
                self.assertNotRegex(text, r'action="/')

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
        # LF is a rule for what the export GENERATES. brand/ holds copies of the approved brand package, kept byte
        # for byte (the package's SVGs use CRLF, the WOFF2 is binary); the next test holds them to their source.
        for p in self.files:
            if p.parent == self.out / "brand":
                continue
            self.assertNotIn(b"\r", p.read_bytes(), p.name)

    def test_brand_files_are_the_package_bytes(self):
        """AVR-584: every exported brand file is exactly the bytes brand.py serves, which are pinned by SHA-256 to
        the approved package (brand/SOURCES.json). Nothing in the export normalises, re-encodes or adds to them."""
        import hashlib
        from avrana_home.app import brand
        exported = {p.relative_to(self.out).as_posix(): p for p in self.files if p.parent == self.out / "brand"}
        self.assertEqual({route.lstrip("/") for route in brand.ROUTES}, set(exported))
        pins = brand.sources()["files"]
        for route, (name, _type) in brand.ROUTES.items():
            data = exported[route.lstrip("/")].read_bytes()
            self.assertEqual(brand.file_bytes(name), data, route)
            self.assertEqual(pins[name]["sha256"], hashlib.sha256(data).hexdigest(), route)

    def test_refuses_a_foreign_folder(self):
        import export_home_static
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "keep.txt").write_text("x")
            self.assertEqual(2, export_home_static.main(["--out", d]))
            self.assertTrue((Path(d) / "keep.txt").exists())


if __name__ == "__main__":
    unittest.main()
