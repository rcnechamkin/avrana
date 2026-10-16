"""AVR-498: HOME_IDENTITY_MODE. Settings (Tier A) and the app in each mode (Tier B).

Everything here is synthetic: the HS256 secrets are obviously fake and are never real Authentik
values, the issuer and audience are invented, and tokens are minted in this file only.
Offline: loopback only (the mock Jellyfin), no network, no Authentik.
"""
import base64
import hashlib
import hmac
import json
import logging
import tempfile
import time
import unittest
from pathlib import Path

from avrana_home.app.settings import Settings, SettingsError

from .support import GROUPS, USER, make_client, make_settings, require_framework

ISS = "https://auth.example.test/application/o/synthetic-home/"
AUD = "synthetic-home-client-id"
SECRET = "SYNTHETIC-FIXTURE-SECRET-not-real-0123456789"        # 44 bytes
SECRET2 = "SYNTHETIC-OTHER-FIXTURE-secret-not-real-9876543210"
PREVIOUS = "SYNTHETIC-PREVIOUS-FIXTURE-secret-not-real-aaaaaa"
JWT = "X-authentik-jwt"
GOOD_GROUPS = ["avrana-users", "avrana-videos"]
JWT_ENV = {"HOME_JWT_ISSUER": ISS, "HOME_JWT_AUDIENCE": AUD, "HOME_JWT_SECRET": SECRET}


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def mint(secret=SECRET, header=None, claims=None, **over) -> str:
    """A real HS256 token over the fixture secret. `over` overrides claims; a value of ... drops one."""
    now = int(time.time())
    base = {"iss": ISS, "aud": AUD, "exp": now + 3600, "iat": now - 5, "sub": "synthetic-sub",
            "preferred_username": "member-a", "groups": GOOD_GROUPS}
    base.update(claims or {})
    base.update(over)
    base = {k: v for k, v in base.items() if v is not ...}
    h = b64(json.dumps(header or {"alg": "HS256", "typ": "JWT"}).encode())
    c = b64(json.dumps(base).encode())
    mac = hmac.new(secret.encode(), f"{h}.{c}".encode(), hashlib.sha256).digest()
    return f"{h}.{c}.{b64(mac)}"


def alg_none() -> str:
    h = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    c = b64(json.dumps({"iss": ISS, "aud": AUD, "exp": int(time.time()) + 3600,
                        "preferred_username": "member-a", "groups": GOOD_GROUPS}).encode())
    return f"{h}.{c}."


def other_alg(alg: str) -> str:
    return mint(header={"alg": alg, "typ": "JWT"})


class SettingsTests(unittest.TestCase):
    def env(self, mode=None, **extra):
        e = dict(JWT_ENV)
        e.update(extra)
        if mode is not None:
            e["HOME_IDENTITY_MODE"] = mode
        return e

    def test_default_is_headers_and_changes_nothing(self):
        s = Settings.from_mapping({})
        self.assertEqual("headers", s.identity_mode)
        self.assertEqual("", s.jwt_secret)
        self.assertEqual("headers", Settings().identity_mode)

    def test_the_three_modes_parse(self):
        self.assertEqual("headers", Settings.from_mapping({"HOME_IDENTITY_MODE": "headers"}).identity_mode)
        for mode in ("jwt_log_only", "jwt_required"):
            self.assertEqual(mode, Settings.from_mapping(self.env(mode)).identity_mode)

    def test_unknown_empty_or_miscased_mode_refuses_to_start(self):
        for bad in ("", "  ", "JWT_REQUIRED", "jwt", "required", "off", "none", "headers,jwt_required"):
            with self.subTest(mode=bad), self.assertRaises(SettingsError) as cm:
                Settings.from_mapping({"HOME_IDENTITY_MODE": bad})
            self.assertIn("HOME_IDENTITY_MODE", str(cm.exception))

    def test_jwt_modes_need_issuer_audience_and_secret(self):
        for mode in ("jwt_log_only", "jwt_required"):
            for drop in ("HOME_JWT_ISSUER", "HOME_JWT_AUDIENCE", "HOME_JWT_SECRET"):
                env = self.env(mode)
                del env[drop]
                with self.subTest(mode=mode, missing=drop), self.assertRaises(SettingsError) as cm:
                    Settings.from_mapping(env)
                self.assertIn(drop, str(cm.exception))

    def test_short_secret_refused_and_the_value_is_never_in_the_message(self):
        short = "short-synthetic-secret-31-bytes-xx"[:31]
        self.assertEqual(31, len(short))
        with self.assertRaises(SettingsError) as cm:
            Settings.from_mapping(self.env("jwt_required", HOME_JWT_SECRET=short))
        self.assertIn("at least 32", str(cm.exception))
        self.assertNotIn(short, str(cm.exception))
        Settings.from_mapping(self.env("jwt_required", HOME_JWT_SECRET="x" * 32))      # the floor is 32 bytes

    def test_secret_from_file_and_both_forms_refused(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "secret"
            f.write_text(SECRET + "\n", encoding="utf-8")
            env = self.env("jwt_required")
            del env["HOME_JWT_SECRET"]
            env["HOME_JWT_SECRET_FILE"] = str(f)
            self.assertEqual(SECRET, Settings.from_mapping(env).jwt_secret)
            env["HOME_JWT_SECRET"] = SECRET
            with self.assertRaises(SettingsError):
                Settings.from_mapping(env)
            env2 = self.env("jwt_required")
            del env2["HOME_JWT_SECRET"]
            env2["HOME_JWT_SECRET_FILE"] = str(Path(d) / "absent")
            with self.assertRaises(SettingsError) as cm:
                Settings.from_mapping(env2)
            self.assertNotIn(SECRET, str(cm.exception))

    def test_jwt_settings_in_headers_mode_are_refused_not_ignored(self):
        for env in (dict(JWT_ENV), {"HOME_JWT_ISSUER": ISS}, {"HOME_JWT_SECRET": SECRET}):
            with self.subTest(env=sorted(env)), self.assertRaises(SettingsError) as cm:
                Settings.from_mapping(env)
            self.assertNotIn(SECRET, str(cm.exception))

    def test_previous_secret_is_optional_checked_and_needs_the_current_one(self):
        s = Settings.from_mapping(self.env("jwt_required", HOME_JWT_SECRET_PREVIOUS=PREVIOUS))
        self.assertEqual(PREVIOUS, s.jwt_secret_previous)
        with self.assertRaises(SettingsError):
            Settings.from_mapping(self.env("jwt_required", HOME_JWT_SECRET_PREVIOUS="tiny"))

    def test_secrets_never_appear_in_repr_or_str(self):
        s = Settings.from_mapping(self.env("jwt_required", HOME_JWT_SECRET_PREVIOUS=PREVIOUS))
        for text in (repr(s), str(s), f"{s!r}", repr([s]), repr({"s": s})):
            self.assertNotIn(SECRET, text)
            self.assertNotIn(PREVIOUS, text)
        self.assertIn("jwt_required", repr(s))

    def test_allowlist_parses_and_needs_jwt_required(self):
        self.assertEqual((), Settings.from_mapping(self.env("jwt_required")).allowed_users)
        s = Settings.from_mapping(self.env("jwt_required", HOME_ALLOWED_USERS=" member-a , member-b,member-a"))
        self.assertEqual(("member-a", "member-b"), s.allowed_users)
        for mode in ("jwt_log_only", None):
            env = self.env(mode, HOME_ALLOWED_USERS="member-a") if mode else {"HOME_ALLOWED_USERS": "member-a"}
            with self.subTest(mode=mode), self.assertRaises(SettingsError) as cm:
                Settings.from_mapping(env)
            self.assertIn("HOME_ALLOWED_USERS", str(cm.exception))

    def test_an_empty_or_malformed_allowlist_is_refused_never_everyone(self):
        for bad in ("", " ", ",", "member-a,", "member a", "m" + chr(0xe9), "x" * 151, "a	b"):
            with self.subTest(value=bad), self.assertRaises(SettingsError):
                Settings.from_mapping(self.env("jwt_required", HOME_ALLOWED_USERS=bad))


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_framework()
        from dev.mock_jellyfin import MockJellyfin
        cls.mock = MockJellyfin().start()
        base = dict(home_sections=True, jellyfin_base_url=cls.mock.url, timeout=1.0)
        jwt = dict(jwt_issuer=ISS, jwt_audience=AUD, jwt_secret=SECRET)
        cls.headers_app = make_client(make_settings(**base))
        cls.log_only = make_client(make_settings(identity_mode="jwt_log_only", **jwt, **base))
        cls.required = make_client(make_settings(identity_mode="jwt_required", **jwt, **base))
        for c in (cls.headers_app, cls.log_only, cls.required):
            c.__enter__()

    @classmethod
    def tearDownClass(cls):
        for c in (cls.headers_app, cls.log_only, cls.required):
            c.__exit__(None, None, None)
        cls.mock.stop()

    def setUp(self):
        self.mock.reset()

    @staticmethod
    def plain(user="member-a", groups="|".join(GOOD_GROUPS)):
        return [(USER, user), (GROUPS, groups)]

    def tiles(self, text):
        import re
        return re.findall(r'<a class="tile" href="/([^"]*)"', text)


class ModeTests(Fixture):
    def test_default_app_is_headers_mode_and_ignores_a_token(self):
        app = self.headers_app.fastapi_app
        self.assertEqual("headers", app.state.identity.mode)
        # A forged-looking token alongside valid headers changes nothing; a token alone gives nothing.
        r = self.headers_app.get("/", headers=self.plain() + [(JWT, "garbage")])
        self.assertEqual(["watch", "request", "help"], self.tiles(r.text))
        self.assertEqual(["help"], self.tiles(self.headers_app.get("/", headers=[(JWT, mint())]).text))

    def test_create_app_without_a_mode_is_headers(self):
        from avrana_home.app.main import create_app
        self.assertEqual("headers", create_app(make_settings()).state.identity.mode)

    def test_required_valid_token_gives_the_same_view_as_the_header_path(self):
        want = self.headers_app.get("/", headers=self.plain())
        got = self.required.get("/", headers=[(JWT, mint())])
        self.assertEqual(want.content, got.content)
        want = self.headers_app.get("/account", headers=self.plain())
        got = self.required.get("/account", headers=[(JWT, mint())])
        self.assertEqual(want.content, got.content)

    def test_required_header_only_request_has_no_principal(self):
        empty_home = self.required.get("/").content
        r = self.required.get("/", headers=self.plain())
        self.assertEqual(empty_home, r.content)
        self.assertEqual(["help"], self.tiles(r.text))
        self.assertEqual([], self.mock.paths())

    def test_required_gated_route_with_and_without_a_token(self):
        self.assertEqual(404, self.required.get("/watch", headers=self.plain()).status_code)
        self.assertEqual(404, self.required.get("/watch").status_code)
        self.assertEqual(200, self.required.get("/watch", headers=[(JWT, mint())]).status_code)
        self.assertEqual(self.required.get("/watch").content,
                         self.required.get("/watch", headers=self.plain()).content)

    def test_required_home_json_and_account(self):
        self.assertEqual(404, self.required.get("/home.json", headers=self.plain()).status_code)
        self.assertEqual(404, self.required.get("/home.json").status_code)
        ok = self.required.get("/home.json", headers=[(JWT, mint())])
        self.assertEqual(200, ok.status_code)
        self.assertEqual(self.headers_app.get("/home.json", headers=self.plain()).json(), ok.json())
        acct = self.required.get("/account", headers=self.plain())
        self.assertEqual(200, acct.status_code)
        self.assertNotIn("member-a", acct.text)                     # signed in, no facts
        self.assertIn("member-a", self.required.get("/account", headers=[(JWT, mint())]).text)

    def test_required_bad_tokens_are_the_no_principal_outcome_never_403_or_redirect(self):
        nobody = self.required.get("/").content
        bad = {
            "expired": mint(exp=int(time.time()) - 3600, iat=int(time.time()) - 7200),
            "wrong_aud": mint(aud="synthetic-someone-else"),
            "wrong_iss": mint(iss="https://auth.example.test/application/o/other/"),
            "alg_none": alg_none(),
            "alg_hs512": other_alg("HS512"),
            "alg_rs256": other_alg("RS256"),
            "forged_signature": mint(secret=SECRET2),
            "tampered_groups": mint().rsplit(".", 1)[0].rsplit(".", 1)[0] + "." + b64(
                json.dumps({"iss": ISS, "aud": AUD, "exp": int(time.time()) + 3600,
                            "preferred_username": "member-a",
                            "groups": ["authentik Admins"]}).encode()) + "." + mint().rsplit(".", 1)[1],
            "garbage": "not-a-jwt",
            "empty": "",
        }
        for name, token in bad.items():
            with self.subTest(token=name):
                r = self.required.get("/", headers=[(JWT, token)] + self.plain("member-a", "authentik Admins"))
                self.assertEqual(200, r.status_code)
                self.assertEqual(nobody, r.content)
                for route in ("/watch", "/ops", "/home.json"):
                    gated = self.required.get(route, headers=[(JWT, token)])
                    self.assertEqual(404, gated.status_code, route)
                    self.assertNotIn("location", gated.headers)
        self.assertEqual([], self.mock.paths())

    def test_required_duplicate_jwt_headers_are_refused_even_when_identical(self):
        tok = mint()
        for headers in ([(JWT, tok), (JWT, tok)], [(JWT, tok), ("x-AUTHENTIK-jwt", mint(secret=SECRET2))]):
            r = self.required.get("/", headers=headers)
            self.assertEqual(["help"], self.tiles(r.text))

    def test_required_plain_headers_that_disagree_with_the_claims_are_refused(self):
        tok = mint()
        for headers in (self.plain("member-b"), self.plain("member-a", "authentik Admins"),
                        self.plain("member-a", "avrana-users")):
            with self.subTest(headers=headers):
                r = self.required.get("/", headers=[(JWT, tok)] + headers)
                self.assertEqual(["help"], self.tiles(r.text))
        agree = self.required.get("/", headers=[(JWT, tok)] + self.plain())
        self.assertEqual(["watch", "request", "help"], self.tiles(agree.text))

    def test_required_token_cannot_be_smuggled_through_other_channels(self):
        tok = mint()
        for headers in ([("Authorization", "Bearer " + tok)], [("Cookie", "X-authentik-jwt=" + tok)],
                        [("X-Forwarded-User", "member-a")]):
            self.assertEqual(["help"], self.tiles(self.required.get("/", headers=headers).text))
        self.assertEqual(["help"], self.tiles(self.required.get("/?X-authentik-jwt=" + tok).text))

    def test_required_secret_rotation_accepts_the_previous_secret_only_when_configured(self):
        s = make_settings(identity_mode="jwt_required", jwt_issuer=ISS, jwt_audience=AUD,
                          jwt_secret=SECRET, jwt_secret_previous=PREVIOUS, home_sections=False)
        with make_client(s) as c:
            self.assertEqual(["watch", "request", "help"],
                             self.tiles(c.get("/", headers=[(JWT, mint(secret=PREVIOUS))]).text))
            self.assertEqual(["help"], self.tiles(c.get("/", headers=[(JWT, mint(secret=SECRET2))]).text))
        self.assertEqual(["help"], self.tiles(self.required.get("/", headers=[(JWT, mint(secret=PREVIOUS))]).text))



class LogOnlyTests(Fixture):
    def capture(self):
        records = []

        class H(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = H(level=logging.DEBUG)
        log = logging.getLogger("avrana_home.app")
        old = log.level
        log.setLevel(logging.INFO)
        log.addHandler(handler)
        self.addCleanup(lambda: (log.removeHandler(handler), log.setLevel(old)))
        return records

    def codes(self, records):
        return [r.avrana_fields["reason"] for r in records if r.msg == "identity_jwt"]

    def test_log_only_serves_the_header_identity_exactly_like_headers_mode(self):
        for headers in (self.plain(), self.plain("member-b", "avrana-users|avrana-comics"), []):
            self.assertEqual(self.headers_app.get("/", headers=headers).content,
                             self.log_only.get("/", headers=headers).content)

    def test_log_only_never_serves_the_jwt_identity(self):
        # Token alone (no plain headers): nothing is served. The token does not become identity.
        r = self.log_only.get("/", headers=[(JWT, mint())])
        self.assertEqual(["help"], self.tiles(r.text))
        self.assertEqual(404, self.log_only.get("/watch", headers=[(JWT, mint())]).status_code)
        # Token for member-a, plain headers for a different member: the header member is served.
        r = self.log_only.get("/account", headers=[(JWT, mint())] + self.plain("member-b", "avrana-users"))
        self.assertIn("member-b", r.text)
        self.assertNotIn("member-a", r.text)

    def test_log_only_reports_fixed_codes_only(self):
        records = self.capture()
        hdr = self.plain()
        self.log_only.get("/", headers=hdr + [(JWT, mint())])
        self.log_only.get("/", headers=hdr)
        self.log_only.get("/", headers=hdr + [(JWT, mint(secret=SECRET2))])
        self.log_only.get("/", headers=self.plain("member-b") + [(JWT, mint())])
        self.log_only.get("/", headers=hdr + [(JWT, mint()), (JWT, mint())])
        self.assertEqual(["ok", "missing_header", "unverified_identity", "identity_mismatch", "duplicate_header"],
                         self.codes(records))

    def test_a_non_ascii_token_header_does_not_drop_the_header_identity_in_log_only(self):
        # Review #52 F1: a malformed token header must be reported, not take the plain sign-in down.
        records = self.capture()
        bad = (JWT.encode("ascii"), ("x" + chr(0xe9)).encode("utf-8"))
        hdr = [(n.encode("ascii"), v.encode("ascii")) for n, v in self.plain()]
        self.assertEqual(self.headers_app.get("/", headers=self.plain()).content,
                         self.log_only.get("/", headers=hdr + [bad]).content)
        self.assertEqual(["malformed_header", "missing_header"], self.codes(records))
        # jwt_required still fails closed on the same request.
        self.assertEqual(["help"], self.tiles(self.required.get("/", headers=hdr + [bad]).text))

    def test_log_lines_never_carry_secrets_tokens_or_identity(self):
        from avrana_home.app.logsafe import ForbiddenValues
        records = self.capture()
        tok = mint()
        self.log_only.get("/", headers=self.plain() + [(JWT, tok), ("X-authentik-email", "a@example.test")])
        self.log_only.get("/", headers=self.plain() + [(JWT, mint(secret=SECRET2))])
        self.assertTrue(records)
        scan = ForbiddenValues([SECRET, SECRET2, tok, tok.split(".")[1], "member-a", "a@example.test"])
        for rec in records:
            self.assertEqual([], scan.scan(rec))

    def test_headers_mode_logs_no_identity_line(self):
        records = self.capture()
        self.headers_app.get("/", headers=self.plain() + [(JWT, mint())])
        self.required.get("/", headers=[(JWT, mint())])
        self.assertEqual([], self.codes(records))


class AllowlistTests(Fixture):
    """The beta's second lock: a verified member who is not on HOME_ALLOWED_USERS gets nothing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.beta = make_client(make_settings(identity_mode="jwt_required", jwt_issuer=ISS, jwt_audience=AUD,
                                             jwt_secret=SECRET, allowed_users=("member-a",),
                                             home_sections=True, jellyfin_base_url=cls.mock.url, timeout=1.0))
        cls.beta.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.beta.__exit__(None, None, None)
        super().tearDownClass()

    def test_the_listed_tester_is_served_like_jwt_required(self):
        hdr = [(JWT, mint())]
        self.assertEqual(self.required.get("/", headers=hdr).content, self.beta.get("/", headers=hdr).content)
        self.assertIn("member-a", self.beta.get("/account", headers=hdr).text)

    def test_a_verified_member_not_on_the_list_gets_no_principal(self):
        hdr = [(JWT, mint(preferred_username="member-b"))]
        self.assertNotEqual(["help"], self.tiles(self.required.get("/", headers=hdr).text))   # valid token
        self.assertEqual(["help"], self.tiles(self.beta.get("/", headers=hdr).text))
        for path in ("/watch", "/home.json"):
            self.assertEqual(404, self.beta.get(path, headers=hdr).status_code)
        self.assertNotIn("member-b", self.beta.get("/account", headers=hdr).text)

    def test_matching_is_exact(self):
        for name in ("Member-A", "member-a ", "member-aa", "member"):
            with self.subTest(name=name):
                hdr = [(JWT, mint(preferred_username=name))]
                self.assertEqual(["help"], self.tiles(self.beta.get("/", headers=hdr).text))

    def test_resolver_refuses_an_allowlist_outside_jwt_required(self):
        from avrana_home.app.identity import IdentityResolver
        with self.assertRaises(SettingsError):
            IdentityResolver(allowed_users=("member-a",))


class StartupTests(unittest.TestCase):
    def test_app_refuses_a_jwt_mode_without_usable_settings(self):
        require_framework()
        from avrana_home.app.main import create_app
        base = dict(home_sections=False)
        for kw in (dict(identity_mode="jwt_required"),                                     # nothing
                   dict(identity_mode="jwt_required", jwt_issuer=ISS, jwt_audience=AUD),    # no secret
                   dict(identity_mode="jwt_required", jwt_issuer=ISS, jwt_audience=AUD, jwt_secret="short"),
                   dict(identity_mode="jwt_log_only", jwt_issuer="", jwt_audience=AUD, jwt_secret=SECRET),
                   dict(identity_mode="bogus")):
            with self.subTest(kw=sorted(kw)), self.assertRaises(SettingsError):
                create_app(make_settings(**base, **kw))

    def test_app_repr_and_state_never_expose_the_secret(self):
        require_framework()
        from avrana_home.app.main import create_app
        app = create_app(make_settings(identity_mode="jwt_required", jwt_issuer=ISS, jwt_audience=AUD,
                                       jwt_secret=SECRET, home_sections=False))
        self.assertNotIn(SECRET, repr(app.state.settings))
        self.assertNotIn(SECRET, repr(app.state.identity.__dict__.get("mode")))

    def test_dev_identity_shim_refuses_a_jwt_mode_and_never_mints_tokens(self):
        require_framework()
        from dev import dev_identity
        ok = Settings.from_mapping({})
        dev_identity.check_startup(enabled=True, host="127.0.0.1", settings=ok)
        for mode in ("jwt_log_only", "jwt_required"):
            s = Settings.from_mapping({**JWT_ENV, "HOME_IDENTITY_MODE": mode})
            with self.subTest(mode=mode), self.assertRaises(dev_identity.DevIdentityRefused):
                dev_identity.check_startup(enabled=True, host="127.0.0.1", settings=s)
        src = Path(dev_identity.__file__).read_text(encoding="utf-8")
        for needle in ("hmac", "hashlib", "HS256", "jwt_secret", "HOME_JWT"):
            self.assertNotIn(needle, src.replace("HOME_IDENTITY_MODE must be headers", ""))
        # Even in headers mode a client-supplied token is stripped by the shim, never passed on.
        kept = dev_identity._rewrite_headers([(b"x-authentik-jwt", b"abc"), (b"accept", b"*/*")], "member-a")
        self.assertNotIn(b"x-authentik-jwt", [k for k, _ in kept])


if __name__ == "__main__":
    unittest.main()
