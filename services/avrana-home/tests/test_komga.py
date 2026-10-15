"""Komga adapter: one section ("Recently added"), proven against HAND-WRITTEN fixtures that are unverified
against any real server. Offline, synthetic data only. Live compatibility is UNPROVEN."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import json
import logging
import unittest

from avrana_home.adapters.komga import ALLOWED_ROUTES, GuardedTransport, KomgaAdapter, link_table_linker
from avrana_home.contract import ForbiddenRequest, Kind, SectionState
from avrana_home.resilience import MAX_IMAGE_BYTES, MAX_JSON_BYTES, FakeClock, UrllibTransport
from tests.fake_jellyfin import FakeOpener, FakeTransport
from tests.fake_komga import FIXTURES, PNG, UA, UB, UC, UD, FakeKomga
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-comics")
TOKEN = "SENTINEL-KOMGA-KEY-0000"
LINKS = {"member-a": UA, "member-b": UB, "member-c": UC, "member-d": UD}
MANGA, COMIC2, COMIC1 = "Synthetic Manga One", "Synthetic Comic Two", "Synthetic Comic One"
MATURE, KIDS, TEEN = "Synthetic Mature One", "Synthetic Kids One", "Synthetic Teen One"


def titles(result):
    return [i.title for i in result.items]


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeKomga(self.clock)
        self.transport = FakeTransport(self.fake)
        self.adapter = KomgaAdapter(self.transport, clock=self.clock, linker=link_table_linker(LINKS))
        self.a, self.b, self.c, self.d = (make_principal(f"member-{x}", GROUPS) for x in "abcd")

    def edit_user(self, uid, **changes):
        users = self.fake.copy_of(self.fake.users)
        for u in users:
            if u["id"] == uid:
                u.update(changes)
        self.fake.serve("/api/v2/users", users)

    def reset(self):
        self.fake.overrides.clear()
        self.fake.requests.clear()
        self.adapter.cache.clear()
        self.adapter.breaker.success(self.adapter.breaker.acquire())


class Restrictions(Base):
    """Four members with different access, one admin key that sees everything."""

    def test_each_member_sees_exactly_what_their_own_restrictions_allow_newest_first(self):
        self.assertEqual(titles(self.adapter.recent_items(self.a)), [TEEN, MATURE, COMIC2, COMIC1])   # library 1 only
        self.assertEqual(titles(self.adapter.recent_items(self.b)), [MANGA, COMIC2, COMIC1])          # age <= 12, no "adult"
        self.assertEqual(titles(self.adapter.recent_items(self.c)), [KIDS])                           # label allow list
        self.assertEqual(titles(self.adapter.recent_items(self.d)), [KIDS, MANGA, COMIC2, COMIC1])    # exclude age >= 16

    def test_the_item_shape_and_the_handoff_url_come_from_the_contract(self):
        r = self.adapter.recent_items(self.b)
        one = r.items[-1]
        self.assertIs(one.kind, Kind.COMIC)
        self.assertEqual(one.id, "komga:BOOKAAAA0001")
        self.assertEqual(one.handoff_url, "https://read.avrana.net/book/BOOKAAAA0001")
        self.assertEqual((one.subtitle, one.series), ("#1", "Synthetic 001"))
        self.assertEqual(one.artwork.ref, "komga/book/BOOKAAAA0001")
        self.assertIsNone(one.progress_fraction)
        self.assertNotIn("77", json.dumps(r.to_dict()))        # the service account's read page is never shown

    def test_item_lookup_applies_the_same_restrictions(self):
        self.assertEqual(titles(self.adapter.item(self.b, "BOOKAAAA0001")), [COMIC1])
        for hidden in ("BOOKCCCC0004", "BOOKDDDD0005", "BOOKEEEE0006"):     # b: too old, unrated, too old
            r = self.adapter.item(self.b, hidden)
            self.assertEqual((r.state, r.items), (SectionState.EMPTY, ()), hidden)
        self.assertEqual(titles(self.adapter.item(self.c, "BOOKDDDD0005")), [KIDS])
        self.assertEqual(self.adapter.item(self.a, "BOOKBBBB0003").items, ())    # a: library 2 is not shared

    def test_labels_compare_case_insensitively_and_exclude_wins(self):
        self.edit_user(UC, labelsAllow=["KIDS"], labelsExclude=["kids"])
        self.assertEqual(self.adapter.recent_items(self.c).state, SectionState.EMPTY)

    def test_unrated_content_is_not_allowed_under_an_allow_only_age_rule(self):
        self.assertNotIn(KIDS, titles(self.adapter.recent_items(self.b)))      # age None, rule ALLOW_ONLY 12

    def test_every_rule_must_pass_it_is_stricter_than_any_one_rule(self):
        self.edit_user(UB, labelsAllow=["kids"])                               # age rule AND label allow rule
        self.assertEqual(self.adapter.recent_items(self.b).items, ())

    def test_missing_or_wrongly_typed_restriction_fields_make_the_section_unavailable_not_unfiltered(self):
        for change in ({"sharedAllLibraries": "yes"}, {"sharedAllLibraries": None},
                       {"ageRestriction": {"age": "12", "restriction": "ALLOW_ONLY"}},
                       {"ageRestriction": {"age": 12, "restriction": "SOMETIMES"}}, {"ageRestriction": 12},
                       {"labelsAllow": "kids"}, {"labelsExclude": [1]}, {"labelsAllow": None}):
            self.reset()
            self.edit_user(UB, **change)
            r = self.adapter.recent_items(self.b)
            self.assertEqual((r.state, r.items), (SectionState.UNAVAILABLE, ()), change)
            self.assertEqual([p for p in self.fake.paths() if "/books/" in p or "/series/" in p], [], change)
        self.reset()
        self.edit_user(UA, sharedAllLibraries=False, sharedLibrariesIds="LIBCOMICS1")
        self.assertIs(self.adapter.recent_items(self.a).state, SectionState.UNAVAILABLE)

    def test_a_book_in_a_series_that_cannot_be_checked_is_never_shown(self):
        bad = self.fake.copy_of(self.fake.series["SERIESAAA001"])
        bad["metadata"]["sharingLabels"] = None
        self.fake.serve("/api/v1/series/SERIESAAA001", bad)
        r = self.adapter.recent_items(self.b)                  # the books that could be checked are still shown
        self.assertEqual(titles(r), [MANGA])

    def test_if_no_book_can_be_checked_the_section_is_drift_never_an_unfiltered_list(self):
        for sid in self.fake.series:
            bad = self.fake.copy_of(self.fake.series[sid])
            bad["metadata"]["ageRating"] = "adult"
            self.fake.serve(f"/api/v1/series/{sid}", bad)
        r = self.adapter.recent_items(self.d)
        self.assertEqual((r.state, r.items), (SectionState.UNAVAILABLE, ()))

    def test_a_series_that_answers_with_another_series_or_library_is_misbehaviour(self):
        self.fake.serve("/api/v1/series/SERIESAAA001", self.fake.copy_of(self.fake.series["SERIESBBB002"]))
        self.assertEqual(self.adapter.recent_items(self.b).reason, "UpstreamMisbehaved")
        self.reset()
        wrong_lib = self.fake.copy_of(self.fake.series["SERIESAAA001"])
        wrong_lib["libraryId"] = "LIBMANGA02"
        self.fake.serve("/api/v1/series/SERIESAAA001", wrong_lib)
        self.assertEqual(self.adapter.recent_items(self.b).reason, "UpstreamMisbehaved")

    def test_deleted_unreadable_and_vanished_books_are_left_out_neutrally(self):
        for bid, change in (("BOOKAAAA0001", {"deleted": True}), ("BOOKAAAA0002", {"media": {"status": "ERROR"}})):
            self.fake.latest["content"] = [dict(b, **change) if b["id"] == bid else b
                                           for b in self.fake.latest["content"]]
        self.assertEqual(titles(self.adapter.recent_items(self.b)), [MANGA])
        self.reset()
        self.fake.overrides["/api/v1/series/SERIESBBB002"] = ("status", 404)
        self.fake.latest["content"] = [b for b in self.fake.latest["content"] if b["seriesId"] == "SERIESBBB002"]
        self.assertEqual(self.adapter.recent_items(self.b).state, SectionState.EMPTY)
        self.assertEqual(self.adapter.health().state, "ok")                    # an item-class 404 never counts

    def test_the_series_lookups_and_the_page_are_bounded(self):
        self.adapter.recent_items(self.d, limit=2)
        latest = [q for _, p, q in self.fake.requests if p == "/api/v1/books/latest"]
        self.assertEqual(latest, [{"page": "0", "size": "6"}])
        self.assertLessEqual(len([p for p in self.fake.paths() if "/series/" in p]), 12)

    def test_a_page_larger_than_asked_is_misbehaviour(self):
        page = self.fake.copy_of(self.fake.latest)
        page["content"] = page["content"] * 5                  # 30 entries for a size of 3
        self.fake.serve("/api/v1/books/latest", page)
        self.assertEqual(self.adapter.recent_items(self.b, limit=1).reason, "UpstreamMisbehaved")


class States(Base):
    def test_continue_is_not_offered_and_makes_no_upstream_call(self):
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.EMPTY, "not_offered"))
        self.assertEqual(self.fake.requests, [])

    def test_empty_when_the_member_may_see_nothing_new(self):
        self.edit_user(UA, sharedLibrariesIds=["LIBNOTHING"])
        r = self.adapter.recent_items(self.a)
        self.assertEqual((r.state, r.items), (SectionState.EMPTY, ()))

    def test_unmapped_members_are_not_linked_and_a_link_to_a_vanished_account_too(self):
        r = self.adapter.recent_items(make_principal("member-zzz", GROUPS))
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "unmapped"))
        gone = KomgaAdapter(self.transport, clock=self.clock, linker=link_table_linker({"member-a": "USERGONE0001"}))
        self.assertEqual(gone.recent_items(self.a).state, SectionState.NOT_LINKED)

    def test_the_cache_is_per_member_and_serves_without_a_second_call(self):
        self.adapter.recent_items(self.a)
        self.adapter.recent_items(self.b)
        n = len(self.fake.requests)
        self.assertEqual(titles(self.adapter.recent_items(self.a))[0], TEEN)
        self.assertEqual(titles(self.adapter.recent_items(self.b))[0], MANGA)
        self.assertEqual(len(self.fake.requests), n)


class MappingSeam(Base):
    """OWNER DECISION (contract 11.2 / 12.2): who a Komga member is has no final answer yet."""

    def test_the_default_linker_is_the_exact_rule_on_the_login_and_links_nobody_with_realistic_emails(self):
        r = KomgaAdapter(self.transport, clock=self.clock).recent_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "unmapped"))

    def test_the_default_linker_links_only_an_exact_match_and_never_a_loose_one(self):
        self.edit_user(UA, email="member-a")
        self.assertIs(KomgaAdapter(self.transport, clock=self.clock).recent_items(self.a).state, SectionState.OK)
        self.edit_user(UA, email="Member-A")
        r = KomgaAdapter(self.transport, clock=self.clock).recent_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "case_or_unicode_mismatch"))

    def test_the_principals_display_email_never_decides(self):
        p = make_principal("member-zzz", GROUPS)
        self.assertEqual(KomgaAdapter(self.transport, clock=self.clock).recent_items(p).reason, "unmapped")

    def test_the_link_table_refuses_duplicates_malformed_ids_and_ambiguous_upstream_lists(self):
        with self.assertRaises(ValueError):
            link_table_linker({"x": UA, "y": UA})
        with self.assertRaises(ValueError):
            link_table_linker({"x": "../etc"})
        twin = self.fake.copy_of(self.fake.users)
        twin.append(dict(twin[0]))
        self.fake.serve("/api/v2/users", twin)
        self.assertEqual(self.adapter.recent_items(self.a).reason, "unmapped")


class Isolation(Base):
    def test_two_members_never_see_each_others_books_in_either_order(self):
        for first, second in ((self.a, self.c), (self.c, self.a)):
            self.adapter.cache.clear()
            r1, r2 = self.adapter.recent_items(first), self.adapter.recent_items(second)
            self.assertEqual(set(titles(r1)) & set(titles(r2)), set())
        self.assertEqual(titles(self.adapter.recent_items(self.c)), [KIDS])

    def test_the_admin_key_is_never_the_members_view(self):
        shown = set()
        for p in (self.a, self.b, self.c, self.d):
            r = self.adapter.recent_items(p)
            self.assertLess(len(r.items), 6)
            shown |= set(titles(r))
        self.assertEqual(len(shown), 6)                        # the six exist; no single member gets them all

    def test_a_user_record_with_a_different_id_is_never_used_for_the_member(self):
        users = self.fake.copy_of(self.fake.users)
        users[0]["id"] = "USERZZZZZZZZ9"                       # member-a's record no longer carries the linked id
        self.fake.serve("/api/v2/users", users)
        self.assertEqual(self.adapter.recent_items(self.a).state, SectionState.NOT_LINKED)

    def test_the_members_record_is_read_before_any_book_is_requested(self):
        self.adapter.recent_items(self.b)
        paths = self.fake.paths()
        self.assertEqual(paths[:2], ["/api/v2/users", "/api/v2/users"])        # mapping, then the restrictions
        self.assertTrue(all(p.startswith("/api/v1/") for p in paths[2:]))


class NoGroup(Base):
    def test_a_member_without_the_group_causes_no_upstream_call_and_leaks_nothing(self):
        outsider = make_principal("member-b", ("avrana-users", "avrana-videos"))
        for r in (self.adapter.recent_items(outsider), self.adapter.continue_items(outsider),
                  self.adapter.item(outsider, "BOOKBBBB0003")):
            self.assertEqual((r.state, r.items), (SectionState.NOT_PERMITTED, ()))
            self.assertNotIn("Manga", repr(r.to_dict()))
        self.assertIs(self.adapter.fetch_artwork(outsider, "komga/book/BOOKBBBB0003").state,
                      SectionState.NOT_PERMITTED)
        self.assertIsNone(self.adapter.resolve_user(outsider))
        self.assertEqual(self.fake.requests, [])
        self.adapter.recent_items(self.b)                      # a warm cache for the same name is not served either
        n = len(self.fake.requests)
        self.assertIs(self.adapter.recent_items(outsider).state, SectionState.NOT_PERMITTED)
        self.assertEqual(len(self.fake.requests), n)


class Artwork(Base):
    def test_a_member_gets_the_cover_of_a_book_they_may_see(self):
        r = self.adapter.fetch_artwork(self.b, "komga/book/BOOKAAAA0001")
        self.assertEqual((r.state, r.content_type, r.data), (SectionState.OK, "image/png", PNG))

    def test_a_cover_the_member_may_not_see_is_never_fetched(self):
        # b may not see the mature, the unrated kids or the 16+ book; a may not see the manga; c only kids
        for who, ref in ((self.b, "BOOKCCCC0004"), (self.b, "BOOKDDDD0005"), (self.b, "BOOKEEEE0006"),
                         (self.a, "BOOKBBBB0003"), (self.c, "BOOKAAAA0001")):
            self.fake.requests.clear()
            r = self.adapter.fetch_artwork(who, f"komga/book/{ref}")
            self.assertEqual((r.state, r.content_type, r.data), (SectionState.EMPTY, None, b""), ref)
            self.assertFalse([p for p in self.fake.paths() if p.endswith("/thumbnail")], ref)

    def test_hostile_or_unknown_refs_are_empty_and_never_interpolated(self):
        for ref in ("komga/book/latest", "komga/book/../users", "komga/book/BOOK", "jellyfin/primary/x",
                    "komga/book/BOOKAAAA0001/thumbnail", "komga/book/BOOKAAAA0001?x=1",
                    "komga/series/SERIESAAA001"):
            self.assertEqual(self.adapter.fetch_artwork(self.a, ref).state, SectionState.EMPTY, ref)
        self.assertFalse([p for p in self.fake.paths() if "thumbnail" in p])

    def test_reserved_sub_routes_are_never_requested_as_book_ids(self):
        """Komga sub-routes that look like ids (review of #37 named ondeck) never reach upstream."""
        for word in ("latest", "updated", "ondeck"):
            self.fake.requests.clear()
            self.assertNotEqual(self.adapter.item(self.b, word).state, SectionState.OK, word)
            self.assertEqual(self.adapter.fetch_artwork(self.b, f"komga/book/{word}").state, SectionState.EMPTY, word)
            self.assertFalse([p for p in self.fake.paths() if p.startswith(f"/api/v1/books/{word}")], word)

    def test_missing_thumbnails_and_bad_images_are_graceful(self):
        self.fake.overrides["/api/v1/books/BOOKAAAA0001/thumbnail"] = ("status", 404)
        self.assertEqual(self.adapter.fetch_artwork(self.b, "komga/book/BOOKAAAA0001").state, SectionState.EMPTY)
        self.assertEqual(self.adapter.health().state, "ok")
        for image in ((200, b"<html>", "text/html"), (200, b"not a png", "image/png"),
                      (200, PNG + b"x" * (MAX_IMAGE_BYTES + 1), "image/png")):
            self.reset()
            self.fake.image = image
            self.assertEqual(self.adapter.fetch_artwork(self.b, "komga/book/BOOKAAAA0001").state,
                             SectionState.UNAVAILABLE, image[2])

    def test_a_cached_cover_is_not_shared_with_another_member(self):
        self.assertEqual(self.adapter.fetch_artwork(self.a, "komga/book/BOOKCCCC0004").state, SectionState.OK)
        self.fake.requests.clear()
        r = self.adapter.fetch_artwork(self.b, "komga/book/BOOKCCCC0004")   # b may not see it; a's cache must not help
        self.assertEqual(r.state, SectionState.EMPTY)
        self.assertFalse([p for p in self.fake.paths() if p.endswith("/thumbnail")])


class Failures(Base):
    def test_unreachable_costs_the_section_only_and_never_raises(self):
        for exc in (ConnectionRefusedError("refused"), OSError("unreachable"), TimeoutError()):
            self.reset()
            self.fake.overrides["/api/v2/users"] = ("raise", exc)
            r = self.adapter.recent_items(self.a)
            self.assertEqual((r.state, r.items), (SectionState.UNAVAILABLE, ()), exc)

    def test_a_timeout_costs_the_section_only_and_a_warm_cache_still_serves(self):
        self.adapter.recent_items(self.a)
        self.fake.slow["/api/v2/users"] = 5.0
        self.assertEqual(self.adapter.recent_items(self.a).state, SectionState.OK)       # cache hit
        self.assertEqual(self.adapter.recent_items(self.b).reason, "UpstreamTimeout")

    def test_401_403_and_404_on_each_route_are_unavailable(self):
        for path, code in (("/api/v2/users", 401), ("/api/v2/users", 403), ("/api/v2/users", 404),
                           ("/api/v1/books/latest", 401), ("/api/v1/books/latest", 403),
                           ("/api/v1/books/latest", 404), ("/api/v1/series/SERIESAAA001", 403)):
            self.reset()
            self.fake.overrides[path] = ("status", code)
            self.assertIs(self.adapter.recent_items(self.a).state, SectionState.UNAVAILABLE, (path, code))

    def test_malformed_bodies_are_unavailable_not_exceptions(self):
        for path in ("/api/v2/users", "/api/v1/books/latest"):
            for body in (b"[" * 100000, b'{"id": 5}', b"not json", b"\xff\xfe", b"null", b"{}", b'"x"'):
                self.reset()
                self.fake.overrides[path] = ("body", body)
                self.assertIs(self.adapter.recent_items(self.b).state, SectionState.UNAVAILABLE, (path, body[:12]))
        self.reset()                                           # every book unusable: drift, never "nothing new"
        page = self.fake.copy_of(self.fake.latest)
        page["content"] = [{"id": 5}, "x", None]
        self.fake.serve("/api/v1/books/latest", page)
        self.assertIs(self.adapter.recent_items(self.b).state, SectionState.UNAVAILABLE)

    def test_an_oversized_body_is_unavailable_and_counted(self):
        self.fake.overrides["/api/v1/books/latest"] = ("body", b" " * (MAX_JSON_BYTES + 1))
        r = self.adapter.recent_items(self.b)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamTooLarge"))
        self.assertEqual(self.adapter.health().state, "failing")

    def test_a_breaker_trip_stops_all_traffic_for_every_member_until_the_cool_off(self):
        self.fake.overrides["/api/v2/users"] = ("raise", ConnectionRefusedError())
        for p in (self.a, self.b, self.c):
            self.adapter.recent_items(p)
        self.assertEqual(self.adapter.health().state, "cooling_off")
        n = len(self.fake.requests)
        self.assertEqual(self.adapter.recent_items(self.d).reason, "cooling_off")
        self.assertEqual(len(self.fake.requests), n)
        self.fake.overrides.clear()
        self.clock.advance(61)
        self.assertIs(self.adapter.recent_items(self.d).state, SectionState.OK)          # the trial succeeds

    def test_a_404_on_the_latest_route_is_route_drift_and_opens_the_circuit_after_three(self):
        self.fake.overrides["/api/v1/books/latest"] = ("status", 404)
        reasons = [self.adapter.recent_items(p).reason for p in (self.a, self.b, self.c)]
        self.assertEqual(reasons, ["RouteMissing"] * 3)
        self.assertEqual(self.adapter.health().state, "cooling_off")


class GuardAndSecrets(Base):
    def test_only_get_on_listed_routes_and_no_query_keys_beyond_the_list(self):
        g = GuardedTransport(self.transport).bind(UA)
        for method, path, query in (("POST", "/api/v2/users", None), ("DELETE", "/api/v1/books/BOOKAAAA0001", None),
                                    ("GET", "/api/v2/users/me", None), ("GET", "/api/v1/readlists", None),
                                    ("GET", "/api/v1/collections", None),
                                    ("GET", "/api/v1/books/BOOKAAAA0001/pages/1", None),
                                    ("GET", "/api/v1/books/BOOKAAAA0001/file", None),
                                    ("GET", "/api/v1/series/latest/x", None), ("GET", "/api/v1/books/%2e%2e", None),
                                    ("GET", "/api/v1/books/latest", {"unpaged": "true"}),
                                    ("GET", "/api/v1/books/BOOKAAAA0001", {"anything": "1"})):
            with self.assertRaises(ForbiddenRequest, msg=(method, path)):
                g.request(method, path, query, 1.0, 1000)
        self.assertEqual(self.fake.requests, [])

    def test_member_routes_need_a_mapped_member_and_reserved_words_are_never_ids(self):
        with self.assertRaises(ForbiddenRequest):
            GuardedTransport(self.transport).bind(None).request("GET", "/api/v1/books/latest", None, 1.0, 1000)
        with self.assertRaises(ForbiddenRequest):
            GuardedTransport(self.transport).bind("../x")
        self.assertEqual([r.name for r in ALLOWED_ROUTES], ["users", "latest", "book", "series", "thumbnail"])
        for word in ("latest", "updated"):
            self.assertEqual(self.adapter.item(self.a, word).items, ())
            self.assertEqual(self.adapter.fetch_artwork(self.a, f"komga/book/{word}").state, SectionState.EMPTY)
        self.assertEqual([p for p in self.fake.paths() if "latest" in p or "updated" in p], [])

    def test_the_credential_is_never_in_a_repr_a_result_a_health_report_or_a_log_line(self):
        opener = FakeOpener(self.fake)
        transport = UrllibTransport("https://komga.invalid", {"X-API-Key": TOKEN}, opener=opener)
        ad = KomgaAdapter(transport, clock=self.clock, linker=link_table_linker(LINKS))
        with self.assertLogs("avrana_home", level=logging.WARNING) as logs:
            logging.getLogger("avrana_home").warning("probe")
            ok = ad.recent_items(self.b)
            self.fake.overrides["/api/v1/books/latest"] = ("status", 401)
            ad.cache.clear()
            bad = ad.recent_items(self.b)
        blob = " ".join([repr(ad), repr(ok), repr(bad), repr(ad.health()), repr(ad._guard),
                         json.dumps(ok.to_dict()), *logs.output])
        self.assertNotIn(TOKEN, blob)
        self.assertTrue(opener.seen_headers)                   # requests went out through the transport

    def test_logs_carry_no_username_title_or_id(self):
        self.fake.overrides["/api/v1/books/latest"] = ("status", 500)
        with self.assertLogs("avrana_home", level=logging.WARNING) as logs:
            self.adapter.recent_items(self.b)
        text = " ".join(logs.output)
        for secret in ("member-b", "Synthetic", UB, "BOOK", "SERIES"):
            self.assertNotIn(secret, text)

    def test_fixtures_declare_their_target_version_and_which_shapes_are_synthetic(self):
        files = sorted(FIXTURES.glob("*.json"))
        self.assertEqual(len(files), 4)
        for f in files:
            doc = json.loads(f.read_text(encoding="utf-8"))
            self.assertIn("Komga", doc["_target_version"], f.name)
            self.assertIn("NOT confirmed", doc["_target_version"], f.name)
            self.assertIn("SYNTHETIC assumption", doc["_provenance"], f.name)
            self.assertIn("UNPROVEN", doc["_provenance"], f.name)


if __name__ == "__main__":
    unittest.main()
