"""Tier B: asking for a film or a show through Home (`/request/watch`, the Seerr request broker) through the HTTP
layer, against an in-memory Seerr transport and a Jellyfin-shaped stub (SYNTHETIC data). Every Seerr call is made
AS the member's own Seerr user, found through their Jellyfin user; an administrator account is never acted as."""
import json
import re
import unittest
from urllib.parse import urlencode

from avrana_home.app.settings import Settings, SettingsError
from avrana_home.contract import Kind, MediaItem, SectionResult, UpstreamUser, build_handoff_url
from avrana_home.requests.seerr import SeerrRequests
from avrana_home.resilience import ItemGone, TransportResponse, UpstreamAuthError, UpstreamHTTPError
from .support import GROUPS, USER, PeerOverride, StubAdapter, make_settings, require_framework

require_framework()

JF = {"member-v": "a" * 32, "owner": "b" * 32, "member-n": "c" * 32}
VIEWER = [(USER, "member-v"), (GROUPS, "avrana-users|avrana-videos")]
OWNER = [(USER, "owner"), (GROUPS, "avrana-users|avrana-videos")]
UNMAPPED = [(USER, "member-n"), (GROUPS, "avrana-users|avrana-videos")]
BOOKS = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-books")]
SAME = [("Sec-Fetch-Site", "same-origin")]
IN_LIBRARY = "d" * 32
USERS = {"pageInfo": {}, "results": [
    {"id": 1, "permissions": 2, "jellyfinUserId": "e" * 32},
    {"id": 5, "permissions": 32, "jellyfinUserId": "a" * 32},
    {"id": 6, "permissions": 2 | 32, "jellyfinUserId": "b" * 32},
]}
SEARCH = {"page": 1, "results": [
    {"id": 101, "mediaType": "movie", "title": "Synthetic Film", "releaseDate": "1999-03-31"},
    {"id": 102, "mediaType": "tv", "name": "Synthetic Show", "firstAirDate": "2019-01-01",
     "mediaInfo": {"status": 4, "jellyfinMediaId": IN_LIBRARY}},
    {"id": 103, "mediaType": "movie", "title": "Asked Film", "mediaInfo": {"status": 3}},
    {"id": 104, "mediaType": "movie", "title": "Owned Elsewhere", "mediaInfo": {"status": 5}},
    {"id": 105, "mediaType": "person", "name": "Some Actor"},
    {"id": 106, "mediaType": "movie", "title": "Blocked Film", "mediaInfo": {"status": 6}},
]}


class FakeSeerr:
    def __init__(self):
        self.calls = []
        self.create_raises = None
        self.create_status, self.create_body = 201, {"id": 9, "status": 2}

    def request(self, method, path, query, timeout, max_bytes, *, json_body=None, act_as=None):
        self.calls.append((method, path, dict(query or {}), json.loads(json_body) if json_body else None, act_as))
        if path == "/api/v1/user":
            return TransportResponse(200, json.dumps(USERS).encode())
        if method == "GET":
            return TransportResponse(200, json.dumps(SEARCH).encode())
        if self.create_raises is not None:
            raise self.create_raises
        return TransportResponse(self.create_status, json.dumps(self.create_body).encode())


class JellyfinStub(StubAdapter):
    """Maps members to 32-hex Jellyfin ids; only IN_LIBRARY exists, and only member-v may open it."""

    def __init__(self):
        super().__init__({name: [] for name in JF})
        self.item_calls = 0

    def _resolve_user(self, principal):
        if principal.username not in JF:
            from avrana_home.contract import MappingFailed
            raise MappingFailed("unmapped")
        return UpstreamUser(self.service, JF[principal.username])

    def _item(self, user, item_id):
        self.item_calls += 1
        if item_id != IN_LIBRARY or user.upstream_id != JF["member-v"]:
            raise ItemGone(404)
        return SectionResult.of(self.service, "item", (MediaItem(
            id=f"jellyfin:{item_id}", service=self.service, kind=Kind.SERIES, title="Synthetic Show",
            handoff_url=build_handoff_url(self.service, item_id)),))


class WatchRequestsWeb(unittest.TestCase):
    def client(self, on=True):
        from fastapi.testclient import TestClient
        from avrana_home.app.main import create_app
        self.seerr, self.jf = FakeSeerr(), JellyfinStub()
        settings = make_settings(home_sections=True, watch_requests=on, seerr_base_url="http://127.0.0.1:1")
        app = create_app(settings, adapters=[self.jf], watch_requests=SeerrRequests(self.seerr, timeout=1.0))
        c = TestClient(PeerOverride(app, ("203.0.113.7", 50000)), base_url="http://portal.test",
                       follow_redirects=False, raise_server_exceptions=False)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def rows(self, text):
        return text.split("<li>")[1:]

    def form_of(self, row):
        form = re.search(r'<form method="post" action="/request/watch"[^>]*>(.*?)</form>', row, re.S)
        return dict(re.findall(r'name="([a-z_]+)" value="([^"]*)"', form.group(1))) if form else None

    def ask(self, c, fields, who=VIEWER, extra=SAME):
        return c.post("/request/watch", content=urlencode(fields),
                      headers=[("Content-Type", "application/x-www-form-urlencoded")] + who + extra)

    def searched(self):
        return [call for call in self.seerr.calls if call[1] == "/api/v1/search"]

    # ---- gating ------------------------------------------------------------------------------
    def test_off_and_without_the_group(self):
        c = self.client(on=False)
        self.assertEqual(404, c.get("/request/watch", headers=VIEWER).status_code)
        self.assertEqual(501, c.post("/request/watch", content=b"a=b", headers=VIEWER).status_code)
        c = self.client()
        for who in (BOOKS, []):
            self.assertEqual(404, c.get("/request/watch", params={"q": "film"}, headers=who).status_code)
            self.assertEqual(404, self.ask(c, {"media_type": "movie"}, who=who).status_code)
        self.assertEqual([], self.seerr.calls)

    def test_form_without_a_term_makes_no_call(self):
        c = self.client()
        r = c.get("/request/watch", headers=VIEWER)
        self.assertEqual(200, r.status_code)
        self.assertIn("Ask for a film or show", r.text)
        self.assertIn("form-action 'self'", r.headers["content-security-policy"])
        self.assertEqual([], self.seerr.calls)

    # ---- who Home acts as --------------------------------------------------------------------
    def test_search_is_sent_as_the_members_own_seerr_user(self):
        c = self.client()
        r = c.get("/request/watch", params={"q": "synthetic"}, headers=VIEWER)
        self.assertEqual(200, r.status_code)
        self.assertEqual([("GET", "/api/v1/search", {"query": "synthetic", "page": "1"}, None, "5")], self.searched())
        self.assertEqual(None, [call for call in self.seerr.calls if call[1] == "/api/v1/user"][0][4])

    def test_admins_and_unmapped_members_are_never_acted_as(self):
        c = self.client()
        for who in (OWNER, UNMAPPED):
            r = c.get("/request/watch", params={"q": "synthetic"}, headers=who)
            self.assertEqual(200, r.status_code)
            self.assertIn("Requests are not set up for your account yet.", r.text)
        self.assertEqual([], self.searched())

    # ---- what the member reads ---------------------------------------------------------------
    def test_states(self):
        c = self.client()
        rows = self.rows(c.get("/request/watch", params={"q": "synthetic"}, headers=VIEWER).text)
        self.assertEqual(5, len(rows))                                   # the person is dropped
        film, show, asked, owned_elsewhere, blocked = rows
        self.assertEqual({"media_type": "movie", "media_id": "101", "title": "Synthetic Film"},
                         {k: v for k, v in self.form_of(film).items() if k != "token"})
        self.assertIn("Ask for this film", film)
        self.assertIn("Film · 1999", film)
        self.assertIn("Already in Movies and TV.", show)
        self.assertIn(f'href="/title/jellyfin/{IN_LIBRARY}"', show)
        self.assertIn("Ask for the missing seasons", show)
        self.assertIn("Already asked for.", asked)
        self.assertIsNone(self.form_of(asked))
        self.assertIn("Already in Movies and TV.", owned_elsewhere)
        self.assertNotIn("href=", owned_elsewhere.split("</span>")[0])
        self.assertIsNone(self.form_of(owned_elsewhere))
        self.assertIn("Not available to ask for.", blocked)
        self.assertNotIn("Some Actor", "".join(rows))

    # ---- asking ------------------------------------------------------------------------------
    def signed(self, c, index=0):
        return self.form_of(self.rows(c.get("/request/watch", params={"q": "synthetic"}, headers=VIEWER).text)[index])

    def test_movie_and_show_requests(self):
        c = self.client()
        r = self.ask(c, self.signed(c))
        self.assertIn("Asked for Synthetic Film. It appears in Movies and TV once it arrives.", r.text)
        self.assertEqual(("POST", "/api/v1/request", {}, {"mediaType": "movie", "mediaId": 101, "is4k": False}, "5"),
                         self.seerr.calls[-1])
        self.seerr.create_body = {"id": 10, "status": 1}
        r = self.ask(c, self.signed(c, 1))
        self.assertIn("It waits for approval first", r.text)
        self.assertEqual({"mediaType": "tv", "mediaId": 102, "is4k": False, "seasons": "all"}, self.seerr.calls[-1][3])

    def test_outcomes(self):
        for exc, words in ((UpstreamHTTPError(409), "has already been asked for"),
                           (UpstreamAuthError(403), "You may have reached your request limit"),
                           (UpstreamHTTPError(500), "Requests could not be reached right now.")):
            c = self.client()
            fields = self.signed(c)
            self.seerr.create_raises = exc
            self.assertIn(words, self.ask(c, fields).text)

    def test_token_bound_and_same_origin(self):
        c = self.client()
        fields = self.signed(c)
        for changed, who, extra in ((dict(fields, media_id="999"), VIEWER, SAME),
                                    (dict(fields, media_type="tv"), VIEWER, SAME),
                                    (fields, OWNER, SAME),
                                    (fields, VIEWER, [("Sec-Fetch-Site", "cross-site")])):
            self.assertEqual(403, self.ask(c, changed, who=who, extra=extra).status_code)
        self.assertFalse([call for call in self.seerr.calls if call[0] == "POST"])

    def test_double_tap(self):
        c = self.client()
        fields = self.signed(c)
        self.ask(c, fields)
        self.assertIn("You just asked for Synthetic Film.", self.ask(c, fields).text)
        self.assertEqual(1, len([call for call in self.seerr.calls if call[0] == "POST"]))

    def test_search_fallback_points_films_at_the_ask_page(self):
        from avrana_home.app.viewmodel import request_options
        hosts = {"requests": "request.avrana.net"}
        on = request_options(["jellyfin"], "a film", hosts, {"requests": "/request/watch"})
        off = request_options(["jellyfin"], "a film", hosts, None)
        self.assertEqual(["/request/watch?q=a%20film"], [o.href for o in on])
        self.assertTrue(off[0].href.startswith("https://request.avrana.net/search?query="))


JWT = {"HOME_IDENTITY_MODE": "jwt_required", "HOME_JWT_ISSUER": "https://auth.example.test/application/o/home/",
       "HOME_JWT_AUDIENCE": "home", "HOME_JWT_SECRET": "x" * 40}
REAL = {"HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes", "HOME_SECTIONS": "on",
        "JELLYFIN_BASE_URL": "http://jellyfin:8096", "JELLYFIN_API_KEY": "fake-key-for-test"}


class BrokerIdentityRule(unittest.TestCase):
    def test_real_mode_brokers_need_verified_identity(self):
        watch = dict(REAL, HOME_WATCH_REQUESTS="on", SEERR_BASE_URL="http://seerr:5055", SEERR_API_KEY="fake-seerr")
        books = dict(REAL, HOME_BOOK_REQUESTS="on", SHELFARR_BASE_URL="http://shelfarr:80", SHELFARR_TOKEN="fake-t")
        for env in (watch, books):
            with self.assertRaises(SettingsError):
                Settings.from_mapping(env)
            s = Settings.from_mapping(dict(env, **JWT))
            self.assertNotIn("fake-seerr", repr(s))
        with self.assertRaises(SettingsError):
            Settings.from_mapping(dict(watch, **JWT, SEERR_API_KEY=""))
        with self.assertRaises(SettingsError):
            Settings.from_mapping({"SEERR_BASE_URL": "http://127.0.0.1:5055"})


if __name__ == "__main__":
    unittest.main()
