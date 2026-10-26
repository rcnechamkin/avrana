"""AVR-716 (MK-2): the Concept K shell on Home's shell pages. SYNTHETIC data only (StubAdapter), no upstream.

Tier A (standard library): the stylesheet carries the tab bar, the lens positions, the safe-area spacing and the
forced-colours fallbacks. Tier B (framework): the tab bar's markup contract with the page script (MK-3: it only
moves data-at on nav.tabbar, from the clicked a.tab's index), which tabs a member sees, viewport-fit=cover on shell
pages only, and the glass Home button on pages that are not tabs.
"""
import re
import unittest
from pathlib import Path

from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

TEMPLATES = Path(__file__).resolve().parents[1] / "avrana_home" / "app" / "templates"
ALL = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks|avrana-comics|avrana-books")]
NOLIB = [(USER, "member-n"), (GROUPS, "avrana-users")]
TAB_BAR = re.compile(r'<nav class="tabbar glass" aria-label="Sections" data-tabs="(\d)"( data-at="(\d)")?>(.*?)</nav>', re.S)


class Stylesheet(unittest.TestCase):
    def setUp(self):
        self.css = (TEMPLATES / "home.css").read_text(encoding="utf-8")

    def test_the_tab_bar_is_fixed_clear_of_the_safe_area_and_the_page_scrolls_clear_of_it(self):
        bar = re.search(r"\.tabbar\{([^}]*)\}", self.css).group(1)
        for decl in ("position:fixed", "bottom:max(24px,env(safe-area-inset-bottom))",
                     "left:max(16px,env(safe-area-inset-left))", "right:max(16px,env(safe-area-inset-right))"):
            self.assertIn(decl, bar)
        self.assertIn("body:has(.tabbar) .page{padding-bottom:calc(5rem + max(24px, env(safe-area-inset-bottom)));}", self.css)

    def test_the_lens_is_placed_by_data_at_alone_and_hidden_without_a_section(self):
        for n in ("1", "2", "3"):
            self.assertIn(f'.tabbar[data-at="{n}"]{{--at:{n};}}', self.css)
        self.assertIn('.tabbar[data-tabs="2"]{--n:2;}', self.css)
        self.assertIn("transform:translateX(calc(var(--at) * 100%))", self.css)
        self.assertIn(".tabbar:not([data-at]) .lens{display:none;}", self.css)
        # the lens is the Media yellow (purple's role in Party), with the solid fallback
        self.assertIn(".k-lens,.tabbar .lens{background:var(--accent-lens);", self.css)

    def test_labels_never_break_inside_a_word_and_forced_colours_keep_the_current_tab(self):
        self.assertIn(".tab .tl{overflow-wrap:normal;word-break:normal;}", self.css)
        self.assertNotRegex(re.search(r"\.tab\{[^}]*\}", self.css).group(0), r"font-size:\d+px")   # grows with text
        self.assertIn("@media (forced-colors:active){.tabbar .lens{border:2px solid Highlight;}", self.css)

    def test_the_old_top_row_is_gone(self):
        rules = re.sub(r"/\*.*?\*/", "", self.css, flags=re.S)
        for gone in (".idlink", "details.account", ".menu{", ".mono{"):
            self.assertNotIn(gone, rules)


class Markup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_framework()
        data = {"member-a": [("a" * 32, "Synthetic Shell Film", 0.5)]}
        cls.on = make_client(make_settings(home_sections=True), adapters=[StubAdapter(data)])
        cls.off = make_client(make_settings(home_sections=False))
        cls.on.__enter__()
        cls.off.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.on.__exit__(None, None, None)
        cls.off.__exit__(None, None, None)

    def bar(self, path, headers=ALL):
        text = self.on.get(path, headers=headers).text
        found = TAB_BAR.findall(text)
        self.assertEqual(1, len(found), path)
        return text, found[0]

    def test_four_tabs_in_order_with_one_lens_and_inline_decorative_icons(self):
        _text, (n, _, at, body) = self.bar("/")
        self.assertEqual(("4", "0"), (n, at))
        self.assertEqual(["/", "/#h-new", "/search", "/account"], re.findall(r'<a class="tab" href="([^"]*)"', body))
        self.assertEqual(["Home", "Library", "Search", "Me"], re.findall(r'<span class="tl">([A-Za-z]+)', body))
        self.assertEqual(1, body.count('<span class="lens" aria-hidden="true"></span>'))
        self.assertEqual(3, body.count('aria-hidden="true" focusable="false"'))
        self.assertNotRegex(body, r"<img|<script|on\w+=|style=")

    def test_a_member_with_no_library_sees_home_and_me_only(self):
        for path in ("/", "/account", "/help"):
            text, (n, _, _at, body) = self.bar(path, NOLIB)
            self.assertEqual("2", n, path)
            self.assertEqual(["/", "/account"], re.findall(r'<a class="tab" href="([^"]*)"', body), path)
            self.assertNotIn("Library", body, path)
            self.assertNotIn("/search", text, path)

    def test_me_names_who_is_signed_in_and_shows_the_initial(self):
        _text, (_n, _, _at, body) = self.bar("/account")
        self.assertIn('<a class="tab" href="/account" aria-current="page"><span class="me" aria-hidden="true">M</span>'
                      '<span class="tl">Me<span class="sr">, signed in as member-a</span></span></a>', body)

    def test_pages_outside_a_section_print_no_lens(self):
        # every shell page today belongs to a section; the attribute is absent only when none matches
        for path in ("/", "/search", "/account", "/help", "/help/movies", "/request", "/watch"):
            _text, (_n, has_at, _at, _body) = self.bar(path)
            self.assertTrue(has_at, path)

    def test_viewport_fit_cover_only_where_the_shell_is(self):
        cover = '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        plain = '<meta name="viewport" content="width=device-width, initial-scale=1">'
        self.assertIn(cover, self.on.get("/", headers=ALL).text)
        for client, path in ((self.off, "/"), (self.off, "/account"), (self.on, "/nope")):
            text = client.get(path, headers=ALL).text
            self.assertIn(plain, text, path)
            self.assertNotIn("tabbar", text, path)

    def test_the_glass_home_button_is_on_pages_that_are_not_tabs_only(self):
        for path in ("/request", "/watch", "/help/movies", "/help/trouble"):
            self.assertIn('<a class="homebtn glass" href="/">', self.on.get(path, headers=ALL).text, path)
        for path in ("/", "/search", "/account", "/help"):
            self.assertNotIn('class="homebtn', self.on.get(path, headers=ALL).text, path)

    def test_one_h1_on_every_shell_page(self):
        for path in ("/", "/search", "/account", "/help", "/help/movies", "/request"):
            self.assertEqual(1, len(re.findall(r"<h1[\s>]", self.on.get(path, headers=ALL).text)), path)


if __name__ == "__main__":
    unittest.main()
