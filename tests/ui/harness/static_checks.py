"""Layer 1: stdlib static checks over every registry page.

Nothing here needs a browser. Each check reads the rendered HTML and the page's own stylesheet and
returns Findings with stable ids `service/page/identity/rule/detail`. An id names WHAT is wrong and
WHERE, never a magnitude (a contrast ratio, a pixel size), so partially fixing a defect does not
mint a new id. Magnitudes live in `message`.

What is deliberately approximate: the CSS reader (css.py) evaluates the cascade for the properties
that matter here and treats anything it cannot read as unknown. The browser layer (check.mjs) is the
authority for rendered size, colour and focus; this layer exists so that every `run_offline.py` run,
with no browser installed, still refuses a new defect.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import css as C
from . import dom as D
from .pages import Page, Registry

RULES = {
    "h1-count": "exactly one h1",
    "heading-skip": "headings must not skip a level",
    "heading-empty": "headings need text",
    "heading-topic-missing": "a help topic page names its topic in an h2",
    "landmark-main": "exactly one main landmark",
    "landmark-nav-label": "several nav landmarks need distinct names",
    "link-name": "links need an accessible name",
    "button-name": "buttons need an accessible name",
    "input-name": "form controls need an accessible name",
    "label-for-target": "label for= must point at a control",
    "img-alt": "images need alt",
    "duplicate-id": "ids are unique",
    "target-blank-rel": "target=_blank needs rel noopener",
    "target-blank-hint": "target=_blank links say they open a new tab",
    "html-lang": "html has a lang",
    "viewport": "viewport meta with width=device-width",
    "viewport-zoom": "zoom must not be disabled",
    "title-missing": "page has a title",
    "color-scheme": "pages declare color-scheme (dark)",
    "meta-refresh": "no automatic page refresh",
    "inline-handler": "no inline event handlers",
    "script-present": "no script on a page that needs none",
    "focus-outline-none": "outline:none only with a replacement ring",
    "focus-ring-missing": "focus shows a ring (outline or box-shadow)",
    "contrast-text": "text contrast at least 4.5:1 (3:1 large)",
    "contrast-control-edge": "interactive edges at least 3:1",
    "target-size": "interactive targets at least 44px where determinable",
    "status-role": "banners and alerts carry role status or alert",
    "dash-in-copy": "no em or en dashes in member-visible copy",
    "first-person": "no first-person words in member-visible copy",
    "leak": "page names nothing the viewer may not use",
    "status": "response status matches the expected visibility",
}

EM, EN = chr(0x2014), chr(0x2013)
MIN_TARGET = 44.0
TEXT_MIN, LARGE_MIN, EDGE_MIN = 4.5, 3.0, 3.0
FIRST_PERSON_CI = re.compile(r"(?<![\w'])(we|we're|we've|we'll|our|ours|us|my|me)(?![\w])", re.I)
FIRST_PERSON_CS = re.compile(r"(?<![\w'])(I|I'm|I've|I'll|I'd)(?![\w])")


@dataclass(frozen=True)
class Finding:
    service: str
    page: str
    identity: str
    rule: str
    detail: str
    message: str = ""

    @property
    def id(self):
        d = re.sub(r"\s+", " ", self.detail).strip()[:100]
        return f"{self.service}/{self.page}/{self.identity}/{self.rule}/{d}"


# ---------------------------------------------------------------------------------------------
class PageContext:
    def __init__(self, page: Page, rendered):
        self.page = page
        self.rendered = rendered
        self.doc = D.parse(rendered.html)
        css_text = self.doc.style_text() + "\n" + "\n".join(rendered.css or [])
        self.sheet = C.Stylesheet(css_text)
        self.body = next(iter(self.doc.all("body")), None) or self.doc.root
        self.html = self.doc.html or self.doc.root
        self.findings: list[Finding] = []
        self._seen = set()

    def add(self, rule, detail, message=""):
        f = Finding(self.page.service, self.page.page, self.page.identity.id, rule, detail, message or RULES.get(rule, ""))
        if f.id not in self._seen:
            self._seen.add(f.id)
            self.findings.append(f)

    # -- derived -------------------------------------------------------------------------
    def interactive(self):
        out = []
        for n in self.doc.root.iter():
            if n.tag == "a" and "href" in n.attrs:
                out.append(n)
            elif n.tag in ("button", "select", "textarea", "summary"):
                out.append(n)
            elif n.tag == "input" and (n.attrs.get("type") or "text").lower() != "hidden":
                out.append(n)
        return out

    def page_colours(self):
        def bg_of(n):
            while n is not None:
                v = self.sheet.computed(n).get("background-color")
                c = C.parse_color(v) if v else None
                if c and c[3] > 0:
                    return C.composite(c, (255, 255, 255, 1.0)) if c[3] < 1 else c
                n = n.parent
            return (255, 255, 255, 1.0)
        fg_v = self.sheet.inherited(self.body, "color")
        fg = C.parse_color(fg_v) if fg_v else None
        return (fg or (0, 0, 0, 1.0)), bg_of(self.body)


# ---------------------------------------------------------------------------------------------
def check_structure(cx: PageContext):
    doc = cx.doc
    heads = [n for n in doc.root.iter() if re.fullmatch(r"h[1-6]", n.tag)]
    h1s = [h for h in heads if h.tag == "h1"]
    if len(h1s) != 1:
        cx.add("h1-count", f"{len(h1s)} h1", f"found {len(h1s)} h1 elements")
    prev = 0
    for h in heads:
        level = int(h.tag[1])
        if prev and level > prev + 1:
            cx.add("heading-skip", f"h{prev}>h{level}", f"h{level} follows h{prev}")
        prev = level
        if not D.visible_text(h) and not D.accessible_name(h, doc):
            cx.add("heading-empty", h.tag)
    if "topic" in cx.page.tags and not any(h.tag == "h2" for h in heads):
        cx.add("heading-topic-missing", "no h2", "the page never names its own topic in a heading")

    mains = doc.all("main") + [n for n in doc.root.iter() if n.attrs.get("role") == "main"]
    if len(mains) != 1:
        cx.add("landmark-main", f"{len(mains)} main")
    navs = doc.all("nav")
    if len(navs) > 1:
        names = [D.accessible_name(n, doc) for n in navs]
        if "" in names or len(set(names)) != len(names):
            cx.add("landmark-nav-label", "navs not distinctly named")

    ids = {}
    for n in doc.root.iter():
        i = n.attrs.get("id")
        if i:
            ids[i] = ids.get(i, 0) + 1
    for i, k in ids.items():
        if k > 1:
            cx.add("duplicate-id", i)


def check_names(cx: PageContext):
    doc = cx.doc
    for n in cx.interactive():
        name = D.accessible_name(n, doc)
        if n.tag == "a" and not name:
            cx.add("link-name", n.attrs.get("href", ""), "link has no accessible name")
        elif n.tag in ("button", "summary") and not name:
            cx.add("button-name", n.label())
        elif n.tag in ("input", "select", "textarea") and not name:
            t = (n.attrs.get("type") or "text").lower() if n.tag == "input" else n.tag
            if t not in ("submit", "button", "reset", "image"):
                cx.add("input-name", f"{n.tag}[{t}] {n.attrs.get('name', '')}".strip(), "control has no label")
    for lab in doc.all("label"):
        target = lab.attrs.get("for")
        if target and target not in doc.by_id:
            cx.add("label-for-target", target)
    for img in doc.all("img"):
        if "alt" not in img.attrs:
            cx.add("img-alt", img.attrs.get("src", "")[:40])
    for a in doc.all("a"):
        if (a.attrs.get("target") or "").lower() == "_blank":
            host = re.sub(r"^https?://([^/]+).*$", r"\1", a.attrs.get("href", ""))
            rel = (a.attrs.get("rel") or "").lower().split()
            if "noopener" not in rel and "noreferrer" not in rel:
                cx.add("target-blank-rel", host)
            said = " ".join([D.accessible_name(a, doc), a.attrs.get("title", "")])
            if not re.search(r"new (tab|window)|opens in|external", said, re.I):
                cx.add("target-blank-hint", host, f"link text {D.accessible_name(a, doc)!r} does not say it opens a new tab")


def check_document(cx: PageContext):
    doc = cx.doc
    if not (cx.html.attrs.get("lang") or "").strip():
        cx.add("html-lang", "missing")
    metas = doc.all("meta")
    vp = next((m for m in metas if (m.attrs.get("name") or "").lower() == "viewport"), None)
    content = (vp.attrs.get("content", "") if vp else "").lower().replace(" ", "")
    if "width=device-width" not in content:
        cx.add("viewport", "no width=device-width")
    if "user-scalable=no" in content or re.search(r"maximum-scale=(0|1)(\.0*)?(,|$)", content):
        cx.add("viewport-zoom", "zoom disabled")
    title = next(iter(doc.all("title")), None)
    if title is None or not title.text_content().strip():
        cx.add("title-missing", "title")
    scheme = any((m.attrs.get("name") or "").lower() == "color-scheme" and "dark" in (m.attrs.get("content") or "").lower()
                 for m in metas)
    if not scheme:
        for n in (cx.html, cx.body):
            if "dark" in (cx.sheet.computed(n).get("color-scheme") or ""):
                scheme = True
    if not scheme:
        cx.add("color-scheme", "not declared", "native controls and scrollbars draw in light mode")
    for m in metas:
        if (m.attrs.get("http-equiv") or "").lower() == "refresh":
            cx.add("meta-refresh", (m.attrs.get("content") or "")[:30])
    if not cx.page.needs_js:
        for n in doc.root.iter():
            for a in n.attrs:
                if a.startswith("on"):
                    cx.add("inline-handler", f"{n.tag} {a}")
        for s in doc.all("script"):
            if (s.attrs.get("type") or "").lower() != "application/ld+json":
                cx.add("script-present", s.attrs.get("src") or "inline")
    # banners and alerts
    for n in doc.root.iter():
        if n.tag == "#text":
            continue
        cl = set(n.classes)
        if cl & {"banner", "alert", "flash"} and n.attrs.get("role") not in ("status", "alert") \
                and n.attrs.get("aria-live") is None:
            cx.add("status-role", n.label(), "status message is not announced to a screen reader")


def check_copy(cx: PageContext):
    title = next(iter(cx.doc.all("title")), None)
    text = D.visible_text(cx.body) + " " + (title.text_content() if title else "")
    for m in re.finditer("[" + EN + EM + "]", text):
        ctx = (text[max(0, m.start() - 14): m.start()] + "<dash>" + text[m.end(): m.end() + 14]).strip()
        cx.add("dash-in-copy", ("em" if m.group() == EM else "en") + ": " + ctx)
    for rx in (FIRST_PERSON_CI, FIRST_PERSON_CS):
        for m in rx.finditer(text):
            ctx = text[max(0, m.start() - 12): m.end() + 12].strip()
            cx.add("first-person", f"{m.group()}: {ctx}")


def check_leaks(cx: PageContext):
    """The page must not contain any token that names something the viewer may not use."""
    if not cx.page.forbid:
        return
    title = next(iter(cx.doc.all("title")), None)
    surface = [D.visible_text(cx.body), title.text_content() if title else ""]
    attrs = []
    for n in cx.doc.root.iter():
        if n.tag == "#text" or n.tag in ("style", "script"):
            continue
        for k in ("href", "src", "action", "formaction", "aria-label", "title", "alt", "value", "placeholder"):
            if n.attrs.get(k):
                attrs.append((k, n.attrs[k]))
    blob = "\n".join(surface)
    for tok in cx.page.forbid:
        if tok.startswith("href=/"):
            path = tok[len("href="):]
            hit = any(k == "href" and (v == path or v.startswith(path + "/") or v.startswith(path + "?")) for k, v in attrs)
        else:
            cs = tok.startswith("=")
            rx = re.compile(r"(?<![\w])" + re.escape(tok[1:] if cs else tok) + r"(?![\w])", 0 if cs else re.I)
            hit = bool(rx.search(blob)) or any(rx.search(v) for k, v in attrs if k != "src")
        if hit:
            tok = tok.lstrip("=")
            cx.add("leak", tok.lower(), f"the page mentions {tok!r}, which this viewer has no access to")


def check_status(cx: PageContext):
    want, got = cx.page.wanted_status, cx.rendered.status
    if want != got:
        cx.add("status", f"{cx.page.visibility}:{got}", f"expected HTTP {want}, got {got}")


# -- CSS-driven -------------------------------------------------------------------------------
def _strip_state(compound_raw):
    return re.sub(r":(hover|focus-visible|focus|active)\b", "", compound_raw)


def _base_key(sel: C.Selector):
    last = sel.parts[-1][1].raw
    head = "".join(f"{c}{p.raw}" if i else p.raw for i, (c, p) in enumerate(sel.parts[:-1]))
    return (head + " " + _strip_state(last)).strip()


def _has_focus(sel: C.Selector):
    return any(p in C.FOCUS_PSEUDOS for p in sel.parts[-1][1].pseudos)


def _ring_decl(decls):
    shadow = (decls.get("box-shadow") or ("", False))[0].strip().lower()
    if shadow and shadow != "none":
        return True
    ostyle = (decls.get("outline-style") or ("", False))[0] if "outline-style" in decls else None
    if "outline" in decls:
        ex = C.expand("outline", decls["outline"][0])
        return ex.get("outline-style") not in ("none",) and ex.get("outline-color", "x") != "transparent"
    return bool(ostyle and ostyle != "none")


def check_focus(cx: PageContext):
    sheet = cx.sheet
    interactive = cx.interactive()
    # 1. outline:none on a focusable selector with no ring rule for the same base selector
    ring_bases = set()
    for r in sheet.rules:
        if _ring_decl(r.decls):
            for s in r.selectors:
                if _has_focus(s):
                    ring_bases.add(_base_key(s))
    for r in sheet.rules:
        removes = ("outline" in r.decls and C.expand("outline", r.decls["outline"][0]).get("outline-style") == "none") \
            or (r.decls.get("outline-style", ("", 0))[0] == "none")
        if not removes:
            continue
        for s in r.selectors:
            state = "focus" if _has_focus(s) else "any"
            if not any(sheet.selector_matches(n, s, state) for n in interactive):
                continue
            if _has_focus(s) or not any(p in C.STATE_PSEUDOS for p in s.parts[-1][1].pseudos):
                if _base_key(s) not in ring_bases:
                    cx.add("focus-outline-none", s.raw, f"{s.raw} removes the outline and no :focus-visible rule draws a ring")
    # 2. computed: an interactive element whose focus state has no ring at all
    reported = set()
    for n in interactive:
        st = sheet.computed(n, "focus")
        shadow = (st.get("box-shadow") or "none").strip().lower()
        ostyle = st.get("outline-style")
        ocol = (st.get("outline-color") or "").strip().lower()
        outline_ok = ostyle is None or (ostyle != "none" and ocol != "transparent")
        if shadow != "none" or outline_ok:
            continue
        key = n.label() + (f"[type={n.attrs['type']}]" if n.tag == "input" and n.attrs.get("type") else "")
        if key not in reported:
            reported.add(key)
            cx.add("focus-ring-missing", key, f"{key} shows no outline or box-shadow when focused")


def _text_bearing(cx, n):
    return n.tag not in ("html", "head") and bool(D.visible_text(n))


def _bg_for_rule(cx: PageContext, rule: C.Rule, sel: C.Selector, page_bg):
    own = rule.decls.get("background-color") or rule.decls.get("background")
    if own:
        v = cx.sheet.resolve(own[0])
        col = C.parse_color(C.expand("background", v).get("background-color", v)) if v else None
        if col and col[3] > 0:
            return C.composite(col, page_bg) if col[3] < 1 else col
    # a state on an ancestor compound: use the background that state's own rule paints
    for idx in range(len(sel.parts) - 1, -1, -1):
        comp = sel.parts[idx][1]
        if any(p in C.STATE_PSEUDOS for p in comp.pseudos):
            prefix = "".join(f"{c if i else ''}{p.raw}" for i, (c, p) in enumerate(sel.parts[:idx + 1]))
            prefix = re.sub(r"\s+", " ", prefix)
            for r2 in cx.sheet.rules:
                if any(re.sub(r"\s+", " ", s2.raw) == prefix for s2 in r2.selectors):
                    b = r2.decls.get("background-color") or r2.decls.get("background")
                    if b:
                        v = cx.sheet.resolve(b[0])
                        col = C.parse_color(v)
                        if col and col[3] > 0:
                            return C.composite(col, page_bg) if col[3] < 1 else col
            return None
    return page_bg


def check_contrast(cx: PageContext):
    sheet = cx.sheet
    _fg, page_bg = cx.page_colours()
    all_nodes = [n for n in cx.doc.root.iter() if n.tag != "#text"]
    interactive = set(map(id, cx.interactive()))
    for r in sheet.rules:
        if r.media:
            continue
        for s in r.selectors:
            matched = [n for n in all_nodes if sheet.selector_matches(n, s, "any")]
            if not matched:
                continue
            # text colour against its ground
            cdecl = r.decls.get("color")
            if cdecl:
                fg = C.parse_color(sheet.resolve(cdecl[0]))
                if fg and any(_text_bearing(cx, n) for n in matched):
                    bg = _bg_for_rule(cx, r, s, page_bg)
                    if bg is not None:
                        eff = C.composite(fg, bg) if fg[3] < 1 else fg
                        ratio = C.contrast(eff, bg)
                        size = C.to_px(sheet.resolve(r.decls.get("font-size", ("", 0))[0]) or None)
                        need = LARGE_MIN if (size and size >= 24) else TEXT_MIN
                        if ratio < need:
                            cx.add("contrast-text", s.raw,
                                   f"{s.raw}: {C.to_hex(eff)} on {C.to_hex(bg)} is {ratio:.2f}:1, needs {need}:1")
            # border of something clickable or typeable
            if any(id(n) in interactive for n in matched):
                ex = {}
                for prop, (val, _i) in r.decls.items():
                    ex.update(C.expand(prop, sheet.resolve(val)))
                style = ex.get("border-style")
                col = C.parse_color(ex.get("border-color", "")) if ex.get("border-color") else None
                if col and style not in ("none", None) and col[3] > 0:
                    eff = C.composite(col, page_bg) if col[3] < 1 else col
                    ratio = C.contrast(eff, page_bg)
                    fill = _bg_for_rule(cx, r, s, page_bg)
                    fill_ratio = C.contrast(fill, page_bg) if fill is not None else 1.0
                    if ratio < EDGE_MIN and fill_ratio < EDGE_MIN:
                        cx.add("contrast-control-edge", s.raw,
                               f"{s.raw}: edge {C.to_hex(eff)} on {C.to_hex(page_bg)} is {ratio:.2f}:1, needs {EDGE_MIN}:1")


def _font_px(sheet, n):
    """(px, known). known is False when a size in the chain cannot be read (clamp, vw, calc)."""
    chain = []
    while n is not None:
        chain.append(n)
        n = n.parent
    size, known = 16.0, True
    for node in reversed(chain):
        v = sheet.computed(node).get("font-size")
        if v:
            px = C.to_px(v, size)
            if px is None and v.strip().endswith("%"):
                try:
                    px = size * float(v.strip()[:-1]) / 100
                except ValueError:
                    px = None
            if px:
                size = px
            else:
                known = False
    return size, known


def check_targets(cx: PageContext):
    sheet = cx.sheet
    for n in cx.interactive():
        if n.tag == "a" and D.inline_in_text(n):
            continue
        st = sheet.computed(n)
        fpx, known = _font_px(sheet, n)
        declared = []
        for prop in ("height", "min-height"):
            px = C.to_px(st.get(prop), fpx) if st.get(prop) else None
            if px is not None:
                declared.append(px)
        if not declared and not known:
            continue
        if declared:
            h, how = max(declared), "declared"
        else:
            lh = st.get("line-height") or sheet.inherited(n, "line-height") or "normal"
            if re.fullmatch(r"[\d.]+", lh):
                line = float(lh) * fpx
            else:
                line = C.to_px(lh, fpx) or 1.15 * fpx
            pad = sum(C.to_px(st.get(f"padding-{s}"), fpx) or 0 for s in ("top", "bottom"))
            bw = C.to_px(st.get("border-width"), fpx) if st.get("border-style") not in (None, "none") else 0
            border = 2 * (bw if bw is not None else 3 if st.get("border-style") else 0)
            if n.tag == "a" and not st.get("display") in ("flex", "block", "inline-block", "grid", "inline-flex"):
                border = sum(C.to_px(st.get(f"border-{s}-width"), fpx) or 0 for s in ("top", "bottom"))
            h, how = line + pad + border, "estimated"
        wdecl = C.to_px(st.get("width"), fpx) if st.get("width") else None
        small_w = wdecl is not None and wdecl < MIN_TARGET and n.tag == "input"
        lab = D.label_for(n, cx.doc) if n.tag == "input" else None
        if lab is not None and small_w:
            lst = sheet.computed(lab)
            if lst.get("display") in ("grid", "flex", "block"):   # the whole row is the target
                small_w = False
                h = max(h, MIN_TARGET)
        if h < MIN_TARGET - 0.5 or small_w:
            key = n.label() + (f"[type={n.attrs['type']}]" if n.tag == "input" and n.attrs.get("type") else "")
            cx.add("target-size", key, f"{key} is about {h:.0f}px tall ({how}); the floor is {MIN_TARGET:.0f}px")


CHECKS = (check_structure, check_names, check_document, check_copy, check_leaks, check_status,
          check_focus, check_contrast, check_targets)


def check_page(page: Page, rendered) -> list[Finding]:
    cx = PageContext(page, rendered)
    for chk in CHECKS:
        chk(cx)
    return cx.findings


def run(registry: Registry):
    """(findings, unavailable) over the whole registry. `unavailable` is [(key, reason)]."""
    findings, unavailable = [], []
    for page in registry.pages():
        rendered, why = page.produce()
        if rendered is None:
            unavailable.append((page.key, why))
            continue
        findings.extend(check_page(page, rendered))
    return findings, unavailable
