"""Tier B: Me -> My profile (owner 2026-10-28: members edit their picture; memberstore.py, avatar.py). SYNTHETIC data.

What this slice adds and must never weaken:
  * /me/profile and /me/avatar exist only with the shell and a verified member (otherwise the standard 404).
  * The photo is Home's own small WebP: any metadata in the upload (location included) is gone, only JPEG/PNG/WebP are
    accepted (by their bytes), oversized and decompression-bomb images are refused, and a member only ever gets their
    own photo.
  * Every save goes through the locks: same origin, a bounded multipart body with only the allow-listed fields, this
    member's form token, and the version the page was drawn from (a stale save is a conflict, never an overwrite).
  * With the store off, the page says edits aren't on and the shell is exactly as before.
"""
import io
import re
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from avrana_home.memberstore import MemberStore, clean_name
from avrana_home.app import avatar
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

from PIL import Image  # noqa: E402  (the dependency this slice adds)

NAME = "X-authentik-name"
A = [(USER, "member-a"), (NAME, "Member A"), (GROUPS, "avrana-users|avrana-videos")]
B = [(USER, "member-b"), (NAME, "Member B"), (GROUPS, "avrana-users|avrana-videos")]


def jpeg(size=(1200, 800), colour=(200, 40, 40), exif_gps=True):
    im = Image.new("RGB", size, colour)
    out = io.BytesIO()
    exif = Image.Exif()
    if exif_gps:
        exif[0x8825] = {2: (51.0, 30.0, 0.0), 1: "N"}         # GPSInfo
        exif[0x010F] = "SyntheticCam"
    im.save(out, format="JPEG", exif=exif.tobytes())
    return out.getvalue()


def multipart(fields, file_bytes=None, filename="p.jpg", ctype="image/jpeg", boundary="XyZboundary42"):
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    if file_bytes is not None:
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="{filename}"\r\n'
                      f'Content-Type: {ctype}\r\n\r\n').encode() + file_bytes + b"\r\n")
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemberStore(Path(self.tmp.name) / "members.sqlite3")
        data = {"member-a": [("a" * 32, "Synthetic Film", 0.5)], "member-b": []}
        self.client = make_client(make_settings(home_sections=True), adapters=[StubAdapter(data)],
                                  member_store=self.store)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.store.close()
        self.tmp.cleanup()

    def page(self, headers=A, query=""):
        r = self.client.get("/me/profile" + query, headers=headers)
        self.assertEqual(200, r.status_code)
        return r.text

    def fields(self, headers=A):
        text = self.page(headers)
        token = re.search(r'name="t" value="([^"]+)"', text).group(1)
        version = re.search(r'name="v" value="([^"]+)"', text).group(1)
        return token, version

    def post(self, body_ctype, headers=A, site="same-origin"):
        body, ctype = body_ctype
        h = dict(headers)
        h.update({"Content-Type": ctype, "Sec-Fetch-Site": site})
        return self.client.post("/me/profile", content=body, headers=h)


class Photo(Base):
    def test_upload_stores_a_small_square_webp_with_no_metadata_and_shows_it(self):
        t, v = self.fields()
        r = self.post(multipart({"t": t, "v": v, "do": "photo"}, jpeg()))
        self.assertEqual((303, "/me/profile?r=photo_saved"), (r.status_code, r.headers["location"]))
        got = self.client.get("/me/avatar", headers=A)
        self.assertEqual(200, got.status_code)
        self.assertEqual("image/webp", got.headers["content-type"])
        self.assertIn("private", got.headers["cache-control"])
        im = Image.open(io.BytesIO(got.content))
        self.assertEqual(("WEBP", (256, 256)), (im.format, im.size))
        self.assertFalse(im.getexif())
        self.assertNotIn(b"SyntheticCam", got.content)
        self.assertNotIn(b"Exif", got.content)
        # the Me hub and the tab show it, versioned
        me = self.client.get("/me", headers=A).text
        self.assertRegex(me, r'<img class="me-av me-av-img" src="/me/avatar\?v=[0-9a-f]{20}"')
        self.assertRegex(me, r'<img class="me me-img" src="/me/avatar\?v=[0-9a-f]{20}"')
        etag = got.headers["etag"]
        self.assertEqual(304, self.client.get("/me/avatar", headers=A + [("If-None-Match", etag)]).status_code)

    def test_each_member_gets_only_their_own_photo(self):
        t, v = self.fields()
        self.post(multipart({"t": t, "v": v, "do": "photo"}, jpeg()))
        self.assertEqual(404, self.client.get("/me/avatar", headers=B).status_code)
        self.assertNotIn("/me/avatar", self.client.get("/me", headers=B).text)

    def test_remove_goes_back_to_the_initial(self):
        t, v = self.fields()
        self.post(multipart({"t": t, "v": v, "do": "photo"}, jpeg()))
        t, v = self.fields()
        r = self.post(multipart({"t": t, "v": v, "do": "remove"}))
        self.assertEqual("/me/profile?r=photo_removed", r.headers["location"])
        self.assertEqual(404, self.client.get("/me/avatar", headers=A).status_code)
        self.assertIn('<span class="me-av" aria-hidden="true">M</span>', self.client.get("/me", headers=A).text)

    def test_png_with_transparency_and_webp_are_accepted(self):
        for fmt in ("PNG", "WEBP"):
            out = io.BytesIO()
            Image.new("RGBA", (300, 500), (0, 0, 255, 0)).save(out, format=fmt)
            t, v = self.fields()
            r = self.post(multipart({"t": t, "v": v, "do": "photo"}, out.getvalue(), "x." + fmt.lower()))
            self.assertEqual("/me/profile?r=photo_saved", r.headers["location"], fmt)

    def test_refusals(self):
        gif = io.BytesIO()
        Image.new("RGB", (10, 10)).save(gif, format="GIF")
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        for data, why in ((b"not an image at all", "not_image"), (svg, "not_image"), (gif.getvalue(), "not_image"),
                          (jpeg()[:200], "not_image")):
            t, v = self.fields()
            r = self.post(multipart({"t": t, "v": v, "do": "photo"}, data, ctype="image/jpeg"))
            self.assertEqual(f"/me/profile?r={why}", r.headers["location"], why)
        t, v = self.fields()
        self.assertEqual("/me/profile?r=no_file",
                         self.post(multipart({"t": t, "v": v, "do": "photo"}, b""))
                         .headers["location"])
        self.assertEqual(404, self.client.get("/me/avatar", headers=A).status_code)

    def test_decompression_bomb_is_refused_before_decoding(self):
        with self.assertRaises(avatar.AvatarError) as caught:
            out = io.BytesIO()
            Image.new("1", (8000, 8000)).save(out, format="PNG")      # 64 MP, a few KB
            avatar.process(out.getvalue())
        self.assertEqual(avatar.TOO_MANY_PIXELS, caught.exception.reason)

    def test_oversized_body_is_413_before_the_app(self):
        t, v = self.fields()
        big = multipart({"t": t, "v": v, "do": "photo"}, b"\xff" * (11 * 1024 * 1024))
        self.assertEqual(413, self.post(big).status_code)


class Name(Base):
    def test_name_shows_in_the_shell_and_empty_goes_back(self):
        t, v = self.fields()
        r = self.post(multipart({"t": t, "v": v, "do": "name", "name": "  Sam   N.  "}))
        self.assertEqual("/me/profile?r=name_saved", r.headers["location"])
        me = self.client.get("/me", headers=A).text
        self.assertIn('<p class="me-name">Sam N.</p>', me)
        self.assertIn("signed in as Sam N.", me)
        t, v = self.fields()
        self.post(multipart({"t": t, "v": v, "do": "name", "name": ""}))
        self.assertIn('<p class="me-name">Member A</p>', self.client.get("/me", headers=A).text)

    def test_names_are_escaped_and_bounded(self):
        t, v = self.fields()
        self.post(multipart({"t": t, "v": v, "do": "name", "name": "<b>x</b>"}))
        me = self.client.get("/me", headers=A).text
        self.assertNotIn("<b>x</b>", me)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", me)
        t, v = self.fields()
        r = self.post(multipart({"t": t, "v": v, "do": "name", "name": "x" * 41}))
        self.assertEqual("/me/profile?r=invalid_name", r.headers["location"])
        self.assertEqual("ab c", clean_name("a​b\u0000 \n c"))


class Locks(Base):
    def test_stale_version_is_a_conflict_not_an_overwrite(self):
        t, v = self.fields()
        self.post(multipart({"t": t, "v": v, "do": "name", "name": "First"}))
        r = self.post(multipart({"t": t, "v": v, "do": "name", "name": "Second"}))     # the old page again
        self.assertEqual("/me/profile?r=conflict", r.headers["location"])
        self.assertIn('<p class="me-name">First</p>', self.client.get("/me", headers=A).text)

    def test_token_site_and_field_locks(self):
        t, v = self.fields()
        # another member's token
        self.assertEqual("/me/profile?r=expired",
                         self.post(multipart({"t": t, "v": v, "do": "name", "name": "x"}), headers=B).headers["location"])
        # cross-site
        self.assertEqual(403, self.post(multipart({"t": t, "v": v, "do": "name", "name": "x"}), site="cross-site")
                         .status_code)
        # urlencoded isn't accepted here; unknown or repeated fields aren't either
        h = dict(A, **{"Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(403, self.client.post("/me/profile", content=f"t={t}&v={v}&do=name&name=x", headers=h)
                         .status_code)
        body, ctype = multipart({"t": t, "v": v, "do": "name", "name": "x", "admin": "1"})
        self.assertEqual(400, self.post((body, ctype)).status_code)
        self.assertEqual(Path(self.tmp.name, "members.sqlite3").exists(), True)
        self.assertEqual(0, self.store.profile("member-a").version)

    def test_gating(self):
        nope = self.client.get("/nope", headers=[])
        for path in ("/me/profile", "/me/avatar"):
            r = self.client.get(path, headers=[])
            self.assertEqual((404, nope.text), (r.status_code, r.text), path)


class StoreOff(unittest.TestCase):
    def test_page_says_not_on_and_post_is_501(self):
        with make_client(make_settings(home_sections=True), adapters=[StubAdapter({"member-a": []})]) as c:
            text = c.get("/me/profile", headers=A).text
            self.assertIn("isn't switched on yet", text)
            self.assertNotIn("<form", text.split("<main", 1)[1])
            self.assertEqual(404, c.get("/me/avatar", headers=A).status_code)
            body, ctype = multipart({"do": "name"})
            self.assertEqual(501, c.post("/me/profile", content=body,
                                         headers=dict(A, **{"Content-Type": ctype})).status_code)

    def test_purge_removes_everything(self):
        with tempfile.TemporaryDirectory() as d:
            store = MemberStore(Path(d) / "m.sqlite3")
            store.save_name("member-a", "X", 0)
            self.assertTrue(store.purge("member-a"))
            self.assertEqual(0, store.profile("member-a").version)
            store.close()

    def test_purge_command_for_offboarding(self):
        from avrana_home import memberstore
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.sqlite3"
            store = MemberStore(path)
            store.save_name("member-a", "X", 0)
            store.close()
            with unittest.mock.patch.dict("os.environ", {"HOME_MEMBER_STORE": str(path)}), \
                    unittest.mock.patch("sys.stdout"):
                self.assertEqual(0, memberstore.main(["purge", "member-a"]))
            with unittest.mock.patch.dict("os.environ", {"HOME_MEMBER_STORE": ""}), unittest.mock.patch("sys.stderr"):
                self.assertEqual(2, memberstore.main(["purge", "member-a"]))
            store = MemberStore(path)
            self.assertEqual(0, store.profile("member-a").version)
            store.close()


if __name__ == "__main__":
    unittest.main()
