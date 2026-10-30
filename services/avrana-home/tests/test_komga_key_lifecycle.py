"""S-01: members' Komga keys minted where the password lives (komga_keys.py, member_keys.py, the intake rules, settings
and the offboarding step). Offline: a fake Komga behind a urllib-style opener, temporary files, synthetic accounts."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from avrana_home import member_keys as mk
from avrana_home.app.settings import Settings, SettingsError
from avrana_home.identity_bindings import digest
from avrana_home.komga_keys import (BAD_KEY, FILED, KOMGA_DOWN, SAME, STORE_DOWN, UNKNOWN_SUBJECT, KeyIntake,
                                    KomgaKeyClient, subject_ref)
from avrana_home.member_keys import MemberKeyStore, read_ids, read_keys, write_keys
from avrana_home.provision import ProvisionFailed
from tests.fake_komga_keys import FakeKeyKomga

REPO = Path(__file__).resolve().parents[3]
SUBJECT = digest("synthetic-sub-alice")
NEW_SUBJECT = digest("synthetic-sub-new-member")
REAL = {"HOME_SECTIONS": "on", "HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes",
        "HOME_IDENTITY_MODE": "jwt_required", "JELLYFIN_BASE_URL": "https://jellyfin.example.test",
        "JELLYFIN_API_KEY": "k" * 32, "KOMGA_BASE_URL": "https://komga.example.test", "KOMGA_TOKEN": "t" * 32,
        "KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS": "yes", "HOME_JWT_SECRET": "s" * 48,
        "HOME_JWT_ISSUER": "https://auth.example.test/application/o/avrana-home/", "HOME_JWT_AUDIENCE": "home"}


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "komga_member_keys")
        write_keys(self.path, {})


class StoreTests(Files):
    def test_put_is_idempotent_and_records_the_komga_id_in_the_sidecar(self):
        store = MemberKeyStore(self.path, writable=True)
        self.assertTrue(store.put("Alice@Example.com", "a" * 32, "K1"))
        self.assertFalse(store.put("alice@example.com", "a" * 32, "K1"))      # same key: nothing written
        self.assertFalse(store.put("alice@example.com", "a" * 32))
        self.assertEqual(read_keys(self.path), (("alice@example.com", "a" * 32),))
        self.assertEqual(read_ids(self.path), {"alice@example.com": "K1"})
        self.assertEqual(store.komga_id("ALICE@example.com"), "K1")

    def test_a_different_key_replaces_and_drops_the_old_id(self):
        store = MemberKeyStore(self.path, writable=True)
        store.put("alice@example.com", "a" * 32, "K1")
        self.assertTrue(store.put("alice@example.com", "b" * 32))
        self.assertEqual(store.get("alice@example.com"), "b" * 32)
        self.assertIsNone(store.komga_id("alice@example.com"))

    def test_remove_returns_what_was_filed_once(self):
        store = MemberKeyStore(self.path, writable=True)
        store.put("alice@example.com", "a" * 32, "K1")
        store.put("bob@example.com", "b" * 32)
        self.assertEqual(store.remove("Alice@Example.com"), ("a" * 32, "K1"))
        self.assertIsNone(store.remove("alice@example.com"))
        self.assertEqual(read_keys(self.path), (("bob@example.com", "b" * 32),))
        self.assertEqual(read_ids(self.path), {})

    def test_read_only_and_bad_values_are_refused(self):
        with self.assertRaises(PermissionError):
            MemberKeyStore(self.path).put("alice@example.com", "a" * 32)
        with self.assertRaises(PermissionError):
            MemberKeyStore(self.path).remove("alice@example.com")
        store = MemberKeyStore(self.path, writable=True)
        for args in (("alice", "a" * 32), ("alice@example.com", "A" * 32), ("alice@example.com", "a" * 32, "../x")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                store.put(*args)

    def test_two_stores_never_lose_each_others_entry(self):
        """Two writers (two processes in production; two store objects here) each with a stale in-memory view."""
        one, two = MemberKeyStore(self.path, writable=True), MemberKeyStore(self.path, writable=True)
        one.put("alice@example.com", "a" * 32)
        two.put("bob@example.com", "b" * 32)              # two never re-read before writing: the lock makes it
        self.assertEqual(dict(read_keys(self.path)), {"alice@example.com": "a" * 32, "bob@example.com": "b" * 32})
        threads = [threading.Thread(target=MemberKeyStore(self.path, writable=True).put,
                                    args=(f"m{i}@example.com", f"{i:032x}")) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(read_keys(self.path)), 10)

    def test_a_broken_ids_sidecar_never_blocks_a_key(self):
        with open(self.path + ".ids", "w", encoding="utf-8") as fh:
            fh.write("not json")
        store = MemberKeyStore(self.path, writable=True)
        store.put("alice@example.com", "a" * 32)
        self.assertEqual(store.get("alice@example.com"), "a" * 32)

    def test_count_prints_a_number_only(self):
        MemberKeyStore(self.path, writable=True).put("alice@example.com", "a" * 32)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mk.main(["count", "--file", self.path]), 0)
        self.assertEqual(out.getvalue(), "1\n")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mk.main(["count", "--file", self.path]), 2)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.komga = FakeKeyKomga()
        self.client = KomgaKeyClient("http://komga.test", opener=self.komga)

    def test_mint_signs_in_as_the_member_replaces_only_avrana_home_and_returns_key_and_id(self):
        old, _ = self.komga.mint_for("U1")
        key, kid = self.client.mint("alice@example.com", "alice-synthetic-pw")
        self.assertEqual(self.komga.comments("U1"), ["avrana-home", "phone"])
        self.assertNotIn(old, [k["key"] for k in self.komga.keys["U1"]])
        self.assertIn({"id": kid, "comment": "avrana-home", "key": key}, self.komga.keys["U1"])

    def test_mint_failures_are_fixed_reasons_without_the_password(self):
        cases = (("alice@example.com", "wrong", "wrong_password"), ("alice@example.com", "", "bad_input"),
                 ("no-at-sign", "x", "bad_input"))
        for email, pw, reason in cases:
            with self.subTest(reason=reason), self.assertRaises(ProvisionFailed) as caught:
                self.client.mint(email, pw)
            self.assertEqual(caught.exception.reason, reason)
            self.assertNotIn("alice-synthetic-pw", repr(caught.exception.__dict__))
        self.komga.down = True
        with self.assertRaises(ProvisionFailed) as caught:
            self.client.mint("alice@example.com", "alice-synthetic-pw")
        self.assertEqual(caught.exception.reason, "unreachable")
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)

    def test_owner_of_reports_the_keys_own_account(self):
        key, _ = self.komga.mint_for("U1")
        self.assertEqual(self.client.owner_of(key), "alice@example.com")
        with self.assertRaises(ProvisionFailed) as caught:
            self.client.owner_of("9" * 32)
        self.assertEqual(caught.exception.reason, "bad_key")

    def test_revoke_by_id_by_list_and_when_already_gone(self):
        key, kid = self.komga.mint_for("U1")
        self.assertEqual(self.client.revoke(key, kid), "revoked")
        self.assertEqual(self.komga.comments("U1"), ["phone"])
        self.assertEqual(self.client.revoke(key, kid), "already_gone")          # the key no longer signs in
        key, _ = self.komga.mint_for("U1")
        self.assertEqual(self.client.revoke(key, None), "revoked")            # no id: every avrana-home key
        self.assertEqual(self.komga.comments("U1"), ["phone"])
        key, kid = self.komga.mint_for("U1")
        self.assertEqual(self.client.revoke(key, "K-stale"), "revoked")       # a stale id falls back to the list
        self.komga.down = True
        with self.assertRaises(ProvisionFailed):
            self.client.revoke(key, kid)

    def test_revoke_deletes_with_the_key_itself_never_basic_auth(self):
        key, kid = self.komga.mint_for("U2")
        self.client.revoke(key, kid)
        self.assertTrue(all(who == "U2" for _m, _p, who in self.komga.calls))
        self.assertEqual(self.komga.calls[-1][:2], ("DELETE", "/api/v2/users/me/api-keys/" + kid))


class IntakeRuleTests(Files):
    def setUp(self):
        super().setUp()
        self.komga = FakeKeyKomga()
        self.store = MemberKeyStore(self.path, writable=True)
        self.logs = []
        self.bound = {SUBJECT}
        self.intake = KeyIntake(self.store, KomgaKeyClient("http://komga.test", opener=self.komga),
                                lambda d: d in self.bound, log=lambda **f: self.logs.append(f))

    def test_enrollment_files_an_unknown_subject_under_the_keys_own_email(self):
        key, kid = self.komga.mint_for("U2")
        self.assertEqual(self.intake.file(NEW_SUBJECT, "enrollment", key, kid), FILED)
        self.assertEqual(self.store.get("bob@example.com"), key)
        self.assertEqual(self.store.komga_id("bob@example.com"), kid)
        self.assertEqual(self.logs, [{"service": "komga", "state": "filed", "reason": "enrollment",
                                      "ref": subject_ref(NEW_SUBJECT)}])

    def test_the_same_key_twice_is_unchanged_and_a_new_key_replaces(self):
        key, kid = self.komga.mint_for("U1")
        self.assertEqual(self.intake.file(SUBJECT, "connect", key, kid), FILED)
        self.assertEqual(self.intake.file(SUBJECT, "connect", key, kid), SAME)
        key2, kid2 = self.komga.mint_for("U1")
        self.assertEqual(self.intake.file(SUBJECT, "connect", key2, kid2), FILED)
        self.assertEqual(self.store.get("alice@example.com"), key2)
        self.assertIn(key, [k["key"] for k in self.komga.keys["U1"]])        # nothing revoked remotely

    def test_connect_from_outside_needs_a_bound_subject(self):
        key, _ = self.komga.mint_for("U2")
        self.assertEqual(self.intake.file(NEW_SUBJECT, "connect", key), UNKNOWN_SUBJECT)
        self.bound = None
        self.intake._known = lambda d: None                                   # bindings unavailable: still refused
        self.assertEqual(self.intake.file(SUBJECT, "connect", key), UNKNOWN_SUBJECT)
        self.assertEqual(self.store.count(), 0)
        self.assertEqual(self.intake.file(NEW_SUBJECT, "connect", key, signed_in=True), FILED)

    def test_bad_keys_komga_down_and_a_broken_store(self):
        self.assertEqual(self.intake.file(SUBJECT, "connect", "short"), BAD_KEY)
        self.assertEqual(self.intake.file(SUBJECT, "connect", "9" * 32), BAD_KEY)          # Komga refuses it
        key, _ = self.komga.mint_for("U1")
        self.assertEqual(self.intake.file(SUBJECT, "connect", key, "bad/id"), BAD_KEY)
        self.komga.down = True
        self.assertEqual(self.intake.file(SUBJECT, "connect", key), KOMGA_DOWN)
        self.komga.down = False
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        self.assertEqual(self.intake.file(SUBJECT, "connect", key), STORE_DOWN)

    def test_no_key_in_any_log_line(self):
        key, kid = self.komga.mint_for("U1")
        self.intake.file(SUBJECT, "connect", key, kid)
        self.intake.file(SUBJECT, "connect", "9" * 32)
        text = json.dumps(self.logs)
        for secret in (key, "9" * 32, SUBJECT, "alice"):
            self.assertNotIn(secret, text)

    def test_shape_errors_are_programming_errors(self):
        with self.assertRaises(ValueError):
            self.intake.file("not-a-digest", "enrollment", "a" * 32)
        with self.assertRaises(ValueError):
            self.intake.file(SUBJECT, "owner", "a" * 32)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.keys = os.path.join(self.dir.name, "komga_member_keys")
        self.token = os.path.join(self.dir.name, "token")
        with open(self.token, "w", encoding="utf-8") as fh:
            fh.write("i" * 40)
        self.on = dict(REAL, KOMGA_MEMBER_KEYS_FILE=self.keys, HOME_KEY_INTAKE_TOKEN_FILE=self.token,
                       HOME_INTERNAL_CIDR="172.30.0.0/16", HOME_KOMGA_CONNECT="on")

    def test_intake_and_connect_on(self):
        got = Settings.from_mapping(self.on)
        self.assertEqual(got.key_intake_token, "i" * 40)
        self.assertEqual([str(n) for n in got.internal_cidrs], ["172.30.0.0/16"])
        self.assertTrue(got.komga_connect)
        self.assertNotIn("i" * 40, repr(got))

    def test_off_by_default(self):
        got = Settings.from_mapping(REAL)
        self.assertEqual((got.key_intake_token, got.internal_cidrs, got.komga_connect), ("", (), False))

    def test_refused_without_preconditions(self):
        short = os.path.join(self.dir.name, "short")
        with open(short, "w", encoding="utf-8") as fh:
            fh.write("short")
        bad = [{k: v for k, v in self.on.items() if k != "HOME_INTERNAL_CIDR"},
               {k: v for k, v in self.on.items() if k != "KOMGA_MEMBER_KEYS_FILE"},
               dict(self.on, HOME_KEY_INTAKE_TOKEN_FILE=short),
               dict(self.on, HOME_INTERNAL_CIDR="8.8.8.0/24"),
               dict(self.on, HOME_INTERNAL_CIDR="0.0.0.0/0"),
               dict(self.on, HOME_INTERNAL_CIDR="172.30.0.1/16"),
               dict(REAL, HOME_INTERNAL_CIDR="172.30.0.0/16"),
               dict(REAL, HOME_KOMGA_CONNECT="on"),
               {"HOME_SECTIONS": "on", "KOMGA_BASE_URL": "http://127.0.0.1:9", "HOME_KOMGA_CONNECT": "on"}]
        for env in bad:
            with self.subTest(env={k: env[k] for k in env if k.startswith(("HOME_K", "HOME_I"))}):
                with self.assertRaises(SettingsError) as caught:
                    Settings.from_mapping(env)
                self.assertNotIn("i" * 40, str(caught.exception))


class LegacySwitchTests(Files):
    def test_build_provisioner_makes_komga_keys_only_with_the_legacy_switch(self):
        from dataclasses import replace
        from avrana_home.contract import Service
        from avrana_home.provision import build_provisioner
        store = MemberKeyStore(self.path, writable=True)
        base = replace(Settings(), upstream_mode="real", provision_accounts=("komga",), komga_admin_token="a" * 32,
                       komga_base_url="http://komga.test")
        self.assertIsNone(build_provisioner(base, komga_keys=store))
        on = build_provisioner(replace(base, komga_legacy_provision=True), komga_keys=store)
        self.assertEqual(on.services, (Service.KOMGA,))


def load_offboard():
    spec = importlib.util.spec_from_file_location("offboard_komga_under_test", REPO / "scripts" / "offboard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OffboardTests(Files):
    def setUp(self):
        super().setUp()
        self.offboard = load_offboard()
        self.komga = FakeKeyKomga()
        self.client = KomgaKeyClient("http://komga.test", opener=self.komga)
        self.key, self.kid = self.komga.mint_for("U1")
        MemberKeyStore(self.path, writable=True).put("alice@example.com", self.key, self.kid)

    def act(self, apply_, email="Alice@Example.com"):
        return self.offboard.act_komga_key(email, apply_, keys_file=self.path, client=self.client)

    def test_dry_run_changes_nothing(self):
        said = self.act(False)
        self.assertIn("would REVOKE", said)
        self.assertEqual(self.komga.calls, [])
        self.assertEqual(len(read_keys(self.path)), 1)
        self.assertNotIn(self.key, said)

    def test_apply_revokes_in_komga_and_drops_the_entry(self):
        said = self.act(True)
        self.assertIn("revoked", said)
        self.assertEqual(read_keys(self.path), ())
        self.assertEqual(self.komga.comments("U1"), ["phone"])
        self.assertNotIn(self.key, said)
        self.assertIn("none", self.act(True))

    def test_komga_down_still_drops_and_says_what_to_do(self):
        self.komga.down = True
        said = self.act(True)
        self.assertIn("by hand", said)
        self.assertEqual(read_keys(self.path), ())

    def test_no_file_or_no_email_is_a_no_op(self):
        self.assertIn("nothing to do", self.offboard.act_komga_key("a@example.com", True,
                                                                  keys_file=self.path + ".absent"))
        self.assertIn("nothing to do", self.act(True, email=""))


if __name__ == "__main__":
    unittest.main()
