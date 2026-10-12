"""Accessibility and copy checks for the Kindle connector pages (Media 2.0 Sprint 1, item S1-4 / AVR-358).

Offline and standard library only (html.parser). Every page state is rendered from the connector's own
code with synthetic data; the stylesheet is then read back out of the page and the checks are computed
from it: a small cascade (specificity, order, inheritance, pseudo-class state) decides which colour,
border, ring and size an element really ends up with, so a later rule that cancels an earlier fix
is caught the same way a browser would show it. No network, no Docker, no credentials.

What this can not do: it is not a browser. Layout, real font metrics, 200% text zoom and screen reader
speech need a real browser and are listed as gaps in the pull request.

Run: python -B -m unittest discover -s services/avrana-kindle-connector/tests -p test_a11y.py
"""
import html.parser
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_authz as T  # noqa: E402  (reuses the loopback harness, the fakes and the synthetic fixtures)

kindle = T.kindle

# ---------------------------------------------------------------- design tokens (docs/design/DESIGN.md)
TOKENS = {"--ink": "#000000", "--paper": "#ffffff", "--ash": "#9a9a9a", "--rule-quiet": "#474747",
          "--rule-control": "#6e6e6e", "--rule-strong": "#999999", "--ok": "#8fe3a6", "--err": "#ff8b8b"}
VOID = {"meta", "link", "input", "br", "hr", "img"}
INTERACTIVE = {"a", "button", "input"}


# ---------------------------------------------------------------- html model
class El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.classes = set((self.attrs.get("class") or "").split())
        self.text, self.children = [], []

    def chain(self):
        e, out = self, []
        while e is not None:
            out.append(e)
            e = e.parent
        return out

    @property
    def own_text(self):
        return " ".join(" ".join(self.text).split())

    @property
    def all_text(self):
        return " ".join(" ".join(self.text + [c.all_text for c in self.children]).split())


class Doc(html.parser.HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = El("#root", {}, None)
        self.cur, self.all, self.css, self.doctype = self.root, [], "", False
        self._in_style = False
        self.feed(source)
        self.close()

    def handle_decl(self, decl):
        self.doctype = decl.lower().startswith("doctype html")

    def handle_starttag(self, tag, attrs):
        e = El(tag, [(k, v if v is not None else "") for k, v in attrs], self.cur)
        self.cur.children.append(e)
        self.all.append(e)
        if tag not in VOID:
            self.cur = e
        self._in_style = tag == "style"

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        e = self.cur
        while e is not None and e.tag != tag:
            e = e.parent
        if e is not None and e.parent is not None:
            self.cur = e.parent
        self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.css += data
        elif data.strip():
            self.cur.text.append(data)

    # -- queries
    def find(self, tag=None, **attr):
        return [e for e in self.all if (tag is None or e.tag == tag)
                and all(e.attrs.get(k.replace("_", "-")) == v for k, v in attr.items())]

    @property
    def visible_elements(self):
        return [e for e in self.all if e.tag not in ("style", "script", "head", "meta", "title", "html")]

    @property
    def visible_text(self):
        """Everything a member can see or hear: text nodes, plus the title and text-bearing attributes."""
        bits = [e.own_text for e in self.all if e.tag not in ("style", "script")]
        for e in self.all:
            for a in ("placeholder", "aria-label", "title", "alt"):
                if e.attrs.get(a):
                    bits.append(e.attrs[a])
        return "\n".join(b for b in bits if b)


# ---------------------------------------------------------------- css model: just enough cascade
class Rule:
    def __init__(self, selector, decls, order, media):
        self.selector, self.decls, self.order, self.media = selector.strip(), decls, order, media


def parse_css(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules, order = [], [0]

    def block(text, media):
        i = 0
        while i < len(text):
            j = text.find("{", i)
            if j < 0:
                break
            head, depth, k = text[i:j].strip(), 1, j + 1
            while depth and k < len(text):
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            body = text[j + 1:k - 1]
            if head.startswith("@media"):
                block(body, head[6:].strip())
            elif head.startswith("@"):
                pass
            else:
                decls = {}
                for d in body.split(";"):
                    if ":" in d:
                        n, _, v = d.partition(":")
                        decls[n.strip().lower()] = v.strip()
                for sel in head.split(","):
                    order[0] += 1
                    rules.append(Rule(sel, decls, order[0], media))
            i = k

    block(css, None)
    return rules


def specificity(sel):
    ids = len(re.findall(r"#[\w-]+", sel))
    cls = len(re.findall(r"\.[\w-]+|\[[^\]]+\]|:(?!:)[\w-]+", sel))
    tags = len(re.findall(r"(?:^|[\s>+~])[a-zA-Z][\w-]*", sel))
    return ids, cls, tags


def _compound_matches(comp, el, state):
    if "::" in comp:
        return False  # pseudo-elements (::placeholder) style no element of ours in the states tested
    for pseudo in re.findall(r"(?<!:):([\w-]+)", comp):
        if pseudo == "root":
            if el.tag != "html":
                return False
        elif pseudo not in state:
            return False
    comp = re.sub(r"(?<!:):[\w-]+", "", comp)
    m = re.match(r"^([a-zA-Z][\w-]*|\*)?", comp)
    if m.group(1) and m.group(1) not in ("*", el.tag):
        return False
    for c in re.findall(r"\.([\w-]+)", comp):
        if c not in el.classes:
            return False
    for a, v in re.findall(r"\[([\w-]+)=([^\]]+)\]", comp):
        if el.attrs.get(a) != v.strip("\"'"):
            return False
    for a in re.findall(r"\[([\w-]+)\]", comp):
        if a not in el.attrs:
            return False
    return True


def selector_matches(sel, el, state):
    parts = re.split(r"\s*[>\s]\s*", sel.strip())
    if not _compound_matches(parts[-1], el, state):
        return False
    anc = el.parent
    for comp in reversed(parts[:-1]):
        while anc is not None and not _compound_matches(comp, anc, set()):
            anc = anc.parent
        if anc is None:
            return False
        anc = anc.parent
    return True


class Sheet:
    def __init__(self, css):
        self.rules = parse_css(css)
        self._memo = {}
        self.vars = {}
        for r in self.rules:
            if r.selector == ":root":
                self.vars.update({k: v for k, v in r.decls.items() if k.startswith("--")})

    def resolve(self, value, depth=0):
        if value is None or depth > 5:
            return value
        return re.sub(r"var\((--[\w-]+)\)", lambda m: self.resolve(self.vars.get(m.group(1), "INVALID"), depth + 1),
                      value)

    def declared(self, el, prop, state=(), mobile=False):
        """Winning declared value of `prop` for el (no inheritance), or None. Longhands are derived from
        the `border` and `background` shorthands. Rules inside a media query apply only when `mobile`."""
        key0 = (id(el), prop, tuple(sorted(state)), mobile)
        if key0 in self._memo:
            return self._memo[key0]
        best = None
        for r in self.rules:
            if r.media and not (mobile and "max-width" in r.media):
                continue
            if not selector_matches(r.selector, el, set(state)):
                continue
            val = r.decls.get(prop)
            if val is None and prop == "border-color" and "border" in r.decls:
                val = _last_color(r.decls["border"], self)
            if val is None and prop == "background-color":
                for k in ("background", "background-color"):
                    if k in r.decls:
                        val = _first_color(r.decls[k], self)
            if val is None:
                continue
            key = (specificity(r.selector), r.order)
            if best is None or key >= best[0]:
                best = (key, val)
        self._memo[key0] = self.resolve(best[1]) if best else None
        return self._memo[key0]

    def color(self, el, state=(), mobile=False):
        for e in el.chain():
            v = self.declared(e, "color", state if e is el else (), mobile)
            if v and v.lower() not in ("inherit",):
                return parse_color(v)
        return parse_color("#ffffff")  # UA default text on a dark scheme; asserted separately

    def background(self, el, state=(), mobile=False):
        layers, base = [], None
        for e in el.chain():
            v = self.declared(e, "background-color", state if e is el else (), mobile)
            if v:
                c = parse_color(v)
                if c[3] >= 1:
                    base = c
                    break
                layers.append(c)
        out = base or (255.0, 255.0, 255.0, 1.0)  # a page that sets no ground gets the UA's white canvas
        for c in reversed(layers):
            out = composite(c, out)
        return out


def _colors_in(value, sheet):
    value = sheet.resolve(value)
    return re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\btransparent\b", value)


def _last_color(value, sheet):
    c = _colors_in(value, sheet)
    return c[-1] if c else None


def _first_color(value, sheet):
    c = _colors_in(value, sheet)
    return c[0] if c else None


def parse_color(v):
    v = v.strip().lower()
    if v == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    m = re.fullmatch(r"#([0-9a-f]{3})", v)
    if m:
        h = m.group(1)
        return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16), 1.0)
    m = re.fullmatch(r"#([0-9a-f]{6})", v)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    m = re.fullmatch(r"rgba?\(([^)]*)\)", v)
    if m:
        p = [x.strip() for x in re.split(r"[,/\s]+", m.group(1).strip()) if x.strip()]
        a = float(p[3]) if len(p) > 3 else 1.0
        return (float(p[0]), float(p[1]), float(p[2]), a)
    raise AssertionError(f"colour not understood: {v!r}")


def composite(fg, bg):
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3)) + (1.0,)


def luminance(c):
    def ch(x):
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def px(v):
    m = re.fullmatch(r"(-?[\d.]+)px", (v or "").strip())
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------- the page states
MEMBER = kindle.render
ADDR_OK = "member_a_old@kindle.com"
SENDER = "sender@example.test"


def states():
    """Every page state the connector can render, from its own render functions (synthetic data)."""
    saved = kindle.SENDER
    kindle.SENDER = SENDER
    try:
        both = dict(audiobooks=True)
        return {
            "form, empty": MEMBER(None, None),
            "form, existing values": MEMBER(ADDR_OK, ADDR_OK, ADDR_OK, None, True),
            "form, existing values, books only": MEMBER(ADDR_OK, None, ADDR_OK, None, True),
            "form, existing values, books and audiobooks": MEMBER(ADDR_OK, ADDR_OK, ADDR_OK, None, True, **both),
            "success": MEMBER(ADDR_OK, ADDR_OK, ADDR_OK,
                              ("ok", "Saved to Calibre-Web and Audiobookshelf. Remember to approve " + SENDER +
                               " on Amazon."), True),
            "removed": MEMBER(None, None, "", ("ok", "Removed from Calibre-Web and Audiobookshelf."), False),
            "error, rejected value": MEMBER(ADDR_OK, ADDR_OK, "someone@gmail.com",
                                            ("err", "That is not a @kindle.com address."), True, invalid=True),
            "partial failure": MEMBER(ADDR_OK, None, ADDR_OK,
                                      ("err", "Saved to Calibre-Web; failed for Audiobookshelf."), True),
            "no account": MEMBER(None, None, "",
                                 ("err", "No Calibre-Web or Audiobookshelf account found for this login."), False),
            "404": kindle.render_not_found(),
        }
    finally:
        kindle.SENDER = saved


def doc(name):
    return Doc(states()[name])


class Pages(unittest.TestCase):
    """Structure, labels, roles, copy, per page state."""

    @classmethod
    def setUpClass(cls):
        cls.pages = {n: Doc(h) for n, h in states().items()}

    def each(self):
        return list(self.pages.items())

    def test_document_basics(self):
        for n, d in self.each():
            with self.subTest(n):
                self.assertTrue(d.doctype, "doctype")
                self.assertEqual(d.find("html")[0].attrs.get("lang"), "en")
                vp = [m for m in d.find("meta") if m.attrs.get("name") == "viewport"]
                self.assertTrue(vp and "width=device-width" in vp[0].attrs["content"])
                self.assertNotIn("user-scalable=no", vp[0].attrs["content"])
                self.assertNotIn("maximum-scale", vp[0].attrs["content"])
                self.assertTrue(d.find("title")[0].own_text)
                self.assertEqual(len(d.find("main")), 1)

    def test_color_scheme_dark_in_css_and_meta(self):
        for n, d in self.each():
            with self.subTest(n):
                self.assertEqual(Sheet(d.css).declared(d.find("html")[0], "color-scheme"), "dark")
                metas = [m for m in d.find("meta") if m.attrs.get("name") == "color-scheme"]
                self.assertTrue(metas and metas[0].attrs["content"] == "dark")

    def test_exactly_one_h1_and_no_skipped_heading_levels(self):
        for n, d in self.each():
            with self.subTest(n):
                levels = [int(e.tag[1]) for e in d.all if re.fullmatch(r"h[1-6]", e.tag)]
                self.assertEqual(levels.count(1), 1, levels)
                self.assertEqual(levels[0], 1)
                for prev, cur in zip(levels, levels[1:]):
                    self.assertLessEqual(cur, prev + 1, f"heading level jumps from {prev} to {cur}: {levels}")
                for h in (e for e in d.all if re.fullmatch(r"h[1-6]", e.tag)):
                    self.assertTrue(h.all_text, "empty heading")

    def test_every_form_control_has_a_programmatic_label(self):
        for n, d in self.each():
            with self.subTest(n):
                labels = {l.attrs.get("for"): l for l in d.find("label")}
                for inp in d.find("input"):
                    if inp.attrs.get("type") in ("hidden", "submit", "button"):
                        continue
                    iid = inp.attrs.get("id")
                    self.assertTrue(iid, "a visible control needs an id for its label")
                    self.assertIn(iid, labels, f"no <label for={iid}>")
                    self.assertTrue(labels[iid].all_text.strip(), "label has no text")
                    self.assertEqual(len([i for i in d.all if i.attrs.get("id") == iid]), 1, "duplicate id")
                for b in d.find("button"):
                    self.assertTrue(b.all_text or b.attrs.get("aria-label"), "button without a name")
                for a in d.find("a"):
                    self.assertTrue(a.all_text or a.attrs.get("aria-label"), "link without a name")

    def test_address_field_is_an_email_field_with_input_hints(self):
        for n, d in self.each():
            with self.subTest(n):
                for inp in d.find("input"):
                    self.assertEqual(inp.attrs.get("type"), "email")
                    self.assertEqual(inp.attrs.get("inputmode"), "email")
                    self.assertEqual(inp.attrs.get("autocomplete"), "off",
                                     "this is the Kindle address, not the member's own e-mail: do not offer to fill it")
                    self.assertEqual(inp.attrs.get("autocapitalize"), "none")
                    self.assertEqual(inp.attrs.get("spellcheck"), "false")
                    self.assertIn("required", inp.attrs)

    def test_describedby_ids_all_resolve_and_hint_is_wired(self):
        for n, d in self.each():
            with self.subTest(n):
                ids = {e.attrs["id"]: e for e in d.all if "id" in e.attrs}
                for e in d.all:
                    for attr in ("aria-describedby", "aria-labelledby"):
                        for ref in (e.attrs.get(attr) or "").split():
                            self.assertIn(ref, ids, f"{attr}={ref} points at nothing")
                for inp in d.find("input"):
                    ref = (inp.attrs.get("aria-describedby") or "").split()
                    self.assertIn("address-hint", ref)
                    self.assertIn("@kindle.com", ids["address-hint"].all_text)

    def test_banners_are_announced_with_the_right_role(self):
        for n, d in self.each():
            with self.subTest(n):
                for b in (e for e in d.all if "banner" in e.classes):
                    expected = "alert" if "err" in b.classes else "status"
                    self.assertEqual(b.attrs.get("role"), expected, f"banner {sorted(b.classes)}")
                    self.assertTrue(b.all_text)
                    self.assertTrue(b.attrs.get("id"))
        d = self.pages["success"]
        self.assertEqual([b.attrs["role"] for b in d.all if "banner" in b.classes], ["status"])
        d = self.pages["partial failure"]
        self.assertEqual([b.attrs["role"] for b in d.all if "banner" in b.classes], ["alert"])

    def test_rejected_value_is_marked_invalid_and_tied_to_its_message(self):
        d = self.pages["error, rejected value"]
        inp = d.find("input")[0]
        banner = [b for b in d.all if "banner" in b.classes][0]
        self.assertEqual(inp.attrs.get("aria-invalid"), "true")
        self.assertIn(banner.attrs["id"], inp.attrs["aria-describedby"].split())
        self.assertEqual(inp.attrs.get("value"), "someone@gmail.com", "the rejected value stays so it can be fixed")
        for n, other in self.pages.items():
            if n != "error, rejected value":
                for i in other.find("input"):
                    self.assertNotIn("aria-invalid", i.attrs, f"{n}: nothing was rejected")

    def test_no_em_or_en_dashes_and_no_first_person_in_member_visible_text(self):
        first = re.compile(r"\b(?:we|we're|we'll|we've|our|ours|us|my|mine|me|let's)\b", re.I)
        for n, d in self.each():
            with self.subTest(n):
                text = d.visible_text
                self.assertNotRegex(text, "[‒–—―−]", "dash character in visible copy")
                self.assertIsNone(first.search(text), first.search(text))
                self.assertIsNone(re.search(r"\bI(?:'m|'ll|'ve)?\b", text), "first person singular")
        self.assertNotRegex(" ".join(states().values()), "&[mn]dash;|&#8212;|&#8211;|&#x2014;|&#x2013;")

    def test_links_that_leave_the_site_are_safe_and_nothing_scripts(self):
        for n, d in self.each():
            with self.subTest(n):
                self.assertEqual(d.find("script"), [])
                for a in d.find("a"):
                    if a.attrs.get("target") == "_blank":
                        self.assertIn("noopener", a.attrs.get("rel", ""))

    def test_state_changing_forms_stay_post(self):
        d = self.pages["form, existing values"]
        forms = d.find("form")
        self.assertEqual([(f.attrs["method"], f.attrs["action"]) for f in forms], [("post", "/save")])
        formactions = [b.attrs.get("formaction") for b in d.find("button")]
        self.assertEqual(sorted(x for x in formactions if x), ["/remove"])

    def test_404_is_still_non_revealing(self):
        text = states()["404"]
        self.assertIn("<title>Not found · Avrana</title>", text)
        for hint in T.NOT_FOUND_FORBIDDEN:
            self.assertNotIn(hint, text)
        d = self.pages["404"]
        self.assertEqual(d.find("form"), [])
        self.assertEqual(d.find("input"), [])


class Style(unittest.TestCase):
    """Computed from the stylesheet inside the rendered page, so a later rule that cancels an earlier one
    shows up here like it would on screen."""

    @classmethod
    def setUpClass(cls):
        cls.pages = {n: Doc(h) for n, h in states().items()}
        cls.sheet = {n: Sheet(d.css) for n, d in cls.pages.items()}

    def each_interactive(self):
        return [(n, d, self.sheet[n], e) for n, d in self.pages.items() for e in d.all
                if e.tag in INTERACTIVE and e.attrs.get("type") not in ("hidden",)]

    def test_tokens_match_the_design_system(self):
        for n, s in self.sheet.items():
            for k, v in TOKENS.items():
                self.assertEqual(s.vars.get(k, "").lower(), v, f"{n}: {k}")

    def test_control_edges_meet_3_to_1_against_the_page(self):
        for n, d, s, e in self.each_interactive():
            with self.subTest(page=n, el=f"{e.tag}.{'.'.join(sorted(e.classes))}"):
                if e.tag == "a":
                    continue
                page = s.background(d.find("body")[0])
                edge = s.declared(e, "border-color")
                self.assertIsNotNone(edge, "interactive control without a declared edge")
                c = composite(parse_color(edge), page)
                self.assertGreaterEqual(contrast(c, page), 3.0, f"edge {edge}")

    def test_dividers_keep_the_quiet_rule_colour(self):
        s = Sheet(self.pages["form, empty"].css)
        self.assertEqual(s.vars["--rule-quiet"], "#474747")
        self.assertEqual(s.vars["--rule-control"], "#6e6e6e")

    def test_text_meets_4_5_to_1_in_rest_hover_and_focus(self):
        for n, d in self.pages.items():
            s = self.sheet[n]
            for e in d.visible_elements:
                if not e.own_text:
                    continue
                states_to_check = [()]
                if e.tag in INTERACTIVE:
                    states_to_check += [("hover",), ("focus-visible", "focus")]
                for st in states_to_check:
                    with self.subTest(page=n, el=e.tag, state=st, text=e.own_text[:30]):
                        bg = s.background(e, st)
                        fg = composite(s.color(e, st), bg)
                        self.assertGreaterEqual(contrast(fg, bg), 4.5)

    def test_status_banners_are_readable_and_their_edge_is_visible(self):
        for n, d in self.pages.items():
            s = self.sheet[n]
            for b in (e for e in d.all if "banner" in e.classes):
                bg = s.background(b)
                self.assertGreaterEqual(contrast(composite(s.color(b), bg), bg), 4.5)
                self.assertGreaterEqual(contrast(composite(parse_color(s.declared(b, "border-color")), bg), bg), 3.0)

    def test_every_interactive_element_shows_the_same_focus_ring(self):
        def norm(v):
            return re.sub(r"\s*,\s*", ",", (v or "").lower()).replace("#000000", "#000").replace("#ffffff", "#fff")

        for n, d, s, e in self.each_interactive():
            with self.subTest(page=n, el=f"{e.tag}.{'.'.join(sorted(e.classes))}"):
                shadow = s.declared(e, "box-shadow", ("focus-visible", "focus"))
                self.assertEqual(norm(shadow), "0 0 0 2px #000,0 0 0 4px #fff",
                                 "focused element has no (or a different) focus ring")
                outline = s.declared(e, "outline", ("focus-visible", "focus")) or ""
                self.assertNotIn("none", outline, "outline must stay (transparent) so forced-colours mode draws one")
                self.assertIn("transparent", outline)
                self.assertNotEqual(shadow, s.declared(e, "box-shadow", ()), "ring should not show at rest")

    def test_no_outline_none_without_the_ring_for_that_selector(self):
        for n, s in self.sheet.items():
            for r in s.rules:
                outline = (r.decls.get("outline") or "").lower()
                if outline in ("none", "0") or outline.startswith("0 ") or r.decls.get("outline-style") == "none":
                    self.fail(f"{n}: `{r.selector}` removes the outline; use the transparent outline plus ring")

    def test_focus_changes_the_input_edge_too(self):
        for n, d in self.pages.items():
            for e in d.find("input"):
                s = self.sheet[n]
                self.assertEqual(parse_color(s.declared(e, "border-color", ("focus", "focus-visible"))),
                                 parse_color("#ffffff"))

    def test_target_size_declared_44px_for_buttons_fields_and_links(self):
        for n, d, s, e in self.each_interactive():
            with self.subTest(page=n, el=f"{e.tag}.{'.'.join(sorted(e.classes))}"):
                if e.tag == "a" and e.parent.tag == "h1":
                    continue  # the wordmark: a 32 to 48px line of display type, above the 24px minimum
                m = px(s.declared(e, "min-height"))
                self.assertIsNotNone(m, "no min-height")
                self.assertGreaterEqual(m, 44.0)
                if e.tag in ("a",):
                    self.assertIn(s.declared(e, "display"), ("inline-flex", "inline-block", "flex", "block"),
                                  "min-height is ignored on a plain inline link")

    def test_phone_layout_cannot_overflow_and_text_can_grow(self):
        for n, s in self.sheet.items():
            self.assertEqual(s.vars.get("--ink"), "#000000")
            for r in s.rules:
                if r.selector == ".rule":
                    continue  # the 64px by 1px decorative rule under the wordmark
                for prop in ("width", "min-width"):
                    v = px(r.decls.get(prop))
                    self.assertFalse(v is not None and v > 320, f"{n}: `{r.selector}` {prop}:{v}px can overflow 390px")
                for prop in ("height", "max-height"):
                    self.assertIsNone(px(r.decls.get(prop)), f"{n}: `{r.selector}` fixes {prop}; text could clip at 200%")
                self.assertNotIn("hidden", r.decls.get("overflow", ""), f"{n}: `{r.selector}` clips overflow")
            self.assertTrue(any(r.selector == "*" and r.decls.get("box-sizing") == "border-box" for r in s.rules))
            main = self.pages[n].find("main")[0]
            self.assertEqual(s.declared(main, "max-width"), "640px")
            self.assertTrue(any(r.media and "max-width:560px" in r.media.replace(" ", "") for r in s.rules))
        d = self.pages["form, existing values"]
        s = self.sheet["form, existing values"]
        dl = d.find("dl")[0]
        self.assertEqual(s.declared(dl, "grid-template-columns", mobile=True), "1fr")
        dd = d.find("dd")[0]
        self.assertEqual(s.declared(dd, "overflow-wrap"), "anywhere")
        self.assertIsNotNone(s.declared(dd, "margin-bottom", mobile=True), "address pairs touch on a phone")
        self.assertEqual(s.declared(d.find("input")[0], "width"), "100%")

    def test_transitions_stand_down_for_reduced_motion(self):
        css = self.pages["form, empty"].css.replace(" ", "")
        self.assertIn("@media(prefers-reduced-motion:reduce)", css)


# ---------------------------------------------------------------- over HTTP: wiring and the new copy rule
BOOKS = T.GROUPS_OK                                   # avrana-users|avrana-books
BOTH = "avrana-users|avrana-books|avrana-audiobooks"


class OverHttp(T.Base):
    def test_real_responses_carry_the_roles_and_wiring(self):
        before = self.state()
        d = Doc(self.get().text)
        self.assertEqual(d.find("input")[0].attrs.get("aria-invalid"), None)
        self.assertNotIn("alert", [e.attrs.get("role") for e in d.all])

        d = Doc(self.post("/save", "someone@gmail.com").text)
        inp, banner = d.find("input")[0], [b for b in d.all if "banner" in b.classes][0]
        self.assertEqual((inp.attrs.get("aria-invalid"), banner.attrs.get("role")), ("true", "alert"))
        self.assertIn(banner.attrs["id"], inp.attrs["aria-describedby"].split())
        self.assertEqual(inp.attrs["value"], "someone@gmail.com")
        self.assertEqual(self.state(), before, "a rejected value writes nothing")

        d = Doc(self.get(headers=T.hdr(user="member-z", email="z@example.test")).text)
        self.assertEqual([b.attrs["role"] for b in d.all if "banner" in b.classes], ["alert"])
        self.assertNotIn("aria-invalid", d.find("input")[0].attrs)

        d = Doc(self.post("/save", T.NEW_A).text)
        self.assertEqual([b.attrs["role"] for b in d.all if "banner" in b.classes], ["status"])

    def test_remove_and_partial_failure_banners_over_http(self):
        self.abs.fail_patch = True
        d = Doc(self.post("/save", T.NEW_A).text)
        self.assertIn("failed for Audiobookshelf", d.find("main")[0].all_text)
        self.assertEqual([b.attrs["role"] for b in d.all if "banner" in b.classes], ["alert"])
        self.assertNotIn("aria-invalid", d.find("input")[0].attrs)
        self.abs.fail_patch = False
        d = Doc(self.post("/remove", body=b"").text)
        self.assertEqual([b.attrs["role"] for b in d.all if "banner" in b.classes], ["status"])

    def test_503_stays_a_plain_text_reply(self):
        self.abs._dead = True
        r = self.get()
        self.assertEqual((r.status, r.headers["content-type"]), (503, "text/plain; charset=utf-8"))
        self.assertEqual(r.text, "temporarily unavailable")
        for ch in "–—":
            self.assertNotIn(ch, r.text)

    def test_404_over_http_is_the_same_document_for_every_denial(self):
        pages = {self.get(headers=h).text for h in ([], T.hdr(groups="avrana-users"), T.hdr(user=None))}
        self.assertEqual(len(pages), 1)
        d = Doc(pages.pop())
        self.assertEqual([e.tag for e in d.all if re.fullmatch(r"h[1-6]", e.tag)], ["h1"])

    # -- copy rule: do not name a service the member may not be allowed to reach (same idea as AVR-430)
    def test_books_only_member_is_not_pointed_at_audiobookshelf_in_the_footer(self):
        d = Doc(self.get(headers=T.hdr(groups=BOOKS)).text)
        footer = d.find("footer")[0]
        hrefs = [a.attrs["href"] for a in footer.children if a.tag == "a"]
        self.assertEqual(hrefs, ["https://books.avrana.net", "https://avrana.net"])
        self.assertNotIn("listen.avrana.net", self.get(headers=T.hdr(groups=BOOKS)).text)
        self.assertNotIn("Audiobookshelf", footer.all_text)

    def test_member_with_both_groups_still_gets_the_audiobookshelf_link(self):
        d = Doc(self.get(headers=T.hdr(groups=BOTH)).text)
        footer = d.find("footer")[0]
        self.assertEqual([a.attrs["href"] for a in footer.children if a.tag == "a"],
                         ["https://books.avrana.net", "https://listen.avrana.net", "https://avrana.net"])
        self.assertIn("Audiobookshelf", footer.all_text)

    def test_group_that_only_contains_the_name_does_not_earn_the_link(self):
        for g in ("avrana-audiobooks-extra", "xavrana-audiobooks", "audiobooks"):
            with self.subTest(g):
                self.assertNotIn("listen.avrana.net", self.get(headers=T.hdr(groups=BOOKS + "|" + g)).text)

    def test_group_gate_itself_is_unchanged(self):
        before = self.state()
        for g in ("avrana-audiobooks", "avrana-users|avrana-audiobooks"):
            self.assertEqual(self.get(headers=T.hdr(groups=g)).status, 404)
            self.assertEqual(self.post("/save", T.NEW_A, headers=T.hdr(groups=g)).status, 404)
        self.assertEqual(self.state(), before)


class _WritesMixin:
    """The same literal expectations run for a books-only member and a books+audiobooks member: the
    group changes the footer link only, never which libraries are written or what is written."""
    groups = None

    def test_save_then_remove_write_exactly_the_same_things(self):
        h = T.hdr(groups=self.groups)
        rows0, devices0 = self.rows(), self.abs.devices
        r = self.post("/save", T.NEW_A, headers=h)
        self.assertEqual(r.status, 200)
        self.assertIn("Saved to Calibre-Web and Audiobookshelf. Remember to approve " + T.SENDER, r.text)
        self.assertEqual(self.rows()[0], (1, "member-a", "a@example.test", T.NEW_A))
        self.assertEqual(self.rows()[1:], rows0[1:])
        self.assertEqual(len(self.abs.patches), 1)
        mine = [d for d in self.abs.devices if d["name"] == "Kindle (member-a)"]
        self.assertEqual(mine, [T.abs_device("Kindle (member-a)", T.NEW_A, ["abs-u-a"])])
        self.assertEqual([d for d in self.abs.devices if d["name"] != "Kindle (member-a)"],
                         [d for d in devices0 if d["name"] != "Kindle (member-a)"])
        r = self.post("/remove", headers=h, body=b"")
        self.assertIn("Removed from Calibre-Web and Audiobookshelf.", r.text)
        self.assertEqual(self.rows()[0][3], None)
        self.assertEqual([d["name"] for d in self.abs.devices if d["users"] == ["abs-u-a"]], [])
        self.assertEqual(len(self.abs.patches), 2)

    def test_member_with_no_audiobookshelf_account_is_still_written_to_calibre_web_alone(self):
        self.abs.users = [u for u in self.abs.users if u["username"] != "member-a"]
        r = self.post("/save", T.NEW_A, headers=T.hdr(groups=self.groups))
        self.assertIn("Saved to Calibre-Web.", r.text)
        self.assertEqual(self.rows()[0][3], T.NEW_A)
        self.assertEqual(self.abs.patches, [])


class WritesBooksOnly(_WritesMixin, T.Base):
    groups = BOOKS


class WritesBooksAndAudiobooks(_WritesMixin, T.Base):
    groups = BOTH


if __name__ == "__main__":
    unittest.main()
