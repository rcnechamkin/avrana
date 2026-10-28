"""gather skips sections an adapter declares not offered (no change to the member_view keys), and
health_summary covers every registered adapter without leaking a token, a member or a title."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import json
import unittest

from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.adapters.calibre_web import CalibreWebAdapter
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.adapters.komga import KomgaAdapter
from avrana_home.aggregate import gather, health_summary
from avrana_home.contract import SectionState
from avrana_home.resilience import FakeClock, UrllibTransport
from tests.fake_abs import FakeAudiobookshelf
from tests.fake_jellyfin import FakeJellyfin, FakeOpener, FakeTransport
from tests.fake_komga import FakeKomga
from tests.helpers import make_principal

TOKEN = "SENTINEL-HEALTH-TOKEN-0000"
ALL = ("avrana-users", "avrana-videos", "avrana-audiobooks", "avrana-comics")


class Setup(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.jf, self.abs_fake, self.kg = FakeJellyfin(self.clock), FakeAudiobookshelf(self.clock), FakeKomga(self.clock)
        self.jellyfin = JellyfinAdapter(FakeTransport(self.jf), clock=self.clock)
        self.abs = AudiobookshelfAdapter(FakeTransport(self.abs_fake), clock=self.clock)
        self.komga = KomgaAdapter(FakeTransport(self.kg), clock=self.clock,
                                  owner_confirms_no_member_restrictions=True)
        self.adapters = [self.jellyfin, self.abs, self.komga]
        self.p = make_principal("member-a", ALL)


class NotOffered(Setup):
    def test_declared_not_offered_sections_are_not_requested_and_not_in_the_member_view(self):
        view = gather(self.p, self.adapters).member_view()
        pairs = {(s["service"], s["section"]) for s in view["sections"]}
        self.assertIn(("jellyfin", "continue"), pairs)
        self.assertIn(("jellyfin", "recent"), pairs)
        self.assertIn(("audiobookshelf", "continue"), pairs)
        self.assertIn(("komga", "recent"), pairs)
        self.assertIn(("audiobookshelf", "recent"), pairs)                 # offered since 2026-10-27
        self.assertNotIn(("komga", "continue"), pairs)
        self.assertEqual(set(view), {"sections"})                          # the member_view keys are unchanged
        for s in view["sections"]:
            self.assertEqual(set(s), {"service", "section", "state", "items"})
        self.assertNotIn("not_offered", json.dumps(view))                  # the diagnostic reason never shows

    def test_nothing_is_asked_upstream_for_a_skipped_section(self):
        self.assertEqual(gather(self.p, [self.komga], sections=("continue",)).sections, ())
        self.assertEqual(self.kg.requests, [])

    def test_the_skip_does_not_change_what_a_member_without_the_group_sees(self):
        outsider = make_principal("member-a", ("avrana-users",))
        self.assertEqual(gather(outsider, self.adapters).member_view(), {"sections": []})

    def test_called_directly_a_not_offered_method_still_answers_without_a_call(self):
        r = self.komga.continue_items(self.p)
        self.assertEqual((r.state, r.reason), (SectionState.EMPTY, "not_offered"))
        self.assertEqual(self.kg.requests, [])

    def test_the_declarations(self):
        self.assertEqual(self.jellyfin.not_offered, frozenset())
        self.assertEqual(self.abs.not_offered, frozenset())
        self.assertEqual(self.abs.extra_sections, frozenset({"shelves", "released"}))
        self.assertEqual(self.komga.not_offered, frozenset({"continue"}))
        self.assertEqual(self.komga.extra_sections, frozenset({"shelves", "released"}))   # New releases, 2026-10-28
        cwa = CalibreWebAdapter(FakeTransport(FakeKomga(self.clock)), clock=self.clock,
                                owner_confirms_no_member_restrictions=True)
        self.assertEqual(cwa.not_offered, frozenset({"continue", "item"}))
        with self.assertRaises(Exception):                                  # the constructor stays opt-in
            CalibreWebAdapter(FakeTransport(FakeKomga(self.clock)), clock=self.clock)


class NotOfferedHelper(Setup):
    def test_the_shared_helper_gates_on_the_group_first(self):
        outsider = make_principal("member-a", ("avrana-users",))
        for call in (self.abs.next_up_items, self.komga.continue_items):
            self.assertEqual(call(outsider).state, SectionState.NOT_PERMITTED)
            self.assertEqual(call(self.p).state, SectionState.EMPTY)
        with self.assertRaises(TypeError):
            self.abs._not_offered("member-a", "recent")
        self.assertEqual(self.abs_fake.requests + self.kg.requests, [])


class Health(Setup):
    def test_every_registered_adapter_is_reported_exactly_once_before_and_after_traffic(self):
        for _ in range(2):
            h = health_summary(self.adapters)
            self.assertEqual([r["service"] for r in h["adapters"]], ["jellyfin", "audiobookshelf", "komga"])
            self.assertEqual(h["home"], "ok")
            gather(self.p, self.adapters)
        self.assertEqual(health_summary([])["adapters"], [])
        self.assertEqual(health_summary([])["libraries"], "ok")

    def test_one_failing_adapter_degrades_the_summary_and_the_others_stay_ok(self):
        self.kg.overrides["/api/v1/books"] = ("status", 500)
        for name in ("member-a", "member-b", "member-c"):
            self.komga.recent_items(make_principal(name, ALL))
        h = health_summary(self.adapters)
        states = {r["service"]: r["state"] for r in h["adapters"]}
        self.assertEqual(states["komga"], "cooling_off")
        self.assertEqual(h["libraries"], "degraded")
        gather(self.p, [self.jellyfin, self.abs])
        states = {r["service"]: r["state"] for r in health_summary(self.adapters)["adapters"]}
        self.assertEqual((states["jellyfin"], states["audiobookshelf"]), ("ok", "ok"))

    def test_the_summary_leaks_no_token_member_id_title_or_url(self):
        opener = FakeOpener(self.jf)
        header = {"Authorization": "MediaBrowser Token=\"" + TOKEN + "\""}
        jf = JellyfinAdapter(UrllibTransport("https://jf.invalid", header, opener=opener), clock=self.clock)
        adapters = [jf, self.abs, self.komga]
        gather(self.p, adapters)                                           # real titles and ids pass through
        self.jf.overrides["/Users"] = ("status", 401)
        jf.cache.clear()
        jf.recent_items(self.p)
        h = health_summary(adapters)
        blob = json.dumps(h)
        for secret in (TOKEN, "member-a", "Synthetic", "SENTINEL", "jf.invalid", "https://", "li_book", "BOOK",
                       "USERAAAAAAAA1", "aaaaaaaa"):
            self.assertNotIn(secret, blob)
        for row in h["adapters"]:
            self.assertEqual(set(row), {"service", "state", "last_error_class", "retry_in_seconds",
                                        "consecutive_failures"})
            self.assertTrue(row["last_error_class"] is None or row["last_error_class"].isidentifier())

    def test_health_makes_no_upstream_call(self):
        def calls():
            return len(self.jf.requests) + len(self.abs_fake.requests) + len(self.kg.requests)
        n = calls()
        health_summary(self.adapters)
        self.assertEqual(calls(), n)


if __name__ == "__main__":
    unittest.main()
