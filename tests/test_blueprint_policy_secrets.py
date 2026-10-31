"""AVR-791: no credential is ever rendered into an Authentik expression, and the enrollment policies read theirs from
files that only authentik-server mounts.

Two parts. A check over every blueprint file: an `expression` built with !Env or !Format is stored by Authentik as
plain text in Postgres, so also in every database dump and off-host backup and in the admin API. And the three
enrollment policies that hold an admin key, run with stand-ins for Authentik's `request`, `requests`, `open`,
`ak_message` and `ak_logger`. Synthetic values only; no Authentik, no network. The same policies inside a REAL Authentik,
with a sentinel key searched for in the policy rows, a full database dump and the logs:
tests/authentik_enrollment_live.{sh,py} (CI workflow enrollment-policy.yml).
"""
from pathlib import Path
import re
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
AUTHENTIK = ROOT / "services/authentik"
BLUEPRINTS = AUTHENTIK / "blueprints"
ENROLLMENT = BLUEPRINTS / "avrana-enrollment.yaml"
SECRET_DIR = "/run/avrana-policy-secrets/"
JELLYFIN_FILE = SECRET_DIR + "jellyfin_enrollment_key"
KOMGA_FILE = SECRET_DIR + "komga_enrollment_key"
JELLYFIN_KEY = "synthetic-jellyfin-file-key-0123456789"
KOMGA_KEY = "synthetic-komga-file-key-0123456789"
PASSWORD = "test-synthetic-Passw0rd-new-member"
EMAIL = "new.member@example.com"
UNAVAILABLE = "Sign-up is briefly unavailable. Please try again in a few minutes."
# A long hex run, or a credential-named field assigned a quoted literal.
LITERALS = (re.compile(r"[0-9a-fA-F]{32,}"),
            re.compile(r"""(?i)(token|api[-_]?key|authorization|password|secret)["']?\s*[:=]\s*["'][^"'\s]{12,}["']"""))
ENV_READ = re.compile(r"os\.(environ|getenv)[^\n]*(JELLYFIN|KOMGA_ADMIN)")


class Tagged:
    """A value behind a blueprint tag (!Env, !Format, !KeyOf, ...), kept so the check can see that it was tagged."""

    def __init__(self, tag, value):
        self.tag, self.value = tag, value


def load(text):
    class Loader(yaml.SafeLoader):
        pass

    def tagged(ld, suffix, node):
        if isinstance(node, yaml.SequenceNode):
            return Tagged("!" + suffix, ld.construct_sequence(node, deep=True))
        if isinstance(node, yaml.MappingNode):
            return Tagged("!" + suffix, ld.construct_mapping(node, deep=True))
        return Tagged("!" + suffix, ld.construct_scalar(node))
    Loader.add_multi_constructor("!", tagged)
    return yaml.load(text, Loader=Loader)


def expressions(node, where=""):
    """Every `expression` value in a blueprint, whatever the model (policy, property mapping, scope mapping)."""
    if isinstance(node, Tagged):
        yield from expressions(node.value, where)
    elif isinstance(node, dict):
        name = (node.get("identifiers") or {}).get("name") if isinstance(node.get("identifiers"), dict) else None
        for key, value in node.items():
            if key == "expression":
                yield where, value
            else:
                yield from expressions(value, name or where)
    elif isinstance(node, list):
        for value in node:
            yield from expressions(value, where)


def findings(text):
    """What is wrong with one blueprint's text; empty when no expression can carry a credential. Never echoes a value."""
    found = []
    for name, value in expressions(load(text)):
        if not isinstance(value, str):
            tag = value.tag if isinstance(value, Tagged) else type(value).__name__
            found.append(f"{name}: expression is rendered with {tag}, so whatever it embeds is stored in Postgres")
            continue
        if any(pattern.search(value) for pattern in LITERALS):
            found.append(f"{name}: a key-like literal in the expression text")
        if ENV_READ.search(value):
            found.append(f"{name}: reads an admin key from the environment (.env reaches Postgres and the worker too)")
        if '"%s"' in value or "b\"%s" in value:
            found.append(f"{name}: a leftover %s placeholder would be sent as the credential")
    return found


@unittest.skipIf(yaml is None, "PyYAML not installed")
class NoCredentialInAnyExpression(unittest.TestCase):
    def test_every_blueprint_is_clean(self):
        files = sorted(BLUEPRINTS.glob("*.yaml"))
        self.assertGreater(len(files), 10)
        problems = [f"{path.name}: {line}" for path in files for line in findings(path.read_text(encoding="utf-8"))]
        self.assertEqual([], problems)

    def test_the_check_sees_all_the_ways_in(self):
        entry = textwrap.dedent("""\
            entries:
              - model: authentik_policies_expression.expressionpolicy
                identifiers: {name: synthetic}
                attrs:
                  expression: %s
            """)
        for label, expression in (
                ("!Format and !Env", '!Format ["x = %s", !Env SOME_NAME]'),
                ("!Format with an email and password pair", '!Format ["x = b\\"%s:%s\\"", !Env A, !Env B]'),
                ("a bare !Env", "!Env SOME_NAME"),
                ("a literal hex key", '"headers = {\\"X\\": \\"' + "ab12" * 8 + '\\"}"'),
                ("a literal token", '"token = \\"not-hex-but-long-enough\\""'),
                ("a credential-named header", '"h = {\\"X-API-Key\\": \\"not-hex-but-long-enough\\"}"'),
                ("the environment", '"k = os.environ[\\"AVRANA_JELLYFIN_API_KEY\\"]"'),
                ("the Komga key from the environment", '"k = os.environ.get(\\"AVRANA_KOMGA_ADMIN_API_KEY\\")"'),
                ("a leftover placeholder", '"k = \\"%s\\""')):
            with self.subTest(label):
                self.assertTrue(findings(entry % expression), label)
        self.assertEqual([], findings(entry % '"key = read_key(\\"name\\")"'))

    def test_property_mappings_are_covered_too(self):
        text = "entries:\n- model: authentik_core.propertymapping\n  identifiers: {name: m}\n" \
               "  attrs: {expression: !Env SOME_NAME}\n"
        self.assertTrue(findings(text))

    def test_a_credential_outside_an_expression_stays_allowed(self):
        # A provider's client_secret and a stage's SMTP password are model fields Authentik needs in the clear.
        text = "entries:\n- model: authentik_stages_email.emailstage\n  identifiers: {name: m}\n" \
               "  attrs: {password: !Env SOME_NAME}\n"
        self.assertEqual([], findings(text))


@unittest.skipIf(yaml is None, "PyYAML not installed")
class TheKeyFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = yaml.safe_load((AUTHENTIK / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
        cls.example = (AUTHENTIK / "blueprints.env.example").read_text(encoding="utf-8")

    def test_only_the_server_mounts_them_and_read_only(self):
        mount = "./secrets:" + SECRET_DIR.rstrip("/") + ":ro"
        self.assertIn(mount, self.compose["server"]["volumes"])
        for name in ("postgresql", "worker", "ldap"):
            self.assertFalse([v for v in self.compose[name].get("volumes", []) if "secrets" in str(v)], name)

    def test_no_env_file_is_told_to_carry_them(self):
        for name in ("AVRANA_JELLYFIN_API_KEY", "AVRANA_KOMGA_ADMIN_API_KEY", "AVRANA_KOMGA_ADMIN_EMAIL",
                     "AVRANA_KOMGA_ADMIN_PASSWORD"):
            self.assertNotIn(name, self.example)


class Response:
    def __init__(self, status=200, body=None, fail=False):
        self.status_code, self.body, self.fail, self.content, self.text = status, body, fail, b"{}", "synthetic body"

    def raise_for_status(self):
        if self.fail:
            raise RuntimeError("503")

    def json(self):
        return self.body


class Upstreams:
    """Jellyfin and Komga at the addresses the policies call."""

    def __init__(self, jellyfin=None, komga_status=200, komga_raises=None):
        self.calls, self.jellyfin, self.komga_status, self.komga_raises = [], jellyfin or [], komga_status, komga_raises

    def _record(self, method, url, kw):
        self.calls.append((method, url, kw))
        if self.komga_raises and ":25600" in url:
            raise self.komga_raises

    def get(self, url, **kw):
        self._record("GET", url, kw)
        if ":25600" in url:
            return Response(self.komga_status, [])
        return Response(200, self.jellyfin)

    def post(self, url, **kw):
        self._record("POST", url, kw)
        return Response(201 if ":25600" in url else 200, {"Id": "synthetic-id", "Policy": {}})

    def patch(self, url, **kw):
        self._record("PATCH", url, kw)
        return Response(200)


class Logger:
    def __init__(self):
        self.lines = []

    def __getattr__(self, level):
        return lambda *a, **k: self.lines.append((level, a, k))


def opener(files):
    """`open` as the expression sees it: the server's mounted directory and nothing else."""
    class Handle:
        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return self.value

    def call(path, *_a, **_k):
        call.opened.append(path)
        value = files.get(path, FileNotFoundError(2, "No such file or directory", path))
        if isinstance(value, Exception):
            raise value
        return Handle(value)
    call.opened = []
    return call


GOOD = {JELLYFIN_FILE: JELLYFIN_KEY + "\n", KOMGA_FILE: KOMGA_KEY + "\n"}
BAD_FILES = (("absent", {}), ("empty", {JELLYFIN_FILE: "", KOMGA_FILE: ""}),
             ("whitespace", {JELLYFIN_FILE: " \n", KOMGA_FILE: "\n"}),
             ("unreadable", {JELLYFIN_FILE: PermissionError(13, "Permission denied"),
                             KOMGA_FILE: PermissionError(13, "Permission denied")}),
             ("not text", {JELLYFIN_FILE: UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
                           KOMGA_FILE: UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")}))


@unittest.skipIf(yaml is None, "PyYAML not installed")
class Policies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = load(ENROLLMENT.read_text(encoding="utf-8"))["entries"]

    def source(self, entry_id):
        entry = next(e for e in self.entries if e.get("id") == entry_id)
        self.assertIsInstance(entry["attrs"]["expression"], str)
        return "def policy():\n" + textwrap.indent(entry["attrs"]["expression"], "    ")

    def gate(self, files=GOOD, upstreams=None, wanted="new-member"):
        upstreams = upstreams or Upstreams()
        log, messages = Logger(), []
        models = types.ModuleType("authentik.core.models")

        class Query:
            def first(self):
                return None

            def exists(self):
                return False

        class Objects:
            @staticmethod
            def filter(**_kw):
                return Query()
        models.Group = models.User = types.SimpleNamespace(objects=Objects)
        request = types.SimpleNamespace(context={"prompt_data": {"username": wanted}})
        open_ = opener(files)
        ns = {"requests": upstreams, "request": request, "ak_message": messages.append, "ak_logger": log, "open": open_}
        exec(self.source("policy-username-available"), ns)
        with mock.patch.dict(sys.modules, {"authentik": types.ModuleType("authentik"),
                                           "authentik.core": types.ModuleType("authentik.core"),
                                           "authentik.core.models": models}):
            return ns["policy"](), messages, upstreams, log

    def create(self, entry_id, files=GOOD, groups=("avrana-videos", "avrana-comics"), upstreams=None, prompt=None):
        upstreams = upstreams or Upstreams()
        log, messages = Logger(), []
        prompt = {"username": "new-member", "email": EMAIL, "password": PASSWORD} if prompt is None else prompt
        context = {"groups": [types.SimpleNamespace(name=g) for g in groups], "prompt_data": prompt}
        request = types.SimpleNamespace(context={"flow_plan": types.SimpleNamespace(context=context)})
        open_ = opener(files)
        ns = {"requests": upstreams, "request": request, "ak_message": messages.append, "ak_logger": log, "open": open_}
        exec(self.source(entry_id), ns)
        return ns, upstreams, log, open_

    def assert_clean(self, log, *extra):
        text = repr(log.lines) + repr(extra)
        for secret in (JELLYFIN_KEY, KOMGA_KEY, PASSWORD):
            self.assertNotIn(secret, text)

    # --- the gate on the prompt stage: runs before the user is written ---------------------------------------------

    def test_gate_uses_both_keys_from_their_files(self):
        ok, messages, upstreams, log = self.gate()
        self.assertIs(ok, True)
        self.assertEqual([], messages)
        sent = {url: kw["headers"] for _m, url, kw in upstreams.calls}
        self.assertEqual({"http://10.0.0.218:8096/Users": {"X-MediaBrowser-Token": JELLYFIN_KEY},
                          "http://10.0.0.218:25600/api/v2/users": {"X-API-Key": KOMGA_KEY}}, sent)
        self.assert_clean(log)

    def test_gate_refuses_before_any_call_when_a_file_cannot_be_used(self):
        for label, files in BAD_FILES:
            with self.subTest(label):
                ok, messages, upstreams, log = self.gate(files)
                self.assertIs(ok, False)
                self.assertEqual([UNAVAILABLE], messages)
                self.assertEqual([], upstreams.calls)
                self.assertEqual("error", log.lines[-1][0])
                self.assertNotIn(SECRET_DIR, repr(log.lines) + repr(messages))

    def test_gate_refuses_when_only_one_file_is_there(self):
        for present in ({JELLYFIN_FILE: JELLYFIN_KEY}, {KOMGA_FILE: KOMGA_KEY}):
            with self.subTest(sorted(present)):
                ok, messages, upstreams, log = self.gate(present)
                self.assertIs(ok, False)
                self.assertEqual([UNAVAILABLE], messages)
                self.assertEqual([], upstreams.calls)
                self.assert_clean(log)

    def test_gate_refuses_a_komga_key_komga_refuses(self):
        # A stale key is what left every enrollee without a Komga account, unnoticed, until 2026-10-30.
        for status in (401, 403):
            with self.subTest(status):
                ok, messages, _upstreams, log = self.gate(upstreams=Upstreams(komga_status=status))
                self.assertIs(ok, False)
                self.assertEqual([UNAVAILABLE], messages)
                self.assertEqual("error", log.lines[-1][0])

    def test_gate_keeps_letting_sign_up_through_when_komga_is_down(self):
        # As before this change: an outage is not a reason to stop enrollment. Only a refused key is.
        for upstreams in (Upstreams(komga_status=503), Upstreams(komga_raises=ConnectionError("synthetic"))):
            ok, messages, _upstreams, _log = self.gate(upstreams=upstreams)
            self.assertIs(ok, True)
            self.assertEqual([], messages)

    # --- the provisioning policies on the login stage: after the email link, too late to refuse ---------------------

    def test_jellyfin_create_sends_the_key_from_its_file(self):
        ns, upstreams, log, open_ = self.create("policy-jellyfin-create")
        self.assertIs(ns["policy"](), True)
        self.assertEqual([JELLYFIN_FILE], open_.opened)
        method, url, kw = upstreams.calls[0]
        self.assertEqual(("POST", "http://10.0.0.218:8096/Users/New"), (method, url))
        self.assertEqual({"X-MediaBrowser-Token": JELLYFIN_KEY}, kw["headers"])
        self.assert_clean(log)

    def test_komga_create_sends_the_key_from_its_file(self):
        ns, upstreams, log, open_ = self.create("policy-komga-create")
        self.assertIs(ns["policy"](), True)
        self.assertEqual([KOMGA_FILE], open_.opened)
        self.assertEqual(["GET", "POST"], [m for m, _u, _k in upstreams.calls])
        self.assertTrue(all(kw["headers"] == {"X-API-Key": KOMGA_KEY} for _m, _u, kw in upstreams.calls))
        self.assert_clean(log)

    def test_a_member_who_needs_neither_never_touches_a_file(self):
        for entry in ("policy-jellyfin-create", "policy-komga-create"):
            ns, upstreams, _log, open_ = self.create(entry, groups=("avrana-audiobooks",))
            self.assertIs(ns["policy"](), True)
            self.assertEqual(([], []), (open_.opened, upstreams.calls))

    def test_an_unusable_file_is_a_loud_exception_never_a_quiet_true(self):
        # Authentik turns the exception into a policy_exception event (default-notify-exception tells the admins) and
        # passes the text to the member; the other policies on the login stage still run, so sign-in goes on.
        for entry in ("policy-jellyfin-create", "policy-komga-create"):
            for label, files in BAD_FILES:
                with self.subTest(entry=entry, file=label):
                    ns, upstreams, log, _open = self.create(entry, files)
                    with self.assertRaises(RuntimeError) as caught:
                        ns["policy"]()
                    self.assertEqual([], upstreams.calls)
                    self.assertEqual("error", log.lines[-1][0])
                    self.assertIsNone(caught.exception.__cause__)
                    self.assertTrue(caught.exception.__suppress_context__)
                    self.assertNotIn(SECRET_DIR, str(caught.exception))
                    self.assert_clean(log, str(caught.exception))

    def test_a_failing_request_logs_only_its_type(self):
        for entry, secret in (("policy-jellyfin-create", JELLYFIN_KEY), ("policy-komga-create", KOMGA_KEY)):
            class Boom(Upstreams):
                def post(self, url, **kw):
                    raise ConnectionError("synthetic " + secret + " " + PASSWORD)

                def get(self, url, **kw):
                    raise ConnectionError("synthetic " + secret + " " + PASSWORD)
            ns, _upstreams, log, _open = self.create(entry, upstreams=Boom())
            self.assertIs(ns["policy"](), True)
            self.assert_clean(log)
            self.assertIn("ConnectionError", repr(log.lines))


if __name__ == "__main__":
    unittest.main()
