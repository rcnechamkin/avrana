"""identity_bindings.py (RC1 finding S1) and the principal's `subject`. Offline, temporary files, synthetic values.

Adversarial: a recreated account under a seeded name, a deleted or rolled-back file, letter-case twins of bound and
reserved names, releases while an upstream account or member row survives, and several PROCESSES binding and
claiming at once."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import contextlib
import io
import json
import multiprocessing
import os
import shutil
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from avrana_home import identity_bindings as ib
from avrana_home.memberstore import MemberStore
from avrana_home.principal import principal_from_headers, principal_from_verified_jwt

SEED = {"member-a": ib.digest("sub-a"), "member-b": ib.digest("sub-b"), "former": ib.digest("sub-former")}


def write_seed(folder, users):
    path = os.path.join(folder, "seed.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"format": ib.SEED_FORMAT, "version": ib.SEED_VERSION, "users": users}, fh)
    return path


def run(argv, senders=None):
    err, out = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        code = ib.main(argv, env={}, senders=senders)
    return code, out.getvalue(), err.getvalue()


def senders(jellyfin=(), audiobookshelf=(), store=None, fail=False):
    def jf(method, path, body):
        if fail:
            raise ConnectionRefusedError("synthetic")
        assert (method, path) == ("GET", "/Users")
        return [{"Name": n, "Id": str(i)} for i, n in enumerate(jellyfin)]

    def abs_(method, path, body):
        assert (method, path) == ("GET", "/api/users")
        return {"users": [{"username": n, "id": str(i)} for i, n in enumerate(audiobookshelf)]}
    return jf, abs_, store


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "identity_bindings.json")
        self.logs = []

    def init(self, users=SEED, reserve_upstream=None):
        argv = ["--file", self.path, "init", "--seed", write_seed(self.tmp.name, users)]
        if reserve_upstream is not None:
            argv.append("--reserve-upstream")
        code, out, err = run(argv, senders=reserve_upstream)
        self.assertEqual(0, code, err)
        return out

    def store(self):
        return ib.IdentityBindings(self.path, log=lambda **f: self.logs.append(f))

    def state(self):
        return ib.read_state(self.path)


class Seeded(Base):
    def test_seeded_members_pass_and_a_recreated_account_never_binds(self):
        self.init()
        store = self.store()
        self.assertEqual(ib.OK, store.check("member-a", "sub-a"))
        # A new Authentik user given a seeded name: refused from its FIRST request, not "first sight wins".
        self.assertEqual(ib.CHANGED, store.check("former", "sub-recreated"))
        self.assertEqual(ib.OK, store.check("former", "sub-former"))
        if os.name == "posix":
            self.assertEqual(0o600, stat.S_IMODE(os.stat(self.path).st_mode))

    def test_a_member_who_joined_later_binds_at_first_sign_in(self):
        self.init()
        store = self.store()
        self.assertEqual(ib.OK, store.check("newcomer", "sub-new"))
        self.assertEqual(ib.CHANGED, store.check("newcomer", "sub-other"))
        self.assertEqual(ib.digest("sub-new"), self.state().bindings["newcomer"])

    def test_letter_case_twins_of_a_bound_name_are_refused_not_bound(self):
        self.init()
        store = self.store()
        for twin in ("Member-A", "MEMBER-A", "member-ａ"):                 # fullwidth a folds to a under NFKC
            self.assertEqual(ib.NAME_RESERVED, store.check(twin, "sub-attacker"), twin)
        self.assertNotIn("Member-A", self.state().bindings)

    def test_no_subject_never_binds(self):
        self.init()
        store = self.store()
        for sub in (None, "", 7):
            self.assertEqual(ib.NO_SUBJECT, store.check("newcomer", sub))
        self.assertNotIn("newcomer", self.state().bindings)

    def test_upstream_names_without_an_authentik_user_are_reserved(self):
        self.init(reserve_upstream=senders(jellyfin=["member-a", "orphan", "Ghost"], audiobookshelf=["abs-only"]))
        state = self.state()
        self.assertEqual(ib.RESERVED, state.bindings["orphan"])
        self.assertEqual(ib.RESERVED, state.bindings["abs-only"])
        self.assertEqual(SEED["member-a"], state.bindings["member-a"])     # a seeded name is bound, not reserved
        store = self.store()
        for name in ("orphan", "Orphan", "ghost", "abs-only"):
            self.assertEqual(ib.NAME_RESERVED, store.check(name, "sub-enrolled-later"), name)

    def test_reserve_upstream_refuses_when_an_upstream_cannot_be_read(self):
        code, _out, err = run(["--file", self.path, "init", "--seed", write_seed(self.tmp.name, SEED),
                               "--reserve-upstream"], senders=senders(fail=True))
        self.assertEqual(2, code)
        self.assertIn("could not run", err)
        self.assertFalse(os.path.exists(self.path))

    def test_cli_count_and_list(self):
        self.init(reserve_upstream=senders(jellyfin=["orphan"]))
        code, out, _ = run(["--file", self.path, "count"])
        self.assertEqual((0, "3 bound, 1 reserved, 0 released\n"), (code, out))
        code, out, _ = run(["--file", self.path, "list"])
        self.assertIn("orphan\treserved", out)
        self.assertNotIn(SEED["member-a"], out)                               # names only, never a digest

    def test_repr_and_logs_redact(self):
        self.init()
        store = self.store()
        store.check("newcomer", "sub-new")
        self.assertEqual("IdentityBindings(<redacted>)", repr(store))
        self.assertFalse(any("sub-new" in repr(e) or ib.digest("sub-new") in repr(e) or "newcomer" in repr(e)
                             for e in self.logs))


class FailClosed(Base):
    def test_no_file_refuses_everyone_and_home_never_creates_it(self):
        store = self.store()
        self.assertEqual(ib.UNAVAILABLE, store.check("member-a", "sub-a"))
        self.assertFalse(store.available)
        self.assertFalse(os.path.exists(self.path))
        self.assertIn({"state": "refused", "reason": "missing"}, self.logs)

    def test_deleting_an_initialised_file_refuses_and_is_never_reseeded(self):
        self.init()
        store = self.store()
        self.assertEqual(ib.OK, store.check("member-a", "sub-a"))
        os.unlink(self.path)
        for name, sub in (("member-a", "sub-a"), ("former", "sub-recreated"), ("newcomer", "sub-new")):
            self.assertEqual(ib.UNAVAILABLE, store.check(name, sub))
        self.assertFalse(os.path.exists(self.path))
        self.init()                                                           # the owner's explicit recovery
        self.assertEqual(ib.OK, store.check("member-a", "sub-a"))
        self.assertEqual(ib.CHANGED, store.check("former", "sub-recreated"))

    def test_a_file_that_lost_a_binding_is_refused_whole(self):
        self.init()
        backup = os.path.join(self.tmp.name, "backup.json")
        shutil.copy(self.path, backup)
        store = self.store()
        self.assertEqual(ib.OK, store.check("newcomer", "sub-new"))
        shutil.copy(backup, self.path)                                        # an older copy, or a hand edit
        self.assertEqual(ib.UNAVAILABLE, store.check("newcomer", "sub-impostor"))
        self.assertEqual(ib.UNAVAILABLE, store.check("member-a", "sub-a"))
        self.assertIn("shrunk", {e.get("reason") for e in self.logs})
        state = self.state()                                                  # the owner re-adds it on purpose
        state.bindings["newcomer"] = ib.digest("sub-new")
        ib.write_state(self.path, state)
        self.assertEqual(ib.OK, store.check("member-a", "sub-a"))
        self.assertEqual(ib.CHANGED, store.check("newcomer", "sub-impostor"))

    def test_malformed_or_old_format_refuses_and_recovers(self):
        self.init()
        good = Path(self.path).read_text(encoding="utf-8")
        store = self.store()
        doubled = json.loads(good)
        doubled["bindings"]["MEMBER-A"] = ib.digest("x")
        for bad in ("{", "[]", json.dumps({"member-a": ib.digest("sub-a")}),             # the version 1 shape
                    good.replace('"version": 2', '"version": 3'),
                    good.replace(SEED["member-a"], "not-a-digest"), json.dumps(doubled)):
            with self.subTest(bad=bad[:40]):
                with open(self.path, "w", encoding="utf-8") as fh:
                    fh.write(bad)
                self.assertEqual(ib.UNAVAILABLE, store.check("member-a", "sub-a"))
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(good)
        self.assertEqual(ib.OK, store.check("member-a", "sub-a"))
        self.assertIn({"state": "refused", "reason": "malformed"}, self.logs)

    def test_an_unwritable_folder_refuses_new_names_but_keeps_known_ones(self):
        self.init()
        store = self.store()
        with mock.patch.object(ib, "write_state", side_effect=OSError("read-only")):
            self.assertEqual(ib.UNAVAILABLE, store.check("newcomer", "sub-new"))
            self.assertEqual(ib.OK, store.check("member-a", "sub-a"))

    def test_init_never_overwrites_a_differing_binding_or_an_unreadable_file(self):
        self.init()
        before = Path(self.path).read_text(encoding="utf-8")
        code, _out, err = run(["--file", self.path, "init", "--seed",
                               write_seed(self.tmp.name, dict(SEED, former=ib.digest("sub-recreated")))])
        self.assertEqual(2, code)
        self.assertIn("former", err)
        self.assertEqual(before, Path(self.path).read_text(encoding="utf-8"))
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{")
        code, _out, _err = run(["--file", self.path, "init", "--seed", write_seed(self.tmp.name, SEED)])
        self.assertEqual(2, code)
        self.assertEqual("{", Path(self.path).read_text(encoding="utf-8"))

    def test_init_merges_a_newer_seed(self):
        self.init()
        store = self.store()
        store.check("newcomer", "sub-new")
        self.init(dict(SEED, later=ib.digest("sub-later")))
        state = self.state()
        self.assertEqual(ib.digest("sub-new"), state.bindings["newcomer"])
        self.assertEqual(ib.digest("sub-later"), state.bindings["later"])
        self.assertEqual(ib.OK, store.check("newcomer", "sub-new"))


class Release(Base):
    def setUp(self):
        super().setUp()
        self.init()

    def test_release_needs_the_owner_to_confirm_the_other_apps(self):
        code, _out, err = run(["--file", self.path, "release", "former"], senders=senders())
        self.assertEqual(2, code)
        self.assertIn("identity-bindings.md", err)
        self.assertIn("former", self.state().bindings)

    def test_release_refuses_while_any_library_still_holds_the_name(self):
        for kwargs in ({"jellyfin": ["Former"]}, {"audiobookshelf": ["former"]}, {"jellyfin": ["ｆormer"]}):
            with self.subTest(**{k: v[0] for k, v in kwargs.items()}):
                code, _out, err = run(["--file", self.path, "release", "former", "--other-apps-cleared"],
                                      senders=senders(**kwargs))
                self.assertEqual(2, code)
                self.assertIn("still has an account", err)
                self.assertIn("former", self.state().bindings)

    def test_release_refuses_when_a_library_cannot_be_asked(self):
        code, _out, err = run(["--file", self.path, "release", "former", "--other-apps-cleared"],
                              senders=senders(fail=True))
        self.assertEqual(2, code)
        self.assertIn("could not run", err)
        self.assertIn("former", self.state().bindings)

    def test_release_refuses_while_the_member_store_holds_the_name(self):
        db = Path(self.tmp.name) / "members.sqlite"
        ms = MemberStore(db)
        self.assertEqual("saved", ms.save_name("former", "Former Member", 0)[0])
        ms.close()
        code, _out, err = run(["--file", self.path, "release", "former", "--other-apps-cleared"],
                              senders=senders(store=db))
        self.assertEqual(2, code)
        self.assertIn("member store", err)
        ms = MemberStore(db)
        ms.purge("former")
        ms.close()
        code, _out, err = run(["--file", self.path, "release", "former", "--other-apps-cleared"],
                              senders=senders(store=db))
        self.assertEqual(0, code, err)

    def test_a_clean_release_lets_the_next_holder_bind_without_tripping_the_shrink_guard(self):
        store = self.store()
        self.assertEqual(ib.OK, store.check("former", "sub-former"))
        code, _out, err = run(["--file", self.path, "release", "former", "--other-apps-cleared"],
                              senders=senders(jellyfin=["member-a"]))
        self.assertEqual(0, code, err)
        self.assertIn("former", self.state().released)
        self.assertEqual(ib.OK, store.check("member-a", "sub-a"))             # not "shrunk"
        self.assertEqual(ib.OK, store.check("former", "sub-next"))
        self.assertNotIn("former", self.state().released)

    def test_reserve_then_release_an_orphan_name(self):
        self.assertEqual(0, run(["--file", self.path, "reserve", "orphan"])[0])
        self.assertEqual(1, run(["--file", self.path, "reserve", "Orphan"])[0])
        self.assertEqual(ib.NAME_RESERVED, self.store().check("orphan", "sub-x"))
        self.assertEqual(0, run(["--file", self.path, "release", "orphan", "--other-apps-cleared"],
                                senders=senders())[0])


# ---- several processes at once (module level so spawn can import them) ------------------------------------
def _claim(path, name, subject, gate, out):
    store = ib.IdentityBindings(path)
    gate.wait()
    out.put((subject, store.check(name, subject)))


def _bind_many(path, prefix, count, gate, out):
    store = ib.IdentityBindings(path)
    gate.wait()
    out.put([store.check(f"{prefix}-{i}", f"sub-{prefix}-{i}") for i in range(count)])


def _cli_reserve(path, prefix, count, gate, out):
    gate.wait()
    codes = []
    for i in range(count):
        with contextlib.redirect_stdout(io.StringIO()):
            codes.append(ib.main(["--file", path, "reserve", f"{prefix}-{i}"], env={}))
    out.put(codes)


class Processes(Base):
    def setUp(self):
        super().setUp()
        self.init()
        self.ctx = multiprocessing.get_context("spawn")

    def start(self, jobs):
        gate, out = self.ctx.Event(), self.ctx.Queue()
        procs = [self.ctx.Process(target=fn, args=(self.path,) + args + (gate, out)) for fn, args in jobs]
        for p in procs:
            p.start()
        gate.set()
        results = [out.get(timeout=120) for _ in procs]
        for p in procs:
            p.join(timeout=60)
            self.assertEqual(0, p.exitcode)
        return results

    def test_conflicting_claims_on_one_new_name_have_one_winner(self):
        results = self.start([(_claim, ("contested", f"sub-{i}")) for i in range(6)])
        winners = [s for s, outcome in results if outcome == ib.OK]
        self.assertEqual(1, len(winners), results)
        self.assertEqual({ib.CHANGED}, {o for s, o in results if s not in winners})
        self.assertEqual(ib.digest(winners[0]), self.state().bindings["contested"])

    def test_no_binding_is_lost_when_processes_write_at_once(self):
        jobs = [(_bind_many, (f"w{i}", 8)) for i in range(4)] + [(_cli_reserve, ("owner", 8),)]
        results = self.start(jobs)
        self.assertEqual(4 * 8 + 8, sum(len(r) for r in results))
        self.assertEqual({ib.OK, 0}, {o for r in results for o in r}, results)   # nobody was refused or lost
        state = self.state()
        for i in range(4):
            for j in range(8):
                self.assertEqual(ib.digest(f"sub-w{i}-{j}"), state.bindings[f"w{i}-{j}"])
        for j in range(8):
            self.assertEqual(ib.RESERVED, state.bindings[f"owner-{j}"])
        for name, value in SEED.items():
            self.assertEqual(value, state.bindings[name])


class Threads(Base):
    def test_concurrent_first_sights_bind_one_subject(self):
        self.init()
        store, out = self.store(), []
        threads = [threading.Thread(target=lambda s=s: out.append((s, store.check("contested", s))))
                   for s in ("sub-1", "sub-2") * 8]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(1, len({s for s, o in out if o == ib.OK}))
        self.assertIn(ib.CHANGED, {o for _s, o in out})


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
