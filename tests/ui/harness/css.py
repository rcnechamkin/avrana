"""A small CSS reader for the static layer: stdlib only, deliberately partial.

It understands what the Avrana stylesheets use: custom properties, comma selector lists, tag/class/
id/attribute/state selectors with descendant and child combinators, @media blocks (kept apart from
the base cascade), colour values (hex, rgb[a], a few names), and the shorthands that matter for
focus, contrast and target size. Anything it cannot evaluate is reported as "unknown" rather than
guessed, so a static finding is never invented from a value this module could not read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------------------------
# colour
NAMED = {"black": (0, 0, 0, 1.0), "white": (255, 255, 255, 1.0), "transparent": (0, 0, 0, 0.0)}
_HEX = re.compile(r"^#([0-9a-f]{3,8})$", re.I)
_FUNC = re.compile(r"^rgba?\(\s*([^)]*)\)$", re.I)


def parse_color(value):
    """(r, g, b, a) with r,g,b in 0..255 and a in 0..1, or None when not a plain colour."""
    if value is None:
        return None
    v = value.strip().lower()
    if v in NAMED:
        return NAMED[v]
    m = _HEX.match(v)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            h += "ff"
        if len(h) != 8:
            return None
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16) / 255)
    m = _FUNC.match(v)
    if m:
        parts = [p for p in re.split(r"[\s,/]+", m.group(1).strip()) if p]
        if len(parts) < 3:
            return None
        try:
            rgb = [float(p[:-1]) * 2.55 if p.endswith("%") else float(p) for p in parts[:3]]
            a = 1.0
            if len(parts) > 3:
                a = float(parts[3][:-1]) / 100 if parts[3].endswith("%") else float(parts[3])
        except ValueError:
            return None
        return (rgb[0], rgb[1], rgb[2], a)
    return None


def composite(fg, bg):
    """Colour fg (with alpha) painted over the opaque colour bg."""
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3)) + (1.0,)


def luminance(c):
    def chan(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * chan(c[0]) + 0.7152 * chan(c[1]) + 0.0722 * chan(c[2])


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def to_hex(c):
    return "#%02x%02x%02x" % tuple(int(round(x)) for x in c[:3])


# ---------------------------------------------------------------------------------------------
# parsing
@dataclass
class Compound:
    tag: str | None = None
    id: str | None = None
    classes: list = field(default_factory=list)
    attrs: list = field(default_factory=list)      # (name, op, value)
    pseudos: list = field(default_factory=list)
    unsupported: bool = False
    raw: str = ""


@dataclass
class Selector:
    raw: str
    parts: list            # [(combinator, Compound)], combinator is the one BEFORE the compound
    spec: tuple


@dataclass
class Rule:
    selectors: list
    decls: dict            # prop -> (value, important)
    media: str | None
    order: int
    selector_text: str


STATE_PSEUDOS = {"hover", "focus", "focus-visible", "active", "focus-within", "visited"}
FOCUS_PSEUDOS = {"focus", "focus-visible"}


def _strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _split_top(text, sep):
    out, depth, cur = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [p.strip() for p in out if p.strip()]


def parse_declarations(block):
    decls = {}
    for item in _split_top(block, ";"):
        if ":" not in item:
            continue
        name, _, value = item.partition(":")
        value = value.strip()
        imp = bool(re.search(r"!\s*important\s*$", value, re.I))
        if imp:
            value = re.sub(r"!\s*important\s*$", "", value, flags=re.I).strip()
        decls[name.strip().lower()] = (value, imp)
    return decls


_COMPOUND_PART = re.compile(
    r"""(?P<tag>\*|[a-zA-Z][\w-]*)|\#(?P<id>[\w-]+)|\.(?P<cls>[\w-]+)|\[(?P<attr>[^\]]*)\]|(?P<pseudo>::?[\w-]+(?:\([^)]*\))?)""",
    re.X)


def parse_compound(text):
    c = Compound(raw=text)
    pos = 0
    while pos < len(text):
        m = _COMPOUND_PART.match(text, pos)
        if not m:
            c.unsupported = True
            break
        pos = m.end()
        if m.group("tag"):
            c.tag = None if m.group("tag") == "*" else m.group("tag").lower()
        elif m.group("id"):
            c.id = m.group("id")
        elif m.group("cls"):
            c.classes.append(m.group("cls"))
        elif m.group("attr") is not None:
            am = re.match(r"\s*([\w-]+)\s*(?:([~|^$*]?=)\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\]]*)))?\s*$", m.group("attr"))
            if not am:
                c.unsupported = True
            else:
                val = am.group(3) if am.group(3) is not None else (am.group(4) if am.group(4) is not None else am.group(5))
                c.attrs.append((am.group(1).lower(), am.group(2), val))
        else:
            p = m.group("pseudo")
            if p.startswith("::") or "(" in p:
                c.unsupported = True
            c.pseudos.append(p.lstrip(":").lower())
    return c


def parse_selector(raw):
    s = raw.strip()
    parts, comb, i, n = [], " ", 0, len(s)
    while i < n:
        if s[i].isspace():
            i += 1
            continue
        if s[i] in ">+~":
            comb = s[i]
            i += 1
            continue
        j, depth = i, 0
        while j < n and (depth > 0 or not (s[j].isspace() or s[j] in ">+~")):
            if s[j] in "([":
                depth += 1
            elif s[j] in ")]":
                depth -= 1
            j += 1
        parts.append((comb, parse_compound(s[i:j])))
        comb = " "
        i = j
    ids = sum(1 for _, c in parts if c.id)
    cls = sum(len(c.classes) + len(c.attrs) + len([p for p in c.pseudos if p not in ("root",)]) for _, c in parts)
    tags = sum(1 for _, c in parts if c.tag)
    return Selector(raw=s, parts=parts, spec=(ids, cls, tags))


class Stylesheet:
    def __init__(self, text: str = ""):
        self.rules: list[Rule] = []
        self.vars: dict[str, str] = {}
        self._order = 0
        if text:
            self.add(text)

    def add(self, text: str):
        self._parse(_strip_comments(text), None)
        self._collect_vars()

    def _parse(self, text, media):
        i, n = 0, len(text)
        while i < n:
            j = text.find("{", i)
            if j < 0:
                break
            head = text[i:j].strip()
            depth, k = 1, j + 1
            while k < n and depth:
                depth += (text[k] == "{") - (text[k] == "}")
                k += 1
            body = text[j + 1:k - 1]
            i = k
            if head.startswith("@media"):
                self._parse(body, head[len("@media"):].strip())
            elif head.startswith("@"):
                continue  # @font-face, @keyframes, @supports: not evaluated
            else:
                sels = [parse_selector(s) for s in _split_top(head, ",")]
                self._order += 1
                self.rules.append(Rule(sels, parse_declarations(body), media, self._order, head))

    def _collect_vars(self):
        for r in self.rules:
            if r.media:
                continue
            if any(s.raw in (":root", "html") for s in r.selectors):
                for k, (v, _imp) in r.decls.items():
                    if k.startswith("--"):
                        self.vars[k] = v

    def resolve(self, value: str | None, _depth=0):
        """Substitute var(--x[, fallback]) using :root custom properties."""
        if value is None or "var(" not in value or _depth > 8:
            return value

        def sub(m):
            name, fallback = m.group(1), m.group(2)
            if name in self.vars:
                return self.resolve(self.vars[name], _depth + 1)
            return fallback.strip() if fallback is not None else m.group(0)
        out = re.sub(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)", sub, value)
        return out

    # -- selector matching ---------------------------------------------------------------
    def _compound_matches(self, node, c: Compound, state: str, last: bool):
        if c.unsupported:
            return False
        if c.tag and node.tag != c.tag:
            return False
        if c.id and node.attrs.get("id") != c.id:
            return False
        if any(cl not in node.classes for cl in c.classes):
            return False
        for name, op, val in c.attrs:
            have = node.attrs.get(name)
            if have is None:
                return False
            if op is None:
                continue
            if op == "=" and have != val:
                return False
            if op == "~=" and val not in have.split():
                return False
            if op == "^=" and not have.startswith(val):
                return False
            if op == "$=" and not have.endswith(val):
                return False
            if op == "*=" and val not in have:
                return False
            if op == "|=" and not (have == val or have.startswith(val + "-")):
                return False
        for p in c.pseudos:
            if state == "any" and p in STATE_PSEUDOS:
                continue
            if p in FOCUS_PSEUDOS:
                if not (state == "focus" and last):
                    return False
            elif p in STATE_PSEUDOS:
                return False
            elif p == "root":
                if node.tag != "html":
                    return False
            elif p in ("first-child", "last-child", "first-of-type", "last-of-type"):
                sibs = node.parent.element_children() if node.parent else [node]
                if p == "first-child" and sibs[0] is not node:
                    return False
                if p == "last-child" and sibs[-1] is not node:
                    return False
                same = [s for s in sibs if s.tag == node.tag]
                if p == "first-of-type" and same[0] is not node:
                    return False
                if p == "last-of-type" and same[-1] is not node:
                    return False
            else:
                return False
        return True

    def selector_matches(self, node, sel: Selector, state="rest"):
        parts = sel.parts
        if not parts:
            return False

        def rec(n, idx):
            comb, comp = parts[idx]
            if not self._compound_matches(n, comp, state, last=(idx == len(parts) - 1)):
                return False
            if idx == 0:
                return True
            if comb == " ":
                p = n.parent
                while p is not None:
                    if rec(p, idx - 1):
                        return True
                    p = p.parent
                return False
            if comb == ">":
                return n.parent is not None and rec(n.parent, idx - 1)
            return False
        return rec(node, len(parts) - 1)

    # -- cascade -------------------------------------------------------------------------
    def computed(self, node, state="rest"):
        """Declared (not used) values for node, with shorthands expanded and var() resolved.
        Only the base cascade (no @media). Inline style wins."""
        hits = []
        for r in self.rules:
            if r.media:
                continue
            for s in r.selectors:
                if self.selector_matches(node, s, state):
                    hits.append((s.spec, r.order, r.decls))
        style = node.attrs.get("style")
        if style:
            hits.append(((9, 0, 0), 10 ** 9, parse_declarations(style)))
        flat = {}
        weight = {}
        for spec, order, decls in sorted(hits, key=lambda h: (h[0], h[1])):
            for prop, (val, imp) in decls.items():
                if prop.startswith("--"):
                    continue
                for p, v in expand(prop, self.resolve(val)).items():
                    key = (1 if imp else 0,)
                    if p not in weight or key >= weight[p]:
                        flat[p] = v
                        weight[p] = key
        return flat

    def inherited(self, node, prop, state="rest"):
        n = node
        while n is not None:
            v = self.computed(n, state if n is node else "rest").get(prop)
            if v is not None and v != "inherit":
                return v
            n = n.parent
        return None


# ---------------------------------------------------------------------------------------------
def expand(prop, value):
    """Expand the shorthands the checks care about."""
    v = value.strip()
    if prop == "outline":
        out = {"outline-style": "solid", "outline-width": "medium"}
        if v in ("none", "0"):
            out["outline-style"] = "none"
            return out
        for tok in _split_ws(v):
            if re.match(r"^[\d.]+(px|rem|em)$", tok):
                out["outline-width"] = tok
            elif tok in ("solid", "dashed", "dotted", "double", "auto", "none"):
                out["outline-style"] = tok
            else:
                out["outline-color"] = tok
        return out
    if prop == "padding" or prop == "margin":
        t = _split_ws(v)
        if not 1 <= len(t) <= 4:
            return {}
        t = t * 4 if len(t) == 1 else t * 2 if len(t) == 2 else t + [t[1]] if len(t) == 3 else t
        return {f"{prop}-{s}": x for s, x in zip(("top", "right", "bottom", "left"), t)}
    m = re.match(r"^border(-(?:top|right|bottom|left))?$", prop)
    if m:
        side = m.group(1) or ""
        out = {}
        for tok in _split_ws(v):
            if re.match(r"^[\d.]+(px|rem|em)$", tok):
                out[f"border{side}-width"] = tok
            elif tok in ("solid", "dashed", "dotted", "double", "none"):
                out[f"border{side}-style"] = tok
            else:
                out[f"border{side}-color"] = tok
        if v in ("0", "none"):
            out[f"border{side}-style"] = "none"
        return out
    if prop == "background":
        for tok in _split_ws(v):
            if parse_color(tok):
                return {"background-color": tok}
        return {"background-color": v} if v in ("none", "transparent") else {}
    if prop == "font":
        m = re.match(r"^(?:[\w-]+\s+)*?([\d.]+(?:px|rem|em|%))(?:\s*/\s*([\d.]+(?:px|rem|em|%)?))?\s+(.+)$", v)
        if m:
            out = {"font-size": m.group(1), "font-family": m.group(3)}
            if m.group(2):
                out["line-height"] = m.group(2)
            return out
        return {}
    return {prop: v}


def _split_ws(v):
    return _split_top_ws(v)


def _split_top_ws(text):
    out, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch.isspace() and depth == 0:
            if cur:
                out.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def to_px(value, font_px=16.0, root_px=16.0):
    """Length in px, or None when it cannot be known statically (clamp, vw, calc, auto...)."""
    if value is None:
        return None
    v = value.strip().lower()
    m = re.match(r"^(-?[\d.]+)(px|rem|em)?$", v)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2)
    if unit == "px":
        return n
    if unit == "rem":
        return n * root_px
    if unit == "em":
        return n * font_px
    return 0.0 if n == 0 else None
