"""Audiobookshelf adapter: one section ("Continue listening"), proven against HAND-WRITTEN fixtures that
are unverified against any real server. Offline, synthetic data only."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import json
import logging
import shutil
import tempfile
import threading
import unittest

from avrana_home.adapters.audiobookshelf import ALLOWED_ROUTES, AudiobookshelfAdapter, GuardedTransport
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.aggregate import gather
from avrana_home.cache import MemberCache
from avrana_home.contract import ForbiddenRequest, Kind, SectionState, Service
from avrana_home.principal import principal_from_headers
from avrana_home.resilience import FakeClock, UrllibTransport
from tests.fake_abs import UA, UB, UC, UD, FakeAudiobookshelf
from tests.fake_jellyfin import FakeJellyfin, FakeOpener, FakeTransport
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-audiobooks")
TOKEN = "SENTINEL-ABS-TOKEN-0000"


def titles(result):
    return [i.title for i in result.items]


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeAudiobookshelf(self.clock)
        self.transport = FakeTransport(self.fake)
        self.adapter = AudiobookshelfAdapter(self.transport, clock=self.clock)
        self.a = make_principal("member-a", GROUPS)
        self.b = make_principal("member-b", GROUPS)
        self.c = make_principal("member-c", GROUPS)
        self.d = make_principal("member-d", GROUPS)

    def edit_record(self, uid, fn):
        rec = self.fake.record(uid)
        fn(rec)
        self.fake.serve(f"/api/users/{uid}", rec)
        return rec


class States(Base):
    def test_authorized_member_sees_only_their_own_visible_unfinished_books_newest_first(self):
        r = self.adapter.continue_items(self.a)
        self.assertIs(r.state, SectionState.OK)
        self.assertEqual(titles(r), ["Synthetic Audiobook One", "Synthetic Audiobook Two"])
        one = r.items[0]
        self.assertIs(one.kind, Kind.AUDIOBOOK)
        self.assertEqual(one.id, "audiobookshelf:li_book000001")
        self.assertEqual(one.handoff_url, "https://listen.avrana.net/item/li_book000001")
        self.assertEqual((one.progress_fraction, one.position_seconds, one.duration_seconds),
                         (0.42, 15120, 36000))
        self.assertEqual((one.subtitle, one.series), ("Synthetic Author", "Synthetic Saga #1"))
        self.assertIsNone(one.artwork)                        # covers are deliberately not offered
        self.assertEqual(r.to_dict()["items"][0]["progress"]["percent"], 42)

    def test_a_member_without_the_group_gets_nothing_and_nothing_is_asked_or_read(self):
        cache = MemberCache(self.clock)
        ad = AudiobookshelfAdapter(self.transport, clock=self.clock, cache=cache)
        outsider = make_principal("member-a", ("avrana-users", "avrana-videos"))
        self.assertIs(ad.continue_items(outsider).state, SectionState.NOT_PERMITTED)
        self.assertIs(ad.fetch_artwork(outsider, "x").state, SectionState.NOT_PERMITTED)
        self.assertIs(ad.recent_items(outsider).state, SectionState.NOT_PERMITTED)
        self.assertIsNone(ad.resolve_user(outsider))
        self.assertEqual(self.fake.requests, [])
        self.assertEqual(len(cache), 0)
        # nothing is read from the cache either: a warm entry for the same name stays unserved
        ad.continue_items(self.a)
        n = len(self.fake.requests)
        self.assertIs(ad.continue_items(outsider).state, SectionState.NOT_PERMITTED)
        self.assertEqual(len(self.fake.requests), n)

    def test_empty_when_nothing_is_in_progress(self):
        r = self.adapter.continue_items(self.d)
        self.assertEqual((r.state, r.items), (SectionState.EMPTY, ()))

    def test_unmapped_inactive_and_ambiguous_members_are_not_linked(self):
        self.assertEqual(self.adapter.continue_items(make_principal("member-zzz", GROUPS)).reason, "unmapped")
        self.assertEqual(self.adapter.continue_items(make_principal("member-e", GROUPS)).reason, "disabled")
        self.fake.users_doc["users"].append(dict(self.fake.users_doc["users"][0], id=UD.replace("d", "f", 8)))
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "ambiguous"))

    def test_unavailable_when_the_upstream_fails_and_the_circuit_opens_for_everyone(self):
        self.fake.overrides["/api/users"] = ("status", 500)
        for p in (self.a, self.b, self.c):
            self.assertIs(self.adapter.continue_items(p).state, SectionState.UNAVAILABLE)
        self.assertEqual(self.adapter.health().state, "cooling_off")
        n = len(self.fake.requests)
        self.assertEqual(self.adapter.continue_items(self.d).reason, "cooling_off")
        self.assertEqual(len(self.fake.requests), n)

    def test_a_timeout_costs_the_section_only_and_a_warm_cache_still_serves(self):
        self.adapter.continue_items(self.a)
        self.fake.slow["/api/users"] = 5.0
        self.assertEqual(self.adapter.continue_items(self.a).state, SectionState.OK)   # cache hit
        self.assertEqual(self.adapter.continue_items(self.b).reason, "UpstreamTimeout")

    def test_unoffered_sections_make_no_upstream_call(self):
        for r in (self.adapter.recent_items(self.a), self.adapter.item(self.a, "li_book000001")):
            self.assertEqual((r.state, r.reason), (SectionState.EMPTY, "not_offered"))
        self.assertEqual(self.adapter.fetch_artwork(self.a, "audiobookshelf/cover/li_book000001").state,
                         SectionState.EMPTY)
        self.assertEqual(self.fake.requests, [])


class Isolation(Base):
    def test_overlapping_items_with_different_progress_never_cross_members_under_threads(self):
        errors, served = [], []
        want = {"member-a": 0.42, "member-b": 0.07}

        def run(p):
            try:
                for _ in range(25):
                    r = self.adapter.continue_items(p)
                    if r.state is SectionState.UNAVAILABLE:           # a busy refusal is legitimate, nothing else
                        if r.reason not in ("busy", "member_busy"):
                            errors.append((p.username, r.reason))
                        continue
                    served.append(p.username)
                    one = next((i for i in r.items if i.id.endswith("li_book000001")), None)
                    if one is None or one.progress_fraction != want[p.username]:
                        errors.append((p.username, one))
                    if p.username == "member-a" and any(i.title == "Synthetic Audiobook Ten" for i in r.items):
                        errors.append(("a sees b's book", r))
            except Exception as exc:                          # pragma: no cover
                errors.append(repr(exc))
        threads = [threading.Thread(target=run, args=(p,)) for p in (self.a, self.b) * 3]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        self.assertEqual(errors, [])
        self.assertTrue({"member-a", "member-b"} <= set(served))

    def test_every_request_names_the_bound_user_or_is_the_unbound_mapping_list(self):
        self.adapter.continue_items(self.a)
        self.adapter.continue_items(self.b)
        users = [p for p in self.fake.paths() if p.startswith("/api/users/")]
        self.assertEqual(set(users), {f"/api/users/{UA}", f"/api/users/{UB}"})
        for path in self.fake.paths():
            self.assertRegex(path, r"^/api/(users|users/[0-9a-f-]{36}|items/li_[a-z0-9]+)$")
        self.assertFalse(any(p in ("/api/me", "/api/authorize", "/api/libraries") for p in self.fake.paths()))

    def test_a_hostile_upstream_answering_with_another_users_record_is_discarded(self):
        self.fake.serve(f"/api/users/{UA}", self.fake.record(UB))
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason, r.items), (SectionState.UNAVAILABLE, "UpstreamMisbehaved", ()))
        self.assertNotIn("/api/items/li_book000010", self.fake.paths())          # nothing of b's was fetched

    def test_a_record_for_another_user_is_discarded_even_if_its_entries_claim_the_asker(self):
        def relabel(rec):
            rec["id"] = UB
        self.edit_record(UA, relabel)
        self.assertEqual(self.adapter.continue_items(self.a).reason, "UpstreamMisbehaved")

    def test_progress_entries_naming_another_user_or_nobody_discard_the_whole_section(self):
        def other(rec):
            rec["mediaProgress"][1]["userId"] = UB
        self.edit_record(UA, other)
        self.assertEqual(self.adapter.continue_items(self.a).reason, "UpstreamMisbehaved")
        self.adapter.cache.clear()

        def nobody(rec):
            del rec["mediaProgress"][0]["userId"]
        self.edit_record(UA, nobody)
        self.assertEqual(self.adapter.continue_items(self.a).reason, "UpstreamMisbehaved")
        self.adapter.cache.clear()

        def wrong_type(rec):
            rec["mediaProgress"][0]["userId"] = [UA]
        self.edit_record(UA, wrong_type)
        self.assertEqual(self.adapter.continue_items(self.a).reason, "UpstreamMisbehaved")

    def test_an_item_lookup_answering_with_a_different_item_is_misbehaviour(self):
        self.fake.serve("/api/items/li_book000001", self.fake.items["li_book000010"])
        self.assertEqual(self.adapter.continue_items(self.a).reason, "UpstreamMisbehaved")

    def test_a_follower_section_never_gets_another_members_mapping(self):
        results = {}

        def run(p):
            got = self.adapter.resolve_user(p)
            if got is not None:
                results[p.username] = got.upstream_id
        threads = [threading.Thread(target=run, args=(p,)) for p in (self.a, self.b) * 4]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(results, {"member-a": UA, "member-b": UB})

    def test_the_cache_is_per_member(self):
        self.adapter.continue_items(self.a)
        n = len(self.fake.requests)
        theirs = self.adapter.continue_items(self.b)
        self.assertIn("Synthetic Audiobook Ten", titles(theirs))
        self.assertNotEqual(titles(theirs), titles(self.adapter.continue_items(self.a)))
        self.assertGreater(len(self.fake.requests), n)                       # b did not get a's cached section


class PermissionsFromTheUsersOwnRecord(Base):
    def test_a_library_the_member_cannot_open_is_omitted(self):
        self.assertNotIn("Synthetic Audiobook Three", titles(self.adapter.continue_items(self.a)))
        self.assertIn("Synthetic Audiobook Three", titles(self.adapter.continue_items(self.b)))

    def test_explicit_items_are_shown_only_to_members_who_may_see_them(self):
        self.assertNotIn("Synthetic Audiobook Four", titles(self.adapter.continue_items(self.a)))
        self.assertIn("Synthetic Audiobook Four", titles(self.adapter.continue_items(self.b)))

    def test_a_tag_deny_list_hides_tagged_items(self):
        self.assertEqual(titles(self.adapter.continue_items(self.c)), ["Synthetic Audiobook One"])

    def test_a_tag_allow_list_shows_only_tagged_items(self):
        def allow(rec):
            rec["permissions"].update(accessAllTags=False, selectedTagsNotAccessible=False)
            rec["itemTagsSelected"] = ["mature"]
        self.edit_record(UC, allow)
        self.assertEqual(titles(self.adapter.continue_items(self.c)), ["Synthetic Audiobook Five"])

    def test_missing_or_wrongly_typed_permission_fields_make_the_section_unavailable_not_unfiltered(self):
        cases = {
            "no permissions": lambda r: r.pop("permissions"),
            "permissions not an object": lambda r: r.update(permissions="all"),
            "libraries flag missing": lambda r: r["permissions"].pop("accessAllLibraries"),
            "libraries flag wrong type": lambda r: r["permissions"].update(accessAllLibraries="yes"),
            "explicit flag missing": lambda r: r["permissions"].pop("accessExplicitContent"),
            "explicit flag wrong type": lambda r: r["permissions"].update(accessExplicitContent=1),
            "tags flag missing": lambda r: r["permissions"].pop("accessAllTags"),
            "library list missing": lambda r: r.pop("librariesAccessible"),
            "library list wrong type": lambda r: r.update(librariesAccessible="lib_aaa"),
            "library list holds a number": lambda r: r.update(librariesAccessible=[1]),
        }
        for label, mutate in cases.items():
            self.fake.requests.clear()
            self.adapter.cache.clear()
            self.edit_record(UA, mutate)
            r = self.adapter.continue_items(self.a)
            self.assertEqual((r.state, r.reason, r.items), (SectionState.UNAVAILABLE, "UpstreamMalformed", ()), label)
            self.assertFalse([p for p in self.fake.paths() if p.startswith("/api/items/")], label)
            self.adapter.breaker.success(self.adapter.breaker.acquire())             # keep the circuit closed

    def test_tag_list_fields_are_checked_only_when_they_matter_and_then_fail_closed(self):
        def broken(rec):
            rec["permissions"].update(accessAllTags=False)
            rec.pop("itemTagsSelected")
        self.edit_record(UC, broken)
        self.assertEqual(self.adapter.continue_items(self.c).reason, "UpstreamMalformed")

    def test_an_item_with_a_missing_or_wrongly_typed_field_is_left_out(self):
        for label, mutate in {
            "no library": lambda it: it.pop("libraryId"),
            "library wrong type": lambda it: it.update(libraryId=7),
            "no media": lambda it: it.pop("media"),
            "tags wrong type": lambda it: it["media"].update(tags="mature"),
            "tag not text": lambda it: it["media"].update(tags=[1]),
            "explicit missing": lambda it: it["media"]["metadata"].pop("explicit"),
            "explicit wrong type": lambda it: it["media"]["metadata"].update(explicit="no"),
        }.items():
            self.adapter.cache.clear()
            item = json.loads(json.dumps(self.fake.items["li_book000001"]))
            mutate(item)
            self.fake.serve("/api/items/li_book000001", item)
            self.assertEqual(titles(self.adapter.continue_items(self.a)), ["Synthetic Audiobook Two"], label)

    def test_if_no_item_can_be_checked_the_section_is_drift_never_an_unfiltered_list(self):
        for it in ("li_book000001", "li_book000002"):
            item = json.loads(json.dumps(self.fake.items[it]))
            del item["libraryId"]
            self.fake.serve(f"/api/items/{it}", item)
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason, r.items), (SectionState.UNAVAILABLE, "UpstreamMalformed", ()))

    def test_covers_and_other_media_types_are_not_shown(self):
        item = json.loads(json.dumps(self.fake.items["li_book000001"]))
        item["mediaType"] = "podcast"
        self.fake.serve("/api/items/li_book000001", item)
        self.assertEqual(titles(self.adapter.continue_items(self.a)), ["Synthetic Audiobook Two"])
        self.assertFalse([p for p in self.fake.paths() if "cover" in p])


class ProgressRules(Base):
    def test_finished_hidden_and_vanished_entries_are_excluded(self):
        r = self.adapter.continue_items(self.a, limit=50)
        for gone in ("Synthetic Audiobook Six", "Synthetic Audiobook Seven"):
            self.assertNotIn(gone, titles(r))
        self.assertEqual(self.adapter.health().state, "ok")             # the 404 item was neutral

    def test_progress_is_clamped_and_hostile_numbers_are_harmless(self):
        def hostile(rec):
            rec["mediaProgress"] = rec["mediaProgress"][:3]
            rec["mediaProgress"][0].update(progress=7.5, currentTime=10 ** 400, duration=-5)
            rec["mediaProgress"][1].update(progress=0.5, currentTime="soon", duration=None, lastUpdate="x")
        self.edit_record(UA, hostile)
        r = self.adapter.continue_items(self.a)
        one = next(i for i in r.items if i.title == "Synthetic Audiobook One")
        self.assertEqual(one.progress_fraction, 1.0)
        self.assertEqual(one.position_seconds, None)
        self.assertEqual(one.duration_seconds, 0)
        self.assertTrue(all(0.0 <= i.progress_fraction <= 1.0 for i in r.items))

    def test_a_negative_zero_or_nan_progress_is_not_in_progress(self):
        def odd(rec):
            rec["mediaProgress"] = rec["mediaProgress"][:2]
            rec["mediaProgress"][0]["progress"] = -0.5
            rec["mediaProgress"][1]["progress"] = 0
        self.edit_record(UA, odd)
        self.assertEqual(self.adapter.continue_items(self.a).state, SectionState.EMPTY)

    def test_wrong_types_deep_nesting_and_huge_bodies_are_malformed_not_exceptions(self):
        for body in (b"[" * 100000, b'{"id": 5}', b"not json", b"\xff\xfe", b"null", b"[]"):
            self.adapter.cache.clear()
            self.adapter.breaker.success(self.adapter.breaker.acquire())
            self.fake.overrides[f"/api/users/{UA}"] = ("body", body)
            r = self.adapter.continue_items(self.a)
            self.assertIs(r.state, SectionState.UNAVAILABLE, body[:12])
        self.fake.overrides[f"/api/users/{UA}"] = ("body", json.dumps({"id": UA}).encode())
        self.assertEqual(self.adapter.continue_items(self.a).state, SectionState.UNAVAILABLE)

    def test_the_limit_is_clamped_and_bounds_the_item_lookups(self):
        r = self.adapter.continue_items(self.a, limit=1)
        self.assertEqual(len(r.items), 1)
        self.assertLessEqual(len([p for p in self.fake.paths() if p.startswith("/api/items/")]), 24)
        self.assertEqual(len(self.adapter.continue_items(self.a, limit=10 ** 9).items), 2)
        self.assertEqual(len(self.adapter.continue_items(self.a, limit=-3).items), 2)


class Mapping(Base):
    def test_the_email_is_never_used_and_an_exact_username_is_required(self):
        # an account whose e-mail equals the member's but whose username differs is NOT this member
        self.fake.users_doc["users"][3]["email"] = "member-x@example.invalid"
        self.fake.users_doc["users"][3]["username"] = "someone-else"
        p = principal_from_headers({"X-authentik-username": "member-x", "X-authentik-groups": "avrana-audiobooks",
                                    "X-authentik-email": "member-x@example.invalid"})
        r = self.adapter.continue_items(p)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "unmapped"))
        self.assertIsNone(self.adapter.resolve_user(p))

    def test_case_and_unicode_differences_never_link(self):
        for name in ("Member-A", "MEMBER-A", "member-a​", "member‐a"):
            try:
                p = principal_from_headers({"X-authentik-username": name,
                                            "X-authentik-groups": "avrana-audiobooks"})
            except Exception:
                continue                                      # the principal parser refused it outright
            r = self.adapter.continue_items(p)
            self.assertIs(r.state, SectionState.NOT_LINKED, name)
        p = principal_from_headers({"X-authentik-username": "Member-A", "X-authentik-groups": "avrana-audiobooks"})
        self.assertEqual(self.adapter.continue_items(p).reason, "case_or_unicode_mismatch")

    def test_no_request_is_ever_sent_without_the_bound_user_except_the_mapping_list(self):
        for p in (self.a, self.b, self.c, self.d):
            self.adapter.continue_items(p)
        for method, path, query in self.fake.requests:
            self.assertEqual(method, "GET")
            if path != "/api/users":
                self.assertTrue(path.startswith(("/api/users/", "/api/items/")))
            self.assertLessEqual(set(query), {"expanded"})


class GuardAttacks(unittest.TestCase):
    def guard(self, uid=UA):
        return GuardedTransport(FakeTransport(FakeAudiobookshelf()), uid)

    def refused(self, method, path, query=None, uid=UA):
        with self.assertRaises(ForbiddenRequest):
            self.guard(uid).request(method, path, query, 1.0, 10000)

    def test_only_get_on_listed_routes(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "get", None):
            self.refused(method, f"/api/users/{UA}")
        for path in ("/api/me", "/api/authorize", "/api/libraries", "/api/users/", f"/api/users/{UA}/listening-stats",
                     "/api/items/li_book000001/cover", "/api/items", "/ping", "//api/users", "/api/users?x=1"):
            self.refused("GET", path)

    def test_another_users_id_traversal_and_encoded_slashes_are_refused(self):
        for path in (f"/api/users/{UB}", f"/api/users/{UA}/../{UB}", f"/api/users/{UA}%2f..%2f{UB}",
                     f"/api/users/{UA.upper()}", f"/api/users/{UA}%00", "/api/users/root",
                     f"/api/users/{UA}/", "/api/items/li_book000001/../../users/" + UB,
                     "/api/items/../users", "/api/items/li_%2e%2e", "/api/items/LI_BOOK000001"):
            self.refused("GET", path)

    def test_extra_query_keys_and_non_text_queries_are_refused(self):
        self.refused("GET", "/api/items/li_book000001", {"expanded": "1", "include": "all"})
        self.refused("GET", "/api/items/li_book000001", {"userId": UA})
        self.refused("GET", f"/api/users/{UA}", {"token": "x"})
        self.refused("GET", "/api/items/li_book000001", {"expanded": 1})

    def test_item_and_user_routes_need_a_bound_user_and_a_well_formed_one(self):
        self.refused("GET", "/api/items/li_book000001", {"expanded": "1"}, uid=None)
        self.refused("GET", f"/api/users/{UA}", uid=None)
        with self.assertRaises(ForbiddenRequest):
            GuardedTransport(FakeTransport(FakeAudiobookshelf()), "root")
        with self.assertRaises(ForbiddenRequest):
            GuardedTransport(FakeTransport(FakeAudiobookshelf()), UA + "/..")

    def test_the_user_list_needs_no_user_but_still_allows_no_query(self):
        self.guard(None).request("GET", "/api/users", None, 1.0, 100000)
        self.refused("GET", "/api/users", {"x": "1"}, uid=None)

    def test_route_names(self):
        self.assertEqual([r.name for r in ALLOWED_ROUTES], ["users", "user", "item"])


class FailureClasses(Base):
    def test_an_item_404_is_omitted_and_never_counted(self):
        for _ in range(6):
            self.adapter.cache.clear()
            self.assertIn("Synthetic Audiobook One", titles(self.adapter.continue_items(self.a, limit=50)))
        self.assertEqual(self.adapter.health().state, "ok")

    def test_a_user_route_404_with_a_cached_mapping_means_not_linked_and_drops_the_mapping(self):
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.OK)
        self.clock.advance(31)
        self.fake.overrides[f"/api/users/{UA}"] = ("status", 404)
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "upstream_user_not_found"))
        self.assertNotEqual(self.adapter.health().state, "cooling_off")
        self.assertIsNone(self.adapter.cache.for_member(self.a).get("audiobookshelf", "mapping"))

    def test_a_user_route_404_right_after_a_fresh_mapping_is_drift_and_counts(self):
        self.fake.overrides[f"/api/users/{UA}"] = ("status", 404)
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UserGone"))
        self.assertEqual(self.adapter.health().consecutive_failures, 1)

    def test_a_404_on_the_user_list_is_route_drift_and_opens_the_circuit_after_three(self):
        self.fake.overrides["/api/users"] = ("status", 404)
        self.assertEqual([self.adapter.continue_items(p).reason for p in (self.a, self.b, self.c)],
                         ["RouteMissing"] * 3)
        self.assertEqual(self.adapter.health().state, "cooling_off")

    def test_401_counts_and_a_member_scoped_403_does_not(self):
        self.fake.overrides[f"/api/users/{UA}"] = ("status", 403)
        for _ in range(5):
            self.adapter.cache.clear()
            self.assertIs(self.adapter.continue_items(self.a).state, SectionState.UNAVAILABLE)
        self.assertNotEqual(self.adapter.health().state, "cooling_off")
        self.fake.overrides[f"/api/users/{UA}"] = ("status", 401)
        for _ in range(3):
            self.adapter.cache.clear()
            self.adapter.continue_items(self.a)
        self.assertEqual(self.adapter.health().state, "cooling_off")


class CachePolicyAndSecrets(Base):
    def test_a_file_backed_cache_gets_no_member_rows_and_no_member_text(self):
        tmp = tempfile.mkdtemp(prefix="avrana-abs-")
        try:
            cache = MemberCache(self.clock, path=_os.path.join(tmp, "c.sqlite"))
            ad = AudiobookshelfAdapter(self.transport, clock=self.clock, cache=cache)
            self.assertIs(ad.continue_items(self.a).state, SectionState.OK)
            self.assertGreater(len(cache), 0)                                  # cached in memory ...
            self.assertEqual(cache._conn.execute("SELECT count(*) FROM main.entries").fetchone()[0], 0)
            with open(cache.path, "rb") as fh:                                 # ... and nowhere on disk
                blob = fh.read()
            for needle in (b"Synthetic Audiobook", b"member-a", b"li_book", UA.encode()):
                self.assertNotIn(needle, blob)
            cache.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cache_writes_use_member_classes_only(self):
        self.adapter.continue_items(self.a)
        classes = {r[0] for r in self.adapter.cache._conn.execute("SELECT dclass FROM all_entries")}
        self.assertTrue(classes <= {"member_progress", "member_mapping"}, classes)

    def test_the_token_is_never_in_a_repr_a_result_a_health_report_or_a_log_line(self):
        opener = FakeOpener(self.fake)
        transport = UrllibTransport("https://abs.invalid", {"Authorization": f"Bearer {TOKEN}"}, opener=opener)
        ad = AudiobookshelfAdapter(transport, clock=self.clock)
        with self.assertLogs("avrana_home", level="WARNING") as logs:
            logging.getLogger("avrana_home").warning("probe")
            self.fake.overrides[f"/api/users/{UB}"] = ("status", 500)
            results = [ad.continue_items(self.a), ad.continue_items(self.b)]
        seen = repr(ad) + repr(transport) + repr(ad._guard) + json.dumps(ad.health().to_dict())
        seen += json.dumps([r.to_dict() for r in results]) + "\n".join(logs.output)
        self.assertNotIn(TOKEN, seen)
        self.assertTrue(all(h.get("Authorization") == f"Bearer {TOKEN}" for h in opener.seen_headers))

    def test_a_per_user_token_inside_upstream_bodies_is_never_retained(self):
        upstream_token = "SENTINEL-UPSTREAM-USER-TOKEN"
        for u in self.fake.users_doc["users"]:
            u["token"] = upstream_token
        rec = self.fake.record(UA)
        rec["token"] = upstream_token
        self.fake.serve(f"/api/users/{UA}", rec)
        results = [self.adapter.continue_items(self.a), self.adapter.resolve_user(self.a)]
        rows = self.adapter.cache._conn.execute("SELECT k, owner, value, data FROM all_entries").fetchall()
        seen = repr(results) + json.dumps(results[0].to_dict()) + repr(rows) + repr(self.adapter.health())
        self.assertNotIn(upstream_token, seen)

    def test_logs_carry_no_username_title_or_id(self):
        self.fake.overrides[f"/api/users/{UA}"] = ("status", 500)
        with self.assertLogs("avrana_home", level="WARNING") as logs:
            self.adapter.continue_items(self.a)
        text = "\n".join(logs.output)
        for secret in ("member-a", "Synthetic", UA, "li_book", "/api/"):
            self.assertNotIn(secret, text)
        self.assertIn("service=audiobookshelf", text)


class WithJellyfinThroughGather(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.abs_fake = FakeAudiobookshelf(self.clock)
        self.jf_fake = FakeJellyfin(self.clock)
        self.abs = AudiobookshelfAdapter(FakeTransport(self.abs_fake), clock=self.clock)
        self.jf = JellyfinAdapter(FakeTransport(self.jf_fake), clock=self.clock)

    def by_service(self, res):
        return {(s.service, s.section): s for s in res.sections}

    def test_both_adapters_answer_and_one_failing_costs_only_its_own_section(self):
        both = make_principal("member-a", ("avrana-users", "avrana-videos", "avrana-audiobooks"))
        res = self.by_service(gather(both, [self.jf, self.abs], sections=("continue",)))
        self.assertIs(res[(Service.JELLYFIN, "continue")].state, SectionState.OK)
        self.assertIs(res[(Service.AUDIOBOOKSHELF, "continue")].state, SectionState.OK)
        self.abs.cache.clear()
        self.jf.cache.clear()
        self.abs_fake.overrides[f"/api/users/{UA}"] = ("status", 500)
        res = self.by_service(gather(both, [self.jf, self.abs], sections=("continue",)))
        self.assertIs(res[(Service.JELLYFIN, "continue")].state, SectionState.OK)
        self.assertIs(res[(Service.AUDIOBOOKSHELF, "continue")].state, SectionState.UNAVAILABLE)

    def test_an_audiobooks_only_member_causes_no_jellyfin_call_and_a_videos_only_member_no_abs_call(self):
        listener = make_principal("member-a", ("avrana-users", "avrana-audiobooks"))
        res = self.by_service(gather(listener, [self.jf, self.abs], sections=("continue",)))
        self.assertIs(res[(Service.JELLYFIN, "continue")].state, SectionState.NOT_PERMITTED)
        self.assertEqual(self.jf_fake.requests, [])
        self.abs_fake.requests.clear()
        viewer = make_principal("member-a", ("avrana-users", "avrana-videos"))
        res = self.by_service(gather(viewer, [self.jf, self.abs], sections=("continue",)))
        self.assertIs(res[(Service.AUDIOBOOKSHELF, "continue")].state, SectionState.NOT_PERMITTED)
        self.assertEqual(self.abs_fake.requests, [])

    def test_the_default_sections_include_a_recent_that_makes_no_abs_call(self):
        listener = make_principal("member-a", ("avrana-users", "avrana-audiobooks"))
        res = self.by_service(gather(listener, [self.abs]))
        self.assertEqual(res[(Service.AUDIOBOOKSHELF, "recent")].reason, "not_offered")
        self.assertEqual(self.abs_fake.paths().count("/api/users"), 1)


if __name__ == "__main__":
    unittest.main()
