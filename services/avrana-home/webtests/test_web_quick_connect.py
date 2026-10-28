"""Tier B: "Sign in on a TV" (Media 2.0 ME-05; owner decision 2026-10-27; quickconnect.py, forms.py). SYNTHETIC only.

What this slice adds and must never weaken:
  * /me/tv exists only with the shell, a verified member with TV and Movies, and Quick Connect wired; otherwise GET is
    the standard 404 and POST the standard 501, the same bytes as any other path.
  * A POST is accepted only when every lock holds: same-origin form post (Sec-Fetch-Site, or Origin = Host), form
    content type, a small body with only the allow-listed fields, and a form token for THIS member.
  * The answer is always a 303 back to /me/tv with a fixed result id; the code never appears in a log line.
  * The page offers Jellyfin's own Quick Connect page from the catalogue's fixed host, and carries form-action 'self'.
"""
import json
import logging
import re
import unittest
from urllib.parse import urlencode

from avrana_home.app.middleware import CSP
from avrana_home.quickconnect import QuickConnect
from avrana_home.resilience import TransportResponse
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

VIDEO = [(USER, "member-a"), ("X-authentik-name", "Member A"), (GROUPS, "avrana-users|avrana-videos")]
OTHER = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos")]
ADMIN = [(USER, "synthetic-admin"), (GROUPS, "avrana-users|avrana-videos")]
BOOKS = [(USER, "member-k"), (GROUPS, "avrana-users|avrana-books")]
SAME = [("Content-Type", "application/x-www-form-urlencoded"), ("Sec-Fetch-Site", "same-origin")]
A_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USERS = [{"Id": A_ID, "Name": "member-a", "Policy": {"IsAdministrator": False, "IsDisabled": False}},
         {"Id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "Name": "member-b",
          "Policy": {"IsAdministrator": False, "IsDisabled": False}},
         {"Id": "dddddddddddd4ddd8dddddddddddddd1", "Name": "synthetic-admin",
          "Policy": {"IsAdministrator": True, "IsDisabled": False}}]


class FakeJellyfin:
    def __init__(self):
        self.calls = []

    def request(self, method, path, query, timeout, max_bytes):
        self.calls.append((method, path, dict(query or {})))
        if path == "/QuickConnect/Enabled":
            return TransportResponse(200, b"true", "application/json")
        if path == "/Users":
            return TransportResponse(200, json.dumps(USERS).encode(), "application/json")
        return TransportResponse(200, b"true", "application/json")

    def approvals(self):
        return [c[2] for c in self.calls if c[1] == "/QuickConnect/Authorize"]


def main_of(text):
    return re.split(r"<main(?:\s[^>]*)?>", text)[1].split("</main>")[0]


def make(qc=True, sections=True):
    fake = FakeJellyfin()
    data = {"member-a": [("a" * 32, "Synthetic TV Film", 0.5)]}
    client = make_client(make_settings(home_sections=sections), adapters=[StubAdapter(data)] if sections else None,
                         quick_connect=QuickConnect(fake) if qc else None)
    return client, fake


class TvBase(unittest.TestCase):
    def setUp(self):
        self.client, self.fake = make()
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def token(self, headers=VIDEO):
        page = self.client.get("/me/tv", headers=headers)
        self.assertEqual(200, page.status_code)
        return re.search(r'name="t" value="([^"]+)"', page.text).group(1)

    def post(self, body, headers=VIDEO, extra=SAME):
        data = body if isinstance(body, (bytes, str)) else urlencode(body)
        return self.client.post("/me/tv", content=data, headers=headers + extra)


class Gating(unittest.TestCase):
    def test_off_unless_shell_member_tv_access_and_wiring(self):
        for qc, sections, headers in ((False, True, VIDEO), (True, False, VIDEO), (True, True, []),
                                      (True, True, BOOKS)):
            client, fake = make(qc=qc, sections=sections)
            with client, self.subTest(qc=qc, sections=sections, headers=headers):
                nope = client.get("/nope", headers=headers)
                r = client.get("/me/tv", headers=headers)
                self.assertEqual((404, nope.text), (r.status_code, r.text))
                if not (qc and sections):
                    other = client.post("/nope", headers=headers)
                    post = client.post("/me/tv", content="code=123456", headers=headers + SAME)
                    self.assertEqual((501, other.text), (post.status_code, post.text))
                self.assertEqual([], fake.approvals())

    def test_only_the_exact_path_takes_a_post(self):
        client, _fake = make()
        with client:
            for path in ("/me/tv/", "//me/tv", "/me/TV", "/me", "/", "/me/security"):
                self.assertEqual(501, client.post(path, content="code=1", headers=VIDEO + SAME).status_code, path)

    def test_me_shows_the_row_only_to_members_with_tv_and_movies(self):
        client, _fake = make()
        with client:
            self.assertIn('href="/me/tv"', main_of(client.get("/me", headers=VIDEO).text))
            self.assertNotIn('href="/me/tv"', main_of(client.get("/me", headers=BOOKS).text))
        client, _fake = make(qc=False)
        with client:
            self.assertNotIn('href="/me/tv"', main_of(client.get("/me", headers=VIDEO).text))


class Page(TvBase):
    def test_form_hand_off_and_csp(self):
        r = self.client.get("/me/tv", headers=VIDEO)
        main = main_of(r.text)
        self.assertIn('<form class="srch" method="post" action="/me/tv">', main)
        self.assertIn('pattern="[0-9]{6}"', main)
        self.assertIn('href="https://watch.avrana.net/web/#/quickconnect"', main)
        self.assertIn("as Member A", main)
        self.assertIn("form-action 'self'", r.headers["content-security-policy"])
        self.assertTrue(r.headers["content-security-policy"].startswith(CSP.decode().split(" form-action")[0]))
        self.assertEqual([], self.fake.approvals())                     # loading the page approves nothing

    def test_an_administrator_gets_only_the_hand_off(self):
        main = main_of(self.client.get("/me/tv", headers=ADMIN).text)
        self.assertNotIn("<form", main)
        self.assertIn("can't approve TV codes here", main)
        self.assertIn("watch.avrana.net/web/#/quickconnect", main)

    def test_results_are_fixed_words_and_unknown_ids_are_ignored(self):
        self.assertIn("Approved. Your TV should sign in", main_of(self.client.get("/me/tv?r=approved", headers=VIDEO).text))
        for junk in ("%3Cscript%3E", "Approved", "approved%00", "x" * 40):
            main = main_of(self.client.get("/me/tv?r=" + junk, headers=VIDEO).text)
            self.assertNotIn('role="status"', main, junk)
            self.assertNotIn("<script>", main)


class Post(TvBase):
    def test_approves_and_redirects_back(self):
        r = self.post({"t": self.token(), "code": "123456"})
        self.assertEqual((303, "/me/tv?r=approved"), (r.status_code, r.headers["location"]))
        self.assertEqual([{"code": "123456", "userId": A_ID.replace("-", "")}], self.fake.approvals())

    def test_cross_site_and_wrong_content_types_are_refused(self):
        token = self.token()
        body = {"t": token, "code": "123456"}
        ctype = [("Content-Type", "application/x-www-form-urlencoded")]
        for extra in (ctype,                                                     # no Sec-Fetch-Site, no Origin
                      ctype + [("Sec-Fetch-Site", "cross-site")], ctype + [("Sec-Fetch-Site", "same-site")],
                      ctype + [("Sec-Fetch-Site", "none")],
                      ctype + [("Origin", "https://evil.example")], ctype + [("Origin", "null")],
                      [("Content-Type", "multipart/form-data; boundary=x"), ("Sec-Fetch-Site", "same-origin")],
                      [("Content-Type", "application/json"), ("Sec-Fetch-Site", "same-origin")],
                      [("Content-Type", "text/plain"), ("Sec-Fetch-Site", "same-origin")],
                      SAME + [("Sec-Fetch-Site", "same-origin")]):                # a repeated header
            with self.subTest(extra=extra):
                self.assertEqual(403, self.post(body, extra=extra).status_code)
        self.assertEqual([], self.fake.approvals())

    def test_origin_equal_to_host_is_accepted_for_browsers_without_fetch_metadata(self):
        r = self.post({"t": self.token(), "code": "123456"},
                      extra=[("Content-Type", "application/x-www-form-urlencoded"), ("Origin", "http://portal.test")])
        self.assertEqual("/me/tv?r=approved", r.headers["location"])

    def test_tokens_bind_to_the_member(self):
        for token in ("", "nope", "1.x", self.token(OTHER)):
            with self.subTest(token=token[:8]):
                r = self.post({"t": token, "code": "123456"})
                self.assertEqual("/me/tv?r=expired", r.headers["location"])
        r = self.post({"code": "123456"})
        self.assertEqual("/me/tv?r=expired", r.headers["location"])
        self.assertEqual([], self.fake.approvals())

    def test_malformed_bodies_are_400_and_send_nothing(self):
        token = self.token()
        for body in (f"t={token}&code=123456&extra=1", f"t={token}&code=123456&code=654321", "code=" + "1" * 2000,
                     "%ff=1".encode("latin-1") + b"\xff", "t", f"t={token}&code=12345é"):
            with self.subTest(body=str(body)[:20]):
                self.assertEqual(400, self.post(body).status_code)
        self.assertEqual([], self.fake.approvals())

    def test_admins_and_bad_codes_never_reach_the_approval(self):
        admin_token = self.client.fastapi_app.state.form_tokens.issue("tv", "synthetic-admin")   # no form is shown
        r = self.post({"t": admin_token, "code": "123456"}, headers=ADMIN)
        self.assertEqual("/me/tv?r=not_eligible", r.headers["location"])
        r = self.post({"t": self.token(), "code": "12 456"})
        self.assertEqual("/me/tv?r=bad_code", r.headers["location"])
        self.assertEqual([], self.fake.approvals())

    def test_the_code_never_reaches_a_log_line(self):
        with self.assertLogs("avrana_home", level="INFO") as logs:
            self.post({"t": self.token(), "code": "987654"})
        text = " ".join(repr(r.__dict__) for r in logs.records)
        self.assertIn("quick_connect", text)
        self.assertNotIn("987654", text)
        self.assertNotIn("member-a", text)


if __name__ == "__main__":
    unittest.main()
