"""Tier A/B: creating a member's request account on first ask (HOME_SHELFARR_PROVISION, HOME_SEERR_PROVISION). Off by
default; on, Home creates only a plain account named after the verified member, then asks once more. SYNTHETIC data."""
import json
import re
import unittest
from urllib.parse import urlencode

from avrana_home.requests.seerr import SeerrRequests
from avrana_home.requests.shelfarr import Provisioned, ShelfarrRequests
from avrana_home.resilience import TransportResponse, UpstreamHTTPError, UpstreamNotFound
from .support import GROUPS, USER, PeerOverride, StubAdapter, make_settings, require_framework
from .test_web_book_requests import BOTH, RESULTS, SAME
from .test_web_watch_requests import SEARCH, VIEWER, JellyfinStub

require_framework()
FORM = [("Content-Type", "application/x-www-form-urlencoded")]
PLAIN = [(USER, "Reader_A"), (GROUPS, "avrana-users|avrana-books|avrana-audiobooks")]   # a name Shelfarr can hold


class NewShelfarrMember:
    """Shelfarr with no account for the member until POST /api/v1/users makes one."""

    def __init__(self):
        self.calls, self.exists = [], False

    def request(self, method, path, query, timeout, max_bytes, *, json_body=None):
        body = json.loads(json_body) if json_body else None
        self.calls.append((method, path, body))
        if path == "/api/v1/search":
            return TransportResponse(200, json.dumps(RESULTS).encode())
        if path == "/api/v1/users":
            self.exists = True
            return TransportResponse(201, b'{"id": 4}')
        if not self.exists:
            raise UpstreamNotFound(404)
        return TransportResponse(201, b'{"requests": []}')


class NewSeerrMember:
    """Seerr whose user list lacks member-v until the Jellyfin import adds them."""

    def __init__(self):
        self.calls, self.imported = [], False

    def request(self, method, path, query, timeout, max_bytes, *, json_body=None, act_as=None):
        self.calls.append((method, path, json.loads(json_body) if json_body else None, act_as))
        if path == "/api/v1/user":
            users = [{"id": 1, "permissions": 2, "jellyfinUserId": "e" * 32}]
            if self.imported:
                users.append({"id": 8, "permissions": 32, "jellyfinUserId": "a" * 32})
            return TransportResponse(200, json.dumps({"results": users}).encode())
        if path == "/api/v1/user/import-from-jellyfin":
            self.imported = True
            return TransportResponse(201, b"[]")
        return TransportResponse(200, json.dumps(SEARCH).encode())


def client(**kw):
    from fastapi.testclient import TestClient
    from avrana_home.app.main import create_app
    c = TestClient(PeerOverride(create_app(**kw), ("203.0.113.7", 50000)), base_url="http://portal.test",
                   follow_redirects=False, raise_server_exceptions=False)
    c.__enter__()
    return c


class Shelfarr(unittest.TestCase):
    def run_ask(self, on, who=PLAIN):
        fake = NewShelfarrMember()
        settings = make_settings(home_sections=True, book_requests=True, shelfarr_base_url="http://127.0.0.1:1",
                                 shelfarr_provision=on)
        c = client(settings=settings, adapters=[StubAdapter({})], book_requests=ShelfarrRequests(fake))
        self.addCleanup(c.__exit__, None, None, None)
        page = c.get("/request/books", params={"q": "dune"}, headers=who).text
        form = re.search(r'<form method="post" action="/request/books"[^>]*>(.*?)</form>', page, re.S).group(1)
        fields = dict(re.findall(r'name="([a-z_]+)" value="([^"]*)"', form))
        c.post("/request/books", content=urlencode(fields), headers=FORM + who + SAME)
        return fake, c.get("/request/books", headers=who).text

    def test_off_says_not_set_up_and_creates_nothing(self):
        fake, text = self.run_ask(False)
        self.assertNotIn("/api/v1/users", [c[1] for c in fake.calls])
        self.assertIn("not set up for your account", text)

    def test_on_creates_a_plain_account_then_asks_again(self):
        fake, text = self.run_ask(True)
        made = next(c for c in fake.calls if c[1] == "/api/v1/users")[2]
        self.assertEqual({"name", "username", "password"}, set(made))       # never a role
        self.assertEqual("reader_a", made["username"])
        self.assertGreaterEqual(len(made["password"]), 12)
        self.assertEqual(2, sum(1 for c in fake.calls if c[0] == "POST" and c[1] == "/api/v1/requests"))
        self.assertIn("Asked for the ebook", text)
        self.assertNotIn(made["password"], text)

    def test_a_name_shelfarr_cannot_hold_is_never_provisioned(self):
        fake, text = self.run_ask(True, who=BOTH)                   # "member-a": Shelfarr allows no hyphen
        self.assertNotIn("/api/v1/users", [c[1] for c in fake.calls])
        self.assertIn("not set up for your account", text)
        self.assertIs(Provisioned.EXISTS, ShelfarrRequests(NewShelfarrMember()).provision("jane.doe", "Jane"))

    def test_taken_name_is_left_alone(self):
        class Taken(NewShelfarrMember):
            def request(self, method, path, query, timeout, max_bytes, *, json_body=None):
                if path == "/api/v1/users":
                    raise UpstreamHTTPError(422)
                return super().request(method, path, query, timeout, max_bytes, json_body=json_body)
        self.assertIs(Provisioned.EXISTS, ShelfarrRequests(Taken()).provision("member_a", "A"))


class Seerr(unittest.TestCase):
    def run_search(self, on, path="/request/watch?q=film"):
        fake, jf = NewSeerrMember(), JellyfinStub()
        settings = make_settings(home_sections=True, watch_requests=True, seerr_base_url="http://127.0.0.1:1",
                                 seerr_provision=on)
        c = client(settings=settings, adapters=[jf], watch_requests=SeerrRequests(fake))
        self.addCleanup(c.__exit__, None, None, None)
        return fake, c.get(path, headers=VIEWER).text

    def test_off_says_not_set_up(self):
        fake, text = self.run_search(False)
        self.assertIn("not set up for your account", text)
        self.assertNotIn("/api/v1/user/import-from-jellyfin", [c[1] for c in fake.calls])

    def test_on_imports_the_member_and_searches_as_them(self):
        fake, text = self.run_search(True)
        imported = next(c for c in fake.calls if c[1] == "/api/v1/user/import-from-jellyfin")
        self.assertEqual({"jellyfinUserIds": ["a" * 32]}, imported[2])
        self.assertIsNone(imported[3])                              # the import is the key's own; no member
        self.assertIn("Synthetic Film", text)
        self.assertEqual("8", next(c for c in fake.calls if c[1] == "/api/v1/search")[3])

    def test_viewing_my_requests_never_creates_an_account(self):
        fake, _text = self.run_search(True, "/request/mine")
        self.assertNotIn("/api/v1/user/import-from-jellyfin", [c[1] for c in fake.calls])


if __name__ == "__main__":
    unittest.main()
