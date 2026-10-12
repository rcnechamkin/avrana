"""Authorization tests for services/avrana-portal/portal.py (AVR-352, sprint item S1-1, gate G2).

Offline and stdlib only. The real `Handler` is served by a ThreadingHTTPServer bound to
127.0.0.1 on an ephemeral port, in a thread of this process. Nothing else is contacted and no
identity here is real (see tests/fixtures/identities.py).

Expectations are written in two independent ways:
  * PINNED tables below hold the intended access rules as literals in this file. If someone
    widens a service's group in portal.py, a pinned expectation fails.
  * Leak checks and a few cross-checks DERIVE their material from the portal's own tables
    (SERVICES, CHOOSERS, HELP, INTERSTITIALS, SSO_INIT), so a newly added service cannot slip
    past unexamined: test_tables_match_pins fails until it is pinned here too.

Principle under test: a request is allowed, or it gets a plain 404. Never a 403, and never any
hint that a withheld service exists.
"""
import concurrent.futures
import html
import importlib.util
import io
import re
import socket
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fixtures.identities import (  # noqa: E402
    ADMIN, AUDIOBOOKS, BASELINE, BOOKS, COMICS, CONTRIBUTORS, IDENTITIES, MEMBER_A, MEMBER_B,
    VIDEOS,
)

PORTAL_PATH = HERE.parents[0] / "services" / "avrana-portal" / "portal.py"
spec = importlib.util.spec_from_file_location("avrana_portal_under_test", PORTAL_PATH)
portal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portal)

GROUPS_HEADER = "X-authentik-groups"

# ---------------------------------------------------------------------------------------------
# PINNED expectations (independent of portal.py's tables)
# ---------------------------------------------------------------------------------------------

# service path -> (groups of which holding ANY one grants access, fixed redirect or "interstitial")
PIN_SERVICES = {
    "watch":         ({VIDEOS}, "interstitial"),
    "listen":        ({AUDIOBOOKS}, "https://listen.avrana.net"),
    "comics":        ({COMICS}, "https://read.avrana.net/oauth2/authorization/authentik"),
    "books":         ({BOOKS}, "https://books.avrana.net"),
    "kindle":        ({BOOKS}, "https://kindle.avrana.net"),
    "requests":      ({VIDEOS}, "https://request.avrana.net"),
    "requestabook":  ({BOOKS, AUDIOBOOKS}, "https://requestabook.avrana.net"),
    "requestacomic": ({COMICS}, "https://requestacomic.avrana.net"),
    "contribute":    ({CONTRIBUTORS}, "https://contribute.avrana.net"),
    "ops":           ({ADMIN}, "https://ops.avrana.net"),
}
# chooser path -> groups of which holding ANY one makes the sub-page render
PIN_CHOOSERS = {
    "read":    {COMICS, BOOKS},
    "request": {VIDEOS, BOOKS, AUDIOBOOKS, COMICS},
}
# help slug -> the one group that unlocks it (the SAME group as the service it documents)
PIN_HELP = {
    "audiobooks": AUDIOBOOKS,
    "movies":     VIDEOS,
    "books":      BOOKS,
    "comics":     COMICS,
    "requests":   VIDEOS,
}
ALWAYS_200 = ("/", "/account", "/help", "/healthz")
ALL_LOCATIONS = {t for _g, t in PIN_SERVICES.values() if t != "interstitial"}
OPERATOR_TOKENS = ("Operations", "ops.avrana.net", "/ops", "Health, restarts, backups")

# Home grid tiles per identity, in page order (HOME_ORDER: watch listen read request contribute ops help).
_ALL_TILES = ["watch", "listen", "read", "request", "contribute"]
PIN_HOME = {
    "no_header":       ["help"],
    "empty_header":    ["help"],
    "baseline_only":   ["help"],
    "videos":          ["watch", "request", "help"],
    "audiobooks":      ["listen", "request", "help"],
    "comics":          ["read", "request", "help"],
    "books":           ["read", "request", "help"],
    "contributors":    ["contribute", "help"],
    "legacy_requests": ["help"],
    "all_members":     _ALL_TILES + ["help"],
    "admin_only":      ["ops", "help"],
    "admin_and_all":   _ALL_TILES + ["ops", "help"],
}

# Which routes are exercised everywhere.
SERVICE_ROUTES = ["/" + p for p in PIN_SERVICES]
CHOOSER_ROUTES = ["/" + p for p in PIN_CHOOSERS]
HELP_ROUTES = ["/help/" + s for s in PIN_HELP]
UNKNOWN_ROUTES = ["/nope", "/admin", "/ops/x", "/help/nope", "/help/movies/extra", "/index.html",
                  "/favicon.ico", "/outpost.goauthentik.io/sign_out", "/read/comics", "/static",
                  "/help/Movies", "/WATCH", "/Watch", "/Ops"]
ROUTES = (["/", "/account", "/help", "/healthz"] + HELP_ROUTES + CHOOSER_ROUTES + SERVICE_ROUTES
          + UNKNOWN_ROUTES)

# Routes excluded from the matrix because a known defect makes the pin fail (none at present).
MATRIX_SKIP = set()
LEAK_SKIP = {("books", "/")}   # defect 4 (not fixed): Read tile subtitle says "Comics"


def expected(route, groups):
    """(status, location) for a clean route and a set of group names, from the PINNED tables."""
    if route in ALWAYS_200:
        return (200, None)
    if route.startswith("/help/"):
        need = PIN_HELP.get(route[len("/help/"):])
        return (200, None) if need and need in groups else (404, None)
    key = route[1:]
    if key in PIN_CHOOSERS:
        return (200, None) if PIN_CHOOSERS[key] & groups else (404, None)
    if key in PIN_SERVICES:
        need, target = PIN_SERVICES[key]
        if need & groups:
            return (200, None) if target == "interstitial" else (307, target)
    return (404, None)


# ---------------------------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------------------------

class _Server(ThreadingHTTPServer):
    request_queue_size = 128  # concurrent tests; the default backlog of 5 can reset on Windows


class _Handler(portal.Handler):
    """The real handler, with Nagle off. The portal writes headers and body in two sends; with
    Nagle on, Windows loopback adds ~40 ms of delayed-ACK per request and the suite crawls."""
    disable_nagle_algorithm = True


_server = None
_thread = None
PORT = None


def setUpModule():
    global _server, _thread, PORT
    _server = _Server(("127.0.0.1", 0), _Handler)
    PORT = _server.server_address[1]
    _thread = threading.Thread(target=_server.serve_forever, kwargs={"poll_interval": 0.05},
                               daemon=True)
    _thread.start()


def tearDownModule():
    _server.shutdown()
    _server.server_close()
    _thread.join(timeout=5)


class Resp:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    def all(self, name):
        return [v for k, v in self.headers if k.lower() == name.lower()]

    def header(self, name):
        vals = self.all(name)
        return vals[0] if vals else None

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")

    @property
    def location(self):
        return self.header("Location")


def _b(v):
    return v if isinstance(v, bytes) else v.encode("latin-1")


class PortalUnreachable(AssertionError):
    """The harness could not get a response at all: a test-environment fault, not a decision."""


class _FakeSocket:
    """Just enough of a socket for StreamRequestHandler: the request bytes in, replies out."""

    def __init__(self, wire):
        self._in = io.BytesIO(wire)
        self.sent = io.BytesIO()

    def makefile(self, mode, *_a, **_k):
        return self._in if "r" in mode else self.sent

    def sendall(self, data):
        self.sent.write(data)

    def settimeout(self, _t):
        pass

    def close(self):
        pass


def _exchange_in_process(wire):
    """Run the REAL Handler over an in-memory connection: no socket, no port, same code path
    (request parsing, routing, send_error replies, headers). Most of the suite uses this, so it
    cannot exhaust ephemeral ports or race a server thread."""
    sock = _FakeSocket(wire)
    portal.Handler(sock, ("127.0.0.1", 0), None)
    return sock.sent.getvalue()


def _exchange_live(wire, timeout=10):
    """The same over a real loopback connection to the harness server. One bounded retry, at
    connect time only, for refused/reset/timeout; nothing is retried once bytes may have been
    exchanged."""
    s = None
    for attempt in (1, 2):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
            break
        except (ConnectionRefusedError, ConnectionResetError, socket.timeout) as exc:
            if attempt == 2:
                raise PortalUnreachable(f"cannot connect to 127.0.0.1:{PORT}: {exc!r}") from exc
            time.sleep(0.25)
    chunks = []
    with s:
        try:
            s.sendall(wire)
        except OSError:
            pass  # server may answer and close before reading an oversized request
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        while True:
            try:
                data = s.recv(65536)
            except OSError as exc:
                if not chunks:
                    raise PortalUnreachable(f"connection died before any reply: {exc!r}") from exc
                break
            if not data:
                break
            chunks.append(data)
    return b"".join(chunks)


def send_raw(wire, live=False):
    """Send exact bytes and parse the reply. Raises PortalUnreachable if there is none."""
    data = _exchange_live(wire) if live else _exchange_in_process(wire)
    if not data:
        raise PortalUnreachable("empty reply")
    head, _sep, body = data.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    if not lines[0].startswith(b"HTTP/"):
        # http.server answers an unparseable request line in HTTP/0.9 style: a bare body.
        return Resp(0, [], data)
    status = int(lines[0].split()[1])
    headers = []
    for ln in lines[1:]:
        k, _s, v = ln.partition(b":")
        headers.append((k.decode("latin-1").strip(), v.decode("latin-1").strip()))
    return Resp(status, headers, body)


def request(target, headers=(), method="GET", host="portal.test", body=b"", version="HTTP/1.1",
            live=False):
    lines = [f"{method} {target} {version}".encode("latin-1")]
    if host is not None:
        lines.append(b"Host: " + _b(host))
    for k, v in headers:
        lines.append(_b(k) + b": " + _b(v))
    lines.append(b"Connection: close")
    if body:
        lines.append(b"Content-Length: " + str(len(body)).encode())
    wire = b"\r\n".join(lines) + b"\r\n\r\n" + body
    return send_raw(wire, live)


def ident_headers(name):
    g = IDENTITIES[name]
    return [] if g is None else [(GROUPS_HEADER, "|".join(g))]


def groups_of(name):
    return set(IDENTITIES[name] or [])


_cache = {}


def fetch(ident, target, method="GET"):
    key = (ident, target, method)
    if key not in _cache:
        _cache[key] = request(target, ident_headers(ident), method=method)
    return _cache[key]


def tile_paths(page):
    return re.findall(r'<a class="tile" href="/([^"]*)"', page)


def with_groups(value):
    return [(GROUPS_HEADER, value)]


# ---------------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------------

class PinTests(unittest.TestCase):
    """The portal's tables must agree with the pins; a new or widened entry fails here."""

    def test_tables_match_pins(self):
        seen = {}
        for grp, _label, _desc, path, host in portal.SERVICES:
            seen[path] = (set(grp) if isinstance(grp, (tuple, list)) else {grp}, host)
        self.assertEqual(set(PIN_SERVICES), set(seen), "service added or removed: pin it")
        for path, (need, target) in PIN_SERVICES.items():
            with self.subTest(path=path):
                self.assertEqual(need, seen[path][0], "group requirement changed")
                if target == "interstitial":
                    self.assertIn(path, portal.INTERSTITIALS)
                else:
                    want = portal.SSO_INIT.get(path, f"https://{seen[path][1]}")
                    self.assertEqual(target, want)

    def test_choosers_and_interstitials_match_pins(self):
        self.assertEqual(set(PIN_CHOOSERS), {c[2] for c in portal.CHOOSERS})
        for ch in portal.CHOOSERS:
            union = set()
            for m in ch[3]:
                union |= PIN_SERVICES[m][0]
            self.assertEqual(PIN_CHOOSERS[ch[2]], union, ch[2])
        self.assertEqual({"watch"}, set(portal.INTERSTITIALS))
        self.assertEqual("/help/movies", portal.INTERSTITIALS["watch"][1])
        self.assertEqual({"comics"}, set(portal.SSO_INIT))
        self.assertEqual({}, portal.ALIASES)

    def test_no_path_collisions_between_namespaces(self):
        svc = {s[3] for s in portal.SERVICES}
        ch = {c[2] for c in portal.CHOOSERS}
        self.assertFalse(svc & ch, "a chooser shadows a service route (choosers are looked up first)")
        self.assertFalse((svc | ch) & {"help", "account", "healthz", ""})

    def test_help_topics_match_pins(self):
        slugs = {portal.HELP_SLUGS[h[1]] for h in portal.HELP}
        self.assertEqual(set(PIN_HELP), slugs)

    def test_help_groups_match_the_service_they_document(self):
        got = {portal.HELP_SLUGS[h[1]]: h[0] for h in portal.HELP}
        self.assertEqual(PIN_HELP, got)


class RouteMatrixTests(unittest.TestCase):
    def test_every_route_for_every_identity(self):
        for ident in IDENTITIES:
            groups = groups_of(ident)
            for route in ROUTES:
                if route in MATRIX_SKIP:
                    continue
                want_status, want_loc = expected(route, groups)
                with self.subTest(ident=ident, route=route):
                    r = fetch(ident, route)
                    self.assertEqual(want_status, r.status)
                    self.assertEqual(want_loc, r.location)
                    self.assertNotEqual(403, r.status)

    def test_status_is_only_200_307_or_404_and_never_403(self):
        for ident in IDENTITIES:
            for route in ROUTES:
                with self.subTest(ident=ident, route=route):
                    self.assertIn(fetch(ident, route).status, (200, 307, 404))

    def test_denied_responses_are_identical_to_unknown_paths(self):
        """A withheld service is indistinguishable from a path that never existed."""
        for ident in IDENTITIES:
            groups = groups_of(ident)
            baseline = fetch(ident, "/definitely-not-a-route")
            self.assertEqual(404, baseline.status)
            for route in SERVICE_ROUTES + CHOOSER_ROUTES + HELP_ROUTES:
                if route in MATRIX_SKIP or expected(route, groups)[0] != 404:
                    continue
                with self.subTest(ident=ident, route=route):
                    r = fetch(ident, route)
                    self.assertEqual(baseline.body, r.body)
                    self.assertEqual(sorted(h for h in baseline.headers if h[0] != 'Date'), sorted(h for h in r.headers if h[0] != 'Date'))

    def test_tuple_gated_shelfarr_route(self):
        for ident, allowed in [("books", True), ("audiobooks", True), ("all_members", True),
                               ("videos", False), ("comics", False), ("contributors", False),
                               ("admin_only", False), ("no_header", False), ("empty_header", False)]:
            with self.subTest(ident=ident):
                r = fetch(ident, "/requestabook")
                if allowed:
                    self.assertEqual((307, "https://requestabook.avrana.net"), (r.status, r.location))
                else:
                    self.assertEqual(404, r.status)

    def test_comics_goes_to_sso_init_not_service_root(self):
        r = fetch("comics", "/comics")
        self.assertEqual("https://read.avrana.net/oauth2/authorization/authentik", r.location)

    def test_watch_is_an_interstitial_not_a_redirect(self):
        r = fetch("videos", "/watch")
        self.assertEqual(200, r.status)
        self.assertIsNone(r.location)
        self.assertIn("https://watch.avrana.net", r.text)

    def test_admin_alone_has_no_member_access(self):
        for route in SERVICE_ROUTES + CHOOSER_ROUTES + HELP_ROUTES:
            if route == "/ops":
                continue
            with self.subTest(route=route):
                self.assertEqual(404, fetch("admin_only", route).status)
        self.assertEqual(307, fetch("admin_only", "/ops").status)

    def test_admin_group_gives_nothing_to_members_and_vice_versa(self):
        for ident in ("videos", "audiobooks", "comics", "books", "contributors", "all_members"):
            with self.subTest(ident=ident):
                self.assertEqual(404, fetch(ident, "/ops").status)

    def test_home_tiles_pinned_per_identity(self):
        for ident, want in PIN_HOME.items():
            with self.subTest(ident=ident):
                self.assertEqual(want, tile_paths(fetch(ident, "/").text))

    def test_help_index_lists_exactly_permitted_topics(self):
        for ident in IDENTITIES:
            groups = groups_of(ident)
            want = {s for s, g in PIN_HELP.items() if g in groups}
            with self.subTest(ident=ident):
                got = {p.split("/", 1)[1] for p in tile_paths(fetch(ident, "/help").text)}
                self.assertEqual(want, got)

    def test_chooser_pages_list_only_permitted_members(self):
        want = {"read": {"videos": None, "comics": {"comics"}, "books": {"books", "kindle"},
                         "all_members": {"comics", "books", "kindle"}},
                "request": {"videos": {"requests"}, "audiobooks": {"requestabook"},
                            "books": {"requestabook"}, "comics": {"requestacomic"},
                            "all_members": {"requests", "requestabook", "requestacomic"}}}
        for chooser, cases in want.items():
            for ident, members in cases.items():
                with self.subTest(chooser=chooser, ident=ident):
                    r = fetch(ident, "/" + chooser)
                    if members is None:
                        self.assertEqual(404, r.status)
                    else:
                        self.assertEqual(members, set(tile_paths(r.text)))

    def test_healthz_needs_no_identity(self):
        for ident in IDENTITIES:
            r = fetch(ident, "/healthz")
            self.assertEqual((200, b"ok"), (r.status, r.body))
        r = request("/healthz", host=None, version="HTTP/1.0")
        self.assertEqual(200, r.status)


class VariantTests(unittest.TestCase):
    """Trailing slashes, queries and fragments resolve to the same decision as the clean route."""

    @staticmethod
    def variants(route):
        base = "" if route == "/" else route
        return [base + "/", base + "?q=1", base + "/?q=1", base + "//", base + "#frag",
                base + "/?next=https://evil.example"] if base else ["/?q=1", "//", "/#frag"]

    def test_variants_match_clean_route(self):
        idents = ["no_header", "books", "all_members", "admin_only"]
        routes = [r for r in ROUTES if r not in UNKNOWN_ROUTES[1:]]
        for ident in idents:
            groups = groups_of(ident)
            for route in routes:
                if route in MATRIX_SKIP:
                    continue
                for v in self.variants(route):
                    with self.subTest(ident=ident, target=v):
                        r = fetch(ident, v)
                        clean = route if route != "/healthz" else route
                        want_status, want_loc = expected(clean, groups)
                        self.assertEqual((want_status, want_loc), (r.status, r.location))

    def test_head_matches_get_and_has_no_body(self):
        for ident in ("no_header", "videos", "books", "all_members", "admin_only"):
            for route in ROUTES:
                if route in MATRIX_SKIP:
                    continue
                with self.subTest(ident=ident, route=route):
                    g = fetch(ident, route)
                    h = fetch(ident, route, method="HEAD")
                    self.assertEqual(g.status, h.status)
                    self.assertEqual(g.location, h.location)
                    self.assertEqual(b"", h.body)
                    self.assertEqual(g.header("Content-Length"), h.header("Content-Length"))

    def test_path_is_case_sensitive_and_not_percent_decoded(self):
        """Surprising but safe: only the literal lowercase path matches. Pinned, not a defect."""
        for target in ("/%77atch", "/watch%2f", "/watch%00", "/wat%63h", "/WATCH", "/Watch",
                       "/watch;x", "/watch/.", "/watch/../watch", "/./watch", "/watch%20",
                       "/watch\\", "/\\watch", "/help/%6dovies", "/ac%63ount"):
            with self.subTest(target=target):
                r = fetch("all_members", target)
                self.assertEqual(404, r.status)
                self.assertIsNone(r.location)


class HeaderFailClosedTests(unittest.TestCase):
    # Every gated decision rests on the same parsed group set, so a representative route per
    # group, per chooser and per help topic proves the set is empty.
    GATED = ["/watch", "/listen", "/comics", "/books", "/kindle", "/requests", "/requestabook",
             "/requestacomic", "/contribute", "/ops", "/read", "/request", "/help/audiobooks",
             "/help/movies", "/help/books", "/help/comics"]

    SPOT = ["/ops", "/requestabook", "/watch"]   # admin, tuple-gated, single-group

    def test_every_gated_route_refuses_an_empty_header(self):
        self.assert_no_access(with_groups(""), "empty", routes=self.GATED)

    def assert_no_access(self, headers, label, extra_ok_statuses=(), routes=None):
        """The request carried no usable group: nothing but the bare portal is reachable.
        The home grid, help index and account list are each built from the whole parsed group
        set, so together with a spot check of three gated routes they prove the set is empty."""
        routes = routes or self.SPOT
        replies = [request(rt, headers) for rt in routes]
        for route, r in zip(routes, replies):
            if r is None or r.status in extra_ok_statuses:
                continue
            self.assertEqual(404, r.status, f"{label}: {route}")
            self.assertIsNone(r.location, f"{label}: {route}")
        home = request("/", headers)
        if home is not None and home.status == 200:
            self.assertEqual(["help"], tile_paths(home.text), label)
            self.assertEqual([], tile_paths(request("/help", headers).text), label)
            acct = request("/account", headers).text
            self.assertEqual(0, len(re.findall(r"<li>", acct)), label)
            for tok in OPERATOR_TOKENS:
                self.assertNotIn(tok, home.text + acct, label)

    def test_absent_empty_and_blank(self):
        cases = {"absent": [], "empty": with_groups(""), "spaces": with_groups("    "),
                 "tab": with_groups("\t"), "separators only": with_groups("|,|,"),
                 "pipes with spaces": with_groups(" | | ")}
        for label, h in cases.items():
            with self.subTest(case=label):
                self.assert_no_access(h, label)

    def test_wrong_case_and_near_misses(self):
        values = ["AVRANA-VIDEOS", "Avrana-Videos", "avrana-Videos", "authentik admins",
                  "AUTHENTIK ADMINS", "Authentik Admins", "authentik  Admins", "authentik\tAdmins",
                  "authentik-Admins", "authentikAdmins", "Admins", "admin", "admins",
                  "avrana-video", "avrana-videos-x", "xavrana-videos", "avrana-videosx",
                  "avrana-videos.", "avrana-videos;", "avrana-videos:", "avrana-videos/",
                  "avrana videos", "avrana_videos", "avrana-audiobook", "avrana-comic",
                  "avrana-book", "library-contributor", "library_contributors",
                  "Library-Contributors", "*", "all", "true", "1", "avrana-*", "avrana-.*",
                  "avrana-users", "avrana-videos-x|xavrana-videos",
                  "video", "videos", "books", "ops", "ldap-service"]
        for v in values:
            with self.subTest(value=v):
                self.assert_no_access(with_groups(v), v)

    def test_unicode_lookalikes_and_hidden_characters(self):
        raw = [
            "avr\u0430na-videos".encode("utf-8"),             # Cyrillic a
            "\uff41vrana-videos".encode("utf-8"),             # fullwidth a
            "avrana\u2010videos".encode("utf-8"),             # hyphen U+2010
            "avrana\u2011videos".encode("utf-8"),             # non-breaking hyphen
            "avrana-videos\u200b".encode("utf-8"),            # zero-width space
            "\u200bavrana-videos".encode("utf-8"),
            "avrana-vide\u043es".encode("utf-8"),             # Cyrillic o
            "authentik \u0410dmins".encode("utf-8"),          # Cyrillic A
            "authentik\xa0Admins".encode("utf-8"),          # NBSP inside the name
            "authentik Admins\u2028".encode("utf-8"),         # line separator
            "\u212aindle".encode("utf-8"),
            b"avrana-videos\xff",                             # invalid byte
            b"\xefavrana-videos",
        ]
        for v in raw:
            with self.subTest(value=v):
                self.assert_no_access([(GROUPS_HEADER, v)], repr(v))

    def test_overlong_values(self):
        junk = ",".join(f"g{i}" for i in range(6000))                 # ~40 KB of unknown groups
        self.assert_no_access(with_groups(junk), "many unknown groups")
        self.assert_no_access(with_groups("x" * 60000), "one 60 KB group")
        # Over http.server's 64 KiB line limit the request is refused outright (431 or a reset).
        r = request("/", with_groups("avrana-videos|" + "x" * 70000))
        self.assertEqual(431, r.status)
        self.assertNotIn("tile", r.text)

    def test_long_value_with_a_real_group_still_parses(self):
        """Pinned: length alone neither grants nor strips a genuine group."""
        junk = "|".join(f"g{i}" for i in range(5000))
        r = request("/watch", with_groups(junk + "|avrana-videos"))
        self.assertEqual(200, r.status)
        r = request("/ops", with_groups(junk + "|avrana-videos"))
        self.assertEqual(404, r.status)

    def test_spoof_headers_are_ignored(self):
        spoofs = ["X-Forwarded-Groups", "X-Groups", "Remote-Groups", "X-Authentik-Group",
                  "X-authentik-groups-x", "X-Auth-Groups", "X-Forwarded-User", "X-Authentik-Admin",
                  "X-Real-Groups", "Groups", "X-authentik-uid", "X_authentik_groups",
                  "X-authentik-groups\t", "X-HTTP-Method-Override"]
        for name in spoofs:
            with self.subTest(header=name):
                self.assert_no_access([(name, ADMIN + "|" + VIDEOS)], name)

    def test_spoof_headers_do_not_augment_a_real_header(self):
        h = [(GROUPS_HEADER, VIDEOS), ("X-Forwarded-Groups", ADMIN), ("X-Groups", BOOKS),
             ("X-authentik-username", ADMIN)]
        self.assertEqual(404, request("/ops", h).status)
        self.assertEqual(404, request("/books", h).status)
        self.assertEqual(200, request("/watch", h).status)

    def test_group_names_in_other_identity_headers_grant_nothing(self):
        h = [("X-authentik-name", ADMIN), ("X-authentik-username", VIDEOS),
             ("X-authentik-email", "avrana-videos@example.test")]
        self.assert_no_access(h, "identity headers only")

    def test_group_header_name_is_case_insensitive(self):
        """HTTP header names are; the outpost's casing must not matter. Pinned."""
        for name in ("x-authentik-groups", "X-AUTHENTIK-GROUPS", "X-Authentik-Groups"):
            with self.subTest(header=name):
                self.assertEqual(200, request("/watch", [(name, VIDEOS)]).status)

    def test_group_names_are_matched_exactly_not_by_substring(self):
        h = with_groups("xavrana-videos|avrana-videos-x|avrana-video")
        self.assertEqual(404, request("/watch", h).status)
        self.assertEqual(["help"], tile_paths(request("/", h).text))
        h = with_groups("xavrana-videos|avrana-videos|avrana-videos-x")
        self.assertEqual(200, request("/watch", h).status)
        self.assertEqual(404, request("/listen", h).status)

    # --- duplicated headers -------------------------------------------------------------

    def test_second_group_header_never_adds_groups(self):
        """Whichever order the two arrive in, the second never adds groups (see also
        test_duplicated_group_headers_fail_closed, which is stricter)."""
        for h in ([(GROUPS_HEADER, VIDEOS), (GROUPS_HEADER, ADMIN)],
                  [(GROUPS_HEADER, VIDEOS), (GROUPS_HEADER, BOOKS)]):
            self.assertEqual(404, request("/ops", h).status)
            self.assertEqual(404, request("/books", h).status)

    def test_crlf_injected_second_header_never_adds_groups(self):
        wire = (b"GET /ops HTTP/1.1\r\nHost: portal.test\r\nConnection: close\r\n"
                b"X-authentik-groups: avrana-videos\r\nX-authentik-groups: authentik Admins\r\n\r\n")
        self.assertEqual(404, send_raw(wire).status)
        wire = (b"GET /ops HTTP/1.1\r\nHost: portal.test\r\nConnection: close\r\n"
                b"X-authentik-groups: avrana-videos\r\n\r\nX-authentik-groups: authentik Admins\r\n\r\n")
        self.assertEqual(404, send_raw(wire).status)

    def test_duplicated_group_headers_fail_closed(self):
        """Two group headers are ambiguous, and which one is genuine depends on how the outpost
        merges client headers. Fail closed: grant nothing in either order."""
        for first, second in [(VIDEOS, ADMIN), (ADMIN, VIDEOS), (VIDEOS, VIDEOS), (ADMIN, ADMIN),
                              (VIDEOS, "")]:
            with self.subTest(first=first, second=second):
                h = [(GROUPS_HEADER, first), (GROUPS_HEADER, second)]
                self.assert_no_access(h, f"{first!r}+{second!r}")
                h = [(GROUPS_HEADER, first), ("x-AUTHENTIK-groups", second)]
                self.assert_no_access(h, f"mixed case {first!r}+{second!r}")

    # --- tolerance that is deliberate (parse_groups docstring) -----------------------------

    def test_documented_separator_tolerance(self):
        """Pinned: '|' (Authentik), ',' and whitespace around names are accepted separators."""
        for value in ("avrana-videos|avrana-books", "avrana-videos,avrana-books",
                      " avrana-videos | avrana-books ", ",avrana-videos,,avrana-books,",
                      "|avrana-videos|avrana-books|", "avrana-videos, avrana-books"):
            with self.subTest(value=value):
                h = with_groups(value)
                self.assertEqual(200, request("/watch", h).status)
                self.assertEqual(307, request("/books", h).status)
                self.assertEqual(404, request("/listen", h).status)
                self.assertEqual(404, request("/ops", h).status)

    def test_surprising_but_safe_normalisation(self):
        """Pinned, not fixed: str.strip() also removes NBSP and U+0085 from the edges of a name.
        This cannot widen access beyond the exact names already present in the header."""
        for value in ("avrana-videos\xa0", "\xa0avrana-videos", "avrana-videos\u0085"):
            with self.subTest(value=value):
                h = [(GROUPS_HEADER, value.encode("latin-1"))]
                self.assertEqual(200, request("/watch", h).status)
                self.assertEqual(404, request("/ops", h).status)

    def test_obsolete_line_folding_splits_like_a_separator(self):
        """Pinned, not fixed: a folded header value contains a newline, which parse_groups treats as
        a separator. Whoever can fold a header can equally write '|', so nothing is gained."""
        wire = (b"GET /books HTTP/1.1\r\nHost: portal.test\r\nConnection: close\r\n"
                b"X-authentik-groups: avrana-videos\r\n avrana-books\r\n\r\n")
        self.assertEqual(307, send_raw(wire).status)
        wire = wire.replace(b"/books", b"/ops")
        self.assertEqual(404, send_raw(wire).status)

    def test_header_without_value_and_header_with_only_a_name(self):
        wire = (b"GET /watch HTTP/1.1\r\nHost: portal.test\r\nConnection: close\r\n"
                b"X-authentik-groups:\r\n\r\n")
        self.assertEqual(404, send_raw(wire).status)


class RedirectTests(unittest.TestCase):
    CRAFTED = [
        "//evil.example", "///evil.example", "//evil.example/watch", "/watch//evil.example",
        "/%2f%2fevil.example", "/%2F%2Fevil.example", "/requests/../ops", "/requests/%2e%2e/ops",
        "/watch/%2e%2e/ops", "/watch%2f%2fevil.example", "/watch%0d%0aLocation:%20https://evil.example",
        "/\\evil.example", "/watch\\evil.example", "\\\\evil.example", "/watch/https://evil.example",
        "/https://evil.example", "http://evil.example/watch", "http://evil.example/", "https://evil.example",
        "http://evil.example", "//watch", "//listen", "/ops/..//evil.example",
        "/@evil.example", "/watch@evil.example", "/.evil.example",
        "/%00", "/watch%00", "/;evil.example", "/watch;https://evil.example",
    ]
    # Query strings and fragments are ignored, so these are the SAME request as the clean route.
    QUERY_TARGETS = [("/watch?next=https://evil.example", "/watch"),
                     ("/watch?redirect=//evil.example", "/watch"),
                     ("/comics?continue=https://evil.example", "/comics"),
                     ("/books#https://evil.example", "/books"),
                     ("/listen?url=//evil.example/x", "/listen"),
                     ("/ops?next=https://evil.example", "/ops"),
                     ("/read?x=1", "/read")]
    IDENTS = ["all_members", "admin_and_all", "books", "no_header"]

    def test_query_and_fragment_never_change_the_decision_or_target(self):
        for ident in self.IDENTS:
            for target, clean in self.QUERY_TARGETS:
                with self.subTest(ident=ident, target=target):
                    r = fetch(ident, target)
                    self.assertEqual(expected(clean, groups_of(ident)), (r.status, r.location))
                    self.assertNotIn("evil.example", r.text)

    def test_every_location_is_exactly_a_table_value(self):
        for ident in self.IDENTS:
            for route in ROUTES:
                r = fetch(ident, route)
                if r.status == 307:
                    with self.subTest(ident=ident, route=route):
                        self.assertIn(r.location, ALL_LOCATIONS)
                        self.assertEqual(1, len(r.all("Location")))
                        self.assertEqual(b"", r.body)

    def test_crafted_targets_never_escape_the_table(self):
        for ident in self.IDENTS:
            for target in self.CRAFTED + [t for t, _c in self.QUERY_TARGETS]:
                with self.subTest(ident=ident, target=target):
                    r = fetch(ident, target)
                    self.assertIn(r.status, (200, 307, 404))
                    if r.status == 307:
                        self.assertIn(r.location, ALL_LOCATIONS)
                    self.assertNotIn("evil.example", r.location or "")
                    self.assertNotIn("evil.example", r.text)

    def test_crafted_targets_that_match_no_route_are_404(self):
        # '//watch' is the one deliberate exception: Python 3.12's request parser collapses leading
        # slashes, so it is the same request as '/watch' (or a 404 on older Pythons). Never more.
        for ident in self.IDENTS:
            for target in self.CRAFTED:
                if target in ("//watch", "//listen"):
                    continue
                with self.subTest(ident=ident, target=target):
                    self.assertEqual(404, fetch(ident, target).status)

    def test_collapsed_leading_slashes_grant_no_more_than_the_clean_path(self):
        for ident in IDENTITIES:
            groups = groups_of(ident)
            for clean in ("/watch", "/listen", "/ops", "/account"):
                r = fetch(ident, "/" + clean)
                want = expected(clean, groups)
                with self.subTest(ident=ident, path="/" + clean):
                    self.assertIn((r.status, r.location), [want, (404, None)])

    def test_host_and_forwarding_headers_do_not_influence_location(self):
        spoof = [
            [],
            [("X-Forwarded-Host", "evil.example")],
            [("X-Forwarded-Proto", "http"), ("X-Forwarded-For", "203.0.113.9")],
            [("X-Forwarded-Host", "evil.example"), ("X-Original-URL", "https://evil.example/")],
            [("Referer", "https://evil.example/"), ("Origin", "https://evil.example")],
            [("Forwarded", "host=evil.example;proto=https")],
        ]
        hosts = ["evil.example", "watch.avrana.net@evil.example", "evil.example:80", "", "avrana.net",
                 "localhost", "[::1]", "a b"]
        for h in hosts:
            for extra in spoof:
                for route, want in [("/listen", "https://listen.avrana.net"),
                                    ("/comics", "https://read.avrana.net/oauth2/authorization/authentik"),
                                    ("/ops", "https://ops.avrana.net")]:
                    with self.subTest(host=h, extra=extra, route=route):
                        r = request(route, ident_headers("admin_and_all") + extra, host=h)
                        self.assertIsNotNone(r)
                        if r.status == 400:   # a malformed Host is refused by http.server itself
                            continue
                        self.assertEqual((307, want), (r.status, r.location))
        r = request("/watch", ident_headers("videos"), host="evil.example")
        self.assertNotIn("evil.example", r.text)

    def test_request_input_is_never_reflected_in_a_page(self):
        for ident in ("no_header", "all_members"):
            for target in ("/<script>alert(1)</script>", "/help/<img src=x onerror=1>",
                           "/watch?x=<script>", "/%3Cscript%3E"):
                with self.subTest(ident=ident, target=target):
                    r = fetch(ident, target)
                    self.assertNotIn("<script>alert", r.text)
                    self.assertNotIn("<img", r.text)   # (http.server's own 400 page echoes escaped)
                    self.assertNotIn("%3Cscript", r.text)


class LeakTests(unittest.TestCase):
    @staticmethod
    def tokens_for(groups):
        """(allowed_tokens, forbidden_tokens) derived from the portal's own tables, with the
        decision of what is allowed taken from the PINNED tables."""
        allowed, withheld = set(), set()
        for _g, label, desc, path, host in portal.SERVICES:
            bucket = allowed if PIN_SERVICES[path][0] & groups else withheld
            bucket.update({html.unescape(label), html.unescape(desc), host, f'href="/{path}"'})
        for ch in portal.CHOOSERS:
            bucket = allowed if PIN_CHOOSERS[ch[2]] & groups else withheld
            bucket.add(f'href="/{ch[2]}"')   # subtitles: see DefectTests
        for _g, label, host, _p in portal.HELP:
            slug = portal.HELP_SLUGS[label]
            bucket = allowed if PIN_HELP[slug] in groups else withheld
            bucket.update({label, host, f'href="/help/{slug}"'})
        return allowed, withheld - allowed

    def pages(self, ident):
        out = {}
        for route in ROUTES + ["/definitely-not-a-route", "/ops/", "/watch/"]:
            r = fetch(ident, route)
            if r.status in (200, 404) and r.body and route != "/healthz":
                out[route] = html.unescape(r.text)
        return out

    def test_no_page_mentions_a_service_outside_the_groups(self):
        for ident in IDENTITIES:
            groups = groups_of(ident)
            _allowed, withheld = self.tokens_for(groups)
            self.assertTrue(withheld or ident == "admin_and_all" or ident == "all_members")
            for route, text in self.pages(ident).items():
                if route in MATRIX_SKIP or (ident, route) in LEAK_SKIP:
                    continue
                for tok in withheld:
                    with self.subTest(ident=ident, route=route, token=tok):
                        self.assertNotIn(tok, text)

    def test_leak_check_is_not_vacuous(self):
        """The token sets must actually see content that IS allowed, or the test proves nothing."""
        allowed, withheld = self.tokens_for(groups_of("all_members"))
        self.assertIn('href="/watch"', allowed)
        self.assertIn("ops.avrana.net", withheld)
        page = html.unescape(fetch("all_members", "/").text)
        self.assertIn('href="/watch"', page)
        _a, withheld_v = self.tokens_for(groups_of("videos"))
        for tok in ("listen.avrana.net", 'href="/listen"', "Audiobooks", "Contribute", "ops.avrana.net"):
            self.assertIn(tok, withheld_v)
        # Seed a known leak: the videos home must NOT contain these, and the all-members home does.
        self.assertIn('href="/listen"', html.unescape(fetch("all_members", "/").text))
        self.assertNotIn('href="/listen"', html.unescape(fetch("videos", "/").text))

    def test_members_and_anonymous_never_see_the_operator_surface(self):
        for ident in IDENTITIES:
            if ADMIN in groups_of(ident):
                continue
            for route, text in self.pages(ident).items():
                for tok in OPERATOR_TOKENS:
                    with self.subTest(ident=ident, route=route, token=tok):
                        self.assertNotIn(tok, text)

    def test_admin_sees_operations_on_home_and_account_only_where_expected(self):
        self.assertIn('href="/ops"', fetch("admin_only", "/").text)
        self.assertIn("Operations", fetch("admin_only", "/account").text)
        self.assertNotIn("Operations", fetch("admin_only", "/help").text)

    def test_member_pages_mention_only_their_own_help_hosts(self):
        for ident, want_hosts in [("audiobooks", {"listen.avrana.net"}), ("videos", {"watch.avrana.net"}),
                                  ("comics", {"read.avrana.net"})]:
            for slug in PIN_HELP:
                r = fetch(ident, "/help/" + slug)
                if r.status != 200:
                    continue
                found = set(re.findall(r"[a-z]+\.avrana\.net", r.text))
                with self.subTest(ident=ident, slug=slug):
                    self.assertLessEqual(found - {"auth.avrana.net"}, want_hosts | {"request.avrana.net"})


class DefectTests(unittest.TestCase):
    """Proven departures from the fail-closed / no-leak principle. Each is also reported."""

    def test_requests_help_follows_the_video_group_not_a_retired_one(self):
        """/help/requests is gated on `avrana-requests`, a group no service uses any more. A holder
        of only that group is shown Seerr's help and hostname (request.avrana.net) although the
        Seerr route itself 404s for them; a video member without the retired group is refused
        help for a service they can use."""
        self.assertEqual(404, fetch("legacy_requests", "/requests").status)
        self.assertEqual(404, fetch("legacy_requests", "/help/requests").status)
        self.assertNotIn("request.avrana.net", fetch("legacy_requests", "/help/requests").text)
        self.assertNotIn("/help/requests", fetch("legacy_requests", "/help").text)
        self.assertEqual(200, fetch("videos", "/help/requests").status)
        self.assertIn("/help/requests", fetch("videos", "/help").text)

    @unittest.expectedFailure  # AVR-352 defect 4: copy change owned by the UI team, not fixed here
    def test_read_chooser_subtitle_does_not_name_the_other_library(self):
        """The home tile for the Read chooser reads 'Comics & ebooks' for everyone who sees it, so a
        member with only books is told a comics library exists, and one with only comics is told of
        ebooks. CHOOSERS' own comment on Request says to keep subtitles media-agnostic."""
        self.assertNotIn("Comics", html.unescape(fetch("books", "/").text))
        self.assertNotIn("ebooks", html.unescape(fetch("comics", "/").text))


class AccountTests(unittest.TestCase):
    XSS = {
        "X-authentik-name": "<script>alert('n')</script>",
        "X-authentik-username": '"><img src=x onerror=alert(1)>',
        "X-authentik-email": "a@example.test\"><svg onload=alert(2)>",
    }

    def test_identity_headers_are_html_escaped(self):
        r = request("/account", list(self.XSS.items()) + ident_headers("videos"))
        self.assertEqual(200, r.status)
        for payload in self.XSS.values():
            self.assertNotIn(payload, r.text)
        for needle in ("<script>", "<img src=x", "<svg onload", 'onerror=alert(1)>"'):
            self.assertNotIn(needle, r.text)
        self.assertIn("&lt;script&gt;", r.text)
        self.assertIn("&quot;&gt;&lt;img src=x onerror=alert(1)&gt;", r.text)

    def test_ampersand_and_quote_are_escaped(self):
        r = request("/account", [("X-authentik-name", 'A & B "C" <D>')])
        self.assertIn("A &amp; B &quot;C&quot; &lt;D&gt;", r.text)

    def test_other_pages_do_not_echo_identity_headers(self):
        h = list(self.XSS.items()) + ident_headers("all_members")
        for route in ("/", "/help", "/read", "/request", "/watch", "/nope", "/help/movies"):
            r = request(route, h)
            with self.subTest(route=route):
                for payload in self.XSS.values():
                    self.assertNotIn(payload, r.text)
                self.assertNotIn("alert(", r.text)
                self.assertNotIn("member-a", r.text)

    def test_identity_headers_confer_no_access(self):
        r = request("/account", [("X-authentik-name", "Member A"), ("X-authentik-username", ADMIN)])
        self.assertEqual(0, len(re.findall(r"<li>", r.text)))

    def test_account_lists_exactly_permitted_services(self):
        for ident in IDENTITIES:
            groups = groups_of(ident)
            want = sum(1 for need, _t in PIN_SERVICES.values() if need & groups)
            with self.subTest(ident=ident):
                self.assertEqual(want, len(re.findall(r"<li>", fetch(ident, "/account").text)))

    def test_missing_identity_renders_without_error(self):
        r = fetch("no_header", "/account")
        self.assertEqual(200, r.status)
        self.assertNotIn("None", r.text)

    def test_concurrent_requests_never_cross_identities(self):
        a = MEMBER_A
        b = MEMBER_B

        def hdrs(m):
            return [(GROUPS_HEADER, "|".join(m["groups"])), ("X-authentik-name", m["name"]),
                    ("X-authentik-username", m["username"]), ("X-authentik-email", m["email"])]

        jobs = []
        for i in range(60):
            m = a if i % 2 == 0 else b
            jobs.append((m, "/account" if i % 3 else "/"))
        barrier = threading.Barrier(6, timeout=20)

        def run(job):
            m, route = job
            try:
                barrier.wait(timeout=0.5)
            except threading.BrokenBarrierError:
                pass
            return m, route, request(route, hdrs(m), live=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(run, jobs))
        self.assertEqual(60, len(results))
        for m, route, r in results:
            other = b if m is a else a
            with self.subTest(member=m["username"], route=route):
                self.assertIsNotNone(r)
                self.assertEqual(200, r.status)
                text = r.text
                for k in ("name", "username", "email"):
                    self.assertNotIn(other[k], text)
                if route == "/account":
                    self.assertIn(m["email"], text)
                    self.assertIn(m["username"], text)
                    want_n = sum(1 for need, _t in PIN_SERVICES.values()
                                 if need & set(m["groups"]))
                    self.assertEqual(want_n, len(re.findall(r"<li>", text)))
                else:
                    want = ["watch", "request", "help"] if m is a else ["read", "request", "help"]
                    self.assertEqual(want, tile_paths(text))


class LiveServerTests(unittest.TestCase):
    """End to end over real loopback connections: a representative route from every route class
    against every identity class (~200 connections; the bulk of the suite runs the same Handler
    in memory). Each live reply must equal the in-memory reply and the pinned expectation."""

    LIVE_ROUTES = ["/", "/account", "/help", "/help/books", "/help/requests", "/read", "/request",
                   "/watch", "/listen", "/comics", "/requestabook", "/ops", "/healthz", "/nope"]

    def test_live_replies_match_in_memory_and_pins(self):
        for ident in IDENTITIES:
            groups = groups_of(ident)
            for route in self.LIVE_ROUTES:
                with self.subTest(ident=ident, route=route):
                    live = request(route, ident_headers(ident), live=True)
                    mem = fetch(ident, route)
                    self.assertEqual((live.status, live.location, live.body),
                                     (mem.status, mem.location, mem.body))
                    self.assertEqual(expected(route, groups), (live.status, live.location))
                    for k, v in HygieneTests.REQUIRED.items():
                        self.assertEqual([v], live.all(k))

    def test_live_head_matches_get(self):
        for ident in ("no_header", "videos", "admin_and_all"):
            for route in ("/", "/watch", "/ops", "/nope"):
                with self.subTest(ident=ident, route=route):
                    g = request(route, ident_headers(ident), live=True)
                    h = request(route, ident_headers(ident), method="HEAD", live=True)
                    self.assertEqual((g.status, g.location), (h.status, h.location))
                    self.assertEqual(b"", h.body)

    def test_live_duplicate_headers_and_unsupported_method(self):
        r = request("/ops", [(GROUPS_HEADER, ADMIN), (GROUPS_HEADER, ADMIN)], live=True)
        self.assertEqual(404, r.status)
        r = request("/ops", ident_headers("admin_only"), method="POST", live=True)
        self.assertEqual(501, r.status)
        for k, v in HygieneTests.REQUIRED.items():
            self.assertEqual([v], r.all(k))

    def test_server_speaks_http_1_0_and_answers_only_the_first_pipelined_request(self):
        """Isolation between requests on one connection relies on the connection closing after
        each reply. Two pipelined requests with different identities: only the first is answered
        and the second identity never receives anything."""
        self.assertEqual("HTTP/1.0", portal.Handler.protocol_version)
        first = (b"GET /watch HTTP/1.1\r\nHost: portal.test\r\nX-authentik-groups: avrana-videos\r\n"
                 b"X-authentik-username: member-a\r\n\r\n")
        second = (b"GET /account HTTP/1.1\r\nHost: portal.test\r\nX-authentik-groups: authentik Admins\r\n"
                  b"X-authentik-username: member-b\r\n\r\n")
        for live in (True, False):
            data = _exchange_live(first + second) if live else _exchange_in_process(first + second)
            with self.subTest(live=live):
                self.assertTrue(data.startswith(b"HTTP/1.0 200"))
                self.assertEqual(1, data.count(b"HTTP/1."))
                self.assertNotIn(b"member-b", data)

    @unittest.expectedFailure  # AVR-352 follow-up; remove with the Handler.timeout fix
    def test_handler_has_a_socket_timeout(self):
        """A half-sent request must not pin a handler thread forever."""
        self.assertIsNotNone(portal.Handler.timeout)
        self.assertLessEqual(portal.Handler.timeout, 60)

    def test_stalled_request_is_dropped_by_the_server(self):
        class Short(portal.Handler):
            timeout = 0.5

        srv = _Server(("127.0.0.1", 0), Short)
        t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        t.start()
        try:
            started = time.monotonic()
            with socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5) as s:
                s.sendall(b"GET /watch HTT")        # request line never finished
                data = s.recv(4096)                  # blocks until the server gives up
            self.assertEqual(b"", data)
            self.assertLess(time.monotonic() - started, 4)
        finally:
            srv.shutdown()
            srv.server_close()
            t.join(timeout=5)


class PureFunctionTests(unittest.TestCase):
    def test_parse_groups(self):
        pg = portal.parse_groups
        self.assertEqual(set(), pg(""))
        self.assertEqual(set(), pg("  \t "))
        self.assertEqual({"a", "b", "c"}, pg("a|b,c"))
        self.assertEqual({"authentik Admins"}, pg("authentik Admins"))   # inner space preserved
        self.assertEqual({"a b"}, pg("a b"))
        self.assertEqual({"A"}, pg("A"))                                 # case preserved
        self.assertEqual({"a", "b"}, pg("a\nb"))

    def test_allows(self):
        al = portal.allows
        self.assertTrue(al("g", {"g"}))
        self.assertFalse(al("g", set()))
        self.assertFalse(al("g", {"G"}))
        self.assertFalse(al("g", {"gg"}))
        self.assertFalse(al("g", {"xg"}))
        self.assertTrue(al(("g", "h"), {"h"}))
        self.assertTrue(al(["g", "h"], {"g"}))
        self.assertFalse(al(("g", "h"), {"i"}))
        self.assertFalse(al(("g", "h"), set()))
        self.assertFalse(al((), {"g"}))

    def test_permitted_and_chooser_members_follow_pins(self):
        for ident in IDENTITIES:
            groups = groups_of(ident)
            got = {s[3] for s in portal.permitted(groups)}
            want = {p for p, (need, _t) in PIN_SERVICES.items() if need & groups}
            with self.subTest(ident=ident):
                self.assertEqual(want, got)
                for ch in portal.CHOOSERS:
                    members = {m[3] for m in portal.chooser_members(ch, groups)}
                    self.assertLessEqual(members, set(ch[3]))
                    self.assertEqual(bool(PIN_CHOOSERS[ch[2]] & groups), bool(members))

    def test_empty_groups_permit_nothing(self):
        self.assertEqual([], portal.permitted(set()))
        self.assertEqual([], portal.help_permitted(set()))
        for ch in portal.CHOOSERS:
            self.assertEqual([], portal.chooser_members(ch, set()))

    def test_lookups_reject_unknown_and_non_string_keys(self):
        self.assertIsNone(portal.by_path("nope"))
        self.assertIsNone(portal.by_path(""))
        self.assertIsNone(portal.chooser_by_path("watch"))
        self.assertIsNone(portal.help_by_slug(""))
        self.assertIsNone(portal.help_by_slug("Movies"))


class HygieneTests(unittest.TestCase):
    REQUIRED = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff"}

    def check(self, r, label):
        for k, v in self.REQUIRED.items():
            self.assertEqual([v], r.all(k), f"{label}: {k}")

    def test_hygiene_headers_on_every_matrix_response(self):
        for ident in IDENTITIES:
            for route in ROUTES:
                for method in ("GET", "HEAD"):
                    with self.subTest(ident=ident, route=route, method=method):
                        self.check(fetch(ident, route, method), f"{method} {route}")

    def test_body_framing(self):
        for ident in ("no_header", "all_members"):
            for route in ROUTES:
                r = fetch(ident, route)
                with self.subTest(ident=ident, route=route):
                    self.assertEqual(str(len(r.body)), r.header("Content-Length"))
                    ctype = r.header("Content-Type")
                    self.assertTrue(ctype.startswith("text/"), ctype)
                    self.assertIn("charset=utf-8", ctype)

    def test_pages_carry_noindex(self):
        for route in ("/", "/account", "/help", "/nope"):
            self.assertIn('name="robots" content="noindex, nofollow"', fetch("all_members", route).text)

    def test_unsupported_methods_are_refused_without_a_decision(self):
        """Recorded behaviour: http.server answers 501 for any method without a do_ handler, for
        every identity and every path, before any group is looked at. Identical for admin and
        anonymous, so it reveals nothing about what exists."""
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "FOO", "get", "PROPFIND"):
            for route in ("/", "/ops", "/watch", "/account", "/nope", "/healthz"):
                bodies = set()
                for ident in ("no_header", "admin_and_all"):
                    r = request(route, ident_headers(ident), method=method)
                    with self.subTest(method=method, route=route, ident=ident):
                        self.assertEqual(501, r.status)
                        self.assertIsNone(r.location)
                        bodies.add(re.sub(r"\s+", " ", r.text).replace(route, "<r>"))
                with self.subTest(method=method, route=route, differential="body"):
                    self.assertEqual(1, len(bodies))

    def test_post_with_body_changes_nothing(self):
        r = request("/ops", ident_headers("admin_and_all"), method="POST", body=b"groups=authentik+Admins")
        self.assertEqual(501, r.status)
        self.assertEqual(200, fetch("no_header", "/").status)

    def test_method_name_is_escaped_in_error_page(self):
        r = request("/", method="X<script>alert(1)</script>")
        if r is not None:
            self.assertNotIn("<script>alert", r.text)

    def test_malformed_and_oversized_requests_are_refused(self):
        for wire in (b"GARBAGE\r\n\r\n", b"GET\r\n\r\n", b"GET / HTTP/9.9\r\n\r\n",
                     b"GET / HTTP/1.1\r\nHost: x\r\n" + b"X: " + b"a" * 70000 + b"\r\n\r\n",
                     b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\nHost: x\r\n\r\n"):
            with self.subTest(prefix=wire[:20]):
                r = send_raw(wire)
                if r is not None:
                    self.assertIn(r.status, (0, 400, 414, 431, 505))   # 0 = HTTP/0.9-style reply
                    self.assertNotIn("tile", r.text)

    def test_error_responses_carry_hygiene_headers(self):
        """http.server's own send_error() replies (here 501) bypass Handler._send, so the three
        security headers must be added at end_headers() to cover them too. (Replies to request
        lines too broken to parse are HTTP/0.9-style bare bodies with no headers at all.)"""
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS", "FOO"):
            with self.subTest(method=method):
                r = request("/", method=method)
                self.assertEqual(501, r.status)
                self.check(r, method)


if __name__ == "__main__":
    unittest.main()
