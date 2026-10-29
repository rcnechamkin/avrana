"""Each book library tells Home the day a book reached it (MediaItem.added, owner request 2026-10-29), so New Releases
can place a book whose release date is only a year. Offline, synthetic fixtures only."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import re
import unittest

from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.adapters.calibre_web import CalibreWebAdapter
from avrana_home.adapters.komga import KomgaAdapter
from avrana_home.resilience import FakeClock
from tests.fake_abs import FakeAudiobookshelf
from tests.fake_calibre_web import FakeCalibreWeb
from tests.fake_jellyfin import FakeTransport
from tests.fake_komga import FakeKomga
from tests.helpers import make_principal

DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class Added(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()

    def test_calibre_web_reads_its_updated_date(self):
        a = CalibreWebAdapter(FakeTransport(FakeCalibreWeb(self.clock)), clock=self.clock,
                              owner_confirms_no_member_restrictions=True)
        items = a.recent_items(make_principal("member-a", ("avrana-books",))).items
        self.assertTrue(items and all(i.added == "2026-01-01" for i in items))

    def test_komga_reads_created(self):
        a = KomgaAdapter(FakeTransport(FakeKomga(self.clock)), clock=self.clock,
                         owner_confirms_no_member_restrictions=True)
        items = a.recent_items(make_principal("member-a", ("avrana-comics",))).items
        self.assertTrue(items and all(DAY.fullmatch(i.added or "") for i in items))

    def test_audiobookshelf_reads_added_at(self):
        a = AudiobookshelfAdapter(FakeTransport(FakeAudiobookshelf(self.clock)), clock=self.clock)
        items = a.recent_items(make_principal("member-a", ("avrana-audiobooks",))).items
        self.assertTrue(items)
        self.assertTrue(all(DAY.fullmatch(i.added or "") for i in items))


if __name__ == "__main__":
    unittest.main()
