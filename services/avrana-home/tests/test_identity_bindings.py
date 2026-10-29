"""identity_bindings.py (RC1 finding S1) and the principal's `subject`. Offline, temporary files, synthetic values."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import json
import os
import stat
import tempfile
import threading
import unittest
from unittest import mock

from avrana_home import identity_bindings as ib
from avrana_home.principal import principal_from_headers, principal_from_verified_jwt


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "identity_bindings.json")
        self.logs = []
        self.store = ib.IdentityBindings(self.path, log=lambda **f: self.logs.append(f))

    def test_first_sight_binds_then_only_the_same_subject_passes(self):
        self.assertEqual(ib.OK, self.store.check("member-a", "sub-1"))
        self.assertEqual(ib.OK, self.store.check("member-a", "sub-1"))
        self.assertEqual(ib.CHANGED, self.store.check("member-a", "sub-2"))
        self.assertEqual(ib.OK, self.store.check("member-b", "sub-2"))       # names are independent
        data = json.loads(open(self.path, encoding="utf-8").read())
        self.assertEqual({"member-a": ib.digest("sub-1"), "member-b": ib.digest("sub-2")}, data)
        if os.name == "posix":
            self.assertEqual(0o600, stat.S_IMODE(os.stat(self.path).st_mode))

    def test_case_variants_are_different_names(self):
        self.store.check("member-a", "sub-1")
        self.assertEqual(ib.OK, self.store.check("Member-A", "sub-9"))       # Home never maps it to member-a's accounts

    def test_no_subject_never_binds(self):
        for sub in (None, "", 7):
            self.assertEqual(ib.NO_SUBJECT, self.store.check("member-a", sub))
        self.assertFalse(os.path.exists(self.path))

    def test_a_second_process_writing_the_file_is_seen(self):
        self.store.check("member-a", "sub-1")
        other = ib.IdentityBindings(self.path)
        self.assertEqual(ib.CHANGED, other.check("member-a", "sub-2"))
        ib.write_bindings(self.path, {})                                      # the owner's release
        self.assertEqual(ib.OK, self.store.check("member-a", "sub-2"))

    def test_malformed_file_refuses_and_recovers(self):
        for bad in ("{", "[]", json.dumps({"member-a": "not-a-digest"}), json.dumps({"": "0" * 64})):
            with self.subTest(bad=bad):
                with open(self.path, "w", encoding="utf-8") as fh:
                    fh.write(bad)
                self.assertEqual(ib.UNAVAILABLE, self.store.check("member-a", "sub-1"))
        ib.write_bindings(self.path, {"member-a": ib.digest("sub-1")})
        self.assertEqual(ib.OK, self.store.check("member-a", "sub-1"))
        self.assertIn({"state": "refused", "reason": "malformed"}, self.logs)
        self.assertFalse(any("sub-1" in repr(entry) for entry in self.logs))

    def test_an_unwritable_folder_refuses_new_names_but_keeps_known_ones(self):
        self.store.check("member-a", "sub-1")
        with mock.patch.object(ib, "write_bindings", side_effect=OSError("read-only")):
            self.assertEqual(ib.UNAVAILABLE, self.store.check("member-b", "sub-2"))
            self.assertEqual(ib.OK, self.store.check("member-a", "sub-1"))

    def test_concurrent_first_sights_bind_one_subject(self):
        out = []
        threads = [threading.Thread(target=lambda s=s: out.append(self.store.check("member-a", s)))
                   for s in ("sub-1", "sub-2") * 8]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(1, len({o for o in out} - {ib.CHANGED}))
        self.assertIn(ib.CHANGED, out)

    def test_cli_count_list_release(self):
        self.store.check("member-a", "sub-1")
        self.assertEqual(0, ib.main(["--file", self.path, "count"]))
        self.assertEqual(1, ib.main(["--file", self.path, "release", "nobody"]))
        self.assertEqual(0, ib.main(["--file", self.path, "release", "member-a"]))
        self.assertEqual({}, ib.read_bindings(self.path))

    def test_repr_redacts(self):
        self.assertEqual("IdentityBindings(<redacted>)", repr(self.store))


class Verifier:
    def __init__(self, claims):
        self.claims = claims

    def verify(self, token):
        return self.claims


class PrincipalSubject(unittest.TestCase):
    def test_the_verified_sub_is_carried_and_the_header_path_has_none(self):
        p = principal_from_verified_jwt({"X-authentik-jwt": "t"}, Verifier(
            {"preferred_username": "member-a", "groups": ["avrana-users"], "sub": "synthetic-sub"}))
        self.assertEqual("synthetic-sub", p.subject)
        q = principal_from_verified_jwt({"X-authentik-jwt": "t"}, Verifier(
            {"preferred_username": "member-a", "groups": ["avrana-users"]}))
        self.assertIsNone(q.subject)
        h = principal_from_headers({"X-authentik-username": "member-a", "X-authentik-groups": "avrana-users"})
        self.assertIsNone(h.subject)
        with self.assertRaises(AttributeError):
            p.subject = "other"


if __name__ == "__main__":
    unittest.main()
