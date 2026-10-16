"""Tier B, Home 2.0 Lane D (AVR-364/386): installable Home. The manifest and icons, the head tags only on shell
pages, and the narrowest CSP change (`manifest-src 'self'` on shell pages only; every other route unchanged).
Synthetic data only (StubAdapter), no upstream."""
import json
import struct
import unittest
import zlib

from avrana_home.app import install
from avrana_home.app.middleware import CSP, CSP_SEARCH
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

MEMBER = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
NO_GROUPS_HEADER = [(USER, "member-a")]                     # no principal: the portal's no-group view
MANIFEST_CSP = CSP.decode() + "; manifest-src 'self'"
HEAD_TAGS = ('<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">',
             '<link rel="apple-touch-icon" href="/icons/avrana-180.png">',
             '<meta name="theme-color" content="#000000">',
             '<meta name="apple-mobile-web-app-capable" content="yes">')
SHELL_ROUTES = ("/", "/account", "/help", "/help/movies", "/search", "/search?q=Film")
OTHER_ROUTES = ("/watch", "/request", "/read", "/nope", "/healthz", "/home.json", "/manifest.webmanifest",
                "/icons/avrana-192.png", "/art/jellyfin/primary/aaaa0000000000000000000000000001",
                "/help/comics", "/outpost.goauthentik.io/sign_out")


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
        self.assertEqual(("Avrana", "Avrana", "standalone", "/", "/", "#000000", "#000000"),
                         (m["name"], m["short_name"], m["display"], m["start_url"], m["scope"],
                          m["background_color"], m["theme_color"]))
        self.assertEqual({"192x192", "512x512"}, {i["sizes"] for i in m["icons"]})
        for icon in m["icons"]:
            self.assertTrue(icon["src"].startswith("/icons/") and icon["type"] == "image/png")
            self.assertEqual(200, self.client().get(icon["src"]).status_code, icon["src"])
        self.assertNotIn("serviceworker", r.text.lower())

    def test_icons_are_monochrome_pngs_of_the_declared_size(self):
        c = self.client()
        for n in install.ICON_SIZES:
            r = c.get(f"/icons/avrana-{n}.png")
            self.assertEqual((200, "image/png"), (r.status_code, r.headers["content-type"]))
            self.assertEqual((n, n, 8, 0), png_size(r.content))            # 8-bit greyscale
            # decode and check: only black and white, both present
            data, pos, idat = r.content, 8, b""
            while pos < len(data):
                length, kind = struct.unpack(">I4s", data[pos:pos + 8])
                if kind == b"IDAT":
                    idat += data[pos + 8:pos + 8 + length]
                pos += 12 + length
            raw = zlib.decompress(idat)
            self.assertLessEqual(set(raw), {0, 255})                       # black, white, filter byte 0
            self.assertIn(255, raw)
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
                     "/manifest.json", "/sw.js", "/service-worker.js"):
            r = c.get(path, headers=MEMBER)
            self.assertEqual((404, nf), (r.status_code, r.text), path)

    def test_with_sections_off_the_routes_do_not_exist_and_pages_carry_no_tags(self):
        c = self.client(sections=False)
        nf = c.get("/nope", headers=MEMBER).text
        for path in ["/manifest.webmanifest"] + list(install.ICON_PATHS):
            r = c.get(path, headers=MEMBER)
            self.assertEqual((404, nf), (r.status_code, r.text), path)
        for path in ("/", "/account", "/help"):
            page = c.get(path, headers=MEMBER).text
            for tag in ("manifest", "apple-touch-icon", "theme-color", "apple-mobile-web-app"):
                self.assertNotIn(tag, page, path)

    def test_there_is_no_script_anywhere(self):
        c = self.client()
        for path in SHELL_ROUTES:
            self.assertNotIn("<script", c.get(path, headers=MEMBER).text.lower(), path)


class HeadTagsAndCsp(Base):
    def test_shell_pages_link_the_manifest_and_allow_only_it(self):
        c = self.client()
        for path in SHELL_ROUTES:
            with self.subTest(path=path):
                r = c.get(path, headers=MEMBER)
                self.assertEqual(200, r.status_code)
                for tag in HEAD_TAGS:
                    self.assertIn(tag, r.text)
                want = (CSP_SEARCH.decode() + "; manifest-src 'self'") if path.startswith("/search") else MANIFEST_CSP
                self.assertEqual(want, r.headers["content-security-policy"])
                self.assertNotIn("script-src", r.headers["content-security-policy"])

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
        for path in ("/", "/account", "/help"):
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
