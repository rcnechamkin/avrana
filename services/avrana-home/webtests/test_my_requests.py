"""Tier A/B: My requests (`/request/mine`): the member's own requests from Shelfarr and Seerr, and taking one back.
Only the member's own rows are ever shown, whatever the upstream returns; a cancel is checked upstream as the member
before anything is deleted. SYNTHETIC data only."""
import json
import re
import unittest
from urllib.parse import urlencode

from avrana_home.requests.seerr import ForbiddenCall as SeerrForbidden, RequestState, SeerrRequests
from avrana_home.requests.shelfarr import CancelOutcome, ForbiddenCall, ShelfarrRequests
from avrana_home.resilience import FakeClock, TransportResponse, UpstreamHTTPError, UpstreamNotFound
from .support import GROUPS, USER, PeerOverride, StubAdapter, make_settings, require_framework
from .test_web_watch_requests import IN_LIBRARY, USERS, VIEWER, JellyfinStub

require_framework()

BOTH = [(USER, "Member-A"), (GROUPS, "avrana-users|avrana-books|avrana-audiobooks")]
EBOOKS = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-books")]
NOBODY = [(USER, "member-x"), (GROUPS, "avrana-users")]
SAME = [("Sec-Fetch-Site", "same-origin")]
FORM = [("Content-Type", "application/x-www-form-urlencoded")]
PAGE = "/request/mine"


def book_row(rid, status, username="member-a", book_type="ebook", title=None, created="2026-10-20T10:00:00Z",
             attention=False):
    return {"id": rid, "status": status, "attention_needed": attention, "created_at": created,
            "book": {"title": title or f"Synthetic Book {rid}", "author": "S. Author", "book_type": book_type},
            "user": {"id": 3, "username": username}}


LIST = {"requests": [
    book_row(1, "searching", created="2026-10-27T10:00:00Z"),
    book_row(2, "downloading", book_type="audiobook"),
    book_row(3, "completed", title="Arrived Book", created="2026-09-01T10:00:00Z"),
    book_row(4, "pending", username="someone-else", title="Not Yours"),     # upstream token ignored `username`
    book_row(5, "failed", created="2025-12-01T10:00:00Z"),
    book_row(6, "not_found", attention=True),
    {"id": 7, "status": "weird", "book": {"title": "x", "book_type": "ebook"}, "user": {"username": "member-a"}},
]}


class FakeShelfarr:
    def __init__(self):
        self.calls = []
        self.show = {}
        self.delete_raises = None

    def request(self, method, path, query, timeout, max_bytes, *, json_body=None):
        self.calls.append((method, path, dict(query or {})))
        if path == "/api/v1/requests":
            return TransportResponse(200, json.dumps(LIST).encode())
        rid = int(path.rsplit("/", 1)[1])
        if method == "GET":
            if rid not in self.show:
                raise UpstreamNotFound(404)
            return TransportResponse(200, json.dumps(self.show[rid]).encode())
        if self.delete_raises is not None:
            raise self.delete_raises
        return TransportResponse(200, json.dumps(self.show[rid]).encode())


def watch_row(rid, status, media_status, tmdb, mtype="movie", by=5, jf=None, created="2026-10-25T10:00:00.000Z"):
    return {"id": rid, "status": status, "type": mtype, "createdAt": created, "requestedBy": {"id": by},
            "media": {"mediaType": mtype, "tmdbId": tmdb, "status": media_status, "jellyfinMediaId": jf}}


WATCH = {"pageInfo": {}, "results": [
    watch_row(11, 1, 2, 201, created="2026-10-28T08:00:00.000Z"),
    watch_row(12, 2, 5, 202, mtype="tv", jf=IN_LIBRARY),
    watch_row(13, 3, 1, 203),
    watch_row(14, 1, 2, 204, by=9),                                         # someone else's pending request
]}
TITLES = {201: "Waiting Film", 202: "Synthetic Show", 203: "Declined Film", 204: "Not Yours Either"}


class FakeSeerr:
    def __init__(self):
        self.calls = []

    def request(self, method, path, query, timeout, max_bytes, *, json_body=None, act_as=None):
        self.calls.append((method, path, dict(query or {}), act_as))
        if path == "/api/v1/user":
            return TransportResponse(200, json.dumps(USERS).encode())
        if path == "/api/v1/request":
            return TransportResponse(200, json.dumps(WATCH).encode())
        if method == "DELETE":
            return TransportResponse(204, b"")
        kind, tmdb = path.split("/")[3], int(path.rsplit("/", 1)[1])
        key = "title" if kind == "movie" else "name"
        return TransportResponse(200, json.dumps({key: TITLES[tmdb], "releaseDate": "2001-01-01"}).encode())


def client(**kw):
    from fastapi.testclient import TestClient
    from avrana_home.app.main import create_app
    c = TestClient(PeerOverride(create_app(**kw), ("203.0.113.7", 50000)), base_url="http://portal.test",
                   follow_redirects=False, raise_server_exceptions=False)
    c.__enter__()
    return c


def cancel_forms(text):
    out = []
    for form in re.findall(r'<form method="post" action="/request/mine"[^>]*>(.*?)</form>', text, re.S):
        out.append(dict(re.findall(r'name="([a-z_]+)" value="([^"]*)"', form)))
    return out


class Books(unittest.TestCase):
    def setUp(self):
        self.shelfarr = FakeShelfarr()
        settings = make_settings(home_sections=True, book_requests=True, shelfarr_base_url="http://127.0.0.1:1")
        self.c = client(settings=settings, adapters=[StubAdapter({})],
                        book_requests=ShelfarrRequests(self.shelfarr, timeout=1.0))
        self.addCleanup(self.c.__exit__, None, None, None)

    def post(self, fields, extra=SAME, who=BOTH):
        return self.c.post(PAGE, content=urlencode(fields), headers=FORM + who + extra)

    def test_lists_only_the_members_own_requests_in_two_groups(self):
        r = self.c.get(PAGE, headers=BOTH)
        self.assertEqual(200, r.status_code)
        self.assertEqual(("GET", "/api/v1/requests", {"username": "member-a", "limit": "100"}), self.shelfarr.calls[0])
        self.assertNotIn("Not Yours", r.text)
        self.assertNotIn("weird", r.text)
        coming, done = r.text.split('id="h-done"')
        for words in ("Synthetic Book 1", "Looking for it", "Synthetic Book 2", "On its way", "Not found yet",
                      "The owner has been told."):
            self.assertIn(words, coming)
        self.assertIn("Arrived Book", done)
        self.assertIn('href="/search?q=Arrived+Book"', done)       # Home's own search, never Shelfarr
        self.assertIn("Stopped", done)
        self.assertIn("asked 1 Dec 2025", done)
        self.assertLess(coming.index("Synthetic Book 1"), coming.index("Synthetic Book 2"))   # newest first
        self.assertNotIn("127.0.0.1", r.text)

    def test_cancel_offered_only_before_anything_is_fetched(self):
        ids = {f["request_id"] for f in cancel_forms(self.c.get(PAGE, headers=BOTH).text)}
        self.assertEqual({"1", "6"}, ids)                         # searching, not_found: not downloading or done

    def test_a_library_the_member_does_not_hold_is_never_shown(self):
        r = self.c.get(PAGE, headers=EBOOKS)
        self.assertNotIn("Synthetic Book 2", r.text)              # the audiobook
        self.assertIn("Synthetic Book 1", r.text)

    def test_cancel_reads_first_then_deletes_and_redirects(self):
        self.shelfarr.show[1] = book_row(1, "searching")
        fields = next(f for f in cancel_forms(self.c.get(PAGE, headers=BOTH).text) if f["request_id"] == "1")
        r = self.post(fields)
        self.assertEqual(303, r.status_code)
        self.assertEqual(PAGE, r.headers["location"])
        self.assertEqual([("GET", "/api/v1/requests/1", {"username": "member-a"}),
                          ("DELETE", "/api/v1/requests/1", {"username": "member-a"})], self.shelfarr.calls[-2:])
        page = self.c.get(PAGE, headers=BOTH)
        self.assertIn("Cancelled your request for Synthetic Book 1.", page.text)
        self.assertNotIn("Cancelled your request", self.c.get(PAGE, headers=BOTH).text)   # once only

    def test_cancel_of_a_request_that_is_not_the_members_sends_no_delete(self):
        self.shelfarr.show[1] = book_row(1, "searching", username="someone-else")
        fields = next(f for f in cancel_forms(self.c.get(PAGE, headers=BOTH).text) if f["request_id"] == "1")
        self.post(fields)
        self.assertNotIn("DELETE", [c[0] for c in self.shelfarr.calls])
        self.assertIn("can no longer be cancelled", self.c.get(PAGE, headers=BOTH).text)

    def test_cancel_once_it_is_on_its_way_sends_no_delete(self):
        self.shelfarr.show[1] = book_row(1, "downloading")
        fields = next(f for f in cancel_forms(self.c.get(PAGE, headers=BOTH).text) if f["request_id"] == "1")
        self.post(fields)
        self.assertNotIn("DELETE", [c[0] for c in self.shelfarr.calls])

    def test_forged_or_cross_site_forms_are_refused(self):
        fields = cancel_forms(self.c.get(PAGE, headers=BOTH).text)[0]
        self.assertEqual(403, self.post(dict(fields, request_id="4")).status_code)          # not what was signed
        self.assertEqual(403, self.post(fields, extra=[("Sec-Fetch-Site", "cross-site")]).status_code)
        self.assertEqual(403, self.post(fields, who=[(USER, "member-z"), BOTH[1]]).status_code)   # another member
        self.assertNotIn("DELETE", [c[0] for c in self.shelfarr.calls])

    def test_who_may_open_it(self):
        self.assertEqual(404, self.c.get(PAGE, headers=NOBODY).status_code)
        self.assertEqual(404, self.c.get(PAGE).status_code)
        before = len(self.shelfarr.calls)
        self.assertEqual(200, self.c.head(PAGE, headers=BOTH).status_code)
        self.assertEqual(before, len(self.shelfarr.calls))                                  # HEAD reads nothing

    def test_off_means_404_and_501(self):
        settings = make_settings(home_sections=True)
        c = client(settings=settings, adapters=[StubAdapter({})])
        self.addCleanup(c.__exit__, None, None, None)
        self.assertEqual(404, c.get(PAGE, headers=BOTH).status_code)
        self.assertEqual(501, c.post(PAGE, content="a=1", headers=FORM + BOTH + SAME).status_code)

    def test_ask_pages_link_here(self):
        self.assertIn('href="/request/mine"', self.c.get("/request/books", headers=BOTH).text)


class Watch(unittest.TestCase):
    def setUp(self):
        self.seerr, self.jf = FakeSeerr(), JellyfinStub()
        settings = make_settings(home_sections=True, watch_requests=True, seerr_base_url="http://127.0.0.1:2")
        self.c = client(settings=settings, adapters=[self.jf], watch_requests=SeerrRequests(self.seerr, timeout=1.0))
        self.addCleanup(self.c.__exit__, None, None, None)

    def test_lists_the_members_own_requests_as_the_member(self):
        r = self.c.get(PAGE, headers=VIEWER)
        self.assertEqual(200, r.status_code)
        listed = next(c for c in self.seerr.calls if c[1] == "/api/v1/request")
        self.assertEqual(5, int(listed[3]))
        self.assertEqual("5", listed[2]["requestedBy"])
        self.assertNotIn("Not Yours Either", r.text)
        self.assertNotIn("/api/v1/movie/204", [c[1] for c in self.seerr.calls])     # never even looked up
        self.assertIn("Waiting for approval", r.text)
        self.assertIn("Declined", r.text)
        self.assertIn('href="/title/jellyfin/' + IN_LIBRARY + '"', r.text)        # permission-checked title page
        self.assertEqual({"11"}, {f["request_id"] for f in cancel_forms(r.text)})

    def test_titles_are_cached(self):
        self.c.get(PAGE, headers=VIEWER)
        before = sum(1 for c in self.seerr.calls if c[1].startswith(("/api/v1/movie/", "/api/v1/tv/")))
        self.c.get(PAGE, headers=VIEWER)
        after = sum(1 for c in self.seerr.calls if c[1].startswith(("/api/v1/movie/", "/api/v1/tv/")))
        self.assertEqual(before, after)

    def test_cancel_only_the_members_own_pending_request(self):
        fields = cancel_forms(self.c.get(PAGE, headers=VIEWER).text)[0]
        r = self.c.post(PAGE, content=urlencode(fields), headers=FORM + VIEWER + SAME)
        self.assertEqual(303, r.status_code)
        deletes = [c for c in self.seerr.calls if c[0] == "DELETE"]
        self.assertEqual([("DELETE", "/api/v1/request/11", {}, "5")], deletes)
        self.assertIn("Cancelled your request for Waiting Film.", self.c.get(PAGE, headers=VIEWER).text)

    def test_not_linked_member_is_told_and_nothing_is_read(self):
        r = self.c.get(PAGE, headers=[(USER, "member-n"), (GROUPS, "avrana-users|avrana-videos")])
        self.assertIn("not set up for your account yet", r.text)
        self.assertFalse(any(c[1] == "/api/v1/request" for c in self.seerr.calls))


    def test_jellyfin_down_is_never_told_as_not_set_up(self):
        from avrana_home.resilience import UpstreamTimeout

        def down(principal):
            raise UpstreamTimeout()
        self.jf._resolve_user = down
        for path in (PAGE, "/request/watch?q=film"):
            r = self.c.get(path, headers=VIEWER)
            self.assertNotIn("not set up", r.text, path)
            self.assertIn("could not be reached", r.text, path)


class Units(unittest.TestCase):
    def test_shelfarr_single_request_calls_must_name_a_member(self):
        client = ShelfarrRequests(FakeShelfarr())
        with self.assertRaises(ForbiddenCall):
            client._send("GET", "/api/v1/requests/1", None, None)
        with self.assertRaises(ForbiddenCall):
            client._send("POST", "/api/v1/requests/1/retry", {"username": "a"}, None)
        self.assertIs(CancelOutcome.NOT_ALLOWED, client.cancel("Not A Name!", 1))

    def test_shelfarr_gone_request_is_not_allowed(self):
        self.assertIs(CancelOutcome.NOT_ALLOWED, ShelfarrRequests(FakeShelfarr()).cancel("member-a", 99))

    def test_shelfarr_upstream_refusal_on_delete(self):
        fake = FakeShelfarr()
        fake.show[1] = book_row(1, "pending")
        fake.delete_raises = UpstreamHTTPError(422)
        self.assertIs(CancelOutcome.NOT_ALLOWED, ShelfarrRequests(fake).cancel("member-a", 1))

    def test_seerr_never_lists_or_deletes_as_user_one(self):
        c = SeerrRequests(FakeSeerr())
        self.assertEqual(("unavailable", ()), c.mine(1))
        with self.assertRaises(SeerrForbidden):
            c._send("DELETE", "/api/v1/request/3", None, None, None)
        with self.assertRaises(SeerrForbidden):
            c._send("POST", "/api/v1/request/3/approve", None, None, 5)

    def test_recent_arrivals_are_marked_new_and_lead_done(self):
        import datetime as dt
        from avrana_home.app import myrequests as mine
        from avrana_home.requests.forms import FormSigner
        from avrana_home.requests.shelfarr import BookRequest, RequestState as BS
        today = dt.date(2026, 10, 28)
        old = BookRequest(1, "Old", "", "ebook", BS.ARRIVED, "2026-01-01", False, False, "2026-01-05")
        fresh = BookRequest(2, "Fresh", "", "ebook", BS.ARRIVED, "2025-12-01", False, False, "2026-10-27")
        coming = BookRequest(3, "Coming", "", "ebook", BS.COMING, "2026-10-28", False, False, "2026-10-28")
        rows = mine.book_rows((old, fresh, coming), "m", FormSigner(), today)
        self.assertEqual([False, True, False], [r.new for r in rows])          # only an ARRIVAL is news
        page = mine.build_page(("ok", rows))
        self.assertEqual(["Fresh", "Old"], [r.title for r in page.done])
        self.assertEqual("1 new, 1 on the way", page.outcome)

    def test_seerr_title_budget(self):
        clock = FakeClock()

        class Slow(FakeSeerr):
            def request(self, method, path, query, timeout, max_bytes, **kw):
                if path.startswith("/api/v1/movie/") or path.startswith("/api/v1/tv/"):
                    clock.advance(2.0)
                return super().request(method, path, query, timeout, max_bytes, **kw)
        state, rows = SeerrRequests(Slow(), clock=clock).mine(5)
        self.assertEqual("ok", state)
        self.assertEqual(3, len(rows))
        self.assertEqual("", rows[-1].title)                       # past the budget: named on a later view
        self.assertIs(RequestState.DECLINED, rows[-1].state)


if __name__ == "__main__":
    unittest.main()
