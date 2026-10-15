"""Third-review findings N1 to N16 (phase 1)."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest

from avrana_home import aggregate
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.aggregate import DEFAULT_HARD_CAP, derive_hard_cap, gather
from avrana_home.cache import (DisposableCache, MemberCache, STORED_OVERHEAD, CachePathInUseError,
                               SharedCache, _dumps, _loads)
from avrana_home.contract import (ArtworkResult, MappingFailed, SectionResult, SectionState, Service,
                                  UpstreamUser, _Flight, _SharedFailure)
from avrana_home.principal import PrincipalError, principal_from_raw_headers
from avrana_home.resilience import (REQUEST_BUDGET, CircuitBreaker, FakeClock, ItemGone, RouteMissing,
                                    SystemClock, UpstreamNotFound, UpstreamTimeout, UserGone,
                                    counts_toward_breaker)
from tests.fake_jellyfin import A, B, FakeJellyfin, FakeTransport
from tests.helpers import FakeAdapter, make_principal

GROUPS = ("avrana-users", "avrana-videos")


def pad_for(total):
    """A string whose STORED size (payload + fixed overhead) is `total` bytes."""
    return "x" * (total - STORED_OVERHEAD - 2)


class JF(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeJellyfin(self.clock)
        self.transport = FakeTransport(self.fake)
        self.adapter = JellyfinAdapter(self.transport, clock=self.clock)
        self.a = make_principal("member-a", GROUPS)
        self.b = make_principal("member-b", GROUPS)


# ---------------------------------------------------------------------------- N1
class FalsyClock(FakeClock):
    def __len__(self):
        return 0


class FalsyBreaker(CircuitBreaker):
    def __len__(self):
        return 0


class N1InjectedCollaborators(JF):
    def test_an_empty_injected_cache_breaker_and_clock_are_used(self):
        clock = FalsyClock()
        cache = MemberCache(clock)
        breaker = FalsyBreaker(clock)
        self.assertFalse(cache)                                 # empty caches are falsy (__len__)
        ad = JellyfinAdapter(self.transport, clock=clock, cache=cache, breaker=breaker)
        self.assertIs(ad.cache, cache)
        self.assertIs(ad.breaker, breaker)
        self.assertIs(ad.clock, clock)

    def test_purge_through_the_injected_cache_removes_what_the_adapter_would_serve(self):
        cache = MemberCache(self.clock)
        ad = JellyfinAdapter(self.transport, clock=self.clock, cache=cache)
        ad.continue_items(self.a)
        n = self.fake.paths().count("/UserItems/Resume")
        ad.continue_items(self.a)
        self.assertEqual(self.fake.paths().count("/UserItems/Resume"), n)       # served from cache
        self.assertGreater(cache.purge_member(self.a), 0)
        ad.continue_items(self.a)
        self.assertEqual(self.fake.paths().count("/UserItems/Resume"), n + 1)   # purge took effect

    def test_two_adapters_share_one_injected_cache_and_the_global_bound_holds_once(self):
        cache = MemberCache(self.clock, max_entries=3)
        a1 = JellyfinAdapter(self.transport, clock=self.clock, cache=cache)
        a2 = JellyfinAdapter(self.transport, clock=self.clock, cache=cache)
        for ad in (a1, a2):
            for p in (self.a, self.b):
                ad.continue_items(p)
                ad.recent_items(p)
        self.assertLessEqual(len(cache), 3)
        self.assertIs(a1.cache, a2.cache)


# ---------------------------------------------------------------------------- N2
class N2RouteDeclaredNotFound(JF):
    def test_fixed_route_404_is_always_drift_and_opens_after_exactly_three(self):
        self.fake.overrides["/Users"] = ("status", 404)
        reasons = [self.adapter.continue_items(p).reason for p in (self.a, self.a, self.b)]
        self.assertEqual(reasons, ["RouteMissing"] * 3)
        self.assertEqual(self.adapter.health().state, "cooling_off")
        self.assertEqual(self.adapter.continue_items(self.a).reason, "cooling_off")

    def test_user_route_404_with_a_fresh_mapping_is_contradictory_drift_and_keeps_the_mapping(self):
        self.fake.overrides["/UserItems/Resume"] = ("status", 404)
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UserGone"))
        self.assertEqual(self.adapter.health().consecutive_failures, 1)
        self.assertIsNotNone(self.adapter.cache.for_member(self.a).get("jellyfin", "mapping"))

    def test_image_404_is_empty_and_neutral(self):
        self.adapter.continue_items(self.a)                      # item ...0001 is visible to member-a
        self.fake.image = (404, b"", "application/json")
        ref = "jellyfin/primary/aaaa0000000000000000000000000001"
        for _ in range(5):
            r = self.adapter.fetch_artwork(self.a, ref)
            self.assertIs(r.state, SectionState.EMPTY)
        self.assertTrue(any(p.endswith("/Images/Primary") for p in self.fake.paths()))   # it did ask
        self.assertEqual(self.adapter.health().state, "ok")
        self.assertIsNone(self.adapter.health().last_error_class)

    def test_counting_rule_by_class(self):
        self.assertFalse(counts_toward_breaker(UserGone(404)))
        self.assertFalse(counts_toward_breaker(ItemGone(404)))
        self.assertTrue(counts_toward_breaker(RouteMissing(404)))
        self.assertTrue(counts_toward_breaker(UpstreamNotFound(404)))        # unclassified: drift


class N2BaseClassification(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.ad = FakeAdapter(Service.JELLYFIN, {"member-a": "1"}, self.clock)
        self.p = make_principal("member-a", GROUPS)

    def raising(self, exc):
        self.ad.work_exc = exc

    def test_item_route_404_is_an_empty_neutral_result(self):
        self.raising(ItemGone(404))
        for _ in range(6):
            r = self.ad.continue_items(self.p)
            self.assertEqual((r.state, r.reason), (SectionState.EMPTY, "item_not_found"))
        self.assertNotEqual(self.ad.health().state, "cooling_off")
        self.assertIsNone(self.ad.health().last_error_class)
        art = self.ad.fetch_artwork(self.p, "ref")
        self.assertIs(art.state, SectionState.EMPTY)

    def test_user_route_404_with_a_cached_mapping_is_not_linked_and_drops_it(self):
        self.assertIs(self.ad.continue_items(self.p).state, SectionState.OK)       # mapping cached
        self.clock.advance(31)
        self.raising(UserGone(404))
        r = self.ad.continue_items(self.p)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "upstream_user_not_found"))
        self.assertIsNone(self.ad.health().last_error_class)
        self.assertIsNone(self.ad.cache.for_member(self.p).get("jellyfin", "mapping"))

    def test_user_route_404_right_after_a_fresh_mapping_is_contradictory_and_counted(self):
        self.raising(UserGone(404))
        r = self.ad.continue_items(self.p)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UserGone"))
        self.assertEqual(self.ad.health().consecutive_failures, 1)
        self.assertIsNotNone(self.ad.cache.for_member(self.p).get("jellyfin", "mapping"))   # kept

    def test_a_follower_never_drops_the_mapping_its_leader_just_confirmed(self):
        self.ad.mode = "block"
        self.ad.block_ops = {"resolve"}
        self.raising(UserGone(404))
        results = []
        threads = [threading.Thread(target=lambda f=f: results.append(f(self.p)))
                   for f in (self.ad.continue_items, self.ad.recent_items)]
        for t in threads:
            t.start()
        self.assertTrue(self.ad.started.acquire(timeout=2))
        for _ in range(400):
            if self.ad.in_flight == 2:
                break
            time.sleep(0.005)
        time.sleep(0.05)
        self.ad.release.set()
        for t in threads:
            t.join(5)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.state is SectionState.UNAVAILABLE for r in results))
        self.assertIsNotNone(self.ad.cache.for_member(self.p).get("jellyfin", "mapping"))


# ---------------------------------------------------------------------------- N3
class HungOnceTransport:
    """The first /Users request blocks until released; later ones pass straight through."""

    def __init__(self, inner):
        self.inner = inner
        self.reached = threading.Semaphore(0)
        self.release = threading.Event()
        self.first = True
        self.users_calls = 0

    def request(self, method, path, query, timeout, max_bytes):
        if path == "/Users":
            self.users_calls += 1
            if self.first:
                self.first = False
                self.reached.release()
                self.release.wait(5)
        return self.inner.request(method, path, query, timeout, max_bytes)


class N3FollowersAndBudgets(unittest.TestCase):
    def test_follower_wait_is_bounded_by_the_request_budget_and_a_hung_leader_is_abandoned(self):
        fake = FakeJellyfin()
        hung = HungOnceTransport(FakeTransport(fake))
        ad = JellyfinAdapter(hung, timeout=0.15)                       # real clock, tiny budget
        a = make_principal("member-a", GROUPS)
        leader = threading.Thread(target=ad.continue_items, args=(a,))
        leader.start()
        try:
            self.assertTrue(hung.reached.acquire(timeout=2))
            t0 = time.monotonic()
            r = ad.recent_items(a)                                    # follower of the hung leader
            self.assertLess(time.monotonic() - t0, 1.0)
            self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamTimeout"))
            time.sleep(0.2)                                           # the flight is now older than the budget
            r = ad.continue_items(a)                                  # becomes the new leader
            self.assertIs(r.state, SectionState.OK)
            self.assertEqual(hung.users_calls, 2)
        finally:
            hung.release.set()
            leader.join(5)

    def test_follower_gets_a_new_exception_instance_each_time(self):
        ad = FakeAdapter(Service.JELLYFIN, {}, FakeClock())
        p = make_principal("member-z", GROUPS)
        flight = _Flight(ad.clock.now())
        flight.exc = MappingFailed("unmapped")
        flight.finished = ad.clock.now()
        flight.event.set()
        caught = []
        for _ in range(2):
            ad._flights["member-z"] = flight
            try:
                ad._mapped(ad.cache.for_member(p), p, ad.breaker.acquire(), type("C", (), {})())
            except MappingFailed as exc:
                caught.append(exc)
        self.assertEqual(len(caught), 2)
        self.assertIsNot(caught[0], caught[1])
        self.assertIsNot(caught[0], flight.exc)
        self.assertEqual(caught[0].reason, "unmapped")

    def test_followers_of_a_failed_leader_each_get_their_own_exception_instance(self):
        ad = FakeAdapter(Service.JELLYFIN, {}, FakeClock())
        p = make_principal("member-z", GROUPS)
        flight = _Flight(ad.clock.now())
        flight.exc = UpstreamTimeout()
        flight.finished = ad.clock.now()
        flight.event.set()
        caught = []
        for _ in range(2):
            ad._flights["member-z"] = flight
            try:
                ad._mapped(ad.cache.for_member(p), p, ad.breaker.acquire(), type("C", (), {})())
            except _SharedFailure as exc:
                caught.append(exc.err)
        self.assertIsNot(caught[0], caught[1])
        self.assertIsNot(caught[0], flight.exc)
        self.assertIsInstance(caught[0], UpstreamTimeout)

    def test_a_follower_does_not_accept_a_mapping_older_than_the_ttl(self):
        clock = FakeClock()
        ad = FakeAdapter(Service.JELLYFIN, {"member-a": "1"}, clock)
        p = make_principal("member-a", GROUPS)
        flight = _Flight(clock.now() - 500)
        flight.result = UpstreamUser(Service.JELLYFIN, "9")           # a stale, wrong answer
        flight.finished = clock.now() - 400
        flight.event.set()
        ad._flights["member-a"] = flight
        out = ad.continue_items(p)
        self.assertEqual(out.items[0].title, "Synthetic Title 1")      # re-resolved, not the stale "9"

    def test_followers_never_receive_another_members_user(self):
        gated = HungOnceTransport(FakeTransport(FakeJellyfin()))
        gated.first = False
        ad = JellyfinAdapter(gated)
        results = {}

        def run(name):
            got = ad.resolve_user(make_principal(name, GROUPS))
            if got is not None:                       # a refused (busy) caller says nothing
                results[name] = got
        threads = [threading.Thread(target=run, args=(n,)) for n in ("member-a", "member-b") * 4]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        self.assertEqual(results["member-a"].upstream_id, A)
        self.assertEqual(results["member-b"].upstream_id, B)

    def test_timeout_propagates_to_the_request_budget(self):
        clock = FakeClock()
        fake = FakeJellyfin(clock)
        fake.slow["/Users"] = 2.4
        fake.slow["/UserItems/Resume"] = 2.4
        big = JellyfinAdapter(FakeTransport(fake), clock=clock, timeout=5.0)
        self.assertEqual(big._request_timeout, 5.0)
        self.assertIs(big.continue_items(make_principal("member-a", GROUPS)).state, SectionState.OK)
        small = JellyfinAdapter(FakeTransport(fake), clock=clock)
        self.assertEqual(small._request_timeout, REQUEST_BUDGET)
        self.assertEqual(small.continue_items(make_principal("member-b", GROUPS)).reason, "UpstreamTimeout")

    def test_hard_cap_is_derived_from_the_adapters_own_budget(self):
        t = FakeTransport(FakeJellyfin())
        self.assertEqual(derive_hard_cap([JellyfinAdapter(t, timeout=5.0), JellyfinAdapter(t)]), 6.0)
        self.assertEqual(derive_hard_cap([JellyfinAdapter(t)]), DEFAULT_HARD_CAP)
        self.assertEqual(derive_hard_cap([]), DEFAULT_HARD_CAP)
        self.assertEqual(DEFAULT_HARD_CAP, 3.0)
        self.assertEqual(REQUEST_BUDGET, 2.0)

    def test_defaults(self):
        self.assertEqual(CircuitBreaker(FakeClock())._lease, 30.0)

    def test_slot_is_released_when_the_clock_raises(self):
        class Boom(FakeClock):
            armed = False

            def now(self):
                if self.armed:
                    raise RuntimeError("clock failure")
                return super().now()
        clock = Boom()
        ad = FakeAdapter(Service.JELLYFIN, {"member-a": "1"}, clock)
        clock.armed = True
        with self.assertRaises(RuntimeError):
            ad.continue_items(make_principal("member-a", GROUPS))
        clock.armed = False
        self.assertEqual(ad.in_flight, 0)
        self.assertIs(ad.continue_items(make_principal("member-a", GROUPS)).state, SectionState.OK)

    def test_request_budget_is_cleared_after_every_call(self):
        ad = FakeAdapter(Service.JELLYFIN, {"member-a": "1"}, FakeClock(), mode="timeout")
        ad.continue_items(make_principal("member-a", GROUPS))
        self.assertIsNone(ad._local.budget)
        ad.mode = "ok"
        ad.continue_items(make_principal("member-a", GROUPS))
        self.assertIsNone(ad._local.budget)

    def test_a_stale_token_cannot_free_a_live_trial_slot(self):
        clock = FakeClock()
        cb = CircuitBreaker(clock, threshold=1, trial_lease=10)
        cb.failure("X", cb.acquire())
        clock.advance(61)
        t1 = cb.acquire()
        clock.advance(11)
        t2 = cb.acquire()
        cb.neutral(t1)                                  # the lost trial reports late
        self.assertIsNone(cb.acquire())                  # t2's slot is still held
        cb.neutral(t2)
        self.assertIsNotNone(cb.acquire())


class N16Pool(unittest.TestCase):
    def test_pool_threads_are_daemons(self):
        done = threading.Event()
        fut = aggregate._shared_pool().submit(done.set)
        fut.result(2)
        names = [t for t in threading.enumerate() if t.name.startswith("avrana-section")]
        self.assertTrue(names)
        self.assertTrue(all(t.daemon for t in names))


class RawHeaderName(unittest.TestCase):
    def test_non_ascii_header_name_is_malformed_input(self):
        with self.assertRaises(PrincipalError) as cm:
            principal_from_raw_headers([(b"X-authentik-user\xc3\xa9", b"x"), (b"x-authentik-username", b"a")])
        self.assertEqual(cm.exception.reason, "malformed_input")


# ---------------------------------------------------------------------------- cache
class CacheBase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.tmp = tempfile.mkdtemp(prefix="avrana-p1-")
        self.made = []

    def tearDown(self):
        for c in self.made:
            c.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, cls=MemberCache, **kw):
        c = cls(self.clock, **kw)
        self.made.append(c)
        return c

    def rows(self, cache, sql="SELECT k FROM all_entries"):
        return cache._conn.execute(sql).fetchall()


class N4NoExceptionEscapesAndRowsAreValidated(CacheBase):
    def test_tampered_row_with_wrong_field_types_is_a_miss_and_is_deleted(self):
        c = self.make()
        s = c.for_member(make_principal("member-a"))
        s.set("jellyfin", "continue", SectionResult.of(Service.JELLYFIN, "continue", ()), 100)
        bad = {"$d": "SectionResult", "f": {"service": 123, "section": 5, "state": "ok", "items": "x", "reason": None}}
        c._conn.execute("UPDATE member.entries SET value=?", (json.dumps(bad),))
        self.assertIsNone(s.get("jellyfin", "continue"))
        self.assertEqual(len(c), 0)

    def test_every_decode_failure_is_a_miss_not_an_exception(self):
        for tampered in ("[" * 200000, '{"$d": "SectionResult", "f": 5}', '{"$e": ["Service", "nope"]}',
                         '{"$t": 5}', '{"$d": "Nope", "f": {}}', "not json", '{"$b": 5}', '{"$blob": [0, 99]}'):
            c = self.make()
            s = c.for_member(make_principal("member-a"))
            s.set("jellyfin", "x", "v", 100)
            c._conn.execute("UPDATE member.entries SET value=?", (tampered,))
            self.assertIsNone(s.get("jellyfin", "x"), tampered[:30])
            self.assertEqual(len(c), 0, tampered[:30])

    def test_unencodable_and_deeply_nested_values_are_simply_not_stored(self):
        c = self.make()
        s = c.for_member(make_principal("member-a"))
        deep = []
        for _ in range(100000):
            deep = [deep]
        s.set("jellyfin", "deep", deep, 100)
        s.set("jellyfin", "obj", object(), 100)
        s.set("jellyfin", "big", 10 ** 400, 100)
        self.assertEqual(len(c), 1)                         # only the int fits JSON; the others did not raise

    def test_dumps_refuses_an_unregistered_dataclass(self):
        import dataclasses

        @dataclasses.dataclass
        class Unregistered:
            x: int = 1
        with self.assertRaises(TypeError):
            _dumps(Unregistered())
        with self.assertRaises(TypeError):
            _dumps(object())

    def test_corrupt_row_is_gone_after_a_corrupt_read(self):
        c = self.make()
        s = c.for_member(make_principal("member-a"))
        s.set("jellyfin", "x", "v", 100)
        c._conn.execute("UPDATE member.entries SET value='{broken'")
        self.assertEqual(len(c), 1)
        self.assertIsNone(s.get("jellyfin", "x"))
        self.assertEqual(len(c), 0)


class N5StoredAccounting(CacheBase):
    def test_astral_titles_stay_within_the_member_quota_as_stored(self):
        quota = 64 * 1024
        c = self.make(member_max_bytes=quota, member_max_entries=1000)
        s = c.for_member(make_principal("member-a"))
        for i in range(128):
            s.set("jellyfin", f"k{i}", "\U0001F600" * 200, 100)         # 800 stored bytes of UTF-8 each
        real = c._conn.execute("SELECT coalesce(sum(length(CAST(value AS BLOB)) + coalesce(length(data), 0)), 0) "
                               "FROM all_entries").fetchone()[0]
        self.assertLessEqual(real, quota)
        self.assertLessEqual(c.total_bytes(), quota)

    def test_the_declared_size_cannot_under_report(self):
        c = self.make(member_max_bytes=2000)
        s = c.for_member(make_principal("member-a"))
        for i in range(10):
            s.set("jellyfin", f"k{i}", "y" * 500, 100, size=1)         # a lying caller
        self.assertLessEqual(c.total_bytes(), 2000)

    def test_artwork_bytes_are_a_blob_not_base64(self):
        c = self.make()
        s = c.for_member(make_principal("member-a"))
        png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
        s.set("jellyfin", "art", ArtworkResult(SectionState.OK, "image/png", png), 100, data_class="artwork")
        self.assertEqual(c._conn.execute("SELECT length(data) FROM all_entries").fetchone()[0], len(png))
        self.assertLess(c.total_bytes(), len(png) + 400)                 # not 4/3 of the payload
        self.assertEqual(s.get("jellyfin", "art").data, png)


class N6EvictionIsNotQuadratic(CacheBase):
    def test_a_set_near_quota_into_a_full_cache_is_bounded_in_time(self):
        c = self.make(max_entries=2048, member_max_entries=2048)
        scopes = [c.for_member(make_principal(f"member-{n}")) for n in range(16)]
        for i in range(2048):
            scopes[i % 16].set("jellyfin", f"k{i}", "z" * 50, 1000 + i)
        self.assertEqual(len(c), 2048)
        t0 = time.monotonic()
        for i in range(300):
            scopes[i % 16].set("jellyfin", f"new{i}", "w" * 50, 5000 + i)     # each must evict
        self.assertLess(time.monotonic() - t0, 10.0)
        self.assertLessEqual(len(c), 2048)

    def test_a_large_entry_evicting_many_small_ones_is_one_pass(self):
        c = self.make(member_max_bytes=100_000, member_max_entries=5000, max_bytes=100_000)
        s = c.for_member(make_principal("member-a"))
        for i in range(500):
            s.set("jellyfin", f"k{i}", "q" * 100, 1000 + i)
        t0 = time.monotonic()
        s.set("jellyfin", "big", "B" * 90_000, 100)
        self.assertLess(time.monotonic() - t0, 5.0)
        self.assertEqual(s.get("jellyfin", "big"), "B" * 90_000)


class N8N9Isolation(CacheBase):
    def test_hmac_parts_are_length_prefixed(self):
        c = self.make()
        self.assertNotEqual(c._h("a", "bc"), c._h("ab", "c"))
        self.assertNotEqual(c._h("a\x1fb", "c"), c._h("a", "b\x1fc"))
        self.assertNotEqual(c._h("a", "b"), c._h("a", "b", ""))

    def test_member_keys_with_separator_characters_do_not_collide(self):
        c = self.make()
        a = c.for_member(make_principal("member-a"))
        a.set("jellyfin", "x", 1, 100)
        a.set("jellyfin\x1fx", "", 2, 100)
        self.assertEqual(a.get("jellyfin", "x"), 1)

    def test_shared_cache_exposes_no_member_api(self):
        shared = self.make(SharedCache)
        self.assertFalse(hasattr(shared, "for_member"))
        self.assertFalse(hasattr(shared, "purge_member"))
        shared.set("public", "k", "v", 100)
        members = self.make()
        members.purge_member(make_principal("shared"))
        self.assertEqual(shared.get("public", "k"), "v")
        self.assertTrue(hasattr(members, "for_member"))
        self.assertTrue(issubclass(MemberCache, DisposableCache))


class N9bN12N13FileSafety(CacheBase):
    def path(self, name="c.sqlite"):
        return os.path.join(self.tmp, name)

    def test_two_caches_on_one_path_are_refused_loudly(self):
        first = self.make(SharedCache, path=self.path())
        with self.assertRaises(CachePathInUseError):
            SharedCache(self.clock, path=self.path())
        first.close()
        again = self.make(SharedCache, path=self.path())
        again.set("p", "k", "v", 100)
        self.assertEqual(again.get("p", "k"), "v")

    def test_a_foreign_regular_file_is_refused_not_deleted(self):
        p = self.path("foreign.db")
        with open(p, "wb") as fh:
            fh.write(b"precious data that is not ours" * 50)
        with self.assertLogs("avrana_home", "WARNING") as cm:
            c = self.make(SharedCache, path=p)
        self.assertIsNone(c.path)                                          # degraded to memory
        c.set("p", "k", "v", 100)
        self.assertEqual(c.get("p", "k"), "v")
        with open(p, "rb") as fh:
            self.assertTrue(fh.read().startswith(b"precious data"))
        self.assertEqual(len(cm.output), 1)
        self.assertIn("cache_path_refused", cm.output[0])
        self.assertNotIn("precious", cm.output[0])

    def test_a_symlink_or_directory_at_the_path_is_refused(self):
        target = self.path("target.db")
        with open(target, "wb") as fh:
            fh.write(b"x" * 100)
        link = self.path("link.db")
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError, AttributeError):
            link = None
        os.mkdir(self.path("dir.db"))
        for candidate in [c for c in (link, self.path("dir.db")) if c]:
            with self.assertLogs("avrana_home", "WARNING"):
                c = self.make(SharedCache, path=candidate)
            self.assertIsNone(c.path)
        with open(target, "rb") as fh:
            self.assertEqual(fh.read(), b"x" * 100)                        # the link target is untouched

    def test_creation_is_exclusive_even_if_the_file_appears_after_the_check(self):
        from unittest import mock
        p = self.path("race.db")
        with open(p, "wb") as fh:
            fh.write(b"appeared after the check" * 20)
        with mock.patch.object(DisposableCache, "_prepare_path", lambda *a, **k: None):
            with self.assertLogs("avrana_home", "WARNING"):
                c = self.make(SharedCache, path=p)
        self.assertIsNone(c.path)
        with open(p, "rb") as fh:
            self.assertTrue(fh.read().startswith(b"appeared after the check"))

    def test_our_own_leftover_file_is_replaced(self):
        p = self.path("own.db")
        con = sqlite3.connect(p)
        con.execute("PRAGMA application_id=%d" % DisposableCache.APPLICATION_ID)
        con.execute("CREATE TABLE leftover(x)")
        con.commit()
        con.close()
        c = self.make(SharedCache, path=p)
        self.assertEqual(c.path, p)
        con = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro", uri=True)
        try:
            names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        finally:
            con.close()
        self.assertNotIn("leftover", names)

    def test_an_empty_leftover_file_is_replaced_and_close_removes_the_file(self):
        p = self.path("empty.db")
        open(p, "wb").close()
        c = self.make(SharedCache, path=p)
        self.assertEqual(c.path, p)
        self.assertTrue(os.path.exists(p))
        c.close()
        self.assertFalse(os.path.exists(p))
        self.assertEqual([f for f in os.listdir(self.tmp)], [])

    def test_pragmas_and_schema_names(self):
        c = self.make(path=self.path("pr.db"))
        self.assertEqual(c._conn.execute("PRAGMA temp_store").fetchone()[0], 2)          # MEMORY
        self.assertEqual(c._conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "memory")
        self.assertEqual(c._conn.execute("PRAGMA application_id").fetchone()[0], DisposableCache.APPLICATION_ID)
        listing = {name: file for _, name, file in c._conn.execute("PRAGMA database_list").fetchall()}
        self.assertEqual(listing["member"], "")                      # member data has no file at all
        self.assertTrue(listing["main"].endswith("pr.db"))
        self.assertEqual(listing.get("temp", ""), "")
        self.assertEqual([f for f in os.listdir(self.tmp) if f != "pr.db"], [])

    def test_purge_with_widened_persist_classes_clears_main_too(self):
        c = self.make(path=self.path("w.db"), persist_classes=frozenset({"catalogue", "member_progress"}))
        p = make_principal("member-a")
        c.for_member(p).set("jellyfin", "x", "v", 100)
        self.assertEqual(c._conn.execute("SELECT count(*) FROM main.entries").fetchone()[0], 1)
        self.assertEqual(c.purge_member(p), 1)
        self.assertEqual(c._conn.execute("SELECT count(*) FROM main.entries").fetchone()[0], 0)


class N15RefusedSets(CacheBase):
    def test_a_refused_set_removes_the_previous_value(self):
        c = self.make(member_max_bytes=1000)
        s = c.for_member(make_principal("member-a"))
        s.set("jellyfin", "x", "old", 100)
        s.set("jellyfin", "x", "new", 0)
        self.assertIsNone(s.get("jellyfin", "x"))
        s.set("jellyfin", "y", "old", 100)
        s.set("jellyfin", "y", "z" * 5000, 100)                      # over quota
        self.assertIsNone(s.get("jellyfin", "y"))
        s.set("jellyfin", "w", "old", 100)
        s.set("jellyfin", "w", object(), 100)                        # unencodable
        self.assertIsNone(s.get("jellyfin", "w"))

    def test_nan_and_infinite_ttl_are_refused_without_a_rebuild(self):
        c = self.make()
        s = c.for_member(make_principal("member-a"))
        rebuilds = []
        original = c._open
        c._open = lambda: (rebuilds.append(1), original())[1]
        s.set("jellyfin", "keep", "v", 100)
        for ttl in (float("nan"), float("inf"), float("-inf")):
            s.set("jellyfin", "x", "v", ttl)
            self.assertIsNone(s.get("jellyfin", "x"), ttl)
        self.assertEqual(rebuilds, [])
        self.assertEqual(s.get("jellyfin", "keep"), "v")


class N10EvictionPriority(CacheBase):
    def test_a_members_mapping_outlives_their_section_and_artwork_entries(self):
        c = self.make(member_max_entries=4)
        s = c.for_member(make_principal("member-a"))
        s.set("jellyfin", "mapping", ("absent", "x"), 5, data_class="member_mapping")      # oldest-expiring
        s.set("jellyfin", "continue", "c", 50, data_class="member_progress")
        s.set("jellyfin", "recent", "r", 60, data_class="member_progress")
        s.set("jellyfin", "art", "a", 70, data_class="artwork")
        s.set("jellyfin", "item", "i", 80, data_class="member_progress")                    # forces one eviction
        self.assertIsNotNone(s.get("jellyfin", "mapping"))
        self.assertIsNone(s.get("jellyfin", "art"))                  # artwork goes first, then older sections
        s.set("jellyfin", "more", "m", 90, data_class="member_progress")
        self.assertIsNotNone(s.get("jellyfin", "mapping"))


if __name__ == "__main__":
    unittest.main()
