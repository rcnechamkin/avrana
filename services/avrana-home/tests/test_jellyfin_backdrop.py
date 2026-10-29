"""Jellyfin backdrops for Home's hero (owner review 2026-10-27): parsed from the item (an episode borrows its series'),
fetched only after this member's visibility check of the item that owns the image, never on search results.
SYNTHETIC fixtures and the fake transport; no sockets."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import unittest
from avrana_home.adapters.jellyfin import JellyfinAdapter, check_request
from avrana_home.contract import ForbiddenRequest, SectionState
from avrana_home.resilience import FakeClock
from tests.fake_jellyfin import A, FakeJellyfin, FakeTransport
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-videos")
FILM = "aaaa0000000000000000000000000001"          # resume_member_a.json: has BackdropImageTags
NO_BACKDROP = "aaaa0000000000000000000000000002"   # the episode: no backdrop of its own, no parent's


class Backdrop(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeJellyfin(self.clock)
        self.adapter = JellyfinAdapter(FakeTransport(self.fake), clock=self.clock)
        self.a = make_principal("member-a", GROUPS)
        self.b = make_principal("member-b", GROUPS)

    def parse(self, raw):
        item, _ = self.adapter._parse_item(raw, A, ("Movie", "Series", "Episode"), want_progress=False,
                                           require_progress=False)
        return item

    def test_continue_items_carry_the_backdrop_ref_and_ask_for_it(self):
        items = {i.id: i for i in self.adapter.continue_items(self.a).items}
        self.assertEqual(f"jellyfin/backdrop/{FILM}", items[f"jellyfin:{FILM}"].backdrop.ref)
        self.assertIsNone(items[f"jellyfin:{NO_BACKDROP}"].backdrop)
        self.assertEqual(f"jellyfin/backdrop/{FILM}", items[f"jellyfin:{FILM}"].to_dict()["backdrop"]["ref"])
        self.assertNotIn("backdrop", items[f"jellyfin:{NO_BACKDROP}"].to_dict())
        resume = [q for _, p, q in self.fake.requests if p == "/UserItems/Resume"]
        self.assertEqual("Primary,Backdrop,Logo", resume[0]["enableImageTypes"])

    def test_every_list_that_can_hold_an_episode_asks_for_logo_so_jellyfin_sends_the_series_backdrop(self):
        # Live 2026-10-29: with "Primary,Backdrop" alone, Jellyfin 10.11 sent no ParentBackdrop* for any episode, so
        # an episode's hero fell back to its still or poster. Asking for Logo too makes it walk up to the series.
        self.adapter.continue_items(self.a)
        self.adapter.recent_items(self.a)
        self.adapter.next_up_items(self.a)
        self.adapter.fetch_artwork(self.a, f"jellyfin/backdrop/{FILM}")
        asked = {p: q["enableImageTypes"] for _, p, q in self.fake.requests if "enableImageTypes" in q}
        self.assertTrue({"/UserItems/Resume", "/Shows/NextUp", "/Items"} <= set(asked), asked)
        for path, kinds in asked.items():
            self.assertIn("Logo", kinds.split(","), path)

    def test_an_episode_uses_its_series_backdrop_and_bad_values_give_none(self):
        series = "abcd0000000000000000000000000099"
        ep = {"Id": "abcd0000000000000000000000000098", "Name": "Ep", "Type": "Episode", "SeriesName": "S",
              "ParentBackdropItemId": "abcd0000-0000-0000-0000-000000000099", "ParentBackdropImageTags": ["t"]}
        self.assertEqual(f"jellyfin/backdrop/{series}", self.parse(ep).backdrop.ref)
        for bad in ({"ParentBackdropItemId": "../../Users/x", "ParentBackdropImageTags": ["t"]},
                    {"ParentBackdropItemId": series, "ParentBackdropImageTags": []},
                    {"ParentBackdropItemId": series, "ParentBackdropImageTags": "t"},
                    {"BackdropImageTags": [""]}, {"BackdropImageTags": [3]}):
            raw = {"Id": "abcd0000000000000000000000000098", "Name": "Ep", "Type": "Episode", **bad}
            self.assertIsNone(self.parse(raw).backdrop, bad)
        movie = {"Id": "abcd0000000000000000000000000097", "Name": "M", "Type": "Movie",
                 "ParentBackdropItemId": series, "ParentBackdropImageTags": ["t"]}
        self.assertIsNone(self.parse(movie).backdrop)      # only an episode borrows a parent's

    def test_fetch_checks_this_members_visibility_first_then_asks_for_the_wide_image(self):
        r = self.adapter.fetch_artwork(self.a, f"jellyfin/backdrop/{FILM}")
        self.assertIs(r.state, SectionState.OK)
        images = [(p, q) for _, p, q in self.fake.requests if "/Images/" in p]
        self.assertEqual([(f"/Items/{FILM}/Images/Backdrop", {"maxWidth": "1280", "quality": "80"})], images)

    def test_another_member_or_an_item_without_one_gets_nothing_and_no_image_request(self):
        for who, ref in ((self.b, f"jellyfin/backdrop/{FILM}"), (self.a, f"jellyfin/backdrop/{NO_BACKDROP}"),
                         (self.a, "jellyfin/backdrop/" + "a" * 31 + "Z")):
            self.fake.requests.clear()
            self.assertIs(self.adapter.fetch_artwork(who, ref).state, SectionState.EMPTY, ref)
            self.assertFalse([p for _, p, _ in self.fake.requests if "/Images/" in p], ref)

    def test_continue_shows_an_episodes_series_poster_and_other_sections_keep_the_still(self):
        series = "aaaa0000000000000000000000000011"          # latest_member_a.json: visible to member-a, has a poster
        ep = next(i for i in self.adapter.continue_items(self.a).items if i.kind.value == "episode")
        self.assertEqual((f"jellyfin/primary/{series}", "poster"), (ep.artwork.ref, ep.artwork.shape))
        self.assertEqual({"ref": f"jellyfin/primary/{series}", "alt": "Poster for Synthetic Series Alpha",
                          "shape": "poster"}, ep.to_dict()["artwork"])
        raw = {"Id": "abcd0000000000000000000000000098", "Name": "Ep", "Type": "Episode", "SeriesName": "S",
               "ImageTags": {"Primary": "t"}, "SeriesId": series, "SeriesPrimaryImageTag": "t"}
        own = self.parse(raw).artwork                         # Up next, Recently added, search: the episode's still
        self.assertEqual(("jellyfin/primary/abcd0000000000000000000000000098", None), (own.ref, own.shape))
        self.assertNotIn("shape", own.to_dict())

    def test_a_missing_or_bad_series_poster_keeps_the_still(self):
        series = "aaaa0000000000000000000000000011"
        base = {"Id": "abcd0000000000000000000000000098", "Name": "Ep", "Type": "Episode", "SeriesName": "S",
                "ImageTags": {"Primary": "t"}}
        for bad in ({"SeriesId": series}, {"SeriesId": series, "SeriesPrimaryImageTag": ""},
                    {"SeriesId": series, "SeriesPrimaryImageTag": 3}, {"SeriesId": "../../Users/x",
                                                                       "SeriesPrimaryImageTag": "t"}):
            item, _ = self.adapter._parse_item({**base, **bad}, A, ("Episode",), want_progress=False,
                                               require_progress=False, series_poster=True)
            self.assertEqual("jellyfin/primary/abcd0000000000000000000000000098", item.artwork.ref, bad)
        movie = {"Id": "abcd0000000000000000000000000097", "Name": "M", "Type": "Movie", "ImageTags": {"Primary": "t"},
                 "SeriesId": series, "SeriesPrimaryImageTag": "t"}
        item, _ = self.adapter._parse_item(movie, A, ("Movie",), want_progress=False, require_progress=False,
                                           series_poster=True)
        self.assertEqual("jellyfin/primary/abcd0000000000000000000000000097", item.artwork.ref)   # only episodes

    def test_the_series_poster_is_fetched_only_after_this_members_check_of_the_series(self):
        ref = "jellyfin/primary/aaaa0000000000000000000000000011"
        self.assertIs(self.adapter.fetch_artwork(self.a, ref).state, SectionState.OK)
        images = [p for _, p, _ in self.fake.requests if "/Images/" in p]
        self.assertEqual(["/Items/aaaa0000000000000000000000000011/Images/Primary"], images)
        self.fake.requests.clear()
        self.assertIs(self.adapter.fetch_artwork(self.b, ref).state, SectionState.EMPTY)
        self.assertFalse([p for _, p, _ in self.fake.requests if "/Images/" in p])

    def test_search_results_never_carry_a_backdrop(self):
        found = self.adapter.search(self.a, "Synthetic Film", 10).items
        self.assertTrue(found)
        self.assertTrue(all(i.backdrop is None for i in found))

    def test_the_allow_list_takes_only_primary_and_backdrop_images(self):
        for kind in ("Primary", "Backdrop"):
            check_request("GET", f"/Items/{FILM}/Images/{kind}", {"maxWidth": "400"}, A)
        for kind in ("Logo", "Backdrop/1", "Thumb"):
            with self.assertRaises(ForbiddenRequest):
                check_request("GET", f"/Items/{FILM}/Images/{kind}", {}, A)


if __name__ == "__main__":
    unittest.main()
