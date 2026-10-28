"""AVR-719 (MK-5a): the Concept K Library page (`/library`) and the restyled title page. SYNTHETIC data only.

Tier A (standard library): the view-model (`build_library`): chips only for the member's own libraries, the `?lib=`
choice checked against them and never echoed, a down library as Home's own sentence with no items, the empty and
no-library states, the request group; and the stylesheet block (yellow only for selection, the warning amber, no
library named in its comments).

Tier B (framework, loopback mocks): the route through HTTP. Chips for two members with different libraries; an unknown
or foreign `?lib=` is All and never echoed; a down library is a warning and no items; a member with no library;
the same markup without JavaScript (no script, no inline style, plain links); the tab bar's aria-current; the CSP and
Cache-Control of the other shell pages; the standard 404 without a member or with sections off; and isolation (one
member's Library never holds the other's titles, ids or covers, cold, warm and with one upstream failing), mirroring
test_web_isolation_h2.py. The title page keeps its behaviour and copy and gains the Concept K look.
"""
import re
import unittest
from pathlib import Path

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import NOTHING_NEW, SERVICE_LABEL, build_library

TEMPLATES = Path(__file__).resolve().parents[1] / "avrana_home" / "app" / "templates"
MARKER = "  /* ---- MK-5a Library and title (AVR-719) ---- */\n"
# MK-3 (O1): shell pages carry exactly one first-party script tag in <head>; nothing else may script.
PAGE_SCRIPT = re.compile(r'<script src="/static/home\.[0-9a-f]{12}\.js" defer(?: data-sw="off")?></script>\n?')
HANDOFF = {"jellyfin": "https://watch.avrana.net/web/#/details?id=", "audiobookshelf": "https://listen.avrana.net/item/",
           "komga": "https://read.avrana.net/book/", "calibre-web": "https://books.avrana.net/book/"}
TILES_AV = [("watch", Trusted("Watch"), Trusted("")), ("listen", Trusted("Listen"), Trusted("")),
            ("request", Trusted("Request"), Trusted("Ask for something")), ("help", Trusted("Help"), Trusted(""))]
TILES_ALL = TILES_AV[:2] + [("read", Trusted("Read"), Trusted(""))] + TILES_AV[2:]
TILES_NONE = [("help", Trusted("Help"), Trusted(""))]
PLACES = {"jellyfin": "/watch", "audiobookshelf": "/listen", "komga": "/comics", "calibre-web": "/books"}


def item(service, uid, title, kind="movie"):
    return {"id": f"{service}:{uid}", "service": service, "kind": kind, "title": title,
            "handoff_url": HANDOFF[service] + uid}


def sec(service, section, state, items=()):
    return {"service": service, "section": section, "state": state, "items": list(items)}


def view(*sections):
    return {"sections": list(sections)}


def av_view(**states):
    """Movies and TV and Audiobooks, both sections each; `states` overrides one library's state."""
    out = []
    for s, uid, kind in (("jellyfin", "a" * 32, "movie"), ("audiobookshelf", "li_book000001", "audiobook")):
        state = states.get(s, "ok")
        items = [item(s, uid, f"Synthetic title {kind}", kind)] if state == "ok" else []
        out += [sec(s, "continue", state, items), sec(s, "recent", state, items)]
    return view(*out)


class ViewModel(unittest.TestCase):
    def test_chips_are_all_then_only_the_members_own_libraries_in_order(self):
        page = build_library(av_view(), TILES_AV)
        self.assertEqual([("all", "All", "/library", True), ("jellyfin", "Movies and TV", "/library?lib=jellyfin", False),
                          ("audiobookshelf", "Audiobooks", "/library?lib=audiobookshelf", False)],
                         [(c.key, c.label, c.href, c.current) for c in page.chips])
        self.assertEqual(["jellyfin", "audiobookshelf"], [sh.service for sh in page.shelves])

    def test_the_choice_is_checked_against_the_members_own_libraries_and_never_echoed(self):
        for chip in (None, "", "all", "komga", "calibre-web", "ALL", "Jellyfin", "jellyfin ", "<script>", "x" * 32,
                     "../jellyfin", "jellyfin#h"):
            page = build_library(av_view(), TILES_AV, chip=chip)
            with self.subTest(chip=chip):
                self.assertEqual("all", page.chosen)
                self.assertTrue(page.chips[0].current)
                self.assertEqual(2, len(page.shelves))
                if chip and chip != "all":
                    self.assertNotIn(chip, repr(page))
        page = build_library(av_view(), TILES_AV, chip="audiobookshelf")
        self.assertEqual(("audiobookshelf", "Audiobooks"), (page.chosen, page.chosen_label))
        self.assertEqual(["audiobookshelf"], [sh.service for sh in page.shelves])

    def test_a_down_library_is_homes_sentence_with_no_items_and_a_struck_chip(self):
        down = av_view(jellyfin="unavailable")
        down["sections"][1]["items"] = [item("jellyfin", "b" * 32, "Cached title")]   # Continue still answers (cache)
        down["sections"][1]["state"] = "ok"
        page = build_library(down, TILES_AV)
        self.assertEqual(("Movies and TV are unavailable right now.",), page.warnings)
        self.assertEqual("/library", page.retry_href)
        self.assertEqual(["audiobookshelf"], [sh.service for sh in page.shelves])
        self.assertNotIn("Cached title", repr(page))
        self.assertTrue(next(c for c in page.chips if c.key == "jellyfin").down)
        chosen = build_library(down, TILES_AV, chip="jellyfin")
        self.assertEqual(((), "/library?lib=jellyfin"), (chosen.shelves, chosen.retry_href))

    def test_every_library_down_is_homes_one_combined_line(self):
        page = build_library(av_view(jellyfin="unavailable", audiobookshelf="unavailable"), TILES_AV)
        self.assertEqual(("None of your libraries is answering right now.",), page.warnings)
        self.assertEqual((), page.shelves)

    def test_not_set_up_says_so_with_the_next_step(self):
        page = build_library(av_view(audiobookshelf="not_linked"), TILES_AV, open_paths=PLACES)
        shelf = page.shelves[1]
        self.assertEqual(("not_linked", "Audiobooks are not set up for your account yet.", None),
                         (shelf.state, shelf.message, shelf.open_href))
        self.assertEqual("/help/trouble#not-set-up", page.setup_href)

    def test_empty_states_are_honest(self):
        empty = view(sec("jellyfin", "recent", "empty"), sec("audiobookshelf", "recent", "empty"))
        page = build_library(empty, TILES_AV)
        self.assertEqual(NOTHING_NEW, page.said)
        one = build_library(view(sec("jellyfin", "recent", "ok", [item("jellyfin", "a" * 32, "F")]),
                                 sec("audiobookshelf", "recent", "empty")), TILES_AV)
        self.assertIsNone(one.said)
        self.assertEqual("Nothing recently added in Audiobooks.", one.shelves[1].message)

    def test_open_links_only_to_the_members_own_place_routes(self):
        page = build_library(av_view(), TILES_AV, open_paths=PLACES)
        self.assertEqual([("/watch", "Jellyfin"), ("/listen", "Audiobookshelf")],
                         [(sh.open_href, sh.open_app) for sh in page.shelves])
        none = build_library(av_view(), TILES_AV)
        self.assertEqual([None, None], [sh.open_href for sh in none.shelves])
        odd = build_library(av_view(), TILES_AV, open_paths={"jellyfin": "https://evil.example/", "audiobookshelf": "/watch"})
        self.assertEqual([None, None], [sh.open_href for sh in odd.shelves])

    def test_a_member_with_no_library_and_the_request_group(self):
        page = build_library(view(), TILES_NONE)
        self.assertEqual((True, (), (), ()), (page.no_library, page.chips, page.shelves, page.asks))
        self.assertEqual([("/request", "Request")], [(h, str(l)) for h, l, _d in build_library(av_view(), TILES_AV).asks])

    def test_the_group_heading_says_contribute_only_when_that_row_is_there(self):
        both = TILES_AV + [("contribute", Trusted("Contribute"), Trusted("Add your own"))]
        self.assertEqual("Request or contribute", build_library(av_view(), both).asks_heading)
        self.assertEqual("Requests", build_library(av_view(), TILES_AV).asks_heading)
        self.assertEqual("Contribute", build_library(av_view(), [t for t in both if t[0] != "request"]).asks_heading)

    def test_a_library_the_member_cannot_use_is_never_named(self):
        page = build_library(av_view(), TILES_AV, chip="komga", open_paths=PLACES)
        text = repr(page)
        for word in ("Comics", "komga", "Books", "calibre", "Komga", "/comics", "/books"):
            self.assertNotIn(word, text, word)


class Stylesheet(unittest.TestCase):
    def setUp(self):
        css = (TEMPLATES / "home.css").read_text(encoding="utf-8")
        self.assertEqual(1, css.count(MARKER))
        # this slice's block only: it runs from its marker to the next slice's marker, if any
        self.block = css.split(MARKER, 1)[1].split("\n  /* ---- MK-", 1)[0]
        self.comments = " ".join(re.findall(r"/\*.*?\*/", MARKER + self.block, flags=re.S))
        self.rules = re.sub(r"/\*.*?\*/", "", self.block, flags=re.S)

    def test_the_block_holds_rules(self):
        self.assertIn(".chip[aria-current]", self.rules)

    def test_yellow_is_only_selection_and_focus_and_the_warning_is_amber(self):
        for m in re.finditer(r"([^{}]+)\{([^}]*var\(--accent(?:-selected)?\)[^}]*)\}", self.rules):
            selector = m.group(1).strip()
            self.assertRegex(selector, r"^\.chip(\.off)?\[aria-current\]$|^\.chip \.ck$", selector)
        self.assertIn("var(--focus)", self.rules)
        warn = re.search(r"\.k-warn\{([^}]*)\}", self.rules).group(1)
        self.assertIn("border:1px solid var(--warn)", warn)
        for rule in re.findall(r"\.k-warn[^{]*\{[^}]*\}", self.rules):
            self.assertNotIn("accent", rule)
        for banned in ("#e8cf8a", "#b9a9e8", "purple", "url(", "backdrop-filter"):
            self.assertNotIn(banned, self.rules.lower())

    def test_glass_only_on_the_utility_and_the_progress_rule_is_cream(self):
        self.assertNotIn(".glass", self.rules)          # the utility wears the shared class from the shell's block
        self.assertIn(".title-bar .fill{display:block;height:100%;border-radius:inherit;background:var(--cream);}", self.rules)

    def test_only_a_tall_cover_rises_beside_the_home_button(self):
        self.assertIn("@media (min-width:360px){.title-page:is(.w-poster,.w-book,.w-comic) .title-stage{margin-top:-3.25rem;}}",
                      self.rules)
        self.assertEqual(1, self.rules.count("margin-top:-3.25rem"))

    def test_comments_name_no_library_or_member_word(self):
        words = list(SERVICE_LABEL.values()) + ["Movies", "Audiobook", "Comic", "jellyfin", "Jellyfin", "komga", "Komga",
                                                "audiobookshelf", "Audiobookshelf", "calibre", "Calibre", "Continue",
                                                "Recently added", "member-"]
        for word in words:
            self.assertNotIn(word, self.comments, word)


# ---- Tier B -----------------------------------------------------------------------------------------------------
from . import FRAMEWORK_MISSING  # noqa: E402
from .support import GROUPS, USER, require_framework  # noqa: E402  (stdlib only at import)

if not FRAMEWORK_MISSING:
    from dev.mock_audiobookshelf import MockAudiobookshelf
    from dev.mock_calibre_web import MockCalibreWeb
    from dev.mock_jellyfin import MockJellyfin
    from dev.mock_komga import MockKomga
    from .support import make_client, make_settings

KEY = "mock-api-key-not-real"
CRED = "viewer:mock-api-key-not-real"
A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks")]
B = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos|avrana-comics")]
NOLIB = [(USER, "member-n"), (GROUPS, "avrana-users")]
# The same markers as test_web_isolation_h2.py: each may only ever appear for its own member.
A_ONLY = ("Synthetic Film One", "Synthetic Film Three", "Synthetic Pilot", "Synthetic Series Alpha", "aaaa0000",
          "Audiobook", "audiobookshelf", "li_book", "Continue listening")
B_ONLY = ("Synthetic Film Two", "Synthetic Film Four", "Synthetic Documentary B", "bbbb0000", "komga",
          "Synthetic Comic", "Synthetic Kids", "Synthetic Teen", "Synthetic Manga", "Synthetic Mature", "Comics")
CHIPS = re.compile(r'<nav class="chips" aria-label="Libraries">(.*?)</nav>', re.S)
FILM_A = "aaaa0000000000000000000000000001"


def main_of(text):
    return re.split(r"<main(?:\s[^>]*)?>", text)[1].split("</main>")[0]


def chips(text):
    m = CHIPS.search(text)
    return [] if m is None else re.findall(r'<a class="chip[^"]*" href="([^"]*)"(?: aria-current="true")?>', m.group(1))


class Fixture(unittest.TestCase):
    timeout = 1.5

    @classmethod
    def setUpClass(cls):
        require_framework()
        cls.jf = MockJellyfin(slow_seconds=3.0).start()
        cls.ab = MockAudiobookshelf(slow_seconds=3.0).start()
        cls.kg = MockKomga(slow_seconds=3.0).start()
        cls.cw = MockCalibreWeb(slow_seconds=3.0).start()
        cls.mocks = (cls.jf, cls.ab, cls.kg, cls.cw)

    @classmethod
    def tearDownClass(cls):
        for m in cls.mocks:
            m.stop()

    def setUp(self):
        for m in self.mocks:
            m.set_mode("ok")
            m.reset()

    def client(self, sections=True):
        c = make_client(make_settings(home_sections=sections, jellyfin_base_url=self.jf.url,
                                      audiobookshelf_base_url=self.ab.url, audiobookshelf_token=KEY,
                                      komga_base_url=self.kg.url, komga_token=KEY, calibre_web_base_url=self.cw.url,
                                      calibre_web_credential=CRED, timeout=self.timeout))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def assertIsolated(self, who, text, where):
        for marker in (B_ONLY if who == "A" else A_ONLY):
            self.assertNotIn(marker, text, f"{where}: {who} saw {marker!r}")


class LibraryPage(Fixture):
    def test_chips_name_only_each_members_own_libraries(self):
        c = self.client()
        a, b = c.get("/library", headers=A), c.get("/library", headers=B)
        self.assertEqual((200, 200), (a.status_code, b.status_code))
        self.assertEqual(["/library", "/library?lib=jellyfin", "/library?lib=audiobookshelf"], chips(a.text))
        self.assertEqual(["/library", "/library?lib=jellyfin", "/library?lib=komga"], chips(b.text))
        self.assertIn('<a class="chip" href="/library" aria-current="true">All<span class="ul" aria-hidden="true"></span></a>', a.text)
        self.assertEqual(1, a.text.count('aria-current="true"'))          # the chosen chip, nothing else on this page
        self.assertIn("<title>Library · Avrana</title>", a.text)
        self.assertIn('<a class="shelf-open" href="/watch">Open Jellyfin', a.text)
        self.assertIn('<a class="shelf-open" href="/comics">Open Komga', b.text)
        self.assertIn("Synthetic Film Three", a.text)
        self.assertIn("/art/komga/", b.text)

    def test_a_chosen_chip_shows_that_library_alone_and_an_unknown_or_foreign_one_is_all(self):
        c = self.client()
        one = c.get("/library?lib=jellyfin", headers=A).text
        self.assertIn('<a class="chip" href="/library?lib=jellyfin" aria-current="true">Movies and TV<span class="ul"', one)
        self.assertIn("<title>Movies and TV · Library · Avrana</title>", one)
        self.assertIn('<ul class="lib-grid">', one)
        self.assertIn('<p class="lib-browse"><a href="/watch">', one)
        self.assertNotIn("Open Audiobookshelf", one)
        plain = c.get("/library", headers=A).text
        for q in ("lib=komga", "lib=calibre-web", "lib=nope", "lib=%3Cscript%3Ezzqx", "lib=" + "z" * 600,
                  "lib=Jellyfin", "new=jellyfin", "lib=komga&lib=jellyfin", "lib="):
            with self.subTest(q=q[:40]):
                r = c.get("/library?" + q, headers=A)
                self.assertEqual(200, r.status_code)
                self.assertEqual(main_of(plain), main_of(r.text))           # All, exactly
                for echo in ("komga", "calibre", "nope", "zzqx", "zzzz", "Comics", "Books"):
                    self.assertNotIn(echo, r.text)
        first = c.get("/library?lib=audiobookshelf&lib=jellyfin", headers=A).text   # the first value, as ?new=
        self.assertIn('href="/library?lib=audiobookshelf" aria-current="true"', first)

    def test_a_down_library_is_a_warning_and_no_items(self):
        self.kg.set_mode("down")
        c = self.client()
        for path in ("/library", "/library?lib=komga"):
            t = c.get(path, headers=B).text
            with self.subTest(path=path):
                warn = re.search(r'<div class="k-warn" role="status">.*?</div>\s*(?:<a class="k-warn-act"[^>]*>.*?</a>\s*)?</div>',
                                 t, re.S)
                self.assertIsNotNone(warn)
                self.assertIn("<p>Comics are unavailable right now.</p>", warn.group(0))
                self.assertIn(f'<a class="k-warn-act" href="{path}">Try again', warn.group(0))
                self.assertNotIn("/art/komga/", t)
                self.assertNotIn("read.avrana.net", t)
                self.assertNotIn("Open Komga", t)
                self.assertIn('<a class="chip off" href="/library?lib=komga"', t)
                self.assertIn('<s>Comics</s><span class="sr">, unavailable</span>', t)
        self.assertIn("Synthetic Film Four", c.get("/library", headers=B).text)    # the other library still answers

    def test_a_member_with_no_library(self):
        c = self.client()
        r = c.get("/library", headers=NOLIB)
        self.assertEqual(200, r.status_code)
        main = main_of(r.text)
        self.assertIn('<h2 id="h-none">No library yet</h2>', main)
        self.assertIn("No library is shared with this account yet.", main)
        self.assertIn('<a class="link" href="/help">Help</a>', main)
        self.assertNotIn('class="chips"', main)
        self.assertNotIn('class="utility', main)
        bar = re.search(r'<nav class="tabbar.*?</nav>', r.text, re.S).group(0)
        self.assertEqual(["/", "/me"], re.findall(r'<a class="tab" href="([^"]*)"', bar))
        self.assertNotIn("data-at", bar)
        for word in ("Movies", "Audiobook", "Comics", "Books", "/search"):
            self.assertNotIn(word, r.text, word)

    def test_the_same_markup_without_javascript(self):
        c = self.client()
        for who in (A, B):
            first, second = c.get("/library", headers=who).text, c.get("/library", headers=who).text
            self.assertEqual(first, second)                           # nothing depends on a script or the client
            self.assertEqual(1, len(PAGE_SCRIPT.findall(first)))
            low = PAGE_SCRIPT.sub("", first).lower()
            for token in ("<script", "<noscript", "<form", "<button", " style=", "javascript:"):
                self.assertNotIn(token, low, token)
            self.assertNotRegex(first, r"\son[a-z]+=")
            for href in re.findall(r'<a class="chip[^"]*" href="([^"]*)"', first):
                self.assertTrue(href.startswith("/library"), href)

    def test_the_tab_bar_marks_library_and_the_utility_holds_search(self):
        c = self.client()
        t = c.get("/library?lib=jellyfin", headers=A).text
        self.assertIn('<nav class="tabbar glass" aria-label="Sections" data-tabs="4" data-at="1">', t)
        self.assertIn('<a class="tab" href="/library" aria-current="page">', t)
        self.assertNotIn('class="homebtn', t)
        self.assertIn('<div class="utility glass"><a class="util" href="/search"><svg class="ic"', t)
        self.assertIn('<span class="sr">Search</span></a></div>', t)
        self.assertEqual(2, len(re.findall(r'class="[^"]*\bglass\b', t)))       # the tab bar and the utility only
        for path in ("/", "/search", "/account"):
            self.assertIn('<a class="tab" href="/library"', c.get(path, headers=A).text, path)

    def test_headers_match_the_other_shell_pages(self):
        c = self.client()
        lib, acc = c.get("/library", headers=A), c.get("/account", headers=A)
        for name in ("content-security-policy", "cache-control", "referrer-policy", "x-content-type-options"):
            self.assertEqual(acc.headers[name], lib.headers[name], name)
        self.assertEqual("no-store", lib.headers["cache-control"])
        self.assertIn("manifest-src 'self'; font-src 'self'", lib.headers["content-security-policy"])
        self.assertIn("form-action 'none'", lib.headers["content-security-policy"])
        self.assertIn("script-src 'self'; worker-src 'self'", lib.headers["content-security-policy"])   # MK-3, O1

    def test_no_member_or_sections_off_is_the_standard_404(self):
        c = self.client()
        unknown = c.get("/definitely-not-a-route", headers=A)
        for path in ("/library", "/library?lib=jellyfin"):
            for headers in ([], [(USER, "member-a")]):
                r = c.get(path, headers=headers)
                nf = c.get("/definitely-not-a-route", headers=headers)
                self.assertEqual((404, nf.text), (r.status_code, r.text), (path, headers))
        off = self.client(sections=False)
        r, nf = off.get("/library", headers=A), off.get("/definitely-not-a-route", headers=A)
        self.assertEqual((404, nf.text, nf.headers["content-security-policy"]),
                         (r.status_code, r.text, r.headers["content-security-policy"]))
        self.assertEqual(404, unknown.status_code)


class Isolation(Fixture):
    def test_one_members_library_never_holds_the_others_titles_ids_or_covers(self):
        c = self.client()
        seen = {}
        for rnd in ("cold", "warm"):
            for path in ("/library", "/library?lib=jellyfin", "/library?lib=komga", "/library?lib=audiobookshelf"):
                for who, headers in (("A", A), ("B", B)):
                    r = c.get(path, headers=headers)
                    self.assertEqual(200, r.status_code, (rnd, path, who))
                    self.assertIsolated(who, r.text, f"{rnd} {path}")
                    seen.setdefault((who, path), r.text)
        self.assertIn("Synthetic Film Three", seen[("A", "/library")])
        self.assertIn("Synthetic Film Four", seen[("B", "/library")])
        a_art = set(re.findall(r'src="(/art/[^"]+)"', seen[("A", "/library")]))
        b_art = set(re.findall(r'src="(/art/[^"]+)"', seen[("B", "/library")]))
        self.assertTrue(a_art and b_art)
        self.assertEqual(set(), a_art & b_art)

    def test_one_failing_upstream_never_crosses_members(self):
        for mode in ("down", "500", "malformed", "wrong-user"):
            with self.subTest(mode=mode):
                c = self.client()
                for who, headers in (("A", A), ("B", B)):
                    c.get("/library", headers=headers)                 # warm the caches first
                self.jf.set_mode(mode)
                for who, headers in (("A", A), ("B", B)):
                    r = c.get("/library", headers=headers)
                    self.assertEqual(200, r.status_code, (mode, who))
                    self.assertIsolated(who, r.text, mode)
                    for token in ("Traceback", "127.0.0.1", KEY):
                        self.assertNotIn(token, r.text)
                self.jf.set_mode("ok")
                self.jf.reset()


class TitlePage(Fixture):
    def test_concept_k_look_keeps_the_behaviour_and_copy(self):
        c = self.client()
        t = c.get("/title/jellyfin/" + FILM_A, headers=A).text
        main = main_of(t)
        # this film has a wide backdrop, so the page leads with it, full width (owner review 2026-10-27)
        self.assertIn('<section class="shelf title-page w-still has-backdrop" aria-labelledby="h-title">', main)
        art = re.findall(r'<img class="art" src="([^"]*)"', main)
        self.assertEqual(1, len(art))                                  # the backdrop alone, no blurred copy
        self.assertTrue(art[0].startswith("/art/jellyfin/backdrop/"))
        self.assertNotIn('class="hero-glow"', main)
        self.assertLess(main.index('class="title-stage"'), main.index('<p class="kicker">'))
        self.assertLess(main.index('<p class="kicker">'), main.index('<h2 id="h-title" class="t">'))
        self.assertIn('<p class="d p">70 minutes left</p>', main)
        self.assertRegex(main, r'<span class="bar title-bar" aria-hidden="true"><span class="fill pc\d+"></span></span>')
        self.assertIn('aria-label="Resume Synthetic Film One in Movies and TV">Resume</a>', main)
        self.assertEqual(1, main.count('<a class="open"'))
        self.assertIn('<a class="homebtn glass" href="/">', t)               # not a tab page: the Home button stays
        self.assertNotRegex(PAGE_SCRIPT.sub("", t), r"\sstyle=|<script")
        for word in ("playing", "now playing", "started"):
            self.assertNotIn(word, main.lower())

    def test_no_art_and_no_progress(self):
        c = self.client()
        t = main_of(c.get("/title/jellyfin/cccc0000000000000000000000000001", headers=A).text)
        self.assertIn('class="shelf title-page w-poster no-art"', t)
        self.assertNotIn("hero-glow", t)
        self.assertNotIn("title-bar", t)
        square = main_of(c.get("/title/audiobookshelf/li_book000001", headers=A).text)
        self.assertIn('class="shelf title-page w-square"', square)

    def test_unavailable_is_a_warning_with_try_again(self):
        self.jf.set_mode("500")
        t = self.client().get("/title/jellyfin/" + FILM_A, headers=A).text
        self.assertIn('<div class="k-warn" role="status">', t)
        self.assertIn("<p>The Movies and TV library is unavailable right now. This usually passes within a minute.</p>", t)
        self.assertIn(f'<a class="k-warn-act" href="/title/jellyfin/{FILM_A}">Try again</a>', t)
        self.assertNotIn("Synthetic Film", t)


class TitleSheetLinks(Fixture):
    """Owner decision 2026-10-27 (the title sheet): a Recently added card opens the item's own title page (the page
    script shows it as a sheet over the page), where the library has one; a Continue card still opens the item where
    it plays. Every title link is this member's own item and is a page the member may open."""

    def test_recent_cards_link_to_title_pages_and_continue_cards_play(self):
        c = self.client()
        home = main_of(c.get("/", headers=A).text)
        cont = home.split('id="h-continue"', 1)[1].split("</section>", 1)[0]
        recent = home.split('id="h-new"', 1)[1].split("</section>", 1)[0]
        cont_hrefs = re.findall(r'class="card" href="([^"]*)"', cont)
        recent_hrefs = re.findall(r'class="card" href="([^"]*)"', recent)
        self.assertTrue(cont_hrefs and recent_hrefs)
        self.assertTrue(all(h.startswith("https://") for h in cont_hrefs), cont_hrefs)
        titles = [h for h in recent_hrefs if h.startswith("/title/")]
        self.assertTrue(titles, recent_hrefs)
        for h in titles:
            self.assertRegex(h, r"^/title/jellyfin/[0-9a-f]{32}$")
            self.assertEqual(200, c.get(h, headers=A).status_code, h)
        lib = main_of(c.get("/library", headers=A).text)
        self.assertRegex(lib, r'class="card" href="/title/jellyfin/[0-9a-f]{32}"')

    def test_another_members_title_link_is_the_standard_404(self):
        c = self.client()
        recent = main_of(c.get("/", headers=A).text).split('id="h-new"', 1)[1].split("</section>", 1)[0]
        own = [h for h in re.findall(r'class="card" href="(/title/[^"]*)"', recent) if "/aaaa0000" in h]
        self.assertTrue(own)                                  # cccc0000 items are shared by both members in the mock
        for h in own:
            self.assertEqual(404, c.get(h, headers=B).status_code, h)


class LaunchTiles(Fixture):
    """Owner decision 2026-10-27: the places are matte tiles; the ones that leave Avrana carry an arrow (decorative)
    and say so to assistive technology; Request and Help stay inside and carry none."""

    def test_leaving_places_are_marked_and_staying_ones_are_not(self):
        home = self.client().get("/", headers=A).text
        places = home.split('<nav class="places" aria-label="Avrana">', 1)[1].split("</nav>", 1)[0]
        for link in re.findall(r'<a href="([^"]*)">(.*?)</a>', places, re.S):
            href, inner = link
            leaves = href in ("/watch", "/listen", "/read")
            self.assertEqual(leaves, '<svg class="out"' in inner, href)
            self.assertEqual(leaves, "opens its own site" in inner, href)


if __name__ == "__main__":
    unittest.main()
