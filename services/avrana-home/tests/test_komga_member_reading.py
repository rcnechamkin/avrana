"""Komga Continue reading with a member's OWN key (owner decision 2026-10-28; docs/runbooks/komga-member-keys.md),
the live keys file (member_keys.py), Home making a missing key (provision.py, "Home does it") and the owner-run
tool (tools/komga_member_keys.py). Offline, synthetic data only; the
Komga routes and fields are from the 1.25.0 source, UNVERIFIED live."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import base64
import json
import os
import tempfile
import types
import unittest

from avrana_home.adapters.komga import MEMBER_ROUTES, KomgaAdapter, member_key_id
from avrana_home.contract import SectionResult, Service
from avrana_home.member_keys import MemberKeyStore, read_keys, write_keys
from avrana_home.provision import KomgaKeyCreator, Provisioner, ProvisionFailed
from avrana_home.app.settings import Settings, SettingsError
from avrana_home.contract import ForbiddenRequest, SectionState
from avrana_home.principal import principal_from_headers
from avrana_home.resilience import FakeClock
from tests.fake_jellyfin import FakeTransport
from tests.fake_komga import FakeKomga
from tools import komga_member_keys as tool

GROUPS = "avrana-users|avrana-comics"
KEY_A = "0123456789abcdef0123456789abcdef"


def member(name, email, groups=GROUPS):
    headers = {"X-authentik-username": name, "X-authentik-groups": groups}
    if email is not None:
        headers["X-authentik-email"] = email
    return principal_from_headers(headers)


def book(n, series, page=None, pages=40, completed=False, read=None, created=None):
    raw = {"id": f"READ{n:08d}", "seriesId": series, "seriesTitle": f"Series {series}", "name": f"Book {n}",
           "metadata": {"title": f"Book {n}", "number": str(n)}, "media": {"status": "READY", "pagesCount": pages}}
    if page is not None:
        raw["readProgress"] = {"page": page, "completed": completed}
        if read is not None:
            raw["readProgress"]["readDate"] = read
    if created is not None:
        raw["created"] = created
    return raw


class MemberKomga:
    """One member's own view: their in-progress books and their On Deck. Records every request."""

    def __init__(self):
        self.reading = [book(1, "S1", page=10), book(2, "S2", page=39), book(3, "S3", page=0)]
        self.ondeck = [book(4, "S4"), book(1, "S1")]
        self.read = []                     # finished books, newest read first (Continue's order, New for You)
        self.requests = []
        self.status = None

    def handle(self, method, path, query):
        self.requests.append((method, path, dict(query or {})))
        if self.status:
            return self.status, b"{}", "application/json"
        size = int(query.get("size", "20"))
        if path == "/api/v1/books" and query.get("read_status") == "IN_PROGRESS":
            content = self.reading[:size]
        elif path == "/api/v1/books" and query.get("read_status") == "READ":
            content = self.read[:size]
        elif path == "/api/v1/books/ondeck":
            content = self.ondeck[:size]
        else:
            return 400, b"{}", "application/json"
        return 200, json.dumps({"content": content}).encode("utf-8"), "application/json"


class Reading(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.shared = FakeKomga(self.clock)
        self.mine = MemberKomga()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "komga_member_keys")
        write_keys(self.path, {"alice@example.com": KEY_A})
        self.store = MemberKeyStore(self.path, initial=read_keys(self.path))
        self.made = []

        def transport(key):
            self.made.append(key)
            return FakeTransport(self.mine)
        self.adapter = self.build(transport)
        self.alice = member("alice", "Alice@Example.com")
        self.bob = member("bob", "bob@example.com")

    def build(self, transport, provisioning=False):
        return KomgaAdapter(FakeTransport(self.shared), clock=self.clock, owner_confirms_no_member_restrictions=True,
                            member_keys=self.store, member_transport=transport, provisioning=provisioning)

    def test_a_member_with_a_key_gets_in_progress_then_on_deck_with_their_own_progress(self):
        got = self.adapter.continue_items(self.alice)
        self.assertEqual(got.state, SectionState.OK)
        self.assertEqual([i.title for i in got.items], ["Book 1", "Book 2", "Book 3", "Book 4"])
        self.assertEqual([i.progress_fraction for i in got.items], [0.25, 39 / 40, None, None])
        self.assertEqual(self.shared.requests, [])                    # the shared account is never asked
        self.assertEqual([r[1] for r in self.mine.requests], ["/api/v1/books", "/api/v1/books/ondeck", "/api/v1/books"])
        self.assertEqual(self.mine.requests[2][2]["read_status"], "READ")   # when each On Deck series was last read
        self.assertEqual(self.mine.requests[0][2]["sort"], "readProgress.readDate,desc")

    def test_only_on_deck_books_are_marked_up_next(self):
        # Book 3 is in progress at page 0 (no believable fraction): still in progress, never "Up next".
        got = self.adapter.continue_items(self.alice)
        self.assertEqual([i.shelf for i in got.items], [None, None, None, "next"])
        self.assertEqual(got.items[3].to_dict()["shelf"], "next")
        self.assertIsNone(got.items[3].to_dict()["progress"])
        self.assertNotIn("shelf", got.items[0].to_dict())

    def test_on_deck_is_not_asked_when_in_progress_fills_the_row(self):
        got = self.adapter.continue_items(self.alice, limit=2)
        self.assertEqual(len(got.items), 2)
        self.assertEqual([r[1] for r in self.mine.requests], ["/api/v1/books"])

    def test_a_member_without_a_key_is_not_offered_continue_and_nothing_is_called(self):
        got = self.adapter.continue_items(self.bob)
        self.assertEqual((got.state, got.reason), (SectionState.EMPTY, "not_offered"))
        nomail = self.adapter.continue_items(member("carol", None))
        self.assertEqual(nomail.reason, "not_offered")
        self.assertEqual((self.shared.requests, self.mine.requests), ([], []))

    def test_the_group_is_checked_before_the_key(self):
        got = self.adapter.continue_items(member("alice", "alice@example.com", "avrana-users"))
        self.assertEqual(got.state, SectionState.NOT_PERMITTED)
        self.assertEqual(self.mine.requests, [])

    def test_continue_is_offered_only_when_some_member_has_a_key(self):
        self.assertEqual(self.adapter.not_offered, frozenset())
        plain = KomgaAdapter(FakeTransport(self.shared), owner_confirms_no_member_restrictions=True)
        self.assertIn("continue", plain.not_offered)
        self.assertEqual(plain.continue_items(self.alice).reason, "not_offered")
        with self.assertRaises(ValueError):
            KomgaAdapter(FakeTransport(self.shared), owner_confirms_no_member_restrictions=True,
                         member_keys=self.store)                              # keys without a transport factory

    def test_with_provisioning_a_keyless_member_gets_the_trigger_and_it_is_never_cached(self):
        adapter = self.build(lambda key: FakeTransport(self.mine), provisioning=True)
        for _ in range(2):
            got = adapter.continue_items(self.bob)
            self.assertEqual((got.state, got.reason), (SectionState.EMPTY, "no_member_key"))
        self.assertEqual(adapter.continue_items(member("carol", None)).reason, "not_offered")   # no email
        write_keys(self.path, {"alice@example.com": KEY_A, "bob@example.com": "f" * 32})
        self.assertEqual(adapter.continue_items(self.bob).state, SectionState.OK)

    def test_a_key_written_to_the_file_is_used_without_a_restart(self):
        self.assertEqual(self.adapter.continue_items(self.bob).reason, "not_offered")
        write_keys(self.path, {"alice@example.com": KEY_A, "bob@example.com": "e" * 32})
        os.utime(self.path, ns=(1, 1))                              # a new stamp even on a coarse clock
        self.assertEqual(self.adapter.continue_items(self.bob).state, SectionState.OK)
        self.assertIn("e" * 32, self.made)

    def test_a_broken_file_keeps_the_last_good_keys(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        self.assertEqual(self.store.get("alice@example.com"), KEY_A)

    def test_a_refused_member_key_is_an_empty_row_and_never_opens_the_shared_circuit(self):
        self.mine.status = 401
        for _ in range(5):
            self.adapter.cache.clear()
            got = self.adapter.continue_items(self.alice)
            self.assertEqual((got.state, got.reason), (SectionState.EMPTY, "member_key_refused"))
        self.assertEqual(self.adapter.recent_items(self.bob).state, SectionState.OK)

    def test_the_row_is_cached_per_member(self):
        self.adapter.continue_items(self.alice)
        self.adapter.continue_items(self.alice)
        self.assertEqual(len(self.mine.requests), 3)                  # one fetch (three calls), then the cache

    def test_the_member_allow_list_has_only_the_two_reading_routes(self):
        self.assertEqual([r.name for r in MEMBER_ROUTES], ["reading", "ondeck"])
        guard = self.adapter._member_guard("alice@example.com").bind("shared")
        for path, query in (("/api/v2/users/me/api-keys", {}), ("/api/v1/books/READ00000001", {}),
                            ("/api/v1/books", {"search": "x"})):
            with self.subTest(path=path), self.assertRaises(ForbiddenRequest):
                guard.request("GET", path, query, 1.0, 1000)
        with self.assertRaises(ForbiddenRequest):
            guard.request("POST", "/api/v1/books/ondeck", {}, 1.0, 1000)

    def test_keys_are_filed_under_the_normalised_email(self):
        self.assertEqual(member_key_id(" Alice@Example.COM "), "alice@example.com")
        self.assertIsNone(member_key_id("not an email"))


REAL = {"HOME_SECTIONS": "on", "HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes",
        "HOME_IDENTITY_MODE": "jwt_required", "JELLYFIN_BASE_URL": "https://jellyfin.example.test",
        "JELLYFIN_API_KEY": "k" * 32, "KOMGA_BASE_URL": "https://komga.example.test", "KOMGA_TOKEN": "t" * 32,
        "KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS": "yes", "HOME_JWT_SECRET": "s" * 48,
        "HOME_JWT_ISSUER": "https://auth.example.test/application/o/avrana-home/", "HOME_JWT_AUDIENCE": "home"}


class SettingsFile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "komga_member_keys")

    def env(self, data, **extra):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))
        return dict(REAL, KOMGA_MEMBER_KEYS_FILE=self.path, **extra)

    def from_env(self, env):
        try:
            return Settings.from_env(env)
        except SettingsError as exc:
            return exc

    def test_an_absent_file_is_no_keys_but_its_folder_must_exist(self):
        env = dict(REAL, KOMGA_MEMBER_KEYS_FILE=self.path)
        got = self.from_env(env)
        self.assertIsInstance(got, Settings, got)
        self.assertEqual((got.komga_member_keys, got.komga_member_keys_file), ((), self.path))
        env["KOMGA_MEMBER_KEYS_FILE"] = os.path.join(self.dir.name, "missing", "keys")
        self.assertIsInstance(self.from_env(env), SettingsError)

    def test_home_making_keys_needs_the_admin_key_and_the_file_and_the_admin_key_needs_it(self):
        admin = os.path.join(self.dir.name, "admin")
        with open(admin, "w", encoding="utf-8") as fh:
            fh.write("a" * 32)
        on = dict(REAL, KOMGA_MEMBER_KEYS_FILE=self.path, KOMGA_ADMIN_TOKEN_FILE=admin, HOME_ALLOWED_USERS="alice",
                  HOME_PROVISION_ACCOUNTS="komga")
        got = self.from_env(on)
        self.assertIsInstance(got, Settings, got)
        self.assertEqual(got.provision_accounts, ("komga",))
        self.assertNotIn("a" * 32, repr(got))
        for drop in ("KOMGA_ADMIN_TOKEN_FILE", "KOMGA_MEMBER_KEYS_FILE"):
            with self.subTest(drop=drop):
                self.assertIsInstance(self.from_env({k: v for k, v in on.items() if k != drop}), SettingsError)
        self.assertIsInstance(self.from_env(dict(on, HOME_PROVISION_ACCOUNTS="off")), SettingsError)

    def test_a_valid_file_is_read(self):
        got = self.from_env(self.env({"alice@example.com": KEY_A}))
        self.assertIsInstance(got, Settings, got)
        self.assertEqual(got.komga_member_keys, (("alice@example.com", KEY_A),))
        self.assertNotIn(KEY_A, repr(got))

    def test_a_bad_file_is_refused_without_echoing_it(self):
        for data in ("not json", [], {"Alice@Example.com": KEY_A}, {"alice@example.com": "short"},
                     {"alice": KEY_A}, {"alice@example.com": KEY_A.upper()}):
            with self.subTest(data=data):
                got = self.from_env(self.env(data))
                self.assertIsInstance(got, SettingsError)
                self.assertNotIn(KEY_A, str(got))
                self.assertNotIn("alice", str(got).lower().replace("allowed", ""))

    def test_it_needs_signed_identity_komga_and_real_mode(self):
        cases = (dict(HOME_IDENTITY_MODE="jwt_log_only"),
                 dict(KOMGA_BASE_URL="", KOMGA_TOKEN="", KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=""))
        for extra in cases:
            with self.subTest(extra=extra):
                self.assertIsInstance(self.from_env(self.env({"alice@example.com": KEY_A}, **extra)), SettingsError)
        mock = {"HOME_SECTIONS": "on", "KOMGA_BASE_URL": "http://127.0.0.1:9", "KOMGA_MEMBER_KEYS_FILE": self.path}
        self.env({"alice@example.com": KEY_A})
        self.assertIsInstance(self.from_env(mock), SettingsError)

    def test_the_value_is_never_read_from_the_environment(self):
        env = dict(REAL, KOMGA_MEMBER_KEYS=json.dumps({"alice@example.com": KEY_A}))
        self.assertIsInstance(self.from_env(env), SettingsError)


# ---- Home making a member's key (provision.py) ----------------------------------------------
class HomeMakesKeys(unittest.TestCase):
    """KomgaKeyCreator against the same fake Komga the tool tests use; the admin key's account is U0."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "komga_member_keys")
        write_keys(self.path, {})          # Home refuses to make keys while the configured file is absent (S-02)
        self.store = MemberKeyStore(self.path, writable=True)
        self.fake = FakeAdminKomga()
        self.creator = KomgaKeyCreator(self.sender({"X-API-Key": "ADMIN"}), self.as_member, self.store)

    def sender(self, headers):
        def send(method, path, body):
            status, data = self.fake.send(method, "http://komga.test" + path, headers,
                                          json.dumps(body).encode() if body is not None else None)
            if status >= 400:
                raise ProvisionFailed(f"http_{status}")
            return json.loads(data) if data else None
        return send

    def as_member(self, email, password):
        return self.sender(tool.basic_auth(email, password))

    def test_an_existing_member_gets_a_key_filed_and_their_own_keys_are_kept(self):
        self.creator.create("alice", "Alice@Example.com")
        self.assertEqual(len(self.store.get("alice@example.com")), 32)
        self.assertEqual(sorted(k["comment"] for k in self.fake.keys["U1"]), ["avrana-home", "phone"])
        self.assertEqual(read_keys(self.path)[0][0], "alice@example.com")

    def test_a_member_with_no_komga_account_gets_one_with_sign_in_defaults(self):
        self.creator.create("newbie", "newbie@example.com")
        made = [u for u in self.fake.users.values() if u["email"] == "newbie@example.com"][0]
        self.assertEqual(sorted(made["roles"]), ["FILE_DOWNLOAD", "PAGE_STREAMING", "USER"])
        self.assertIsNotNone(self.store.get("newbie@example.com"))

    def test_the_admin_keys_own_account_gets_a_key_without_a_password_change(self):
        self.fake.users["U0"]["email"] = "owner@example.com"
        self.creator.create("owner", "owner@example.com")
        self.assertEqual(self.fake.passwords["U0"], "owner")
        self.assertIsNotNone(self.store.get("owner@example.com"))

    def test_another_admin_is_never_touched(self):
        self.fake.users["U9"] = {"id": "U9", "email": "boss@example.com", "roles": ["ADMIN", "USER"]}
        self.fake.passwords["U9"] = "boss"
        with self.assertRaises(ProvisionFailed) as caught:
            self.creator.create("boss", "boss@example.com")
        self.assertEqual(caught.exception.reason, "admin")
        self.assertEqual(self.fake.passwords["U9"], "boss")

    def test_no_email_or_an_existing_key_is_refused(self):
        for email in (None, "", "not-an-email"):
            with self.subTest(email=email), self.assertRaises(ProvisionFailed):
                self.creator.create("x", email)
        self.creator.create("alice", "alice@example.com")
        with self.assertRaises(ProvisionFailed):
            self.creator.create("alice", "alice@example.com")

    def test_the_provisioner_triggers_only_on_the_komga_continue_reason(self):
        prov = Provisioner({Service.KOMGA: self.creator})
        hit = SectionResult(Service.KOMGA, "continue", SectionState.EMPTY, reason="no_member_key")
        miss = SectionResult(Service.KOMGA, "continue", SectionState.EMPTY, reason="not_offered")
        self.assertEqual(prov.candidates([miss]), ())
        self.assertEqual(prov.candidates([hit]), (Service.KOMGA,))
        self.assertEqual(prov.provision(member("alice", "alice@example.com"), [hit]), (Service.KOMGA,))
        self.assertEqual(prov.provision(member("alice", "alice@example.com"), [hit]), ())      # once an hour

    def test_a_read_only_store_is_refused(self):
        with self.assertRaises(ValueError):
            KomgaKeyCreator(self.sender({}), self.as_member, MemberKeyStore(self.path))

    def test_two_page_loads_of_one_member_make_exactly_one_reset(self):
        import threading
        inside, release = threading.Event(), threading.Event()
        gate = threading.Lock()
        entered = []
        real = self.fake.send

        def slow(method, url, headers, body):
            if method == "PATCH":
                with gate:
                    entered.append(1)
                inside.set()
                release.wait(5)                              # hold the first attempt inside Komga
            return real(method, url, headers, body)
        self.fake.send = slow
        logs = []
        start = threading.Barrier(2)

        def clock():
            start.wait(5)                                    # both loads reach the lock together
            return 0.0
        prov = Provisioner({Service.KOMGA: self.creator}, clock=clock, log=lambda **f: logs.append(f))
        hit = SectionResult(Service.KOMGA, "continue", SectionState.EMPTY, reason="no_member_key")
        alice = member("alice", "Alice@Example.com")
        first = threading.Thread(target=prov.provision, args=(alice, [hit]))
        second = threading.Thread(target=prov.provision, args=(alice, [hit]))
        first.start()
        second.start()
        self.assertTrue(inside.wait(5))
        release.set()
        first.join(5)
        second.join(5)
        self.assertEqual(len(self.resets()), 1)
        self.assertEqual([l["state"] for l in logs], ["provisioned"])

    # ---- S-02: a failed key step after the password reset is terminal, and a missing keys file stops everything
    def prov(self, log):
        return Provisioner({Service.KOMGA: self.creator}, log=lambda **f: log.append(f))

    def resets(self):
        return [c for c in self.fake.calls if c[0] == "PATCH"]

    def test_a_key_step_failing_after_the_reset_is_not_retried_and_logs_its_own_reason(self):
        logs, clock = [], [0.0]
        prov = Provisioner({Service.KOMGA: self.creator}, clock=lambda: clock[0], log=lambda **f: logs.append(f))
        hit = SectionResult(Service.KOMGA, "continue", SectionState.EMPTY, reason="no_member_key")
        alice = member("alice", "Alice@Example.com")
        self.fake.fail_keys = 500
        self.assertEqual(prov.provision(alice, [hit]), ())
        self.assertEqual(len(self.resets()), 1)
        self.assertEqual(logs, [{"service": "komga", "state": "failed", "reason": "failed_after_reset"}])
        self.assertIsNone(self.store.get("alice@example.com"))
        self.fake.fail_keys = None
        for _ in range(3):                                   # hourly passes, even after Komga recovers
            clock[0] += 3601
            self.assertEqual(prov.provision(alice, [hit]), ())
        self.assertEqual(len(self.resets()), 1)              # no second password reset
        self.assertEqual(len(logs), 1)                       # and no log noise after the one line

    def test_the_block_survives_a_restart(self):
        self.fake.fail_keys = 500
        with self.assertRaises(ProvisionFailed) as caught:
            self.creator.create("alice", "Alice@Example.com")
        self.assertEqual(caught.exception.reason, "failed_after_reset")
        self.fake.fail_keys = None
        again = KomgaKeyCreator(self.sender({"X-API-Key": "ADMIN"}), self.as_member,
                                MemberKeyStore(self.path, writable=True))
        calls = len(self.fake.calls)
        with self.assertRaises(ProvisionFailed) as caught:
            again.create("alice", "Alice@Example.com")
        self.assertEqual(caught.exception.reason, "failed_after_reset")
        self.assertEqual(len(self.fake.calls), calls)        # decided before any Komga request

    def test_a_filing_failure_after_the_reset_is_also_terminal(self):
        def broken(email, key):
            raise OSError("read-only file system")
        self.store.put = broken
        with self.assertRaises(ProvisionFailed) as caught:
            self.creator.create("alice", "Alice@Example.com")
        self.assertEqual(caught.exception.reason, "failed_after_reset")
        with self.assertRaises(ProvisionFailed):
            self.creator.create("alice", "Alice@Example.com")
        self.assertEqual(len(self.resets()), 1)

    def test_a_failure_before_any_reset_is_still_an_ordinary_retryable_failure(self):
        self.fake.users["U9"] = {"id": "U9", "email": "dup@example.com", "roles": ["USER"]}
        self.fake.users["U8"] = {"id": "U8", "email": "DUP@example.com", "roles": ["USER"]}
        with self.assertRaises(ProvisionFailed) as caught:
            self.creator.create("dup", "dup@example.com")
        self.assertEqual(caught.exception.reason, "ambiguous")
        self.assertEqual(self.resets(), [])

    def test_the_admin_keys_own_account_failing_is_not_a_reset_failure(self):
        self.fake.users["U0"]["email"] = "owner@example.com"
        self.fake.keys["U0"] = []
        real = self.fake.send

        def flaky(method, url, headers, body):
            if method == "POST" and url.endswith("/api-keys"):
                return 500, b""
            return real(method, url, headers, body)
        self.fake.send = flaky
        with self.assertRaises(ProvisionFailed) as caught:
            self.creator.create("owner", "owner@example.com")
        self.assertEqual(caught.exception.reason, "http_500")   # no password was changed: retryable
        self.assertEqual(self.resets(), [])

    def test_a_configured_but_missing_keys_file_refuses_before_any_komga_request(self):
        logs = []
        prov = self.prov(logs)
        os.unlink(self.path)                                  # the state volume went away
        hit = SectionResult(Service.KOMGA, "continue", SectionState.EMPTY, reason="no_member_key")
        for name in ("alice", "bob", "carol"):
            self.assertEqual(prov.provision(member(name, name + "@example.com"), [hit]), ())
        self.assertEqual(self.fake.calls, [])
        self.assertEqual([l["reason"] for l in logs], ["keys_file_unusable"] * 3)
        self.assertEqual({l["state"] for l in logs}, {"refused"})

    def test_a_missing_keys_file_does_not_use_up_the_hourly_cap(self):
        logs = []
        prov = Provisioner({Service.KOMGA: self.creator}, cap_per_hour=1, log=lambda **f: logs.append(f))
        os.unlink(self.path)
        hit = SectionResult(Service.KOMGA, "continue", SectionState.EMPTY, reason="no_member_key")
        for name in ("alice", "bob"):
            prov.provision(member(name, name + "@example.com"), [hit])
        self.assertEqual({l["reason"] for l in logs}, {"keys_file_unusable"})   # never "cap"

    def test_an_existing_empty_keys_file_is_a_normal_start(self):
        write_keys(self.path, {})
        self.creator.create("alice", "Alice@Example.com")
        self.assertIsNotNone(self.store.get("alice@example.com"))

    def test_an_unreadable_keys_file_refuses_too(self):
        with open(self.path, "w") as fh:
            fh.write("not json")
        with self.assertRaises(ProvisionFailed) as caught:
            self.creator.create("alice", "Alice@Example.com")
        self.assertEqual(caught.exception.reason, "keys_file_unusable")
        self.assertEqual(self.fake.calls, [])

    def test_the_read_adapters_still_treat_an_absent_file_as_no_keys(self):
        os.unlink(self.path)
        self.assertEqual(read_keys(self.path), ())
        self.assertIsNone(self.store.get("alice@example.com"))


# ---- the owner-run tool ---------------------------------------------------------------------
class FakeAdminKomga:
    """Komga's user and API-key routes, as the 1.25.0 source declares them."""

    def __init__(self):
        self.users = {"U1": {"id": "U1", "email": "Alice@Example.com", "roles": ["FILE_DOWNLOAD", "USER"]},
                      "U0": {"id": "U0", "email": "owner@example.com", "roles": ["ADMIN", "USER"]},
                      "U2": {"id": "U2", "email": "viewer@example.com", "roles": ["USER"]}}
        self.passwords = {"U1": "old", "U0": "owner", "U2": "viewer"}
        self.keys = {"U1": [{"id": "K-old", "comment": "avrana-home"}, {"id": "K-own", "comment": "phone"}]}
        self.calls = []
        self.serial = 0
        self.fail_keys = None          # an HTTP status: the key routes answer it (a failing Komga after the reset)

    def _who(self, headers):
        if headers.get("X-API-Key") == "ADMIN":
            return "U0"
        auth = headers.get("Authorization", "")
        if auth.startswith("Basic "):
            email, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
            for uid, u in self.users.items():
                if u["email"] == email and self.passwords.get(uid) == pw:
                    return uid
        return None

    def send(self, method, url, headers, body):
        path = url.split("://", 1)[1].split("/", 1)[1]
        path = "/" + path
        self.calls.append((method, path))
        who = self._who(headers)
        data = json.loads(body) if body else None
        if who is None:
            return 401, b""
        if path == "/api/v2/users/me" and method == "GET":
            return 200, json.dumps(self.users[who]).encode()
        if path == "/api/v2/users" and method == "GET":
            return (200, json.dumps(list(self.users.values())).encode()) if who == "U0" else (403, b"")
        if path == "/api/v2/users" and method == "POST":
            uid = f"U{len(self.users) + 1}"
            self.users[uid] = {"id": uid, "email": data["email"], "roles": data["roles"] + ["USER"],
                               "sharedAll": data["sharedLibraries"]["all"]}
            self.passwords[uid] = data["password"]
            return 201, json.dumps(self.users[uid]).encode()
        if path.endswith("/password") and method == "PATCH":
            self.passwords[path.split("/")[4]] = data["password"]
            return 204, b""
        if self.fail_keys and path.startswith("/api/v2/users/me/api-keys") and who != "U0":
            return self.fail_keys, b""
        if path == "/api/v2/users/me/api-keys" and method == "GET":
            return 200, json.dumps(self.keys.get(who, [])).encode()
        if path == "/api/v2/users/me/api-keys" and method == "POST":
            self.serial += 1
            key = f"{self.serial:032x}"
            self.keys.setdefault(who, []).append({"id": f"K{self.serial}", "comment": data["comment"], "key": key})
            return 200, json.dumps({"id": f"K{self.serial}", "key": key, "comment": data["comment"]}).encode()
        if path.startswith("/api/v2/users/me/api-keys/") and method == "DELETE":
            kid = path.rsplit("/", 1)[1]
            self.keys[who] = [k for k in self.keys.get(who, []) if k["id"] != kid]
            return 204, b""
        return 404, b""


class Tool(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "komga_member_keys")
        self.fake = FakeAdminKomga()
        self.komga = tool.Komga("http://komga.test", send=self.fake.send)
        self.lines = []

    def run_tool(self, answer=True, **kw):
        args = types.SimpleNamespace(member=[], all=False, remove=[], skip=[], keys_file=self.path)
        vars(args).update(kw)
        asked = []

        def ask(q):
            asked.append(q)
            return answer
        code = tool.run(args, self.komga, "ADMIN", ask, out=self.lines.append)
        return code, asked

    def keys(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_an_existing_member_gets_a_fresh_home_key_and_their_own_keys_are_kept(self):
        code, asked = self.run_tool(member=["alice@example.com"])
        self.assertEqual(code, 0)
        self.assertIn("signs them out of Komga once", asked[0])
        key = self.keys()["alice@example.com"]
        self.assertEqual(len(key), 32)
        comments = sorted(k["comment"] for k in self.fake.keys["U1"])
        self.assertEqual(comments, ["avrana-home", "phone"])            # the old Home key was replaced
        self.assertNotEqual(self.fake.passwords["U1"], "old")
        self.assertFalse(any(key in line for line in self.lines))
        if os.name == "posix":
            self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_a_new_member_is_created_with_the_authentik_sign_in_defaults(self):
        code, _ = self.run_tool(member=["New@Example.com"])
        self.assertEqual(code, 0)
        created = [u for u in self.fake.users.values() if u["email"] == "new@example.com"][0]
        self.assertEqual(sorted(created["roles"]), ["FILE_DOWNLOAD", "PAGE_STREAMING", "USER"])
        self.assertTrue(created["sharedAll"])
        self.assertIn("new@example.com", self.keys())

    def test_admins_and_skipped_accounts_are_never_touched(self):
        code, asked = self.run_tool(all=True, skip=["viewer@example.com"])
        self.assertEqual(code, 0)
        self.assertEqual(self.fake.passwords["U0"], "owner")
        self.assertEqual(self.fake.passwords["U2"], "viewer")
        self.assertEqual(list(self.keys()), ["alice@example.com"])
        self.assertEqual(len(asked), 1)

    def test_a_no_changes_nothing(self):
        code, _ = self.run_tool(answer=False, all=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.fake.passwords, {"U1": "old", "U0": "owner", "U2": "viewer"})
        self.assertFalse(os.path.exists(self.path))

    def test_remove_revokes_the_key_in_komga_and_drops_it_from_the_file(self):
        self.run_tool(member=["alice@example.com"])
        code, _ = self.run_tool(remove=["alice@example.com"])
        self.assertEqual(code, 0)
        self.assertEqual([k["comment"] for k in self.fake.keys["U1"]], ["phone"])
        self.assertEqual(self.keys(), {})

    def test_missing_lists_non_admin_accounts_without_a_key_and_changes_nothing(self):
        code, _ = self.run_tool(missing=True)
        self.assertEqual(code, 1)
        self.assertIn("alice@example.com: no Home key", self.lines)
        self.assertFalse(any("owner@" in line for line in self.lines))
        self.assertEqual(self.fake.passwords["U1"], "old")

    def test_a_non_admin_key_is_refused_before_anything_changes(self):
        args = types.SimpleNamespace(member=["alice@example.com"], all=False, remove=[], skip=[], keys_file=self.path)
        code = tool.run(args, self.komga, "NOT-ADMIN", lambda q: True, out=self.lines.append)
        self.assertEqual(code, 2)
        self.assertEqual(self.fake.passwords["U1"], "old")


if __name__ == "__main__":
    unittest.main()
