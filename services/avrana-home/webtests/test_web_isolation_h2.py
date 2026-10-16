"""Tier B, Home 2.0 Lane D (AVR-375): consolidated cross-member isolation through the HTTP layer.

Two synthetic members with DIFFERENT groups and DIFFERENT upstream users, against the loopback mock Jellyfin,
Audiobookshelf and Komga (SYNTHETIC fixtures, real UrllibTransport):

  member A: Movies and TV + Audiobooks (Jellyfin user member-a, Audiobookshelf user member-a)
  member B: Movies and TV + Comics     (Jellyfin user member-b, the shared Komga view)

For `/`, `/home.json`, `/search?q=` and `/art/...`: no title, item id, cover or progress of one member appears
for the other, with a cold cache, with a warm cache, and while one upstream is down, slow, failing, malformed
or answering with another user's data.

TODO(Lane C, title pages): when `/title/...` lands, add it to ROUTES below and assert the same: a title page
for an item only A can see is the standard 404 for B (cold and warm), and its cover likewise.
"""
import json
import re
import unittest

from dev.mock_audiobookshelf import MockAudiobookshelf
from dev.mock_jellyfin import MockJellyfin
from dev.mock_komga import MockKomga

from .support import GROUPS, USER, make_client, make_settings, require_framework

require_framework()

KEY = "mock-api-key-not-real"
A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks")]
B = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos|avrana-comics")]
# Markers that may only ever appear for their own member. "Synthetic Shared Film" is visible to both upstream
# users by fixture design and is deliberately not a marker.
A_ONLY = ("Synthetic Film One", "Synthetic Film Three", "Synthetic Pilot", "Synthetic Series Alpha", "aaaa0000",
          "Audiobook", "audiobookshelf", "li_book", "Continue listening")
B_ONLY = ("Synthetic Film Two", "Synthetic Film Four", "Synthetic Documentary B", "bbbb0000", "komga",
          "Synthetic Comic", "Synthetic Kids", "Synthetic Teen", "Synthetic Manga", "Synthetic Mature", "Comics")
ROUTES = ("/", "/home.json", "/search?q=Synthetic")       # TODO(Lane C): "/title/..." once it exists
ART = re.compile(r'(/art/[a-z-]+/[a-z]+/[A-Za-z0-9_-]+)')


class Fixture(unittest.TestCase):
    timeout = 1.5

    @classmethod
    def setUpClass(cls):
        cls.jf = MockJellyfin(slow_seconds=3.0).start()
        cls.ab = MockAudiobookshelf(slow_seconds=3.0).start()
        cls.kg = MockKomga(slow_seconds=3.0).start()

    @classmethod
    def tearDownClass(cls):
        for m in (cls.jf, cls.ab, cls.kg):
            m.stop()

    def setUp(self):
        for m in (self.jf, self.ab, self.kg):
            m.set_mode("ok")
            m.reset()

    def client(self):
        c = make_client(make_settings(home_sections=True, jellyfin_base_url=self.jf.url,
                                      audiobookshelf_base_url=self.ab.url, audiobookshelf_token=KEY,
                                      komga_base_url=self.kg.url, komga_token=KEY, timeout=self.timeout))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def assertIsolated(self, who, text, where):
        foreign = B_ONLY if who == "A" else A_ONLY
        for marker in foreign:
            self.assertNotIn(marker, text, f"{where}: {who} saw {marker!r}")

    def covers(self, c, headers):
        found = set()
        for route in ("/", "/search?q=Synthetic"):
            found |= set(ART.findall(c.get(route, headers=headers).text))
        return found


class PagesAndJson(Fixture):
    def test_no_title_id_or_progress_crosses_members_cold_and_warm(self):
        c = self.client()
        seen = {}
        for rnd in ("cold", "warm", "warm again"):
            for route in ROUTES:
                for who, headers in (("A", A), ("B", B)):
                    r = c.get(route, headers=headers)
                    self.assertEqual(200, r.status_code, (rnd, route, who))
                    self.assertIsolated(who, r.text, f"{rnd} {route}")
                    seen.setdefault((who, route), r.text)
        # sanity: each member really sees their own data, so the absence above means something
        self.assertIn("Synthetic Film One", seen[("A", "/")])
        self.assertIn("Synthetic Audiobook", seen[("A", "/")])
        self.assertIn("Synthetic Film Two", seen[("B", "/")])
        self.assertIn("Synthetic Comic", seen[("B", "/search?q=Synthetic")])

    def test_progress_of_one_member_is_never_in_the_others_json(self):
        c = self.client()
        a = json.loads(c.get("/home.json", headers=A).text)
        b = json.loads(c.get("/home.json", headers=B).text)

        def ids(doc):
            return {i["id"] for s in doc["sections"] for i in s.get("items", ())}

        def progress(doc):
            return {i["id"]: i.get("progress") for s in doc["sections"] for i in s.get("items", ())
                    if i.get("progress")}
        self.assertTrue(progress(a) and progress(b))
        shared = ids(a) & ids(b)
        self.assertLessEqual(shared, {"jellyfin:cccc0000000000000000000000000001"})
        for item_id in progress(a):
            self.assertNotIn(item_id, ids(b))
        for item_id in progress(b):
            self.assertNotIn(item_id, ids(a))


class Covers(Fixture):
    def test_each_members_covers_are_the_standard_404_for_the_other_even_when_warm(self):
        c = self.client()
        nf = c.get("/definitely-not-a-route", headers=A).text
        a_covers, b_covers = self.covers(c, A), self.covers(c, B)
        self.assertTrue(a_covers and b_covers)
        both = a_covers & b_covers
        self.assertEqual(set(), both)
        for rnd in ("cold", "warm"):
            for own, other, headers, other_headers in ((a_covers, b_covers, A, B), (b_covers, a_covers, B, A)):
                for path in sorted(own):
                    r = c.get(path, headers=headers)                     # warms the owner's cache
                    self.assertEqual(200, r.status_code, (rnd, path))
                    self.assertTrue(r.headers["content-type"].startswith("image/"))
                    self.assertEqual("private, no-store", r.headers["cache-control"])
                for path in sorted(other):
                    r = c.get(path, headers=headers)
                    self.assertEqual((404, nf), (r.status_code, r.text), (rnd, path))

    def test_a_member_who_loses_a_group_loses_its_covers_at_once(self):
        c = self.client()
        own = sorted(p for p in self.covers(c, A) if p.startswith("/art/audiobookshelf/"))
        for path in own:
            self.assertEqual(200, c.get(path, headers=A).status_code)
        lost = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
        self.ab.reset()
        for path in own:
            self.assertEqual(404, c.get(path, headers=lost).status_code, path)
        self.assertEqual([], self.ab.paths())                      # no upstream call, no cache read


class OneUpstreamFailing(Fixture):
    MODES = ("down", "500", "malformed", "slow", "wrong-user")

    def test_one_failing_upstream_never_breaks_the_page_or_crosses_members(self):
        for mode in self.MODES:
            with self.subTest(mode=mode):
                c = self.client()
                for route in ROUTES:                                     # warm every cache first
                    c.get(route, headers=A)
                    c.get(route, headers=B)
                a_jf_covers = sorted(p for p in self.covers(c, A) if p.startswith("/art/jellyfin/"))
                for path in a_jf_covers:
                    c.get(path, headers=A)
                self.jf.set_mode(mode)
                for route in ROUTES:
                    for who, headers in (("A", A), ("B", B)):
                        r = c.get(route, headers=headers)
                        self.assertEqual(200, r.status_code, (mode, route, who))
                        self.assertIsolated(who, r.text, f"{mode} {route}")
                        for token in ("Traceback", "127.0.0.1", KEY):
                            self.assertNotIn(token, r.text)
                # the other libraries still answer on the same page
                self.assertIn("Synthetic Audiobook", c.get("/", headers=A).text, mode)
                self.assertIn("Synthetic Comic", c.get("/search?q=Comic", headers=B).text, mode)
                # a per-member service that cannot be asked serves no cover, cached or not (fail closed)
                if mode != "wrong-user":
                    for path in a_jf_covers:
                        self.assertEqual(404, c.get(path, headers=A).status_code, (mode, path))
                self.jf.set_mode("ok")
                self.jf.reset()


if __name__ == "__main__":
    unittest.main()
