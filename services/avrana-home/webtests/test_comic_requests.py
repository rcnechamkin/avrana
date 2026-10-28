"""Tier A/B: asking for a comic series through Home (`/request/comics`, the Omnibus fork's on-behalf key) and the
comics part of My requests. Every call names the verified member; nothing else can be posted anywhere. SYNTHETIC
data only."""
import datetime as dt
import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from avrana_home.requests.omnibus import ForbiddenCall, OmnibusRequests, Outcome, SeriesState
from avrana_home.resilience import TransportResponse, UpstreamAuthError, UpstreamHTTPError
from .support import GROUPS, USER, PeerOverride, StubAdapter, make_settings, require_framework

require_framework()

READER = [(USER, "Member-C"), (GROUPS, "avrana-users|avrana-comics")]
NOBODY = [(USER, "member-x"), (GROUPS, "avrana-users|avrana-books")]
SAME = [("Sec-Fetch-Site", "same-origin")]
FORM = [("Content-Type", "application/x-www-form-urlencoded")]
PAGE = "/request/comics"
SEARCH = {"results": [
    {"id": 41001, "name": "Synthetic Saga", "year": 2012, "publisher": "Synthetic Press", "count": 54,
     "image": "/api/library/cover?path=https%3A%2F%2Felsewhere.example%2Fc.jpg", "description": "<b>x</b>",
     "metadataSource": "COMICVINE"},
    {"id": 41002, "name": "Owned Series", "year": 2001, "publisher": "Other", "count": 12, "metadataSource": "COMICVINE"},
    {"id": 7, "name": "Metron Only", "metadataSource": "METRON"},
    {"id": "nope", "name": "Bad id"},
], "hasMore": False}
MINE = [
    {"id": "c1", "volumeId": "41001", "metadataSource": "COMICVINE", "seriesName": "Synthetic Saga #001",
     "status": "IMPORTED", "createdAt": "2026-10-20T10:00:00.000Z"},
    {"id": "c2", "volumeId": "41001", "metadataSource": "COMICVINE", "seriesName": "Synthetic Saga #002",
     "status": "DOWNLOADING", "createdAt": "2026-10-20T10:00:00.000Z"},
    {"id": "c3", "volumeId": "41003", "metadataSource": "COMICVINE", "seriesName": "Waiting Series (1999)",
     "status": "PENDING_APPROVAL", "createdAt": "2026-10-27T10:00:00.000Z"},
    {"id": "c4", "volumeId": "41004", "metadataSource": "COMICVINE", "seriesName": "Done Series #001",
     "status": "IMPORTED", "createdAt": "2026-09-01T10:00:00.000Z"},
]


class FakeOmnibus:
    def __init__(self):
        self.calls = []
        self.post_status, self.post_body, self.raises = 200, {"success": True, "message": "Queued 54 issues."}, None

    def request(self, method, path, query, timeout, max_bytes, *, json_body=None, act_as_name=None):
        self.calls.append((method, path, dict(query or {}), json.loads(json_body) if json_body else None, act_as_name))
        if self.raises is not None:
            raise self.raises
        if path == "/api/search":
            return TransportResponse(200, json.dumps(SEARCH).encode())
        if method == "GET":
            return TransportResponse(200, json.dumps(MINE).encode())
        return TransportResponse(self.post_status, json.dumps(self.post_body).encode())


def client(**kw):
    from fastapi.testclient import TestClient
    from avrana_home.app.main import create_app
    c = TestClient(PeerOverride(create_app(**kw), ("203.0.113.7", 50000)), base_url="http://portal.test",
                   follow_redirects=False, raise_server_exceptions=False)
    c.__enter__()
    return c


def forms(text):
    out = []
    for form in re.findall(r'<form method="post" action="/request/comics"[^>]*>(.*?)</form>', text, re.S):
        out.append(dict(re.findall(r'name="([a-z_]+)" value="([^"]*)"', form)))
    return out


class Comics(unittest.TestCase):
    def setUp(self):
        self.omnibus = FakeOmnibus()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        index = Path(self.dir.name) / "ids.json"
        index.write_text(json.dumps({"version": 1, "built": dt.datetime.now(dt.timezone.utc).isoformat(),
                                     "comic": {"comicvine:41002": "0ABCDEFGHJKMN"}}))
        settings = make_settings(home_sections=True, comic_requests=True, omnibus_base_url="http://127.0.0.1:3",
                                 library_ids_file=index)
        self.c = client(settings=settings, adapters=[StubAdapter({})],
                        comic_requests=OmnibusRequests(self.omnibus, timeout=1.0))
        self.addCleanup(self.c.__exit__, None, None, None)

    def post(self, fields, who=READER, extra=SAME):
        return self.c.post(PAGE, content=urlencode(fields), headers=FORM + who + extra)

    def test_search_as_the_member_with_only_comicvine_series(self):
        r = self.c.get(PAGE, params={"q": "saga"}, headers=READER)
        self.assertEqual(200, r.status_code)
        self.assertEqual(("GET", "/api/search", {"q": "saga", "page": "1"}, None, "Member-C"), self.omnibus.calls[0])
        self.assertIn("Synthetic Saga", r.text)
        self.assertIn("Synthetic Press · 2012 · 54 issues", r.text)
        self.assertNotIn("Metron Only", r.text)
        self.assertNotIn("elsewhere.example", r.text)
        self.assertNotIn("<b>x</b>", r.text)
        self.assertIn("https://read.avrana.net/series/0ABCDEFGHJKMN", r.text)     # exact id hit: Komga's series
        self.assertIn("Ask for missing issues", r.text)

    def test_ask_sends_one_volume_request_as_the_member(self):
        fields = forms(self.c.get(PAGE, params={"q": "saga"}, headers=READER).text)[0]
        r = self.post(fields)
        self.assertEqual(303, r.status_code)
        self.assertEqual(PAGE, r.headers["location"])
        method, path, _q, body, who = self.omnibus.calls[-1]
        self.assertEqual(("POST", "/api/request", "Member-C"), (method, path, who))
        self.assertEqual({"type": "volume", "cvId": 41001, "name": "Synthetic Saga", "metadataSource": "COMICVINE",
                          "year": "2012", "publisher": "Synthetic Press"}, body)
        page = self.c.get(PAGE, headers=READER)
        self.assertIn("Asked for Synthetic Saga.", page.text)
        self.assertIn("Asked for just now.", page.text)

    def test_awaiting_approval_and_refusals_in_fixed_words(self):
        fields = forms(self.c.get(PAGE, params={"q": "saga"}, headers=READER).text)[0]
        self.omnibus.post_body = {"success": True, "message": "Sent for Admin approval."}
        self.post(fields)
        self.assertIn("waits for approval first", self.c.get(PAGE, headers=READER).text)
        self.omnibus.raises = UpstreamAuthError(403)
        self.post(dict(fields))
        text = self.c.get(PAGE, headers=READER).text
        self.assertIn("You just asked", text)                     # the guard: a second tap within a minute

    def test_forged_cross_site_and_other_members_refused(self):
        fields = forms(self.c.get(PAGE, params={"q": "saga"}, headers=READER).text)[0]
        self.assertEqual(403, self.post(dict(fields, cv_id="99")).status_code)
        self.assertEqual(403, self.post(fields, extra=[("Sec-Fetch-Site", "cross-site")]).status_code)
        self.assertEqual(403, self.post(fields, who=[(USER, "member-z"), READER[1]]).status_code)
        self.assertNotIn("POST", [c[0] for c in self.omnibus.calls])

    def test_who_may_open_it(self):
        self.assertEqual(404, self.c.get(PAGE, headers=NOBODY).status_code)
        self.assertEqual(404, self.c.get(PAGE).status_code)
        self.assertEqual(200, self.c.head(PAGE, params={"q": "saga"}, headers=READER).status_code)
        self.assertEqual([], self.omnibus.calls)

    def test_not_linked_member(self):
        self.omnibus.raises = UpstreamAuthError(401)
        r = self.c.get(PAGE, params={"q": "saga"}, headers=READER)
        self.assertIn("Comic requests are not set up for your account yet", r.text)

    def test_my_requests_groups_issues_by_series(self):
        r = self.c.get("/request/mine", headers=READER)
        self.assertEqual(200, r.status_code)
        coming, done = r.text.split('id="h-done"')
        self.assertIn("Synthetic Saga", coming)
        self.assertIn("1 of 2 issues arrived.", coming)
        self.assertIn("Waiting Series", coming)
        self.assertNotIn("(1999)", coming)
        self.assertIn("Waiting for approval", coming)
        self.assertIn("Done Series", done)
        self.assertNotIn("Cancel request", r.text)                # the fork's key cannot cancel
        self.assertIn('href="/request/comics"', r.text)

    def test_request_menu_opens_the_comics_page(self):
        r = self.c.get("/request", headers=READER)
        if r.status_code == 200 and "requestacomic" in r.text:
            self.assertIn('href="/request/comics"', r.text)


class Units(unittest.TestCase):
    def test_every_call_names_a_member(self):
        c = OmnibusRequests(FakeOmnibus())
        with self.assertRaises(ForbiddenCall):
            c._exchange("GET", "/api/search", {"q": "x"}, None, "")
        with self.assertRaises(ForbiddenCall):
            c._exchange("DELETE", "/api/request", None, None, "member")
        with self.assertRaises(ForbiddenCall):
            c._exchange("GET", "/api/library", None, None, "member")
        self.assertEqual(("not_linked", ()), c.search("bad name!", "saga"))

    def test_create_outcomes(self):
        fake = FakeOmnibus()
        c = OmnibusRequests(fake)
        self.assertIs(Outcome.CREATED, c.create("m", 1, "S", 2000, "P"))
        fake.post_body = {"success": False}
        self.assertIs(Outcome.UNAVAILABLE, c.create("m", 1, "S", 2000, "P"))
        fake.raises = UpstreamHTTPError(400)
        self.assertIs(Outcome.REFUSED, c.create("m", 1, "S", 2000, "P"))
        self.assertIs(Outcome.REFUSED, c.create("m", "x", "S", 2000, "P"))

    def test_series_grouping(self):
        state, rows = OmnibusRequests(FakeOmnibus()).mine("m")
        self.assertEqual("ok", state)
        by = {r.volume_id: r for r in rows}
        self.assertEqual((SeriesState.COMING, 1, 2), (by["41001"].state, by["41001"].arrived, by["41001"].total))
        self.assertIs(SeriesState.AWAITING, by["41003"].state)
        self.assertIs(SeriesState.ARRIVED, by["41004"].state)
        self.assertEqual("41003", rows[0].volume_id)              # newest first


if __name__ == "__main__":
    unittest.main()
