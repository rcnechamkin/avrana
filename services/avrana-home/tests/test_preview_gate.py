"""The owner preview (preview/): password gate, fixed owner identity, startup refusals, the sealed settings
path and the per-service member-username override. Standard library only, no sockets, synthetic values."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import base64
import logging
import re
import tempfile
import unittest
from pathlib import Path

from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.app import settings as settings_mod
from avrana_home.app.settings import _OWNER_PREVIEW_SEAL, Settings, SettingsError
from avrana_home.contract import SectionState
from avrana_home.resilience import FakeClock
from preview import gate
from preview.gate import (LOCKOUT, MAX_FAILURES, OwnerIdentity, PasswordGate, PreviewRefused, check_bind,
                          check_preview_startup, owner_headers, read_password)
from tests.fake_abs import FakeAudiobookshelf
from tests.fake_jellyfin import FakeJellyfin, FakeTransport
from tests.helpers import make_principal

HOME = Path(__file__).resolve().parents[1]
PASSWORD = "synthetic-preview-pass-0001"          # a test value, not anyone's password
GROUPS = ("avrana-users", "avrana-videos", "avrana-audiobooks", "avrana-comics", "avrana-books")


def basic(password, user="anything"):
    return b"Basic " + base64.b64encode(f"{user}:{password}".encode())


class Inner:
    """Records every scope that got through; answers 200."""

    def __init__(self):
        self.scopes = []

    async def __call__(self, scope, receive, send):
        self.scopes.append(scope)
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"inner"})


def scope(path="/", headers=(), client=("192.0.2.10", 5000), method="GET", query=b""):
    return {"type": "http", "method": method, "path": path, "raw_path": path.encode(), "query_string": query,
            "headers": [(k.lower() if isinstance(k, bytes) else k.lower().encode(),
                         v if isinstance(v, bytes) else v.encode()) for k, v in headers],
            "client": client}


def drive(coro):
    """Run a coroutine that never really suspends (these layers do no I/O of their own). No event loop:
    the adapter suite forbids sockets, and an asyncio loop on Windows opens a socket pair."""
    try:
        coro.send(None)
    except StopIteration:
        return
    raise AssertionError("the coroutine suspended")


def run(app, sc):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)
    drive(app(sc, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body


def checked_seal():
    s = Settings.from_mapping({"HOME_OWNER_PREVIEW": "yes", "HOME_SECTIONS": "on",
                               "PREVIEW_OWNER_USERNAME": "akadmin"}, owner_preview_seal=_OWNER_PREVIEW_SEAL)
    return check_preview_startup(password=PASSWORD.encode(), settings=s, host="127.0.0.1", in_container=False)


class GateBase(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.inner = Inner()
        self.gate = PasswordGate(self.inner, password=PASSWORD.encode(), checked=checked_seal(),
                                 clock=lambda: self.now[0])

    def req(self, **kw):
        return run(self.gate, scope(**kw))


class PasswordGateTests(GateBase):
    def test_no_password_is_401_with_the_realm_and_nothing_inside_runs(self):
        for path in ("/", "/home.json", "/healthz", "/readyz", "/search", "/art/x", "/nope", "/_dev/identity"):
            status, headers, body = self.req(path=path)
            self.assertEqual(401, status, path)
            self.assertEqual(b'Basic realm="Avrana preview"', headers[b"www-authenticate"])
            self.assertEqual(b"no-store", headers[b"cache-control"])
            self.assertNotIn(b"inner", body)
        self.assertEqual([], self.inner.scopes)

    def test_wrong_or_malformed_credentials_are_401_and_nothing_inside_runs(self):
        for value in (basic("wrong-password-0000000"), basic(PASSWORD + "x"), basic(PASSWORD[:-1]),
                      basic(PASSWORD.upper()), b"Basic", b"Basic !!!notbase64", b"Bearer " + basic(PASSWORD)[6:],
                      b"Basic " + base64.b64encode(PASSWORD.encode()),             # no colon at all
                      b"Digest username=x"):
            status, _, _ = self.req(headers=[(b"authorization", value)])
            self.assertEqual(401, status, value)
            self.now[0] += 61                                                     # keep the throttle out of it
        status, _, _ = self.req(headers=[(b"authorization", basic(PASSWORD)), (b"Authorization", basic(PASSWORD))])
        self.assertEqual(401, status)                                             # two headers: refused
        self.assertEqual([], self.inner.scopes)

    def test_the_right_password_with_any_username_gets_through_without_the_header(self):
        for user in ("anything", "", "akadmin", "someone-else"):
            status, _, body = self.req(headers=[(b"authorization", basic(PASSWORD, user))])
            self.assertEqual((200, b"inner"), (status, body), user)
        self.assertEqual(4, len(self.inner.scopes))
        for sc in self.inner.scopes:
            self.assertEqual([], [k for k, _ in sc["headers"] if k.lower() == b"authorization"])
        status, _, _ = self.req(headers=[(b"AUTHORIZATION", b"basic " + basic(PASSWORD)[6:])])
        self.assertEqual(200, status)                                             # scheme and name, any case

    def test_healthz_without_a_password_only_from_loopback_exactly(self):
        for peer in (("127.0.0.1", 1), ("::1", 1)):
            self.assertEqual(200, self.req(path="/healthz", client=peer)[0], peer)
        self.assertEqual(200, self.req(path="/healthz", client=("127.0.0.1", 1), method="HEAD")[0])
        for kw in ({"client": ("10.0.0.5", 1)}, {"client": ("172.17.0.1", 1)}, {"client": None},
                   {"client": ("::ffff:127.0.0.1", 1)}, {"client": ("127.0.0.1", 1), "query": b"x=1"},
                   {"client": ("127.0.0.1", 1), "method": "POST"}, {"client": ("127.0.0.1", 1), "path": "/healthz/"},
                   {"client": ("127.0.0.1", 1), "path": "/"}, {"client": ("127.0.0.1", 1), "path": "/home.json"}):
            self.assertEqual(401, self.req(**dict({"path": "/healthz"}, **kw))[0], kw)
        self.assertEqual(3, len(self.inner.scopes))

    def test_throttle_after_repeated_failures_then_recovery(self):
        wrong = [(b"authorization", basic("wrong-password-0000000"))]
        right = [(b"authorization", basic(PASSWORD))]
        statuses = [self.req(headers=wrong)[0] for _ in range(MAX_FAILURES)]
        self.assertEqual([401] * (MAX_FAILURES - 1) + [429], statuses)
        status, headers, _ = self.req(headers=right)
        self.assertEqual(429, status)                                             # even the right password
        self.assertEqual(str(int(LOCKOUT)).encode(), headers[b"retry-after"])
        self.assertEqual(200, self.req(headers=right, client=("192.0.2.99", 1))[0])   # another address is fine
        self.now[0] += LOCKOUT + 1
        self.assertEqual(200, self.req(headers=right)[0])
        self.assertEqual(2, len(self.inner.scopes))

    def test_failures_spread_beyond_the_window_and_missing_headers_do_not_lock(self):
        wrong = [(b"authorization", basic("wrong-password-0000000"))]
        for _ in range(3 * MAX_FAILURES):
            self.assertEqual(401, self.req()[0])                                  # no header: never counted
        for _ in range(3 * MAX_FAILURES):
            self.assertEqual(401, self.req(headers=wrong)[0])
            self.now[0] += 7                                                      # 10 failures span > 60 s
        self.assertEqual(200, self.req(headers=[(b"authorization", basic(PASSWORD))])[0])

    def test_no_secret_in_logs_or_repr(self):
        token = basic(PASSWORD)[6:].decode()
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger("avrana_home").warning("probe")
            for _ in range(MAX_FAILURES + 2):
                self.req(headers=[(b"authorization", basic(PASSWORD + "-near-miss"))])
            self.now[0] += LOCKOUT + 1
            self.req(headers=[(b"authorization", basic(PASSWORD))])
        blob = " ".join(logs.output) + repr(self.gate) + repr(self.gate.__dict__)
        for secret in (PASSWORD, token, PASSWORD + "-near-miss"):
            self.assertNotIn(secret, blob)
        self.assertIn("preview_auth_throttled", blob)

    def test_the_layers_refuse_to_be_built_without_the_seal_or_with_a_short_password(self):
        with self.assertRaises(PreviewRefused):
            PasswordGate(Inner(), password=PASSWORD.encode(), checked=object())
        with self.assertRaises(PreviewRefused):
            PasswordGate(Inner(), password=b"short", checked=checked_seal())
        with self.assertRaises(PreviewRefused):
            OwnerIdentity(Inner(), headers=[], checked=None)

    def test_a_websocket_is_closed_and_never_reaches_the_app(self):
        sent = []

        async def send(m):
            sent.append(m)

        async def receive():
            return {"type": "websocket.connect"}
        drive(self.gate({"type": "websocket", "path": "/", "headers": []}, receive, send))
        self.assertEqual("websocket.close", sent[0]["type"])
        self.assertEqual([], self.inner.scopes)


class OwnerIdentityTests(unittest.TestCase):
    def test_forged_identity_headers_are_stripped_and_the_owner_is_injected_once(self):
        inner = Inner()
        app = OwnerIdentity(inner, headers=owner_headers("akadmin", GROUPS), checked=checked_seal())
        forged = [("X-authentik-username", "member-b"), ("X_Authentik_Groups", "authentik Admins"),
                  ("x-authentik-email", "b@example.test"), ("X-Authentik-Jwt", "e30.e30.x"),
                  ("X-Forwarded-User", "member-b"), ("X-Forwarded-For", "127.0.0.1"), ("Forwarded", "for=1"),
                  ("Remote-User", "member-b"), ("X-Remote-User", "member-b"), ("X-Real-IP", "127.0.0.1"),
                  ("X-Dev-Identity", "member-b"), ("Authorization", "Basic x"), ("Accept", "text/html")]
        run(app, scope(headers=forged))
        got = inner.scopes[0]["headers"]
        self.assertEqual([(b"accept", b"text/html"), (b"x-authentik-username", b"akadmin"),
                          (b"x-authentik-groups", "|".join(GROUPS).encode())], got)

    def test_owner_headers_refuse_admin_or_unknown_groups_and_bad_usernames(self):
        for groups in ((), ("authentik Admins",), ("avrana-videos", "library-contributors")):
            with self.assertRaises(PreviewRefused, msg=groups):
                owner_headers("akadmin", groups)
        for name in ("", "a b", "x" * 400, "café"):
            with self.assertRaises(PreviewRefused, msg=name):
                owner_headers(name, GROUPS)


class StartupRefusals(unittest.TestCase):
    def test_password_file_rules(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pw"
            for content in (b"", b"short\n", b"fifteen-chars-x\n", b"two\nlines-that-are-long-enough", b"\xff" * 20):
                p.write_bytes(content)
                with self.assertRaises(PreviewRefused, msg=content):
                    read_password(str(p))
            p.write_bytes(PASSWORD.encode() + b"\n")
            self.assertEqual(PASSWORD.encode(), read_password(str(p)))
            for missing in (None, "", str(Path(d) / "absent")):
                with self.assertRaises(PreviewRefused) as cm:
                    read_password(missing)
                self.assertNotIn(d, str(cm.exception))

    def test_bind_rules(self):
        for host in ("127.0.0.1", "::1"):
            check_bind(host, False)
        check_bind("0.0.0.0", True)
        for host, inside in (("0.0.0.0", False), ("::", True), ("::", False), ("10.0.0.218", False),
                             ("10.0.0.218", True), ("203.0.113.1", True), ("localhost", False), ("", True)):
            with self.assertRaises(PreviewRefused, msg=(host, inside)):
                check_bind(host, inside)

    def test_check_preview_startup_needs_preview_settings_sections_and_a_safe_bind(self):
        plain = Settings.from_mapping({"HOME_SECTIONS": "on"})
        with self.assertRaises(PreviewRefused):
            check_preview_startup(password=PASSWORD.encode(), settings=plain, host="127.0.0.1", in_container=False)
        no_sections = Settings.from_mapping({"HOME_OWNER_PREVIEW": "yes", "PREVIEW_OWNER_USERNAME": "akadmin"},
                                            owner_preview_seal=_OWNER_PREVIEW_SEAL)
        with self.assertRaises(PreviewRefused):
            check_preview_startup(password=PASSWORD.encode(), settings=no_sections, host="127.0.0.1",
                                  in_container=False)
        with self.assertRaises(PreviewRefused):
            check_preview_startup(password=b"x" * 15, settings=no_sections, host="127.0.0.1", in_container=False)


REAL = {"HOME_UPSTREAM_MODE": "real", "JELLYFIN_BASE_URL": "https://jf.example.test", "JELLYFIN_API_KEY": "k",
        "HOME_SECTIONS": "on"}
PREVIEW = dict(REAL, HOME_OWNER_PREVIEW="yes", PREVIEW_OWNER_USERNAME="akadmin")


class SealedSettings(unittest.TestCase):
    def test_real_mode_without_the_gates_only_through_the_sealed_preview(self):
        s = Settings.from_mapping(PREVIEW, owner_preview_seal=_OWNER_PREVIEW_SEAL)
        self.assertTrue(s.owner_preview and s.uses_real_upstream)
        self.assertEqual("akadmin", s.owner_preview_username)
        for env, seal in ((REAL, None), (PREVIEW, None), (PREVIEW, object()), (REAL, _OWNER_PREVIEW_SEAL),
                          (dict(PREVIEW, HOME_GATES_VERIFIED="yes"), _OWNER_PREVIEW_SEAL),
                          (dict(PREVIEW, HOME_GATES_VERIFIED="no"), _OWNER_PREVIEW_SEAL),
                          (dict(PREVIEW, PREVIEW_OWNER_USERNAME=""), _OWNER_PREVIEW_SEAL)):
            with self.subTest(env=sorted(env), seal=seal), self.assertRaises(SettingsError):
                Settings.from_mapping(env, owner_preview_seal=seal)

    def test_serve_py_still_refuses_real_mode_without_the_gates(self):
        # serve.main() builds its settings with Settings.from_env() and nothing else.
        source = (HOME / "avrana_home" / "app" / "serve.py").read_text(encoding="utf-8")
        self.assertIn("settings = Settings.from_env()", source)
        self.assertNotIn("seal", source.lower())
        for env in (REAL, PREVIEW, dict(PREVIEW, HOME_JELLYFIN_USERNAME="Cody")):
            with self.assertRaises(SettingsError):
                Settings.from_env(env)
        self.assertTrue(Settings.from_env(dict(REAL, HOME_GATES_VERIFIED="yes")).uses_real_upstream)

    def test_komga_and_calibre_still_need_their_owner_flags_in_the_preview(self):
        komga = dict(PREVIEW, KOMGA_BASE_URL="https://komga.example.test", KOMGA_TOKEN="t")
        cw = dict(PREVIEW, CALIBRE_WEB_BASE_URL="https://cw.example.test", CALIBRE_WEB_CREDENTIAL="v:p")
        for env in (komga, cw):
            with self.assertRaises(SettingsError):
                Settings.from_mapping(env, owner_preview_seal=_OWNER_PREVIEW_SEAL)
        Settings.from_mapping(dict(komga, KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS="yes"),
                              owner_preview_seal=_OWNER_PREVIEW_SEAL)
        Settings.from_mapping(dict(cw, CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS="yes"),
                              owner_preview_seal=_OWNER_PREVIEW_SEAL)

    def test_member_usernames_only_in_the_preview_and_validated(self):
        s = Settings.from_mapping(dict(PREVIEW, HOME_JELLYFIN_USERNAME="Cody", HOME_AUDIOBOOKSHELF_USERNAME="akadmin"),
                                  owner_preview_seal=_OWNER_PREVIEW_SEAL)
        self.assertEqual(("Cody", "akadmin"), (s.jellyfin_member_username, s.audiobookshelf_member_username))
        self.assertEqual(("", ""), (Settings.from_mapping(PREVIEW, owner_preview_seal=_OWNER_PREVIEW_SEAL)
                                    .jellyfin_member_username, Settings().audiobookshelf_member_username))
        for extra in ({"HOME_JELLYFIN_USERNAME": "Cody"}, {"HOME_AUDIOBOOKSHELF_USERNAME": "akadmin"},
                      {"PREVIEW_OWNER_USERNAME": "akadmin"}):
            with self.assertRaises(SettingsError):
                Settings.from_mapping(dict(REAL, HOME_GATES_VERIFIED="yes", **extra))
        for bad in ("Co dy", "x" * 151, "a\tb"):
            with self.assertRaises(SettingsError):
                Settings.from_mapping(dict(PREVIEW, HOME_JELLYFIN_USERNAME=bad), owner_preview_seal=_OWNER_PREVIEW_SEAL)

    def test_errors_and_repr_name_variables_never_values(self):
        try:
            Settings.from_mapping(dict(PREVIEW, HOME_JELLYFIN_USERNAME="Secret Name"),
                                  owner_preview_seal=_OWNER_PREVIEW_SEAL)
        except SettingsError as exc:
            self.assertNotIn("Secret Name", str(exc))
        s = Settings.from_mapping(dict(PREVIEW, HOME_JELLYFIN_USERNAME="Cody"), owner_preview_seal=_OWNER_PREVIEW_SEAL)
        self.assertNotIn("Cody", repr(s))
        self.assertNotIn("akadmin", repr(s))

    def test_the_seal_has_exactly_one_importer_outside_settings_and_the_tests(self):
        users = []
        for path in HOME.rglob("*.py"):
            rel = path.relative_to(HOME).as_posix()
            if rel.startswith(("tests/", "webtests/")) or rel == "avrana_home/app/settings.py":
                continue
            if "_OWNER_PREVIEW_SEAL" in path.read_text(encoding="utf-8"):
                users.append(rel)
        self.assertEqual(["preview/run_preview.py"], users)
        self.assertIs(settings_mod._OWNER_PREVIEW_SEAL, _OWNER_PREVIEW_SEAL)

    def test_the_package_never_imports_the_preview(self):
        for path in (HOME / "avrana_home").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"^\s*(from|import)\s+preview\b", text, re.M), path.name)


class MemberUsernameOverride(unittest.TestCase):
    """The override replaces the username ONLY for that adapter's user lookup, ONLY for the named principal.
    The match stays exact (case-sensitive); cache entries stay keyed by the principal's own username."""

    def setUp(self):
        self.clock = FakeClock()
        self.jf = FakeJellyfin(self.clock)
        self.owner = make_principal("akadmin", GROUPS)
        self.a, self.b = make_principal("member-a", GROUPS), make_principal("member-b", GROUPS)

    def jellyfin(self, override=None):
        return JellyfinAdapter(FakeTransport(self.jf), clock=self.clock, member_username=override)

    def test_default_is_unchanged_and_the_override_maps_only_the_owner(self):
        plain = self.jellyfin()
        self.assertIsNone(plain.resolve_user(self.owner))                         # no "akadmin" in Jellyfin
        self.assertEqual(SectionState.NOT_LINKED, plain.continue_items(self.owner).state)
        ad = self.jellyfin(("akadmin", "member-a"))
        self.assertEqual(plain.resolve_user(self.a).upstream_id, ad.resolve_user(self.owner).upstream_id)
        self.assertEqual(plain.resolve_user(self.b).upstream_id, ad.resolve_user(self.b).upstream_id)
        self.assertEqual([i.id for i in plain.continue_items(self.a).items],
                         [i.id for i in ad.continue_items(self.owner).items])

    def test_the_match_stays_case_sensitive(self):
        ad = self.jellyfin(("akadmin", "Member-A"))
        self.assertIsNone(ad.resolve_user(self.owner))
        self.assertEqual(SectionState.NOT_LINKED, ad.recent_items(self.owner).state)

    def test_cache_entries_stay_per_principal(self):
        ad = self.jellyfin(("akadmin", "member-a"))
        ad.continue_items(self.owner)
        self.assertIsNotNone(ad.cache.for_member(self.owner).get("jellyfin", "mapping"))
        self.assertIsNone(ad.cache.for_member(self.a).get("jellyfin", "mapping"))
        before = len(self.jf.requests)
        ad.continue_items(self.a)                                                 # nothing reused from the owner
        self.assertIn("/Users", [p for _, p, _ in self.jf.requests[before:]])
        ad.cache.purge_member(self.owner)
        self.assertIsNotNone(ad.cache.for_member(self.a).get("jellyfin", "mapping"))

    def test_audiobookshelf_override_and_default(self):
        ab = FakeAudiobookshelf(self.clock)
        plain = AudiobookshelfAdapter(FakeTransport(ab), clock=self.clock)
        ad = AudiobookshelfAdapter(FakeTransport(ab), clock=self.clock, member_username=("akadmin", "member-a"))
        self.assertIsNone(plain.resolve_user(self.owner))
        self.assertEqual(plain.resolve_user(self.a).upstream_id, ad.resolve_user(self.owner).upstream_id)
        self.assertEqual(plain.resolve_user(self.b).upstream_id, ad.resolve_user(self.b).upstream_id)

    def test_a_malformed_override_is_refused_at_construction(self):
        for bad in ("member-a", ("akadmin",), ("akadmin", ""), (" akadmin", "x"), ("akadmin", 5), ["a", "b"]):
            with self.assertRaises(ValueError, msg=bad):
                self.jellyfin(bad)


if __name__ == "__main__":
    unittest.main()
