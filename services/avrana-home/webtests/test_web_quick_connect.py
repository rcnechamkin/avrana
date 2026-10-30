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
from avrana_home.resilience import TransportResponse, UpstreamTimeout, classify_status
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
                # Wired or not, someone without TV and Movies gets the same 501 as a POST anywhere else.
                other = client.post("/nope", content="code=123456", headers=headers + SAME)
                post = client.post("/me/tv", content="code=123456", headers=headers + SAME)
                self.assertEqual((501, other.text, other.headers["content-type"]),
                                 (post.status_code, post.text, post.headers["content-type"]))
                self.assertEqual([], fake.approvals())

    def test_only_the_exact_path_takes_a_post(self):
        client, _fake = make()
        with client:
            for path in ("/me/tv/", "//me/tv", "/me/TV", "/me", "/", "/me/security"):
                self.assertEqual(501, client.post(path, content="code=1", headers=VIDEO + SAME).status_code, path)

    def test_me_shows_the_row_only_to_members_with_tv_and_movies(self):
        client, _fake = make()
        with client:
            me = main_of(client.get("/me", headers=VIDEO).text)
            self.assertIn('href="/me/tv"', me)
            self.assertLess(me.index('id="me-devices"'), me.index('id="me-account"'))    # setup first (ME-01)
            self.assertNotIn('href="/me/tv"', main_of(client.get("/me", headers=BOOKS).text))
        client, _fake = make(qc=False)
        with client:
            self.assertNotIn('href="/me/tv"', main_of(client.get("/me", headers=VIDEO).text))


class Page(TvBase):
    def test_form_hand_off_and_csp(self):
        r = self.client.get("/me/tv", headers=VIDEO)
        main = main_of(r.text)
        self.assertIn('<form class="srch" method="post" action="/me/tv" data-once>', main)
        self.assertIn('data-busy="Approving', main)                    # home.js part 11: a second press sends nothing
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
        for origin in ("http://portal.test", "http://Portal.TEST"):                 # host names ignore case
            with self.subTest(origin=origin):
                r = self.post({"t": self.token(), "code": "123456"},
                              extra=[("Content-Type", "application/x-www-form-urlencoded"), ("Origin", origin)])
                self.assertEqual("/me/tv?r=approved", r.headers["location"])

    def test_a_double_submit_approves_once_and_both_read_approved(self):
        body = {"t": self.token(), "code": "123456"}
        first, second = self.post(body), self.post(body)
        self.assertEqual(["/me/tv?r=approved"] * 2, [first.headers["location"], second.headers["location"]])
        self.assertEqual(1, len(self.fake.approvals()))
        self.post({"t": body["t"], "code": "654321"})                           # another code is another approval
        self.assertEqual(2, len(self.fake.approvals()))

    def test_tokens_bind_to_the_member(self):
        for token in ("", "nope", "1.x", "².x", "99999999999.é", "1.x.y", self.token(OTHER)):
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


class ScriptedJellyfin(FakeJellyfin):
    """A Jellyfin that fails on cue. `authorize` is an HTTP status (raised the way the real transport raises it), the
    string "false"/"true" (a 200 body), or an exception; `users` likewise an exception."""

    def __init__(self, enabled=b"true", authorize="true", users=None):
        super().__init__()
        self.enabled, self.authorize, self.users = enabled, authorize, users

    def request(self, method, path, query, timeout, max_bytes):
        if path == "/QuickConnect/Enabled":
            self.calls.append((method, path, dict(query or {})))
            return TransportResponse(200, self.enabled, "application/json")
        if path == "/Users" and self.users is not None:
            self.calls.append((method, path, dict(query or {})))
            raise self.users
        if path == "/QuickConnect/Authorize":
            self.calls.append((method, path, dict(query or {})))
            if isinstance(self.authorize, int):
                raise classify_status(self.authorize)
            if isinstance(self.authorize, BaseException):
                raise self.authorize
            return TransportResponse(200, self.authorize.encode(), "application/json")
        return super().request(method, path, query, timeout, max_bytes)


# (label, how the fake Jellyfin misbehaves, redirect id, whether Authorize is reached)
SCRIPTS = (
    ("enabled false", dict(enabled=b"false"), "off", False),
    ("authorize 404", dict(authorize=404), "not_found", True),
    ("authorize 401", dict(authorize=401), "off", True),
    ("authorize 403", dict(authorize=403), "unavailable", True),
    ("authorize 500", dict(authorize=500), "not_accepted", True),
    ("authorize false", dict(authorize="false"), "not_accepted", True),
    ("authorize timeout", dict(authorize=UpstreamTimeout()), "unknown", True),
    ("users timeout", dict(users=UpstreamTimeout()), "unavailable", False),
)
SENTENCES = {
    "off": "Quick Connect is switched off for TV and Movies right now.",
    "not_found": "That code didn't work. Check the numbers on your TV; codes last 10 minutes.",
    "unavailable": "TV and Movies couldn't be reached. Try again in a moment, or approve the code in TV and Movies itself.",
    "not_accepted": "That code didn't go through. It may already have been used. Get a new code on the TV and try again.",
    "unknown": "We couldn't tell whether it went through. Look at your TV before trying again.",
    "approved": "Approved. Your TV should sign in within a few seconds",
    "bad_code": "Enter the 6 numbers shown on your TV.",
    "not_eligible": "This account can't approve TV codes here. Approve the code in TV and Movies itself instead.",
    "busy": "Too many tries. Wait 10 minutes, then try again.",
    "expired": "This page was open too long. Enter the code again.",
}


def status_text(page):
    return re.search(r'<p class="note msg" role="status">(.*?)</p>', main_of(page), re.S).group(1).strip()


class Outcomes(unittest.TestCase):
    """T-07: every documented Quick Connect outcome, from the upstream failure to the sentence on /me/tv."""

    def start(self, **script):
        fake = ScriptedJellyfin(**script)
        client = make_client(make_settings(home_sections=True), adapters=[StubAdapter({})],
                             quick_connect=QuickConnect(fake))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client, fake

    def submit(self, client, code="123456"):
        found = re.search(r'name="t" value="([^"]+)"', client.get("/me/tv", headers=VIDEO).text)
        if found is None:               # the status is already off/unavailable: no form to read a token from
            token = client.fastapi_app.state.form_tokens.issue("tv", "member-a")
        else:
            token = found.group(1)
        return client.post("/me/tv", content=urlencode({"t": token, "code": code}), headers=VIDEO + SAME)

    def test_each_upstream_failure_maps_to_its_documented_redirect(self):
        for label, script, expected, reaches_authorize in SCRIPTS:
            with self.subTest(label):
                client, fake = self.start(**script)
                r = self.submit(client)
                self.assertEqual((303, f"/me/tv?r={expected}"), (r.status_code, r.headers["location"]))
                self.assertEqual(1 if reaches_authorize else 0, len(fake.approvals()))     # counted once, never retried
                self.assertNotIn("123456", r.headers["location"])

    def test_each_outcome_renders_one_fixed_sentence_in_the_status_region(self):
        seen = {}
        client, fake = self.start()
        for outcome, words in SENTENCES.items():
            with self.subTest(outcome):
                page = client.get(f"/me/tv?r={outcome}", headers=VIDEO)
                text = status_text(page.text)
                self.assertIn(words, text)
                self.assertEqual(1, main_of(page.text).count('role="status"'))
                seen[outcome] = text
        self.assertEqual([], fake.approvals())                            # a GET approves nothing
        self.assertEqual(len(SENTENCES), len(set(seen.values())))         # no two outcomes share a sentence

    def test_unknown_says_it_may_have_worked_and_to_look_at_the_tv_first(self):
        client, fake = self.start(authorize=UpstreamTimeout())
        r = self.submit(client)
        self.assertEqual("/me/tv?r=unknown", r.headers["location"])
        text = status_text(client.get(r.headers["location"], headers=VIDEO).text)
        self.assertIn("couldn't tell whether it went through", text)
        self.assertIn("Look at your TV before trying again", text)
        self.assertNotIn("Approved", text)
        self.assertEqual(1, len(fake.approvals()))                        # never retried automatically

    def test_no_upstream_text_or_status_code_reaches_the_page(self):
        for label, script, _expected, _reach in SCRIPTS:
            with self.subTest(label):
                client, _fake = self.start(**script)
                r = self.submit(client)
                page = client.get(r.headers["location"], headers=VIDEO)
                text = status_text(page.text)
                for leak in ("401", "403", "404", "500", "HTTP", "Upstream", "Traceback", "timed out", "Timeout",
                             "false", "Exception"):
                    self.assertNotIn(leak, text, leak)
                for leak in ("HTTP", "Upstream", "Traceback", "Timeout"):
                    self.assertNotIn(leak, page.text, leak)

    def test_a_double_submit_of_one_approval_is_counted_once(self):
        client, fake = self.start()
        found = re.search(r'name="t" value="([^"]+)"', client.get("/me/tv", headers=VIDEO).text).group(1)
        body = urlencode({"t": found, "code": "123456"})
        locations = [client.post("/me/tv", content=body, headers=VIDEO + SAME).headers["location"] for _ in range(2)]
        self.assertEqual(["/me/tv?r=approved"] * 2, locations)
        self.assertEqual(1, len(fake.approvals()))

    def test_the_sixth_try_in_the_window_is_busy_and_asks_nothing(self):
        client, fake = self.start(authorize=404)
        found = re.search(r'name="t" value="([^"]+)"', client.get("/me/tv", headers=VIDEO).text).group(1)
        where = [client.post("/me/tv", content=urlencode({"t": found, "code": f"12345{n}"}),
                             headers=VIDEO + SAME).headers["location"] for n in range(6)]
        self.assertEqual(["/me/tv?r=not_found"] * 5 + ["/me/tv?r=busy"], where)
        self.assertEqual(5, len(fake.approvals()))                        # the sixth reached no upstream
        calls = len(fake.calls)
        client.post("/me/tv", content=urlencode({"t": found, "code": "123450"}), headers=VIDEO + SAME)
        self.assertEqual(calls, len(fake.calls))

    def test_a_refused_code_is_not_remembered_so_the_next_try_is_a_new_approval(self):
        client, fake = self.start(authorize=404)
        found = re.search(r'name="t" value="([^"]+)"', client.get("/me/tv", headers=VIDEO).text).group(1)
        body = urlencode({"t": found, "code": "123456"})
        for _ in range(2):
            self.assertEqual("/me/tv?r=not_found",
                             client.post("/me/tv", content=body, headers=VIDEO + SAME).headers["location"])
        self.assertEqual(2, len(fake.approvals()))


class ReplayTests(unittest.TestCase):
    def test_concurrent_repeats_share_one_run_and_only_kept_outcomes_are_remembered(self):
        import asyncio
        from avrana_home.app.forms import Replays
        runs = []

        async def slow(outcome):
            runs.append(outcome)
            await asyncio.sleep(0.01)
            return outcome

        async def scenario():
            replays = Replays(keep=frozenset({"approved"}))
            together = await asyncio.gather(*(replays.once(("m", "t", "1"), lambda: slow("approved")) for _ in range(3)))
            later = await replays.once(("m", "t", "1"), lambda: slow("never"))
            first = await replays.once(("m", "t", "2"), lambda: slow("not_found"))
            again = await replays.once(("m", "t", "2"), lambda: slow("not_found"))
            return together, later, first, again
        together, later, first, again = asyncio.run(scenario())
        self.assertEqual(["approved"] * 3, together)
        self.assertEqual("approved", later)                       # remembered: no second upstream write
        self.assertEqual(("not_found", "not_found"), (first, again))
        self.assertEqual(["approved", "not_found", "not_found"], runs)   # a not-kept outcome may be tried again


if __name__ == "__main__":
    unittest.main()
