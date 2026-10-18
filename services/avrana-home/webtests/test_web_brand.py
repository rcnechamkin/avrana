"""AVR-584: the approved AVRANA Brand v1.0.0 files on the Home shell. Synthetic data only (StubAdapter), no upstream.

Tier A (standard library): every served file is the brand package's own bytes (SHA-256 in brand/SOURCES.json), a
tampered file is refused, the SVGs carry nothing that could run or fetch, and the shell stylesheet uses the brand
tokens and no Party purple. Tier B (framework): the routes, their types, the 404s and the masthead lockup.
"""
import hashlib
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from avrana_home.app import brand
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

MEMBER = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
TEMPLATES = Path(brand.__file__).resolve().parent / "templates"
LOCKUP_TAG = ('<img class="lockup" src="/brand/avrana-media-l3.svg" alt="Avrana Media" width="1384" '
              'height="650">')


class BrandFiles(unittest.TestCase):
    def setUp(self):
        brand.file_bytes.cache_clear()
        self.addCleanup(brand.file_bytes.cache_clear)

    def test_every_recorded_file_matches_its_package_hash(self):
        files = brand.sources()["files"]
        self.assertEqual(("AVRANA-Brand", "1.0.0"), (brand.sources()["package"], brand.sources()["version"]))
        for name, entry in files.items():
            data = brand.file_bytes(name)
            self.assertEqual((entry["sha256"], entry["bytes"]), (hashlib.sha256(data).hexdigest(), len(data)), name)
        self.assertEqual(brand.LOCKUP_RATIO, 1384.38 / 650)
        for _route, (name, _type) in brand.ROUTES.items():
            self.assertIn(name, files)

    def test_a_changed_file_is_refused_not_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "brand"
            shutil.copytree(brand.BRAND_DIR, copy)
            svg = copy / "avrana-media-lockup-product_cream_trim.svg"
            svg.write_bytes(svg.read_bytes().replace(b"#EDEAE4", b"#B9A9E8").replace(b"#edeae4", b"#b9a9e8"))
            with mock.patch.object(brand, "BRAND_DIR", copy):
                with self.assertRaises(RuntimeError):
                    brand.asset_for(brand.LOCKUP)

    def test_the_svgs_have_no_script_link_text_or_external_reference(self):
        for name in ("avrana-media-lockup-product_cream_trim.svg", "favicon.svg"):
            text = brand.file_bytes(name).decode("utf-8").lower()
            for bad in ("<script", "<foreignobject", "href", "<text", "@import", "url(", "on" + "load", "<image"):
                self.assertNotIn(bad, text, (name, bad))

    def test_the_lockup_is_the_media_l3_product_lockup_in_cream(self):
        text = brand.file_bytes("avrana-media-lockup-product_cream_trim.svg").decode("utf-8")
        self.assertIn("Avrana Media product lockup (L3)", text)
        self.assertIn('viewBox="0 0 1384.38 650"', text)
        self.assertTrue(re.search(r"#edeae4", text, re.I))

    def test_the_font_is_woff2_and_carries_its_licence(self):
        self.assertEqual(b"wOF2", brand.file_bytes("Geist-Variable.woff2")[:4])
        self.assertIn("SIL OPEN FONT LICENSE", brand.file_bytes("OFL.txt").decode("utf-8").upper())

    def test_the_shell_stylesheet_uses_the_brand_tokens_and_no_party_purple(self):
        css = (TEMPLATES / "home.css").read_text(encoding="utf-8").lower()
        for token in ("--bg:#121214", "--fg:#edeae4", "--dim:#aeaba7", "--rule-control:#6e6c72", '"geist"',
                      'url("/brand/geist.woff2")', "font-display:swap"):
            self.assertIn(token, css)
        rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)          # the comments may name what is not used
        for purple in ("#b9a9e8", "#5a439d", "--avr-purple", "rgb(185"):
            self.assertNotIn(purple, rules)
        # the portal's stylesheet copy is untouched: parity, and the token-drift gate, stay as they were
        self.assertNotIn("geist", (TEMPLATES / "style.css").read_text(encoding="utf-8").lower())


class BrandRoutes(unittest.TestCase):
    def setUp(self):
        require_framework()

    def client(self, sections=True):
        adapters = [StubAdapter({"member-a": [("aaaa0000000000000000000000000001", "Synthetic Film", 0.5)]})]
        c = make_client(make_settings(home_sections=sections), adapters=adapters if sections else None)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def test_each_route_serves_the_package_bytes_with_its_type(self):
        c = self.client()
        for route, (name, ctype) in brand.ROUTES.items():
            for headers in (MEMBER, []):
                with self.subTest(route=route, ident=bool(headers)):
                    r = c.get(route, headers=headers)
                    self.assertEqual(200, r.status_code)
                    self.assertTrue(r.headers["content-type"].startswith(ctype))
                    self.assertEqual(brand.file_bytes(name), r.content)
                    self.assertEqual("nosniff", r.headers["x-content-type-options"])
                    self.assertNotIn("script-src", r.headers["content-security-policy"])

    def test_other_brand_names_and_sections_off_are_the_standard_404(self):
        c = self.client()
        nf = c.get("/nope", headers=MEMBER).text
        for path in ("/brand/", "/brand/OFL.txt", "/brand/SOURCES.json", "/brand/README.md",
                     "/brand/Geist-Variable.woff2.b64", "/brand/avrana-media-l3.svg/x", "/brand/../brand.py",
                     "/brand/avrana-media-lockup-product_cream_trim.svg"):
            r = c.get(path, headers=MEMBER)
            self.assertEqual((404, nf), (r.status_code, r.text), path)
        off = self.client(sections=False)
        nf = off.get("/nope", headers=MEMBER).text
        for route in brand.ROUTES:
            r = off.get(route, headers=MEMBER)
            self.assertEqual((404, nf), (r.status_code, r.text), route)

    def test_shell_pages_show_the_lockup_and_pages_without_the_shell_do_not(self):
        c = self.client()
        for path in ("/", "/account", "/help", "/search"):
            text = c.get(path, headers=MEMBER).text
            self.assertIn(LOCKUP_TAG, text, path)
            self.assertNotIn(">AVRANA</a>", text, path)
        off = self.client(sections=False)
        for path in ("/", "/account", "/help"):
            text = off.get(path, headers=MEMBER).text
            self.assertNotIn("/brand/", text, path)
            self.assertRegex(text, r"<h1>(<a href=\"/\">)?AVRANA(</a>)?</h1>", path)   # the portal's wordmark


if __name__ == "__main__":
    unittest.main()
