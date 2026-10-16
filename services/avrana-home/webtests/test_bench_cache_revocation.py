"""AVR-503, benchmark-adjacent: a WARM cache never discloses titles, artwork or progress after a group is lost,
nor to another member. Uses the benchmark's synthetic world (tools/bench_catalog.py) at zero latency, the real
app, the real four adapters and the one shared MemberCache. In-process only (no socket).

Existing tests cover the cold-cache versions of these rules (tests/test_search.py revoked search,
webtests/test_web_artwork.py no-group 404, webtests/test_web_home.py two members). The gap closed here: the
victim's Home and thumbnails are already IN the cache when the other request arrives."""
import re
import unittest

from .support import require_framework

require_framework()

from tools.bench_catalog import Bench, Capture, World, fast   # noqa: E402

TITLE = re.compile(r"Synthetic [A-Z][a-z]+ [A-Z][a-z]+ \d+")
ART = re.compile(r'src="(/art/[a-z-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+)"')


class WarmCacheIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World(seed=503, size=200)
        cls.by_name = {m.username: m for m in cls.world.members}

    def setUp(self):
        self.b = Bench(self.world, fast(0), Capture())
        self.addCleanup(self.b.close)
        self.a = self.by_name["bench-m01"]                 # all four libraries
        status, html, *_ = self.b.get("/", self.a.headers())
        self.assertEqual(200, status)
        self.titles = set(TITLE.findall(html))
        self.art = ART.findall(html)
        self.assertTrue(self.titles and self.art)
        for ref in self.art:                               # thumbnails cached for the victim
            self.assertEqual(200, self.b.get(ref, self.a.headers())[0])
        self.assertEqual(0, self.b.get("/", self.a.headers())[3])     # and the page is warm: no upstream call
        self.assertGreater(len(self.b.cache), 0)

    def test_the_same_member_after_every_library_group_is_revoked_sees_nothing_cached(self):
        revoked = self.a.headers(groups=("avrana-users",))
        status, html, _ms, calls, _u = self.b.get("/", revoked)
        self.assertEqual((200, 0), (status, calls))
        self.assertEqual(set(), self.titles & set(TITLE.findall(html)))
        self.assertNotIn("/art/", html)
        self.assertNotIn("Continue", html)                 # no progress of any kind
        for ref in self.art:
            status, body, _ms, calls, _u = self.b.get(ref, revoked)
            self.assertEqual((404, 0), (status, calls), ref)
        status, html, _ms, calls, _u = self.b.get("/search?q=synthetic", revoked)
        self.assertEqual(0, calls)
        self.assertEqual(set(), set(TITLE.findall(html)))

    def test_losing_one_group_hides_that_library_and_its_cached_thumbnails_at_once(self):
        only_books = self.a.headers(groups=("avrana-users", "avrana-audiobooks"))
        status, html, *_ = self.b.get("/", only_books)
        self.assertEqual(200, status)
        self.assertNotIn("/art/jellyfin/", html)
        self.assertNotIn("/art/komga/", html)
        self.assertNotIn("/art/calibre-web/", html)
        for ref in (r for r in self.art if not r.startswith("/art/audiobookshelf/")):
            status, _body, _ms, calls, _u = self.b.get(ref, only_books)
            self.assertEqual((404, 0), (status, calls), ref)

    def test_another_member_never_receives_the_victims_cached_page_or_thumbnails(self):
        other = self.by_name["bench-m07"]                  # Audiobookshelf only; its own upstream account
        status, html, *_ = self.b.get("/", other.headers())
        self.assertEqual(200, status)
        mine = set(TITLE.findall(html))
        jellyfin_titles = self.titles & set(self.world.sims["jellyfin"].titles)
        self.assertEqual(set(), mine & jellyfin_titles)
        self.assertNotIn("/art/jellyfin/", html)
        cold = Bench(self.world, fast(0), Capture())       # the same requests against an EMPTY cache
        self.addCleanup(cold.close)
        for ref in self.art:
            status, _body, _ms, calls, _u = self.b.get(ref, other.headers())
            if not ref.startswith("/art/audiobookshelf/"):
                self.assertEqual((404, 0), (status, calls), ref)   # no group: refused before cache or upstream
            else:
                # Same group, different member: re-checked upstream against THIS member's own permissions (so at
                # least one upstream call), with the same answer an empty cache gives: the victim's copy is unused.
                self.assertGreater(calls, 0, ref)
                self.assertEqual(cold.get(ref, other.headers())[0], status, ref)


if __name__ == "__main__":
    unittest.main()
