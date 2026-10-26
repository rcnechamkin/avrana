"""Tier B, Home 2.0 Lane D (AVR-364/386): installable Home. The manifest and icons, the head tags only on shell
pages, and the narrow CSP change (`manifest-src`, `font-src`, and since MK-3 / AVR-717 `script-src` and `worker-src`, all 'self',
on shell pages only; every other route unchanged except the two in test_web_pwa.py). Synthetic data only (StubAdapter)."""
import hashlib
import json
import re
import struct
import unittest

from avrana_home.app import brand, install, pwa
from avrana_home.app.middleware import CSP, CSP_SEARCH
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

MEMBER = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
NO_GROUPS_HEADER = [(USER, "member-a")]                     # no principal: the portal's no-group view
# MK-3 (AVR-717, owner decision O1): shell pages alone also get script-src and worker-src, both 'self'.
SHELL_SOURCES = "; manifest-src 'self'; font-src 'self'; script-src 'self'; worker-src 'self'"
MANIFEST_CSP = CSP.decode() + SHELL_SOURCES
HEAD_TAGS = ('<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">',
             '<link rel="icon" href="/brand/favicon.svg" type="image/svg+xml">',
             '<link rel="apple-touch-icon" href="/icons/avrana-180.png">',
             '<meta name="theme-color" content="#121214">',
             '<meta name="apple-mobile-web-app-capable" content="yes">',
             '<meta name="apple-mobile-web-app-title" content="Avrana Media">')
SHELL_ROUTES = ("/", "/library", "/me", "/account", "/help", "/help/movies", "/help/trouble", "/search", "/search?q=Film", "/watch",
                "/request")   # Watch and Request wear the shell since #59; Read is 404 for this member
OTHER_ROUTES = ("/read", "/nope", "/healthz", "/home.json", "/manifest.webmanifest",
                "/icons/avrana-192.png", "/brand/plus-jakarta-sans-latin.woff2", "/brand/avrana-media-l3.svg", "/art/jellyfin/primary/aaaa0000000000000000000000000001",
                "/help/comics", "/outpost.goauthentik.io/sign_out")
OTHER_ROUTES += (pwa.script_path(), "/signout")        # MK-3: the page script and the sign-out hop keep the base CSP
# The two non-page responses that add one source each (middleware.ROUTE_SOURCES): see test_web_pwa.py.


def png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    length, kind = struct.unpack(">I4s", data[8:16])
    assert kind == b"IHDR" and length == 13
    w, h, depth, ctype = struct.unpack(">IIBB", data[16:26])
    return w, h, depth, ctype


class Base(unittest.TestCase):
    def client(self, sections=True):
        adapters = [StubAdapter({"member-a": [("aaaa0000000000000000000000000001", "Synthetic Film", 0.5)]})]
        c = make_client(make_settings(home_sections=sections), adapters=adapters if sections else None)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c


class ManifestAndIcons(Base):
    def test_the_manifest_has_the_agreed_fields_and_type(self):
        r = self.client().get("/manifest.webmanifest", headers=MEMBER)
        self.assertEqual(200, r.status_code)
        self.assertEqual("application/manifest+json", r.headers["content-type"])
        m = json.loads(r.content)
        self.assertEqual(("Avrana Media", "Avrana Media", "standalone", "/", "/", "#121214", "#121214"),
                         (m["name"], m["short_name"], m["display"], m["start_url"], m["scope"],
                          m["background_color"], m["theme_color"]))
        self.assertEqual(("/", "en"), (m["id"], m["lang"]))                    # D8, MK-3
        self.assertTrue(m["description"] and "member" not in m["description"].lower())
        self.assertEqual({"192x192", "512x512"}, {i["sizes"] for i in m["icons"]})
        self.assertEqual({"any", "maskable"}, {i["purpose"] for i in m["icons"]})
        for icon in m["icons"]:
            self.assertTrue(icon["src"].startswith("/icons/") and icon["type"] == "image/png")
            self.assertEqual(200, self.client().get(icon["src"]).status_code, icon["src"])
        self.assertNotIn("serviceworker", r.text.lower())

    def test_icons_are_the_brand_pngs_of_the_declared_size(self):
        """AVR-584: the approved brand package's icons, byte for byte (SHA-256 recorded in brand/SOURCES.json)."""
        c = self.client()
        pins = brand.sources()["files"]
        for path, name in install.ICON_PATHS.items():
            r = c.get(path)
            self.assertEqual((200, "image/png"), (r.status_code, r.headers["content-type"]), path)
            n = 180 if "180" in path else 192 if "192" in path else 512
            self.assertEqual((n, n), png_size(r.content)[:2], path)
            self.assertEqual(pins[name]["sha256"], hashlib.sha256(r.content).hexdigest(), path)
            self.assertEqual("nosniff", r.headers["x-content-type-options"])

    def test_the_same_bytes_for_every_viewer_without_identity(self):
        c = self.client()
        anon = c.get("/manifest.webmanifest")
        self.assertEqual(200, anon.status_code)
        self.assertEqual(anon.content, c.get("/manifest.webmanifest", headers=MEMBER).content)
        self.assertNotIn("member-a", anon.text)

    def test_unknown_icon_names_are_the_standard_404(self):
        c = self.client()
        nf = c.get("/nope", headers=MEMBER).text
        for path in ("/icons/avrana-64.png", "/icons/avrana-512.svg", "/icons/", "/icons/avrana-180.png/x",
                     "/manifest.json", "/service-worker.js", "/sw.js.map", "/static/home.js",
                     "/static/home." + "0" * 12 + ".js", pwa.script_path() + "/x"):
            r = c.get(path, headers=MEMBER)
            self.assertEqual((404, nf), (r.status_code, r.text), path)

    def test_with_sections_off_the_routes_do_not_exist_and_pages_carry_no_tags(self):
        c = self.client(sections=False)
        nf = c.get("/nope", headers=MEMBER).text
        for path in (["/manifest.webmanifest", "/sw.js", "/offline", "/signout", pwa.script_path()]
                     + list(install.ICON_PATHS)):
            r = c.get(path, headers=MEMBER)
            self.assertEqual((404, nf), (r.status_code, r.text), path)
        for path in ("/", "/me", "/account", "/help"):
            page = c.get(path, headers=MEMBER).text
            for tag in ("manifest", "apple-touch-icon", "theme-color", "apple-mobile-web-app", "<script"):
                self.assertNotIn(tag, page.lower(), path)

    def test_sections_off_there_is_no_script_anywhere(self):
        """With sections off Home is the portal's pages: no script tag, no script source (MK-3 changes shell pages only)."""
        c = self.client(sections=False)
        for path in SHELL_ROUTES:
            r = c.get(path, headers=MEMBER)
            self.assertNotIn("<script", r.text.lower(), path)
            self.assertNotIn("script-src", r.headers["content-security-policy"], path)

    def test_shell_pages_have_exactly_one_first_party_script_and_nothing_inline(self):
        """MK-3 (AVR-717): this replaces `test_there_is_no_script_anywhere`. One external, deferred script at the
        versioned path; no inline script, no event-handler attribute, no javascript: URL."""
        c = self.client()
        want = '<script src="%s" defer></script>' % pwa.script_path()
        for path in SHELL_ROUTES:
            text = c.get(path, headers=MEMBER).text
            self.assertEqual([want], re.findall(r"<script\b[^>]*>.*?</script>", text, re.S | re.I), path)
            self.assertNotRegex(text, r"(?i)\son[a-z]+\s*=|javascript:|<iframe|<object|<embed", path)


class HeadTagsAndCsp(Base):
    def test_shell_pages_link_the_manifest_and_allow_only_it(self):
        c = self.client()
        for path in SHELL_ROUTES:
            with self.subTest(path=path):
                r = c.get(path, headers=MEMBER)
                self.assertEqual(200, r.status_code)
                for tag in HEAD_TAGS:
                    self.assertIn(tag, r.text)
                want = (CSP_SEARCH.decode() + SHELL_SOURCES) if path.startswith("/search") else MANIFEST_CSP
                self.assertEqual(want, r.headers["content-security-policy"])
                csp = r.headers["content-security-policy"]
                self.assertNotIn("unsafe-eval", csp)
                self.assertEqual(1, csp.count("unsafe-inline"))                 # style-src only
                self.assertIn("style-src 'unsafe-inline'", csp)
                self.assertIn("script-src 'self'; worker-src 'self'", csp)
                self.assertNotIn("connect-src", csp)                            # D12: the worker's response alone

    def test_every_other_route_keeps_the_csp_unchanged(self):
        c = self.client()
        for path in OTHER_ROUTES:
            for headers in (MEMBER, NO_GROUPS_HEADER, []):
                with self.subTest(path=path, ident=bool(headers)):
                    r = c.get(path, headers=headers)
                    self.assertEqual(CSP.decode(), r.headers["content-security-policy"], (path, r.status_code))
                    self.assertNotIn("manifest", r.text if "html" in r.headers["content-type"] else "")

    def test_without_a_principal_no_page_wears_the_shell_or_the_manifest(self):
        c = self.client()
        for path in ("/", "/me", "/account", "/help"):
            r = c.get(path, headers=NO_GROUPS_HEADER)
            self.assertEqual(CSP.decode(), r.headers["content-security-policy"], path)
            self.assertNotIn("rel=\"manifest\"", r.text, path)

    def test_the_manifest_link_and_manifest_src_always_come_together(self):
        """Single source of truth (review of #57): respond() marks the CSP whenever it renders a shell."""
        c = self.client()
        for path in SHELL_ROUTES + OTHER_ROUTES:
            for headers in (MEMBER, NO_GROUPS_HEADER):
                r = c.get(path, headers=headers)
                linked = 'rel="manifest"' in r.text and "html" in r.headers["content-type"]
                allowed = "manifest-src 'self'" in r.headers["content-security-policy"]
                self.assertEqual(linked, allowed, (path, bool(headers)))

    def test_sections_off_csp_is_unchanged_on_every_route(self):
        c = self.client(sections=False)
        for path in SHELL_ROUTES + OTHER_ROUTES:
            r = c.get(path, headers=MEMBER)
            self.assertIn(r.headers["content-security-policy"], (CSP.decode(),), path)


if __name__ == "__main__":
    unittest.main()
