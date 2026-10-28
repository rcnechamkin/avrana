"""Tier B: asking for a book or an audiobook through Home (`/request/books`, the Shelfarr request broker) through the
HTTP layer, against an in-memory Shelfarr transport (SYNTHETIC data). Who asks is the verified principal only; the
form must be one this process signed for that member; nothing else can be posted anywhere."""
import json
import re
import unittest
from urllib.parse import urlencode

from avrana_home.requests.shelfarr import ShelfarrRequests
from avrana_home.resilience import TransportResponse, UpstreamAuthError, UpstreamHTTPError, UpstreamNotFound
from .support import GROUPS, USER, PeerOverride, StubAdapter, make_settings, require_framework

require_framework()

BOTH = [(USER, "Member-A"), (GROUPS, "avrana-users|avrana-books|avrana-audiobooks")]
EBOOKS = [(USER, "member-e"), (GROUPS, "avrana-users|avrana-books")]
LISTENER = [(USER, "member-l"), (GROUPS, "avrana-users|avrana-audiobooks")]
VIDEOS = [(USER, "member-v"), (GROUPS, "avrana-users|avrana-videos")]
SAME = [("Sec-Fetch-Site", "same-origin")]
RESULTS = {"results": [
    {"work_id": "hardcover:123", "title": "Synthetic Dune", "author": "Synthetic Author", "year": 1965,
     "series_name": "Synthetic Chronicles", "has_ebook": True, "has_audiobook": True,
     "cover_url": "https://elsewhere.example/c.jpg"},
    {"work_id": "openlibrary:OL1W", "title": "Spoken Only", "author": "A. Voice", "has_ebook": False,
     "has_audiobook": True},
    {"work_id": "BAD id", "title": "Dropped"},
]}


class FakeShelfarr:
    """Answers the two allow-listed calls. `create_raises` / `create_status` shape the POST answer."""

    def __init__(self):
        self.calls = []
        self.create_raises = None
        self.create_status = 201
        self.search_body = RESULTS

    def request(self, method, path, query, timeout, max_bytes, *, json_body=None):
        self.calls.append((method, path, dict(query or {}), json.loads(json_body) if json_body else None))
        if method == "GET":
            return TransportResponse(200, json.dumps(self.search_body).encode())
        if self.create_raises is not None:
            raise self.create_raises
        return TransportResponse(self.create_status, b'{"id": 7}')


class BookRequestsWeb(unittest.TestCase):
    def client(self, on=True):
        from fastapi.testclient import TestClient
        from avrana_home.app.main import create_app
        self.shelfarr = FakeShelfarr()
        broker = ShelfarrRequests(self.shelfarr, timeout=1.0)
        settings = make_settings(home_sections=True, book_requests=on, shelfarr_base_url="http://127.0.0.1:1")
        app = create_app(settings, adapters=[StubAdapter({})], book_requests=broker)
        c = TestClient(PeerOverride(app, ("203.0.113.7", 50000)), base_url="http://portal.test",
                       follow_redirects=False, raise_server_exceptions=False)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def forms(self, page_text):
        """The (fields, button label) of each POST form on the page."""
        out = []
        for form in re.findall(r'<form method="post" action="/request/books"[^>]*>(.*?)</form>', page_text, re.S):
            fields = dict(re.findall(r'name="([a-z_]+)" value="([^"]*)"', form))
            out.append((fields, re.search(r"<button[^>]*>(.*?)<", form).group(1)))
        return out

    def ask(self, c, fields, who=BOTH, extra=SAME):
        return c.post("/request/books", content=urlencode(fields),
                      headers=[("Content-Type", "application/x-www-form-urlencoded")] + who + extra)

    # ---- gating ------------------------------------------------------------------------------
    def test_off_is_the_standard_404_and_post_is_501(self):
        c = self.client(on=False)
        self.assertEqual(404, c.get("/request/books", headers=BOTH).status_code)
        self.assertEqual(501, c.post("/request/books", content=b"a=b", headers=BOTH).status_code)
        self.assertEqual([], self.shelfarr.calls)

    def test_member_without_a_book_library_gets_404_with_no_upstream_call(self):
        c = self.client()
        for who in (VIDEOS, [], [(USER, "x")]):
            self.assertEqual(404, c.get("/request/books", params={"q": "dune"}, headers=who).status_code)
            self.assertEqual(404, self.ask(c, {"work_id": "hardcover:123"}, who=who).status_code)
        self.assertEqual([], self.shelfarr.calls)

    def test_other_posts_stay_501(self):
        c = self.client()
        for path in ("/", "/search", "/request/books/", "/request/books2"):
            self.assertEqual(501, c.post(path, content=b"a=b", headers=BOTH + SAME).status_code, path)

    # ---- search ------------------------------------------------------------------------------
    def test_form_without_a_term_makes_no_upstream_call(self):
        c = self.client()
        r = c.get("/request/books", headers=BOTH)
        self.assertEqual(200, r.status_code)
        self.assertIn("Ask for a book", r.text)
        self.assertIn("form-action 'self'", r.headers["content-security-policy"])
        self.assertEqual([], self.shelfarr.calls)

    def test_search_offers_only_the_members_formats_and_drops_upstream_urls(self):
        c = self.client()
        r = c.get("/request/books", params={"q": "dune"}, headers=EBOOKS)
        self.assertEqual(200, r.status_code)
        self.assertEqual([("GET", "/api/v1/search", {"q": "dune", "limit": "10", "content_kind": "book"}, None)],
                         self.shelfarr.calls)
        forms = self.forms(r.text)
        self.assertEqual(["Ask for the ebook"], [label for _f, label in forms])
        self.assertEqual("hardcover:123", forms[0][0]["work_id"])
        self.assertIn("Only as an audiobook, which is not one of your libraries.", r.text)
        self.assertNotIn("elsewhere.example", r.text)
        self.assertNotIn("Dropped", r.text)

    def test_both_formats_for_a_member_with_both_libraries(self):
        c = self.client()
        r = c.get("/request/books", params={"q": "dune"}, headers=BOTH)
        labels = [label for _f, label in self.forms(r.text)]
        self.assertEqual(["Ask for the ebook", "Ask for the audiobook", "Ask for the audiobook"], labels)

    def test_unavailable_upstream_is_said_plainly(self):
        c = self.client()
        self.shelfarr.search_body = {"oops": True}
        r = c.get("/request/books", params={"q": "dune"}, headers=BOTH)
        self.assertEqual(200, r.status_code)
        self.assertIn("Requests could not be reached right now.", r.text)

    # ---- asking ------------------------------------------------------------------------------
    def signed(self, c, who=BOTH, index=0):
        r = c.get("/request/books", params={"q": "dune"}, headers=who)
        return self.forms(r.text)[index][0]

    def test_ask_names_the_principal_lowercased_never_a_form_field(self):
        c = self.client()
        fields = self.signed(c)
        r = self.ask(c, fields)
        self.assertEqual(200, r.status_code)
        self.assertIn("Asked for the ebook of Synthetic Dune. It appears in Books once it arrives.", r.text)
        post = self.shelfarr.calls[-1]
        self.assertEqual(("POST", "/api/v1/requests"), post[:2])
        self.assertEqual({"work_id": "hardcover:123", "book_type": "ebook", "title": "Synthetic Dune",
                          "author": "Synthetic Author", "username": "member-a"}, post[3])

    def test_token_is_bound_to_the_member_and_the_fields(self):
        c = self.client()
        fields = self.signed(c)
        for who, changed in ((EBOOKS, fields), (BOTH, dict(fields, title="Other")),
                             (BOTH, dict(fields, book_type="audiobook")), (BOTH, dict(fields, token="1.ab"))):
            r = self.ask(c, changed, who=who)
            self.assertEqual(403, r.status_code)
            self.assertIn("This page has expired.", r.text)
        self.assertEqual(1, len(self.shelfarr.calls))          # the search only

    def test_format_outside_the_members_libraries_is_refused_even_when_signed(self):
        c = self.client()
        fields = self.signed(c, who=BOTH, index=1)              # audiobook, signed for BOTH
        self.assertEqual("audiobook", fields["book_type"])
        r = self.ask(c, fields, who=[(USER, "Member-A"), (GROUPS, "avrana-users|avrana-books")])
        self.assertEqual(403, r.status_code)

    def test_cross_site_and_signal_less_posts_are_refused(self):
        c = self.client()
        fields = self.signed(c)
        for extra in ([("Sec-Fetch-Site", "cross-site")], [("Sec-Fetch-Site", "same-site")], [],
                      [("Origin", "https://evil.example")], [("Origin", "null")]):
            self.assertEqual(403, self.ask(c, fields, extra=extra).status_code, extra)
        self.assertEqual(200, self.ask(c, fields, extra=[("Origin", "http://portal.test")]).status_code)

    def test_malformed_bodies_are_refused(self):
        c = self.client()
        fields = self.signed(c)
        base = [("Content-Type", "application/x-www-form-urlencoded")] + BOTH + SAME
        bad = (urlencode(dict(fields, username="someone-else")), urlencode({k: v for k, v in fields.items()
                                                                            if k != "author"}),
               urlencode(fields) + "&title=again", "%%%")
        for body in bad:
            self.assertEqual(403, c.post("/request/books", content=body, headers=base).status_code, body)
        r = c.post("/request/books", content=urlencode(fields), headers=[("Content-Type", "text/plain")] + BOTH + SAME)
        self.assertEqual(403, r.status_code)

    def test_length_rules(self):
        c = self.client()
        self.assertEqual(413, c.post("/request/books", content=b"a" * 5000, headers=BOTH + SAME).status_code)
        r = c.post("/request/books", content=iter([b"a=b"]), headers=BOTH + SAME)   # chunked: no length
        self.assertEqual(411, r.status_code)

    def test_double_tap_and_rate(self):
        c = self.client()
        fields = self.signed(c)
        self.assertEqual(200, self.ask(c, fields).status_code)
        again = self.ask(c, fields)
        self.assertEqual(200, again.status_code)
        self.assertIn("You just asked for the ebook of Synthetic Dune.", again.text)
        self.assertEqual(1, sum(1 for call in self.shelfarr.calls if call[0] == "POST"))

    def test_outcomes(self):
        cases = ((UpstreamNotFound(404), 200, "Requests are not set up for your account yet."),
                 (UpstreamHTTPError(422), 200, "could not be asked for"),
                 (UpstreamAuthError(403), 200, "Requests could not be reached right now."))
        for exc, status, words in cases:
            c = self.client()
            fields = self.signed(c)
            self.shelfarr.create_raises = exc
            r = self.ask(c, fields)
            self.assertEqual(status, r.status_code)
            self.assertIn(words, r.text)
            self.assertNotIn("http 4", r.text)

    def test_not_linked_links_to_the_members_own_request_place(self):
        c = self.client()
        fields = self.signed(c)
        self.shelfarr.create_raises = UpstreamNotFound(404)
        self.assertIn('href="/requestabook"', self.ask(c, fields).text)

    # ---- search fallback --------------------------------------------------------------------
    def test_search_fallback_points_books_at_the_ask_page(self):
        from avrana_home.app.viewmodel import request_options
        hosts = {"requestabook": "requestabook.avrana.net", "requests": "request.avrana.net"}
        on = request_options(["calibre-web", "jellyfin"], "dune book", hosts, {"requestabook": "/request/books"})
        off = request_options(["calibre-web"], "dune book", hosts, None)
        self.assertIn("/request/books?q=dune%20book", [o.href for o in on])
        self.assertEqual(["/requestabook"], [o.href for o in off])


if __name__ == "__main__":
    unittest.main()
