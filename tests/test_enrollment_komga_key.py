"""S-01: the enrollment stage `avrana-komga-key-mint` (avrana-enrollment.yaml) mints the new member's own Komga key while
the password is still in the flow and hands it to Home's key intake, and never fails enrollment.

Runs the blueprint's expression with stand-ins for Authentik's `request`, `requests` and `ak_logger`. Synthetic
accounts only; no Authentik, no Komga, no Home, no network. The policy's presence and binding inside a REAL
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
BLUEPRINT = ROOT / "services/authentik/blueprints/avrana-enrollment.yaml"
TOKEN = "synthetic-intake-token-" + "x" * 20
PASSWORD = "test-synthetic-Passw0rd-new-member"
EMAIL = "new.member@example.com"
UID = "synthetic-hashed-user-id"
KEY = "0123456789abcdef0123456789abcdef"


def load():
    class Loader(yaml.SafeLoader):
        pass
    for tag in ("!KeyOf", "!Env", "!Format", "!Find"):
        Loader.add_constructor(tag, lambda ld, node, tag=tag: ld.construct_sequence(node)
                               if isinstance(node, yaml.SequenceNode) else (tag, ld.construct_scalar(node)))
    return yaml.load(BLUEPRINT.read_text(encoding="utf-8"), Loader=Loader)


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


class FakeRequests:
    """Komga at 10.0.0.218:25600 (the member's own key routes) and Home's intake."""

    def __init__(self, sign_in=(200,), post=200, put=204, raises=None):
        self.calls, self.sign_in, self.post_status, self.put_status, self.raises = [], list(sign_in), post, put, raises
        self.keys = [{"id": "K-old", "comment": "avrana-home"}, {"id": "K-own", "comment": "phone"}]

    def _record(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if self.raises:
            raise self.raises

    def get(self, url, **kw):
        self._record("GET", url, **kw)
        status = self.sign_in.pop(0) if len(self.sign_in) > 1 else self.sign_in[0]
        return Resp(status, list(self.keys) if status == 200 else None)

    def delete(self, url, **kw):
        self._record("DELETE", url, **kw)
        return Resp(204)

    def post(self, url, **kw):
        self._record("POST", url, **kw)
        return Resp(self.post_status, {"id": "K-new", "key": KEY, "comment": "avrana-home"})

    def put(self, url, **kw):
        self._record("PUT", url, **kw)
        return Resp(self.put_status)


class Logger:
    def __init__(self):
        self.lines = []

    def __getattr__(self, level):
        return lambda *a, **k: self.lines.append((level, a, k))


@unittest.skipIf(yaml is None, "PyYAML not installed")
class KomgaKeyMint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load()
        cls.entries = cls.doc["entries"]
        cls.ids = [e.get("id") for e in cls.entries]
        policy = cls.entries[cls.ids.index("policy-komga-key-mint")]
        cls.expression = policy["attrs"]["expression"]
        cls.source = "def policy():\n" + textwrap.indent(cls.expression, "    ")

    def run_policy(self, fake=None, groups=("avrana-comics",), token=TOKEN, prompt=None, uid=UID, plan=True):
        fake = fake or FakeRequests()
        log = Logger()
        prompt = {"email": EMAIL, "password": PASSWORD} if prompt is None else prompt
        context = {"groups": [types.SimpleNamespace(name=g) for g in groups], "prompt_data": prompt,
                   "pending_user": types.SimpleNamespace(uid=uid) if uid else None}
        request = types.SimpleNamespace(context={"flow_plan": types.SimpleNamespace(context=context)} if plan else {})
        ns = {"requests": fake, "request": request, "ak_logger": log}
        exec(self.source, ns)
        env = {"AVRANA_HOME_KEY_INTAKE_TOKEN": token} if token is not None else {}
        with mock.patch.dict(os.environ, env, clear=False), mock.patch("time.sleep") as sleep:
            if token is None:
                os.environ.pop("AVRANA_HOME_KEY_INTAKE_TOKEN", None)
            result = ns["policy"]()
        return result, fake, log, sleep

    def test_is_additive_bound_after_komga_create_and_reads_no_secret_at_apply_time(self):
        self.assertLess(self.ids.index("policy-komga-create"), self.ids.index("policy-komga-key-mint"))
        self.assertIsInstance(self.expression, str)               # no !Format/!Env: nothing secret in the text
        bindings = [e for e in self.entries if e.get("model") == "authentik_policies.policybinding"
                    and e["identifiers"]["target"] == ("!KeyOf", "binding-user-login")]
        orders = {e["identifiers"]["policy"][1]: e["identifiers"]["order"] for e in bindings}
        self.assertEqual(orders, {"policy-jellyfin-create": 0, "policy-komga-create": 1, "policy-komga-key-mint": 2})

    def test_mints_as_the_member_and_puts_the_key_to_home(self):
        ok, fake, log, _ = self.run_policy()
        self.assertIs(ok, True)
        methods = [(m, u) for m, u, _ in fake.calls]
        keys_url = "http://10.0.0.218:25600/api/v2/users/me/api-keys"
        subject = hashlib.sha256(UID.encode()).hexdigest()
        self.assertEqual(methods, [("GET", keys_url), ("DELETE", keys_url + "/K-old"), ("POST", keys_url),
                                   ("PUT", "http://avrana-home-beta:8096/internal/komga-key/" + subject)])
        for m, _u, kw in fake.calls[:3]:
            self.assertEqual(kw["auth"], (EMAIL, PASSWORD))         # as the member: no admin credential anywhere
        put = fake.calls[3][2]
        self.assertEqual(put["json"], {"key": KEY, "key_id": "K-new", "source": "enrollment"})
        self.assertEqual(put["headers"], {"Authorization": "Bearer " + TOKEN})
        self.assertNotIn("auth", put)
        self.assertEqual(log.lines[-1][1], ("komga-key-mint: key filed in Home",))

    def test_skips_quietly_without_comics_token_flow_or_data(self):
        for kw in ({"groups": ("avrana-videos",)}, {"token": None}, {"token": "  "}, {"plan": False},
                   {"prompt": {"email": EMAIL}}, {"uid": None}):
            with self.subTest(kw=kw):
                ok, fake, _log, _ = self.run_policy(**kw)
                self.assertIs(ok, True)
                self.assertEqual(fake.calls, [])

    def test_a_refused_sign_in_is_retried_twice_then_given_up_without_failing(self):
        ok, fake, log, sleep = self.run_policy(FakeRequests(sign_in=(401, 401, 401)))
        self.assertIs(ok, True)
        self.assertEqual([m for m, _u, _k in fake.calls], ["GET", "GET", "GET"])
        self.assertEqual(sleep.call_count, 2)
        ok, fake, _log, _ = self.run_policy(FakeRequests(sign_in=(401, 200)))
        self.assertEqual([m for m, _u, _k in fake.calls], ["GET", "GET", "DELETE", "POST", "PUT"])

    def test_home_refusing_deletes_the_new_key_and_never_fails(self):
        for put in (401, 403, 503):
            with self.subTest(put=put):
                ok, fake, _log, _ = self.run_policy(FakeRequests(put=put))
                self.assertIs(ok, True)
                self.assertEqual(fake.calls[-1][:2],
                                 ("DELETE", "http://10.0.0.218:25600/api/v2/users/me/api-keys/K-new"))

    def test_komga_refusing_the_key_or_anything_raising_never_fails_enrollment(self):
        ok, fake, _log, _ = self.run_policy(FakeRequests(post=500))
        self.assertIs(ok, True)
        self.assertNotIn("PUT", [m for m, _u, _k in fake.calls])
        ok, fake, log, _ = self.run_policy(FakeRequests(raises=ConnectionError("synthetic")))
        self.assertIs(ok, True)
        self.assertEqual(log.lines[-1][2], {"error": "ConnectionError"})

    def test_no_secret_or_email_in_any_log_line(self):
        for fake in (FakeRequests(), FakeRequests(put=503), FakeRequests(sign_in=(401,)),
                     FakeRequests(raises=RuntimeError(PASSWORD))):
            _ok, _fake, log, _ = self.run_policy(fake)
            text = repr(log.lines)
            for secret in (PASSWORD, KEY, TOKEN, EMAIL, UID):
                self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
