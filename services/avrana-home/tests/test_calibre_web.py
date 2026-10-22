"""Calibre-Web adapter: one section ("Recently added") through OPDS, a SHARED VIEW of one viewer account.
Proven against HAND-WRITTEN fixtures that are unverified against any real server. Offline, synthetic data
only. Live compatibility is UNPROVEN."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import json
import logging
import unittest

from avrana_home.adapters.calibre_web import (ALLOWED_ROUTES, SHARED_VIEWER, CalibreWebAdapter,
                                              GuardedTransport, parse_feed)
from avrana_home.contract import ForbiddenRequest, Kind, SectionState, Service
from avrana_home.resilience import MAX_IMAGE_BYTES, MAX_JSON_BYTES, FakeClock, UpstreamMalformed, UrllibTransport
from tests.fake_calibre_web import FIXTURES, PNG, FakeCalibreWeb
from tests.fake_jellyfin import FakeOpener, FakeTransport
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-books")
TOKEN = "SENTINEL-CWA-PASSWORD-0000"
THREE, TWO, ONE = "Synthetic Book Three", "Synthetic Book Two", "Synthetic Book One"


def titles(result):
    return [i.title for i in result.items]


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeCalibreWeb(self.clock)
        self.transport = FakeTransport(self.fake)
        self.adapter = CalibreWebAdapter(self.transport, clock=self.clock, owner_confirms_no_member_restrictions=True)
        self.a = make_principal("member-a", GROUPS)
        self.b = make_principal("member-b", GROUPS)
        self.c = make_principal("member-c", GROUPS)

    def reset(self):
        self.fake.overrides.clear()
        self.fake.requests.clear()
        self.adapter.cache.clear()
        self.adapter.breaker.success(self.adapter.breaker.acquire())

    def serve(self, xml):
        self.fake.overrides["/opds/new"] = ("body", xml.encode("utf-8") if isinstance(xml, str) else xml)


class States(Base):
    def test_a_member_with_the_group_sees_the_shared_catalogue_newest_first(self):
        r = self.adapter.recent_items(self.a)
        self.assertEqual((r.state, titles(r)), (SectionState.OK, [THREE, TWO, ONE]))
        one = r.items[-1]
        self.assertIs(one.kind, Kind.EBOOK)
        self.assertEqual(one.id, "calibre-web:101")
        self.assertEqual(one.handoff_url, "https://books.avrana.net/book/101")
        self.assertEqual(one.subtitle, "Synthetic Author A")
        self.assertEqual((one.artwork.ref, one.artwork.alt), ("calibre-web/cover/101", f"Cover of {ONE}"))
        self.assertIsNone(one.progress_fraction)
        self.assertEqual(self.fake.paths(), ["/opds/new"])         # no mapping call: there is no member mapping

    def test_the_limit_is_clamped_and_applied(self):
        self.assertEqual(len(self.adapter.recent_items(self.a, limit=2).items), 2)
        self.assertEqual(len(self.adapter.recent_items(self.a, limit=10 ** 9).items), 3)
        self.assertEqual(len(self.adapter.recent_items(self.a, limit=-3).items), 3)

    def test_empty_feed_is_empty_and_markup_in_titles_stays_text(self):
        self.serve('<feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>')
        self.assertEqual(self.adapter.recent_items(self.a).state, SectionState.EMPTY)
        self.reset()
        self.serve(self.fake.feed.replace("Synthetic Book Two", "Two &lt;script&gt;x&lt;/script&gt;"))
        self.assertIn("Two <script>x</script>", titles(self.adapter.recent_items(self.a)))   # text; the UI escapes it

    def test_continue_item_and_search_are_not_offered_without_an_upstream_call(self):
        for r in (self.adapter.continue_items(self.a), self.adapter.item(self.a, "101")):
            self.assertEqual((r.state, r.reason), (SectionState.EMPTY, "not_offered"))
        self.assertEqual(self.fake.requests, [])
        self.assertEqual(self.adapter.search(self.a, "Synthetic").state, SectionState.OK)   # offered since AVR-383


class SharedViewAndIsolation(Base):
    """The honest statement of what 'two members' means here: one viewer account, one catalogue."""

    def test_every_member_with_the_group_is_mapped_to_the_same_fixed_non_member_viewer(self):
        users = {self.adapter.resolve_user(p).upstream_id for p in (self.a, self.b, self.c)}
        self.assertEqual(users, {SHARED_VIEWER})
        self.assertEqual(self.adapter.resolve_user(self.a).service, Service.CALIBRE_WEB)

    def test_two_members_get_the_same_catalogue_and_nothing_member_specific(self):
        ra, rb = self.adapter.recent_items(self.a), self.adapter.recent_items(self.b)
        self.assertEqual(ra.items, rb.items)
        for r in (ra, rb):
            blob = json.dumps(r.to_dict())
            for name in ("member-a", "member-b", SHARED_VIEWER):
                self.assertNotIn(name, blob)

    def test_the_cache_is_per_member_and_the_group_is_checked_before_it(self):
        self.adapter.recent_items(self.a)
        n = len(self.fake.requests)
        self.adapter.recent_items(self.a)
        self.assertEqual(len(self.fake.requests), n)                # served from a's cache
        self.adapter.recent_items(self.b)
        self.assertEqual(len(self.fake.requests), n + 1)            # b has its own entry
        outsider = make_principal("member-a", ("avrana-users", "avrana-videos"))
        self.assertIs(self.adapter.recent_items(outsider).state, SectionState.NOT_PERMITTED)
        self.assertEqual(len(self.fake.requests), n + 1)

    def test_no_per_account_feed_is_ever_requested(self):
        self.adapter.recent_items(self.a)
        self.adapter.fetch_artwork(self.a, "calibre-web/cover/101")
        for p in self.fake.paths():
            for banned in ("shelf", "read", "hot", "discover", "download", "user", "admin", "me"):
                self.assertNotIn(banned, p.replace("cover_240_240", "").replace("opds", ""), p)


class NoGroup(Base):
    def test_a_member_without_the_group_causes_no_upstream_call_and_leaks_nothing(self):
        outsider = make_principal("member-b", ("avrana-users", "avrana-videos"))
        for r in (self.adapter.recent_items(outsider), self.adapter.continue_items(outsider),
                  self.adapter.item(outsider, "101")):
            self.assertEqual((r.state, r.items), (SectionState.NOT_PERMITTED, ()))
            self.assertNotIn("Synthetic", repr(r.to_dict()))
        self.assertIs(self.adapter.fetch_artwork(outsider, "calibre-web/cover/101").state,
                      SectionState.NOT_PERMITTED)
        self.assertIsNone(self.adapter.resolve_user(outsider))
        self.assertEqual(self.fake.requests, [])
        self.adapter.fetch_artwork(self.a, "calibre-web/cover/101")        # a warm artwork cache is not served either
        n = len(self.fake.requests)
        self.assertIs(self.adapter.fetch_artwork(outsider, "calibre-web/cover/101").state, SectionState.NOT_PERMITTED)
        self.assertEqual(len(self.fake.requests), n)


class Artwork(Base):
    def test_a_member_with_the_group_gets_the_cover(self):
        r = self.adapter.fetch_artwork(self.a, "calibre-web/cover/101")
        self.assertEqual((r.state, r.content_type, r.data), (SectionState.OK, "image/png", PNG))
        self.assertEqual(self.fake.paths(), ["/opds/cover_240_240/101"])

    def test_a_cover_the_viewer_cannot_see_is_empty_and_never_counted(self):
        r = self.adapter.fetch_artwork(self.a, "calibre-web/cover/999")
        self.assertEqual((r.state, r.content_type, r.data), (SectionState.EMPTY, None, b""))
        self.assertEqual("unknown", self.adapter.health().state)   # artwork is neutral for the circuit

    def test_hostile_or_foreign_refs_are_empty_and_never_interpolated(self):
        for ref in ("calibre-web/cover/../../admin", "calibre-web/cover/1/../2", "calibre-web/cover/1?x=1",
                    "calibre-web/cover/1234567890", "calibre-web/cover/", "calibre-web/cover/abc",
                    "komga/book/BOOKAAAA0001", "jellyfin/primary/x", "https://evil.invalid/x",
                    "calibre-web/download/101", "calibre-web/cover/١٢٣"):
            self.assertEqual(self.adapter.fetch_artwork(self.a, ref).state, SectionState.EMPTY, ref)
        self.assertEqual(self.fake.requests, [])

    def test_bad_images_are_unavailable_not_exceptions(self):
        for image in ((200, b"<html>", "text/html"), (200, b"not a png", "image/png"),
                      (200, PNG + b"x" * (MAX_IMAGE_BYTES + 1), "image/png")):
            self.reset()
            self.fake.image = image
            self.assertEqual(self.adapter.fetch_artwork(self.a, "calibre-web/cover/101").state,
                             SectionState.UNAVAILABLE, image[2])

    def test_a_cached_cover_is_per_member(self):
        self.adapter.fetch_artwork(self.a, "calibre-web/cover/101")
        n = len(self.fake.requests)
        self.adapter.fetch_artwork(self.a, "calibre-web/cover/101")
        self.assertEqual(len(self.fake.requests), n)
        self.adapter.fetch_artwork(self.b, "calibre-web/cover/101")
        self.assertEqual(len(self.fake.requests), n + 1)


class Feed(Base):
    """Untrusted XML and untrusted links."""

    def test_links_that_are_not_relative_paths_never_become_ids_or_urls(self):
        evil = self.fake.feed.replace('href="/opds/cover/101"', 'href="https://evil.invalid/opds/cover/101"') \
            .replace('href="/opds/cover_240_240/101"', 'href="//evil.invalid/opds/cover_240_240/101"') \
            .replace('href="/opds/download/101/epub/"', 'href="javascript:alert(1)"')
        self.serve(evil)
        r = self.adapter.recent_items(self.a)
        self.assertEqual(titles(r), [THREE, TWO])                      # the book with no usable relative link is left out
        self.assertNotIn("evil", json.dumps(r.to_dict()))

    def test_links_that_disagree_about_the_id_leave_the_entry_out(self):
        self.serve(self.fake.feed.replace('href="/opds/download/101/epub/"', 'href="/opds/download/555/epub/"'))
        self.assertEqual(titles(self.adapter.recent_items(self.a)), [THREE, TWO])

    def test_if_every_entry_is_unusable_the_section_is_drift_never_empty(self):
        self.serve(self.fake.feed.replace("/opds/", "/x/"))
        r = self.adapter.recent_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamMalformed"))

    def test_doctype_entities_and_external_references_are_refused_before_parsing(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
                '<feed xmlns="http://www.w3.org/2005/Atom"><title>&b;</title></feed>')
        xxe = ('<?xml version="1.0"?><!DOCTYPE feed SYSTEM "file:///etc/passwd">'
               '<feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>')
        for body in (bomb, xxe, xxe.lower().replace("doctype", "DocType")):
            self.reset()
            self.serve(body)
            self.assertIs(self.adapter.recent_items(self.a).state, SectionState.UNAVAILABLE)
            with self.assertRaises(UpstreamMalformed):
                parse_feed(body.encode())

    def test_not_a_feed_is_unavailable_not_an_exception(self):
        for body in (b"<html><body>Sign in</body></html>", b"not xml", b"", b"\xff\xfe\x00", b"<feed>", b"{}",
                     b"<rss/>", b"<" * 100000, b"<a>" * 200000, b'<feed xmlns="urn:other"/>'):
            self.reset()
            self.serve(body)
            self.assertIs(self.adapter.recent_items(self.a).state, SectionState.UNAVAILABLE, body[:12])

    def test_a_feed_with_too_many_entries_is_misbehaviour(self):
        entry = self.fake.feed.split("<entry>")[1].split("</entry>")[0]
        self.serve(self.fake.feed.replace("</feed>", ("<entry>" + entry + "</entry>") * 101 + "</feed>"))
        self.assertEqual(self.adapter.recent_items(self.a).reason, "UpstreamMisbehaved")


class Failures(Base):
    def test_unreachable_costs_the_section_only_and_never_raises(self):
        for exc in (ConnectionRefusedError("refused"), OSError("unreachable"), TimeoutError()):
            self.reset()
            self.fake.overrides["/opds/new"] = ("raise", exc)
            r = self.adapter.recent_items(self.a)
            self.assertEqual((r.state, r.items), (SectionState.UNAVAILABLE, ()), exc)

    def test_a_timeout_costs_the_section_only_and_a_warm_cache_still_serves(self):
        self.adapter.recent_items(self.a)
        self.fake.slow["/opds/new"] = 5.0
        self.assertEqual(self.adapter.recent_items(self.a).state, SectionState.OK)       # cache hit
        self.assertEqual(self.adapter.recent_items(self.b).reason, "UpstreamTimeout")

    def test_401_403_404_and_5xx_are_unavailable(self):
        for code in (401, 403, 404, 429, 500, 503):
            self.reset()
            self.fake.overrides["/opds/new"] = ("status", code)
            self.assertIs(self.adapter.recent_items(self.a).state, SectionState.UNAVAILABLE, code)

    def test_an_oversized_body_is_unavailable_and_counted(self):
        self.serve(b" " * (MAX_JSON_BYTES + 1))
        r = self.adapter.recent_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamTooLarge"))
        self.assertEqual(self.adapter.health().state, "failing")

    def test_a_breaker_trip_stops_all_traffic_for_every_member_until_the_cool_off(self):
        self.fake.overrides["/opds/new"] = ("raise", ConnectionRefusedError())
        for p in (self.a, self.b, self.c):
            self.adapter.recent_items(p)
        self.assertEqual(self.adapter.health().state, "cooling_off")
        n = len(self.fake.requests)
        d = make_principal("member-d", GROUPS)
        self.assertEqual(self.adapter.recent_items(d).reason, "cooling_off")
        self.assertEqual(len(self.fake.requests), n)
        self.fake.overrides.clear()
        self.clock.advance(61)
        self.assertIs(self.adapter.recent_items(d).state, SectionState.OK)                # the trial succeeds

    def test_a_404_on_the_feed_is_route_drift_and_opens_the_circuit_after_three(self):
        self.fake.overrides["/opds/new"] = ("status", 404)
        reasons = [self.adapter.recent_items(p).reason for p in (self.a, self.b, self.c)]
        self.assertEqual(reasons, ["RouteMissing"] * 3)
        self.assertEqual(self.adapter.health().state, "cooling_off")


class GuardAndSecrets(Base):
    def test_only_get_on_two_routes_and_nothing_per_account(self):
        g = GuardedTransport(self.transport).bind(SHARED_VIEWER)
        for method, path, query in (("POST", "/opds/new", None), ("GET", "/opds/shelf", None),
                                    ("GET", "/opds/shelfdetail/1", None), ("GET", "/opds/readbooks", None),
                                    ("GET", "/opds/download/101/epub/", None), ("GET", "/opds/cover/101", None),
                                    ("GET", "/opds/search/x", None), ("GET", "/admin/user/new", None),
                                    ("GET", "/opds/new", {"offset": "1"}), ("GET", "/opds/cover_240_240/1/../2", None),
                                    ("GET", "/opds/cover_240_240/%2e", None), ("GET", "/opds/cover_240_240/1", {"a": "b"})):
            with self.assertRaises(ForbiddenRequest, msg=(method, path)):
                g.request(method, path, query, 1.0, 1000)
        with self.assertRaises(ForbiddenRequest):
            GuardedTransport(self.transport).bind(None).request("GET", "/opds/new", None, 1.0, 1000)
        with self.assertRaises(ForbiddenRequest):
            GuardedTransport(self.transport).bind("member-a")      # only the fixed shared viewer can be bound
        self.assertEqual([r.name for r in ALLOWED_ROUTES], ["new", "search", "cover"])
        self.assertEqual(self.fake.requests, [])

    def test_the_credential_is_never_in_a_repr_a_result_a_health_report_or_a_log_line(self):
        opener = FakeOpener(self.fake)
        transport = UrllibTransport("https://books.invalid", {"Authorization": "Basic " + TOKEN}, opener=opener)
        ad = CalibreWebAdapter(transport, clock=self.clock, owner_confirms_no_member_restrictions=True)
        with self.assertLogs("avrana_home", level=logging.WARNING) as logs:
            logging.getLogger("avrana_home").warning("probe")
            ok = ad.recent_items(self.a)
            self.fake.overrides["/opds/new"] = ("status", 401)
            ad.cache.clear()
            bad = ad.recent_items(self.a)
        blob = " ".join([repr(ad), repr(ok), repr(bad), repr(ad.health()), repr(ad._guard),
                         json.dumps(ok.to_dict()), *logs.output])
        self.assertNotIn(TOKEN, blob)
        self.assertTrue(opener.seen_headers)                       # the requests went out through the transport

    def test_logs_carry_no_username_title_or_id(self):
        self.fake.overrides["/opds/new"] = ("status", 500)
        with self.assertLogs("avrana_home", level=logging.WARNING) as logs:
            self.adapter.recent_items(self.b)
        text = " ".join(logs.output)
        for secret in ("member-b", "Synthetic", "101", SHARED_VIEWER):
            self.assertNotIn(secret, text)

    def test_fixtures_declare_their_target_version_and_which_shapes_are_synthetic(self):
        files = sorted(FIXTURES.glob("*.json"))
        self.assertEqual(len(files), 2)
        for f in files:
            doc = json.loads(f.read_text(encoding="utf-8"))
            self.assertTrue(doc["_synthetic"].startswith("Hand-written SYNTHETIC"), f.name)
            self.assertIn("Calibre-Web", doc["_target_version"], f.name)
            self.assertIn("NOT confirmed", doc["_target_version"], f.name)
            self.assertIn("SYNTHETIC assumption", doc["_provenance"], f.name)
            self.assertIn("UNPROVEN", doc["_provenance"], f.name)



class ReviewOf39(Base):
    """Independent review of #39: UTF-16 hid a DOCTYPE from the byte check; nesting was unbounded; the
    shared-view invariant lived only in docs; a query string on /opds/new was never tested."""

    DOCTYPE = ('<?xml version="1.0" encoding="utf-16"?><!DOCTYPE f [<!ENTITY a "EXPANDED">]>'
               '<feed xmlns="http://www.w3.org/2005/Atom"><title>&a;</title></feed>')

    def test_utf16_and_nul_bodies_are_refused_before_parsing(self):
        for body in (self.DOCTYPE.encode("utf-16"), self.DOCTYPE.encode("utf-16-le"),
                     self.DOCTYPE.encode("utf-16-be"), self.DOCTYPE.encode("utf-32"), b"<feed>\x00</feed>"):
            with self.assertRaises(UpstreamMalformed):
                parse_feed(body)

    def test_a_utf8_bom_is_still_accepted(self):
        body = b"\xef\xbb\xbf" + b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        self.assertTrue(parse_feed(body).tag.endswith("feed"))

    def test_deep_nesting_is_bounded(self):
        body = (b'<feed xmlns="http://www.w3.org/2005/Atom">' + b"<x>" * 6000 + b"</x>" * 6000 + b"</feed>")
        with self.assertRaises(UpstreamMalformed):
            parse_feed(body)

    def test_the_adapter_refuses_to_exist_without_the_owner_confirming_the_shared_view(self):
        for value in (False, None, 1, "yes"):
            with self.assertRaises(ValueError):
                CalibreWebAdapter(self.transport, clock=self.clock, owner_confirms_no_member_restrictions=value)
        with self.assertRaises(ValueError):
            CalibreWebAdapter(self.transport, clock=self.clock)

    def test_a_query_string_on_the_new_feed_is_forbidden(self):
        with self.assertRaises(ForbiddenRequest):
            GuardedTransport(self.transport).request("GET", "/opds/new", {"q": "x"}, 2.0, MAX_JSON_BYTES)


if __name__ == "__main__":
    unittest.main()
