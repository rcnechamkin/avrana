"""Title-page synopsis (R2-C, AVR-384): plain text only, title lookups only, after every permission check.
Offline; synthetic fixtures only."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import json
import unittest

from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.adapters.komga import KomgaAdapter
from avrana_home.contract import MAX_SUMMARY, clean_summary
from avrana_home.resilience import FakeClock
from tests.fake_abs import FakeAudiobookshelf
from tests.fake_jellyfin import FakeJellyfin, FakeTransport
from tests.fake_komga import FakeKomga
from tests.helpers import make_principal

ALL = ("avrana-users", "avrana-videos", "avrana-audiobooks", "avrana-comics", "avrana-books")
FILM_A3 = "aaaa0000000000000000000000000010"


class CleanSummaryTests(unittest.TestCase):
    def test_markup_is_removed_and_entities_decoded(self):
        self.assertEqual(clean_summary("<p>A <b>bold</b> &amp; brave &lt;tale&gt;.</p><p>Two</p>"),
                         "A bold & brave <tale>. Two")

    def test_scripts_styles_comments_and_attributes_leave_nothing(self):
        text = clean_summary('<script>alert("x")</script><style>p{}</style><!-- c --><a href="javascript:x"'
                             ' onclick="y()">link</a> <img src=x onerror=alert(1)>')
        self.assertEqual(text, "link")

    def test_unclosed_and_nested_scripts_do_not_leak(self):
        self.assertIsNone(clean_summary("<script>never closed"))
        # as a browser parses it: script content is raw text up to the first </script>
        self.assertEqual(clean_summary("a<script><script>x</script>y</script>b"), "ayb")

    def test_control_and_bidi_characters_are_dropped(self):
        self.assertEqual(clean_summary("safe‮text\x00\x1b[31m here"), "safe text [31m here")

    def test_long_text_is_cut_at_a_word_with_an_ellipsis(self):
        text = clean_summary("word " * 1000)
        self.assertLessEqual(len(text), MAX_SUMMARY + 1)
        self.assertTrue(text.endswith("word…"), text[-12:])

    def test_the_ellipsis_survives_the_view_model(self):
        from avrana_home.app.viewmodel import build_title
        long = clean_summary("x" * 3000)              # one token, no space to cut at
        self.assertTrue(long.endswith("…"))
        section = {"state": "ok", "items": [{"id": "komga:BOOKAAAA0001", "kind": "comic", "title": "T",
                                             "handoff_url": "https://read.avrana.net/book/BOOKAAAA0001",
                                             "summary": long}]}
        self.assertTrue(build_title(section, "komga", "BOOKAAAA0001", None).summary.endswith("…"))

    def test_huge_input_is_bounded_before_parsing(self):
        text = clean_summary("<b>" * 200000 + "x")
        self.assertIsNone(text)                     # the text after the cut-off is never reached

    def test_non_text_is_none(self):
        for value in (None, "", "   ", "<p></p>", 5, ["x"], {"a": 1}):
            self.assertIsNone(clean_summary(value), repr(value))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.member = make_principal("member-a", ALL)

    def test_jellyfin_asks_for_the_overview_only_on_the_title_lookup(self):
        fake = FakeJellyfin(FakeClock())
        adapter = JellyfinAdapter(FakeTransport(fake), clock=FakeClock())
        recent = adapter.recent_items(self.member).items
        self.assertTrue(recent)
        self.assertTrue(all(i.summary is None for i in recent))    # the fake sends Overview anyway: not read
        for _method, _path, query in fake.requests:
            self.assertNotIn("Overview", query.get("fields", ""))
        item = adapter.item(self.member, FILM_A3, fresh=True).items[0]
        self.assertEqual(item.summary, "A synthetic film & its overview. Second line.")
        self.assertIn("Overview", fake.requests[-1][2]["fields"].split(","))

    def test_audiobookshelf_description_is_plain_text(self):
        adapter = AudiobookshelfAdapter(FakeTransport(FakeAudiobookshelf(FakeClock())), clock=FakeClock())
        item = adapter.item(self.member, "li_book000001", fresh=True).items[0]
        self.assertEqual(item.summary, "A synthetic audiobook description. With a link.")
        self.assertNotIn("javascript", json.dumps(item.to_dict()))

    def test_audiobookshelf_never_reads_the_description_of_a_hidden_item(self):
        fake = FakeAudiobookshelf(FakeClock())
        adapter = AudiobookshelfAdapter(FakeTransport(fake), clock=FakeClock())
        # member-a may use library lib_aaa only; li_book000003 is in lib_bbb (fixtures)
        result = adapter.item(self.member, "li_book000003", fresh=True)
        self.assertEqual(result.items, ())

    def test_komga_summary_on_the_title_lookup_only(self):
        adapter = KomgaAdapter(FakeTransport(FakeKomga(FakeClock())), clock=FakeClock(),
                               owner_confirms_no_member_restrictions=True)
        self.assertTrue(all(i.summary is None for i in adapter.recent_items(self.member).items))
        item = adapter.item(self.member, "BOOKAAAA0001", fresh=True).items[0]
        self.assertEqual(item.summary, "A synthetic comic summary.")


if __name__ == "__main__":
    unittest.main()
