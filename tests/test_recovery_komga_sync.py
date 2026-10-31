"""The password-reset policy `avrana-komga-password-sync` (avrana-recovery.yaml; docs/runbooks/komga-password-sync.md):
after a member proves their email and chooses a new Avrana password, it gives their Komga account the same password
(creating the account when missing), then mints their own `avrana-home` key and hands it to Home's intake with source
`recovery`. It never fails the reset.

Runs the blueprint's expression with stand-ins for Authentik's `request`, `requests` and `ak_logger`. Synthetic
accounts only; no Authentik, no Komga, no Home, no network. The policy's presence, binding and validity inside a REAL
Authentik: tests/authentik_enrollment_live.py (CI workflow enrollment-policy.yml).
"""
from pathlib import Path
import hashlib
import os
import textwrap
import types
import unittest
from unittest import mock

try:
    import yaml
except ImportError:          # run_offline.py fails loudly without PyYAML (AVRANA_REQUIRE_YAML)
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = ROOT / "services/authentik/blueprints/avrana-recovery.yaml"
ACCOUNT = ROOT / "services/authentik/blueprints/avrana-account.yaml"
TOKEN = "synthetic-intake-token-" + "x" * 20
ADMIN_KEY = "synthetic-komga-admin-key-" + "y" * 10
PASSWORD = "test-synthetic-Passw0rd-after-reset"
EMAIL = "Member@Example.com"
UID = "synthetic-hashed-user-id"
KEY = "0123456789abcdef0123456789abcdef"
KOMGA = "http://10.0.0.218:25600"
USERS_URL = KOMGA + "/api/v2/users"
KEYS_URL = KOMGA + "/api/v2/users/me/api-keys"


def load(path):
    class Loader(yaml.SafeLoader):
        pass
    for tag in ("!KeyOf", "!Env", "!Format", "!Find"):
        Loader.add_constructor(tag, lambda ld, node, tag=tag: (tag, ld.construct_sequence(node))
                               if isinstance(node, yaml.SequenceNode) else (tag, ld.construct_scalar(node)))
    return yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


class FakeRequests:
    """Komga's admin routes (X-API-Key), the member's own key routes (Basic) and Home's intake."""

    def __init__(self, accounts=None, users_status=200, patch=204, create=201, sign_in=(200,), post=200, put=204,
                 raises=None, put_raises=None):
        self.calls = []
        self.accounts = [{"id": "U-1", "email": "member@example.com"}] if accounts is None else accounts
        self.users_status, self.patch_status, self.create_status = users_status, patch, create
        self.sign_in, self.post_status, self.put_status = list(sign_in), post, put
        self.raises, self.put_raises = raises, put_raises
        self.keys = [{"id": "K-old", "comment": "avrana-home"}, {"id": "K-own", "comment": "phone"}]

    def _record(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if self.raises:
            raise self.raises

    def get(self, url, **kw):
        self._record("GET", url, **kw)
        if url == USERS_URL:
            return Resp(self.users_status, list(self.accounts) if self.users_status == 200 else None)
        status = self.sign_in.pop(0) if len(self.sign_in) > 1 else self.sign_in[0]
        return Resp(status, list(self.keys) if status == 200 else None)

    def patch(self, url, **kw):
        self._record("PATCH", url, **kw)
        return Resp(self.patch_status)

    def delete(self, url, **kw):
        self._record("DELETE", url, **kw)
        return Resp(204)

    def post(self, url, **kw):
        self._record("POST", url, **kw)
        if url == USERS_URL:
            return Resp(self.create_status, {"id": "U-new", "email": EMAIL.lower()})
        return Resp(self.post_status, {"id": "K-new", "key": KEY, "comment": "avrana-home"})

    def put(self, url, **kw):
        self._record("PUT", url, **kw)
        if self.put_raises:
            raise self.put_raises
        return Resp(self.put_status)


class Logger:
    def __init__(self):
        self.lines = []

    def __getattr__(self, level):
        return lambda *a, **k: self.lines.append((level, a, k))


class Groups:
    def __init__(self, names, broken=False):
        self.names, self.broken = set(names), broken

    def filter(self, name):
        if self.broken:
            raise RuntimeError("synthetic database error")
        return types.SimpleNamespace(exists=lambda: name in self.names)


@unittest.skipIf(yaml is None, "PyYAML not installed")
class KomgaPasswordSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load(BLUEPRINT)
        cls.entries = cls.doc["entries"]
        cls.ids = [e.get("id") for e in cls.entries]
        policy = cls.entries[cls.ids.index("policy-komga-password-sync")]
        cls.expression = policy["attrs"]["expression"]
        cls.source = "def policy():\n" + textwrap.indent(cls.expression, "    ")

    def run_policy(self, fake=None, groups=("avrana-comics",), token=TOKEN, admin_key=ADMIN_KEY, prompt=None,
                   user=True, uid=UID, email=EMAIL, plan=True, broken_groups=False):
        fake = fake or FakeRequests()
        log = Logger()
        prompt = {"password": PASSWORD, "password_repeat": PASSWORD} if prompt is None else prompt
        pending = types.SimpleNamespace(email=email, uid=uid, ak_groups=Groups(groups, broken_groups)) if user else None
        context = {"prompt_data": prompt, "pending_user": pending}
        request = types.SimpleNamespace(context={"flow_plan": types.SimpleNamespace(context=context)} if plan else {})
        ns = {"requests": fake, "request": request, "ak_logger": log}
        exec(self.source, ns)
        env = {}
        if token is not None:
            env["AVRANA_HOME_KEY_INTAKE_TOKEN"] = token
        if admin_key is not None:
            env["AVRANA_KOMGA_ADMIN_API_KEY"] = admin_key
        with mock.patch.dict(os.environ, env, clear=False), mock.patch("time.sleep") as sleep:
            for name, value in (("AVRANA_HOME_KEY_INTAKE_TOKEN", token), ("AVRANA_KOMGA_ADMIN_API_KEY", admin_key)):
                if value is None:
                    os.environ.pop(name, None)
            result = ns["policy"]()
        return result, fake, log, sleep

    # --- shape of the blueprint ---------------------------------------------------------------------------------------
    def test_is_additive_and_bound_to_the_write_stage_which_re_evaluates(self):
        self.assertIsInstance(self.expression, str)               # no !Format/!Env: nothing secret in the text
        write = self.entries[self.ids.index("recovery-binding-write")]
        self.assertEqual(write["identifiers"]["order"], 40)
        self.assertEqual(write["attrs"]["stage"], ("!KeyOf", "recovery-write"))
        self.assertIs(write["attrs"]["re_evaluate_policies"], True)
        bindings = [e for e in self.entries if e.get("model") == "authentik_policies.policybinding"]
        self.assertEqual([(e["identifiers"]["target"], e["identifiers"]["policy"], e["identifiers"]["order"])
                          for e in bindings],
                         [(("!KeyOf", "recovery-binding-write"), ("!KeyOf", "policy-komga-password-sync"), 0)])
        # The recovery flow's other bindings are untouched.
        others = [e for e in self.entries if e.get("model") == "authentik_flows.flowstagebinding"
                  and e["identifiers"]["order"] != 40]
        self.assertEqual([e["attrs"]["re_evaluate_policies"] for e in others], [False] * len(others))

    def test_the_account_password_flow_binds_the_same_policy_by_name(self):
        doc = load(ACCOUNT)
        entries = doc["entries"]
        ids = [e.get("id") for e in entries]
        write = entries[ids.index("binding-password-write")]
        self.assertEqual(write["identifiers"], {"target": ("!KeyOf", "flow-password"), "order": 30})
        self.assertIs(write["attrs"]["re_evaluate_policies"], True)
        bound = [e for e in entries if e.get("model") == "authentik_policies.policybinding"
                 and e["identifiers"]["target"] == ("!KeyOf", "binding-password-write")]
        self.assertEqual(len(bound), 1)
        self.assertEqual(bound[0]["identifiers"]["policy"],
                         ("!Find", ["authentik_policies_expression.expressionpolicy",
                                    ["name", "avrana-komga-password-sync"]]))

    def test_matches_the_enrollment_mint_on_the_key_name_addresses_and_timeouts(self):
        enrollment = load(ROOT / "services/authentik/blueprints/avrana-enrollment.yaml")["entries"]
        mint = next(e for e in enrollment if e.get("id") == "policy-komga-key-mint")["attrs"]["expression"]
        for line in ('komga_url = "http://10.0.0.218:25600"', 'home_url = "http://avrana-home-beta:8096"',
                     '"comment": "avrana-home"', 'keys_url = urljoin(komga_url, "/api/v2/users/me/api-keys")'):
            self.assertIn(line, mint)
            self.assertIn(line, self.expression)
        self.assertNotIn("timeout=10", self.expression)

    # --- behaviour ----------------------------------------------------------------------------------------------------
    def test_sets_the_komga_password_then_mints_as_the_member_and_puts_the_key_to_home(self):
        ok, fake, log, _ = self.run_policy()
        self.assertIs(ok, True)
        subject = hashlib.sha256(UID.encode()).hexdigest()
        self.assertEqual([(m, u) for m, u, _ in fake.calls],
                         [("GET", USERS_URL), ("PATCH", USERS_URL + "/U-1/password"),
                          ("GET", KEYS_URL), ("DELETE", KEYS_URL + "/K-old"), ("POST", KEYS_URL),
                          ("PUT", "http://avrana-home-beta:8096/internal/komga-key/" + subject)])
        for m, _u, kw in fake.calls[:2]:
            self.assertEqual(kw["headers"], {"X-API-Key": ADMIN_KEY})          # admin only for the password
            self.assertNotIn("auth", kw)
        self.assertEqual(fake.calls[1][2]["json"], {"password": PASSWORD})
        for m, _u, kw in fake.calls[2:5]:
            self.assertEqual(kw["auth"], (EMAIL, PASSWORD))                   # the key: as the member
            self.assertNotIn("headers", kw)
        put = fake.calls[5][2]
        self.assertEqual(put["json"], {"key": KEY, "key_id": "K-new", "source": "recovery"})
        self.assertEqual(put["headers"], {"Authorization": "Bearer " + TOKEN})
        self.assertNotIn("auth", put)
        self.assertEqual({kw["timeout"] for _m, _u, kw in fake.calls}, {5})
        self.assertEqual(log.lines[-1][1], ("komga-password-sync: key filed in Home",))

    def test_the_komga_account_is_matched_by_email_case_insensitively_and_created_when_missing(self):
        ok, fake, _log, _ = self.run_policy(FakeRequests(accounts=[{"id": "U-9", "email": "MEMBER@example.com"}]))
        self.assertIs(ok, True)
        self.assertEqual(fake.calls[1][:2], ("PATCH", USERS_URL + "/U-9/password"))
        ok, fake, log, _ = self.run_policy(FakeRequests(accounts=[{"id": "U-2", "email": "other@example.com"}]))
        self.assertIs(ok, True)
        self.assertEqual(fake.calls[1][:2], ("POST", USERS_URL))
        self.assertEqual(fake.calls[1][2]["json"], {"email": EMAIL, "password": PASSWORD,
                                                    "roles": ["FILE_DOWNLOAD", "PAGE_STREAMING"]})
        self.assertEqual(fake.calls[1][2]["headers"], {"X-API-Key": ADMIN_KEY})
        self.assertEqual([m for m, _u, _k in fake.calls], ["GET", "POST", "GET", "DELETE", "POST", "PUT"])
        self.assertIn(("komga-password-sync: Komga account created",), [l[1] for l in log.lines])

    def test_skips_quietly_when_it_has_nothing_to_do(self):
        for kw in ({"groups": ("avrana-videos",)}, {"plan": False}, {"user": False}, {"prompt": {}},
                   {"prompt": {"password": ""}}, {"uid": None}, {"email": ""}, {"broken_groups": True},
                   {"admin_key": None}, {"admin_key": "  "}):
            with self.subTest(kw=kw):
                ok, fake, _log, _ = self.run_policy(**kw)
                self.assertIs(ok, True)
                self.assertEqual(fake.calls, [])

    def test_without_the_intake_token_the_password_is_synced_but_no_key_is_made(self):
        ok, fake, log, _ = self.run_policy(token=None)
        self.assertIs(ok, True)
        self.assertEqual([m for m, _u, _k in fake.calls], ["GET", "PATCH"])
        self.assertEqual(log.lines[-1][1], ("komga-password-sync: AVRANA_HOME_KEY_INTAKE_TOKEN not set, key not renewed",))

    def test_komga_refusing_the_admin_calls_stops_before_any_member_call_and_never_fails(self):
        for fake in (FakeRequests(users_status=401), FakeRequests(patch=403),
                     FakeRequests(accounts=[], create=400), FakeRequests(raises=ConnectionError("synthetic"))):
            with self.subTest(fake=[fake.users_status, fake.patch_status, fake.create_status, fake.raises]):
                ok, fake, log, _ = self.run_policy(fake)
                self.assertIs(ok, True)
                self.assertNotIn("PUT", [m for m, _u, _k in fake.calls])
                self.assertTrue(all("auth" not in kw for _m, _u, kw in fake.calls))
                self.assertEqual(log.lines[-1][0], "warning")

    def test_a_refused_member_sign_in_is_retried_twice_then_given_up_without_failing(self):
        ok, fake, _log, sleep = self.run_policy(FakeRequests(sign_in=(401, 401, 401)))
        self.assertIs(ok, True)
        self.assertEqual([m for m, _u, _k in fake.calls], ["GET", "PATCH", "GET", "GET", "GET"])
        self.assertEqual(sleep.call_count, 2)
        ok, fake, _log, _ = self.run_policy(FakeRequests(sign_in=(401, 200)))
        self.assertEqual([m for m, _u, _k in fake.calls], ["GET", "PATCH", "GET", "GET", "DELETE", "POST", "PUT"])

    def test_home_refusing_deletes_the_new_key_and_never_fails(self):
        for put in (400, 401, 403, 503):
            with self.subTest(put=put):
                ok, fake, _log, _ = self.run_policy(FakeRequests(put=put))
                self.assertIs(ok, True)
                self.assertEqual(fake.calls[-1][:2], ("DELETE", KEYS_URL + "/K-new"))

    def test_a_lost_answer_from_home_leaves_the_key_in_komga_and_logs_unknown(self):
        for exc in (TimeoutError("synthetic read timeout"), ConnectionError("synthetic reset")):
            with self.subTest(exc=type(exc).__name__):
                ok, fake, log, _ = self.run_policy(FakeRequests(put_raises=exc))
                self.assertIs(ok, True)
                self.assertEqual(fake.calls[-1][0], "PUT")
                self.assertEqual(log.lines[-1][2], {"state": "unknown", "error": type(exc).__name__})

    def test_komga_refusing_the_key_never_fails_the_reset(self):
        ok, fake, _log, _ = self.run_policy(FakeRequests(post=500))
        self.assertIs(ok, True)
        self.assertNotIn("PUT", [m for m, _u, _k in fake.calls])

    def test_no_secret_or_identity_in_any_log_line(self):
        for fake in (FakeRequests(), FakeRequests(put=503), FakeRequests(sign_in=(401,)), FakeRequests(patch=500),
                     FakeRequests(accounts=[]), FakeRequests(raises=RuntimeError(PASSWORD)),
                     FakeRequests(put_raises=RuntimeError(KEY))):
            _ok, _fake, log, _ = self.run_policy(fake)
            text = repr(log.lines)
            for secret in (PASSWORD, KEY, TOKEN, ADMIN_KEY, EMAIL, EMAIL.lower(), UID):
                self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
