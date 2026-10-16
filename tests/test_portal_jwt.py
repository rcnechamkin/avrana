"""AVR-498: portal verified-JWT identity behind a default-off mode switch (offline, stdlib only).

Fixture secrets and invented identities only; nothing is read from the environment or the network. The real
`Handler` is served on 127.0.0.1 with the mode set on a subclass, so no module state is changed. The existing
authorization suite (test_portal_authz.py) exercises the default `headers` mode unchanged; this file adds the
JWT modes, the vendored-verifier pin and the attack classes also covered for avrana-home.
"""
import ast
import base64
import hashlib
import hmac
import http.client
import importlib.util
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fixtures.identities import ADMIN, AUDIOBOOKS, BASELINE, BOOKS, IDENTITIES, VIDEOS  # noqa: E402
from test_portal_authz import ROUTES, expected  # noqa: E402

ROOT = HERE.parent
PORTAL_DIR = ROOT / "services" / "avrana-portal"
CANONICAL = ROOT / "services" / "avrana-home" / "avrana_home" / "outpost_jwt.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


portal = _load("portal_under_jwt_test", PORTAL_DIR / "portal.py")
vendored = _load("portal_jwt_under_test", PORTAL_DIR / "portal_jwt.py")

ISS = "https://auth.example.test/application/o/avrana-portal/"
AUD = "synthetic-portal-client"
NOW = 1_800_000_000
SECRET = b"synthetic-portal-secret-" + b"s" * 40
OTHER_SECRET = b"synthetic-other-secret-" + b"o" * 40
PREVIOUS_SECRET = b"synthetic-previous-secret-" + b"p" * 40


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def token(secret=SECRET, header=None, **over):
    payload = {"iss": ISS, "aud": AUD, "exp": NOW + 3600, "iat": NOW - 10, "sub": "synthetic-sub",
               "preferred_username": "member-a", "groups": [BASELINE, BOOKS]}
    payload.update(over)
    payload = {k: v for k, v in payload.items() if v is not ...}
    h = b64(json.dumps(header or {"alg": "HS256", "typ": "JWT"}).encode())
    c = b64(json.dumps(payload).encode())
    return f"{h}.{c}.{b64(hmac.new(secret, f'{h}.{c}'.encode(), hashlib.sha256).digest())}"


def make_verifier(*secrets):
    return vendored.OutpostJwtVerifier(issuer=ISS, audience=AUD, hmac_secrets=secrets or (SECRET,),
                                       clock=lambda: NOW)


class _Server(ThreadingHTTPServer):
    request_queue_size = 128


def serve(mode, verifier=None, report=None):
    attrs = {"IDENTITY_MODE": mode, "JWT_VERIFIER": verifier, "disable_nagle_algorithm": True}
    if report is not None:
        attrs["JWT_REPORT"] = staticmethod(report)
    handler = type("TestHandler", (portal.Handler,), attrs)
    server = _Server(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread


def get(server, route, headers):
    """headers: list of (name, value) so duplicates can be sent."""
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    try:
        conn.putrequest("GET", route, skip_host=False, skip_accept_encoding=True)
        for name, value in headers:
            conn.putheader(name, value)
        conn.endheaders()
        resp = conn.getresponse()
        return resp.status, resp.getheader("Location"), resp.read().decode("utf-8", "replace")
    finally:
        conn.close()


def plain(groups, username="member-a"):
    return [("X-authentik-username", username), ("X-authentik-groups", "|".join(groups))]


class Base(unittest.TestCase):
    mode = "jwt_required"
    reports = None

    @classmethod
    def setUpClass(cls):
        cls.reports = []
        cls.server, cls.thread = serve(cls.mode, make_verifier(), cls.reports.append)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def get(self, route, headers):
        return get(self.server, route, headers)

    def assert_no_identity(self, headers, msg=""):
        """The request must look exactly like one with no identity headers at all."""
        for route in ROUTES:
            with self.subTest(route=route, msg=msg):
                self.assertEqual(self.get(route, headers)[:2], self.get(route, [])[:2])
        status, _loc, body = self.get("/account", headers)
        self.assertEqual(status, 200)
        self.assertNotIn("member-a", body)
        self.assertEqual(self.get("/ops", headers)[0], 404)
        self.assertEqual(self.get("/watch", headers)[0], 404)


# ---------------------------------------------------------------------------------------------
class VendoredVerifierPinTests(unittest.TestCase):
    # Update ONLY together with a deliberate, reviewed change to the vendored file.
    PINNED_SHA256 = "62cccaa5d8af807783d785aed72a647653ed997f1312c849e572202e653d4db2"

    SHARED = ("HMAC_ALG", "MIN_HMAC_SECRET", "MAX_TOKEN_LEN", "DEFAULT_LEEWAY", "MAX_LEEWAY", "_B64URL",
              "_FORBIDDEN_HEADER_KEYS", "MAX_TIMESTAMP", "DEFAULT_MAX_LIFETIME", "MAX_LIFETIME_LIMIT", "JwtRejected", "_b64url_decode", "_no_constants", "_no_duplicates",
              "_json_object", "_is_group_name", "_is_number")
    SHARED_METHODS = ("verify", "_check_claims")

    @staticmethod
    def segments(path):
        src = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(src)
        out = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                out[node.name] = ast.get_source_segment(src, node)
                if node.name == "OutpostJwtVerifier":
                    for m in node.body:
                        if isinstance(m, ast.FunctionDef):
                            out["OutpostJwtVerifier." + m.name] = ast.get_source_segment(src, m)
            elif isinstance(node, ast.Assign):
                out[node.targets[0].id] = ast.get_source_segment(src, node)
        return out

    def test_file_hash_is_pinned(self):
        digest = hashlib.sha256((PORTAL_DIR / "portal_jwt.py").read_bytes()).hexdigest()
        self.assertEqual(digest, self.PINNED_SHA256,
                         "portal_jwt.py changed: re-sync with avrana_home/outpost_jwt.py and update the pin")

    def test_shared_code_is_identical_to_the_canonical_module(self):
        canonical, copy = self.segments(CANONICAL), self.segments(PORTAL_DIR / "portal_jwt.py")
        names = list(self.SHARED) + ["OutpostJwtVerifier." + m for m in self.SHARED_METHODS]
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, canonical)
                self.assertIn(name, copy)
                self.assertEqual(copy[name], canonical[name])

    def test_the_copy_is_hs256_only_and_stdlib_only(self):
        src = (PORTAL_DIR / "portal_jwt.py").read_text(encoding="utf-8")
        for forbidden in ("RsaPublicKey", "pow(", "from_pem", "from_jwks", "RS256", "_DIGEST_INFO"):
            self.assertNotIn(forbidden, src)
        tree = ast.parse(src)
        roots = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        roots |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertLessEqual(roots, {"__future__", "base64", "binascii", "hashlib", "hmac", "json", "math",
                                     "re", "time", "typing"})

    def test_portal_imports_only_the_standard_library(self):
        tree = ast.parse((PORTAL_DIR / "portal.py").read_text(encoding="utf-8"))
        roots = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        roots |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertLessEqual(roots, {"__future__", "html", "importlib", "os", "sys", "unicodedata", "http"})


# ---------------------------------------------------------------------------------------------
class DefaultOffTests(unittest.TestCase):
    def test_default_mode_is_headers_and_nothing_enables_jwt(self):
        self.assertEqual(portal.Handler.IDENTITY_MODE, "headers")
        self.assertIsNone(portal.Handler.JWT_VERIFIER)
        for rel in ("Dockerfile", "docker-compose.yml"):
            text = (PORTAL_DIR / rel).read_text(encoding="utf-8")
            self.assertNotIn("AVRANA_IDENTITY_MODE", text)
            self.assertNotIn("AVRANA_JWT", text)

    def test_headers_mode_ignores_the_token_entirely(self):
        server, thread = serve("headers", make_verifier())
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(5)))
        for name, groups in IDENTITIES.items():
            headers = [] if groups is None else [("X-authentik-groups", "|".join(groups))]
            for extra in ([], [("X-authentik-jwt", token(groups=[ADMIN]))], [("X-authentik-jwt", "garbage")]):
                for route in ("/", "/ops", "/watch", "/account", "/help/movies"):
                    with self.subTest(identity=name, route=route, jwt=bool(extra)):
                        self.assertEqual(get(server, route, headers + extra), get(server, route, headers))

    def test_unknown_mode_or_missing_settings_stop_the_service(self):
        for env, text in (({"AVRANA_IDENTITY_MODE": "jwt"}, "AVRANA_IDENTITY_MODE"),
                          ({"AVRANA_IDENTITY_MODE": "JWT_REQUIRED"}, "AVRANA_IDENTITY_MODE"),
                          ({"AVRANA_IDENTITY_MODE": ""}, "AVRANA_IDENTITY_MODE")):
            with self.subTest(env=env):
                saved = dict(portal.os.environ)
                portal.os.environ.update(env)
                try:
                    with self.assertRaises(SystemExit) as caught:
                        portal.main()
                finally:
                    portal.os.environ.clear()
                    portal.os.environ.update(saved)
                self.assertIn(text, str(caught.exception))

    def test_jwt_modes_need_complete_settings_and_never_echo_values(self):
        full = {"AVRANA_JWT_ISSUER": ISS, "AVRANA_JWT_AUDIENCE": AUD, "AVRANA_JWT_SECRET": SECRET.decode()}
        self.assertIsNotNone(portal.build_verifier(full))
        self.assertIsNotNone(portal.build_verifier(dict(full, AVRANA_JWT_SECRET_PREVIOUS=PREVIOUS_SECRET.decode())))
        for key in full:
            with self.subTest(missing=key), self.assertRaises(SystemExit) as caught:
                portal.build_verifier({k: v for k, v in full.items() if k != key})
            self.assertIn(key, str(caught.exception))
            self.assertNotIn(SECRET.decode(), str(caught.exception))
        with self.assertRaises(SystemExit) as caught:
            portal.build_verifier(dict(full, AVRANA_JWT_SECRET="short"))
        self.assertNotIn("short", str(caught.exception).replace("at least", ""))

    def test_misconfigured_jwt_modes_fail_closed(self):
        for mode in ("jwt_required", "no_such_mode"):
            server, thread = serve(mode, None)
            try:
                self.assertEqual(get(server, "/ops", plain([ADMIN]) + [("X-authentik-jwt", token())])[0], 404)
                self.assertEqual(get(server, "/watch", plain([VIDEOS]))[0], 404)
            finally:
                server.shutdown(), server.server_close(), thread.join(5)


# ---------------------------------------------------------------------------------------------
class RequiredModeMatrixTests(Base):
    def test_route_matrix_matches_the_header_path_for_every_identity(self):
        for name, groups in IDENTITIES.items():
            if not groups:
                continue  # no usable group list can be a token (covered as "no identity" below)
            tok = token(groups=groups)
            for route in ROUTES:
                with self.subTest(identity=name, route=route):
                    status, location, _ = self.get(route, [("X-authentik-jwt", tok)])
                    self.assertEqual((status, location), expected(route, set(groups)))

    def test_identity_headers_that_agree_with_the_token_are_accepted(self):
        tok = token(groups=[BASELINE, VIDEOS])
        headers = [("X-authentik-jwt", tok)] + plain([VIDEOS, BASELINE])
        self.assertEqual(self.get("/watch", headers)[0], 200)

    def test_two_members_get_their_own_identity_and_entitlements(self):
        a = token(preferred_username="member-a", groups=[BASELINE, BOOKS], email="a@example.test", name="Member A")
        b = token(preferred_username="member-b", groups=[BASELINE, VIDEOS, ADMIN], email="b@example.test",
                  name="Member B")
        _, _, page_a = self.get("/account", [("X-authentik-jwt", a)])
        _, _, page_b = self.get("/account", [("X-authentik-jwt", b)])
        self.assertIn("member-a", page_a)
        self.assertNotIn("member-b", page_a)
        self.assertIn("member-b", page_b)
        self.assertNotIn("member-a", page_b)
        self.assertEqual(self.get("/books", [("X-authentik-jwt", a)])[0], 307)
        self.assertEqual(self.get("/books", [("X-authentik-jwt", b)])[0], 404)
        self.assertEqual(self.get("/ops", [("X-authentik-jwt", a)])[0], 404)
        self.assertEqual(self.get("/ops", [("X-authentik-jwt", b)])[0], 307)

    def test_header_only_identity_is_refused(self):
        self.assert_no_identity(plain([ADMIN, BASELINE, VIDEOS]), "admin headers, no token")
        self.assert_no_identity(plain([ADMIN]) + [("X-authentik-jwt", "")], "empty token")


class RequiredModeAttackTests(Base):
    def test_every_unverifiable_token_is_the_same_as_no_identity(self):
        good = token(groups=[ADMIN, BASELINE, VIDEOS])
        h, c, s = good.split(".")
        forged_claims = b64(json.dumps({"iss": ISS, "aud": AUD, "exp": NOW + 3600, "iat": NOW - 10,
                                        "preferred_username": "member-a", "groups": [ADMIN]}).encode())
        none = b64(json.dumps({"alg": "none"}).encode()) + "." + c + "."
        rs = token(header={"alg": "RS256", "kid": "x"})
        attacks = {
            "forged signature (other secret)": token(OTHER_SECRET, groups=[ADMIN]),
            "claims edited, signature kept": f"{h}.{forged_claims}.{s}",
            "wrong issuer": token(iss="https://evil.example.test/", groups=[ADMIN]),
            "wrong audience": token(aud="synthetic-home-client", groups=[ADMIN]),
            "audience list without this client": token(aud=["a", "b"], groups=[ADMIN]),
            "expired": token(exp=NOW - 3600, groups=[ADMIN]),
            "not yet valid (nbf)": token(nbf=NOW + 3600, groups=[ADMIN]),
            "issued in the future (iat)": token(iat=NOW + 3600, groups=[ADMIN]),
            "alg none": none,
            "alg none, no signature part": none.rstrip(".") + ".",
            "alg RS256 on an HS256 verifier": rs,
            "alg HS384": token(header={"alg": "HS384"}, groups=[ADMIN]),
            "alg lower case": token(header={"alg": "hs256"}, groups=[ADMIN]),
            "jku in header": token(header={"alg": "HS256", "jku": "https://evil.example.test/k"}, groups=[ADMIN]),
            "missing username": token(preferred_username=..., groups=[ADMIN]),
            "missing groups": token(groups=...),
            "empty groups": token(groups=[]),
            "missing iat": token(iat=..., groups=[ADMIN]),
            "group with separator": token(groups=["a|authentik Admins"]),
            "huge integer exp": token(exp=10 ** 400, groups=[ADMIN]),
            "exp far in the future (lifetime cap)": token(exp=NOW + 10 ** 9, groups=[ADMIN]),
            "deeply nested header": b64(("[" * 10000).encode()) + "." + c + "." + s,
            "deeply nested claims": h + "." + b64(("[" * 10000).encode()) + "." + s,
            "garbage": "not-a-token",
            "two dots": "..",
            "oversized": "x" * 20000,
            "non-ascii": "é" + good,
        }
        for label, tok in attacks.items():
            with self.subTest(attack=label):
                try:
                    headers = [("X-authentik-jwt", tok)]
                    self.assert_no_identity(headers, label)
                    self.assert_no_identity(headers + plain([ADMIN, VIDEOS]), label + " + admin headers")
                except UnicodeEncodeError:
                    pass  # http.client refuses to send a non-latin-1 header; nothing reaches the portal

    def test_valid_token_with_conflicting_plain_headers_is_refused(self):
        tok = token(groups=[BASELINE, BOOKS])
        for extra in (plain([BASELINE, BOOKS, ADMIN]), plain([BASELINE]), plain([BASELINE, BOOKS], "member-b"),
                      [("X-authentik-groups", ADMIN)]):
            with self.subTest(extra=extra):
                self.assert_no_identity([("X-authentik-jwt", tok)] + extra)

    def test_duplicate_or_repeated_tokens_are_refused(self):
        good = token(groups=[BASELINE, VIDEOS])
        other = token(preferred_username="member-b", groups=[BASELINE, BOOKS])
        for headers in ([("X-authentik-jwt", good), ("X-authentik-jwt", good)],
                        [("X-authentik-jwt", good), ("x-authentik-jwt", other)],
                        [("X-authentik-jwt", other), ("X-authentik-jwt", good)]):
            self.assert_no_identity(headers)

    def test_replay_across_audiences_and_secrets(self):
        for name, tok in (("home audience, same secret", token(aud="synthetic-home-client", groups=[ADMIN])),
                          ("kindle audience", token(aud="synthetic-kindle-client", groups=[ADMIN])),
                          ("this audience, other service's secret", token(OTHER_SECRET, groups=[ADMIN]))):
            with self.subTest(replay=name):
                self.assert_no_identity([("X-authentik-jwt", tok)])
        # An edited audience still needs the secret.
        h, c, s = token(aud="synthetic-home-client", groups=[ADMIN]).split(".")
        c2 = b64(json.dumps({"iss": ISS, "aud": AUD, "exp": NOW + 3600, "iat": NOW - 10,
                             "preferred_username": "member-a", "groups": [ADMIN]}).encode())
        self.assert_no_identity([("X-authentik-jwt", f"{h}.{c2}.{s}")])

    def test_single_character_mutations_never_grant_identity(self):
        good = token(groups=[BASELINE, VIDEOS])
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        step = max(1, len(good) // 40)
        for i in range(0, len(good), step):
            if good[i] == ".":
                continue
            mutated = good[:i] + alphabet[(alphabet.index(good[i]) + 1) % 64] + good[i + 1:]
            with self.subTest(index=i):
                self.assertEqual(self.get("/watch", [("X-authentik-jwt", mutated)])[0], 404)

    def test_rotation_overlap_in_the_vendored_verifier(self):
        both = make_verifier(SECRET, PREVIOUS_SECRET)
        self.assertTrue(both.verify(token(SECRET)) and both.verify(token(PREVIOUS_SECRET)))
        with self.assertRaises(vendored.JwtRejected):
            make_verifier(SECRET).verify(token(PREVIOUS_SECRET))


# ---------------------------------------------------------------------------------------------
class LogOnlyModeTests(Base):
    mode = "jwt_log_only"

    def setUp(self):
        self.reports.clear()

    def test_serves_from_headers_whatever_the_token_says(self):
        for tok in (None, "garbage", token(OTHER_SECRET, groups=[ADMIN]), token(groups=[ADMIN])):
            headers = plain([BASELINE, VIDEOS]) + ([] if tok is None else [("X-authentik-jwt", tok)])
            with self.subTest(token=str(tok)[:10]):
                self.assertEqual(self.get("/watch", headers)[0], 200)
                self.assertEqual(self.get("/ops", headers)[0], 404)

    def test_no_headers_means_no_identity_even_with_a_valid_token(self):
        self.assert_no_identity([("X-authentik-jwt", token(groups=[ADMIN, BASELINE, VIDEOS]))])

    def test_reports_fixed_codes_only(self):
        cases = [(plain([BASELINE, BOOKS]) + [("X-authentik-jwt", token(groups=[BASELINE, BOOKS]))], "ok"),
                 (plain([BASELINE, BOOKS]), "missing_header"),
                 (plain([BASELINE, BOOKS]) + [("X-authentik-jwt", token(OTHER_SECRET))], "unverified_identity"),
                 (plain([BASELINE, VIDEOS]) + [("X-authentik-jwt", token(groups=[BASELINE, BOOKS]))],
                  "identity_mismatch"),
                 (plain([BASELINE]) + [("X-authentik-jwt", token()), ("X-authentik-jwt", token())],
                  "duplicate_header")]
        for headers, code in cases:
            self.reports.clear()
            self.get("/", headers)
            self.assertEqual(self.reports, [code])
        self.assertTrue(all(c.replace("_", "").isalpha() for c in self.reports))

    def test_a_failing_report_hook_changes_nothing(self):
        def boom(code):
            raise RuntimeError(code)

        server, thread = serve("jwt_log_only", make_verifier(), boom)
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(5)))
        self.assertEqual(get(server, "/watch", plain([BASELINE, VIDEOS]))[0], 200)
        self.assertEqual(get(server, "/watch", [])[0], 404)

    def test_default_report_writes_one_code_line_to_stderr_and_no_identity(self):
        import io
        server, thread = serve("jwt_log_only", make_verifier())
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(5)))
        saved, sys.stderr = sys.stderr, io.StringIO()
        try:
            get(server, "/account", plain([BASELINE, BOOKS]) + [("X-authentik-jwt", token(groups=[BASELINE, BOOKS]))])
            written = sys.stderr.getvalue()
        finally:
            sys.stderr = saved
        self.assertEqual(written, "identity_jwt=ok\n")


if __name__ == "__main__":
    unittest.main()
