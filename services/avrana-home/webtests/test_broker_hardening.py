"""Tier A/B: the request brokers' hardening pass: post-redirect-get with a one-shot outcome, search cache and per-member
search allowance, a form key that survives restarts, HEAD never searching, a stale index making no claims, the Seerr
user map's deadline, and the Request chooser opening Home's own ask pages. SYNTHETIC data only."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from avrana_home.requests.forms import Flash, FormSigner, SearchCache, SearchLimiter, form_key
from avrana_home.requests.owned import MAX_AGE, OwnedIndex
from avrana_home.requests.seerr import MAP_DEADLINE, SeerrRequests
from avrana_home.requests.shelfarr import ShelfarrRequests
from avrana_home.resilience import FakeClock, TransportResponse
from .support import GROUPS, USER, PeerOverride, StubAdapter, make_settings, require_framework
from .test_web_book_requests import BOTH, SAME, FakeShelfarr
from .test_web_watch_requests import VIEWER, FakeSeerr, JellyfinStub

require_framework()


def client(settings, **kw):
    from fastapi.testclient import TestClient
    from avrana_home.app.main import create_app
    app = create_app(settings, **kw)
    c = TestClient(PeerOverride(app, ("203.0.113.7", 50000)), base_url="http://portal.test", follow_redirects=False,
                   raise_server_exceptions=False)
    c.__enter__()
    return c


class Units(unittest.TestCase):
    def test_form_key_is_stable_and_labelled(self):
        self.assertIsNone(form_key(""))
        k = form_key("x" * 40)
        self.assertEqual(k, form_key("x" * 40))
        self.assertNotEqual(k, form_key("y" * 40))
        token = FormSigner(k).sign("member-a", {"a": "1"})
        self.assertTrue(FormSigner(form_key("x" * 40)).verify(token, "member-a", {"a": "1"}))   # after a restart

    def test_limiter(self):
        now = [0.0]
        lim = SearchLimiter(now=lambda: now[0], window=60.0, limit=3)
        self.assertEqual([True, True, True, False], [lim.allow("a") for _ in range(4)])
        self.assertTrue(lim.allow("b"))
        now[0] = 61.0
        self.assertTrue(lim.allow("a"))

    def test_cache_and_flash(self):
        now = [0.0]
        cache = SearchCache(ttl=10.0, size=2, now=lambda: now[0])
        cache.put("a", 1); cache.put("b", 2); cache.put("c", 3)
        self.assertIsNone(cache.get("a"))                 # the oldest went when the cache filled
        self.assertEqual(3, cache.get("c"))
        now[0] = 11.0
        self.assertIsNone(cache.get("c"))
        flash = Flash(now=lambda: now[0])
        flash.put("m", "/p", "said")
        self.assertIsNone(flash.take("other", "/p"))
        self.assertEqual("said", flash.take("m", "/p"))
        self.assertIsNone(flash.take("m", "/p"))           # once only

    def test_stale_index_makes_no_claims(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ids.json"
            built = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
            path.write_text(json.dumps({"version": 1, "built": built.isoformat(), "ebook": {"hardcover:1": "45"}}))
            fresh = OwnedIndex(path, wall=lambda: built.timestamp() + 3600)
            stale = OwnedIndex(path, wall=lambda: built.timestamp() + MAX_AGE + 1)
            self.assertEqual("45", fresh.exact("ebook", ["hardcover:1"]))
            self.assertIsNone(stale.exact("ebook", ["hardcover:1"]))
            path.write_text(json.dumps({"version": 1, "ebook": {"hardcover:1": "45"}}))   # no build time
            self.assertIsNone(OwnedIndex(path).exact("ebook", ["hardcover:1"]))

    def test_seerr_map_refresh_is_abandoned_past_its_deadline(self):
        clock = FakeClock()

        class SlowPages:
            calls = 0

            def request(self, method, path, query, timeout, max_bytes, **kw):
                SlowPages.calls += 1
                clock.advance(MAP_DEADLINE / 2 + 0.1)
                page = [{"id": 10 + SlowPages.calls, "permissions": 32, "jellyfinUserId": f"{SlowPages.calls:032x}"}
                        for _ in range(100)]
                return TransportResponse(200, json.dumps({"results": page}).encode())
        c = SeerrRequests(SlowPages(), clock=clock)
        self.assertEqual(("unavailable", None), c.user_for("1".rjust(32, "0")))
        self.assertLessEqual(SlowPages.calls, 3)


class Pages(unittest.TestCase):
    def books(self, **extra):
        self.shelfarr = FakeShelfarr()
        c = client(make_settings(home_sections=True, book_requests=True, shelfarr_base_url="http://127.0.0.1:1",
                                 **extra), adapters=[StubAdapter({})], book_requests=ShelfarrRequests(self.shelfarr))
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def form(self, c, term="dune"):
        import re
        r = c.get("/request/books", params={"q": term}, headers=BOTH)
        block = re.search(r'<form method="post" action="/request/books"[^>]*>(.*?)</form>', r.text, re.S).group(1)
        return dict(re.findall(r'name="([a-z_]+)" value="([^"]*)"', block))

    def test_post_redirects_back_to_the_search_with_a_one_shot_outcome(self):
        c = self.books()
        fields = self.form(c)
        r = c.post("/request/books", content=urlencode(fields),
                   headers=[("Content-Type", "application/x-www-form-urlencoded")] + BOTH + SAME)
        self.assertEqual(303, r.status_code)
        self.assertEqual("/request/books", r.headers["location"])      # our own fixed path; the term rides the flash
        page = c.get(r.headers["location"], headers=BOTH)
        self.assertIn("Asked for the ebook of Synthetic Dune.", page.text)
        self.assertIn("Asked for the ebook just now.", page.text)        # over the same results
        self.assertIn('value="dune"', page.text)                          # the search box keeps the term
        self.assertEqual(1, page.text.count('role="status"'))
        again = c.get(r.headers["location"], headers=BOTH)        # a reload: the outcome is not shown twice
        self.assertNotIn("Asked for the ebook of Synthetic Dune.", again.text)
        self.assertNotIn("Asked for the ebook just now.", again.text)
        self.assertEqual(1, sum(1 for call in self.shelfarr.calls if call[0] == "GET"))   # the rest from the cache

    def test_redirect_never_carries_anything_from_the_form(self):
        c = self.books()
        fields = dict(self.form(c), q="x\r\nLocation: https://evil.example")
        r = c.post("/request/books", content=urlencode(fields),
                   headers=[("Content-Type", "application/x-www-form-urlencoded")] + BOTH + SAME)
        self.assertEqual("/request/books", r.headers["location"])      # nothing from the form, ever
        self.assertNotIn("location", {k.lower() for k in r.headers if k.lower() != "location"})

    def test_search_allowance_per_member(self):
        from avrana_home.requests import forms
        c = self.books()
        for i in range(forms.SEARCH_MAX):
            self.assertNotIn("searched a lot", c.get("/request/books", params={"q": f"term {i}"}, headers=BOTH).text)
        r = c.get("/request/books", params={"q": "one more"}, headers=BOTH)
        self.assertIn("You have searched a lot in the last few minutes.", r.text)
        self.assertNotIn("searched a lot", c.get("/request/books", params={"q": "term 0"}, headers=BOTH).text)  # cached
        self.assertEqual(forms.SEARCH_MAX, len(self.shelfarr.calls))

    def test_head_never_searches(self):
        c = self.books()
        self.assertEqual(200, c.head("/request/books", params={"q": "dune"}, headers=BOTH).status_code)
        self.assertEqual([], self.shelfarr.calls)

    def test_forms_survive_a_restart_with_a_jwt_secret(self):
        c1 = self.books(jwt_secret="s" * 40)
        fields = self.form(c1)
        c2 = self.books(jwt_secret="s" * 40)                         # a new process, the same secret
        r = c2.post("/request/books", content=urlencode(fields),
                    headers=[("Content-Type", "application/x-www-form-urlencoded")] + BOTH + SAME)
        self.assertEqual(303, r.status_code)

    def test_chooser_opens_the_ask_pages(self):
        seerr, jf = FakeSeerr(), JellyfinStub()
        c = client(make_settings(home_sections=True, book_requests=True, shelfarr_base_url="http://127.0.0.1:1",
                                 watch_requests=True, seerr_base_url="http://127.0.0.1:2"),
                   adapters=[jf], book_requests=ShelfarrRequests(FakeShelfarr()), watch_requests=SeerrRequests(seerr))
        self.addCleanup(c.__exit__, None, None, None)
        who = [(USER, "member-v"), (GROUPS, "avrana-users|avrana-videos|avrana-books")]
        r = c.get("/request", headers=who)
        self.assertEqual(200, r.status_code)
        self.assertIn('href="/request/watch"', r.text)
        self.assertIn('href="/request/books"', r.text)
        self.assertIn("Search and ask here", r.text)
        only_video = c.get("/request", headers=VIEWER)
        self.assertNotIn('href="/request/books"', only_video.text)


if __name__ == "__main__":
    unittest.main()
