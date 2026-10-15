"""AVR-362 (narrow slice): do the three custom UIs still agree on the house-style tokens?

Reads the inline stylesheets of the portal and the Kindle connector (their `STYLE` strings, parsed
with `ast`, never executed) and the Audible connector's `style.css`, extracts the shared tokens and
the literal colours they repeat, and compares them with a reference:

* `docs/design/foundation/tokens.json` (theme "media") when that file exists. It is the design team's
  proposal (PR #3) and is not on every branch; when it lands this module uses it automatically.
* otherwise the services against each other, the first service that defines a token (portal, then
  Kindle, then Audible) being the pivot.

Known differences live in `token_drift_allowlist.json`, one entry per (token, service, value) with a
reason and an issue. A divergence not in the list is new and fails `tests/test_token_drift.py`.
This module builds no shared stylesheet and changes no service.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from . import css as C
from .adapters import KINDLE_PATH, PORTAL_PATH
from .pages import HARNESS_DIR, REPO_ROOT

AUDIBLE_CSS = REPO_ROOT / "services/avrana-audible-connector/connector/app/static/style.css"
TOKENS_JSON = REPO_ROOT / "docs/design/foundation/tokens.json"
ALLOWLIST = HARNESS_DIR / "token_drift_allowlist.json"
SERVICES = ("portal", "kindle", "audible")
GROUND = (0, 0, 0, 1.0)

# service variable name -> design role
VAR_ROLE = {"bg": "surface", "fg": "on_surface", "dim": "on_surface_muted", "line": "outline_quiet",
            "line-strong": "outline_strong", "strong": "outline_strong", "control": "outline_control",
            "line-control": "outline_control", "err": "status_error", "ok": "status_ok", "warn": "status_warn",
            # names the accessibility repairs (AVR-357/358/359) gave the same roles
            "ink": "surface", "paper": "on_surface", "ash": "on_surface_muted", "rule-quiet": "outline_quiet",
            "rule-control": "outline_control", "rule-strong": "outline_strong"}
# reference: tokens.json "color" keys we compare
REF_COLOURS = ("surface", "on_surface", "on_surface_muted", "outline_quiet", "outline_control", "outline_strong",
               "status_ok", "status_warn", "status_error")
# colours DESIGN.md allows that are not roles in tokens.json (hover description ink)
EXTRA_PALETTE = {"#333333"}

# where each service draws the shared components
SELECTORS = {
# "mark" is which of DESIGN.md's two wordmark sizes the service draws: the full one on the portal home,
# the compact one on every inner page. Sizes are compared within a kind; the tracking across all.
    "portal": {"column": ".page", "wordmark": "h1", "mark": "full", "button": None, "field": None},
    "kindle": {"column": ".page", "wordmark": "h1", "mark": "compact", "button": "button", "field": "input[type=email]"},
    "audible": {"column": ".wrap", "wordmark": ".wordmark", "mark": "compact", "button": "button", "field": "input[type=email]"},
}


def inline_style(path: Path) -> str:
    """The module-level STYLE string literal, read with ast (the module is not imported)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "STYLE" for t in node.targets):
            return ast.literal_eval(node.value)
    raise LookupError(f"no literal STYLE in {path.name}")


def load_sources(overrides=None):
    """service -> stylesheet text."""
    src = {"portal": inline_style(PORTAL_PATH), "kindle": inline_style(KINDLE_PATH),
           "audible": AUDIBLE_CSS.read_text(encoding="utf-8")}
    src.update(overrides or {})
    return src


def _norm_colour(value):
    col = C.parse_color(value)
    if col is None:
        return None
    return C.to_hex(C.composite(col, GROUND) if col[3] < 1 else col)


def _norm_ws(v):
    v = re.sub(r"\s+", " ", v.strip().lower())
    v = re.sub(r"\s*,\s*", ",", v)
    v = re.sub(r"#([0-9a-f])([0-9a-f])([0-9a-f])\b", r"#\1\1\2\2\3\3", v)
    return v


def _families(v):
    return ",".join(f.strip().strip("\"'").lower() for f in _norm_ws(v).split(",") if f.strip())


def _find(sheet, selector, prop):
    """Last base-cascade value of `prop` declared by a rule that lists exactly `selector`."""
    if not selector:
        return None
    for r in reversed(sheet.rules):
        if r.media or selector not in {re.sub(r"\s+", "", s.raw) for s in r.selectors}:
            continue
        for p, (val, _imp) in r.decls.items():
            ex = C.expand(p, sheet.resolve(val))
            if prop in ex:
                return ex[prop]
    return None


def extract(text):
    """token -> normalised value, for what this stylesheet defines."""
    sheet = C.Stylesheet(text)
    out = {}
    for var, val in sheet.vars.items():
        role = VAR_ROLE.get(var.lstrip("-"))
        c = _norm_colour(sheet.resolve(val)) if role else None
        if c:
            out[f"color.{role}"] = c
    fam = _find(sheet, "body", "font-family")
    if fam:
        out["font.family"] = _families(fam)
    # focus ring: the first :focus-visible rule that draws a box-shadow
    for r in sheet.rules:
        if any(":focus-visible" in s.raw for s in r.selectors) and "box-shadow" in r.decls:
            sh = sheet.resolve(r.decls["box-shadow"][0])
            if sh.strip().lower() != "none":
                out["focus.ring"] = _norm_ws(sh)
                break
    return out, sheet


def extract_service(service, text):
    tokens, sheet = extract(text)
    sel = SELECTORS[service]
    col = _find(sheet, sel["column"], "max-width")
    if col:
        tokens["layout.column"] = _norm_ws(col)
    for name, prop in ((f"wordmark.{sel['mark']}.size", "font-size"), ("wordmark.tracking", "letter-spacing")):
        v = _find(sheet, sel["wordmark"], prop)
        if v:
            tokens[name] = _norm_ws(v)
    v = _find(sheet, sel["button"], "padding-top")
    h = _find(sheet, sel["button"], "padding-left")
    if v and h:
        tokens["button.padding"] = f"{_norm_ws(v)} {_norm_ws(h)}"
    v = _find(sheet, sel["field"], "padding-top")
    h = _find(sheet, sel["field"], "padding-left")
    if v and h:
        tokens["field.padding"] = f"{_norm_ws(v)} {_norm_ws(h)}"
    # literal colours written into rules (not custom-property definitions)
    lits = set()
    for r in sheet.rules:
        if any(s.raw in (":root", "html") for s in r.selectors) and all(k.startswith("--") for k in r.decls):
            continue
        for prop, (val, _imp) in r.decls.items():
            if prop.startswith("--"):
                continue
            for m in re.finditer(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)", val):
                c = _norm_colour(m.group(0))
                if c:
                    lits.add(c)
    tokens["literal.colours"] = ",".join(sorted(lits))
    return tokens


def reference_from_tokens(path: Path):
    """tokens.json (theme media) -> {token: value}, or None when the file is absent or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        media = data["themes"]["media"]
    except (OSError, KeyError, ValueError):
        return None
    ref = {}
    for key in REF_COLOURS:
        v = media.get("color", {}).get(key)
        if isinstance(v, str) and C.parse_color(v):
            ref[f"color.{key}"] = _norm_colour(v)
    iface = media.get("type", {}).get("interface")
    if iface:
        ref["font.family"] = _families(iface)
    ring = media.get("color", {}).get("focus_ring")
    if ring:
        ref["focus.ring"] = _norm_ws(ring)
    return ref


def compare(per_service, reference=None):
    """(divergences, undefined, source). A divergence is a dict with token, service, value, expected."""
    src = "tokens.json" if reference else "peers"
    ref = dict(reference or {})
    divergences, undefined = [], []
    tokens = sorted({t for s in per_service.values() for t in s if t != "literal.colours"})
    for tok in tokens:
        want = ref.get(tok)
        origin = "tokens.json" if want is not None else None
        for svc in SERVICES:
            have = per_service[svc].get(tok)
            if have is None:
                continue
            if want is None:             # peer pivot: the first service that defines it
                want, origin = have, svc
                continue
            if have != want:
                divergences.append({"token": tok, "service": svc, "value": have, "expected": want, "reference": origin})
    palette = set(EXTRA_PALETTE) | {v for k, v in ref.items() if k.startswith("color.")}
    if not reference:
        palette |= {v for s in per_service.values() for k, v in s.items() if k.startswith("color.")}
    for svc in SERVICES:
        for lit in filter(None, per_service[svc].get("literal.colours", "").split(",")):
            if lit not in palette:
                divergences.append({"token": "literal.colour", "service": svc, "value": lit,
                                    "expected": "a palette colour", "reference": "palette"})
    for tok in sorted(t for t in ref if t not in tokens):
        undefined.append(tok)
    return divergences, undefined, src


def load_allowlist(path: Path = ALLOWLIST):
    if not Path(path).is_file():
        return []
    return json.loads(Path(path).read_text(encoding="utf-8")).get("allow", [])


def allowed(div, allow):
    return any(a["token"] == div["token"] and a["service"] == div["service"] and a["value"] == div["value"] for a in allow)


def run(overrides=None, tokens_path=TOKENS_JSON, allowlist=None):
    per_service = {s: extract_service(s, t) for s, t in load_sources(overrides).items()}
    reference = reference_from_tokens(tokens_path) if tokens_path else None
    divs, undefined, src = compare(per_service, reference)
    allow = load_allowlist() if allowlist is None else allowlist
    new = [d for d in divs if not allowed(d, allow)]
    known = [d for d in divs if allowed(d, allow)]
    # an entry that only applies against tokens.json is not "unused" while that file is absent
    unused = [a for a in allow if not any(allowed(d, [a]) for d in divs)
              and (a.get("reference", "any") == "any" or a.get("reference") == src)]
    return {"per_service": per_service, "source": src, "new": new, "known": known, "unused": unused,
            "undefined": undefined, "divergences": divs}
