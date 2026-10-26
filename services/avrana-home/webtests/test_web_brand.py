"""AVR-584: the approved AVRANA Brand v1.0.0 files on the Home shell; AVR-715: Plus Jakarta Sans and the Concept K
tokens. Synthetic data only (StubAdapter), no upstream.

Tier A (standard library): every served file is its source's own bytes (SHA-256 in brand/SOURCES.json), a
tampered file is refused, the SVGs carry nothing that could run or fetch, and the shell stylesheet uses the brand
and Concept K tokens, the Media yellow and no Party purple. Tier B (framework): the routes, their types, the 404s and the masthead lockup.
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

    def test_the_font_is_plus_jakarta_sans_woff2_and_carries_its_licence(self):
        files = brand.sources()["files"]
        for name in ("PlusJakartaSans-Latin-Variable.woff2", "PlusJakartaSans-LatinExt-Variable.woff2"):
            self.assertEqual(b"wOF2", brand.file_bytes(name)[:4])
            self.assertIn("@fontsource-variable/plus-jakarta-sans 5.3.0", files[name]["source"])
        licence = brand.file_bytes("OFL-PlusJakartaSans.txt").decode("utf-8")
        self.assertIn("SIL OPEN FONT LICENSE", licence.upper())
        self.assertIn("Plus Jakarta Sans Project Authors", licence)
        # Geist is retired from the shell (owner: Plus Jakarta Sans everywhere, AVR-715)
        self.assertFalse(any("geist" in n.lower() for n in files))
        self.assertFalse(any("geist" in r for r in brand.ROUTES))

    def test_the_shell_stylesheet_uses_the_concept_k_tokens_the_media_yellow_and_no_party_purple(self):
        css = (TEMPLATES / "home.css").read_text(encoding="utf-8").lower()
        for token in ("--ink:#121214", "--cream:#edeae4", "--stone:#aeaba7", "--control:#6e6c72", "--graphite:#5e5b57",
                      "--ash:#8f8c89", "--bg:var(--ink)", "--fg:var(--cream)", "--dim:var(--stone)",
                      "--accent:#eada6e", "--accent-deep:#776a00", "--warn:#f59e0b", "--focus:var(--accent)",
                      '"plus jakarta sans"', 'url("/brand/plus-jakarta-sans-latin.woff2")',
                      'url("/brand/plus-jakarta-sans-latin-ext.woff2")', "font-display:swap",
                      "--motion-3:200ms", "prefers-reduced-motion:reduce", "prefers-reduced-transparency:reduce"):
            self.assertIn(token, css)
        rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)          # the comments may name what is not used
        for purple in ("#b9a9e8", "#5a439d", "--avr-purple", "rgb(185", "--color-purple"):
            self.assertNotIn(purple, rules)
        # Media's older warn reads as the same colour as the yellow, so the shell never uses it
        self.assertNotIn("#e8cf8a", rules)
        for gone in ("geist", "/brand/geist.woff2"):
            self.assertNotIn(gone, rules)
        # the portal's stylesheet copy is untouched: parity, and the token-drift gate, stay as they were
        portal = (TEMPLATES / "style.css").read_text(encoding="utf-8").lower()
        self.assertNotIn("geist", portal)
        self.assertNotIn("jakarta", portal)
        self.assertNotIn("#eada6e", portal)

    def test_glass_clips_itself_and_has_fallbacks(self):
        css = (TEMPLATES / "home.css").read_text(encoding="utf-8")
        glass = re.search(r"\.glass\{([^}]*)\}", css).group(1)
        for decl in ("isolation:isolate", "overflow:hidden", "backdrop-filter:blur(28px)"):
            self.assertIn(decl, glass)
        self.assertNotIn("border-image", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
        self.assertIn("@supports not ((backdrop-filter:blur(1px))", css)
        self.assertIn("@media (forced-colors:active){.glass", css)


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
                     "/brand/geist.woff2", "/brand/PlusJakartaSans-Latin-Variable.woff2.b64",
                     "/brand/OFL-PlusJakartaSans.txt", "/brand/avrana-media-l3.svg/x", "/brand/../brand.py",
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
            self.assertNotIn('<div class="rule">', text, path)        # no rule under the lockup (owner, 2026-10-18)
        off = self.client(sections=False)
        for path in ("/", "/account", "/help"):
            text = off.get(path, headers=MEMBER).text
            self.assertNotIn("/brand/", text, path)
            self.assertNotIn("lockup-text", text, path)
            self.assertIn('<div class="rule"></div>', text, path)    # the portal keeps its wordmark rule (AVR-362)
            self.assertRegex(text, r"<h1>(<a href=\"/\">)?AVRANA(</a>)?</h1>", path)   # the portal's wordmark

    def test_forced_colours_show_the_name_as_text_named_once(self):
        """Windows high contrast cannot recolour the cream lockup, so the name shows as text there. The text is
        aria-hidden and the image is only hidden visually, so the link keeps one accessible name: the alt text."""
        text = self.client().get("/", headers=MEMBER).text
        link = re.search(r'<h1><a href="/"[^>]*>(.*?)</a></h1>', text).group(1)
        self.assertEqual(LOCKUP_TAG + '<span class="lockup-text" aria-hidden="true">Avrana Media</span>', link)
        named = re.sub(r'<span[^>]*aria-hidden="true"[^>]*>.*?</span>', "", link)      # what assistive tech reads
        self.assertEqual(["Avrana Media"], re.findall(r'alt="([^"]*)"', named))
        self.assertEqual("", re.sub(r"<[^>]+>", "", named).strip())
        css = re.sub(r"/\*.*?\*/", "", (TEMPLATES / "home.css").read_text(encoding="utf-8"), flags=re.S)
        self.assertIn(".mast .lockup-text{display:none;}", css)                         # off everywhere else
        forced = re.search(r"@media \(forced-colors:active\)\{(.*?)\n  \}", css, flags=re.S).group(1)
        self.assertIn(".mast .lockup-text{display:inline;", forced)
        lockup = re.search(r"\.mast \.lockup\{([^}]*)\}", forced).group(1)
        self.assertIn("clip-path:inset(50%)", lockup)
        for gone in ("display:none", "visibility:hidden"):                              # would drop the alt text
            self.assertNotIn(gone, lockup)


if __name__ == "__main__":
    unittest.main()
