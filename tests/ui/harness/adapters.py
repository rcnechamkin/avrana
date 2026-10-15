"""Offline adapters: render the stdlib portal and Kindle connector pages from their own code.

Both services are BaseHTTPRequestHandler apps behind Authentik's outpost. The adapter drives the real
`Handler` class in memory (no socket, no thread, no port) with fixture identity headers, so the page
is exactly what the service would send, including its status code. It detects what the module offers
instead of assuming a version: the portal on `main` and on the authorization branch, and the Kindle
connector before and after the 404 / username-only change, are both handled.

Environment overrides (rarely needed): UI_HARNESS_PORTAL_PATH, UI_HARNESS_KINDLE_PATH point at a
different copy of the module, for example another worktree.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import sys
import types
import urllib.parse
import urllib.request
from email.message import Message
from pathlib import Path

from .pages import Identity, Page, Rendered, Unavailable, REPO_ROOT

PORTAL_PATH = Path(os.environ.get("UI_HARNESS_PORTAL_PATH") or REPO_ROOT / "services/avrana-portal/portal.py")
KINDLE_PATH = Path(os.environ.get("UI_HARNESS_KINDLE_PATH") or REPO_ROOT / "services/avrana-kindle-connector/kindle.py")

# ---------------------------------------------------------------------------------------------
# synthetic identities (never real people)
G_VIDEOS, G_AUDIO, G_COMICS, G_BOOKS = "avrana-videos", "avrana-audiobooks", "avrana-comics", "avrana-books"
G_CONTRIB, G_ADMIN = "library-contributors", "authentik Admins"


def _ident(id, groups, klass="member", label=""):
    return Identity(id=id, klass=klass, groups=tuple(groups), username="member-a", name="Member A",
                    email="a@example.test", label=label or id)


IDENTITIES = {
    "none": Identity(id="none", klass="member", groups=(), username="member-a", name="Member A",
                     email="a@example.test", label="signed in, no groups"),
    "videos": _ident("videos", [G_VIDEOS]),
    "audiobooks": _ident("audiobooks", [G_AUDIO]),
    "comics": _ident("comics", [G_COMICS]),
    "books": _ident("books", [G_BOOKS]),
    "contributors": _ident("contributors", [G_CONTRIB]),
    "admin": _ident("admin", [G_ADMIN], klass="admin"),
    "multi": _ident("multi", [G_VIDEOS, G_AUDIO, G_BOOKS], label="videos + audiobooks + books"),
}
GROUP_IDENTITY = {G_VIDEOS: "videos", G_AUDIO: "audiobooks", G_COMICS: "comics", G_BOOKS: "books",
                  G_CONTRIB: "contributors", G_ADMIN: "admin"}

# Forbidden tokens match case-insensitively as whole words; a token that starts with "=" (a service
# or topic label such as "Books") matches case-sensitively so ordinary prose ("your books") is not hit.
# Words that name a media type, per group. A viewer who lacks every group that owns a word must not
# read it anywhere (the "no-leak copy rule"). Service labels, hosts and paths are added from the
# portal's own tables in `portal_forbidden`.
GROUP_WORDS = {
    G_VIDEOS: ("movies", "movie", "films", "film", "TV"),
    G_AUDIO: ("audiobooks", "audiobook"),
    G_COMICS: ("comics", "comic", "manga"),
    G_BOOKS: ("ebooks", "ebook", "kindle"),
    G_CONTRIB: ("audible",),
    G_ADMIN: ("operations",),
}


# ---------------------------------------------------------------------------------------------
# in-memory HTTP
class _Out(io.BytesIO):
    def close(self):          # StreamRequestHandler.finish() closes wfile; keep the bytes
        self.flush()


class _FakeSocket:
    def __init__(self, raw: bytes):
        self._in = io.BytesIO(raw)
        self.out = _Out()

    def makefile(self, mode, *a, **k):
        return self._in if "r" in mode else self.out

    def settimeout(self, *_):
        pass

    def setsockopt(self, *_):
        pass

    def sendall(self, data):
        self.out.write(data)

    def close(self):
        pass


def call(handler_cls, method, path, headers=None, body=b""):
    """Run one request through `handler_cls` in memory. Returns (status, headers_dict, body_text)."""
    lines = [f"{method} {path} HTTP/1.0"]
    hdrs = dict(headers or {})
    if body:
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        hdrs["Content-Length"] = str(len(body))
    for k, v in hdrs.items():
        lines.append(f"{k}: {v}")
    raw = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body
    sock = _FakeSocket(raw)
    handler_cls(sock, ("127.0.0.1", 0), None)
    out = sock.out.getvalue()
    head, _, payload = out.partition(b"\r\n\r\n")
    status_line, *hlines = head.decode("latin-1").split("\r\n")
    status = int(status_line.split()[1])
    parsed = {}
    for h in hlines:
        k, _, v = h.partition(":")
        parsed[k.strip().lower()] = v.strip()
    return status, parsed, payload.decode("utf-8", "replace")


def identity_headers(ident: Identity):
    h = {}
    if ident.groups:
        h["X-authentik-groups"] = "|".join(ident.groups)
    if ident.username:
        h["X-authentik-username"] = ident.username
    if ident.name:
        h["X-authentik-name"] = ident.name
    if ident.email:
        h["X-authentik-email"] = ident.email
    return h


def _load(path: Path, name: str):
    if not path.is_file():
        raise Unavailable(f"{path.name} not found on this tree")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        sys.modules.pop(name, None)
        raise Unavailable(f"{path.name} did not import: {type(e).__name__}") from e
    return mod


_modules = {}


def portal_module():
    if "portal" not in _modules:
        _modules["portal"] = _load(PORTAL_PATH, "ui_harness_portal")
    return _modules["portal"]


def kindle_module():
    if "kindle" not in _modules:
        _modules["kindle"] = _load(KINDLE_PATH, "ui_harness_kindle")
    return _modules["kindle"]


def _html(status, headers, body):
    if "text/html" not in headers.get("content-type", ""):
        raise Unavailable(f"response was not HTML (status {status})")
    return status, body


# ---------------------------------------------------------------------------------------------
# portal
def _plain(text):
    import html as _h
    return _h.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def portal_forbidden(mod, ident: Identity):
    """Tokens a portal page rendered for `ident` must not contain, derived from the portal's tables."""
    groups = set(ident.groups)
    allows = getattr(mod, "allows", lambda spec, g: spec in g)
    services = getattr(mod, "SERVICES", [])
    allowed_specs, tokens, allowed_labels = [], [], set()
    for grp, label, _desc, path, host in services:
        specs = tuple(grp) if isinstance(grp, (tuple, list)) else (grp,)
        if allows(grp, groups):
            allowed_specs.extend(specs)
            allowed_labels.add(_plain(label))
    for grp, label, _desc, path, host in services:
        if allows(grp, groups):
            continue
        lab = _plain(label)
        if lab not in allowed_labels:
            tokens.append("=" + lab)
        tokens.append(host)
        tokens.append(f"href=/{path}")
    # help topics the viewer lacks
    for topic in getattr(mod, "HELP", []):
        grp, label, host = topic[0], topic[1], topic[2]
        if grp not in groups:
            if label not in allowed_labels:
                tokens.append("=" + label)
            tokens.append(host)
    # media-type words owned only by groups the viewer (or a service they can reach) does not hold
    held = set(groups) | set(allowed_specs)
    for grp, words in GROUP_WORDS.items():
        if grp not in held:
            tokens.extend(words)
    seen, out = set(), []
    for t in tokens:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return tuple(out)


def _portal_render(path, ident):
    def render():
        mod = portal_module()
        status, headers, body = call(mod.Handler, "GET", path, identity_headers(ident))
        status, body = _html(status, headers, body)
        return Rendered(status, body, notes=[f"portal Handler GET {path} in memory"])
    return render


def _portal_page(reg, page, ident, vis, path, tags=(), mod=None, allow=()):
    forbid = tuple(t for t in (portal_forbidden(mod, ident) if mod is not None else ()) if t not in allow)
    reg.add(Page("portal", page, ident, vis, _portal_render(path, ident), tags=tuple(tags), forbid=forbid))


def register_portal(reg):
    try:
        mod = portal_module()
        ok = hasattr(mod, "Handler") and hasattr(mod, "SERVICES")
        if not ok:
            raise Unavailable("portal module has no Handler/SERVICES")
    except Unavailable as e:
        reason = str(e)

        def gone():
            raise Unavailable(reason)
        reg.add(Page("portal", "all", IDENTITIES["none"], "authorized", gone, tags=("unavailable",)))
        return
    I = IDENTITIES
    parse = getattr(mod, "parse_groups", lambda raw: set(filter(None, re.split(r"[|,]", raw))))

    # home: every class of viewer
    for key in ("none", "videos", "audiobooks", "comics", "books", "contributors", "admin", "multi"):
        _portal_page(reg, "home", I[key], "empty" if key == "none" else "authorized", "/", ("home",), mod)

    # choosers: whatever the module declares; denied for a viewer with no member service
    members = getattr(mod, "chooser_members", None)
    for ch in getattr(mod, "CHOOSERS", []):
        path = ch[2]
        for key in ("none", "videos", "audiobooks", "comics", "books", "multi"):
            has = bool(members(ch, set(I[key].groups))) if members else key != "none"
            if key in ("none",) or has:
                _portal_page(reg, f"chooser-{path}", I[key], "authorized" if has else "denied",
                             f"/{path}", ("chooser",), mod)

    # help index
    for key, vis in (("none", "empty"), ("videos", "authorized"), ("multi", "authorized")):
        _portal_page(reg, "help-index", I[key], vis, "/help", ("help",), mod)

    # help topics: one page per topic the module declares, viewed by a holder of the topic's group
    slugs = getattr(mod, "HELP_SLUGS", {})
    first_topic = None
    for topic in getattr(mod, "HELP", []):
        grp, label = topic[0], topic[1]
        slug = slugs.get(label)
        if not slug:
            continue
        # "holder": whoever holds the topic's group. The id stays the same if a branch changes which
        # group gates a topic (the authorization branch moves Requests from avrana-requests to
        # avrana-videos), so baseline ids do not churn.
        ident = _ident("holder", [grp], label=f"holds {grp}")
        _portal_page(reg, f"help-{slug}", ident, "authorized", f"/help/{slug}", ("help", "topic"), mod,
                     allow=(topic[2],))
        first_topic = first_topic or (slug, grp)
    if first_topic:
        # the same topic for a viewer without its group: a plain 404
        other = next(k for k in ("books", "comics", "videos") if _group_of(k) != first_topic[1])
        _portal_page(reg, f"help-{first_topic[0]}", I[other], "denied", f"/help/{first_topic[0]}",
                     ("help", "denied"), mod)

    # account
    for key, vis in (("none", "empty"), ("videos", "authorized"), ("multi", "authorized"), ("admin", "authorized")):
        _portal_page(reg, "account", I[key], vis, "/account", ("account",), mod)

    # interstitial: a service route that pauses before handing off
    for path in getattr(mod, "INTERSTITIALS", {}):
        svc = next((s for s in mod.SERVICES if s[3] == path), None)
        if svc:
            grp = svc[0] if isinstance(svc[0], str) else svc[0][0]
            key = GROUP_IDENTITY.get(grp, "multi")
            _portal_page(reg, f"interstitial-{path}", I[key], "authorized", f"/{path}", ("interstitial",), mod)

    # not found
    _portal_page(reg, "not-found", I["none"], "denied", "/no-such-page", ("404",), mod)


def _group_of(identity_id):
    return next((g for g, i in GROUP_IDENTITY.items() if i == identity_id), "")


# ---------------------------------------------------------------------------------------------
# Kindle
KINDLE_VALUE = "member_a_demo@kindle.com"
KINDLE_WORDS = ("Kindle", "Amazon", "Calibre", "Audiobookshelf", "kindle.com", "Send-to-Kindle")


class _KindleFakes(contextlib.AbstractContextManager):
    """Patch the library back-ends of the Kindle module for one call: no SQLite file, no network.

    `cwa_find` is called as (username) or (username, email) depending on the version, so the stand-in
    takes *args. Restores everything on exit.
    """

    def __init__(self, mod, has_cwa, has_abs, cwa_value=None, abs_value=None):
        self.mod = mod
        self.cwa = [1, "member-a", cwa_value] if has_cwa else None
        self.abs_user = {"id": "abs-1", "username": "member-a", "email": "a@example.test"} if has_abs else None
        self.devices = [{"name": "Kindle (member-a)", "email": abs_value, "users": ["abs-1"],
                         "availabilityOption": "specificUsers"}] if (has_abs and abs_value) else []
        self.saved = {}

    def __enter__(self):
        m = self.mod
        self._orig = {n: getattr(m, n, None) for n in ("cwa_find", "cwa_set", "abs_find", "abs_call", "abs_devices", "abs_set")}
        m.cwa_find = lambda *a, **k: tuple(self.cwa) if self.cwa else None
        m.abs_find = lambda *a, **k: self.abs_user

        def cwa_set(uid, address):
            self.cwa[2] = address
        m.cwa_set = cwa_set
        m.abs_devices = lambda: list(self.devices)

        def abs_set(user, address, label):
            self.devices = [{"name": label, "email": address, "users": [user["id"]],
                             "availabilityOption": "specificUsers"}] if address else []
            return self.devices
        m.abs_set = abs_set
        m.abs_call = lambda *a, **k: {}
        # Guard: a back-end helper this list does not know about must fail the render, not reach the real
        # database or network.
        def refuse(*a, **k):
            raise AssertionError("Kindle render touched SQLite or the network; add the helper to _KindleFakes")
        self._guards = [(m, "sqlite3", getattr(m, "sqlite3", None)), (urllib.request, "urlopen", urllib.request.urlopen)]
        m.sqlite3 = types.SimpleNamespace(connect=refuse)
        urllib.request.urlopen = refuse
        return self

    def __exit__(self, *exc):
        for n, v in self._orig.items():
            if v is None:
                if hasattr(self.mod, n):
                    delattr(self.mod, n)  # it did not exist before: do not leave the fake behind
            else:
                setattr(self.mod, n, v)
        for owner, name, value in self._guards:
            if value is None:
                delattr(owner, name)
            else:
                setattr(owner, name, value)


def _kindle_ident(groups=(G_BOOKS,)):
    return Identity(id="member" if G_BOOKS in groups else "none", klass="member", groups=tuple(groups),
                    username="member-a", name="Member A", email="a@example.test")


def _kindle_render(method, path, ident, *, has_cwa=True, has_abs=True, cwa_value=None, abs_value=None, form=None):
    def render():
        mod = kindle_module()
        body = urllib.parse.urlencode(form).encode() if form is not None else b""
        with _KindleFakes(mod, has_cwa, has_abs, cwa_value, abs_value):
            status, headers, text = call(mod.Handler, method, path, identity_headers(ident), body)
        status, text = _html(status, headers, text)
        return Rendered(status, text, notes=[f"kindle Handler {method} {path} in memory; libraries faked"])
    return render


def kindle_forbidden(mod):
    """What a non-member must never read on the Kindle surface."""
    sender = getattr(mod, "SENDER", "")
    return tuple(KINDLE_WORDS) + ((sender,) if sender else ())


def register_kindle(reg):
    try:
        mod = kindle_module()
        if not hasattr(mod, "Handler"):
            raise Unavailable("kindle module has no Handler")
    except Unavailable as e:
        reason = str(e)

        def gone():
            raise Unavailable(reason)
        reg.add(Page("kindle", "all", IDENTITIES["none"], "authorized", gone, tags=("unavailable",)))
        return
    member = _kindle_ident()
    nobody = _kindle_ident(groups=())
    add = lambda page, vis, ident, render, tags=(), forbid=(), **kw: reg.add(
        Page("kindle", page, ident, vis, render, tags=tags, forbid=forbid, **kw))
    add("form-empty", "authorized", member, _kindle_render("GET", "/", member), ("form",))
    add("form-values", "authorized", member,
        _kindle_render("GET", "/", member, cwa_value=KINDLE_VALUE, abs_value=KINDLE_VALUE), ("form",))
    add("form-no-account", "degraded", member,
        _kindle_render("GET", "/", member, has_cwa=False, has_abs=False), ("form", "banner"))
    add("saved", "authorized", member,
        _kindle_render("POST", "/save", member, form={"address": KINDLE_VALUE}), ("form", "banner", "success"))
    add("error-bad-address", "degraded", member,
        _kindle_render("POST", "/save", member, form={"address": "not-an-address"}), ("form", "banner", "error"))
    add("not-found", "denied", nobody, _kindle_render("GET", "/", nobody), ("404",), forbid=kindle_forbidden(mod))
