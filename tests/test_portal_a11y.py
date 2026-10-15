"""Accessibility tests for services/avrana-portal/portal.py (AVR-357, sprint item S1-4).

Offline and stdlib only. Pages come from the real Handler through the in-memory helper in
tests/test_portal_authz.py (every identity class in tests/fixtures/identities.py, including the
denied 404 and the empty-handed member), plus direct calls to the module's render functions for
pages no single identity reaches. Nothing here needs a browser, so it cannot judge rendering:
it pins what can be read from markup and the stylesheet. The axe-core, 390px/1280px and
text-zoom checks belong to the browser harness under tests/ui/ (S1-5).

The numbers come from docs/design/DESIGN.md: Control Rule #6e6e6e for interactive edges (WCAG
1.4.11, at least 3:1), Quiet Rule #474747 for dividers, text at least 4.5:1, the two-ring focus
indicator, 44px targets for footer and store links, no em or en dashes, no first person.
"""
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_portal_authz as authz  # noqa: E402  (shared in-memory harness, not its test classes)
from fixtures.identities import IDENTITIES  # noqa: E402

portal = authz.portal

# ---------------------------------------------------------------------------------------------
# Colour maths (WCAG 2.x relative luminance)
# ---------------------------------------------------------------------------------------------


def parse_color(value, backdrop=(0, 0, 0)):
    """'#rgb', '#rrggbb' or 'rgba(r,g,b,a)' -> (r, g, b) composited over `backdrop`."""
    v = value.strip().lower()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", v)
    if not m:
        raise ValueError(f"unsupported colour {value!r}")
    r, g, b = (int(m.group(i)) for i in (1, 2, 3))
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    return tuple(round(a * c + (1 - a) * k) for c, k in zip((r, g, b), backdrop))


def luminance(rgb):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ---------------------------------------------------------------------------------------------
# A small HTML tree (stdlib parser) with the queries the tests need
# ---------------------------------------------------------------------------------------------

VOID = {"meta", "link", "br", "img", "input", "hr", "area", "base", "col", "embed", "source",
        "track", "wbr"}


class El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, dict(attrs), parent, []

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def walk(self):
        yield self
        for k in self.kids:
            if isinstance(k, El):
                yield from k.walk()

    def ancestors(self):
        p = self.parent
        while p is not None:
            yield p
            p = p.parent

    def text(self):
        """Text a screen reader would read: descendants, minus aria-hidden, style and script."""
        if self.attrs.get("aria-hidden") == "true" or self.tag in ("style", "script"):
            return ""
        out = []
        for k in self.kids:
            out.append(k if isinstance(k, str) else k.text())
        return re.sub(r"\s+", " ", " ".join(out)).strip()

    def name(self):
        """Accessible name: aria-label wins, else the text content."""
        return (self.attrs.get("aria-label") or "").strip() or self.text()


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = El("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        el = El(tag, [(k, v if v is not None else "") for k, v in attrs], self.cur)
        self.cur.kids.append(el)
        if tag not in VOID:
            self.cur = el

    def handle_endtag(self, tag):
        e = self.cur
        while e is not None and e.tag != tag:
            e = e.parent
        if e is not None and e.parent is not None:
            self.cur = e.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def parse(markup):
    t = Tree()
    t.feed(markup)
    t.close()
    return t.root


def visible_strings(root):
    """Every string a member can read or hear: text nodes (not CSS), <title>, and the text-bearing
    attributes."""
    out = []
    for el in root.walk():
        if el.tag in ("style", "script"):
            continue
        out += [k for k in el.kids if isinstance(k, str) and k.strip()]
        for attr in ("aria-label", "title", "alt", "placeholder"):
            if el.attrs.get(attr):
                out.append(el.attrs[attr])
    return out


# ---------------------------------------------------------------------------------------------
# Pages under test
# ---------------------------------------------------------------------------------------------

_pages = None


def pages():
    """label -> markup, for every page a request can produce and every render function."""
    global _pages
    if _pages is not None:
        return _pages
    out = {}
    for ident in IDENTITIES:
        for route in authz.ROUTES + ["/definitely-not-a-route", "/ops/", "/watch/", "/read/", "/request"]:
            if route == "/healthz":
                continue
            r = authz.fetch(ident, route)
            if r.status in (200, 404) and r.body:
                out[(ident, route)] = r.text
    named = authz.request("/account", authz.ident_headers("all_members") + [
        ("X-authentik-name", "Member A"), ("X-authentik-username", "member-a"),
        ("X-authentik-email", "a@example.test")])
    out[("all_members", "/account (named)")] = named.text
    everything = {g for spec, *_r in portal.SERVICES for g in (spec if isinstance(spec, tuple) else (spec,))}
    out[("direct", "render_home")] = portal.render_home(everything)
    for ch in portal.CHOOSERS:
        out[("direct", "render_chooser " + ch[2])] = portal.render_chooser(
            ch, portal.chooser_members(ch, everything), everything)
    for topic in portal.HELP:
        out[("direct", "render_help_page " + topic[1])] = portal.render_help_page(topic)
    out[("direct", "render_help_index")] = portal.render_help_index(portal.help_permitted(everything))
    out[("direct", "render_help_index empty")] = portal.render_help_index([])
    out[("direct", "render_account empty")] = portal.render_account(set(), "", "", "")
    out[("direct", "render_interstitial")] = portal.render_interstitial(
        portal.by_path("watch"), *portal.INTERSTITIALS["watch"])
    out[("direct", "render_404")] = portal.render_404()
    _pages = out
    return out


_trees = {}


def unique_pages():
    """(first label, markup, tree) for each distinct page body."""
    seen = {}
    for label, markup in pages().items():
        if markup not in seen:
            if markup not in _trees:
                _trees[markup] = parse(markup)
            seen[markup] = (label, markup, _trees[markup])
    return list(seen.values())


# ---------------------------------------------------------------------------------------------
# Stylesheet helpers
# ---------------------------------------------------------------------------------------------

CSS = portal.STYLE


def css_rules(css=None):
    """Flat [(selector, {prop: value})]. Media queries are flattened: their rules still count."""
    css = re.sub(r"/\*.*?\*/", "", css or CSS, flags=re.S)
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel = re.sub(r"\s+", " ", m.group(1)).strip()
        decls = {}
        for d in m.group(2).split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                decls[k.strip().lower()] = re.sub(r"\s+", " ", v).strip()
        out.append((sel, decls))
    return out


def tokens():
    out = {}
    for sel, decls in css_rules():
        if sel == ":root":
            out.update({k: v for k, v in decls.items() if k.startswith("--")})
    return out


def resolve(value, toks=None, backdrop=(0, 0, 0)):
    toks = toks or tokens()
    m = re.fullmatch(r"var\((--[\w-]+)\)", value.strip())
    return parse_color(toks[m.group(1)] if m else value, backdrop)


def selectors(sel):
    return [s.strip() for s in sel.split(",")]


def rule_for(selector, prop=None):
    """Declarations of every rule whose selector list contains `selector` exactly."""
    found = [d for sel, d in css_rules() if selector in selectors(sel)]
    return [d for d in found if prop is None or prop in d]


BG = (0, 0, 0)


# ---------------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------------

class ColourMathTests(unittest.TestCase):
    """The checker has to be right before its verdicts mean anything."""

    def test_known_ratios(self):
        self.assertAlmostEqual(21.0, contrast((255, 255, 255), (0, 0, 0)), places=6)
        self.assertAlmostEqual(1.0, contrast((9, 9, 9), (9, 9, 9)), places=6)
        self.assertAlmostEqual(4.1, contrast(parse_color("#6e6e6e"), BG), delta=0.1)   # DESIGN.md: 4.1:1
        self.assertAlmostEqual(2.3, contrast(parse_color("#474747"), BG), delta=0.1)   # DESIGN.md: 2.3:1
        self.assertAlmostEqual(7.4, contrast(parse_color("#9a9a9a"), BG), delta=0.1)   # DESIGN.md: 7.4:1

    def test_rgba_is_composited_over_the_backdrop(self):
        # The old --line token: 28% white on black is #474747 and fails 1.4.11.
        self.assertEqual((71, 71, 71), parse_color("rgba(255,255,255,0.28)", BG))
        self.assertLess(contrast(parse_color("rgba(255,255,255,0.28)", BG), BG), 3.0)
        self.assertEqual((153, 153, 153), parse_color("rgba(255,255,255,0.6)", BG))
        self.assertEqual((255, 255, 255), parse_color("#fff"))


class DocumentTests(unittest.TestCase):
    def test_there_are_pages_to_check(self):
        labels = pages()
        self.assertGreater(len(labels), 400)
        self.assertGreater(len(unique_pages()), 25)
        for must in [("no_header", "/"), ("empty_header", "/help"), ("baseline_only", "/account"),
                     ("videos", "/help/movies"), ("videos", "/watch"), ("no_header", "/nope"),
                     ("books", "/read"), ("direct", "render_404")]:
            self.assertIn(must, labels)
        statuses = {authz.fetch("videos", "/ops").status, authz.fetch("videos", "/").status}
        self.assertEqual({200, 404}, statuses)

    def test_language_viewport_color_scheme_and_title(self):
        for label, _m, root in unique_pages():
            with self.subTest(page=label):
                html_el = next(e for e in root.walk() if e.tag == "html")
                self.assertTrue(html_el.attrs.get("lang"), "html lang")
                metas = {e.attrs.get("name"): e.attrs.get("content", "") for e in root.walk() if e.tag == "meta"}
                self.assertIn("width=device-width", metas.get("viewport", ""))
                self.assertNotIn("user-scalable=no", metas.get("viewport", ""))
                self.assertNotIn("maximum-scale", metas.get("viewport", ""))
                self.assertEqual("dark", metas.get("color-scheme"))
                titles = [e.text() for e in root.walk() if e.tag == "title"]
                self.assertEqual(1, len(titles))
                self.assertTrue(titles[0])

    def test_exactly_one_h1_and_no_skipped_heading_level(self):
        for label, _m, root in unique_pages():
            heads = [(int(e.tag[1]), e.text()) for e in root.walk() if re.fullmatch(r"h[1-6]", e.tag)]
            with self.subTest(page=label):
                self.assertEqual(1, sum(1 for lvl, _t in heads if lvl == 1), heads)
                self.assertEqual(1, heads[0][0], "first heading must be the h1")
                prev = 0
                for lvl, text in heads:
                    self.assertLessEqual(lvl, prev + 1, f"{text!r} skips a level after h{prev}")
                    self.assertTrue(text, "empty heading")
                    prev = lvl

    def test_help_topic_pages_name_their_topic_with_an_h2(self):
        for topic in portal.HELP:
            label = topic[1]
            root = parse(portal.render_help_page(topic))
            with self.subTest(topic=label):
                h2s = [e for e in root.walk() if e.tag == "h2"]
                self.assertGreaterEqual(len(h2s), 1)
                first_h2 = h2s[0]
                self.assertEqual(label, first_h2.text())
                heads = [e for e in root.walk() if re.fullmatch(r"h[1-6]", e.tag)]
                self.assertIs(first_h2, heads[1], "the topic headline comes straight after the h1")
                self.assertTrue(any(e.tag == "h3" for e in root.walk()), "platforms stay h3 under it")

    def test_landmarks(self):
        for label, _m, root in unique_pages():
            els = list(root.walk())
            with self.subTest(page=label):
                for tag in ("main", "header", "footer"):
                    self.assertEqual(1, sum(1 for e in els if e.tag == tag), tag)
                main = next(e for e in els if e.tag == "main")
                header = next(e for e in els if e.tag == "header")
                footer = next(e for e in els if e.tag == "footer")
                self.assertIn("h1", {e.tag for e in header.walk()})
                self.assertNotIn(main, list(header.ancestors()) + list(footer.ancestors()))
                # header and footer sit outside <main>, so they are page-level banner/contentinfo
                for part in (header, footer):
                    self.assertNotIn("main", {a.tag for a in part.ancestors()})
                navs = [e for e in els if e.tag == "nav"]
                self.assertTrue(navs)
                names = [n.attrs.get("aria-label", "").strip() for n in navs]
                self.assertTrue(all(names), f"every nav needs a label: {names}")
                self.assertEqual(len(names), len(set(names)), f"nav labels must differ: {names}")
                self.assertTrue(any(n in footer.walk() for n in navs), "footer links live in a nav")
                self.assertTrue([e for e in footer.walk() if e.tag == "a"], "footer has links")

    def test_every_interactive_element_is_a_link_or_button_with_a_name(self):
        for label, _m, root in unique_pages():
            with self.subTest(page=label):
                for e in root.walk():
                    if e.tag in ("input", "select", "textarea", "summary", "area") or \
                            "onclick" in e.attrs or "tabindex" in e.attrs or \
                            e.attrs.get("role") in ("button", "link", "tab", "menuitem"):
                        self.fail(f"<{e.tag}> is interactive but is not an <a> or <button>")
                    if e.tag in ("a", "button"):
                        self.assertTrue(e.name(), f"<{e.tag}> has no accessible name: {e.attrs}")
                        if e.tag == "a":
                            self.assertTrue(e.attrs.get("href"), "a link without href is not focusable")
                            self.assertNotIn("a", {a.tag for a in e.ancestors()}, "nested link")

    def test_new_tab_links_are_safe_and_say_so(self):
        seen = 0
        for label, _m, root in unique_pages():
            with self.subTest(page=label):
                for e in root.walk():
                    if e.tag == "a" and e.attrs.get("target") == "_blank":
                        seen += 1
                        rel = set(e.attrs.get("rel", "").split())
                        self.assertLessEqual({"noopener", "noreferrer"}, rel)
                        self.assertRegex(e.name(), r"(?i)\bnew (tab|window)\b")
                    if e.tag == "a" and e.attrs.get("target") not in (None, "", "_self", "_blank"):
                        self.fail("unexpected link target " + e.attrs["target"])
        self.assertGreater(seen, 10, "the help pages carry store links; the check must see them")

    def test_message_blocks_carry_the_right_role_and_no_page_has_a_live_region(self):
        """Every block here is present at page load; the portal has no live updates. So no GET page
        has role=status or role=alert, the interstitial warning is a note, and the rest are plain
        paragraphs."""
        expect = {   # start of the text -> required role (None means the attribute is absent)
            "Nothing is set up on this account yet": None,
            "That page does not exist": None,
            "It is advised to use": "note",
        }
        msg_start = re.compile("^(" + "|".join(re.escape(k) for k in expect) + ")")
        seen = {}
        for label, _m, root in unique_pages():
            with self.subTest(page=label):
                for e in root.walk():
                    self.assertNotIn(e.attrs.get("role"), ("status", "alert"), f"{e.tag}: {e.text()}")
                    self.assertFalse({"aria-live", "aria-atomic"} & set(e.attrs), e.tag)
                    if e.tag == "p" and msg_start.match(e.text()):
                        key = msg_start.match(e.text()).group(1)
                        seen[key] = seen.get(key, 0) + 1
                        self.assertEqual(expect[key], e.attrs.get("role"), e.text())
                    if "msg" in e.classes:
                        self.assertTrue(msg_start.match(e.text()), e.text())
        self.assertEqual(set(expect), set(seen), "the empty, 404 and interstitial messages must all be seen")

    def test_footer_nav_is_labelled_footer(self):
        for label, _m, root in unique_pages():
            with self.subTest(page=label):
                footer = next(e for e in root.walk() if e.tag == "footer")
                navs = [e for e in footer.walk() if e.tag == "nav"]
                self.assertEqual(["Footer"], [n.attrs.get("aria-label") for n in navs])

    def test_interstitial_continue_link_names_its_destination_as_one_phrase(self):
        root = parse(portal.render_interstitial(portal.by_path("watch"), *portal.INTERSTITIALS["watch"]))
        links = [e for e in root.walk() if e.tag == "a" and e.attrs.get("href", "").startswith("https://")
                 and "tile" in e.classes]
        self.assertEqual(1, len(links))
        name = links[0].name()
        self.assertEqual("Understood, continue to watch.avrana.net", name)
        # the visible label stays inside the accessible name (WCAG 2.5.3 label in name)
        self.assertIn("Understood", links[0].text())
        self.assertIn("Understood", name)
        self.assertEqual(1, name.count("watch.avrana.net"))

    def test_step_lists_are_lists(self):
        for topic in portal.HELP:
            root = parse(portal.render_help_page(topic))
            with self.subTest(topic=topic[1]):
                lists = [e for e in root.walk() if e.tag == "ol"]
                self.assertEqual(sum(1 for _p, cl in topic[3] for _c in cl), len(lists))
                want = sum(len(c[3]) for _p, cl in topic[3] for c in cl)
                got = sum(1 for ol in lists for k in ol.kids if isinstance(k, El) and k.tag == "li")
                self.assertEqual(want, got)

    def test_account_facts_use_a_description_list(self):
        root = parse(authz.fetch("all_members", "/account").text)
        dl = [e for e in root.walk() if e.tag == "dl"]
        self.assertEqual(1, len(dl))
        self.assertTrue([e for e in dl[0].walk() if e.tag == "dt"])
        self.assertTrue([e for e in root.walk() if e.tag == "ul" and "access" in e.classes])


class CopyTests(unittest.TestCase):
    DASHES = "‒–—―"

    def test_no_em_or_en_dash_in_member_visible_text(self):
        for label, _m, root in unique_pages():
            with self.subTest(page=label):
                for s in visible_strings(root):
                    for ch in self.DASHES:
                        self.assertNotIn(ch, s, s)
                    self.assertNotIn(" -- ", s)

    def test_no_first_person(self):
        rx = re.compile(r"\b(we|our|ours|ourselves|us|i|my|mine|me)\b", re.I)
        for label, _m, root in unique_pages():
            with self.subTest(page=label):
                for s in visible_strings(root):
                    self.assertIsNone(rx.search(s), s)

    def test_the_dash_and_person_checks_are_not_vacuous(self):
        root = parse("<p>Settings — playback — live here. We will help. I understand.</p>")
        strings = visible_strings(root)
        self.assertTrue(any("—" in s for s in strings))
        rx = re.compile(r"\b(we|our|ours|ourselves|us|i|my|mine|me)\b", re.I)
        self.assertTrue(rx.search(strings[0]))


class StylesheetTests(unittest.TestCase):
    def test_stylesheet_in_pages_is_the_module_stylesheet(self):
        for label, markup, _root in unique_pages():
            with self.subTest(page=label):
                self.assertIn(portal.STYLE, markup)

    def test_color_scheme_dark_is_declared(self):
        root = [d for sel, d in css_rules() if sel == ":root"][0]
        self.assertEqual("dark", root.get("color-scheme"))

    def test_text_colours_meet_4_5_to_1(self):
        toks = tokens()
        # Every colour a rule sets for text must be one of these, so the pairs below cover the sheet.
        allowed = {"var(--fg)", "var(--dim)", "var(--bg)", "var(--dim-on-fg)", "inherit"}
        used = {d["color"] for _s, d in css_rules() if "color" in d}
        self.assertLessEqual(used, allowed, "a new text colour needs a contrast pair here")
        on_page = [("var(--fg)", BG), ("var(--dim)", BG)]
        fg = resolve("var(--fg)", toks)
        on_inverted = [("var(--bg)", fg), ("var(--dim-on-fg)", fg)]
        for token, backdrop in on_page + on_inverted:
            with self.subTest(text=token, on=backdrop):
                self.assertGreaterEqual(contrast(resolve(token, toks), backdrop), 4.5)
        # The inverted pairs are only valid where the ground really is inverted.
        for sel, d in css_rules():
            if d.get("color") in ("var(--bg)", "var(--dim-on-fg)"):
                self.assertTrue(all(":hover" in s or ":focus-visible" in s for s in selectors(sel)), sel)
        # the page ground is the one the pairs assume
        body = [d for sel, d in css_rules() if sel == "body"][0]
        self.assertEqual("var(--bg)", body["background"])
        self.assertEqual((0, 0, 0), resolve("var(--bg)", toks))

    def test_control_rule_edges_meet_3_to_1_and_dividers_keep_the_quiet_rule(self):
        toks = tokens()
        self.assertEqual((0x6e, 0x6e, 0x6e), resolve("var(--rule-control)", toks))
        self.assertEqual((0x47, 0x47, 0x47), resolve("var(--rule-quiet)", toks))
        self.assertEqual((0x99, 0x99, 0x99), resolve("var(--rule-strong)", toks))
        self.assertGreaterEqual(contrast(resolve("var(--rule-control)", toks), BG), 3.0)
        # every border or rule drawn on something clickable clears 3:1 against the page
        interactive = re.compile(r"^(a|button|input|select|textarea)\b")
        checked = 0
        for sel, d in css_rules():
            if not any(interactive.match(s) for s in selectors(sel)):
                continue
            for prop in ("border", "border-color", "border-bottom", "outline", "outline-color",
                         "text-decoration-color"):
                if prop in d and "transparent" not in d[prop]:
                    m = re.search(r"(var\(--[\w-]+\)|#[0-9a-fA-F]{3,6}|rgba?\([^)]*\))", d[prop])
                    self.assertTrue(m, f"{sel} {prop}: {d[prop]}")
                    with self.subTest(selector=sel, prop=prop):
                        self.assertGreaterEqual(contrast(resolve(m.group(1), toks), BG), 3.0, d[prop])
                        self.assertNotIn("--rule-quiet", d[prop])
                    checked += 1
        self.assertGreaterEqual(checked, 3)
        tile = rule_for("a.tile", "border")[0]
        self.assertIn("var(--rule-control)", tile["border"])
        # dividers and chips that are not controls keep the quiet rule
        for sel in (".platform", "ul.access li"):
            self.assertTrue(any("var(--rule-quiet)" in " ".join(d.values()) for d in rule_for(sel)), sel)

    def test_one_focus_ring_covers_every_link(self):
        ring = rule_for("a:focus-visible")
        self.assertEqual(1, len(ring))
        d = ring[0]
        self.assertEqual("0 0 0 2px var(--bg),0 0 0 4px var(--fg)", d["box-shadow"].replace(", ", ","))
        self.assertEqual("2px solid transparent", d["outline"])   # keeps Windows High Contrast ring
        toks = tokens()
        self.assertGreaterEqual(contrast(resolve("var(--fg)", toks), BG), 3.0)
        # Everything interactive on every page is an <a>, which `a:focus-visible` reaches.
        for label, _m, root in unique_pages():
            for e in root.walk():
                if e.tag == "a":
                    self.assertTrue(e.classes and set(e.classes) <= {"tile", "account", "store"}
                                    or "h1" in {a.tag for a in e.ancestors()},
                                    f"{label}: link outside the styled classes {e.attrs}")
        # and no rule weakens the ring for any state
        for sel, decl in css_rules():
            if "focus" in sel:
                self.assertNotIn("box-shadow", decl if sel != "a:focus-visible" else {}, sel)

    def test_outline_is_never_removed_without_the_ring(self):
        """Any rule that sets outline none/0 needs a :focus-visible rule for the SAME selector that
        draws a visible ring (a box-shadow other than none)."""
        removal = re.compile(r"^(none|0|0px)\b|\bnone\b")
        rules = css_rules()
        for sel, d in rules:
            for prop in ("outline", "outline-style", "outline-width"):
                if prop not in d or not removal.search(d[prop]):
                    continue
                for one in selectors(sel):
                    base = re.sub(r":(hover|focus|focus-visible)$", "", one)
                    ring = [x for x in rules if base + ":focus-visible" in selectors(x[0])
                            and x[1].get("box-shadow", "none") != "none"]
                    with self.subTest(selector=one):
                        self.assertTrue(ring, f"{one} removes the outline without a :focus-visible ring")
        # the stylesheet as shipped removes none at all, and keeps the transparent outline instead
        self.assertFalse([sel for sel, d in rules if any(
            removal.search(d.get(p, "")) for p in ("outline", "outline-style", "outline-width"))])

    def test_focus_does_not_rely_on_colour_inversion_alone(self):
        # tiles invert on hover AND focus; the ring is applied independently by a:focus-visible
        inv = [sel for sel, d in css_rules() if d.get("background") == "var(--fg)"]
        self.assertTrue(any("a.tile:focus-visible" in s for sel in inv for s in selectors(sel)))
        ring_selectors = [s for sel, d in css_rules() if "box-shadow" in d for s in selectors(sel)]
        self.assertIn("a:focus-visible", ring_selectors)

    def test_footer_account_and_store_links_reach_44px(self):
        rules = rule_for("a.account") + rule_for("a.store")
        self.assertTrue(rules)
        sized = [d for d in rules if d.get("min-height") == "44px"]
        self.assertTrue(sized, "min-height:44px on the footer and store links")
        self.assertTrue(all(d.get("display") in ("inline-block", "inline-flex", "flex", "block")
                            for d in sized), "min-height needs a box that honours it")
        self.assertEqual(sized[0], rule_for("a.store", "min-height")[0])
        self.assertEqual(sized[0], rule_for("a.account", "min-height")[0])

    def _tile_state_colours(self, state):
        """(background, {where: colour}) of text in a tile in a hover/focus state, from the sheet."""
        toks = tokens()
        tile = [d for sel, d in css_rules() if f"a.tile:{state}" in selectors(sel)]
        self.assertTrue(tile, f"a.tile:{state} must have a rule")
        bg = resolve(next(d["background"] for d in tile if "background" in d), toks)
        base = next(d["color"] for d in tile if "color" in d)
        texts = {"tile": resolve(base, toks)}
        for sel, d in css_rules():
            for s in selectors(sel):
                if s.startswith(f"a.tile:{state} ") and "color" in d:
                    texts[s] = resolve(d["color"], toks)
        # label and host inherit the tile's colour; a rule of their own would escape this check
        for sel, d in css_rules():
            for s in selectors(sel):
                if s.startswith("a.tile .") and s != "a.tile .desc" and "color" in d:
                    self.fail(f"{s} sets its own colour; it would escape the inverted-state check")
        return bg, texts

    def test_tile_text_meets_4_5_to_1_when_inverted_on_hover_and_focus(self):
        for state in ("hover", "focus-visible"):
            with self.subTest(state=state):
                bg, texts = self._tile_state_colours(state)
                self.assertIn(f"a.tile:{state} .desc", texts, "the description needs its own inverted colour")
                for where, rgb in texts.items():
                    self.assertGreaterEqual(contrast(rgb, bg), 4.5, f"{where} on {bg} in :{state}")

    def test_inverted_tile_check_catches_the_known_bad_grey(self):
        self.assertAlmostEqual(2.81, contrast(parse_color("#9a9a9a"), (255, 255, 255)), delta=0.01)
        self.assertLess(contrast(parse_color("#9a9a9a"), (255, 255, 255)), 4.5)

    def test_visually_hidden_text_uses_clip_and_position_not_display_none(self):
        sr = rule_for(".sr")
        self.assertEqual(1, len(sr))
        d = sr[0]
        self.assertEqual("absolute", d.get("position"))
        self.assertEqual("1px", d.get("width"))
        self.assertEqual("1px", d.get("height"))
        self.assertEqual("hidden", d.get("overflow"))
        self.assertRegex(d.get("clip", "").replace(" ", ""), r"^rect\(0(px)?,0(px)?,0(px)?,0(px)?\)$")
        self.assertEqual("nowrap", d.get("white-space"))
        # nothing in the stylesheet hides it from assistive technology
        for sel, decl in css_rules():
            if any(re.search(r"\.sr\b|\bspan\b", s) for s in selectors(sel)):
                self.assertNotEqual("none", decl.get("display"), sel)
                self.assertNotIn(decl.get("visibility"), ("hidden", "collapse"), sel)
                self.assertNotEqual("0", decl.get("opacity"), sel)
        seen = 0
        for _label, _m, root in unique_pages():
            for e in root.walk():
                if "sr" in e.classes:
                    seen += 1
                    self.assertNotIn("hidden", e.attrs)
                    self.assertNotIn("style", e.attrs)
                    self.assertNotEqual("true", e.attrs.get("aria-hidden"))
                    self.assertEqual(" (opens in a new tab)", "".join(k for k in e.kids if isinstance(k, str)))
        self.assertGreater(seen, 10)

    def test_store_link_target_does_not_overlap_adjacent_text(self):
        def px(v):
            m = re.fullmatch(r"(-?\d+(?:\.\d+)?)px", v)
            self.assertTrue(m, v)
            return float(m.group(1))

        def sides(v):
            """(top, bottom) of a one-, two- or three/four-value shorthand."""
            parts = v.split()
            return (parts[0], parts[0]) if len(parts) < 3 else (parts[0], parts[2])

        merged = {}
        for d in rule_for("a.store"):
            merged.update(d)
        self.assertEqual("44px", merged["min-height"])
        pad_t, pad_b = (px(x) for x in sides(merged["padding"]))
        mar_t, mar_b = (px(x) for x in sides(merged["margin"]))
        gap = px(rule_for(".client")[0]["gap"])
        ol_top = px(rule_for(".client ol")[0]["margin"].split()[0])
        # how far the 44px target reaches past its own layout box, above and below
        self.assertLessEqual(-mar_t, gap, "the target reaches into the app name above it")
        self.assertLessEqual(-mar_b, gap + ol_top, "the target reaches into the first step below it")
        self.assertGreaterEqual(pad_t + pad_b + 22, 44 - 2.5, "padding plus one line must still make about 44px")

    def test_text_can_grow_without_clipping_or_sideways_scroll(self):
        small_boxes = {".rule", ".sr"}
        for sel, d in css_rules():
            for prop, val in d.items():
                where = f"{sel} {{{prop}:{val}}}"
                if prop in ("height", "max-height") and not set(selectors(sel)) <= small_boxes:
                    self.fail("fixed height can clip enlarged text: " + where)
                if prop == "overflow" and "hidden" in val and not set(selectors(sel)) <= small_boxes:
                    self.fail("overflow:hidden can clip: " + where)
                if prop == "white-space" and "nowrap" in val and not set(selectors(sel)) <= small_boxes:
                    self.fail("nowrap forces sideways scroll: " + where)
                if prop == "font-size":
                    self.assertNotRegex(val, r"^\d+(\.\d+)?px$", where)
                if prop in ("width", "min-width") and not set(selectors(sel)) <= small_boxes | {".page"}:
                    self.assertRegex(val, r"^(100%|auto)$", where)
        page = rule_for(".page")[0]
        self.assertEqual("100%", page["width"])
        self.assertRegex(page["max-width"], r"^720px$")

    def test_long_strings_wrap_instead_of_overflowing_a_390px_screen(self):
        for sel in ("h1", "a.tile", ".client ol li", "dl.facts dd"):
            with self.subTest(selector=sel):
                self.assertTrue(rule_for(sel, "overflow-wrap"), sel)
                self.assertEqual("anywhere", rule_for(sel, "overflow-wrap")[0]["overflow-wrap"])
        grid = rule_for("nav.tiles", "grid-template-columns")
        self.assertIn("minmax(0,1fr)", grid[0]["grid-template-columns"])
        # the phone layout collapses the grid to one column and narrows the gutters
        phone = [d for sel, d in css_rules() if sel == "nav.tiles" and d.get("grid-template-columns") == "1fr"]
        self.assertTrue(phone)
        self.assertIn("(max-width:560px)", CSS)
        # the wordmark can never be wider than the viewport it sits in
        self.assertIn("min(clamp(2.6rem,9vw,4.4rem)", rule_for("h1", "font-size")[0]["font-size"].replace(" ", ""))

    def test_motion_is_reduced_on_request(self):
        self.assertIn("prefers-reduced-motion:reduce", CSS.replace(" ", ""))

    def test_no_state_is_carried_by_colour_alone(self):
        # The portal uses no status colours at all: nothing here needs a word beside it.
        toks = tokens()
        self.assertFalse({"--ok", "--warn", "--err"} & set(toks))


if __name__ == "__main__":
    unittest.main()
