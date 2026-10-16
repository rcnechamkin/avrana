"""Authorized cross-library search (AVR-383): adapters and aggregate. Offline, synthetic data only; every
upstream is a fake serving HAND-WRITTEN fixtures that are unverified against any real server."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import json
import logging
import unittest

from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.adapters.calibre_web import CalibreWebAdapter
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.adapters.komga import KomgaAdapter
from avrana_home.aggregate import health_summary, search
from avrana_home.contract import MAX_QUERY, MAX_QUERY_RAW, SectionResult, SectionState, Service, clean_query
from avrana_home.resilience import MAX_JSON_BYTES, FakeClock
from tests.fake_abs import FakeAudiobookshelf
from tests.fake_calibre_web import FakeCalibreWeb
from tests.fake_jellyfin import FakeJellyfin, FakeTransport
from tests.fake_komga import FakeKomga
from tests.helpers import make_principal

ALL = ("avrana-users", "avrana-videos", "avrana-audiobooks", "avrana-comics", "avrana-books")
SENTINEL = "zzqxsentineltermzz"


def names(result):
    return sorted(i.title for i in result.items)


class Setup(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.jf, self.kg = FakeJellyfin(self.clock), FakeKomga(self.clock)
        self.cw, self.ab = FakeCalibreWeb(self.clock), FakeAudiobookshelf(self.clock)
        self.jellyfin = JellyfinAdapter(FakeTransport(self.jf), clock=self.clock)
        self.komga = KomgaAdapter(FakeTransport(self.kg), clock=self.clock,
                                  owner_confirms_no_member_restrictions=True)
        self.calibre = CalibreWebAdapter(FakeTransport(self.cw), clock=self.clock,
                                         owner_confirms_no_member_restrictions=True)
        self.abs = AudiobookshelfAdapter(FakeTransport(self.ab), clock=self.clock)
        self.adapters = [self.jellyfin, self.abs, self.komga, self.calibre]
        self.fakes = [self.jf, self.ab, self.kg, self.cw]
        self.a, self.b, self.c = (make_principal(f"member-{x}", ALL) for x in "abc")

    def calls(self):
        return sum(len(f.requests) for f in self.fakes)

    def by_service(self, res):
        return {s.service: s for s in res.sections}


class CleanQuery(unittest.TestCase):
    def test_what_a_term_becomes(self):
        for raw, want in (("hello  world", "hello world"), ("  ab ", "ab"), ("ab\x00c", "abc"), ("a*b", "a b"),
                          ("%27 OR 1=1", "27 OR 1=1"), ("café", "café"), ("café", "café"),
                          ("‮evil", "evil"), ("zero​width", "zerowidth"), ("a\nb\tc", "a b c"),
                          ("../../etc/passwd", "../../etc/passwd"), ("a?b[c]d", "a b c d"),
                          ("x" * 150, "x" * MAX_QUERY), ("\U0001f600smile", "\U0001f600smile")):
            self.assertEqual(clean_query(raw), want, repr(raw))

    def test_what_is_refused(self):
        for raw in (None, 5, b"abc", ["abc"], "", " ", "a", "*", "**", "%%", "\x00\x00", "x" * (MAX_QUERY_RAW + 1),
                    "​​", "_ _"):
            self.assertIsNone(clean_query(raw), repr(raw))
        self.assertEqual(clean_query("x" * MAX_QUERY_RAW), "x" * MAX_QUERY)


class NoGroup(Setup):
    def test_a_member_without_the_group_causes_no_upstream_call_for_any_query_and_leaks_nothing(self):
        outsider = make_principal("member-a", ("avrana-users",))
        for term in ("Synthetic", "*", "", "x" * 1000, None, "../../x"):
            for ad in self.adapters:
                r = ad.search(outsider, term)
                self.assertEqual((r.state, r.items), (SectionState.NOT_PERMITTED, ()), (ad, term))
        res = search(outsider, self.adapters, "Synthetic")
        self.assertEqual(self.calls(), 0)
        self.assertEqual(res.search_view(), {"status": "ok", "entitled": False, "groups": []})

    def test_each_service_needs_its_own_group_and_a_revoked_group_acts_on_the_next_search(self):
        comics_only = make_principal("member-a", ("avrana-users", "avrana-comics"))
        res = search(comics_only, self.adapters, "Synthetic")
        view = res.search_view()
        self.assertEqual([g["service"] for g in view["groups"]], ["komga"])
        self.assertTrue(view["entitled"])
        self.assertEqual(len(self.jf.requests) + len(self.cw.requests) + len(self.ab.requests), 0)
        search(self.a, self.adapters, "Synthetic")                          # warm everything for the same name
        before = self.calls()
        revoked = make_principal("member-a", ("avrana-users",))
        self.assertEqual(search(revoked, self.adapters, "Synthetic").search_view()["groups"], [])
        self.assertEqual(self.calls(), before)


class HostileQueries(Setup):
    HOSTILE = ("../../Users/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "a/../b", "%2e%2e%2fadmin", "..\\..\\x",
               "Synthetic\r\nX-Evil: 1", "Synthetic\x00admin", "café ‮", "Synthetic" + "​" * 5,
               "Synthetic*", "S*", "%", "' OR '1'='1", "Synthetic; DROP", "{{7*7}}", "<script>x</script>", "?&=#")

    def test_the_term_only_ever_travels_as_a_query_parameter_never_in_a_path(self):
        for term in self.HOSTILE:
            for ad in self.adapters:
                ad.cache.clear()
                ad.breaker.success(ad.breaker.acquire())
            for f in self.fakes:
                f.requests.clear()
            res = search(self.a, self.adapters, term)
            cleaned = clean_query(term)
            for f in self.fakes:
                for method, path, query in f.requests:
                    self.assertEqual(method, "GET")
                    self.assertNotIn(cleaned or "\x00", path, term)         # never interpolated
                    for ch in ("\r", "\n", "\x00", "*", "%", "‮", "​"):
                        self.assertNotIn(ch, path + json.dumps(query), repr(term))
                    for key in ("searchTerm", "search", "query", "q"):
                        if key in query:
                            self.assertEqual(query[key], cleaned, term)
            self.assertIn(res.status, ("ok", "invalid_query"))

    def test_unusable_terms_ask_nobody_and_are_reported_as_such(self):
        for term in ("*", "x" * (MAX_QUERY_RAW + 1), "", None, 5, "\x00\x00", "a"):
            res = search(self.a, self.adapters, term)
            self.assertEqual(res.search_view(), {"status": "invalid_query", "entitled": True, "groups": []})
            for ad in self.adapters:
                r = ad.search(self.a, term)
                self.assertEqual((r.state, r.reason), (SectionState.EMPTY, "invalid_query"))
        self.assertEqual(self.calls(), 0)

    def test_a_long_term_is_bounded_before_it_is_sent(self):
        search(self.a, self.adapters, "Synthetic " * 20)                   # 200 characters in, 100 out
        sent = [q[k] for f in self.fakes for _, _, q in f.requests for k in ("searchTerm", "search", "query", "q") if k in q]
        self.assertTrue(sent)
        self.assertTrue(all(len(t) <= MAX_QUERY for t in sent))

    def test_unicode_terms_work_and_are_normalised(self):
        res = search(self.a, self.adapters, "café Synthetic")
        self.assertEqual(res.status, "ok")
        sent = [q[k] for f in self.fakes for _, _, q in f.requests for k in ("searchTerm", "search", "query", "q") if k in q]
        self.assertTrue(all(t == "café Synthetic" for t in sent))


class MemberSafety(Setup):
    def test_two_members_get_different_results_for_the_same_term(self):
        ra, rb = self.jellyfin.search(self.a, "Synthetic"), self.jellyfin.search(self.b, "Synthetic")
        self.assertEqual((ra.state, rb.state), (SectionState.OK, SectionState.OK))
        self.assertTrue(names(ra) and names(rb))
        self.assertEqual(set(names(ra)) & {"Synthetic Film Two", "Synthetic Film Four"}, set())
        self.assertEqual(set(names(rb)) & {"Synthetic Film One", "Synthetic Film Three"}, set())
        self.assertNotEqual(names(ra), names(rb))

    def test_komga_search_is_the_shared_view_and_the_flag_is_required(self):
        """Komga is a shared regular-account view (contract 12.2, owner decision 2026-10-15): every comics
        member gets the same answer; Komga applies the one account's library sharing upstream."""
        self.assertEqual(names(self.komga.search(self.a, "Synthetic")), names(self.komga.search(self.c, "Synthetic")))
        self.assertEqual(names(self.komga.search(self.a, "Kids")), ["Synthetic Kids One"])
        self.assertEqual(self.komga.search(self.a, "nothingmatches").state, SectionState.EMPTY)
        self.assertEqual([p for p in self.kg.paths() if "users" in p or "series" in p], [])
        with self.assertRaises(ValueError):
            KomgaAdapter(FakeTransport(self.kg), clock=self.clock)

    def test_a_cover_from_a_komga_search_result_is_fetched_through_the_shared_account(self):
        item = self.komga.search(self.b, "Comic One").items[0]
        self.assertEqual(self.komga.fetch_artwork(self.b, item.artwork.ref).state, SectionState.OK)
        self.kg.overrides[f"/api/v1/books/{item.id.split(':', 1)[1]}/thumbnail"] = ("status", 404)
        self.komga.cache.clear()
        self.assertEqual(self.komga.fetch_artwork(self.b, item.artwork.ref).state, SectionState.EMPTY)

    def test_calibre_search_is_the_shared_view_and_the_flag_is_required(self):
        self.assertEqual(names(self.calibre.search(self.a, "Synthetic")), names(self.calibre.search(self.b, "Synthetic")))
        self.assertEqual(names(self.calibre.search(self.a, "Unrelated")), ["Unrelated Tome"])
        self.assertEqual(self.calibre.search(self.a, "nothingmatches").state, SectionState.EMPTY)
        with self.assertRaises(ValueError):
            CalibreWebAdapter(FakeTransport(self.cw), clock=self.clock)

    def test_audiobookshelf_search_applies_each_members_own_rights(self):
        # member-a: lib_aaa only, no explicit; member-b: everything; member-c: tag "mature" denied
        self.assertNotIn("Synthetic Audiobook Three", names(self.abs.search(self.a, "Synthetic", limit=50)))
        self.assertNotIn("Synthetic Audiobook Four", names(self.abs.search(self.a, "Synthetic", limit=50)))
        self.assertIn("Synthetic Audiobook Three", names(self.abs.search(self.b, "Synthetic", limit=50)))
        self.assertEqual(names(self.abs.search(self.c, "Audiobook Five")), [])
        self.assertEqual(names(self.abs.search(self.b, "Audiobook Five")), ["Synthetic Audiobook Five"])
        res = search(self.a, self.adapters, "Synthetic")
        group = next(g for g in res.search_view()["groups"] if g["service"] == "audiobookshelf")
        self.assertEqual(group["state"], "ok")
        self.assertTrue(all(p.startswith("/api/") for p in self.ab.paths()))

    def test_jellyfin_search_is_user_scoped_in_the_path_and_never_the_unbound_list(self):
        self.jellyfin.search(self.a, "Synthetic")
        paths = self.jf.paths()
        self.assertEqual(paths[0], "/Users")                                # the mapping list, once
        self.assertRegex(paths[1], r"^/Users/[0-9a-f]{32}/Items$")
        self.assertEqual(len(paths), 2)


class NoCacheNoLog(Setup):
    def test_search_is_never_cached(self):
        for ad in (self.jellyfin, self.komga, self.calibre):
            ad.search(self.a, "Synthetic")
            n = self.calls()
            ad.search(self.a, "Synthetic")
            self.assertGreater(self.calls(), n, ad)                          # the upstream is asked again
        for ad in (self.jellyfin, self.komga, self.calibre):
            scope = ad.cache.for_member(self.a)
            self.assertIsNone(scope.get(ad.service.value, "search"))
            self.assertIsNone(scope.get(ad.service.value, "search:12"))

    def test_the_term_never_appears_in_logs_health_or_results(self):
        self.kg.overrides["/api/v1/books"] = ("status", 500)
        self.jf.overrides["/Users"] = ("raise", ConnectionRefusedError(SENTINEL))
        self.cw.overrides["/opds/search"] = ("body", ("<feed>" + SENTINEL).encode())
        with self.assertLogs("avrana_home", level=logging.DEBUG) as logs:
            logging.getLogger("avrana_home").warning("probe")
            res = search(self.a, self.adapters, SENTINEL)
        blob = " ".join(logs.output) + json.dumps(health_summary(self.adapters)) + json.dumps(res.search_view())
        blob += " ".join(repr(s) for s in res.sections)
        self.assertNotIn(SENTINEL, blob)
        self.assertNotIn(SENTINEL.upper(), blob.upper().replace("PROBE", ""))


class Failures(Setup):
    def states(self, term="Synthetic"):
        return {s.service: s for s in search(self.a, self.adapters, term).sections}

    def test_one_service_down_still_returns_the_others(self):
        self.kg.overrides["/api/v1/books"] = ("raise", ConnectionRefusedError())
        res = self.states()
        self.assertEqual(res[Service.KOMGA].state, SectionState.UNAVAILABLE)
        self.assertEqual(res[Service.JELLYFIN].state, SectionState.OK)
        self.assertEqual(res[Service.CALIBRE_WEB].state, SectionState.OK)
        view = search(self.a, self.adapters, "Synthetic").search_view()
        states = {g["service"]: g["state"] for g in view["groups"]}
        self.assertEqual(states["komga"], "unavailable")
        self.assertEqual((states["jellyfin"], states["calibre-web"]), ("ok", "ok"))

    def test_no_match_is_empty_and_an_outage_is_unavailable_never_the_same(self):
        none = {g["service"]: g["state"] for g in search(self.a, self.adapters, "nomatchatall").search_view()["groups"]}
        self.assertEqual(set(none.values()), {"empty"})
        self.assertIn("audiobookshelf", none)
        self.jellyfin.cache.clear()                                         # forget the cached mapping
        self.jf.overrides["/Users"] = ("status", 500)
        down = {g["service"]: g["state"] for g in search(self.a, self.adapters, "nomatchatall").search_view()["groups"]}
        self.assertEqual(down["jellyfin"], "unavailable")

    def test_unlinked_is_its_own_state(self):
        stranger = make_principal("member-zzz", ALL)
        view = search(stranger, self.adapters, "Synthetic").search_view()
        states = {g["service"]: g["state"] for g in view["groups"]}
        self.assertEqual(states["jellyfin"], "not_linked")
        self.assertEqual(states["komga"], "ok")                             # a shared view has no mapping
        self.assertEqual(states["calibre-web"], "ok")                       # a shared view has no mapping

    def test_every_upstream_failure_is_a_state_on_every_searching_adapter(self):
        cases = {(self.jellyfin, self.jf): "/Users", (self.komga, self.kg): "/api/v1/books",
                 (self.calibre, self.cw): "/opds/search"}
        for (ad, fake), path in cases.items():
            for kind, val in (("status", 401), ("status", 403), ("status", 404), ("status", 500), ("status", 429),
                              ("raise", ConnectionRefusedError()), ("raise", TimeoutError()),
                              ("body", b"not json or xml"), ("body", b"\xff\xfe"), ("body", b"null"),
                              ("body", b" " * (MAX_JSON_BYTES + 1))):
                fake.overrides.clear()
                ad.cache.clear()
                ad.breaker.success(ad.breaker.acquire())
                fake.overrides[path] = (kind, val)
                r = ad.search(self.a, "Synthetic")
                self.assertIsInstance(r, SectionResult)
                self.assertIn(r.state, (SectionState.UNAVAILABLE, SectionState.NOT_LINKED, SectionState.EMPTY), (ad, kind, val))

    def test_a_breaker_trip_on_search_stops_traffic_and_recovers(self):
        self.cw.overrides["/opds/search"] = ("raise", ConnectionRefusedError())
        for p in (self.a, self.b, self.c):
            self.calibre.search(p, "Synthetic")
        self.assertEqual(self.calibre.health().state, "cooling_off")
        n = len(self.cw.requests)
        self.assertEqual(self.calibre.search(self.a, "Synthetic").reason, "cooling_off")
        self.assertEqual(len(self.cw.requests), n)
        self.cw.overrides.clear()
        self.clock.advance(61)
        self.assertEqual(self.calibre.search(self.a, "Synthetic").state, SectionState.OK)

    def test_the_result_count_is_bounded_and_an_upstream_that_ignores_the_limit_is_misbehaviour(self):
        self.assertLessEqual(len(self.komga.search(self.a, "Synthetic", limit=1).items), 1)
        self.assertLessEqual(len(self.jellyfin.search(self.a, "Synthetic", limit=10 ** 9).items), 50)
        many = {"Items": [{"Id": "aaaa%028d" % i, "Name": "Synthetic %d" % i, "Type": "Movie"} for i in range(60)]}
        self.jf.overrides["/Users/aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa/Items"] = ("body", json.dumps(many).encode())
        r = self.jellyfin.search(self.a, "Synthetic", limit=3)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamMisbehaved"))

    def test_a_programming_error_in_one_adapter_costs_that_group_only(self):
        class Boom(JellyfinAdapter):
            def search(self, principal, query, limit=12):
                raise RuntimeError("boom " + query)
        boom = Boom(FakeTransport(self.jf), clock=self.clock)
        with self.assertLogs("avrana_home", level=logging.WARNING) as logs:
            res = search(self.a, [boom, self.calibre], "Synthetic")
        got = {s.service: s for s in res.sections}
        self.assertEqual(got[Service.JELLYFIN].state, SectionState.UNAVAILABLE)
        self.assertEqual(got[Service.CALIBRE_WEB].state, SectionState.OK)
        self.assertNotIn("Synthetic", " ".join(logs.output))


class HardCap(Setup):
    def test_a_hung_service_costs_its_own_group_at_the_hard_cap_and_the_others_return(self):
        import threading
        release = threading.Event()

        class Hung(KomgaAdapter):
            def search(self, principal, query, limit=12):
                release.wait(5)
                return super().search(principal, query, limit)
        hung = Hung(FakeTransport(self.kg), clock=self.clock, owner_confirms_no_member_restrictions=True)
        try:
            res = search(self.a, [hung, self.calibre], "Synthetic", hard_cap=0.3)
        finally:
            release.set()
        got = {s.service: s for s in res.sections}
        self.assertEqual((got[Service.KOMGA].state, got[Service.KOMGA].reason), (SectionState.UNAVAILABLE, "hard_cap"))
        self.assertEqual(got[Service.CALIBRE_WEB].state, SectionState.OK)
        self.assertEqual(hung.health().state, "cooling_off")


class ViewShape(Setup):
    def test_the_search_view_has_its_own_shape_and_member_view_is_untouched(self):
        view = search(self.a, self.adapters, "Synthetic").search_view()
        self.assertEqual(set(view), {"status", "entitled", "groups"})
        for g in view["groups"]:
            self.assertEqual(set(g), {"service", "state", "items"})
            self.assertIn(g["state"], ("ok", "empty", "unavailable", "not_linked"))
            for item in g["items"]:
                self.assertEqual(set(item), {"id", "service", "kind", "title", "subtitle", "series", "progress",
                                             "artwork", "creator", "year", "handoff_url"})
                self.assertTrue(item["handoff_url"].startswith("https://"))
        self.assertNotIn("Synthetic", json.dumps({k: v for k, v in view.items() if k != "groups"}))
        self.assertTrue(any(g["items"] for g in view["groups"]))
        json.dumps(view)

    def test_the_term_is_not_echoed(self):
        self.assertNotIn(SENTINEL, json.dumps(search(self.a, self.adapters, SENTINEL).search_view()))


if __name__ == "__main__":
    unittest.main()
