"""Title pages and truthful search states (AVR-383/384), offline. Synthetic fixtures only; every upstream is a
fake serving HAND-WRITTEN data that is unverified against any real server.

Covers: the item lookup each adapter offers for a title page (two members, revoked group, hostile ids), the
`creator`/`year` fields, Audiobookshelf's every-library-404 search (unavailable, never "no matches"), and the
pure view-model rules for search states, the request fallback and the title page."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import unittest

from avrana_home.adapters._base import year_from
from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.adapters.calibre_web import CalibreWebAdapter
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.adapters.komga import KomgaAdapter
from avrana_home.aggregate import search
from avrana_home.app.routing import parse_title_route
from avrana_home.app.viewmodel import build_search, build_title, request_options, split_item_id
from avrana_home.contract import SectionState
from avrana_home.resilience import FakeClock
from tests.fake_abs import FakeAudiobookshelf
from tests.fake_calibre_web import FakeCalibreWeb
from tests.fake_jellyfin import FakeJellyfin, FakeTransport
from tests.fake_komga import FakeKomga
from tests.helpers import make_principal

ALL = ("avrana-users", "avrana-videos", "avrana-audiobooks", "avrana-comics", "avrana-books")
FILM_A = "aaaa0000000000000000000000000001"      # in member-a's resume list only, with a saved position
FILM_A3 = "aaaa0000000000000000000000000010"     # member-a's latest, no position, ProductionYear 2020
FILM_B = "bbbb0000000000000000000000000001"      # member-b only
HOSTILE_IDS = ("../" + FILM_A, FILM_A + "/../x", FILM_A.upper() + "%2f", FILM_A + "\r\nX: y", FILM_A + "\x00",
               "x" * 5000, "", None, 7, FILM_A + " ", "%2e%2e%2f")


class Setup(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.jf, self.kg = FakeJellyfin(self.clock), FakeKomga(self.clock)
        self.cw, self.ab = FakeCalibreWeb(self.clock), FakeAudiobookshelf(self.clock)
        self.jellyfin = JellyfinAdapter(FakeTransport(self.jf), clock=self.clock)
        self.komga = KomgaAdapter(FakeTransport(self.kg), clock=self.clock, owner_confirms_no_member_restrictions=True)
        self.calibre = CalibreWebAdapter(FakeTransport(self.cw), clock=self.clock,
                                         owner_confirms_no_member_restrictions=True)
        self.abs = AudiobookshelfAdapter(FakeTransport(self.ab), clock=self.clock)
        self.adapters = [self.jellyfin, self.abs, self.komga, self.calibre]
        self.a, self.b = make_principal("member-a", ALL), make_principal("member-b", ALL)


class ItemLookup(Setup):
    def test_jellyfin_title_is_the_members_own_with_their_own_position(self):
        a = self.jellyfin.item(self.a, FILM_A)
        self.assertEqual(a.state, SectionState.OK)
        self.assertGreater(a.items[0].position_seconds, 0)
        self.assertEqual(self.jellyfin.item(self.b, FILM_A).state, SectionState.EMPTY)    # hidden: same as unknown
        self.assertEqual(self.jellyfin.item(self.b, "f" * 32).state, SectionState.EMPTY)
        self.assertEqual(self.jellyfin.item(self.a, FILM_A3).items[0].year, 2020)

    def test_audiobookshelf_title_applies_the_members_own_rights_and_progress(self):
        a = self.abs.item(self.a, "li_book000001")
        self.assertEqual(a.state, SectionState.OK)
        self.assertEqual(a.items[0].position_seconds, 15120)                 # member-a's own entry
        self.assertEqual((a.items[0].creator, a.items[0].year), ("Synthetic Author", 2011))
        b = self.abs.item(self.b, "li_book000001")
        self.assertEqual(b.items[0].position_seconds, 2520)                  # member-b's own entry, not a's
        self.assertEqual(self.abs.item(self.a, "li_book000003").state, SectionState.EMPTY)   # library a cannot use
        self.assertEqual(self.abs.item(self.a, "li_book000004").state, SectionState.EMPTY)   # explicit, a may not
        self.assertEqual(self.abs.item(self.b, "li_book000003").state, SectionState.OK)
        self.assertEqual(self.abs.item(self.a, "li_book999999").state, SectionState.EMPTY)   # unknown
        self.assertIsNone(self.abs.item(self.a, "li_book000005").items[0].position_seconds
                          if self.abs.item(self.a, "li_book000005").items else None)

    def test_audiobookshelf_title_refuses_another_members_progress_entry(self):
        rec = self.ab.record("aaaaaaaa-1111-4aaa-8aaa-aaaaaaaaaaaa")
        rec["mediaProgress"][0]["userId"] = "bbbbbbbb-2222-4bbb-8bbb-bbbbbbbbbbbb"
        self.ab.serve("/api/users/aaaaaaaa-1111-4aaa-8aaa-aaaaaaaaaaaa", rec)
        r = self.abs.item(self.a, "li_book000001")
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamMisbehaved"))

    def test_a_revoked_group_is_absent_at_once_even_with_a_warm_cache(self):
        for ad, item_id in ((self.jellyfin, FILM_A), (self.abs, "li_book000001"), (self.komga, "BOOKAAAA0001")):
            self.assertEqual(ad.item(self.a, item_id).state, SectionState.OK, ad)
            revoked = make_principal("member-a", tuple(g for g in ALL if g != ad.required_group))
            before = sum(len(f.requests) for f in (self.jf, self.ab, self.kg))
            self.assertEqual(ad.item(revoked, item_id).state, SectionState.NOT_PERMITTED, ad)
            self.assertEqual(before, sum(len(f.requests) for f in (self.jf, self.ab, self.kg)))

    def test_the_cache_is_per_member(self):
        self.assertEqual(self.jellyfin.item(self.a, FILM_A).state, SectionState.OK)
        self.jf.overrides["/Users"] = ("status", 500)
        self.assertEqual(self.jellyfin.item(self.a, FILM_A).state, SectionState.OK)          # a's own cache
        self.assertNotEqual(self.jellyfin.item(self.b, FILM_A).state, SectionState.OK)       # never a's answer

    def test_hostile_ids_make_no_upstream_call(self):
        for ad in (self.jellyfin, self.abs, self.komga):
            for bad in HOSTILE_IDS:
                r = ad.item(self.a, bad)
                self.assertEqual(r.state, SectionState.EMPTY, (ad, repr(bad)[:30]))
        self.assertEqual([], self.jf.requests + self.ab.requests + self.kg.requests)

    def test_calibre_web_offers_no_title_page(self):
        self.assertIn("item", self.calibre.not_offered)


class CreatorAndYear(Setup):
    def test_each_adapter_fills_creator_and_year_only_from_fields_it_reads(self):
        kg = self.komga.item(self.a, "BOOKAAAA0001").items[0]
        self.assertEqual((kg.creator, kg.year), ("Synthetic Writer", 2019))   # the writer, not the inker
        cw = {i.title: i for i in self.calibre.search(self.a, "Synthetic Book").items}
        self.assertEqual((cw["Synthetic Book One"].creator, cw["Synthetic Book One"].year), ("Synthetic Author A", 2008))
        self.assertIsNone(cw["Synthetic Book Two"].year)
        jf = {i.title: i for i in self.jellyfin.search(self.a, "Synthetic").items}
        self.assertIsNone(jf["Synthetic Film One"].creator)                     # People are not fetched

    def test_year_from_accepts_only_plausible_years(self):
        for raw, want in ((2004, 2004), ("2004", 2004), ("2004-05-01", 2004), ("2004-05-01T00:00:00+00:00", 2004),
                          ("0101-01-01T00:00:00+00:00", None), (True, None), ("20040", None), ("abcd", None),
                          (99999, None), ("2004-05-01<script>", None), (None, None), (2004.0, None),
                          ("x" * 100, None), ("1999\n", 1999)):
            self.assertEqual(year_from(raw), want, repr(raw))


class AbsUnavailableIsNotEmpty(Setup):
    def test_every_library_search_404_is_unavailable(self):
        self.ab.overrides["/api/libraries/lib_aaa/search"] = ("status", 404)
        r = self.abs.search(self.a, "Synthetic")                       # member-a's only library
        self.assertEqual(r.state, SectionState.UNAVAILABLE)
        self.assertEqual(r.reason, "RouteMissing")

    def test_one_library_gone_of_several_is_still_an_answer(self):
        self.ab.overrides["/api/libraries/lib_bbb/search"] = ("status", 404)
        r = self.abs.search(self.b, "Synthetic")                       # member-b may use every library
        self.assertEqual(r.state, SectionState.OK)

    def test_all_adapters_down_is_reported_as_unsearchable_never_no_results(self):
        for f in (self.jf, self.kg, self.cw):
            f.overrides["/Users"] = f.overrides["/api/v1/books"] = f.overrides["/opds/search"] = ("status", 500)
        self.ab.overrides["/api/users"] = ("status", 500)
        page = build_search(search(self.a, self.adapters, "Synthetic").search_view(), "Synthetic")
        self.assertEqual(page.result_state, "unsearchable")
        self.assertEqual(page.outcome, "Not searched")
        self.assertNotIn("match", page.message)
        self.assertEqual(page.retry_href, "/search?q=Synthetic")
        self.assertEqual(page.requests, ())


def view(*groups, entitled=True, status="ok"):
    return {"status": status, "entitled": entitled,
            "groups": [{"service": s, "state": st, "items": list(items)} for s, st, *rest in groups
                       for items in [rest[0] if rest else []]]}


def film(i=1, **kw):
    it = {"id": "jellyfin:" + "a" * 31 + str(i), "service": "jellyfin", "kind": "movie", "title": f"Film {i}",
          "handoff_url": "https://watch.avrana.net/web/#/details?id=x", "artwork": None, "subtitle": "2001", "year": 2001}
    it.update(kw)
    return it


HOSTS = {"requests": "request.example.net", "requestabook": "requestabook.example.net",
         "requestacomic": "requestacomic.example.net"}


class SearchStates(unittest.TestCase):
    def test_found(self):
        p = build_search(view(("jellyfin", "ok", [film()]), ("komga", "unavailable")), "Film",
                         title_services={"jellyfin"})
        self.assertEqual((p.result_state, p.found, p.outcome), ("found", 1, "1 result"))
        self.assertEqual(p.groups[1].message, "The Comics library could not be searched right now.")
        self.assertEqual(p.retry_href, "/search?q=Film")
        hit = p.groups[0].items[0]
        self.assertEqual(hit.href, "/title/jellyfin/" + "a" * 31 + "1?q=Film")
        self.assertEqual(hit.line, "Movie · 2001")                      # the year once, not twice
        self.assertIsNone(hit.opens)
        self.assertEqual(p.requests, ())                                 # results: no request offer

    def test_without_a_title_page_the_one_link_is_the_library(self):
        p = build_search(view(("calibre-web", "ok", [film(service="calibre-web", id="calibre-web:12", kind="ebook",
                                                           creator="An Author",
                                                           handoff_url="https://books.avrana.net/book/12")])), "Film")
        hit = p.groups[0].items[0]
        self.assertEqual((hit.href, hit.opens, hit.medium), ("https://books.avrana.net/book/12", "Books", "Book"))
        self.assertEqual(hit.line, "Book · An Author · 2001")

    def test_a_forged_id_never_becomes_a_title_link(self):
        for bad in ("jellyfin:../x", "komga:" + "a" * 32, "jellyfin:" + "A" * 32, "nope:1", "", None, "jellyfin"):
            p = build_search(view(("jellyfin", "ok", [film(id=bad)])), "Film", title_services={"jellyfin"})
            self.assertTrue(p.groups[0].items[0].href.startswith("https://"), repr(bad))
            self.assertIsNone(split_item_id(bad) if bad != "komga:" + "a" * 32 else None)

    def test_all_empty_is_no_results_with_request_offers(self):
        p = build_search(view(("jellyfin", "empty"), ("calibre-web", "empty"), ("audiobookshelf", "empty")),
                         "a b&c", request_hosts=HOSTS)
        self.assertEqual((p.result_state, p.outcome), ("none", "No results"))
        self.assertEqual([(r.href, r.label) for r in p.requests], [
            ("https://request.example.net/search?query=a%20b%26c", "Request this title as a film or show"),
            ("/requestabook", "Request this title as an ebook or an audiobook")])

    def test_partial_empty_names_only_the_libraries_that_could_not_answer(self):
        p = build_search(view(("jellyfin", "empty"), ("komga", "unavailable")), "Film", request_hosts=HOSTS)
        self.assertEqual(p.result_state, "partial_none")
        self.assertIn("No matches in Movies and TV.", p.message)
        self.assertIn("Comics could not be searched right now", p.message)
        self.assertEqual([r.href for r in p.requests], ["https://request.example.net/search?query=Film"])

    def test_all_down_and_one_down(self):
        p = build_search(view(("jellyfin", "unavailable"), ("komga", "unavailable")), "Film", request_hosts=HOSTS)
        self.assertEqual((p.result_state, p.outcome), ("unsearchable", "Not searched"))
        self.assertTrue(p.message.startswith("Your libraries could not be searched right now."))
        self.assertEqual(p.requests, ())
        one = build_search(view(("komga", "unavailable")), "Film")
        self.assertTrue(one.message.startswith("The Comics library could not be searched right now."))

    def test_not_linked_only(self):
        p = build_search(view(("jellyfin", "not_linked")), "Film", request_hosts=HOSTS)
        self.assertEqual(p.result_state, "not_set_up")
        self.assertIsNone(p.retry_href)
        self.assertEqual(p.requests, ())

    def test_zero_entitlements_and_invalid_and_idle(self):
        self.assertEqual(build_search(view(entitled=False), "Film").mode, "no_library")
        self.assertEqual(build_search(view(status="invalid_query"), "*").mode, "invalid")
        self.assertEqual(build_search(view(), None).mode, "idle")

    def test_requests_only_where_the_catalogue_holds_the_service(self):
        self.assertEqual(request_options(["jellyfin"], "x y", {}), ())
        self.assertEqual(request_options(["komga"], "x y", {"requests": "request.example.net"}), ())
        self.assertEqual([r.href for r in request_options(["komga"], "x y", HOSTS)], ["/requestacomic"])
        for host in ("evil.example/x", "a b", "https://x.example", "", "x", "request.example.net:8443", None):
            self.assertEqual(request_options(["jellyfin"], "x y", {"requests": host}), (), repr(host))
        self.assertEqual([r.href for r in request_options(["jellyfin"], None, HOSTS)], ["/requests"])


class HandoffHosts(unittest.TestCase):
    def test_only_the_services_own_fixed_host_survives(self):
        bad = ("https://evil.example/web/#/details?id=x", "https://listen.avrana.net/item/x",
               "https://watch.avrana.net.evil.example/x", "https://watch.avrana.netx/", "http://watch.avrana.net/x",
               "https://watch.avrana.net", "//watch.avrana.net/x", "javascript:alert(1)", None, 5)
        for href in bad:
            p = build_search(view(("jellyfin", "ok", [film(handoff_url=href)])), "Film", title_services={"jellyfin"})
            self.assertEqual((p.found, p.result_state), (0, "none"), repr(href))
            sec = {"state": "ok", "items": [film(handoff_url=href)]}
            self.assertIsNone(build_title(sec, "jellyfin", "a" * 31 + "1", None), repr(href))
        good = build_search(view(("jellyfin", "ok", [film()])), "Film")
        self.assertEqual(good.found, 1)


class TitleRules(unittest.TestCase):
    def section(self, state="ok", **kw):
        return {"state": state, "items": [film(**kw)] if state == "ok" else []}

    def test_404_states(self):
        for st in ("not_permitted", "empty", None, "weird"):
            self.assertIsNone(build_title({"state": st, "items": []}, "jellyfin", "a" * 31 + "1", None), st)
        self.assertIsNone(build_title(self.section(id="jellyfin:" + "b" * 32), "jellyfin", "a" * 31 + "1", None))
        self.assertIsNone(build_title(self.section(handoff_url="javascript:x"), "jellyfin", "a" * 31 + "1", None))
        self.assertIsNone(build_title(self.section(), "nope", "a" * 31 + "1", None))

    def test_watch_or_resume(self):
        t = build_title(self.section(), "jellyfin", "a" * 31 + "1", None)
        self.assertEqual((t.action, t.progress, t.back_href), ("Watch", None, None))
        prog = {"fraction": 0.5, "percent": 50, "position_seconds": 3600, "duration_seconds": 7200}
        t = build_title(self.section(progress=prog), "jellyfin", "a" * 31 + "1", "Film")
        self.assertEqual((t.action, t.progress), ("Resume", "1 hour left"))
        self.assertEqual(t.action_label, "Resume Film 1 in Movies and TV")
        self.assertEqual(t.back_href, "/search?q=Film")
        done = dict(prog, position_seconds=7200)
        self.assertEqual(build_title(self.section(progress=done), "jellyfin", "a" * 31 + "1", None).action, "Watch")
        self.assertEqual(build_title(self.section(kind="audiobook"), "jellyfin", "a" * 31 + "1", None).action, "Listen")
        self.assertEqual(build_title(self.section(kind="comic"), "jellyfin", "a" * 31 + "1", None).action, "Read")

    def test_back_to_search_only_from_a_usable_term(self):
        for raw in ("*", "a", "x" * 300, "", None):
            self.assertIsNone(build_title(self.section(), "jellyfin", "a" * 31 + "1", raw).back_href, repr(raw))
        t = build_title(self.section(), "jellyfin", "a" * 31 + "1", 'a"><b>&\r\n')
        self.assertEqual(t.back_href, "/search?q=a%20%3E%3Cb%3E%26")       # " became a space; CRLF dropped

    def test_unavailable_and_not_linked_say_nothing_about_the_title(self):
        u = build_title({"state": "unavailable", "items": []}, "jellyfin", "a" * 31 + "1", None)
        self.assertEqual((u.state, u.title), ("unavailable", ""))
        self.assertEqual(u.retry_href, "/title/jellyfin/" + "a" * 31 + "1")
        n = build_title({"state": "not_linked", "items": []}, "komga", "BOOKAAAA0001", None)
        self.assertEqual((n.state, n.retry_href), ("not_linked", None))


class TitleRoute(unittest.TestCase):
    def test_only_exact_valid_routes_parse(self):
        self.assertEqual(parse_title_route("/title/jellyfin/" + FILM_A), ("jellyfin", FILM_A))
        self.assertEqual(parse_title_route("/title/komga/BOOKAAAA0001"), ("komga", "BOOKAAAA0001"))
        self.assertEqual(parse_title_route("/title/audiobookshelf/li_book000001"), ("audiobookshelf", "li_book000001"))
        for bad in ("/title/jellyfin/" + FILM_A.upper(), "/title/jellyfin/../" + FILM_A, "/title/jellyfin",
                    "/title/jellyfin/" + FILM_A + "/x", "/title/jellyfin/%2e%2e%2f" + FILM_A,
                    "/title/jellyfin/" + FILM_A + "%2f", "/title/nope/" + FILM_A, "/title//" + FILM_A,
                    "/title/jellyfin/" + FILM_A + "\r\n", "/title/jellyfin/" + FILM_A + "\x00",
                    "/title/jellyfin/" + "a" * 5000, "/title/calibre-web/12x", "/TITLE/jellyfin/" + FILM_A,
                    "/title/komga/BOOK%41AAA0001"):
            self.assertIsNone(parse_title_route(bad), repr(bad)[:60])


class ReviewFixes(Setup):
    """Review of #58: no existence oracle on Komga 403 or Audiobookshelf malformed items; title lookups uncached."""

    def test_komga_403_on_a_book_is_hidden_like_404_and_never_counts(self):
        self.kg.overrides["/api/v1/books/BOOKAAAA0001"] = ("status", 403)
        for _ in range(12):
            r = self.komga.item(self.a, "BOOKAAAA0001", fresh=True)
            self.assertEqual((r.state, r.items), (SectionState.EMPTY, ()))
        self.assertEqual(self.komga.item(self.a, "BOOKZZZZ9999", fresh=True).state, SectionState.EMPTY)
        self.assertNotIn(self.komga.health().to_dict()["state"], ("cooling_off", "failing"))
        self.assertEqual(self.komga.recent_items(self.a).state, SectionState.OK)       # circuit still closed
        self.kg.overrides["/api/v1/books/BOOKAAAA0001"] = ("status", 401)               # a refused key is not "hidden"
        self.assertEqual(self.komga.item(self.a, "BOOKAAAA0001", fresh=True).state, SectionState.UNAVAILABLE)

    def test_abs_forbidden_library_with_malformed_fields_is_hidden_not_unavailable(self):
        item = dict(self.ab.items["li_book000003"])                     # lib_bbb: member-a may not use it
        item["media"] = dict(item["media"], tags=None)
        self.ab.serve("/api/items/li_book000003", item)
        r = self.abs.item(self.a, "li_book000003", fresh=True)
        self.assertEqual((r.state, r.items), (SectionState.EMPTY, ()))
        ok = dict(self.ab.items["li_book000001"])                       # a library member-a may use, malformed
        ok["media"] = dict(ok["media"], tags=None)
        self.ab.serve("/api/items/li_book000001", ok)
        r = self.abs.item(self.a, "li_book000001", fresh=True)
        self.assertEqual((r.state, r.items), (SectionState.EMPTY, ()))  # fails closed to hidden

    def test_abs_checks_library_access_before_any_other_field(self):
        from avrana_home.adapters.audiobookshelf import _Access
        access = _Access(frozenset({"lib_aaa"}), None, False)
        raw = {"id": "li_book000003", "libraryId": "lib_bbb", "mediaType": "book", "media": {"tags": None}}
        self.assertEqual(AudiobookshelfAdapter._visible(raw, "li_book000003", access, None, None, None),
                         (None, "filtered"))                              # forbidden first, not "bad"
        raw["libraryId"] = "lib_aaa"
        self.assertEqual(AudiobookshelfAdapter._visible(raw, "li_book000003", access, None, None, None)[1], "bad")

    def test_a_fresh_title_lookup_reads_no_cache_and_sees_access_removal_at_once(self):
        self.assertEqual(self.jellyfin.item(self.a, FILM_A, fresh=True).state, SectionState.OK)
        before = len(self.jf.requests)
        self.assertEqual(self.jellyfin.item(self.a, FILM_A, fresh=True).state, SectionState.OK)
        self.assertEqual(len(self.jf.requests), before + 1)            # one upstream call per view, mapping cached
        self.jf.overrides["/Items"] = ("body", b'{"Items": [], "TotalRecordCount": 0}')
        self.assertEqual(self.jellyfin.item(self.a, FILM_A, fresh=True).state, SectionState.EMPTY)
        rec = self.ab.record("aaaaaaaa-1111-4aaa-8aaa-aaaaaaaaaaaa")
        self.assertEqual(self.abs.item(self.a, "li_book000001", fresh=True).state, SectionState.OK)
        rec["librariesAccessible"] = []
        self.ab.serve("/api/users/aaaaaaaa-1111-4aaa-8aaa-aaaaaaaaaaaa", rec)
        self.assertEqual(self.abs.item(self.a, "li_book000001", fresh=True).state, SectionState.EMPTY)

    def test_down_and_not_set_up_together_are_named_precisely(self):
        p = build_search(view(("jellyfin", "unavailable"), ("komga", "not_linked")), "Film")
        self.assertEqual(p.result_state, "unsearchable")
        self.assertTrue(p.message.startswith("Movies and TV could not be searched right now, and Comics is not set up "
                                             "for your account yet."), p.message)


if __name__ == "__main__":
    unittest.main()
