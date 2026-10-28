"""Tier B: the season picker on /request/watch (`?show=<id>`): each season of a show with what Seerr knows of it, and a
request for just the seasons the member chose, sent as the member. SYNTHETIC data only."""
import json
import re
import unittest
from urllib.parse import urlencode

from avrana_home.requests.seerr import SeerrRequests
from avrana_home.resilience import TransportResponse
from .support import PeerOverride, make_settings, require_framework
from .test_web_watch_requests import SEARCH, USERS, VIEWER, JellyfinStub

require_framework()
SAME = [("Sec-Fetch-Site", "same-origin")]
FORM = [("Content-Type", "application/x-www-form-urlencoded")]
SHOW = {"id": 102, "name": "Synthetic Show", "firstAirDate": "2019-01-01",
        "seasons": [{"seasonNumber": 0, "episodeCount": 3}, {"seasonNumber": 1, "episodeCount": 8},
                    {"seasonNumber": 2, "episodeCount": 10}, {"seasonNumber": 3, "episodeCount": 1}],
        "mediaInfo": {"status": 4, "seasons": [{"seasonNumber": 1, "status": 5}, {"seasonNumber": 2, "status": 3}]}}


class FakeSeerr:
    def __init__(self):
        self.calls = []

    def request(self, method, path, query, timeout, max_bytes, *, json_body=None, act_as=None):
        self.calls.append((method, path, dict(query or {}), json.loads(json_body) if json_body else None, act_as))
        if path == "/api/v1/user":
            return TransportResponse(200, json.dumps(USERS).encode())
        if path == "/api/v1/tv/102":
            return TransportResponse(200, json.dumps(SHOW).encode())
        if method == "GET":
            return TransportResponse(200, json.dumps(SEARCH).encode())
        return TransportResponse(201, json.dumps({"id": 9, "status": 2}).encode())


class SeasonPicker(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from avrana_home.app.main import create_app
        self.seerr = FakeSeerr()
        settings = make_settings(home_sections=True, watch_requests=True, seerr_base_url="http://127.0.0.1:1")
        app = create_app(settings, adapters=[JellyfinStub()], watch_requests=SeerrRequests(self.seerr))
        self.c = TestClient(PeerOverride(app, ("203.0.113.7", 50000)), base_url="http://portal.test",
                            follow_redirects=False, raise_server_exceptions=False)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def picker(self):
        r = self.c.get("/request/watch", params={"show": "102", "q": "show"}, headers=VIEWER)
        self.assertEqual(200, r.status_code)
        form = re.search(r'<form method="post" action="/request/watch" class="seasons">(.*?)</form>', r.text, re.S)
        return r, dict(re.findall(r'type="hidden" name="([a-z_]+)" value="([^"]*)"', form.group(1)))

    def test_search_offers_the_picker_for_shows(self):
        r = self.c.get("/request/watch", params={"q": "show"}, headers=VIEWER)
        self.assertIn('href="/request/watch?show=102&amp;q=show"', r.text)

    def test_seasons_say_what_is_there_and_only_open_ones_can_be_chosen(self):
        r, _hidden = self.picker()
        self.assertIn("Season 1 · 8 episodes", r.text)
        self.assertIn("In Movies and TV", r.text)
        self.assertIn("Already asked for", r.text)
        self.assertNotIn("Season 0", r.text)                       # specials are left out
        self.assertEqual(["season_3"], re.findall(r'type="checkbox" id="(season_\d+)"', r.text))
        self.assertIn(("GET", "/api/v1/tv/102", {}, None, "5"), self.seerr.calls)

    def test_asks_for_the_chosen_seasons_as_the_member(self):
        _r, hidden = self.picker()
        r = self.c.post("/request/watch", content=urlencode(dict(hidden, season_3="1")), headers=FORM + VIEWER + SAME)
        self.assertEqual(303, r.status_code)
        posted = [c for c in self.seerr.calls if c[0] == "POST"]
        self.assertEqual({"mediaType": "tv", "mediaId": 102, "is4k": False, "seasons": [3]}, posted[0][3])
        self.assertEqual("5", posted[0][4])

    def test_nothing_chosen_sends_nothing(self):
        _r, hidden = self.picker()
        self.c.post("/request/watch", content=urlencode(hidden), headers=FORM + VIEWER + SAME)
        self.assertFalse([c for c in self.seerr.calls if c[0] == "POST"])
        self.assertIn("Choose at least one season", self.c.get("/request/watch", headers=VIEWER).text)

    def test_the_signed_fields_still_bind_the_show(self):
        _r, hidden = self.picker()
        r = self.c.post("/request/watch", content=urlencode(dict(hidden, media_id="999", season_1="1")),
                        headers=FORM + VIEWER + SAME)
        self.assertEqual(403, r.status_code)
        bad = self.c.post("/request/watch", content=urlencode(dict(hidden, season_61="1")),
                          headers=FORM + VIEWER + SAME)
        self.assertEqual(403, bad.status_code)                      # not a field the form can carry
        self.assertFalse([c for c in self.seerr.calls if c[0] == "POST"])

    def test_bad_show_id_shows_the_search(self):
        r = self.c.get("/request/watch", params={"show": "abc"}, headers=VIEWER)
        self.assertNotIn("Choose seasons</h2>", r.text)


if __name__ == "__main__":
    unittest.main()
