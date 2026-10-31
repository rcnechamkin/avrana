"""The catalogue with Calibre-Web Automated (handoff 04): every book through OPDS, in windows of the upstream's own page
size, and a hostile feed refused. Offline, SYNTHETIC; shapes from the CWA 4.0.6 source, UNVERIFIED live."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import unittest
from xml.sax.saxutils import escape

from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.adapters.calibre_web import CalibreWebAdapter
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.adapters.komga import KomgaAdapter
from avrana_home.contract import SectionState
from avrana_home.resilience import FakeClock
from tests.catalog_support import SIZES, Wire, member, walk


HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom"><title>Books</title>'
        '<id>urn:synthetic</id>{link}')


def entry(n):
    return (f'<entry><title>{escape(f"Synthetic Novel {n:05}")}</title><author><name>Synthetic Author</name></author>'
            f'<link rel="http://opds-spec.org/image/thumbnail" href="/opds/cover_240_240/{n + 1}"/></entry>')


class CalibreWeb(unittest.TestCase):
    PER_PAGE = 60

    def setUp(self):
        self.count = 0
        self.wire = Wire(self.handle, "application/atom+xml")
        self.adapter = CalibreWebAdapter(self.wire, clock=FakeClock(), owner_confirms_no_member_restrictions=True)
        self.alice = member("alice")

    def handle(self, path, query):
        assert path == "/opds/books/letter/00"
        offset = int(query.get("offset", "0"))
        assert offset % self.PER_PAGE == 0, "an offset that is not a multiple can land one entry off"
        ends = offset + self.PER_PAGE
        link = (f'<link rel="next" href="/opds/books/letter/00?offset={ends}"/>' if ends < self.count else "")
        rows = "".join(entry(n) for n in range(offset, min(ends, self.count)))
        return 200, (HEAD.format(link=link) + rows + "</feed>").encode()

    def test_every_size_pages_without_gaps_or_repeats(self):
        for n in SIZES[:-1]:
            self.count = n
            ad = CalibreWebAdapter(self.wire, clock=FakeClock(), owner_confirms_no_member_restrictions=True)
            seen, _ = walk(ad, self.alice, "titles")
            self.assertEqual([f"Synthetic Novel {i:05}" for i in range(n)], [i.title for i in seen], n)

    def test_a_deep_page_stays_bounded_at_three_calls(self):
        self.count = 25000
        self.wire.calls.clear()
        out = self.adapter.catalog(self.alice, "titles", 8)     # entries 168-191 cross the boundary at 180
        self.assertEqual(24, len(out.items))
        self.assertEqual("Synthetic Novel 00168", out.items[0].title)
        self.assertEqual(3, len(self.wire.calls))
        self.assertTrue(out.has_next)

    def test_a_count_is_given_only_when_the_whole_catalogue_was_seen(self):
        self.count = 40
        self.assertEqual(40, self.adapter.catalog(self.alice, "titles").total)
        self.count = 61
        ad = CalibreWebAdapter(self.wire, clock=FakeClock(), owner_confirms_no_member_restrictions=True)
        self.assertIsNone(ad.catalog(self.alice, "titles").total)

    def hostile(self, link, rows=""):
        body = (HEAD.format(link=link) + entry(1) + rows + "</feed>").encode()
        return CalibreWebAdapter(Wire(lambda p, q: (200, body), "application/atom+xml"), clock=FakeClock(),
                                 owner_confirms_no_member_restrictions=True).catalog(self.alice, "titles")

    def test_a_next_link_that_goes_anywhere_else_or_back_is_refused(self):
        for href in ("https://evil.example/opds/books/letter/00?offset=60", "//evil.example/opds/books/letter/00?offset=60",
                     "/admin/view?offset=60", "/opds/books/letter/00?offset=0", "/opds/books/letter/00?offset=-1",
                     "/opds/books/letter/00?offset=60&x=1", "/opds/books/letter/00/../../admin?offset=60"):
            out = self.hostile(f'<link rel="next" href="{escape(href)}"/>')
            self.assertEqual(SectionState.UNAVAILABLE, out.state, href)

    def test_xml_attacks_are_refused(self):
        bodies = [b'<!DOCTYPE feed [<!ENTITY x "y">]><feed xmlns="http://www.w3.org/2005/Atom"></feed>',
                  b"<html><body>sign in</body></html>", b"not xml at all"]
        for body in bodies:
            ad = CalibreWebAdapter(Wire(lambda p, q: (200, body)), clock=FakeClock(),
                                   owner_confirms_no_member_restrictions=True)
            self.assertEqual(SectionState.UNAVAILABLE, ad.catalog(self.alice, "titles").state, body)

    def test_the_group_comes_first(self):
        self.assertEqual(SectionState.NOT_PERMITTED, self.adapter.catalog(member("x", "avrana-comics"), "titles").state)
        self.assertEqual([], self.wire.calls)

    def test_an_oversized_window_is_refused(self):
        rows = "".join(entry(n) for n in range(300))
        self.assertEqual(SectionState.UNAVAILABLE, self.hostile("", rows).state)


class Registry(unittest.TestCase):
    def test_only_groupings_that_really_page_are_offered(self):
        self.assertEqual(("movies", "series"), JellyfinAdapter.catalog_groups)
        self.assertEqual(("titles",), AudiobookshelfAdapter.catalog_groups)
        self.assertEqual(("series",), KomgaAdapter.catalog_groups)
        self.assertEqual(("titles",), CalibreWebAdapter.catalog_groups)


if __name__ == "__main__":
    unittest.main()
