"""Tier A: the request broker's settings, form signing, guard, and the Shelfarr client's allow-list and parsing."""
import json
import unittest

from avrana_home.app.settings import MOCK_API_KEY, Settings, SettingsError
from avrana_home.requests.forms import DOUBLE_TAP_WINDOW, RATE_MAX, RATE_WINDOW, TOKEN_TTL, FormSigner, RequestGuard
from avrana_home.requests.shelfarr import ForbiddenCall, Outcome, ShelfarrRequests, clean_term, member_username
from avrana_home.resilience import MAX_REQUEST_BODY, TransportResponse, UpstreamTimeout

ON = {"HOME_SECTIONS": "on", "HOME_BOOK_REQUESTS": "on", "SHELFARR_BASE_URL": "http://127.0.0.1:18300"}
REAL = {"HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes", "HOME_SECTIONS": "on",
        "JELLYFIN_BASE_URL": "http://jellyfin:8096", "JELLYFIN_API_KEY": "fake-key-for-test",
        "HOME_BOOK_REQUESTS": "on", "SHELFARR_BASE_URL": "http://shelfarr:80", "SHELFARR_TOKEN": "fake-token-for-test"}


class BrokerSettings(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(Settings.from_mapping({}).book_requests)

    def test_mock_mode(self):
        s = Settings.from_mapping(ON)
        self.assertTrue(s.book_requests)
        self.assertEqual(MOCK_API_KEY, s.shelfarr_token)
        self.assertNotIn(MOCK_API_KEY, repr(s))
        for bad in (dict(ON, SHELFARR_TOKEN="real-looking"), dict(ON, SHELFARR_BASE_URL="http://shelfarr:80"),
                    dict(ON, HOME_SECTIONS="off"), {k: v for k, v in ON.items() if k != "SHELFARR_BASE_URL"},
                    {"SHELFARR_BASE_URL": "http://127.0.0.1:1"}):
            with self.subTest(env=bad), self.assertRaises(SettingsError):
                Settings.from_mapping(bad)

    def test_real_mode_needs_a_token_and_a_safe_url(self):
        s = Settings.from_mapping(REAL)
        self.assertEqual("fake-token-for-test", s.shelfarr_token)
        self.assertNotIn("fake-token-for-test", repr(s))
        for bad in ({k: v for k, v in REAL.items() if k != "SHELFARR_TOKEN"},
                    dict(REAL, SHELFARR_BASE_URL="http://192.0.2.10:80"),
                    dict(REAL, SHELFARR_BASE_URL="ftp://shelfarr")):
            with self.subTest(env=bad), self.assertRaises(SettingsError):
                Settings.from_mapping(bad)


class Signing(unittest.TestCase):
    F = {"work_id": "hardcover:1", "book_type": "ebook", "title": "T", "author": "A"}

    def test_round_trip_and_binding(self):
        now = [1000.0]
        s = FormSigner(now=lambda: now[0])
        token = s.sign("member-a", self.F)
        self.assertTrue(s.verify(token, "member-a", self.F))
        self.assertFalse(s.verify(token, "member-b", self.F))
        self.assertFalse(s.verify(token, "member-a", dict(self.F, title="U")))
        self.assertFalse(FormSigner(now=lambda: now[0]).verify(token, "member-a", self.F))   # another process
        for junk in (None, "", "x", "1.zz", token + "0", "9" * 40 + "." + token.split(".")[1]):
            self.assertFalse(s.verify(junk, "member-a", self.F), junk)
        now[0] += TOKEN_TTL + 1
        self.assertFalse(s.verify(token, "member-a", self.F))
        self.assertNotIn("key", repr(s).lower().replace("<redacted>", ""))

    def test_guard(self):
        now = [0.0]
        g = RequestGuard(now=lambda: now[0])
        self.assertIsNone(g.check("a", "k"))
        self.assertEqual("repeat", g.check("a", "k"))
        self.assertIsNone(g.check("b", "k"))
        now[0] += DOUBLE_TAP_WINDOW + 1
        self.assertIsNone(g.check("a", "k"))
        for i in range(RATE_MAX - 2):
            self.assertIsNone(g.check("a", f"k{i}"))
        self.assertEqual("rate", g.check("a", "other"))
        now[0] += RATE_WINDOW + 1
        self.assertIsNone(g.check("a", "other"))


class Recorder:
    def __init__(self, answer=None, raises=None):
        self.calls, self.answer, self.raises = [], answer, raises

    def request(self, method, path, query, timeout, max_bytes, *, json_body=None):
        self.calls.append((method, path, query, json_body))
        if self.raises:
            raise self.raises
        return self.answer


class Client(unittest.TestCase):
    def test_terms_and_usernames(self):
        self.assertIsNone(clean_term("a"))
        self.assertIsNone(clean_term("x" * 101))
        self.assertIsNone(clean_term("bad\x00term"))
        self.assertEqual("two words", clean_term("  two \t words "))
        self.assertEqual("member-a", member_username(" Member-A "))
        self.assertIsNone(member_username("has space"))
        self.assertIsNone(member_username(None))

    def test_only_allow_listed_calls(self):
        c = ShelfarrRequests(Recorder(TransportResponse(200, b"{}")))
        with self.assertRaises(ForbiddenCall):
            c._send("GET", "/api/v1/requests", None, None)
        with self.assertRaises(ForbiddenCall):
            c._send("GET", "/api/v1/search", {"q": "x", "username": "y"}, None)
        with self.assertRaises(ForbiddenCall):
            c._send("POST", "/api/v1/requests", None, b"x" * (MAX_REQUEST_BODY + 1))

    def test_invalid_create_never_calls(self):
        rec = Recorder(TransportResponse(201, b"{}"))
        c = ShelfarrRequests(rec)
        self.assertIs(Outcome.REFUSED, c.create("Has Space", "hardcover:1", "ebook", "T", "A"))
        self.assertIs(Outcome.REFUSED, c.create("a", "not an id", "ebook", "T", "A"))
        self.assertIs(Outcome.REFUSED, c.create("a", "hardcover:1", "paperback", "T", "A"))
        self.assertIs(Outcome.REFUSED, c.create("a", "hardcover:1", "ebook", "", "A"))
        self.assertEqual([], rec.calls)

    def test_create_outcomes(self):
        self.assertIs(Outcome.QUEUED, ShelfarrRequests(Recorder(TransportResponse(202, b"{}")))
                      .create("a", "hardcover:1", "ebook", "T", "A"))
        rec = Recorder(TransportResponse(201, b'{"id": 1}'))
        self.assertIs(Outcome.CREATED, ShelfarrRequests(rec).create("A", "hardcover:1", "audiobook", "T", "A"))
        self.assertEqual("a", json.loads(rec.calls[0][3])["username"])
        self.assertIs(Outcome.UNAVAILABLE, ShelfarrRequests(Recorder(raises=UpstreamTimeout()))
                      .create("a", "hardcover:1", "ebook", "T", "A"))
        self.assertIs(Outcome.UNAVAILABLE, ShelfarrRequests(Recorder(TransportResponse(204, b"")))
                      .create("a", "hardcover:1", "ebook", "T", "A"))

    def test_breaker_opens_and_fails_fast(self):
        rec = Recorder(raises=UpstreamTimeout())
        c = ShelfarrRequests(rec)
        for _ in range(5):
            c.search("dune")
        made = len(rec.calls)
        self.assertEqual(("unavailable", ()), c.search("dune"))
        self.assertEqual(made, len(rec.calls))
        self.assertNotIn("token", repr(c).lower())


if __name__ == "__main__":
    unittest.main()
