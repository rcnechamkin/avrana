"""Account creation (provision.py, docs/design/ACCOUNT-PROVISIONING.md). Offline, synthetic data only."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import io
import threading
import unittest
import urllib.error
import urllib.request

from avrana_home.app.settings import Settings, SettingsError
from avrana_home.contract import SectionResult, SectionState, Service
from avrana_home.principal import principal_from_headers
from avrana_home.provision import (LDAP_PROVIDER, AudiobookshelfCreator, JellyfinCreator, ProvisionFailed,
                                   Provisioner, http_sender)

JF_ID = "a" * 32
EMAIL = "member-a@example.test"


def member(username="member-a", groups=("avrana-videos", "avrana-audiobooks"), email=EMAIL):
    headers = {"X-authentik-username": username, "X-authentik-groups": "|".join(groups)}
    if email:
        headers["X-authentik-email"] = email
    return principal_from_headers(headers)


def unmapped(service, reason="unmapped", state=SectionState.NOT_LINKED):
    return SectionResult(service, "continue", state, reason=reason)


class FakeJellyfinAdmin:
    """Records every call. `users` is the upstream user list; the policy step can be made to fail."""

    def __init__(self, users=()):
        self.users = [dict(u) for u in users]
        self.calls = []
        self.policy_sticks = True

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        if (method, path) == ("GET", "/Users"):
            return self.users
        if (method, path) == ("POST", "/Users/New"):
            user = {"Name": body["Name"], "Id": JF_ID,
                    "Policy": {"IsAdministrator": False, "IsDisabled": False, "EnableAllFolders": True,
                               "AuthenticationProviderId": "Jellyfin.Server.Implementations.Users."
                                                           "DefaultAuthenticationProvider",
                               "PasswordResetProviderId": "Jellyfin.Server.Implementations.Users."
                                                          "DefaultPasswordResetProvider",
                               "SyncPlayAccess": "CreateAndJoinGroups"}}
            self.users.append(user)
            return user
        if (method, path) == ("POST", f"/Users/{JF_ID}/Policy"):
            if self.policy_sticks:
                self.users[-1]["Policy"] = body
            return None
        if (method, path) == ("GET", f"/Users/{JF_ID}"):
            return self.users[-1]
        raise AssertionError(f"unexpected call {method} {path}")


class FakeAbsAdmin:
    def __init__(self, users=()):
        self.users = [dict(u) for u in users]
        self.calls = []

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        if (method, path) == ("GET", "/api/users"):
            return {"users": self.users}
        if (method, path) == ("POST", "/api/users"):
            user = {"id": "usr_synthetic", "username": body["username"], "email": body["email"],
                    "type": body["type"]}
            self.users.append(user)
            return {"user": user}
        raise AssertionError(f"unexpected call {method} {path}")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def provisioner(creators, cap=10, clock=None):
    logs = []
    p = Provisioner(creators, cap, clock=clock or Clock(), log=lambda **f: logs.append(f))
    return p, logs


class JellyfinCreatorTests(unittest.TestCase):
    def test_creates_an_ldap_account_like_the_plugin_does(self):
        jf = FakeJellyfinAdmin([{"Name": "someone-else", "Id": "b" * 32}])
        JellyfinCreator(jf).create("member-a", EMAIL)
        methods = [(m, p) for m, p, _ in jf.calls]
        self.assertEqual(methods, [("GET", "/Users"), ("POST", "/Users/New"), ("POST", f"/Users/{JF_ID}/Policy"),
                                   ("GET", f"/Users/{JF_ID}")])
        new = jf.calls[1][2]
        self.assertEqual(new["Name"], "member-a")
        self.assertGreaterEqual(len(new["Password"]), 40)      # random, locks the account until the policy lands
        policy = jf.calls[2][2]
        self.assertEqual(policy["AuthenticationProviderId"], LDAP_PROVIDER)
        self.assertEqual(policy["PasswordResetProviderId"], LDAP_PROVIDER)
        self.assertIs(policy["IsAdministrator"], False)
        self.assertIs(policy["IsDisabled"], False)
        self.assertIs(policy["EnableAllFolders"], True)
        self.assertIs(policy["EnableContentDeletion"], False)
        self.assertIs(policy["EnableRemoteControlOfOtherUsers"], False)
        self.assertEqual(policy["SyncPlayAccess"], "CreateAndJoinGroups")   # the rest is the server's default

    def test_each_account_gets_its_own_password(self):
        a, b = FakeJellyfinAdmin(), FakeJellyfinAdmin()
        JellyfinCreator(a).create("member-a", None)
        JellyfinCreator(b).create("member-b", None)
        self.assertNotEqual(a.calls[1][2]["Password"], b.calls[1][2]["Password"])

    def test_a_name_in_any_letter_case_is_never_created_again(self):
        for existing in ("member-a", "Member-A", " member-a"):
            jf = FakeJellyfinAdmin([{"Name": existing, "Id": "b" * 32}])
            with self.assertRaises(ProvisionFailed) as cm:
                JellyfinCreator(jf).create("member-a", None)
            self.assertEqual(cm.exception.reason, "exists")
            self.assertEqual([m for m, _p, _b in jf.calls], ["GET"])

    def test_a_policy_that_did_not_stick_is_a_failure(self):
        jf = FakeJellyfinAdmin()
        jf.policy_sticks = False
        with self.assertRaises(ProvisionFailed) as cm:
            JellyfinCreator(jf).create("member-a", None)
        self.assertEqual(cm.exception.reason, "policy_unverified")

    def test_an_unexpected_create_answer_is_a_failure(self):
        def send(method, path, body):
            return [] if method == "GET" else {"Name": "other", "Id": JF_ID, "Policy": {}}
        with self.assertRaises(ProvisionFailed) as cm:
            JellyfinCreator(send).create("member-a", None)
        self.assertEqual(cm.exception.reason, "created_unverified")


class AudiobookshelfCreatorTests(unittest.TestCase):
    def test_creates_a_plain_user_with_the_members_email(self):
        abs_ = FakeAbsAdmin([{"username": "someone-else", "email": "else@example.test"}])
        AudiobookshelfCreator(abs_).create("member-a", EMAIL)
        method, path, body = abs_.calls[1]
        self.assertEqual((method, path), ("POST", "/api/users"))
        self.assertEqual({k: body[k] for k in ("username", "email", "type", "isActive")},
                         {"username": "member-a", "email": EMAIL, "type": "user", "isActive": True})
        self.assertNotIn("permissions", body)                   # the server's default for a new user
        self.assertGreaterEqual(len(body["password"]), 40)

    def test_refusals(self):
        cases = ((None, [], "no_email"), ("not-an-address", [], "no_email"),
                 (EMAIL, [{"username": "MEMBER-A", "email": "x@example.test"}], "exists"),
                 (EMAIL, [{"username": "other", "email": "Member-A@Example.test"}], "email_in_use"))
        for email, users, reason in cases:
            abs_ = FakeAbsAdmin(users)
            with self.assertRaises(ProvisionFailed) as cm:
                AudiobookshelfCreator(abs_).create("member-a", email)
            self.assertEqual(cm.exception.reason, reason)
            self.assertFalse(any(m == "POST" for m, _p, _b in abs_.calls))


class ProvisionerTests(unittest.TestCase):
    def test_only_no_account_with_that_name_triggers(self):
        jf = FakeJellyfinAdmin()
        p, _logs = provisioner({Service.JELLYFIN: JellyfinCreator(jf)})
        quiet = [unmapped(Service.JELLYFIN, "case_or_unicode_mismatch"), unmapped(Service.JELLYFIN, "ambiguous"),
                 unmapped(Service.JELLYFIN, "disabled"), unmapped(Service.JELLYFIN, "upstream_user_not_found"),
                 unmapped(Service.JELLYFIN, "unmapped", SectionState.UNAVAILABLE),
                 unmapped(Service.AUDIOBOOKSHELF), unmapped(Service.KOMGA)]
        self.assertEqual(p.provision(member(), quiet), ())
        self.assertEqual(jf.calls, [])
        self.assertEqual(p.provision(member(), [unmapped(Service.JELLYFIN)]), (Service.JELLYFIN,))

    def test_only_jellyfin_audiobookshelf_and_komga(self):
        with self.assertRaises(ValueError):
            Provisioner({Service.CALIBRE_WEB: object()})

    def test_needs_the_librarys_group(self):
        jf = FakeJellyfinAdmin()
        p, logs = provisioner({Service.JELLYFIN: JellyfinCreator(jf)})
        self.assertEqual(p.provision(member(groups=("avrana-audiobooks",)), [unmapped(Service.JELLYFIN)]), ())
        self.assertEqual(jf.calls, [])
        self.assertEqual(logs, [{"service": "jellyfin", "state": "refused", "reason": "no_group"}])

    def test_one_attempt_per_member_and_library_per_hour(self):
        clock = Clock()
        calls = []

        class Failing:
            def create(self, username, email):
                calls.append(username)
                raise ProvisionFailed("http_500")
        p, logs = provisioner({Service.JELLYFIN: Failing()}, clock=clock)
        for _ in range(3):
            p.provision(member(), [unmapped(Service.JELLYFIN)])
        self.assertEqual(calls, ["member-a"])
        self.assertEqual(logs, [{"service": "jellyfin", "state": "failed", "reason": "http_500"}])
        clock.t += 3600
        p.provision(member(), [unmapped(Service.JELLYFIN)])
        self.assertEqual(len(calls), 2)

    def test_the_global_cap_counts_attempts(self):
        clock = Clock()
        jf = FakeJellyfinAdmin()
        p, logs = provisioner({Service.JELLYFIN: JellyfinCreator(jf)}, cap=2, clock=clock)
        made = [p.provision(member(f"member-{i}"), [unmapped(Service.JELLYFIN)]) for i in range(3)]
        self.assertEqual(made, [(Service.JELLYFIN,), (Service.JELLYFIN,), ()])
        self.assertEqual(logs[-1], {"service": "jellyfin", "state": "refused", "reason": "cap"})
        clock.t += 3600
        self.assertEqual(p.provision(member("member-9"), [unmapped(Service.JELLYFIN)]), (Service.JELLYFIN,))

    def test_two_tabs_at_once_create_one_account(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        class Slow:
            def create(self, username, email):
                calls.append(username)
                started.set()
                release.wait(5)
        p, _logs = provisioner({Service.JELLYFIN: Slow()})
        first = threading.Thread(target=p.provision, args=(member(), [unmapped(Service.JELLYFIN)]))
        first.start()
        self.assertTrue(started.wait(5))
        self.assertEqual(p.provision(member(), [unmapped(Service.JELLYFIN)]), ())
        release.set()
        first.join(5)
        self.assertEqual(calls, ["member-a"])

    def test_unusable_usernames_are_refused(self):
        jf = FakeJellyfinAdmin()
        p, logs = provisioner({Service.JELLYFIN: JellyfinCreator(jf)})
        self.assertEqual(p.provision(member("a/b"), [unmapped(Service.JELLYFIN)]), ())
        self.assertEqual(logs[-1]["reason"], "bad_username")
        self.assertEqual(jf.calls, [])

    def test_a_crash_in_a_creator_never_escapes(self):
        class Broken:
            def create(self, username, email):
                raise KeyError("synthetic")
        p, logs = provisioner({Service.JELLYFIN: Broken()})
        self.assertEqual(p.provision(member(), [unmapped(Service.JELLYFIN)]), ())
        self.assertEqual(logs[-1], {"service": "jellyfin", "state": "failed", "reason": "KeyError"})

    def test_logs_carry_no_identity_or_secret(self):
        jf, abs_ = FakeJellyfinAdmin(), FakeAbsAdmin()
        p, logs = provisioner({Service.JELLYFIN: JellyfinCreator(jf), Service.AUDIOBOOKSHELF: AudiobookshelfCreator(abs_)})
        made = p.provision(member(), [unmapped(Service.JELLYFIN), unmapped(Service.AUDIOBOOKSHELF)])
        self.assertEqual(made, (Service.JELLYFIN, Service.AUDIOBOOKSHELF))
        secrets_seen = [jf.calls[1][2]["Password"], abs_.calls[1][2]["password"], "member-a", EMAIL, JF_ID]
        text = repr(logs)
        for value in secrets_seen:
            self.assertNotIn(value, text)
        self.assertEqual([l["state"] for l in logs], ["provisioned", "provisioned"])


class _Opener:
    def __init__(self, status=200, body=b"{}"):
        self.status, self.body, self.requests = status, body, []

    def open(self, req, timeout):
        self.requests.append(req)
        if self.status >= 400:
            raise urllib.error.HTTPError(req.full_url, self.status, "synthetic", {}, io.BytesIO(b"upstream text"))
        return io.BytesIO(self.body)


class HttpSenderTests(unittest.TestCase):
    def test_sends_json_with_the_credential_header(self):
        opener = _Opener(body=b'{"ok": true}')
        send = http_sender("http://jellyfin.test", {"Authorization": "synthetic"}, opener=opener)
        self.assertEqual(send("POST", "/Users/New", {"Name": "member-a"}), {"ok": True})
        req = opener.requests[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, "http://jellyfin.test/Users/New")
        self.assertEqual(req.data, b'{"Name": "member-a"}')
        self.assertEqual(req.get_header("Content-type"), "application/json")

    def test_failures_are_fixed_reasons(self):
        send = http_sender("http://jellyfin.test", {}, opener=_Opener(status=403))
        with self.assertRaises(ProvisionFailed) as cm:
            send("GET", "/Users", None)
        self.assertEqual(cm.exception.reason, "http_403")
        with self.assertRaises(ProvisionFailed) as cm:
            http_sender("http://jellyfin.test", {}, opener=_Opener(body=b"<html>"))("GET", "/Users", None)
        self.assertEqual(cm.exception.reason, "malformed")

    def test_the_default_opener_never_uses_a_proxy_or_follows_a_redirect(self):
        built = []
        real = urllib.request.build_opener

        def spy(*handlers):
            built.extend(handlers)
            return real(*handlers)
        urllib.request.build_opener = spy
        try:
            http_sender("http://jellyfin.test", {})
        finally:
            urllib.request.build_opener = real
        proxy = [h for h in built if isinstance(h, urllib.request.ProxyHandler)]
        self.assertEqual(len(proxy), 1)
        self.assertEqual(proxy[0].proxies, {})
        self.assertTrue(any(getattr(h, "__name__", "") == "_NoRedirect" for h in built))


REAL = {"HOME_SECTIONS": "on", "HOME_UPSTREAM_MODE": "real", "JELLYFIN_BASE_URL": "https://jellyfin.test",
        "JELLYFIN_API_KEY": "k" * 32, "AUDIOBOOKSHELF_BASE_URL": "https://abs.test", "AUDIOBOOKSHELF_TOKEN": "t" * 32,
        "HOME_IDENTITY_MODE": "jwt_required", "HOME_JWT_ISSUER": "https://auth.test/", "HOME_JWT_AUDIENCE": "home",
        "HOME_JWT_SECRET": "s" * 64, "HOME_ALLOWED_USERS": "member-a", "HOME_GATES_VERIFIED": "yes"}


class SettingsTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(Settings.from_mapping(REAL).provision_accounts, ())
        self.assertEqual(Settings.from_mapping(dict(REAL, HOME_PROVISION_ACCOUNTS="off")).provision_accounts, ())

    def test_on_per_library(self):
        s = Settings.from_mapping(dict(REAL, HOME_PROVISION_ACCOUNTS="jellyfin"))
        self.assertEqual(s.provision_accounts, ("jellyfin",))
        self.assertEqual(s.provision_cap_per_hour, 10)
        s = Settings.from_mapping(dict(REAL, HOME_PROVISION_ACCOUNTS="audiobookshelf, jellyfin",
                                       HOME_PROVISION_CAP_PER_HOUR="3"))
        self.assertEqual((s.provision_accounts, s.provision_cap_per_hour), (("audiobookshelf", "jellyfin"), 3))

    def test_refused_without_its_preconditions(self):
        bad = [dict(REAL, HOME_PROVISION_ACCOUNTS="komga"), dict(REAL, HOME_PROVISION_ACCOUNTS=""),
               dict(REAL, HOME_PROVISION_ACCOUNTS="jellyfin", HOME_PROVISION_CAP_PER_HOUR="500")]
        no_allow = dict(REAL, HOME_PROVISION_ACCOUNTS="jellyfin")
        del no_allow["HOME_ALLOWED_USERS"]
        bad.append(no_allow)
        mock = {"HOME_SECTIONS": "on", "HOME_PROVISION_ACCOUNTS": "jellyfin"}
        bad.append(mock)
        for env in bad:
            with self.assertRaises(SettingsError):
                Settings.from_mapping(env)


if __name__ == "__main__":
    unittest.main()
