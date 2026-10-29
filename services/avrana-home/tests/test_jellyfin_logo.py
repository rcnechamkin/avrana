"""Jellyfin title logos for Home's hero (H3 refined, owner decision 2026-10-29): parsed from the item (an episode
borrows its series', ParentLogo*), fetched only after this member's visibility check of the item that owns the image,
never on search results. SYNTHETIC fixtures and the fake transport; no sockets."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import unittest
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.contract import SectionState
from avrana_home.resilience import FakeClock
from tests.fake_jellyfin import A, FakeJellyfin, FakeTransport
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-videos")
FILM = "aaaa0000000000000000000000000001"          # resume_member_a.json: has ImageTags.Logo
NO_LOGO = "aaaa0000000000000000000000000002"       # the episode: no logo of its own, no parent's
SERIES = "abcd0000000000000000000000000099"


class Logo(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeJellyfin(self.clock)
        self.adapter = JellyfinAdapter(FakeTransport(self.fake), clock=self.clock)
        self.a = make_principal("member-a", GROUPS)
        self.b = make_principal("member-b", GROUPS)

    def parse(self, raw, **kw):
        item, _ = self.adapter._parse_item(raw, A, ("Movie", "Series", "Episode"), want_progress=False,
                                           require_progress=False, **kw)
        return item

    def test_continue_items_carry_the_logo_ref_with_the_title_as_its_alt(self):
        items = {i.id: i for i in self.adapter.continue_items(self.a).items}
        film = items[f"jellyfin:{FILM}"]
        self.assertEqual({"ref": f"jellyfin/logo/{FILM}", "alt": film.title}, film.to_dict()["logo"])
        self.assertIsNone(items[f"jellyfin:{NO_LOGO}"].logo)
        self.assertNotIn("logo", items[f"jellyfin:{NO_LOGO}"].to_dict())

    def test_an_episode_uses_its_series_logo_named_for_the_series_and_bad_values_give_none(self):
        ep = {"Id": "abcd0000000000000000000000000098", "Name": "Ep", "Type": "Episode", "SeriesName": "Saga",
              "ParentLogoItemId": "abcd0000-0000-0000-0000-000000000099", "ParentLogoImageTag": "t"}
        self.assertEqual((f"jellyfin/logo/{SERIES}", "Saga"), (self.parse(ep).logo.ref, self.parse(ep).logo.alt))
        for bad in ({"ParentLogoItemId": "../../Users/x", "ParentLogoImageTag": "t"},
                    {"ParentLogoItemId": SERIES, "ParentLogoImageTag": ""},
                    {"ParentLogoItemId": SERIES, "ParentLogoImageTag": ["t"]},
                    {"ImageTags": {"Logo": ""}}, {"ImageTags": {"Logo": 3}}, {"ImageTags": "Logo"}):
            raw = {"Id": "abcd0000000000000000000000000098", "Name": "Ep", "Type": "Episode", **bad}
            self.assertIsNone(self.parse(raw).logo, bad)
        movie = {"Id": "abcd0000000000000000000000000097", "Name": "M", "Type": "Movie",
                 "ParentLogoItemId": SERIES, "ParentLogoImageTag": "t"}
        self.assertIsNone(self.parse(movie).logo)          # only an episode borrows a parent's
        own = dict(movie, ImageTags={"Logo": "t"})
        self.assertEqual("jellyfin/logo/abcd0000000000000000000000000097", self.parse(own).logo.ref)
        self.assertIsNone(self.parse(own, want_backdrop=False).logo)   # search results: no hero art at all

    def test_fetch_checks_this_members_visibility_first_then_asks_for_the_logo(self):
        r = self.adapter.fetch_artwork(self.a, f"jellyfin/logo/{FILM}")
        self.assertIs(r.state, SectionState.OK)
        images = [(p, q) for _, p, q in self.fake.requests if "/Images/" in p]
        self.assertEqual([(f"/Items/{FILM}/Images/Logo", {"maxWidth": "800", "quality": "90"})], images)

    def test_another_member_or_an_item_without_one_gets_nothing_and_no_image_request(self):
        for who, ref in ((self.b, f"jellyfin/logo/{FILM}"), (self.a, f"jellyfin/logo/{NO_LOGO}"),
                         (self.a, "jellyfin/logo/" + "a" * 31 + "Z")):
            self.fake.requests.clear()
            self.assertIs(self.adapter.fetch_artwork(who, ref).state, SectionState.EMPTY, ref)
            self.assertFalse([p for _, p, _ in self.fake.requests if "/Images/" in p], ref)

    def test_search_results_never_carry_a_logo(self):
        found = self.adapter.search(self.a, "Synthetic Film", 10).items
        self.assertTrue(found)
        self.assertTrue(all(i.logo is None for i in found))


if __name__ == "__main__":
    unittest.main()
