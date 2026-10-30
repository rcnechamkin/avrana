"""The phone visual pass (owner, 2026-10-30), from a video of the installed app on an iPhone. SYNTHETIC data only.

Tier A (standard library): the stylesheet keeps the status bar clear, the ceiling solid, the tab bar legible and each row
of cards on one rhythm. The page script changes a Home shelf's filter in place, and falls back to the plain link.
The help row stays a plain link.
"""
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "avrana_home" / "app"


def block():
    css = (APP / "templates" / "home.css").read_text(encoding="utf-8")
    return css.split("/* ---- MK-13", 1)[1].split("/* ---- MK-6", 1)[0]


class Stylesheet(unittest.TestCase):
    def setUp(self):
        self.css = re.sub(r"/\*.*?\*/", "", block(), flags=re.S)

    def test_the_status_bar_strip_is_opaque_over_the_stuck_chrome_and_nothing_without_a_notch(self):
        rule = re.search(r"body:has\(\.mast\)::before\{([^}]*)\}", self.css).group(1)
        for decl in ("position:fixed", "z-index:16", "height:env(safe-area-inset-top,0px)", "background:var(--bg)",
                     "pointer-events:none"):
            self.assertIn(decl, rule)

    def test_the_ceiling_is_solid_and_the_filters_stick_under_the_notch_without_a_gap_at_rest(self):
        self.assertIn(".mast.at-home::before,.places::before{background:var(--bg);", self.css)
        self.assertIn("body:has(.mast) .chips{top:env(safe-area-inset-top,0px);padding-top:0;}", self.css)
        self.assertIn("html[data-scrolled] body:has(.mast) .chips{background:var(--bg);}", self.css)

    def test_a_tucked_row_leaves_fast_and_only_with_motion_allowed(self):
        self.assertRegex(self.css, r"@media \(prefers-reduced-motion:no-preference\)\{html\[data-chrome=\"tucked\"\] \.places"
                                   r":not\(:focus-within\),\s*html\[data-chrome=\"tucked\"\] body:has\(\.mast\) \.chips"
                                   r":not\(:focus-within\)\{transition-duration:560ms,160ms;\}\}")

    def test_the_stronger_tab_bar_still_gives_way_to_reduced_transparency(self):
        self.assertIn("rgb(18 18 20 / 0.88)", self.css)
        self.assertRegex(self.css, r"\(prefers-reduced-transparency:reduce\),\(prefers-contrast:more\)\{\.tabbar\.glass\{"
                                   r"background:var\(--raised\);")

    def test_rows_of_cards_keep_two_title_lines_and_filtered_shelves_keep_their_height(self):
        self.assertIn(".rail .t,.lib-grid:not(.lib-v-compact,.lib-v-list) .t{min-height:2.5em;}", self.css)
        self.assertIn(".shelf-released .rail,.shelf-new .rail,.shelf-released .said,.shelf-new .said{min-height:", self.css)

    def test_a_phone_keeps_no_hover_underline(self):
        self.assertIn("@media (hover:none){.card:hover .t,.hero-card:hover .hero-plate{text-decoration:none;}}", self.css)

    def test_art_on_its_way_breathes(self):
        self.assertIn(".frame:has(img.art.k-wait){animation:k-art-wait", self.css)

    def test_the_strip_fade_is_no_mask_so_a_pinned_ceiling_stays_whole(self):
        self.assertNotIn("mask", self.css)
        self.assertIn(".tabs::after,.chips::after{", self.css)
        self.assertIn("@media (forced-colors:active){.tabs::after,.chips::after{display:none;}}", self.css)

    def test_the_sheet_stand_in_has_the_shape_of_the_wide_picture_from_its_first_frame(self):
        self.assertIn(".k-sheet-standin img{height:auto;aspect-ratio:16/9;}", self.css)
        self.assertIn("calc(env(safe-area-inset-top,0px) + 24px)", self.css)


class PageScript(unittest.TestCase):
    def setUp(self):
        self.js = (APP / "assets" / "home.js").read_text(encoding="utf-8")
        self.part = self.js.split("function strips()", 1)[1].split("\n  lens();", 1)[0]

    def test_only_a_homes_shelf_filter_is_taken_and_never_a_library_chip(self):
        self.assertIn("from.closest('section.shelf > nav.tabs a[href]')", self.part)
        self.assertIn("link.origin !== window.location.origin", self.part)
        self.assertNotIn("a.chip", self.part)

    def test_anything_unexpected_navigates(self):
        self.assertIn(".catch(function () { if (mine === latest) window.location.assign(href); })", self.part)
        self.assertIn("response.redirected", self.part)
        self.assertIn("throw new Error('not this shelf')", self.part)

    def test_the_page_stays_where_it_is_and_the_new_shelf_is_a_whole_one(self):
        self.assertIn("if (window.scrollY !== y) window.scrollTo(0, y);", self.part)
        self.assertIn("window.history.replaceState(window.history.state, '', href);", self.part)
        self.assertNotIn("pushState", self.part)
        for call in ("clean(fresh)", "arrive(shelf);", "railButtons(shelf);"):
            self.assertIn(call, self.part)

    def test_each_strip_centres_its_chosen_word_and_honours_reduced_motion(self):
        self.assertIn("querySelectorAll('nav.tabs, nav.chips')", self.part)
        self.assertIn("behavior: smooth && !still() ? 'smooth' : 'auto'", self.js)

    def test_the_sheet_rises_full_width_and_still_returns_into_the_art(self):
        opening = self.js.split("function open(link)", 1)[1].split("function ask()", 1)[0]
        self.assertIn("var from = { transform: 'translateY(100%)', clipPath: full() };", opening)
        self.assertNotIn("onto(", opening)
        closing = self.js.split("function shut(from)", 1)[1].split("function pull()", 1)[0]
        self.assertIn("onto(origin.getBoundingClientRect())", closing)


class Pages(unittest.TestCase):
    def test_the_help_row_is_still_the_plain_link_with_a_decorative_mark(self):
        text = (APP / "templates" / "home.html").read_text(encoding="utf-8")
        self.assertRegex(text, r'<a class="link help-row" href="/help/trouble"><svg class="kic"[^>]*aria-hidden="true"[^>]*>')
        self.assertIn("If something doesn&#x27;t open</a>", text)


if __name__ == "__main__":
    unittest.main()
