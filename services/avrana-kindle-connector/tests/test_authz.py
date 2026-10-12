"""Authorization and isolation suite for the Kindle connector (Media 2.0 gate G2, item S1-2 / AVR-353).

Offline and standard library only. The real `Handler` is driven over a loopback HTTP server on
127.0.0.1 (port 0). Calibre-Web is a temporary SQLite file with a minimal `user` table and
Audiobookshelf is an in-memory fake that replaces `kindle.abs_call`. Every name, e-mail and Kindle
address below is synthetic. Nothing here touches a network other than loopback, Docker or a
credential.

Run: python -B -m unittest discover -s services/avrana-kindle-connector/tests -p test_authz.py
"""
import copy
import http.server
import importlib.util
import json
import os
import pathlib
import select
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse

# ---------------------------------------------------------------- module under test
_ENV = {"CWA_DB": os.path.join(tempfile.gettempdir(), "kindle-authz-never-created.db"),
        "ABS_URL": "http://abs.invalid", "ABS_API_KEY": "synthetic-test-key",
        "REQUIRED_GROUP": "avrana-books", "SENDER_ADDRESS": "sender@example.test"}
_saved_env = {k: os.environ.get(k) for k in _ENV}
os.environ.update(_ENV)
try:
    _spec = importlib.util.spec_from_file_location(
        "kindle_under_authz_test", pathlib.Path(__file__).resolve().parents[1] / "kindle.py")
    kindle = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = kindle
    _spec.loader.exec_module(kindle)
finally:
    for _k, _v in _saved_env.items():
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v


def _no_network(*a, **k):  # any real outbound call is a test bug
    raise AssertionError("test attempted a real network call")


kindle.urllib.request.urlopen = _no_network

SENDER = "sender@example.test"
GROUPS_OK = "avrana-users|avrana-books"

ADDR = {"a": "member_a_old@kindle.com", "b": "member_b_x1@kindle.com",
        "c": "admin_c_x1@kindle.com", "shared": "shared_x9@kindle.com"}
NEW_A = "member_a_new@kindle.com"
NEW_B = "member_b_new@kindle.com"

CWA_ROWS = [
    (1, "member-a", "a@example.test", ADDR["a"]),
    (2, "member-b", "b@example.test", ADDR["b"]),
    (3, "admin-c", "c@example.test", ADDR["c"]),
]


def abs_user(uid, username, email):
    return {"id": uid, "username": username, "email": email}


def abs_device(name, email, users):
    return {"name": name, "email": email, "availabilityOption": "specificUsers", "users": list(users)}


ABS_USERS = [abs_user("abs-u-a", "member-a", "a@example.test"),
             abs_user("abs-u-b", "member-b", "b@example.test"),
             abs_user("abs-u-c", "admin-c", "c@example.test")]
ABS_DEVICES = [
    abs_device("Kindle (member-a)", ADDR["a"], ["abs-u-a"]),
    abs_device("Kindle (member-b)", ADDR["b"], ["abs-u-b"]),
    abs_device("Kindle (admin-c)", ADDR["c"], ["abs-u-c"]),
    {"name": "Shared Ereader", "email": ADDR["shared"], "availabilityOption": "adminOrUp", "users": []},
]


# ---------------------------------------------------------------- fakes
class FakeAbs:
    """In-memory Audiobookshelf: users, the global ereaderDevices array, a record of every PATCH."""

    def __init__(self, users, devices):
        self.users = copy.deepcopy(users)
        self.devices = copy.deepcopy(devices)
        self.patches = []
        self.calls = []
        self.fail_patch = False        # PATCH raises, reads still work
        self.dead_after_patch = False   # after a successful PATCH every call raises
        self.dead_after_failed_patch = False  # once a PATCH has failed, every call raises
        self._dead = False
        self.latency = 0.0             # seconds slept between reading and acting, outside the fake's lock
        self._lock = threading.Lock()

    def __call__(self, path, method="GET", body=None):
        if self.latency and path == "/api/emails/settings":
            snapshot = self._call(path, method, body)
            time.sleep(self.latency)
            if method == "PATCH":  # the write lands after the delay, like a slow network round trip
                return self._call(path, method, body, apply_delayed=True)
            return snapshot
        return self._call(path, method, body)

    def _call(self, path, method, body, apply_delayed=False):
        with self._lock:
            self.calls.append((method, path))
            if self._dead:
                raise urllib.error.URLError("fake ABS is down")
            if path == "/api/users" and method == "GET":
                return {"users": copy.deepcopy(self.users)}
            if path == "/api/emails/settings" and method == "GET":
                return {"settings": {"ereaderDevices": copy.deepcopy(self.devices)}}
            if path == "/api/emails/settings" and method == "PATCH":
                if self.latency and not apply_delayed:
                    return {}  # first half of a delayed PATCH: nothing applied yet
                if self.fail_patch:
                    self._dead = self.dead_after_failed_patch
                    raise urllib.error.URLError("fake ABS PATCH failure")
                assert set(body) == {"ereaderDevices"}, body
                self.patches.append(json.dumps(body))
                new = copy.deepcopy(body["ereaderDevices"])
                for d in new:  # real ABS coerces an empty specificUsers list to adminOrUp
                    if d.get("availabilityOption") == "specificUsers" and not d.get("users"):
                        d["availabilityOption"] = "adminOrUp"
                self.devices = new
                self._dead = self.dead_after_patch
                return {"settings": {"ereaderDevices": copy.deepcopy(new)}}
            raise AssertionError(f"unexpected ABS call {method} {path}")


class Resp:
    def __init__(self, status, headers, body, timed_out=False, version=None):
        self.status, self.headers, self.raw, self.timed_out = status, headers, body, timed_out
        self.version = version
        self.text = body.decode("utf-8", "replace")


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.errors = []

    def handle_error(self, request, client_address):  # keep tracebacks out of test output
        self.errors.append(sys.exc_info()[1])


def hdr(user="member-a", email="a@example.test", groups=GROUPS_OK):
    out = []
    if user is not None:
        out.append(("X-authentik-username", user))
    if email is not None:
        out.append(("X-authentik-email", email))
    if groups is not None:
        out.append(("X-authentik-groups", groups))
    return out


def form(address):
    return urllib.parse.urlencode({"address": address}).encode()


# ---------------------------------------------------------------- harness
class Base(unittest.TestCase):
    cwa_rows = CWA_ROWS
    abs_users = ABS_USERS
    abs_devices = ABS_DEVICES
    handler_timeout = None
    handler_attrs = {}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # a straggler handler thread may still hold the file
        self.addCleanup(tmp.cleanup)
        self.db = os.path.join(tmp.name, "app.db")
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE user (id INTEGER PRIMARY KEY, name TEXT, email TEXT, kindle_mail TEXT)")
        con.executemany("INSERT INTO user VALUES (?,?,?,?)", self.cwa_rows)
        con.commit()
        con.close()
        self.abs = FakeAbs(self.abs_users, self.abs_devices)
        saved = {n: getattr(kindle, n) for n in ("CWA_DB", "abs_call", "SENDER", "REQUIRED_GROUP")}
        kindle.CWA_DB, kindle.abs_call = self.db, self.abs
        kindle.SENDER, kindle.REQUIRED_GROUP = SENDER, "avrana-books"
        self.addCleanup(lambda: [setattr(kindle, n, v) for n, v in saved.items()])
        attrs = {"disable_nagle_algorithm": True}  # avoids a ~40 ms delayed-ACK stall per response
        attrs.update(self.handler_attrs)
        if self.handler_timeout is not None:
            attrs["timeout"] = self.handler_timeout
        self.handler_cls = type("TestHandler", (kindle.Handler,), attrs)
        self.server = Server(("127.0.0.1", 0), self.handler_cls)
        self.port = self.server.server_address[1]
        t = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        t.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), t.join(5)))

    # -- state
    def rows(self):
        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT id, name, email, kindle_mail FROM user ORDER BY id").fetchall()
        finally:
            con.close()

    def state(self):
        return (self.rows(), copy.deepcopy(self.abs.devices), list(self.abs.patches))

    def assertNoWrites(self, before, msg=None):
        self.assertEqual(before, self.state(), msg)

    # -- http
    def request(self, method, path, headers=(), body=b"", content_length="auto",
                half_close=False, timeout=5.0):
        lines = [f"{method} {path} HTTP/1.1".encode(), b"Host: 127.0.0.1"]
        for k, v in headers:
            lines.append(f"{k}: {v}".encode("latin-1"))
        if content_length == "auto":
            if body or method == "POST":
                lines.append(f"Content-Length: {len(body)}".encode())
        elif content_length is not None:
            lines.append(f"Content-Length: {content_length}".encode())
        data = b"\r\n".join(lines) + b"\r\n\r\n" + body
        try:
            s = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        except (ConnectionRefusedError, ConnectionResetError):  # one retry, at connect time only
            time.sleep(0.05)
            s = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        chunks, timed_out = [], False
        try:
            s.sendall(data)
            if half_close:
                s.shutdown(socket.SHUT_WR)
            while True:
                try:
                    c = s.recv(65536)
                except socket.timeout:
                    timed_out = True
                    break
                except ConnectionError:
                    break
                if not c:
                    break
                chunks.append(c)
        finally:
            s.close()
        raw = b"".join(chunks)
        if b"\r\n\r\n" not in raw:
            return Resp(None, {}, raw, timed_out)
        head, _, rest = raw.partition(b"\r\n\r\n")
        first, *hl = head.decode("latin-1").split("\r\n")
        headers_d = {}
        for h in hl:
            k, _, v = h.partition(":")
            headers_d[k.strip().lower()] = v.strip()
        return Resp(int(first.split()[1]), headers_d, rest, timed_out, first.split()[0])

    def get(self, path="/", headers=None, **k):
        return self.request("GET", path, hdr() if headers is None else headers, **k)

    def post(self, path, address=None, headers=None, body=None, **k):
        if body is None:
            body = form(address if address is not None else NEW_A)
        return self.request("POST", path, hdr() if headers is None else headers, body, **k)

    def assertNoAddressLeak(self, text, allowed=()):
        for who, addr in ADDR.items():
            if addr not in allowed:
                self.assertNotIn(addr, text, f"{who}'s stored address leaked")


# ---------------------------------------------------------------- permitted behaviour (pinned)
class PermittedMember(Base):
    def test_get_shows_own_state_and_amazon_instructions(self):
        before = self.state()
        r = self.get()
        self.assertEqual(r.status, 200)
        self.assertIn(ADDR["a"], r.text)
        self.assertIn("amazon.com/hz/mycd/myx", r.text)
        self.assertIn(SENDER, r.text)
        self.assertIn("Save to both libraries", r.text)
        self.assertIn('formaction="/remove"', r.text)  # something is set, so Remove is offered
        self.assertNoAddressLeak(r.text, allowed=(ADDR["a"],))
        self.assertNoWrites(before)

    def test_response_headers(self):
        r = self.get()
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.headers["referrer-policy"], "no-referrer")
        self.assertTrue(r.headers["content-type"].startswith("text/html"))

    def test_head_has_headers_and_no_body(self):
        r = self.request("HEAD", "/", hdr())
        self.assertEqual(r.status, 200)
        self.assertEqual(r.raw, b"")
        self.assertGreater(int(r.headers["content-length"]), 0)

    def test_get_with_query_and_trailing_slash_never_writes(self):
        before = self.state()
        for p in ("/?address=evil_1@kindle.com", "//", "/save", "/remove", "/save?address=x@kindle.com",
                  "/some/other/path"):
            r = self.get(p)
            self.assertEqual(r.status, 200, p)
            self.assertNoAddressLeak(r.text, allowed=(ADDR["a"],))
        self.assertNoWrites(before)

    def test_unsupported_methods_do_nothing(self):
        before = self.state()
        for m in ("PUT", "DELETE", "PATCH", "OPTIONS", "TRACE"):
            r = self.request(m, "/save", hdr(), b"address=" + NEW_A.encode())
            self.assertEqual(r.status, 501, m)
            self.assertNoAddressLeak(r.text)
        self.assertNoWrites(before)

    def test_no_account_shows_plain_message(self):
        r = self.get(headers=hdr(user="member-z", email="z@example.test"))
        self.assertEqual(r.status, 200)
        self.assertIn("No Calibre-Web or Audiobookshelf account found", r.text)
        self.assertNoAddressLeak(r.text)

    def test_missing_email_is_fine_when_username_matches(self):
        r = self.get(headers=hdr(email=None))
        self.assertEqual(r.status, 200)
        self.assertIn(ADDR["a"], r.text)

    def test_username_case_and_padding_resolve_to_the_same_member(self):
        before_b = self.rows()[1]
        r = self.post("/save", NEW_A, headers=hdr(user="  MEMBER-A  ", email=None))
        self.assertEqual(r.status, 200)
        self.assertIn("Saved to Calibre-Web and Audiobookshelf", r.text)
        self.assertEqual(self.rows()[0][3], NEW_A)
        self.assertEqual(self.rows()[1], before_b)
        mine = [d for d in self.abs.devices if d["users"] == ["abs-u-a"]]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["email"], NEW_A)

    def test_save_roundtrip_pinned(self):
        r = self.post("/save", "  " + NEW_A + "  ")
        self.assertEqual(r.status, 200)
        self.assertIn("Saved to Calibre-Web and Audiobookshelf. Remember to approve " + SENDER, r.text)
        self.assertIn(NEW_A, r.text)
        self.assertEqual(self.rows()[0], (1, "member-a", "a@example.test", NEW_A))
        self.assertEqual(len(self.abs.patches), 1)
        # idempotent: saving the same address again leaves exactly one device for A
        self.post("/save", NEW_A)
        self.assertEqual(len([d for d in self.abs.devices if d["users"] == ["abs-u-a"]]), 1)

    def test_remove_roundtrip_pinned(self):
        r = self.post("/remove", body=b"")
        self.assertEqual(r.status, 200)
        self.assertIn("Removed from Calibre-Web and Audiobookshelf.", r.text)
        self.assertIsNone(self.rows()[0][3])
        self.assertEqual([d["name"] for d in self.abs.devices],
                         ["Kindle (member-b)", "Kindle (admin-c)", "Shared Ereader"])
        self.assertNotIn('formaction="/remove"', r.text)

    def test_routes_tolerate_trailing_slash_and_query(self):
        self.assertEqual(self.post("/save/?x=1", NEW_A).status, 200)
        self.assertEqual(self.rows()[0][3], NEW_A)
        self.post("/remove/?x=1", body=b"")
        self.assertIsNone(self.rows()[0][3])

    def test_member_with_only_cwa_account(self):
        # fixture: member-d exists only in Calibre-Web
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO user VALUES (4,'member-d','d@example.test',NULL)")
        con.commit()
        con.close()
        before_abs = self.state()[1]
        r = self.post("/save", "member_d_x1@kindle.com", headers=hdr(user="member-d", email="d@example.test"))
        self.assertIn("Saved to Calibre-Web.", r.text)
        self.assertEqual(self.abs.devices, before_abs)
        self.assertEqual(self.rows()[3][3], "member_d_x1@kindle.com")

    def test_member_with_no_accounts_writes_nothing(self):
        before = self.state()
        r = self.post("/save", NEW_A, headers=hdr(user="member-z", email="z@example.test"))
        self.assertEqual(r.status, 200)
        self.assertIn("No library account found for this login.", r.text)
        self.assertNoWrites(before)

    def test_null_device_array_is_handled(self):
        self.abs.devices = []
        self.assertEqual(self.post("/save", NEW_A).status, 200)
        self.assertEqual([d["users"] for d in self.abs.devices], [["abs-u-a"]])

    def test_duplicate_address_field_takes_the_first(self):
        body = urllib.parse.urlencode([("address", NEW_A), ("address", "evil_1@kindle.com")]).encode()
        self.post("/save", body=body)
        self.assertEqual(self.rows()[0][3], NEW_A)

    def test_healthz_needs_no_identity_and_reads_nothing(self):
        r = self.request("GET", "/healthz")
        self.assertEqual((r.status, r.text), (200, "ok"))
        self.assertEqual(self.request("HEAD", "/healthz").status, 200)
        self.assertEqual(self.request("GET", "/healthz/", hdr(groups="nothing")).status, 200)
        self.assertEqual(self.abs.calls, [])

    def test_group_membership_is_exact_not_substring(self):
        for g in ("x|avrana-books|y", "avrana-books", "avrana-users, avrana-books", "a,b|avrana-books"):
            self.assertEqual(self.get(headers=hdr(groups=g)).status, 200, g)


# ---------------------------------------------------------------- denied identities
DENIED_IDENTITIES = [
    ("no headers", []),
    ("empty groups", hdr(groups="")),
    ("whitespace groups", hdr(groups="   ")),
    ("only separators", hdr(groups="|||,,")),
    ("wrong group", hdr(groups="avrana-users")),
    ("admin group only", hdr(groups="authentik Admins")),
    ("prefix of group", hdr(groups="avrana-book")),
    ("suffix extended", hdr(groups="avrana-books-extra")),
    ("prefix extended", hdr(groups="xavrana-books")),
    ("case differs", hdr(groups="AVRANA-BOOKS")),
    ("space inside", hdr(groups="avrana books")),
    ("no groups header", hdr(groups=None)),
    ("no username, wrong group", hdr(user=None, groups="avrana-users")),
    ("duplicate groups, first lacks", hdr(groups="avrana-users") + [("X-authentik-groups", "avrana-books")]),
    ("other member's email, wrong group", hdr(user="member-b", email="b@example.test", groups="avrana-users")),
]

DENIED_REQUESTS = [  # the four shapes that matter for every identity
    ("GET", "/", b""), ("HEAD", "/", b""),
    ("POST", "/save", form(NEW_A)), ("POST", "/remove", b"x=1"),
]
DENIED_EXTRA_REQUESTS = [  # other shapes, tried for two representative identities
    ("GET", "/save", b""), ("GET", "/anything", b""), ("POST", "/", form(NEW_A)),
    ("POST", "/unknown", form(NEW_A)), ("POST", "/save?address=" + NEW_A, form(NEW_B)),
]
NOT_FOUND_FORBIDDEN = (SENDER, "Kindle", "kindle", "Amazon", "amazon", "Calibre", "Audiobookshelf",
                       "<form", "ebook members")


class Denied(Base):
    def each(self):
        for i, (label, h) in enumerate(DENIED_IDENTITIES):
            shapes = DENIED_REQUESTS + (DENIED_EXTRA_REQUESTS if i in (0, 4) else [])
            for method, path, body in shapes:
                yield label, method, path, h, body

    def test_denied_is_a_plain_404_that_writes_nothing_and_reveals_nothing(self):
        before = self.state()
        for label, method, path, h, body in self.each():
            with self.subTest(label, method=method, path=path):
                r = self.request(method, path, h, body)
                self.assertEqual(r.status, 404)
                self.assertEqual(r.headers["cache-control"], "no-store")
                self.assertNoAddressLeak(r.text)
                self.assertNotIn("a@example.test", r.text)
                if method != "HEAD":
                    self.assertIn("That page does not exist.", r.text)
                    self.assertIn("<title>Not found · Avrana</title>", r.text)
                    for hint in NOT_FOUND_FORBIDDEN:
                        self.assertNotIn(hint, r.text)
        self.assertNoWrites(before)
        self.assertEqual(self.abs.calls, [], "denied requests must not even read the libraries")

    def test_permitted_member_gets_404_for_unknown_post_routes_without_leak(self):
        before = self.state()
        for path in ("/unknown", "/", "/SAVE", "/save/extra"):
            with self.subTest(path):
                r = self.post(path, NEW_A)
                self.assertEqual(r.status, 404)
                self.assertIn("That page does not exist.", r.text)
                for hint in NOT_FOUND_FORBIDDEN:
                    self.assertNotIn(hint, r.text)
        self.assertNoWrites(before)

    @unittest.expectedFailure
    def test_group_name_containing_a_comma_does_not_grant_access(self):
        # parse_groups splits on "," as well as "|", so a group literally named "x,avrana-books"
        # would count as avrana-books. Observed; see the report (needs an owner decision).
        r = self.get(headers=hdr(groups="x,avrana-books"))
        self.assertEqual(r.status, 404)


# ---------------------------------------------------------------- malformed identities
class MalformedIdentity(Base):
    def test_missing_or_blank_username_fails_closed_on_get(self):
        for label, h in (("missing", hdr(user=None, email="b@example.test")),
                         ("empty", hdr(user="", email="b@example.test")),
                         ("blank", hdr(user="   ", email="b@example.test"))):
            with self.subTest(label):
                r = self.get(headers=h)
                self.assertEqual(r.status, 404)
                self.assertNoAddressLeak(r.text)

    def test_missing_username_cannot_write_another_members_rows(self):
        before = self.state()
        for path, h in (("/save", hdr(user=None, email="b@example.test")),
                        ("/save", hdr(user="", email="b@example.test")),
                        ("/remove", hdr(user="", email="b@example.test"))):
            with self.subTest(path=path, h=h):
                r = self.post(path, NEW_A, headers=h)
                self.assertEqual(r.status, 404)
                self.assertNoAddressLeak(r.text)
        self.assertNoWrites(before)

    def test_duplicated_identity_headers_fail_closed(self):
        base = hdr(user="member-a")
        cases = {
            "two usernames": base + [("X-authentik-username", "member-b")],
            "two emails": base + [("X-authentik-email", "b@example.test")],
            "second groups line lacks books": base + [("X-authentik-groups", "avrana-users")],
            "second groups line has books": hdr(groups="avrana-users") + [("X-authentik-groups", GROUPS_OK)],
        }
        for label, h in cases.items():
            with self.subTest(label):
                before = self.state()
                self.assertEqual(self.get(headers=h).status, 404)
                self.assertEqual(self.post("/save", NEW_A, headers=h).status, 404)
                self.assertNoWrites(before)

    def test_very_long_username_matches_nobody(self):
        before = self.state()
        r = self.post("/save", NEW_A, headers=hdr(user="m" * 8000, email=None))
        self.assertEqual(r.status, 200)
        self.assertIn("No library account found", r.text)
        self.assertNoAddressLeak(r.text)
        self.assertNoWrites(before)

    def test_oversized_header_line_is_rejected_by_the_stdlib(self):
        before = self.state()
        r = self.get(headers=hdr(user="m" * 70000))
        self.assertNotEqual(r.status, 200)
        self.assertNoWrites(before)

    def test_odd_username_characters_match_nobody(self):
        before = self.state()
        for u in ("member-a'--", "' OR '1'='1", "member%", "member_a", "member-_", "../member-a",
                  "Kindle (member-a)", "mémber-a"):
            with self.subTest(u):
                r = self.post("/save", NEW_A, headers=hdr(user=u, email=None))
                self.assertEqual(r.status, 200)
                self.assertNoAddressLeak(r.text)
        for u in ("%", "_"):  # LIKE wildcards must not match every row, on read or on remove
            with self.subTest(u):
                for r in (self.get(headers=hdr(user=u, email=None)),
                          self.post("/remove", headers=hdr(user=u, email=None), body=b"")):
                    self.assertEqual(r.status, 200)
                    self.assertNoAddressLeak(r.text)
        self.assertNoWrites(before)

    def test_odd_email_characters_match_nobody(self):
        before = self.state()
        for e in ("' OR '1'='1", "%@example.test", "_@example.test", "%", "a@example.test'--"):
            with self.subTest(e):
                r = self.post("/save", NEW_A, headers=hdr(user="member-z", email=e))
                self.assertEqual(r.status, 200)
                self.assertNoAddressLeak(r.text)
        self.assertNoWrites(before)


# ---------------------------------------------------------------- request bodies
class Bodies(Base):
    def test_invalid_and_injection_shaped_addresses_write_nothing(self):
        bad = ["", " ", "someone@gmail.com", "me@free.kindle.com", "me@kindle.com.evil.com", "@kindle.com",
               "a@kindle.com,b@evil.com", "a@kindle.com\nBcc: x@y.com", "a@kindle.com\r\nBcc: x@y.com",
               "a\n@kindle.com", "'; DROP TABLE user;--", "a b@kindle.com",
               "a@kindle.com;b@kindle.com", "<script>@kindle.com", "a@kindle.com\x00", "me at kindle.com"]
        before = self.state()
        for a in bad:
            with self.subTest(repr(a)):
                r = self.post("/save", a)
                self.assertEqual(r.status, 200)
                self.assertIn("That is not a @kindle.com address.", r.text)
                self.assertNoAddressLeak(r.text, allowed=(ADDR["a"],))
        self.assertNoWrites(before)

    def test_unicode_case_folding_does_not_admit_lookalike_addresses(self):
        # re.I on a str pattern folds U+212A (Kelvin sign) to k and U+0131 (dotless i) to i
        bad = ["a@Kindle.com", "a@kındle.com", "Kelvin@kindle.com", "a@kindle.com x",
               "ſmile@kindle.com"]
        before = self.state()
        for a in bad:
            self.assertIsNone(kindle.KINDLE_RE.match(a), ascii(a))
            r = self.post("/save", a)
            self.assertIn("That is not a @kindle.com address.", r.text, ascii(a))
        self.assertNoWrites(before)
        self.assertTrue(kindle.KINDLE_RE.match("UPPER@KINDLE.COM"))  # ASCII case-insensitivity stays

    def test_error_banner_escapes_the_submitted_value(self):
        r = self.post("/save", '"><script>alert(1)</script>')
        self.assertNotIn("<script>alert(1)", r.text)

    def test_non_form_bodies_write_nothing(self):
        before = self.state()
        for ctype, body in (("application/json", json.dumps({"address": NEW_A}).encode()),
                            ("text/plain", NEW_A.encode()), ("application/octet-stream", bytes(range(256))),
                            ("multipart/form-data; boundary=x", b"--x\r\nContent-Disposition: form-data; "
                             b'name="address"\r\n\r\n' + NEW_A.encode() + b"\r\n--x--\r\n"),
                            ("application/x-www-form-urlencoded", b"\xff\xfe\x00address=")):
            with self.subTest(ctype):
                r = self.request("POST", "/save", hdr() + [("Content-Type", ctype)], body)
                self.assertEqual(r.status, 200)
                self.assertIn("That is not a @kindle.com address.", r.text)
        self.assertNoWrites(before)

    def test_missing_content_length_means_empty_body(self):
        before = self.state()
        r = self.request("POST", "/save", hdr(), b"", content_length=None)
        self.assertEqual(r.status, 200)
        self.assertIn("That is not a @kindle.com address.", r.text)
        self.assertNoWrites(before)

    def test_zero_content_length_ignores_body(self):
        before = self.state()
        r = self.request("POST", "/save", hdr(), form(NEW_A), content_length="0")
        self.assertIn("That is not a @kindle.com address.", r.text)
        self.assertNoWrites(before)

    def test_non_numeric_content_length_is_a_clean_400(self):
        before = self.state()
        for cl in ("abc", "1x", "0x10", "1.5"):
            with self.subTest(cl):
                r = self.request("POST", "/save", hdr(), form(NEW_A), content_length=cl)
                self.assertEqual(r.status, 400)
        self.assertEqual(self.server.errors, [], "handler raised instead of answering")
        self.assertNoWrites(before)

    def test_negative_content_length_does_not_hang_the_handler(self):
        before = self.state()
        r = self.request("POST", "/save", hdr(), form(NEW_A), content_length="-1", timeout=1.5)
        self.assertFalse(r.timed_out, "handler blocked reading until EOF")
        self.assertEqual(r.status, 400)
        self.assertNoWrites(before)

    def test_huge_content_length_is_refused_without_waiting(self):
        before = self.state()
        r = self.request("POST", "/save", hdr(), b"address=", content_length="99999999999", timeout=1.5)
        self.assertFalse(r.timed_out, "handler blocked waiting for a body that never comes")
        self.assertEqual(r.status, 413)
        self.assertNoWrites(before)

    def test_overlong_but_well_shaped_address_is_rejected(self):
        before = self.state()
        r = self.post("/save", "a" * 300 + "@kindle.com")
        self.assertEqual(r.status, 200)
        self.assertIn("That is not a @kindle.com address.", r.text)
        self.assertNoWrites(before)



# ---------------------------------------------------------------- isolation between members
class Isolation(Base):
    MEMBERS = {
        "a": dict(user="member-a", email="a@example.test", row=0, uid="abs-u-a"),
        "b": dict(user="member-b", email="b@example.test", row=1, uid="abs-u-b"),
        "c": dict(user="admin-c", email="c@example.test", row=2, uid="abs-u-c"),
    }

    def others_devices(self, devices, uid):
        return [json.dumps(d) for d in devices if d.get("users") != [uid]]

    def test_save_only_changes_own_cwa_row_and_abs_device(self):
        for who, m in self.MEMBERS.items():
            with self.subTest(who):
                rows0, dev0, patches0 = self.state()
                new = f"member_{who}_save1@kindle.com"
                r = self.post("/save", new, headers=hdr(user=m["user"], email=m["email"]))
                self.assertEqual(r.status, 200)
                rows1, dev1, patches1 = self.state()
                # Calibre-Web: only the caller's kindle_mail changed
                for i, (before, after) in enumerate(zip(rows0, rows1)):
                    if i == m["row"]:
                        self.assertEqual(after, before[:3] + (new,))
                    else:
                        self.assertEqual(after, before)
                # Audiobookshelf: exactly one PATCH; others' entries preserved byte for byte, in order
                self.assertEqual(len(patches1), len(patches0) + 1)
                sent = json.loads(patches1[-1])["ereaderDevices"]
                self.assertEqual(self.others_devices(sent, m["uid"]), self.others_devices(dev0, m["uid"]))
                mine = [d for d in sent if d.get("users") == [m["uid"]]]
                self.assertEqual(len(mine), 1)
                self.assertEqual(mine[0]["availabilityOption"], "specificUsers")
                self.assertEqual(mine[0]["users"], [m["uid"]])
                self.assertEqual(mine[0]["email"], new)
                for d in sent:  # nothing is ever written unscoped
                    if d["name"].startswith("Kindle ("):
                        self.assertEqual(d["availabilityOption"], "specificUsers")
                        self.assertTrue(d["users"])
                # the page shows the caller's own address and nobody else's
                self.assertIn(new, r.text)
                self.assertNoAddressLeak(r.text, allowed=(ADDR[who],))

    def test_remove_only_changes_own_cwa_row_and_abs_device(self):
        for who, m in self.MEMBERS.items():
            with self.subTest(who):
                rows0, dev0, patches0 = self.state()
                r = self.post("/remove", headers=hdr(user=m["user"], email=m["email"]), body=b"")
                self.assertEqual(r.status, 200)
                rows1, dev1, patches1 = self.state()
                for i, (before, after) in enumerate(zip(rows0, rows1)):
                    self.assertEqual(after, before[:3] + (None,) if i == m["row"] else before)
                self.assertEqual(len(patches1), len(patches0) + 1)
                self.assertEqual([json.dumps(d) for d in dev1], self.others_devices(dev0, m["uid"]))
                self.assertNoAddressLeak(r.text)

    def test_page_for_each_member_shows_only_their_own_address(self):
        for who, m in self.MEMBERS.items():
            with self.subTest(who):
                r = self.get(headers=hdr(user=m["user"], email=m["email"]))
                self.assertIn(ADDR[who], r.text)
                self.assertNoAddressLeak(r.text, allowed=(ADDR[who],))
                for other in self.MEMBERS.values():
                    if other is not m:
                        self.assertNotIn(other["email"], r.text)

    def test_unscoped_and_multi_user_devices_are_preserved_and_hidden(self):
        family = abs_device("Family reader", "family_x1@kindle.com", ["abs-u-a", "abs-u-b"])
        self.abs.devices.insert(1, family)
        before = json.dumps(family)
        r = self.get()
        self.assertNotIn("family_x1@kindle.com", r.text)
        self.assertNotIn(ADDR["shared"], r.text)
        self.post("/save", NEW_A)
        self.assertIn(before, [json.dumps(d) for d in self.abs.devices])
        self.post("/remove", body=b"")
        self.assertIn(before, [json.dumps(d) for d in self.abs.devices])
        self.assertIn(ADDR["shared"], [d["email"] for d in self.abs.devices])

    def test_concurrent_saves_by_two_members_both_survive(self):
        # The array is global and written whole. With a slow Audiobookshelf both requests would read
        # the same snapshot and the second PATCH would erase the first, unless _abs_lock serialises
        # read-modify-write. (Verified: with the lock removed this test fails.)
        self.abs.latency = 0.15
        out, start = [], threading.Barrier(2)

        def go(m, addr):
            start.wait(5)
            out.append(self.post("/save", addr, headers=hdr(user=m["user"], email=m["email"]), timeout=15).status)
        ts = [threading.Thread(target=go, args=(self.MEMBERS["a"], NEW_A)),
              threading.Thread(target=go, args=(self.MEMBERS["b"], NEW_B))]
        [t.start() for t in ts]
        [t.join(20) for t in ts]
        self.assertEqual(out, [200, 200])
        by_user = {tuple(d["users"]): d["email"] for d in self.abs.devices if d["users"]}
        self.assertEqual(by_user[("abs-u-a",)], NEW_A)
        self.assertEqual(by_user[("abs-u-b",)], NEW_B)
        self.assertEqual(by_user[("abs-u-c",)], ADDR["c"])
        self.assertEqual(len(self.abs.devices), 4)


# ---------------------------------------------------------------- cross-member identity defects
class IdentityResolution(Base):
    def test_email_match_on_an_earlier_abs_user_does_not_beat_the_exact_username(self):
        # Member A's e-mail header equals B's address (Authentik lets users edit their own e-mail by
        # default), and B is listed before A in Audiobookshelf. abs_find returns the first user matching
        # username OR e-mail in list order, so A's save lands on B's account.
        self.abs.users = [ABS_USERS[1], ABS_USERS[0], ABS_USERS[2]]
        h = hdr(user="member-a", email="b@example.test")
        r = self.get(headers=h)
        self.assertNotIn(ADDR["b"], r.text, "A's page shows B's Audiobookshelf address")
        before = self.state()
        r = self.post("/save", NEW_A, headers=h)
        rows1, dev1, _ = self.state()
        b_dev = [d for d in dev1 if d.get("users") == ["abs-u-b"]]
        self.assertEqual([d["email"] for d in b_dev], [ADDR["b"]], "B's device was overwritten by A")
        a_dev = [d for d in dev1 if d.get("users") == ["abs-u-a"]]
        self.assertEqual([d["email"] for d in a_dev], [NEW_A])
        self.assertEqual(rows1[1], CWA_ROWS[1])

    def test_remove_with_a_colliding_email_does_not_remove_the_victim(self):
        self.abs.users = [ABS_USERS[1], ABS_USERS[0], ABS_USERS[2]]
        self.post("/remove", headers=hdr(user="member-a", email="b@example.test"), body=b"")
        self.assertIn("abs-u-b", [u for d in self.abs.devices for u in d["users"]], "B's device was removed")

    def test_cwa_fallback_never_beats_an_existing_username_match(self):
        # sanity pin: with a matching username the Calibre-Web row is A's even if e-mail names B
        self.post("/save", NEW_A, headers=hdr(user="member-a", email="b@example.test"))
        self.assertEqual(self.rows()[0][3], NEW_A)
        self.assertEqual(self.rows()[1], CWA_ROWS[1])

    def test_unmatched_username_with_a_victims_email_cannot_act_as_the_victim(self):
        # The e-mail header is not a join key (Authentik lets users edit it): it never resolves an account.
        h = hdr(user="member-z", email="b@example.test")
        r = self.get(headers=h)
        self.assertNotIn(ADDR["b"], r.text)
        before = self.state()
        self.post("/save", NEW_A, headers=h)
        self.assertNoWrites(before)

    def test_email_header_never_resolves_an_account(self):
        before = self.state()
        for e in ("b@example.test", "B@EXAMPLE.TEST", "c@example.test"):
            r = self.post("/save", NEW_B, headers=hdr(user="renamed-b", email=e))
            self.assertIn("No library account found", r.text)
            self.assertNoAddressLeak(r.text)
            self.assertNotIn("Removed", self.post("/remove", headers=hdr(user="renamed-b", email=e), body=b"").text)
        self.assertNoWrites(before)

    def test_partial_account_member_cannot_reach_the_victims_abs_account(self):
        # mallory: Calibre-Web row, NO Audiobookshelf account, e-mail header = alice's (member-a's).
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO user VALUES (4,'mallory','m@example.test',NULL)")
        con.commit()
        con.close()
        h = hdr(user="mallory", email="a@example.test")
        r = self.get(headers=h)
        self.assertNotIn(ADDR["a"], r.text)
        abs_before = copy.deepcopy(self.abs.devices)
        r = self.post("/save", "mallory_x1@kindle.com", headers=h)
        self.assertIn("Saved to Calibre-Web.", r.text)
        self.assertEqual(self.abs.devices, abs_before)
        self.assertEqual(self.abs.patches, [])
        self.assertEqual(self.rows()[0], CWA_ROWS[0])
        self.post("/remove", headers=h, body=b"")
        self.assertEqual(self.abs.devices, abs_before)

    def test_abs_only_member_cannot_reach_the_victims_calibre_web_row(self):
        # mirror case: Audiobookshelf account, NO Calibre-Web row, e-mail header = alice's
        self.abs.users.append(abs_user("abs-u-m", "mallory", "m@example.test"))
        h = hdr(user="mallory", email="a@example.test")
        r = self.get(headers=h)
        self.assertNotIn(ADDR["a"], r.text)
        self.post("/save", "mallory_x1@kindle.com", headers=h)
        self.post("/remove", headers=h, body=b"")
        self.assertEqual(self.rows(), CWA_ROWS)
        self.assertEqual([d["email"] for d in self.abs.devices if d["users"] == ["abs-u-a"]], [ADDR["a"]])

    def test_ambiguous_email_fallback_matches_nobody(self):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO user VALUES (4,'member-d','b@example.test','member_d_x1@kindle.com')")
        con.commit()
        con.close()
        self.abs.users.append(abs_user("abs-u-d", "member-d", "b@example.test"))
        before = self.state()
        r = self.post("/save", NEW_A, headers=hdr(user="renamed", email="b@example.test"))
        self.assertIn("No library account found", r.text)
        self.assertNoAddressLeak(r.text)
        self.assertNoWrites(before)

    def test_cwa_names_differing_only_by_case_resolve_exactly(self):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO user VALUES (4,'Member-X','x1@example.test','upper_x1@kindle.com')")
        con.execute("INSERT INTO user VALUES (5,'member-x','x2@example.test','lower_x2@kindle.com')")
        con.commit()
        con.close()
        r = self.get(headers=hdr(user="member-x", email=None))
        self.assertIn("lower_x2@kindle.com", r.text)
        self.assertNotIn("upper_x1@kindle.com", r.text)
        self.post("/save", NEW_A, headers=hdr(user="member-x", email=None))
        self.assertEqual(self.rows()[3][3], "upper_x1@kindle.com", "the other case's row was overwritten")
        self.assertEqual(self.rows()[4][3], NEW_A)

    def test_cwa_ambiguous_case_insensitive_match_fails_closed(self):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO user VALUES (4,'Member-X','x1@example.test','upper_x1@kindle.com')")
        con.execute("INSERT INTO user VALUES (5,'member-x','x2@example.test','lower_x2@kindle.com')")
        con.commit()
        con.close()
        before = self.state()
        r = self.post("/save", NEW_A, headers=hdr(user="MEMBER-X", email=None))
        self.assertNotIn("x1@kindle", r.text)
        self.assertNoWrites(before)

    def test_abs_users_differing_only_by_case_resolve_exactly(self):
        self.abs.users = self.abs.users + [abs_user("abs-u-x1", "Member-X", ""),
                                           abs_user("abs-u-x2", "member-x", "")]
        self.abs.devices = self.abs.devices + [abs_device("Kindle (Member-X)", "upper_x1@kindle.com", ["abs-u-x1"]),
                                               abs_device("Kindle (member-x)", "lower_x2@kindle.com", ["abs-u-x2"])]
        r = self.get(headers=hdr(user="member-x", email=None))
        self.assertIn("lower_x2@kindle.com", r.text)
        self.assertNotIn("upper_x1@kindle.com", r.text)

    def test_abs_user_record_without_username_does_not_crash(self):
        self.abs.users = [{"id": "abs-u-ghost"}] + self.abs.users
        r = self.get()
        self.assertEqual(r.status, 200)
        self.assertEqual(self.server.errors, [])
        self.assertIn(ADDR["a"], r.text)

    def test_label_collision_does_not_delete_someone_elses_device(self):
        # A device scoped to someone else that carries A's label used to be dropped by abs_set.
        self.abs.devices = [abs_device("Kindle (member-a)", ADDR["c"], ["abs-u-c"])] + [
            d for d in ABS_DEVICES if d["users"] not in (["abs-u-a"], ["abs-u-c"])]
        victim = json.dumps(self.abs.devices[0])
        self.post("/save", NEW_A)
        devs = self.abs.devices
        self.assertIn(victim, [json.dumps(d) for d in devs])
        mine = [d for d in devs if d["users"] == ["abs-u-a"]]
        self.assertEqual([d["email"] for d in mine], [NEW_A])
        names = [d["name"] for d in devs]
        self.assertEqual(len(names), len(set(names)), "device names must stay unique")
        self.post("/remove", body=b"")  # and removing A's still leaves the foreign device alone
        self.assertEqual([d for d in self.abs.devices if json.dumps(d) == victim], [self.abs.devices[0]])
        self.assertEqual([d for d in self.abs.devices if d["users"] == ["abs-u-a"]], [])

    def test_unscoped_leftover_with_the_members_label_is_replaced(self):
        self.abs.devices = [{"name": "Kindle (member-a)", "email": ADDR["shared"], "availabilityOption": "adminOrUp",
                             "users": []}] + [d for d in ABS_DEVICES if d["users"] != ["abs-u-a"]]
        self.post("/save", NEW_A)
        self.assertNotIn(ADDR["shared"] + "\"", json.dumps([d for d in self.abs.devices if d["name"] == "Kindle (member-a)"]))


# ---------------------------------------------------------------- owner-set username aliases
class AliasMap(unittest.TestCase):
    def parse(self, raw):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            return kindle.load_aliases(raw), err.getvalue()

    def test_valid_formats(self):
        self.assertEqual(self.parse("")[0], {})
        self.assertEqual(self.parse(None)[0], {})
        self.assertEqual(self.parse("akadmin=admin-c")[0], {"akadmin": "admin-c"})
        self.assertEqual(self.parse("a=b, c=d\ne=f  g=h")[0], {"a": "b", "c": "d", "e": "f", "g": "h"})
        self.assertEqual(self.parse("a=b,a=b")[0], {"a": "b"})  # an exact repeat is harmless

    def test_any_malformed_token_refuses_the_whole_map(self):
        # names with spaces are not supported: "John Smith=Cody" must not become {"Smith": "Cody"}
        for raw in ("John Smith=Cody", "akadmin=Cody Smith", "ok=fine novalue", "ok=fine =x", "ok=fine y=",
                    "ok=fine a=b=c", "ok=fine,junk", "novalue"):
            with self.subTest(raw):
                got, log = self.parse(raw)
                self.assertEqual(got, {})
                self.assertEqual(log.count("\n"), 1)
                self.assertIn("refused", log)
                for name in ("John", "Smith", "Cody", "ok", "fine", "novalue", "akadmin"):
                    self.assertNotIn(name, log)

    def test_ambiguous_maps_are_refused_whole_with_a_count_only_log(self):
        for raw in ("a=b,b=c", "a=x,b=x", "a=x,b=X", "a=x,a=y", "a=A", "a=b,fine=ok,B=z"):
            with self.subTest(raw):
                got, log = self.parse(raw)
                self.assertEqual(got, {}, "the whole map must be refused")
                self.assertEqual(log.count("\n"), 1)
                self.assertIn("refused", log)
                for name in ("fine", "ok", "x", "y"):
                    self.assertNotRegex(log, r"\b" + name + r"\b")

    def test_no_aliases_by_default(self):
        self.assertEqual(kindle.ALIASES, {})
        self.assertEqual(kindle.library_name("akadmin"), "akadmin")


class AliasedLogin(Base):
    def setUp(self):
        super().setUp()
        saved = kindle.ALIASES
        kindle.ALIASES = {"akadmin": "admin-c"}
        self.addCleanup(lambda: setattr(kindle, "ALIASES", saved))

    def test_alias_resolves_in_both_libraries_and_only_touches_the_target(self):
        h = hdr(user="akadmin", email="whatever@example.test")
        r = self.get(headers=h)
        self.assertIn(ADDR["c"], r.text)
        self.assertNoAddressLeak(r.text, allowed=(ADDR["c"],))
        rows0, dev0, _ = self.state()
        r = self.post("/save", "admin_c_new@kindle.com", headers=h)
        self.assertIn("Saved to Calibre-Web and Audiobookshelf", r.text)
        rows1, dev1, _ = self.state()
        self.assertEqual(rows1[:2], rows0[:2])
        self.assertEqual(rows1[2][3], "admin_c_new@kindle.com")
        mine = [d for d in dev1 if d["users"] == ["abs-u-c"]]
        self.assertEqual([(d["name"], d["email"]) for d in mine], [("Kindle (admin-c)", "admin_c_new@kindle.com")])
        self.assertEqual([d for d in dev1 if d["users"] != ["abs-u-c"]], [d for d in dev0 if d["users"] != ["abs-u-c"]])

    def test_the_target_name_belongs_to_the_alias_source_alone(self):
        before = self.state()
        for u in ("admin-c", "ADMIN-C", "Admin-C"):
            with self.subTest(u):
                self.assertEqual(self.get(headers=hdr(user=u)).status, 404)
                self.assertEqual(self.post("/save", NEW_A, headers=hdr(user=u)).status, 404)
        self.assertNoWrites(before)

    def test_alias_needs_an_exact_source_and_never_chains(self):
        before = self.state()
        r = self.post("/save", NEW_A, headers=hdr(user="akadmin2"))
        self.assertIn("No library account found", r.text)
        self.assertNoWrites(before)

    def test_case_variants_of_a_source_or_target_resolve_to_nobody(self):
        # a library account named like the source in another case must not be reachable by that variant
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO user VALUES (4,'AkAdmin','x@example.test','akadmin_x1@kindle.com')")
        con.commit()
        con.close()
        before = self.state()
        for u in ("AKADMIN", "Akadmin", "AkAdmin", "ADMIN-C", "Admin-C"):
            with self.subTest(u):
                self.assertEqual(self.get(headers=hdr(user=u)).status, 404)
                self.assertEqual(self.post("/save", NEW_A, headers=hdr(user=u)).status, 404)
        self.assertNoWrites(before)
        self.assertIn(ADDR["c"], self.get(headers=hdr(user="akadmin")).text)  # the exact source still works

    def test_alias_to_a_name_that_does_not_exist_resolves_nobody(self):
        kindle.ALIASES = {"akadmin": "nobody-here"}
        before = self.state()
        r = self.post("/save", NEW_A, headers=hdr(user="akadmin"))
        self.assertIn("No library account found", r.text)
        self.assertNoWrites(before)

    def test_unaliased_members_are_unaffected(self):
        r = self.get(headers=hdr(user="member-b"))
        self.assertIn(ADDR["b"], r.text)
        self.assertNoAddressLeak(r.text, allowed=(ADDR["b"],))


class WriteFailures(Base):
    def block_cwa_updates(self):
        con = sqlite3.connect(self.db)
        con.execute("CREATE TRIGGER no_update BEFORE UPDATE ON user BEGIN SELECT RAISE(ABORT,'blocked'); END")
        con.commit()
        con.close()

    def test_save_with_abs_patch_failure_reports_it_and_leaves_others_alone(self):
        self.abs.fail_patch = True
        dev0 = copy.deepcopy(self.abs.devices)
        r = self.post("/save", NEW_A)
        self.assertEqual(r.status, 200)
        self.assertIn("Saved to Calibre-Web; failed for Audiobookshelf.", r.text)
        self.assertEqual(self.abs.devices, dev0)
        self.assertEqual(self.rows()[0][3], NEW_A)  # observed: the two libraries now disagree
        self.assertEqual(self.rows()[1:], CWA_ROWS[1:])
        self.assertEqual(self.server.errors, [])
        self.assertNoAddressLeak(r.text, allowed=(ADDR["a"], NEW_A))

    def test_save_with_cwa_failure_reports_it_and_leaves_others_alone(self):
        self.block_cwa_updates()
        r = self.post("/save", NEW_A)
        self.assertEqual(r.status, 200)
        self.assertIn("Saved to Audiobookshelf; failed for Calibre-Web.", r.text)
        self.assertEqual(self.rows(), CWA_ROWS)
        self.assertEqual([d["email"] for d in self.abs.devices if d["users"] == ["abs-u-a"]], [NEW_A])
        self.assertEqual(self.server.errors, [])

    def test_save_when_abs_goes_down_after_the_failed_write_still_answers(self):
        self.abs.fail_patch = True
        self.abs.dead_after_failed_patch = True
        r = self.post("/save", NEW_A)
        self.assertEqual(r.status, 200, "connection dropped after Calibre-Web was already written")
        self.assertIn("failed for Audiobookshelf", r.text)
        self.assertEqual(self.server.errors, [])

    def test_remove_with_abs_patch_failure_reports_it(self):
        self.abs.fail_patch = True
        r = self.post("/remove", body=b"")
        self.assertEqual(r.status, 200, "no response: /remove has no error handling")
        self.assertIn("failed for Audiobookshelf", r.text)
        self.assertEqual(self.server.errors, [])
        self.assertEqual(self.rows()[1:], CWA_ROWS[1:])

    def test_remove_with_cwa_failure_still_removes_from_abs_and_reports(self):
        self.block_cwa_updates()
        r = self.post("/remove", body=b"")
        self.assertEqual(r.status, 200, "no response: /remove has no error handling")
        self.assertIn("failed for Calibre-Web", r.text)
        self.assertEqual(self.server.errors, [])
        self.assertEqual(self.rows(), CWA_ROWS)

    def test_remove_never_touches_others_even_when_it_fails(self):
        self.abs.fail_patch = True
        dev0 = copy.deepcopy(self.abs.devices)
        self.post("/remove", body=b"")
        self.assertEqual(self.abs.devices, dev0)
        self.assertEqual(self.rows()[1:], CWA_ROWS[1:])

    def test_reads_failing_up_front_answer_503_and_write_nothing(self):
        self.abs._dead = True
        before = self.state()
        for r in (self.get(), self.post("/save", NEW_A), self.post("/remove", body=b"")):
            self.assertEqual(r.status, 503)
            self.assertEqual(r.headers["content-type"], "text/plain; charset=utf-8")
            self.assertNotIn("Traceback", r.text)
            self.assertNoAddressLeak(r.text)
            self.assertNotIn("member-a", r.text)
        self.assertNoWrites(before)
        self.assertEqual(self.server.errors, [])

    def test_calibre_web_unreadable_answers_503(self):
        kindle.CWA_DB = os.path.join(os.path.dirname(self.db), "missing", "app.db")
        before = self.state()
        self.assertEqual(self.get().status, 503)
        self.assertEqual(self.post("/save", NEW_A).status, 503)
        self.assertEqual(self.server.errors, [])
        kindle.CWA_DB = self.db
        self.assertNoWrites(before)

    def test_refresh_survives_both_libraries_down_after_a_failed_write(self):
        h = self.handler_cls.__new__(self.handler_cls)
        h._state = lambda u: (_ for _ in ()).throw(OSError("down"))
        saved = kindle.cwa_find
        kindle.cwa_find = lambda u: (_ for _ in ()).throw(OSError("down"))
        self.addCleanup(lambda: setattr(kindle, "cwa_find", saved))
        before = ((1, "member-a", ADDR["a"]), {"id": "abs-u-a"}, ADDR["a"], ADDR["a"])
        self.assertEqual(h._refresh("member-a", before, ["Audiobookshelf"]), before)

    def test_refresh_with_nothing_failed_reports_unavailable_not_stale_data(self):
        h = self.handler_cls.__new__(self.handler_cls)
        h._state = lambda u: (_ for _ in ()).throw(OSError("down"))
        self.assertIsNone(h._refresh("member-a", ("x",) * 4, []))
        h._state = lambda u: ("fresh",)
        self.assertEqual(h._refresh("member-a", ("x",) * 4, []), ("fresh",))
        self.assertEqual(h._refresh("member-a", ("x",) * 4, ["Calibre-Web"]), ("fresh",))

    def test_post_refresh_failure_with_nothing_failed_answers_503(self):
        self.abs.dead_after_patch = True  # the write lands, then the library goes away
        r = self.post("/save", NEW_A)
        self.assertEqual(r.status, 503)
        self.assertNotIn("Traceback", r.text)
        self.assertEqual(self.server.errors, [])
        self.assertEqual(self.rows()[0][3], NEW_A)  # observed: the write did happen


class Hardening(Base):
    handler_timeout = 0.4
    handler_attrs = {"body_deadline": 0.6}

    def test_stalled_body_times_out_with_408_instead_of_pinning_a_thread(self):
        before = self.state()
        t0 = time.time()
        r = self.request("POST", "/save", hdr(), b"address=", content_length="50", timeout=5)
        self.assertFalse(r.timed_out)
        self.assertEqual(r.status, 408)
        self.assertLess(time.time() - t0, 3)
        self.assertNoWrites(before)

    def test_trickled_body_hits_a_total_deadline_not_just_a_per_read_timeout(self):
        # one byte every 0.15 s never trips the 0.4 s per-read timeout; only a total deadline stops it
        before = self.state()
        head = (b"POST /save HTTP/1.1\r\nHost: x\r\nContent-Length: 60\r\n" +
                b"".join(f"{k}: {v}\r\n".encode() for k, v in hdr()) + b"\r\n")
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        t0 = time.time()
        try:
            s.sendall(head)
            sent, data = 0, b""
            while sent < 60 and time.time() - t0 < 4 and not data:
                s.sendall(b"a")
                sent += 1
                if select.select([s], [], [], 0.15)[0]:  # the server answered: stop sending
                    data = s.recv(65536)
            if not data:
                s.settimeout(2)
                data = s.recv(65536)
        finally:
            s.close()
        self.assertTrue(data.startswith(b"HTTP/1.0 408"), data[:40])
        self.assertLess(time.time() - t0, 3, "the server kept reading a trickled body")
        self.assertLess(sent, 60)
        self.assertNoWrites(before)

    def test_timeout_default_and_protocol(self):
        self.assertEqual(kindle.Handler.timeout, 15)
        self.assertEqual(kindle.Handler.protocol_version, "HTTP/1.0")

    def test_every_response_is_http_1_0_and_closes_the_connection(self):
        # early 404/400/413 replies do not read the body; that is only safe if the connection closes
        for r in (self.get(), self.get(headers=[]), self.post("/save", NEW_A),
                  self.request("POST", "/save", hdr(), b"x", content_length="abc"),
                  self.request("POST", "/save", hdr(), b"x", content_length="99999999")):
            self.assertEqual(r.version, "HTTP/1.0")
            self.assertFalse(r.timed_out)  # the server closed; we never had to give up waiting


class StoredValues(Base):
    def test_stored_addresses_are_html_escaped_when_rendered(self):
        evil = '"><script>alert(1)</script>@kindle.com'
        con = sqlite3.connect(self.db)
        con.execute("UPDATE user SET kindle_mail=? WHERE id=1", (evil,))
        con.commit()
        con.close()
        self.abs.devices[0]["email"] = '<img src=x onerror=alert(2)>@kindle.com'
        r = self.get()
        self.assertNotIn("<script>alert(1)", r.text)
        self.assertNotIn("<img src=x", r.text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", r.text)
        self.assertIn("&lt;img src=x onerror=alert(2)&gt;", r.text)
        self.assertNotIn('value=""><script', r.text)

    def test_banner_text_and_sender_are_escaped(self):
        saved = kindle.SENDER
        kindle.SENDER = "<b>s</b>@example.test"
        self.addCleanup(lambda: setattr(kindle, "SENDER", saved))
        r = self.get()
        self.assertNotIn("<b>s</b>", r.text)
        self.assertIn("&lt;b&gt;s&lt;/b&gt;@example.test", r.text)

    def test_matching_is_ascii_only_and_consistent_across_libraries(self):
        kelvin, dotless = "Kevin", "kındle"
        # Python's lower() folds the Kelvin sign to k, SQLite's does not: both must say "nobody"
        self.assertEqual(kindle._pick([(1, "kevin")], lambda r: r[1], kelvin), (None, False))
        self.assertEqual(kindle._pick([(1, kelvin)], lambda r: r[1], "kevin"), (None, False))
        self.assertEqual(kindle._pick([(1, "kindle")], lambda r: r[1], dotless), (None, False))
        self.assertEqual(kindle._pick([(1, kelvin)], lambda r: r[1], kelvin), (None, False))  # non-ASCII never matches
        self.assertEqual(kindle._fold("ABC-Kİ"), "abc-Kİ")
        self.abs.users.append(abs_user("abs-u-k", "kevin", ""))
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO user VALUES (4,'kevin','k@example.test',NULL)")
        con.commit()
        con.close()
        for wanted in (kelvin, dotless, "member-K"):
            self.assertIsNone(kindle.cwa_find(wanted), ascii(wanted))
            self.assertIsNone(kindle.abs_find(wanted), ascii(wanted))
        self.assertEqual(kindle.cwa_find("KEVIN")[1], "kevin")  # ASCII case-insensitivity stays
        self.assertEqual(kindle.abs_find("KEVIN")["id"], "abs-u-k")
        self.assertEqual(kindle.library_name(kelvin), kelvin)  # passed through, then matches nobody

    def test_pick_with_identical_exact_names_resolves_to_nobody(self):
        rows = [(1, "dup"), (2, "dup")]
        self.assertEqual(kindle._pick(rows, lambda r: r[1], "dup"), (None, True))
        self.assertEqual(kindle._pick(rows, lambda r: r[1], "DUP"), (None, True))
        self.assertEqual(kindle._pick([(1, "Dup")], lambda r: r[1], "dup"), ((1, "Dup"), True))
        self.assertEqual(kindle._pick([(1, "Dup"), (2, "dup")], lambda r: r[1], "dup"), ((2, "dup"), True))
        self.assertEqual(kindle._pick([], lambda r: r[1], "dup"), (None, False))

    def test_two_audiobookshelf_users_with_the_same_exact_name_resolve_to_nobody(self):
        self.abs.users.append(abs_user("abs-u-dup", "member-a", "dup@example.test"))
        dev0 = copy.deepcopy(self.abs.devices)
        r = self.post("/save", NEW_A)
        self.assertIn("Saved to Calibre-Web.", r.text)  # the unambiguous library only
        self.assertEqual(self.abs.patches, [])
        self.assertEqual(self.abs.devices, dev0)
        self.assertNotIn(ADDR["b"], r.text)


class ParseGroups(unittest.TestCase):
    def test_separators(self):
        self.assertEqual(kindle.parse_groups("a|b"), {"a", "b"})
        self.assertEqual(kindle.parse_groups(" a | b ,c"), {"a", "b", "c"})
        self.assertEqual(kindle.parse_groups(""), set())


if __name__ == "__main__":
    unittest.main()
