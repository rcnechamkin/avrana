"""RC1 finding S1: enrollment refuses a username that already has a Jellyfin account, that is a letter-case twin of
an existing Authentik user, or that is retired (avrana-enrollment.yaml).

Runs the blueprint's expression with stand-ins for Authentik's `request`, `requests`, `ak_message`, `ak_logger` and
`authentik.core.models`. Synthetic names only; no Authentik, no Jellyfin, no network. The same policy against a
real Authentik: tests/authentik_enrollment_live.py (CI workflow enrollment-policy.yml).
"""
from pathlib import Path
import sys
import textwrap
import types
import unittest
from unittest import mock

try:
    import yaml
except ImportError:          # run_offline.py fails loudly without PyYAML (AVRANA_REQUIRE_YAML)
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = ROOT / "services/authentik/blueprints/avrana-enrollment.yaml"


def load():
    class Loader(yaml.SafeLoader):
        pass
    for tag in ("!KeyOf", "!Env", "!Format", "!Find"):
        Loader.add_constructor(tag, lambda ld, node, tag=tag: ld.construct_sequence(node)
                               if isinstance(node, yaml.SequenceNode) else (tag, ld.construct_scalar(node)))
    return yaml.load(BLUEPRINT.read_text(encoding="utf-8"), Loader=Loader)


class Response:
    def __init__(self, users=None, fail=False):
        self.users, self.fail = users or [], fail

    def raise_for_status(self):
        if self.fail:
            raise RuntimeError("503")

    def json(self):
        return self.users


@unittest.skipIf(yaml is None, "PyYAML not installed")
class UsernameAvailable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load()
        cls.entries = cls.doc["entries"]
        cls.ids = [e.get("id") for e in cls.entries]
        policy = cls.entries[cls.ids.index("policy-username-available")]
        template, _key = policy["attrs"]["expression"]
        cls.source = "def policy():\n" + textwrap.indent(template % "SYNTHETIC-KEY", "    ")

    def run_policy(self, wanted, users=None, fail=False, raises=None, authentik_users=(), retired=None):
        calls, messages = [], []
        models = types.ModuleType("authentik.core.models")

        class Query:
            def __init__(self, rows):
                self.rows = rows

            def first(self):
                return self.rows[0] if self.rows else None

            def exists(self):
                return bool(self.rows)

        class Group:
            class objects:
                @staticmethod
                def filter(name):
                    found = retired is not None and name == "avrana-retired-usernames"
                    return Query([types.SimpleNamespace(attributes={"usernames": retired})] if found else [])

        class User:
            class objects:
                @staticmethod
                def filter(username__iexact):
                    return Query([u for u in authentik_users if u.casefold() == username__iexact.casefold()])
        models.Group, models.User = Group, User

        class Requests:
            @staticmethod
            def get(url, headers=None, timeout=None):
                calls.append((url, headers))
                if raises:
                    raise raises
                return Response(users, fail)

        class Logger:
            def __getattr__(self, _name):
                return lambda *a, **k: None

        class Request:
            context = {"prompt_data": {"username": wanted}}

        ns = {"requests": Requests, "request": Request, "ak_message": messages.append, "ak_logger": Logger()}
        exec(self.source, ns)
        with mock.patch.dict(sys.modules, {"authentik": types.ModuleType("authentik"),
                                           "authentik.core": types.ModuleType("authentik.core"),
                                           "authentik.core.models": models}):
            return ns["policy"](), messages, calls

    def test_bound_to_the_prompt_stage_and_defined_before_it(self):
        stage = self.entries[self.ids.index("stage-prompt")]
        self.assertEqual([("!KeyOf", "policy-username-available")], stage["attrs"].get("validation_policies"))
        self.assertLess(self.ids.index("policy-username-available"), self.ids.index("stage-prompt"))

    def test_a_free_name_passes(self):
        ok, messages, calls = self.run_policy("new-member", [{"Name": "member-a"}, {"Name": "Member-B"}])
        self.assertTrue(ok)
        self.assertEqual([], messages)
        self.assertEqual({"X-MediaBrowser-Token": "SYNTHETIC-KEY"}, calls[0][1])

    def test_an_existing_jellyfin_name_is_refused_in_any_case(self):
        for wanted in ("member-a", "MEMBER-A", "Member-A"):
            with self.subTest(wanted=wanted):
                ok, messages, _ = self.run_policy(wanted, [{"Name": "member-a"}])
                self.assertFalse(ok)
                self.assertEqual(["That username is taken. Please pick another."], messages)

    def test_jellyfin_unreachable_or_erroring_refuses(self):
        for kw in ({"raises": OSError("down")}, {"fail": True}):
            with self.subTest(kw=kw):
                ok, messages, _ = self.run_policy("new-member", **kw)
                self.assertFalse(ok)
                self.assertIn("try again", messages[0])

    def test_a_retired_name_is_refused_in_any_case_without_asking_jellyfin(self):
        for wanted in ("former", "FORMER"):
            ok, messages, calls = self.run_policy(wanted, [], retired=["Former", "other"])
            self.assertFalse(ok)
            self.assertEqual(["That username is taken. Please pick another."], messages)
            self.assertEqual([], calls)
        self.assertTrue(self.run_policy("new-member", [], retired=["former"])[0])
        self.assertTrue(self.run_policy("new-member", [], retired=None)[0])     # group not created yet

    def test_a_letter_case_twin_of_an_existing_authentik_user_is_refused(self):
        ok, messages, _ = self.run_policy("Member-A", [], authentik_users=["member-a"])
        self.assertFalse(ok)
        self.assertIn("taken", messages[0])

    def test_the_retired_group_is_created_once_and_never_reset(self):
        group = self.entries[self.ids.index("group-retired-usernames")]
        self.assertEqual("created", group.get("state"))        # re-applying the blueprint keeps the list
        self.assertEqual({"usernames": []}, group["attrs"]["attributes"])

    def test_an_empty_name_is_refused(self):
        self.assertFalse(self.run_policy("")[0])


if __name__ == "__main__":
    unittest.main()
