"""RC1 finding S1: `offboard.py --purge` retires the name before it deletes the Authentik user.

Runs the ak-shell script act_authentik builds against stand-in Authentik models. No docker, no Authentik, no network;
synthetic names only. (scripts/test_offboard.py covers the rest of the tool on the host.)
"""
from pathlib import Path
import importlib.util
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_offboard():
    spec = importlib.util.spec_from_file_location("offboard_under_test", ROOT / "scripts" / "offboard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeAuthentik:
    def __init__(self, users, retired=None, fail_save=False):
        self.users, self.deleted, self.fail_save = list(users), [], fail_save
        self.group = None if retired is None else types.SimpleNamespace(attributes={"usernames": list(retired)})
        fake = self

        class Query:
            def __init__(self, rows):
                self.rows = rows

            def exists(self):
                return bool(self.rows)

            def delete(self):
                fake.deleted.extend(self.rows)
                fake.users = [u for u in fake.users if u not in self.rows]
                return (len(self.rows), {})

        class User:
            class objects:
                @staticmethod
                def filter(username__iexact):
                    return Query([u for u in fake.users if u.casefold() == username__iexact.casefold()])

        class Group:
            class objects:
                @staticmethod
                def get_or_create(name):
                    assert name == "avrana-retired-usernames"
                    created = fake.group is None
                    if created:
                        fake.group = types.SimpleNamespace(attributes={})
                    group = fake.group

                    def save():
                        if fake.fail_save:
                            raise RuntimeError("synthetic database error")
                    group.save = save
                    return group, created
        self.User, self.Group = User, Group

    def run(self, script):
        printed = []
        ns = {"print": lambda *a: printed.append(" ".join(map(str, a)))}
        models = types.ModuleType("authentik.core.models")
        models.User, models.Group = self.User, self.Group
        with mock.patch.dict("sys.modules", {"authentik": types.ModuleType("authentik"),
                                             "authentik.core": types.ModuleType("authentik.core"),
                                             "authentik.core.models": models}):
            try:
                exec(script, ns)
            except RuntimeError:
                pass
        return "\n".join(printed)

    @property
    def retired(self):
        return None if self.group is None else self.group.attributes.get("usernames")


class PurgeRetiresTheName(unittest.TestCase):
    def setUp(self):
        self.offboard = load_offboard()

    def purge(self, fake, name="former"):
        with mock.patch.object(self.offboard, "sh", side_effect=lambda cmd: fake.run(self.script(cmd))):
            return self.offboard.act_authentik({"username": name}, purge=True, apply_=True)

    @staticmethod
    def script(cmd):
        import shlex
        return shlex.split(cmd)[-1]

    def test_purge_retires_then_deletes(self):
        fake = FakeAuthentik(["former", "member-a"])
        self.assertEqual("retired the name and deleted authentik/former", self.purge(fake))
        self.assertEqual(["former"], fake.retired)
        self.assertEqual(["former"], fake.deleted)

    def test_an_existing_list_is_kept_and_not_duplicated(self):
        fake = FakeAuthentik(["Former"], retired=["older", "FORMER"])
        self.purge(fake, "Former")
        self.assertEqual(["older", "FORMER"], fake.retired)

    def test_if_retiring_fails_nothing_is_deleted(self):
        fake = FakeAuthentik(["former"], fail_save=True)
        self.assertIn("FAILED to retire", self.purge(fake))
        self.assertEqual([], fake.deleted)

    def test_deactivate_never_runs_the_purge_script(self):
        calls = []
        with mock.patch.object(self.offboard, "sh", side_effect=lambda cmd: calls.append(cmd) or ""):
            self.assertEqual("deactivated authentik/former",
                             self.offboard.act_authentik({"username": "former"}, purge=False, apply_=True))
        self.assertTrue(all("is_active=false" in c for c in calls))


if __name__ == "__main__":
    unittest.main()
