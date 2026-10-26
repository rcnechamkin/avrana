"""The temporary fixture-only HTTPS LAN preview (dev/run_lan_preview.py, dev/lan_gate.py; AVR-585 B1).

Every startup refusal, the expiry bound, the passphrase gate, an end-to-end run of the gated fixture stack on
127.0.0.1 (TLS file checks patched out, plain HTTP), and auto-expiry. Nothing binds anything but loopback.

The real TLS handshake smoke test needs a throwaway certificate, made with the `cryptography` package. That package
is NOT in requirements.lock and is not added for this: when it is absent the smoke-test class is not defined at all
(rather than skipped, because AVRANA_REQUIRE_DEPS=1 fails any skip), and this note is the recorded reason.
"""
import asyncio
import importlib.util
import logging
import os
import re
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock as umock

from .support import HOME, parse_http, require_framework

require_framework()

from dev import lan_gate, run_lan_preview as rlp  # noqa: E402
from dev.dev_identity import DevIdentityRefused, check_lan_bind, check_lan_startup  # noqa: E402

HAVE_CRYPTOGRAPHY = importlib.util.find_spec("cryptography") is not None
PASS = "correct-horse-battery-staple-1"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def free_ports():
    return {name: free_port() for name in rlp.MOCK_PORTS}


# ---- bind address ------------------------------------------------------------------------------------------
class BindTests(unittest.TestCase):
    REFUSED = ("0.0.0.0", "::", "::1", "127.0.0.1", "127.0.0.2", "169.254.10.20", "8.8.8.8", "203.0.113.7",
               "100.64.0.1", "172.32.0.1", "172.15.255.255", "224.0.0.1", "255.255.255.255", "localhost",
               "my-laptop.local", "192.168.1.300", "fe80::1", "fd00::1", "010.0.0.1", " 192.168.1.2", "")
    ACCEPTED = ("10.0.0.5", "10.255.255.254", "172.16.0.1", "172.31.255.254", "192.168.1.23")

    def test_only_one_rfc1918_ipv4_literal_is_accepted(self):
        for host in self.REFUSED:
            with self.subTest(host=host), self.assertRaises(DevIdentityRefused):
                check_lan_bind(host)
        for host in self.ACCEPTED:
            with self.subTest(host=host):
                check_lan_bind(host)

    def test_loopback_only_with_the_test_flag_and_only_127_0_0_1(self):
        check_lan_bind("127.0.0.1", allow_loopback=True)
        for host in ("::1", "127.0.0.2", "0.0.0.0"):
            with self.subTest(host=host), self.assertRaises(DevIdentityRefused):
                check_lan_bind(host, allow_loopback=True)

    def test_check_lan_startup_needs_enable_and_acknowledgement_and_mock_settings(self):
        from .support import make_settings
        ok = make_settings()
        check_lan_startup(enabled=True, acknowledged=True, host="192.168.1.23", settings=ok)
        for kw in ({"enabled": False, "acknowledged": True}, {"enabled": True, "acknowledged": False}):
            with self.subTest(**kw), self.assertRaises(DevIdentityRefused):
                check_lan_startup(host="192.168.1.23", settings=ok, **kw)
        for bad in (make_settings(upstream_mode="real"), make_settings(jellyfin_api_key="real-looking"),
                    make_settings(jellyfin_base_url="http://10.0.0.218:8096"),
                    make_settings(identity_mode="jwt_required")):
            with self.subTest(bad=repr(bad)), self.assertRaises(DevIdentityRefused):
                check_lan_startup(enabled=True, acknowledged=True, host="192.168.1.23", settings=bad)

    def test_only_the_lan_launcher_imports_check_lan_startup(self):
        users = []
        for path in HOME.rglob("*.py"):
            rel = path.relative_to(HOME).as_posix()
            if rel.startswith(("webtests/", "tests/")) or rel == "dev/dev_identity.py":
                continue
            if "check_lan_startup" in path.read_text(encoding="utf-8"):
                users.append(rel)
        self.assertEqual(["dev/run_lan_preview.py"], users)


# ---- the other startup refusals ----------------------------------------------------------------------------
class RefusalTests(unittest.TestCase):
    def test_minutes_bound(self):
        for good in (1, 60, 240):
            self.assertEqual(good, rlp.check_minutes(good))
        for bad in (0, -1, 241, 10_000, True, 1.5, "60"):
            with self.subTest(bad=bad), self.assertRaises(DevIdentityRefused):
                rlp.check_minutes(bad)
        self.assertEqual(60, rlp.DEFAULT_MINUTES)
        self.assertEqual(240, rlp.MAX_MINUTES)

    def test_real_upstream_environment_is_refused_by_name(self):
        for name in ("JELLYFIN_BASE_URL", "JELLYFIN_API_KEY", "JELLYFIN_API_KEY_FILE", "AUDIOBOOKSHELF_TOKEN",
                     "KOMGA_TOKEN_FILE", "CALIBRE_WEB_CREDENTIAL", "HOME_UPSTREAM_MODE", "HOME_OWNER_PREVIEW",
                     "HOME_CATALOGUE_PATH", "HOME_JWT_SECRET", "PREVIEW_PASSWORD_FILE",
                     "jellyfin_base_url"):
            with self.subTest(name=name), self.assertRaises(DevIdentityRefused) as ctx:
                rlp.check_environment({name: "https://media.example.invalid/secret-value"})
            self.assertNotIn("secret-value", str(ctx.exception))
        rlp.check_environment({"HOME_PWA_SW": "off", "HOME_MOTION_PROPOSAL": "on", "HOMEPATH": "x",
                               "GH_TOKEN": "x", "PATH": "x"})

    def test_tls_files_missing_unreadable_wrong_kind_in_git_or_mismatched(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "outside"
            out.mkdir()
            cert, key = out / "c.pem", out / "k.pem"
            cert.write_text("-----BEGIN CERTIFICATE-----\nnot really\n-----END CERTIFICATE-----\n")
            fake = "PRIVATE " + "KEY-----"          # split so the repository's secret scanner is not tripped
            key.write_text(f"-----BEGIN {fake}\nnot really\n-----END {fake}\n")
            repo = Path(tmp) / "repo"
            (repo / ".git").mkdir(parents=True)
            (repo / "sub").mkdir()
            gkey = repo / "sub" / "k.pem"
            gkey.write_text(key.read_text())
            cases = [(None, str(key), "required"), (str(cert), None, "required"),
                     (str(out / "nope.pem"), str(key), "missing"), (str(cert), str(out / "nope.pem"), "missing"),
                     (str(out), str(key), "missing"),                       # a directory is not a readable file
                     (str(key), str(key), "PEM"), (str(cert), str(cert), "PEM"),
                     (str(cert), str(gkey), "Git"),
                     (str(cert), str(key), "matching pair")]
            for c, k, word in cases:
                with self.subTest(cert=c, key=k), self.assertRaises(DevIdentityRefused) as ctx:
                    rlp.check_tls_files(c, k)
                self.assertIn(word, str(ctx.exception))
                self.assertNotIn("not really", str(ctx.exception))

    def test_this_repository_counts_as_a_git_tree(self):
        self.assertTrue(rlp.inside_git_tree(HOME / "dev" / "preview-key.pem"))

    def test_hostname_must_be_one_dot_local_name(self):
        self.assertEqual("laptop.local", rlp.check_hostname("Laptop.local"))
        self.assertIsNone(rlp.check_hostname(None))
        for bad in ("laptop", "media.avrana.net", "*.local", "a.b.local", "-x.local", "x .local", ""):
            with self.subTest(bad=bad), self.assertRaises(DevIdentityRefused):
                rlp.check_hostname(bad)

    def test_settings_must_point_only_at_this_processes_mocks(self):
        from .support import make_settings
        ports = {"jellyfin": 18096, "abs": 13378, "komga": 25600, "calibre": 18083}
        rlp.check_mock_targets(make_settings(jellyfin_base_url="http://127.0.0.1:18096"), ports)
        for bad in (make_settings(jellyfin_base_url="http://127.0.0.1:9999"),
                    make_settings(jellyfin_base_url="http://10.0.0.218:8096"),
                    make_settings(jellyfin_base_url="http://127.0.0.1:18096",
                                  komga_base_url="https://read.avrana.net"),
                    make_settings(jellyfin_base_url="http://127.0.0.1:18096/prefix"),
                    make_settings(jellyfin_base_url="http://127.0.0.1:18096", upstream_mode="real")):
            with self.subTest(bad=repr(bad)), self.assertRaises(DevIdentityRefused):
                rlp.check_mock_targets(bad, ports)

    def test_build_refuses_before_binding_anything(self):
        ports = free_ports()
        base = dict(cert="c", key="k", acknowledged=True, environ={}, ports=ports, start_mock=False)
        cases = [("192.168.1.23", dict(base, acknowledged=False)),           # no flag
                 ("0.0.0.0", base), ("::", base), ("127.0.0.1", base),       # bind
                 ("192.168.1.23", dict(base, minutes=241)),                  # expiry bound
                 ("192.168.1.23", dict(base, environ={"JELLYFIN_BASE_URL": "x"})),
                 ("192.168.1.23", dict(base, cert=None)),                     # TLS files
                 ("192.168.1.23", base)]                                      # unreadable cert/key
        for host, kw in cases:
            with self.subTest(host=host, kw=sorted(kw)), self.assertRaises(DevIdentityRefused):
                rlp.build(host, 8443, **kw)
        for port in ports.values():                                          # no mock port was taken
            with socket.socket() as s:
                s.bind(("127.0.0.1", port))

    def test_main_exits_2_without_the_flag_or_with_a_bad_bind_or_expiry(self):
        for argv in (["--host", "192.168.1.23"],
                     ["--i-understand-lan", "--host", "0.0.0.0", "--cert", "c", "--key", "k"],
                     ["--i-understand-lan", "--host", "192.168.1.23", "--minutes", "241", "--cert", "c", "--key", "k"],
                     ["--i-understand-lan", "--host", "192.168.1.23"]):
            clean = {k: v for k, v in os.environ.items() if not k.upper().startswith(rlp.REAL_PREFIXES + ("HOME_",))}
            with self.subTest(argv=argv), umock.patch.dict(os.environ, clean, clear=True):
                self.assertEqual(2, rlp.main(argv))


# ---- the gate, as an ASGI app (no network) -----------------------------------------------------------------
class Inner:
    def __init__(self):
        self.scopes = []

    async def __call__(self, scope, receive, send):
        self.scopes.append(scope)
        body = b"<html><body>FIXTURE member-b Continue</body></html>"
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/html"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def call(app, method="GET", path="/", headers=(), body=b"", host=b"192.168.1.23:8443", client=("192.168.1.50", 5)):
    scope = {"type": "http", "method": method, "path": path, "raw_path": path.encode(), "query_string": b"",
             "headers": [(b"host", host)] + list(headers) if host is not None else list(headers),
             "client": client}
    sent, chunks = [], [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        return chunks.pop(0) if chunks else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)
    asyncio.run(app(scope, receive, send))
    start = sent[0]
    out_body = b"".join(m.get("body", b"") for m in sent[1:])
    return start["status"], [(bytes(k).lower(), bytes(v)) for k, v in start["headers"]], out_body


def form(value):
    from urllib.parse import urlencode
    return [(b"content-type", b"application/x-www-form-urlencoded")], urlencode({"passphrase": value}).encode()


def header(headers, name):
    return [v for k, v in headers if k == name]


class GateTests(unittest.TestCase):
    def setUp(self):
        self.inner, self.clock = Inner(), Clock()
        self.gate = lan_gate.LanGate(self.inner, passphrase=PASS, allowed_hosts=["192.168.1.23:8443",
                                                                                 "laptop.local:8443"],
                                     expires_at=self.clock() + 3600, clock=self.clock)

    def unlock(self, value=PASS, client=("192.168.1.50", 5)):
        h, b = form(value)
        return call(self.gate, "POST", lan_gate.UNLOCK_PATH, h, b, client=client)

    def cookie(self):
        status, headers, _ = self.unlock()
        self.assertEqual(303, status)
        return header(headers, b"set-cookie")[0].split(b";")[0]

    def test_no_cookie_gets_only_the_form_and_never_reaches_the_app(self):
        for method, path in (("GET", "/"), ("HEAD", "/"), ("GET", "/sw.js"), ("GET", "/offline"),
                             ("GET", "/_dev/identity/member-b"), ("GET", "/title/jellyfin/abc"),
                             ("POST", "/"), ("GET", lan_gate.UNLOCK_PATH)):
            with self.subTest(method=method, path=path):
                status, headers, body = call(self.gate, method, path)
                self.assertEqual(403, status)
                self.assertNotIn(b"FIXTURE", body)
                self.assertNotIn(b"member", body)
                self.assertTrue(header(headers, b"content-security-policy"))
                self.assertEqual([b"no-store"], header(headers, b"cache-control"))
                self.assertEqual([b"no-referrer"], header(headers, b"referrer-policy"))
        self.assertEqual([], self.inner.scopes)

    def test_wrong_or_missing_host_is_misdirected(self):
        cookie = self.cookie()
        for host in (b"evil.example:8443", b"192.168.1.23", b"192.168.1.23:8444", None):
            with self.subTest(host=host):
                status, _h, body = call(self.gate, headers=[(b"cookie", cookie)], host=host)
                self.assertEqual(421, status)
                self.assertNotIn(b"FIXTURE", body)
        self.assertEqual(200, call(self.gate, headers=[(b"cookie", cookie)], host=b"LAPTOP.local:8443")[0])

    def test_right_passphrase_sets_a_strict_session_cookie_and_serves(self):
        status, headers, _ = self.unlock("  " + PASS + " ")
        self.assertEqual(303, status)
        self.assertEqual([b"/"], header(headers, b"location"))
        cookie = header(headers, b"set-cookie")[0].decode()
        self.assertTrue(cookie.startswith("__Host-avrana_lan="))
        for attr in ("Path=/", "HttpOnly", "Secure", "SameSite=Strict", "Max-Age=3600"):
            self.assertIn(attr, cookie)
        self.assertNotIn("Domain", cookie)
        self.assertNotIn(PASS, cookie)
        pair = cookie.split(";")[0].encode()
        status, _h, body = call(self.gate, headers=[(b"cookie", b"avrana_dev_identity=member-b; " + pair)])
        self.assertEqual(200, status)
        self.assertIn(b"FIXTURE", body)
        inner_cookies = [v for k, v in self.inner.scopes[-1]["headers"] if k == b"cookie"]
        self.assertEqual([b"avrana_dev_identity=member-b"], inner_cookies)       # gate cookie removed
        status, _h, _b = call(self.gate, headers=[(b"cookie", pair)], path=lan_gate.UNLOCK_PATH)
        self.assertEqual(303, status)

    def test_wrong_passphrase_is_refused_then_rate_limited(self):
        for _ in range(lan_gate.MAX_FAILURES - 1):
            status, headers, body = self.unlock("wrong-passphrase-attempt")
            self.assertEqual(403, status)
            self.assertFalse(header(headers, b"set-cookie"))
        self.assertEqual(403, self.unlock("wrong-passphrase-attempt")[0])         # the fifth locks the address
        status, headers, _ = self.unlock()                                         # even the right one now
        self.assertEqual(429, status)
        self.assertFalse(header(headers, b"set-cookie"))
        self.assertEqual(303, self.unlock(client=("192.168.1.51", 5))[0])         # another address is not locked
        self.clock.now += lan_gate.LOCKOUT + 1
        self.assertEqual(303, self.unlock()[0])

    def test_too_many_failures_in_total_seal_the_gate_for_the_run(self):
        for i in range(lan_gate.MAX_TOTAL_FAILURES):
            self.unlock("wrong-passphrase-attempt", client=(f"192.168.1.{100 + i}", 5))
        self.assertTrue(self.gate.sealed)
        self.assertEqual(429, self.unlock(client=("192.168.1.9", 5))[0])

    def test_malformed_unlock_requests_are_refused(self):
        self.assertEqual(403, call(self.gate, "POST", lan_gate.UNLOCK_PATH,
                                   [(b"content-type", b"text/plain")], b"passphrase=" + PASS.encode())[0])
        self.assertEqual(403, call(self.gate, "POST", lan_gate.UNLOCK_PATH,
                                   [(b"content-type", b"application/x-www-form-urlencoded")],
                                   b"passphrase=a&passphrase=" + PASS.encode())[0])
        self.assertEqual(413, call(self.gate, "POST", lan_gate.UNLOCK_PATH,
                                   [(b"content-type", b"application/x-www-form-urlencoded")],
                                   b"passphrase=" + b"x" * 4096)[0])
        self.assertEqual([], self.inner.scopes)

    def test_sessions_end_with_the_run_and_do_not_carry_to_another_run(self):
        cookie = self.cookie()
        other = lan_gate.LanGate(self.inner, passphrase=PASS, allowed_hosts=["192.168.1.23:8443"],
                                 expires_at=self.clock() + 3600, clock=self.clock)
        self.assertEqual(403, call(other, headers=[(b"cookie", cookie)])[0])
        self.assertEqual(403, call(self.gate, headers=[(b"cookie", b"__Host-avrana_lan=forged")])[0])
        self.clock.now += 3601
        self.assertEqual(403, call(self.gate, headers=[(b"cookie", cookie)])[0])
        self.assertEqual(429, self.unlock()[0])

    def test_the_passphrase_is_never_logged_or_shown(self):
        records = []

        class Grab(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))
        grab = Grab(level=logging.DEBUG)
        root = logging.getLogger()
        root.addHandler(grab)
        old = root.level
        root.setLevel(logging.DEBUG)
        try:
            self.unlock()
            for _ in range(lan_gate.MAX_FAILURES + 1):
                _s, _h, body = self.unlock(PASS + "x")
                self.assertNotIn(PASS.encode(), body)
        finally:
            root.removeHandler(grab)
            root.setLevel(old)
        self.assertFalse([r for r in records if PASS in r])
        self.assertNotIn(PASS, repr(self.gate))
        self.assertNotIn(PASS.encode(), b"".join(v for v in vars(self.gate).values() if isinstance(v, bytes)))

    def test_short_passphrase_or_no_hosts_cannot_build_a_gate(self):
        with self.assertRaises(ValueError):
            lan_gate.LanGate(self.inner, passphrase="short", allowed_hosts=["a:1"], expires_at=1.0)
        with self.assertRaises(ValueError):
            lan_gate.LanGate(self.inner, passphrase=PASS, allowed_hosts=[], expires_at=1.0)


# ---- end to end on loopback: the real fixture stack behind the gate ----------------------------------------
class _Serve:
    def __init__(self, app, port):
        import uvicorn
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, http="h11", log_config=None,
                                                    access_log=False, proxy_headers=False, server_header=False))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.port = port

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("uvicorn did not start")
            time.sleep(0.02)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)

    def request(self, method, target, headers=(), body=b""):
        lines = [f"{method} {target} HTTP/1.1".encode(), f"Host: 127.0.0.1:{self.port}".encode()]
        lines += [k.encode() + b": " + v.encode() for k, v in headers]
        lines += [f"Content-Length: {len(body)}".encode(), b"Connection: close"]
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as s:
            s.sendall(b"\r\n".join(lines) + b"\r\n\r\n" + body)
            chunks = []
            while True:
                data = s.recv(65536)
                if not data:
                    break
                chunks.append(data)
        return parse_http(b"".join(chunks))


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port, cls.ports = free_port(), free_ports()
        with umock.patch.object(rlp, "check_tls_files", lambda c, k: (c, k)):
            cls.mock, cls.app, cls.settings, cls.passphrase, cls.seconds = rlp.build(
                "127.0.0.1", cls.port, cert="unused", key="unused", acknowledged=True, minutes=5,
                allow_loopback=True, environ={}, ports=cls.ports)
        cls.serve = _Serve(cls.app, cls.port).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.serve.__exit__(None, None, None)
        rlp.stop_mocks(cls.mock)

    def test_stack_is_the_fixture_stack(self):
        self.assertEqual("mock", self.settings.upstream_mode)
        self.assertEqual(300, self.seconds)
        self.assertEqual(f"http://127.0.0.1:{self.ports['jellyfin']}", self.settings.jellyfin_base_url)
        self.assertGreaterEqual(len(self.passphrase), 20)

    def test_locked_then_unlocked(self):
        locked = self.serve.request("GET", "/", [("Cookie", "avrana_dev_identity=member-b")])
        self.assertEqual(403, locked.status)
        self.assertNotIn("DEVELOPMENT IDENTITY", locked.text)
        self.assertNotIn("Continue", locked.text)
        wrong = self.serve.request("POST", lan_gate.UNLOCK_PATH,
                                   [("Content-Type", "application/x-www-form-urlencoded")], b"passphrase=nope")
        self.assertEqual(403, wrong.status)
        from urllib.parse import quote
        ok = self.serve.request("POST", lan_gate.UNLOCK_PATH, [("Content-Type", "application/x-www-form-urlencoded")],
                                ("passphrase=" + quote(self.passphrase)).encode())
        self.assertEqual(303, ok.status)
        pair = ok.header("set-cookie").split(";")[0]
        home = self.serve.request("GET", "/", [("Cookie", f"{pair}; avrana_dev_identity=member-b")])
        self.assertEqual(200, home.status)
        self.assertIn("DEVELOPMENT IDENTITY: member-b", home.text)
        self.assertTrue(home.header("content-security-policy"))
        sw = self.serve.request("GET", "/sw.js", [("Cookie", pair)])
        self.assertEqual(200, sw.status)
        self.assertIn("javascript", sw.header("content-type"))


class AutoExpiryTests(unittest.TestCase):
    def test_run_server_stops_by_itself(self):
        async def app(scope, receive, send):
            if scope["type"] == "lifespan":
                while True:
                    msg = await receive()
                    if msg["type"] == "lifespan.startup":
                        await send({"type": "lifespan.startup.complete"})
                    elif msg["type"] == "lifespan.shutdown":
                        await send({"type": "lifespan.shutdown.complete"})
                        return
        started = time.monotonic()
        done = threading.Event()

        def run():
            rlp.run_server(app, "127.0.0.1", free_port(), 0.5, cert=None, key=None, hard_stop=False)
            done.set()
        threading.Thread(target=run, daemon=True).start()
        self.assertTrue(done.wait(15), "the server did not stop by itself")
        self.assertLess(time.monotonic() - started, 15)

    def test_main_never_offers_a_background_mode(self):
        source = (HOME / "dev" / "run_lan_preview.py").read_text(encoding="utf-8")
        for word in ("schtasks", "systemd", "daemon=False", "nohup", "subprocess", "Popen", "--background"):
            self.assertNotIn(word, source)
        self.assertTrue(re.search(r"ssl_certfile", source))


if HAVE_CRYPTOGRAPHY:                    # see the module docstring: defined only when the package is present
    class TlsSmokeTests(unittest.TestCase):
        def test_https_on_loopback_with_a_throwaway_certificate(self):
            import datetime
            import ipaddress
            import ssl
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.x509.oid import NameOID
            key = ec.generate_private_key(ec.SECP256R1())
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
            now = datetime.datetime.now(datetime.timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now)
                    .not_valid_after(now + datetime.timedelta(hours=1))
                    .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                                   critical=False).sign(key, hashes.SHA256()))
            with tempfile.TemporaryDirectory() as tmp:
                cpath, kpath = Path(tmp) / "c.pem", Path(tmp) / "k.pem"
                cpath.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
                kpath.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                    serialization.NoEncryption()))
                rlp.check_tls_files(str(cpath), str(kpath))
                port = free_port()
                gate = lan_gate.LanGate(Inner(), passphrase=PASS, allowed_hosts=[f"127.0.0.1:{port}"],
                                        expires_at=time.monotonic() + 60)
                t = threading.Thread(target=rlp.run_server, args=(gate, "127.0.0.1", port, 3),
                                     kwargs={"cert": str(cpath), "key": str(kpath), "hard_stop": False}, daemon=True)
                t.start()
                ctx = ssl.create_default_context(cafile=str(cpath))
                deadline = time.time() + 10
                while True:
                    try:
                        raw = socket.create_connection(("127.0.0.1", port), timeout=5)
                        break
                    except OSError:
                        if time.time() > deadline:
                            raise
                        time.sleep(0.05)
                with ctx.wrap_socket(raw, server_hostname="127.0.0.1") as s:
                    s.sendall(f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode())
                    data = b""
                    while chunk := s.recv(65536):
                        data += chunk
                self.assertEqual(403, parse_http(data).status)
                t.join(15)


if __name__ == "__main__":
    unittest.main()
