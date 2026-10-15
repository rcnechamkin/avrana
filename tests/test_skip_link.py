"""Skip link: one canonical definition, byte-identical copies, and the structure every page needs.

Canonical source: docs/design/components/skip-link.html and skip-link.css (DESIGN.md, "Skip link").
The portal embeds them in portal.SHELL / portal.STYLE; Home carries copies in templates/base.html
and templates/style.css. Editing a copy without the canonical file (or the reverse) fails here.
Browser behaviour (focus order, viewport, axe, accessibility tree) is in tests/ui/skip_link_browser.mjs.
"""
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_portal_a11y as a11y  # noqa: E402  (shared page registry, colour maths, HTML tree)

REPO = HERE.parent
CANON = REPO / "docs" / "design" / "components"
HOME_TEMPLATES = REPO / "services" / "avrana-home" / "avrana_home" / "app" / "templates"
MARKUP = (CANON / "skip-link.html").read_bytes().decode()
CSS = (CANON / "skip-link.css").read_bytes().decode()
MAIN_OPEN = '<main id="main" tabindex="-1">'


class CanonicalTests(unittest.TestCase):
    def test_canonical_files_are_lf_and_exact(self):
        self.assertEqual('<a class="skip-link" href="#main">Skip to main content</a>', MARKUP)
        self.assertNotIn("\r", MARKUP + CSS)
        self.assertTrue(CSS.endswith("\n"))

    def test_portal_copy_is_byte_identical(self):
        self.assertEqual(1, a11y.portal.STYLE.count(CSS))
        self.assertEqual(1, a11y.portal.SHELL.count("<body>\n" + MARKUP + "\n<div"))
        self.assertEqual(1, a11y.portal.SHELL.count("  " + MAIN_OPEN + "\n{body}"))

    def test_home_copy_is_byte_identical(self):
        style = (HOME_TEMPLATES / "style.css").read_bytes().decode()
        base = (HOME_TEMPLATES / "base.html").read_bytes().decode()
        self.assertEqual(1, style.count(CSS))
        self.assertEqual(1, base.count("<body>\n" + MARKUP + "\n<div"))
        self.assertEqual(1, base.count("  " + MAIN_OPEN + "\n"))
        self.assertEqual(a11y.portal.STYLE, "\n" + style)

    def test_no_other_main_in_home_templates(self):
        for p in HOME_TEMPLATES.glob("*.html"):
            if p.name != "base.html":
                self.assertNotIn("<main", p.read_text(encoding="utf-8"), p.name)

    def test_design_md_documents_the_component(self):
        text = (REPO / "docs" / "design" / "DESIGN.md").read_text(encoding="utf-8")
        self.assertIn("### Skip link", text)
        self.assertIn("docs/design/components/skip-link.css", text)


class StyleTests(unittest.TestCase):
    def test_hidden_with_clip_not_display_none(self):
        rules = dict(a11y.css_rules(CSS))
        hidden = rules[".skip-link"]
        self.assertEqual("rect(0,0,0,0)", hidden["clip"])
        self.assertNotIn("display", hidden)
        self.assertNotIn("visibility", hidden)

    def test_focused_contrast_and_not_obscured(self):
        focus = dict(a11y.css_rules(CSS))[".skip-link:focus-visible"]
        bg = a11y.parse_color("#000000")
        fg = a11y.parse_color("#ffffff")
        self.assertEqual("var(--fg)", focus["background"])
        self.assertEqual("var(--bg)", focus["color"])
        self.assertGreaterEqual(a11y.contrast(fg, bg), 4.5)       # text: ink on paper, 21:1
        self.assertGreaterEqual(a11y.contrast(fg, bg), 3.0)       # ring against the page
        self.assertEqual("fixed", focus["position"])              # stays put under a sticky header
        self.assertGreaterEqual(int(focus["z-index"]), 1000)

    def test_no_new_colours_and_no_transition(self):
        self.assertNotRegex(CSS, r"#[0-9a-fA-F]{3,6}\b")
        self.assertNotIn("transition", CSS)                        # so nothing to gate on reduced-motion


class PortalPageTests(unittest.TestCase):
    def test_every_portal_page_has_skip_link_first_and_one_main(self):
        pages = a11y.unique_pages()
        self.assertGreater(len(pages), 25)
        for label, markup, root in pages:
            with self.subTest(page=label):
                body = next(e for e in root.walk() if e.tag == "body")
                first = next(e for e in body.walk() if e is not body)
                self.assertEqual("a", first.tag)
                self.assertEqual(["skip-link"], first.classes)
                self.assertEqual("#main", first.attrs["href"])
                self.assertEqual("Skip to main content", first.text())
                focusable = [e for e in body.walk() if e.tag == "a" and "href" in e.attrs]
                self.assertIs(first, focusable[0])
                mains = [e for e in root.walk() if e.tag == "main"]
                self.assertEqual(1, len(mains))
                self.assertEqual("main", mains[0].attrs.get("id"))
                self.assertEqual("-1", mains[0].attrs.get("tabindex"))
                self.assertEqual(1, len(re.findall(r'\bid="main"', markup)))
                self.assertEqual(1, len(re.findall(r"<main\b", markup)))


if __name__ == "__main__":
    unittest.main()
