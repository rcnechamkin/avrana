"""Home 2.0, Lane D (AVR-375): artwork revocation, cache isolation, identity mapping edges and the sealed owner
override. Offline: synthetic fixtures behind fake transports, a fake clock, no sockets.

Findings addressed (see docs/design/IDENTITY-MAPPING.md and the PR body):
  * #53 LOW: a cached cover was served for up to ARTWORK_TTL after the member lost access to the item. Per-member
    services (Jellyfin, Audiobookshelf) now re-check visibility on EVERY request before the cache is consulted.
  * #50 LOWs: the cover cache is per member for the shared Komga view; losing the group gates item and artwork
    as well as the sections, with a warm cache and no upstream call.
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import dataclasses
import unittest

from avrana_home.adapters._base import match_exactly_one
from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.adapters.calibre_web import CalibreWebAdapter
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.adapters.komga import KomgaAdapter
from avrana_home.app import artwork
from avrana_home.contract import (ARTWORK_TTL, MAPPING_TTL_FOUND, AmbiguousMappingError, MappingFailed,
                                  SectionState)
from avrana_home.principal import PrincipalError, principal_from_raw_headers
from avrana_home.resilience import FakeClock
from tests.fake_abs import JPEG, UA, FakeAudiobookshelf
from tests.fake_calibre_web import FakeCalibreWeb
from tests.fake_jellyfin import A, PNG, FakeJellyfin, FakeTransport
from tests.fake_komga import FakeKomga
from tests.helpers import make_principal

VIDEOS = ("avrana-users", "avrana-videos")
LISTEN = ("avrana-users", "avrana-audiobooks")
COMICS = ("avrana-users", "avrana-comics")
BOOKS = ("avrana-users", "avrana-books")
NOTHING = ("avrana-users",)
A_FILM = "jellyfin/primary/aaaa0000000000000000000000000001"      # member-a's own film (has artwork)
A_FILM_ID = "aaaa0000000000000000000000000001"
A_BOOK = "audiobookshelf/cover/li_book000001"                    # member-a may see it (lib_aaa)
EMPTY_ITEMS = b'{"Items": [], "TotalRecordCount": 0}'


def image_calls(fake, suffix):
    return [p for _m, p, _q in fake.requests if p.endswith(suffix)]


# ---- 1. revocation: per-member services re-check visibility before any cached cover ----------------------
class JellyfinArtworkRevocation(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeJellyfin(self.clock)
        self.adapter = JellyfinAdapter(FakeTransport(self.fake), clock=self.clock)
        self.a = make_principal("member-a", VIDEOS)
        self.b = make_principal("member-b", VIDEOS)

    def test_visible_then_hidden_is_a_404_on_the_next_request_even_with_a_warm_cache(self):
        self.assertIs(self.adapter.fetch_artwork(self.a, A_FILM).state, SectionState.OK)
        self.assertIsNotNone(self.adapter.cache.for_member(self.a).get("jellyfin", "art:" + A_FILM))   # warm
        self.fake.overrides["/Items"] = ("body", EMPTY_ITEMS)       # the owner hides the item from member-a
        self.clock.advance(1)                                        # well inside ARTWORK_TTL
        self.assertIs(self.adapter.fetch_artwork(self.a, A_FILM).state, SectionState.EMPTY)
        self.assertIsNone(artwork.fetch(self.a, [self.adapter], A_FILM))     # the route's 404
        self.assertIsNone(self.adapter.cache.for_member(self.a).get("jellyfin", "art:" + A_FILM))  # dropped

    def test_a_warm_cover_is_served_after_a_fresh_visibility_check_without_refetching_the_bytes(self):
        self.adapter.fetch_artwork(self.a, A_FILM)
        n = len(self.fake.requests)
        r = self.adapter.fetch_artwork(self.a, A_FILM)
        self.assertEqual((r.state, r.data), (SectionState.OK, PNG))
        later = [p for _m, p, _q in self.fake.requests[n:]]
        self.assertEqual(later, ["/Items"])                         # the member-scoped check, then the cache

    def test_losing_the_group_is_a_404_with_a_warm_cache_and_no_upstream_call(self):
        self.adapter.fetch_artwork(self.a, A_FILM)
        n = len(self.fake.requests)
        lost = make_principal("member-a", NOTHING)
        self.assertIs(self.adapter.fetch_artwork(lost, A_FILM).state, SectionState.NOT_PERMITTED)
        self.assertIsNone(artwork.fetch(lost, [self.adapter], A_FILM))
        self.assertEqual(len(self.fake.requests), n)

    def test_a_second_member_never_gets_the_first_members_cached_cover(self):
        # make A's film visible to BOTH members (a shared item), so only the cache partition separates them
        real = self.fake._visible
        self.fake._visible = lambda uid: {**real(uid), A_FILM_ID: real(A.lower().replace("-", ""))[A_FILM_ID]}
        self.adapter.fetch_artwork(self.a, A_FILM)
        before = len(image_calls(self.fake, "/Images/Primary"))
        self.assertIsNone(self.adapter.cache.for_member(self.b).get("jellyfin", "art:" + A_FILM))
        self.assertIs(self.adapter.fetch_artwork(self.b, A_FILM).state, SectionState.OK)
        self.assertEqual(len(image_calls(self.fake, "/Images/Primary")), before + 1,
                         "member-b was served member-a's cached bytes")

    def test_an_unreachable_upstream_never_serves_a_cached_cover_and_recovers(self):
        self.adapter.fetch_artwork(self.a, A_FILM)
        self.fake.overrides["/Items"] = ("status", 500)
        for _ in range(3):                                          # opens the circuit (threshold 3)
            self.assertIs(self.adapter.fetch_artwork(self.a, A_FILM).state, SectionState.UNAVAILABLE)
        self.assertEqual(self.adapter.health().state, "cooling_off")
        self.fake.overrides.clear()
        self.assertIs(self.adapter.fetch_artwork(self.a, A_FILM).state, SectionState.UNAVAILABLE)  # cooling off
        self.clock.advance(120)
        self.assertIs(self.adapter.fetch_artwork(self.a, A_FILM).state, SectionState.OK)          # recovered
        self.assertEqual(self.adapter.health().state, "ok")

    def test_a_lost_mapping_is_never_served_from_a_warm_cover(self):
        self.adapter.fetch_artwork(self.a, A_FILM)
        self.fake.users = [u for u in self.fake.users if u["Name"] != "member-a"]
        self.clock.advance(MAPPING_TTL_FOUND + 1)
        self.assertIs(self.adapter.fetch_artwork(self.a, A_FILM).state, SectionState.NOT_LINKED)


class AudiobookshelfArtworkRevocation(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeAudiobookshelf(self.clock)
        self.adapter = AudiobookshelfAdapter(FakeTransport(self.fake), clock=self.clock)
        self.a = make_principal("member-a", LISTEN)

    def test_library_access_removed_is_a_404_on_the_next_request_even_with_a_warm_cache(self):
        self.assertIs(self.adapter.fetch_artwork(self.a, A_BOOK).state, SectionState.OK)
        rec = self.fake.record(UA)
        rec["librariesAccessible"] = []
        self.fake.serve(f"/api/users/{UA}", rec)
        self.clock.advance(1)
        self.assertIs(self.adapter.fetch_artwork(self.a, A_BOOK).state, SectionState.EMPTY)
        self.assertIsNone(artwork.fetch(self.a, [self.adapter], A_BOOK))

    def test_a_deactivated_member_gets_no_warm_cover(self):
        self.adapter.fetch_artwork(self.a, A_BOOK)
        rec = self.fake.record(UA)
        rec["isActive"] = False
        self.fake.serve(f"/api/users/{UA}", rec)
        self.assertIsNot(self.adapter.fetch_artwork(self.a, A_BOOK).state, SectionState.OK)

    def test_losing_the_group_is_a_404_with_a_warm_cache_and_no_upstream_call(self):
        r = self.adapter.fetch_artwork(self.a, A_BOOK)
        self.assertEqual(r.data, JPEG)
        n = len(self.fake.requests)
        self.assertIs(self.adapter.fetch_artwork(make_principal("member-a", NOTHING), A_BOOK).state,
                      SectionState.NOT_PERMITTED)
        self.assertEqual(len(self.fake.requests), n)


# ---- 2. shared views (Komga, Calibre-Web): group first, per-member cache, bounded TTL ---------------------
class SharedViewCovers(unittest.TestCase):
    def build(self, kind):
        clock = FakeClock()
        if kind == "komga":
            fake = FakeKomga(clock)
            adapter = KomgaAdapter(FakeTransport(fake), clock=clock, owner_confirms_no_member_restrictions=True)
            return clock, fake, adapter, COMICS, "komga/book/BOOKAAAA0001", "BOOKAAAA0001", "/thumbnail"
        fake = FakeCalibreWeb(clock)
        adapter = CalibreWebAdapter(FakeTransport(fake), clock=clock, owner_confirms_no_member_restrictions=True)
        return clock, fake, adapter, BOOKS, "calibre-web/cover/101", "101", "/opds/cover_240_240/101"

    def test_the_cover_cache_is_per_member(self):            # review of #50: re-added
        for kind in ("komga", "calibre-web"):
            with self.subTest(kind=kind):
                _clock, fake, adapter, groups, ref, _id, suffix = self.build(kind)
                a, b = make_principal("member-a", groups), make_principal("member-b", groups)
                self.assertIs(adapter.fetch_artwork(a, ref).state, SectionState.OK)
                n = len(image_calls(fake, suffix))
                self.assertIs(adapter.fetch_artwork(a, ref).state, SectionState.OK)     # a's own cache
                self.assertEqual(len(image_calls(fake, suffix)), n)
                self.assertIsNone(adapter.cache.for_member(b).get(adapter.service.value, "art:" + ref))
                self.assertIs(adapter.fetch_artwork(b, ref).state, SectionState.OK)
                self.assertEqual(len(image_calls(fake, suffix)), n + 1, "b was served a's cached cover")

    def test_losing_the_group_gates_sections_item_and_artwork_with_a_warm_cache(self):   # review of #50
        for kind in ("komga", "calibre-web"):
            with self.subTest(kind=kind):
                _clock, fake, adapter, groups, ref, item_id, _suffix = self.build(kind)
                a = make_principal("member-a", groups)
                adapter.recent_items(a)
                adapter.item(a, item_id)
                self.assertIs(adapter.fetch_artwork(a, ref).state, SectionState.OK)
                n = len(fake.requests)
                lost = make_principal("member-a", NOTHING)
                self.assertIs(adapter.recent_items(lost).state, SectionState.NOT_PERMITTED)
                self.assertIs(adapter.item(lost, item_id).state, SectionState.NOT_PERMITTED)
                self.assertIs(adapter.fetch_artwork(lost, ref).state, SectionState.NOT_PERMITTED)
                self.assertIsNone(artwork.fetch(lost, [adapter], ref))
                self.assertEqual(len(fake.requests), n)

    def test_a_shared_cover_outlives_removal_at_most_artwork_ttl(self):
        """The documented residual for a shared view: the one account's view is not re-checked per request."""
        clock, fake, adapter, groups, ref, _id, suffix = self.build("komga")
        a = make_principal("member-a", groups)
        adapter.fetch_artwork(a, ref)
        fake.overrides["/api/v1/books/BOOKAAAA0001/thumbnail"] = ("status", 404)
        clock.advance(ARTWORK_TTL - 1)
        self.assertIs(adapter.fetch_artwork(a, ref).state, SectionState.OK)
        clock.advance(2)
        self.assertIs(adapter.fetch_artwork(a, ref).state, SectionState.EMPTY)


# ---- 3. identity mapping edges (AVR-375) ------------------------------------------------------------------
def _extract(entry):
    return entry


class MatchExactlyOne(unittest.TestCase):
    CYRILLIC_O = "о"

    def test_exact_case_sensitive_only(self):
        self.assertEqual(match_exactly_one("cody", [("cody", "1")], _extract)[0], "1")
        with self.assertRaises(MappingFailed) as cm:
            match_exactly_one("cody", [("Cody", "1")], _extract)
        self.assertEqual(cm.exception.reason, "case_or_unicode_mismatch")

    def test_two_upstream_users_differing_only_by_case_are_ambiguous_for_either_name(self):
        users = [("Cody", "1"), ("cody", "2")]
        for wanted in ("cody", "Cody", "CODY"):
            with self.assertRaises((AmbiguousMappingError, MappingFailed), msg=wanted) as cm:
                match_exactly_one(wanted, users, _extract)
            if wanted != "CODY":
                self.assertIsInstance(cm.exception, AmbiguousMappingError, wanted)

    def test_a_fullwidth_nfkc_twin_makes_the_exact_name_ambiguous(self):
        with self.assertRaises(AmbiguousMappingError):
            match_exactly_one("Cody", [("Cody", "1"), ("Ｃｏｄｙ", "2")], _extract)

    def test_a_cyrillic_confusable_never_links_and_never_collides(self):
        lookalike = "C" + self.CYRILLIC_O + "dy"
        with self.assertRaises(MappingFailed) as cm:
            match_exactly_one("Cody", [(lookalike, "9")], _extract)
        self.assertEqual(cm.exception.reason, "unmapped")           # NFKC does not fold scripts together
        self.assertEqual(match_exactly_one("Cody", [("Cody", "1"), (lookalike, "9")], _extract)[0], "1")

    def test_a_confusable_principal_cannot_arrive_over_the_header_path(self):
        lookalike = ("C" + self.CYRILLIC_O + "dy").encode("utf-8")
        with self.assertRaises(PrincipalError):
            principal_from_raw_headers([(b"x-authentik-username", lookalike), (b"x-authentik-groups", b"g")])


class MappingLifetime(unittest.TestCase):
    """What a rename, a disabled account and a revoked group cost, in time, with the mapping cache warm."""

    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeJellyfin(self.clock)
        self.adapter = JellyfinAdapter(FakeTransport(self.fake), clock=self.clock)
        self.a = make_principal("member-a", VIDEOS)

    def rename(self, new):
        self.fake.users = [dict(u, Name=new) if u["Name"] == "member-a" else u for u in self.fake.users]

    def test_a_renamed_upstream_account_stops_linking_once_the_mapping_ttl_passes(self):
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.OK)
        self.rename("member-a-renamed")
        self.clock.advance(MAPPING_TTL_FOUND - 1)
        # bounded residual: inside the mapping TTL the cached upstream id still links (the fake serves that
        # id's data by its current name, so the section is empty, but it is not NOT_LINKED)
        self.assertIsNot(self.adapter.continue_items(self.a).state, SectionState.NOT_LINKED)
        self.clock.advance(31)                     # past the mapping TTL and the section's own 30 s cache
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "unmapped"))
        self.assertIs(self.adapter.fetch_artwork(self.a, A_FILM).state, SectionState.NOT_LINKED)

    def test_a_rename_to_a_case_variant_is_never_linked(self):
        self.rename("Member-A")
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "case_or_unicode_mismatch"))

    def test_a_disabled_upstream_account_stops_linking_once_the_mapping_ttl_passes(self):
        self.adapter.continue_items(self.a)
        self.fake.users = [dict(u, Policy={"IsDisabled": True}) if u["Name"] == "member-a" else u
                           for u in self.fake.users]
        self.clock.advance(MAPPING_TTL_FOUND + 1)
        r = self.adapter.recent_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "disabled"))

    def test_a_revoked_group_is_immediate_whatever_is_cached(self):
        self.adapter.continue_items(self.a)
        self.adapter.fetch_artwork(self.a, A_FILM)
        n = len(self.fake.requests)
        lost = make_principal("member-a", NOTHING)
        for r in (self.adapter.continue_items(lost), self.adapter.recent_items(lost),
                  self.adapter.item(lost, A_FILM_ID), self.adapter.search(lost, "Synthetic")):
            self.assertIs(r.state, SectionState.NOT_PERMITTED)
        self.assertIsNone(self.adapter.resolve_user(lost))
        self.assertEqual(len(self.fake.requests), n)


# ---- 3b. expired entries do not linger (AVR-503 benchmark F3) --------------------------------------------
class ExpiredEntriesAreSwept(unittest.TestCase):
    def setUp(self):
        from avrana_home.cache import MemberCache
        self.clock = FakeClock()
        self.cache = MemberCache(self.clock)
        self.a, self.b = make_principal("member-a", VIDEOS), make_principal("member-b", VIDEOS)

    def test_a_write_sweeps_another_members_expired_entries(self):
        from avrana_home.cache import SWEEP_INTERVAL
        scope_a = self.cache.for_member(self.a)
        for n in range(5):
            scope_a.set("jellyfin", f"item:{n}", "Synthetic Title", ttl=10, data_class="member_progress")
        scope_a.set("jellyfin", "art:x", b"synthetic-bytes", ttl=10, data_class="artwork")
        self.assertEqual(len(self.cache), 6)
        self.clock.advance(max(11, SWEEP_INTERVAL))
        self.cache.for_member(self.b).set("jellyfin", "continue:12", "other", ttl=30)
        self.assertEqual(len(self.cache), 1, "member-a's expired titles and bytes are still held in memory")
        self.assertIsNone(scope_a.get("jellyfin", "item:0"))

    def test_the_sweep_is_rate_limited_and_never_drops_live_entries(self):
        scope_a = self.cache.for_member(self.a)
        scope_a.set("jellyfin", "short", "x", ttl=5)
        scope_a.set("jellyfin", "long", "y", ttl=600)
        self.clock.advance(6)
        self.cache.for_member(self.b).set("jellyfin", "k", "z", ttl=600)  # within the interval: no sweep yet
        self.assertEqual(len(self.cache), 3)
        self.clock.advance(30)
        self.cache.for_member(self.b).set("jellyfin", "k2", "z", ttl=30)
        self.assertEqual(len(self.cache), 3)                              # short gone; long, k, k2 kept
        self.assertEqual(scope_a.get("jellyfin", "long"), "y")


# ---- 4. the owner override is reachable only through the sealed preview path ------------------------------
class SealedOverride(unittest.TestCase):
    def test_settings_cannot_be_constructed_into_the_preview_or_an_override(self):
        from avrana_home.app.settings import Settings, SettingsError
        for kw in ({"owner_preview": True}, {"owner_preview_username": "akadmin"},
                   {"jellyfin_member_username": "member-a"}, {"audiobookshelf_member_username": "member-a"},
                   {"owner_preview": True, "owner_preview_username": "akadmin",
                    "jellyfin_member_username": "member-a", "preview_seal": object()}):
            with self.subTest(kw=sorted(kw)):
                with self.assertRaises(SettingsError):
                    Settings(**kw)
                with self.assertRaises(SettingsError):
                    dataclasses.replace(Settings(), **kw)

    def test_the_sealed_path_still_works_and_an_unsealed_app_never_overrides(self):
        from avrana_home.app.main import _member_username
        from avrana_home.app.settings import _OWNER_PREVIEW_SEAL, Settings, SettingsError
        sealed = Settings(owner_preview=True, owner_preview_username="akadmin", jellyfin_member_username="member-a",
                          preview_seal=_OWNER_PREVIEW_SEAL)
        self.assertEqual(("akadmin", "member-a"), _member_username(sealed, sealed.jellyfin_member_username))
        self.assertIsNone(_member_username(Settings(), "member-a"))
        with self.assertRaises(SettingsError):                       # an override without the owner name
            Settings(owner_preview=True, jellyfin_member_username="member-a", preview_seal=_OWNER_PREVIEW_SEAL)


if __name__ == "__main__":
    unittest.main()
