"""Shared accessibility checks for the Audible connector pages (Media 2.0 Sprint 1, item S1-4 / AVR-359).

Pure helpers, standard library only (html.parser): no network, no fixtures, nothing imported from any other
service. The page's stylesheet is read back and a small cascade (specificity, order, inheritance,
pseudo-class state) decides which colour, edge, ring and size an element really ends up with, so a later
rule that cancels an earlier fix is caught the way a browser would show it.

What this can not do: it is not a browser. Layout, real font metrics, 200% text zoom and screen reader
speech need a real browser and are listed as gaps in the pull request.
"""
import html.parser
import re

# ---------------------------------------------------------------- design tokens (docs/design/DESIGN.md)
TOKENS = {"--ink": "#000000", "--paper": "#ffffff", "--ash": "#9a9a9a", "--rule-quiet": "#474747",
          "--rule-control": "#6e6e6e", "--rule-strong": "#999999", "--ok": "#8fe3a6", "--warn": "#e8cf8a",
          "--err": "#ff8b8b"}
RING = "0 0 0 2px #000,0 0 0 4px #fff"

# ---------------------------------------------------------------- html model, css cascade, colour maths
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

    def all_descendants(self):
        out = []
        for c in self.children:
            out.append(c)
            out.extend(c.all_descendants())
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




# ---------------------------------------------------------------- checks
def interactive(doc):
    out = []
    for e in doc.all:
        if e.tag == "a" and "href" in e.attrs:
            out.append(e)
        elif e.tag in ("button", "select", "textarea", "summary"):
            out.append(e)
        elif e.tag == "input" and e.attrs.get("type") not in ("hidden", "submit", "button"):
            out.append(e)
        elif e.tag == "input":
            out.append(e)
    return [e for e in out if not (e.tag == "input" and e.attrs.get("type") == "hidden")]


def is_toggle(e):
    return e.tag == "input" and e.attrs.get("type") in ("checkbox", "radio")


def name_of(e):
    return f"{e.tag}.{'.'.join(sorted(e.classes))}" if e.classes else e.tag


def check_document(d):
    """lang, viewport, title, doctype, color-scheme meta, one main, one h1, heading order."""
    assert d.doctype, "doctype"
    assert d.find("html")[0].attrs.get("lang") == "en"
    vp = [m for m in d.find("meta") if m.attrs.get("name") == "viewport"]
    assert vp and "width=device-width" in vp[0].attrs["content"]
    assert "user-scalable=no" not in vp[0].attrs["content"] and "maximum-scale" not in vp[0].attrs["content"]
    assert d.find("title")[0].own_text, "empty title"
    cs = [m for m in d.find("meta") if m.attrs.get("name") == "color-scheme"]
    assert cs and cs[0].attrs["content"] == "dark", "color-scheme meta"
    assert len(d.find("main")) == 1
    levels = [int(e.tag[1]) for e in d.all if re.fullmatch(r"h[1-6]", e.tag)]
    assert levels.count(1) == 1 and levels[0] == 1, levels
    for prev, cur in zip(levels, levels[1:]):
        assert cur <= prev + 1, f"heading level jumps from {prev} to {cur}: {levels}"
    for h in (e for e in d.all if re.fullmatch(r"h[1-6]", e.tag)):
        assert h.all_text, "empty heading"


def check_no_auto_navigation(d, response=None):
    """Nothing reloads, redirects or re-requests by itself: no meta refresh, no Refresh header, no scripts
    that could set a timer, no `Link: rel=prefetch/prerender`."""
    for m in d.find("meta"):
        assert (m.attrs.get("http-equiv") or "").lower() != "refresh", "meta refresh"
    assert d.find("script") == [], "page scripts"
    for e in d.all:
        for a, v in e.attrs.items():
            if a.startswith("on"):
                # the only script allowed is the native confirm() on the disconnect forms
                assert e.tag == "form" and a == "onsubmit" and re.fullmatch(r"return confirm\('[^']*'\);?", v),                     f"inline handler {a}={v!r} on {e.tag}"
    if response is not None:
        names = {k.lower() for k in response.headers.keys()}
        assert "refresh" not in names, "Refresh response header"
        assert "link" not in names or "prerender" not in response.headers.get("link", "").lower()


def check_labels(d):
    labels = {}
    for l in d.find("label"):
        if l.attrs.get("for"):
            labels[l.attrs["for"]] = l
    ids = [e.attrs["id"] for e in d.all if "id" in e.attrs]
    assert len(ids) == len(set(ids)), "duplicate id"
    byid = {e.attrs["id"]: e for e in d.all if "id" in e.attrs}
    for e in d.all:
        if e.tag in ("input", "select", "textarea") and e.attrs.get("type") not in ("hidden", "submit", "button"):
            wrapped = [a for a in e.chain()[1:] if a.tag == "label" and a.all_text.strip()]
            by_for = labels.get(e.attrs.get("id", None))
            named = bool(wrapped) or (by_for is not None and by_for.all_text.strip()) \
                or e.attrs.get("aria-label") or e.attrs.get("aria-labelledby")
            assert named, f"{name_of(e)} has no programmatic label"
        if e.tag == "fieldset":
            ok = any(c.tag == "legend" and c.all_text for c in e.children) or \
                (e.attrs.get("aria-labelledby") in byid and byid[e.attrs["aria-labelledby"]].all_text)
            assert ok, "fieldset without a name"
        if e.tag == "button":
            assert e.all_text or e.attrs.get("aria-label"), "button without a name"
        if e.tag == "a" and "href" in e.attrs:
            assert e.all_text or e.attrs.get("aria-label"), "link without a name"
    for e in d.all:
        for attr in ("aria-describedby", "aria-labelledby"):
            for ref in (e.attrs.get(attr) or "").split():
                assert ref in byid, f"{attr}={ref} points at nothing"
    for e in d.find("img"):
        assert "alt" in e.attrs, "img without alt"


def check_alerts(d):
    for b in (e for e in d.all if "alert" in e.classes):
        expected = "alert" if "error" in b.classes else "status"
        assert b.attrs.get("role") == expected, f"alert {sorted(b.classes)} has role {b.attrs.get('role')!r}"
        assert b.all_text


FIRST_PERSON = re.compile(r"\b(?:we|we're|we'll|we've|our|ours|us|my|mine|me|let's)\b", re.I)


def check_copy(d):
    text = d.visible_text
    assert not re.search("[‒–—―−]", text), "dash character in visible copy"
    assert not FIRST_PERSON.search(text), FIRST_PERSON.search(text)
    assert not re.search(r"\bI(?:'m|'ll|'ve)?\b", text), "first person singular"


def check_csrf_forms(d, token_ok):
    """Every form posts (nothing state-changing is a GET) and carries a verifying CSRF token."""
    for f in d.find("form"):
        assert (f.attrs.get("method") or "").lower() == "post", f"form {f.attrs.get('action')} is not POST"
        tokens = [i for i in f.all_descendants() if i.tag == "input" and i.attrs.get("name") == "csrf_token"]
        assert len(tokens) == 1, f"form {f.attrs.get('action')} needs exactly one csrf_token field"
        assert token_ok(tokens[0].attrs.get("value", "")), "csrf token does not verify"
        assert tokens[0].attrs.get("type") == "hidden"


def check_style(d, s):
    """Contrast, edges, focus ring, targets, tokens, overflow guards. `s` is the page's Sheet."""
    for k, v in TOKENS.items():
        assert s.vars.get(k, "").lower() == v, f"token {k}"
    html_el = d.find("html")[0]
    assert s.declared(html_el, "color-scheme") == "dark"
    page = s.background(d.find("body")[0])
    # control edges
    for e in interactive(d):
        if is_toggle(e) or e.tag in ("a", "summary") and "as-button" not in e.classes:
            continue
        edge = s.declared(e, "border-color")
        assert edge is not None, f"{name_of(e)}: interactive control without a declared edge"
        c = composite(parse_color(edge), page)
        assert contrast(c, page) >= 3.0, f"{name_of(e)}: edge {edge} is under 3:1"
    # text, in rest / hover / focus
    for e in d.visible_elements:
        if not e.own_text:
            continue
        sts = [()]
        if e.tag in ("a", "button", "summary", "input", "select", "textarea") or "as-button" in e.classes:
            sts += [("hover",), ("focus-visible", "focus")]
        for st in sts:
            bg = s.background(e, st)
            fg = composite(s.color(e, st), bg)
            assert contrast(fg, bg) >= 4.5, f"{name_of(e)} {st} text {contrast(fg, bg):.2f}:1 ({e.own_text[:30]!r})"
    # one focus ring everywhere, kept at rest off
    def norm(v):
        return re.sub(r"\s*,\s*", ",", (v or "").lower()).replace("#000000", "#000").replace("#ffffff", "#fff")

    for e in interactive(d):
        shadow = s.declared(e, "box-shadow", ("focus-visible", "focus"))
        assert norm(shadow) == RING, f"{name_of(e)} has no (or a different) focus ring: {shadow!r}"
        outline = s.declared(e, "outline", ("focus-visible", "focus")) or ""
        assert "transparent" in outline and "none" not in outline, f"{name_of(e)} outline {outline!r}"
        assert s.declared(e, "box-shadow", ()) != shadow, f"{name_of(e)} ring shows at rest"
    for r in s.rules:
        o = (r.decls.get("outline") or "").lower()
        assert not (o in ("none", "0") or o.startswith("0 ") or r.decls.get("outline-style") == "none"), \
            f"`{r.selector}` removes the outline"
    # targets
    for e in interactive(d):
        if is_toggle(e):
            lab = [a for a in e.chain()[1:] if a.tag == "label"]
            assert lab, f"{name_of(e)} is a bare toggle; wrap it in a <label> for a 44px target"
            assert px(s.declared(lab[0], "min-height")) and px(s.declared(lab[0], "min-height")) >= 44, name_of(lab[0])
            if e.attrs.get("type") == "checkbox":
                assert px(s.declared(lab[0], "min-width")) and px(s.declared(lab[0], "min-width")) >= 44, name_of(lab[0])
            continue
        m = px(s.declared(e, "min-height"))
        assert m is not None and m >= 44, f"{name_of(e)} has no 44px min-height"
        if e.tag in ("a", "summary"):
            assert s.declared(e, "display") in ("inline-flex", "inline-block", "flex", "block", "grid"), \
                f"{name_of(e)}: min-height is ignored on an inline box"
    # overflow guards and room for larger text
    allowed_fixed = {".cover", ".pick input", ".choice input", ".rule"}
    for r in s.rules:
        for prop in ("width", "min-width"):
            v = px(r.decls.get(prop))
            assert not (v is not None and v > 320), f"`{r.selector}` {prop}:{v}px can overflow 390px"
        if r.selector not in allowed_fixed and not r.media:
            for prop in ("height", "max-height"):
                assert px(r.decls.get(prop)) is None, f"`{r.selector}` fixes {prop}; text could clip at 200%"
        assert "hidden" not in r.decls.get("overflow", ""), f"`{r.selector}` clips overflow"
    assert any(r.selector == "*" and r.decls.get("box-sizing") == "border-box" for r in s.rules)
    assert any(r.media and "max-width:560px" in r.media.replace(" ", "") for r in s.rules)


def check_reduced_motion(css):
    assert "@media (prefers-reduced-motion:reduce)" in re.sub(r"\s+", " ", css).replace("( ", "(")
