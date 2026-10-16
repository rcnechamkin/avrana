"""Continue semantics (Home 2.0, AVR-381/504): what a Continue card says and which verb it offers, from the
adapters' own parsing through `member_view()` to the view-model. SYNTHETIC fixtures, no sockets.

Rules under test:
  * "Resume" only when the upstream gave THIS member a saved position (Jellyfin `UserData.PlaybackPositionTicks`
    of at least one second; Audiobookshelf `mediaProgress.currentTime` of at least one second, not finished).
    Anything else is "Open". Komga and Calibre-Web have no member progress and never offer Continue.
  * Remaining time is the upstream's own numbers: Jellyfin RunTimeTicks - PlaybackPositionTicks (10,000,000 ticks
    per second); Audiobookshelf duration - currentTime (seconds, float). A percent only when that is all there is.
  * Finished items never appear in Continue; hostile numbers (negative, NaN, huge, wrong type) are unknown.
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import json
import unittest

from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.adapters.jellyfin import TICKS_PER_SECOND, JellyfinAdapter
from avrana_home.app.viewmodel import (KIND_LABEL, MAX_PLAUSIBLE_SECONDS, build_home, continue_state,
                                       progress_words)
from avrana_home.app.catalogue import Trusted
from avrana_home.contract import SectionResult, SectionState, Service
from avrana_home.resilience import FakeClock
from tests.fake_abs import UA, FakeAudiobookshelf
from tests.fake_jellyfin import FakeJellyfin, FakeTransport
from tests.helpers import make_principal

JF_GROUPS = ("avrana-users", "avrana-videos")
TILES = [("watch", Trusted("Watch"), Trusted("Movies")), ("listen", Trusted("Listen"), Trusted("Audiobooks")),
         ("help", Trusted("Help"), Trusted("Guides"))]
FILM = "cccc0000000000000000000000000001"


def view_of(*results):
    return {"sections": [r.to_dict() for r in results]}


def jf_item(position_ticks, run_ticks=72000000000, played=False, kind="Movie", **extra):
    data = {"Played": played}
    if position_ticks is not ...:
        data["PlaybackPositionTicks"] = position_ticks
    raw = {"Id": FILM, "Name": "Synthetic Edge Film", "Type": kind, "UserData": data}
    if run_ticks is not ...:
        raw["RunTimeTicks"] = run_ticks
    raw.update(extra)
    return raw


class JellyfinContinue(unittest.TestCase):
    def setUp(self):
        self.fake = FakeJellyfin(FakeClock())
        self.adapter = JellyfinAdapter(FakeTransport(self.fake), clock=FakeClock())
        self.a = make_principal("member-a", JF_GROUPS)

    def serve(self, *items):
        self.setUp()                              # a fresh adapter per call: no cache, closed circuit
        self.fake.overrides["/UserItems/Resume"] = ("body", json.dumps({"Items": list(items)}).encode())
        return self.adapter.continue_items(self.a)

    def card(self, *items):
        home = build_home(view_of(self.serve(*items)), TILES)
        return home.continue_items

    def test_ticks_are_ten_million_per_second_and_remaining_is_run_minus_position(self):
        # 2 h run, 38 min 59.9 s watched -> 81 min 0.1 s left -> "1 hour 22 minutes left" (minutes rounded up)
        pos = (38 * 60 + 59) * TICKS_PER_SECOND + 9_000_000
        (c,) = self.card(jf_item(pos))
        self.assertEqual(("Resume", "1 hour 22 minutes left"), (c.action, c.progress))
        self.assertEqual("Resume in Movies and TV", c.action_label)
        self.assertNotIn("Synthetic Edge Film", c.action_label)       # the link already starts with the title
        self.assertEqual("Movie", c.kind_label)
        r = self.serve(jf_item(pos))
        self.assertEqual((2339, 7200), (r.items[0].position_seconds, r.items[0].duration_seconds))

    def test_zero_position_is_not_in_progress(self):
        self.assertIs(SectionState.EMPTY, self.serve(jf_item(0)).state)

    def test_a_sub_second_position_is_open_not_resume(self):
        (c,) = self.card(jf_item(TICKS_PER_SECOND - 1))
        self.assertEqual("Open", c.action)
        self.assertEqual("Open in Movies and TV", c.action_label)

    def test_played_items_never_reach_continue(self):
        self.assertIs(SectionState.EMPTY, self.serve(jf_item(30 * TICKS_PER_SECOND, played=True)).state)

    def test_position_at_or_past_the_end_is_finished_and_left_out(self):
        for pos in (72000000000, 72000000000 + 5 * TICKS_PER_SECOND):
            with self.subTest(pos=pos):
                home = build_home(view_of(self.serve(jf_item(pos))), TILES)
                self.assertEqual((), home.continue_items)
                self.assertNotIn("finished", repr(home))

    def test_missing_run_time_uses_the_percent_or_the_position_only(self):
        pct = jf_item(1800 * TICKS_PER_SECOND, run_ticks=...)
        pct["UserData"]["PlayedPercentage"] = 25.0
        (c,) = self.card(pct)
        self.assertEqual(("Resume", "25 percent watched"), (c.action, c.progress))
        (c,) = self.card(jf_item(1800 * TICKS_PER_SECOND, run_ticks=...))
        self.assertEqual(("Resume", "30 minutes in"), (c.action, c.progress))

    def test_hostile_numbers_are_unknown_never_a_made_up_time(self):
        for pos, run in ((-5, 72000000000), (float("nan"), 72000000000), ("30", 72000000000), (True, 100),
                         (2 ** 70, 72000000000)):
            with self.subTest(pos=pos):
                r = self.serve(jf_item(pos, run))
                self.assertIn(r.state, (SectionState.EMPTY, SectionState.UNAVAILABLE))
        # a huge but bounded run time: the position is believed, the duration is not
        (c,) = self.card(jf_item(600 * TICKS_PER_SECOND, run_ticks=(MAX_PLAUSIBLE_SECONDS + 1) * TICKS_PER_SECOND))
        self.assertEqual("Resume", c.action)
        self.assertNotIn("hours left", c.progress or "")

    def test_episode_line_is_series_and_episode(self):
        (c,) = self.card(jf_item(60 * TICKS_PER_SECOND, kind="Episode", SeriesName="Synthetic Series",
                                 ParentIndexNumber=1, IndexNumber=3))
        self.assertEqual("S1 E3 · Synthetic Series", c.line)      # the marker survives a one-line clamp
        self.assertEqual("Episode", c.kind_label)
        self.assertEqual("still", c.shape)


class AudiobookshelfContinue(unittest.TestCase):
    def cards(self, **update):
        clock = FakeClock()                       # a fresh fake and adapter per call: nothing cached
        fake = FakeAudiobookshelf(clock)
        adapter = AudiobookshelfAdapter(FakeTransport(fake), clock=clock)
        rec = fake.record(UA)
        rec["mediaProgress"] = rec["mediaProgress"][:1]
        rec["mediaProgress"][0].update(update)
        fake.serve(f"/api/users/{UA}", rec)
        a = make_principal("member-a", ("avrana-users", "avrana-audiobooks"))
        return build_home(view_of(adapter.continue_items(a)), TILES).continue_items

    def test_saved_seconds_resume_with_duration_minus_current_time(self):
        (c,) = self.cards(progress=0.5, currentTime=18000.7, duration=36000.2)
        self.assertEqual(("Resume", "5 hours left"), (c.action, c.progress))
        self.assertEqual("Audiobook", c.kind_label)
        self.assertEqual("Resume in Audiobooks", c.action_label)

    def test_progress_without_a_position_is_open_with_a_percent(self):
        (c,) = self.cards(progress=0.42, currentTime=None, duration=None)
        self.assertEqual("Open", c.action)
        self.assertEqual("42 percent listened", c.progress)

    def test_finished_by_flag_or_by_numbers_is_left_out(self):
        self.assertEqual((), self.cards(progress=0.99, isFinished=True))
        self.assertEqual((), self.cards(progress=1.0, isFinished=False))


class ViewModelBoundaries(unittest.TestCase):
    def test_continue_state_table(self):
        cases = [
            (None, (False, False)),
            ({}, (False, False)),
            ({"position_seconds": 0, "duration_seconds": 100}, (False, False)),
            ({"position_seconds": 1, "duration_seconds": 100}, (False, True)),
            ({"position_seconds": 100, "duration_seconds": 100}, (True, False)),
            ({"position_seconds": 101, "duration_seconds": 100}, (True, False)),
            ({"position_seconds": -1, "duration_seconds": 100}, (False, False)),
            ({"position_seconds": 5.5, "duration_seconds": 100}, (False, False)),
            ({"position_seconds": True, "duration_seconds": 100}, (False, False)),
            ({"position_seconds": MAX_PLAUSIBLE_SECONDS + 1}, (False, False)),
            ({"position_seconds": 50, "duration_seconds": MAX_PLAUSIBLE_SECONDS + 1}, (False, True)),
            ({"fraction": 1.0}, (True, False)),
            ({"fraction": float("nan")}, (False, False)),
            ({"fraction": 0.99, "percent": 99}, (False, False)),
            ({"position_seconds": 10, "duration_seconds": None, "fraction": 1.0}, (True, False)),
        ]
        for progress, want in cases:
            with self.subTest(progress=progress):
                self.assertEqual(want, continue_state(progress))

    def test_percent_edges_in_words(self):
        self.assertEqual("just started", progress_words("movie", {"percent": 0}))
        self.assertEqual("nearly finished", progress_words("audiobook", {"percent": 100}))
        self.assertIsNone(progress_words("movie", {"position_seconds": MAX_PLAUSIBLE_SECONDS + 1}))

    def test_kind_labels_are_member_language(self):
        self.assertEqual({"movie": "Movie", "episode": "Episode", "series": "Series", "audiobook": "Audiobook",
                          "comic": "Comic", "ebook": "Book"}, KIND_LABEL)

    def test_new_this_week_is_always_open_without_progress(self):
        res = SectionResult.of(Service.JELLYFIN, "recent", ())
        home = build_home({"sections": [res.to_dict(), {
            "service": "jellyfin", "section": "recent", "state": "ok", "items": [{
                "id": "jellyfin:" + FILM, "service": "jellyfin", "kind": "movie", "title": "Synthetic New",
                "handoff_url": "https://watch.avrana.net/web/#/details?id=" + FILM,
                "progress": {"position_seconds": 50, "duration_seconds": 100}}]}]}, TILES)
        (c,) = home.new_items
        self.assertEqual(("Open", "Open in Movies and TV", None), (c.action, c.action_label, c.progress))



class HandoffTests(unittest.TestCase):
    """AVR-479: item links are allowlisted (fixed host per service), built only from a validated id, and a Home
    card never renders a link to any other host."""

    def test_each_service_has_one_fixed_host_and_path(self):
        from avrana_home.contract import build_handoff_url
        self.assertEqual("https://watch.avrana.net/web/#/details?id=" + FILM, build_handoff_url(Service.JELLYFIN, FILM))
        uuid = "0a0b0c0d-1111-4222-8333-444455556666"
        self.assertEqual("https://listen.avrana.net/item/" + uuid, build_handoff_url(Service.AUDIOBOOKSHELF, uuid))
        self.assertEqual("https://read.avrana.net/book/0SYNTH1234AB", build_handoff_url(Service.KOMGA, "0SYNTH1234AB"))
        self.assertEqual("https://books.avrana.net/book/42", build_handoff_url(Service.CALIBRE_WEB, "42"))

    def test_hostile_ids_never_become_links(self):
        from avrana_home.contract import HandoffError, build_handoff_url
        hostile = ["", "../x", "//evil.example", "https://evil.example", "a b", "%2e%2e", "42?next=//e",
                   "42#x", "@evil.example", "\evil", "A" * 33, FILM + "0", None, 42]
        for service in Service:
            for bad in hostile:
                with self.subTest(service=service, bad=bad):
                    with self.assertRaises(HandoffError):
                        build_handoff_url(service, bad)
        with self.assertRaises(HandoffError):
            build_handoff_url(Service.JELLYFIN, FILM.upper())     # adapters normalise; the contract does not

    def test_a_card_renders_only_allowlisted_hosts(self):
        bad = ["https://evil.example/web/#/details?id=1", "https://watch.avrana.net.evil.example/x",
               "https://watch.avrana.net@evil.example/x", "https://watch.avrana.net", "http://watch.avrana.net/x",
               "https://WATCH.avrana.net/x", " https://watch.avrana.net/x", "javascript:alert(1)", None]
        items = [{"id": f"jellyfin:{i}", "service": "jellyfin", "kind": "movie", "title": f"Bad {i}",
                  "handoff_url": u, "progress": {"position_seconds": 60, "duration_seconds": 600}}
                 for i, u in enumerate(bad)]
        items.append(dict(items[0], title="Good", handoff_url="https://listen.avrana.net/item/x"))
        home = build_home({"sections": [{"service": "jellyfin", "section": "continue", "state": "ok",
                                         "items": items}]}, TILES)
        self.assertEqual(["Good"], [c.title for c in home.continue_items])


if __name__ == "__main__":
    unittest.main()
