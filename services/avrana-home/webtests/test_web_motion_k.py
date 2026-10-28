"""AVR-720 (MK-6): Concept K page-to-page motion. SYNTHETIC data only.

Tier A (standard library): the stylesheet contract. `@view-transition` and every `view-transition-name` live only
inside `@media (prefers-reduced-motion:no-preference)`, so with Reduce Motion there is no transition at all; every
duration in this slice's block is tier 3 (at most 200 ms) and the 600 ms Proposal token is not in it; a safety net
ends any transition under Reduce Motion; the names are on class selectors only (so the rendered pages can be counted).
The Proposal is a server setting, default off. The page script keeps MK-3's rules (test_web_pwa.py) and adds only
the art flight and the interruption, through a class the stylesheet owns (no style written from script).

Tier B (framework, loopback mocks): no view-transition-name value is carried by two elements on any shell page that
can be fetched (Home, Library, every title page reachable from Home's Details and from search results, Search, Me,
Account, Help), for every identity the mocks know, with JavaScript off (the server's HTML; the script's one flight
class is never in it). The Proposal setting adds its rule to the pages that carry the shell stylesheet (shell pages and the offline page)
and changes no header.

The browser half (a transition really starts with no-preference and never with reduce, art moves, a touch tap ends an
exposed transition) is
tests/ui/harness/motion_run.py.
"""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from avrana_home.app.settings import Settings, SettingsError
from avrana_home.app.viewmodel import SERVICE_LABEL

APP = Path(__file__).resolve().parents[1] / "avrana_home" / "app"
TEMPLATES = APP / "templates"
MARKER = "  /* ---- MK-6 Motion (AVR-720) ---- */\n"
NO_PREF = "@media (prefers-reduced-motion:no-preference)"
TIME = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)(ms|s)\b")


def css():
    return (TEMPLATES / "home.css").read_text(encoding="utf-8")


def strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def enclosing_at_rules(text, index):
    """The at-rule preludes of every block that contains `index`, outermost first (comments already stripped)."""
    stack = []
    prelude_start = 0
    for i, ch in enumerate(text[:index]):
        if ch == "{":
            stack.append(text[prelude_start:i].strip())
            prelude_start = i + 1
        elif ch == "}":
            if stack:
                stack.pop()
            prelude_start = i + 1
        elif ch == ";":
            prelude_start = i + 1
    return [p for p in stack if p.startswith("@")]


def tokens(text):
    """:root custom properties of the first :root block (MK-1's tokens), as written."""
    root = re.search(r":root\{(.*?)\n  \}", text, flags=re.S).group(1)
    return dict(re.findall(r"(--[\w-]+):([^;]+);", strip_comments(root)))


def ms(value, table, depth=0):
    """A duration value in ms: a literal, or var(--token) resolved through MK-1's tokens."""
    value = value.strip()
    m = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if m:
        assert depth < 5
        return ms(table[m.group(1)], table, depth + 1)
    m = TIME.fullmatch(value)
    assert m, value
    return float(m.group(1)) * (1 if m.group(2) == "ms" else 1000)


def named_selectors(text):
    """{selector: name} for every rule in `text` that sets view-transition-name."""
    out = {}
    for m in re.finditer(r"([^{}]+)\{([^{}]*view-transition-name:\s*([\w-]+)[^{}]*)\}", strip_comments(text)):
        for sel in m.group(1).split(","):
            out[sel.strip()] = m.group(3)
    return out


class Stylesheet(unittest.TestCase):
    def setUp(self):
        self.css = css()
        self.assertEqual(1, self.css.count(MARKER))
        self.block = self.css.split(MARKER, 1)[1]
        self.assertNotIn("/* ---- MK-", self.block)              # this slice's block is the last one in the file
        self.rules = strip_comments(self.block)
        self.comments = " ".join(re.findall(r"/\*.*?\*/", MARKER + self.block, flags=re.S))

    def test_view_transition_only_inside_the_no_preference_query(self):
        text = strip_comments(self.css)
        hits = [m.start() for m in re.finditer(r"@view-transition\b", text)]
        self.assertEqual(1, len(hits))
        for at in hits:
            self.assertEqual([NO_PREF], enclosing_at_rules(text, at))
        self.assertIn("@view-transition{navigation:auto;}", text)
        self.assertNotIn("view-transition", (TEMPLATES / "style.css").read_text(encoding="utf-8"))   # portal parity

    def test_every_name_is_set_only_inside_the_no_preference_query(self):
        text = strip_comments(self.css)
        found = [m.start() for m in re.finditer(r"view-transition-name\s*:", text)]
        self.assertGreater(len(found), 0)
        for at in found:
            self.assertEqual([NO_PREF], enclosing_at_rules(text, at), text[at - 80:at + 40])

    def test_the_names_and_where_they_are(self):
        """Class selectors only, each name on one element per page: the title page's one frame (or, on the page being
        left, the one frame the script marks while it is captured), the tab bar's one lens, and the tab bar itself
        (k-dock, held still while the pages change; owner review 2026-10-27)."""
        self.assertEqual({".title-page .frame": "k-art", ".frame.k-flight": "k-art", ".tabbar .lens": "k-lens",
                          ".tabbar": "k-dock", ".tabs .ul": "k-filter", ".chips .ul": "k-filter"},
                         named_selectors(self.css))
        for sel in named_selectors(self.css):
            self.assertRegex(sel, r"^(\.[\w-]+)+( (\.[\w-]+)+)*$", sel)
        self.assertNotIn(".hero .frame", named_selectors(self.css))     # the first page's art is named only by the script

    def test_every_duration_in_the_block_is_tier_3_at_most_200ms(self):
        table = tokens(self.css)
        self.assertEqual(200, ms(table["--motion-3"], table))
        durations = re.findall(r"animation-duration:([^;}]+)", self.rules)
        self.assertGreater(len(durations), 0)
        for d in durations:
            self.assertLessEqual(ms(d, table), 200, d)
        for literal in TIME.finditer(self.rules):
            self.assertLessEqual(float(literal.group(1)) * (1 if literal.group(2) == "ms" else 1000), 200, literal.group(0))
        for ref in re.findall(r"var\((--motion[\w-]*)\)", self.rules):
            self.assertLessEqual(ms(table[ref], table), 200, ref)
        for longer in ("--motion-3-proposal", "--motion-spring", "--motion-2"):
            self.assertNotIn("var(" + longer + ")", self.rules)
        self.assertNotRegex(self.rules, r"(?<![\w-])animation(?:-delay)?\s*:(?!none)")   # no shorthand hiding a time

    def test_the_curve_is_an_existing_token(self):
        self.assertIn("animation-timing-function:var(--ease-meaningful);", self.rules)
        self.assertIn("--ease-meaningful:", self.css.split(MARKER)[0])

    def test_reduce_motion_ends_any_transition_and_mk1s_rule_still_stands(self):
        self.assertIn("@media (prefers-reduced-motion:reduce){::view-transition-group(*),::view-transition-old(*),"
                      "::view-transition-new(*){\n    animation:none!important;}}", self.block)
        self.assertIn("@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;"
                      "transition:none!important;}}", self.css)

    def test_no_colour_glass_or_layout_in_the_block(self):
        for banned in ("#", "rgb(", "accent", "backdrop-filter", "url(", "width", "height", "margin", "padding",
                       "display", "position", "font", "z-index"):
            self.assertNotIn(banned, self.rules, banned)

    def test_comments_name_no_library_or_member_word(self):
        words = list(SERVICE_LABEL.values()) + ["Movies", "Audiobook", "Comic", "jellyfin", "Jellyfin", "komga", "Komga",
                                                "audiobookshelf", "Audiobookshelf", "calibre", "Calibre", "Continue",
                                                "New to Avrana", "member-"]
        for word in words:
            self.assertNotIn(word, self.comments, word)


class PageScript(unittest.TestCase):
    def setUp(self):
        self.js = (APP / "assets" / "home.js").read_text(encoding="utf-8")

    def test_the_flight_marks_through_the_stylesheets_class_and_writes_no_style(self):
        self.assertIn("addEventListener('pageswap'", self.js)
        self.assertIn("event.viewTransition", self.js)
        self.assertIn("classList.add('k-flight')", self.js)
        self.assertIn("classList.remove('k-flight')", self.js)
        self.assertNotRegex(self.js, r"\.style\b|setProperty|viewTransitionName|view-transition-name")
        self.assertNotIn("startViewTransition", self.js)             # cross-document only: the browser starts them
        # one element, one class for the flight; the only other class the script adds is the art's k-wait
        self.assertEqual(2, self.js.count("classList.add("))
        self.assertIn("img.classList.add('k-wait')", self.js)

    def test_the_chrome_follows_the_scroll_through_two_marks_only(self):
        """Owner decision 2026-10-27: the header slims and tucks, the tab bar shrinks, on the way down; both come back
        on the way up, at either end, or on focus. The script writes only two attributes on <html>; no style."""
        part = self.js.split("function chrome()", 1)[1].split("\n  }\n", 1)[0]
        self.assertIn("window.addEventListener('scroll', update, { passive: true })", part)
        self.assertEqual({"data-chrome", "data-scrolled"}, set(re.findall(r"'(data-[a-z]+)'", part)))
        self.assertIn("closest('header, nav.tabbar, nav.chips')", part)
        css = strip_comments(css_text := (TEMPLATES / "home.css").read_text(encoding="utf-8"))
        self.assertIn('html[data-chrome="tucked"] .tabbar:not(:focus-within){transform:translateY(0.625rem) scale(0.84);}', css)
        self.assertIn('html[data-chrome="tucked"] .places:not(:focus-within)', css)
        # owner review 2026-10-27: "the slightest pan in and out", so a slow even glide, never a spring or a snap
        self.assertIn("html[data-chrome=\"tucked\"] .places:not(:focus-within){transform:translateY(-75%);", css)
        self.assertIn(".places{z-index:1;transition:transform 560ms cubic-bezier(0.37,0,0.2,1),"
                      "opacity 480ms cubic-bezier(0.37,0,0.2,1);}", css)
        self.assertIn(".tabbar{transform-origin:50% 100%;transition:transform 520ms cubic-bezier(0.37,0,0.2,1);}", css)
        # with the labels gone, the dock's icons settle to the middle of the bar
        self.assertIn('html[data-chrome="tucked"] .tabbar:not(:focus-within) :is(.ic,.me){transform:translateY(', css)
        self.assertIn("body:has(.mast) header{position:sticky;top:0;", css_text)

    def test_the_flight_only_aims_at_a_title_page_on_this_origin(self):
        self.assertIn("to.origin !== window.location.origin || to.pathname.indexOf('/title/') !== 0", self.js)
        self.assertIn("document.querySelector('.title-page .frame')", self.js)

    def test_interruption_skips_an_exposed_transition_on_the_first_press_and_never_stops_the_event(self):
        self.assertIn("document.addEventListener('pointerdown'", self.js)
        self.assertIn("skipTransition()", self.js)
        self.assertIn("passive: true", self.js)
        part = self.js.split("function interrupt()", 1)[1].split("\n  }\n", 1)[0]
        self.assertNotIn("preventDefault", part)                    # the sheet's are its own (test_web_pwa.py)
        self.assertNotIn("stopPropagation", self.js)

    def test_the_flight_class_is_never_in_the_templates(self):
        for path in TEMPLATES.glob("*.html"):
            self.assertNotIn("k-flight", path.read_text(encoding="utf-8"), path.name)


class Proposal(unittest.TestCase):
    def test_setting_default_off_and_strict(self):
        self.assertFalse(Settings.from_mapping({}).motion_proposal)
        for raw in ("on", "1", "yes", "TRUE"):
            self.assertTrue(Settings.from_mapping({"HOME_MOTION_PROPOSAL": raw}).motion_proposal, raw)
        for raw in ("off", "0", "no", ""):
            self.assertFalse(Settings.from_mapping({"HOME_MOTION_PROPOSAL": raw}).motion_proposal, raw)
        with self.assertRaises(SettingsError) as cm:
            Settings.from_mapping({"HOME_MOTION_PROPOSAL": "600"})
        self.assertIn("HOME_MOTION_PROPOSAL", str(cm.exception))


# ---- Tier B -----------------------------------------------------------------------------------------------------
from . import FRAMEWORK_MISSING, SKIP_REASON  # noqa: E402
from .support import GROUPS, USER, make_client, make_settings, require_framework  # noqa: E402  (stdlib at import)

if not FRAMEWORK_MISSING:
    from avrana_home.app.main import MOTION_PROPOSAL_CSS
    from dev.mock_audiobookshelf import MockAudiobookshelf
    from dev.mock_calibre_web import MockCalibreWeb
    from dev.mock_jellyfin import MockJellyfin
    from dev.mock_komga import MockKomga

KEY = "mock-api-key-not-real"
CRED = "viewer:mock-api-key-not-real"
ALL = "avrana-users|avrana-videos|avrana-audiobooks|avrana-comics|avrana-books"
IDENTITIES = {
    "member-a": [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks")],
    "member-b": [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos|avrana-comics")],
    "member-a, every group": [(USER, "member-a"), (GROUPS, ALL)],
    "member-b, every group": [(USER, "member-b"), (GROUPS, ALL)],
    "no library": [(USER, "member-n"), (GROUPS, "avrana-users")],
}
PAGES = ("/", "/library", "/search", "/search?q=Synthetic", "/me", "/account", "/help")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class Classes(HTMLParser):
    """Every element as (its classes, its ancestors' classes), enough to match the class-only selectors above."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.elements = [], []

    def handle_starttag(self, tag, attrs):
        classes = frozenset((dict(attrs).get("class") or "").split())
        self.elements.append((classes, [c for c, _t in self.stack]))
        if tag not in VOID:
            self.stack.append((classes, tag))

    def handle_startendtag(self, tag, attrs):
        classes = frozenset((dict(attrs).get("class") or "").split())
        self.elements.append((classes, [c for c, _t in self.stack]))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][1] == tag:
                del self.stack[i:]
                return


def matches(selector, classes, ancestors):
    parts = [frozenset(p.split(".")[1:]) for p in selector.split()]
    if not parts[-1] <= classes:
        return False
    need = parts[:-1]
    for anc in reversed(ancestors):                     # descendant combinators, right to left
        if need and need[-1] <= anc:
            need.pop()
    return not need


def name_counts(html):
    parser = Classes()
    parser.feed(html)
    counts = {}
    for sel, name in named_selectors(css()).items():
        for classes, ancestors in parser.elements:
            if matches(sel, classes, ancestors):
                counts[name] = counts.get(name, 0) + 1
    return counts


@unittest.skipIf(FRAMEWORK_MISSING, SKIP_REASON)
class RenderedPages(unittest.TestCase):
    timeout = 1.5

    @classmethod
    def setUpClass(cls):
        require_framework()
        cls.mocks = (MockJellyfin().start(), MockAudiobookshelf().start(), MockKomga().start(), MockCalibreWeb().start())

    @classmethod
    def tearDownClass(cls):
        for m in cls.mocks:
            m.stop()

    def client(self, **extra):
        jf, ab, kg, cw = self.mocks
        c = make_client(make_settings(home_sections=True, jellyfin_base_url=jf.url, audiobookshelf_base_url=ab.url,
                                      audiobookshelf_token=KEY, komga_base_url=kg.url, komga_token=KEY,
                                      calibre_web_base_url=cw.url, calibre_web_credential=CRED, timeout=self.timeout,
                                      **extra))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def test_matcher_counts_what_it_should(self):
        html = ('<div class="title-page w-poster"><span class="stage"><span class="frame"><img class="art"></span></span>'
                '</div><nav class="tabbar glass"><a class="tab"></a><span class="lens"></span></nav>'
                '<section class="hero"><span class="frame"></span></section>')
        self.assertEqual({"k-art": 1, "k-lens": 1, "k-dock": 1}, name_counts(html))
        self.assertEqual({"k-art": 2}, name_counts('<p class="title-page"><span class="frame"></span></p>'
                                                   '<span class="frame k-flight"></span>'))

    def test_no_name_is_carried_twice_on_any_shell_page_for_any_identity(self):
        c = self.client()
        seen_title = seen_lens = 0
        for who, headers in IDENTITIES.items():
            pages = list(PAGES)
            home = c.get("/", headers=headers).text
            search = c.get("/search?q=Synthetic", headers=headers).text
            pages += sorted(set(re.findall(r'href="(/title/[^"]+)"', home + search)))
            for path in pages:
                r = c.get(path.replace("&amp;", "&"), headers=headers)
                if r.status_code != 200 or 'class="tabbar' not in r.text:
                    continue                                 # not a shell page for this identity
                with self.subTest(who=who, path=path):
                    counts = name_counts(r.text)
                    self.assertTrue(all(n == 1 for n in counts.values()), counts)
                    self.assertNotRegex(r.text, r"class=\"[^\"]*k-flight")       # the script's class, never the server's
                    if path.startswith("/title/") and 'class="shelf title-page' in r.text:
                        self.assertEqual(1, counts.get("k-art"))
                        seen_title += 1
                    else:
                        self.assertNotIn("k-art", counts)    # only a title page names art in its HTML
                    seen_lens += counts.get("k-lens", 0)
        self.assertGreater(seen_title, 2)                     # title pages were really reached (Details and results)
        self.assertGreater(seen_lens, 10)

    def test_the_proposal_is_off_by_default_and_on_adds_one_labelled_rule_where_the_shell_stylesheet_is(self):
        headers = IDENTITIES["member-a"]
        off = self.client()
        on = self.client(motion_proposal=True)
        self.assertIn("Proposal", MOTION_PROPOSAL_CSS)
        self.assertIn("var(--motion-3-proposal)", MOTION_PROPOSAL_CSS)
        self.assertTrue(MOTION_PROPOSAL_CSS.strip().split("*/", 1)[1].strip().startswith(NO_PREF))
        for path in ("/", "/library", "/title/jellyfin/aaaa0000000000000000000000000001", "/search?q=Synthetic"):
            a, b = off.get(path, headers=headers), on.get(path, headers=headers)
            self.assertNotIn("var(--motion-3-proposal)", a.text, path)
            self.assertEqual(1, b.text.count(MOTION_PROPOSAL_CSS), path)
            self.assertEqual(a.text.replace(MOTION_PROPOSAL_CSS, ""), b.text.replace(MOTION_PROPOSAL_CSS, ""), path)
            for h in ("content-security-policy", "cache-control"):
                self.assertEqual(a.headers[h], b.headers[h], (path, h))
        for path in ("/nope", "/healthz"):                       # pages without the shell stylesheet never get it
            self.assertNotIn("motion-3-proposal", on.get(path, headers=headers).text, path)
        # the offline page carries the shell stylesheet (base.html: shell or offline), so it carries the rule too
        self.assertEqual(1, on.get("/offline").text.count(MOTION_PROPOSAL_CSS))
        self.assertNotIn("var(--motion-3-proposal)", off.get("/offline").text)
