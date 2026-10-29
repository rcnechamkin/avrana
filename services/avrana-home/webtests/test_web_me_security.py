"""Tier B: Me -> Account & Security (Media 2.0 supplement 2026-10-27; owner decision 2026-10-28; security.py,
accountreader.py). SYNTHETIC data only.

What this slice adds and must never weaken:
  * Every /me/security path exists only with the shell and a verified member; otherwise it is the standard 404, the
    same bytes as an unknown route (portal parity).
  * Members are never sent to the sign-in service's own pages (owner, 2026-10-28). A hand-off exists only for an
    action whose single-purpose flow the owner configured, is a 303 to that FIXED flow address, and is otherwise the
    standard 404. No page links to the service's user interface, and no page names it.
  * "Added" / "changed" is said only on fresh evidence from the scoped reader (a method created minutes ago, a password
    changed minutes ago); coming back alone says it couldn't confirm.
  * The reader shows only the member's own methods and sessions, and "Sign out" of a session works only for one of
    theirs, through every form lock.
  * Passkey and authenticator are offered with equal weight; no "recommended" badge; no flow slug or host in the JSON.
"""
import json
import re
import unittest
from datetime import datetime, timedelta, timezone

from avrana_home import accountreader
from avrana_home.accountreader import AccountReader
from avrana_home.app import security
from avrana_home.app.middleware import CSP
from avrana_home.app.settings import Settings, SettingsError
from avrana_home.resilience import TransportResponse, UpstreamTimeout
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

NAME = "X-authentik-name"
EMAIL = "X-authentik-email"
VIDEO = [(USER, "member-a"), (NAME, "Member A"), (EMAIL, "member.a@example.test"),
         (GROUPS, "avrana-users|avrana-videos")]
BOOKS = [(USER, "member-k"), (GROUPS, "avrana-users|avrana-books")]
OTHER = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos")]
PAGES = ("/me/security", "/me/security/password", "/me/security/protection", "/me/security/protection/passkey",
         "/me/security/protection/authenticator", "/me/security/recovery", "/me/security/recovery/codes",
         "/me/security/sessions") + tuple(security.DONE_PREFIX + a for a in security.ACTIONS)
GO = tuple(security.GO_PREFIX + a for a in security.ACTIONS)
FLOWS = (("password", "avrana-password"), ("passkey", "avrana-passkey"), ("totp", "avrana-authenticator"),
         ("recovery_codes", "avrana-backup-codes"))
S1, S2, S3 = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
              "33333333-3333-4333-8333-333333333333")


def iso(delta_minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=delta_minutes)).isoformat()


class FakeAuth:
    """The four allow-listed requests, for two synthetic members. Records every call."""

    def __init__(self):
        self.calls = []
        self.fail = None
        self.users = [{"pk": 7, "username": "member-a", "is_active": True, "password_change_date": iso(60 * 24 * 30)},
                      {"pk": 8, "username": "member-b", "is_active": True}]
        self.devices = {7: [{"name": "iPhone", "meta_model_name": "authentik_stages_authenticator_webauthn.webauthndevice",
                             "created": iso(60 * 24 * 3), "last_used": iso(60), "confirmed": True}],
                        8: []}
        self.sessions = {"member-a": [{"uuid": S1, "last_used": iso(5), "geo_ip": {"city": "Leeds", "country": "GB"},
                                       "user_agent": {"user_agent": {"family": "Safari"}, "os": {"family": "iOS"},
                                                      "device": {"family": "iPhone"}}},
                                      {"uuid": S2, "last_used": iso(60 * 24 * 2), "geo_ip": None,
                                       "user_agent": {"user_agent": {"family": "Firefox"}, "os": {"family": "Windows"},
                                                      "device": {"family": "Other"}}}],
                         "member-b": [{"uuid": S3, "last_used": iso(1)}]}

    def request(self, method, path, query, timeout, max_bytes, **kw):
        self.calls.append((method, path, dict(query or {})))
        if self.fail is not None:
            raise self.fail
        if path == accountreader.USERS:
            rows = [u for u in self.users if u["username"] == query["username"]]
            return TransportResponse(200, json.dumps({"results": rows}).encode(), "application/json")
        if path == accountreader.DEVICES:
            return TransportResponse(200, json.dumps({"results": self.devices[int(query["user"])]}).encode(), "")
        if path == accountreader.SESSIONS and method == "GET":
            return TransportResponse(200, json.dumps({"results": self.sessions[query["user__username"]]}).encode(), "")
        if method == "DELETE":
            uuid = path.rsplit("/", 2)[-2]
            for rows in self.sessions.values():
                rows[:] = [r for r in rows if r["uuid"] != uuid]
            return TransportResponse(204, b"", "")
        raise AssertionError(path)


def main_of(text):
    return re.split(r"<main(?:\s[^>]*)?>", text)[1].split("</main>")[0]


def hrefs(fragment):
    return re.findall(r'<a class="krow-a" href="([^"]*)"', fragment)


def client_with(reader=None, **overrides):
    data = {"member-a": [("a" * 32, "Synthetic Security Film", 0.5)]}
    return make_client(make_settings(home_sections=True, **overrides), adapters=[StubAdapter(data)],
                       account_reader=reader)


def form_post(client, path, body, headers):
    h = dict(headers)
    h.update({"Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": "same-origin"})
    return client.post(path, content=body, headers=h)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.on = client_with()
        cls.off = make_client(make_settings(home_sections=False))
        cls.on.__enter__()
        cls.off.__enter__()
        cls.origin = security.auth_origin(cls.on.fastapi_app.state.catalogue.account_url)

    @classmethod
    def tearDownClass(cls):
        cls.on.__exit__(None, None, None)
        cls.off.__exit__(None, None, None)

    def page(self, path, headers=VIDEO, client=None):
        r = (client or self.on).get(path, headers=headers)
        self.assertEqual(200, r.status_code, path)
        return r.text


class Gating(Base):
    def test_only_with_the_shell_and_a_member_otherwise_exactly_an_unknown_route(self):
        for client, headers in ((self.off, VIDEO), (self.on, []), (self.on, [(GROUPS, "avrana-videos")])):
            nope = client.get("/nope", headers=headers)
            for path in PAGES + GO + (security.JSON_ROUTE,):
                r = client.get(path, headers=headers)
                self.assertEqual((404, nope.text), (r.status_code, r.text), (path, headers))

    def test_unknown_paths_actions_and_unconfigured_flows_are_the_standard_404(self):
        nope = self.on.get("/nope", headers=VIDEO)
        for path in ("/me/securityx", "/me/security/admin", "/me/security/go/", "/me/security/go/delete",
                     "/me/security/go/PASSWORD", "/me/security/go/password/extra", "/me/security/go/..%2fadmin",
                     "/me/security/go/sessions", "/me/security/go/account", "/me/security/back",
                     "/me/security/done/sessions", "/me/security/protection/both", "/me/security.json/x") + GO:
            r = self.on.get(path, headers=VIDEO)
            self.assertEqual((404, nope.text), (r.status_code, r.text), path)


class NeverTheServiceItself(Base):
    """The owner's rule: no link to the sign-in service's own pages, and never its name, on any member page."""

    def test_no_page_links_off_avrana_or_names_the_service(self):
        with client_with(AccountReader(FakeAuth()), security_flows=FLOWS) as c:
            for path in PAGES + ("/me", "/account"):
                main = main_of(self.page(path, client=c))
                for word in ("authentik", "Authentik", "/if/user", "MFA Devices", self.origin):
                    self.assertNotIn(word, main, (path, word))
                for href in re.findall(r'href="([^"]*)"', main):
                    self.assertTrue(href.startswith("/"), (path, href))      # every link stays on Avrana

    def test_handoffs_go_only_to_the_configured_flow(self):
        with client_with(security_flows=(("passkey", "avrana-passkey"),)) as c:
            r = c.get("/me/security/go/passkey?next=https://evil.example", headers=VIDEO)
            self.assertEqual((303, self.origin + "/if/flow/avrana-passkey/"), (r.status_code, r.headers["location"]))
            self.assertEqual(404, c.get("/me/security/go/totp", headers=VIDEO).status_code)
            body = json.loads(c.get(security.JSON_ROUTE, headers=VIDEO).text)
            self.assertTrue(body["capabilities"]["enroll_passkey"]["available"])
            self.assertEqual("not_configured", body["capabilities"]["enroll_totp"]["reason"])
            self.assertNotIn("avrana-passkey", json.dumps(body))
            self.assertNotIn(self.origin, json.dumps(body))

    def test_unconfigured_actions_say_ask_and_offer_no_continue(self):
        for path in ("/me/security/password", "/me/security/protection/passkey",
                     "/me/security/protection/authenticator", "/me/security/recovery/codes"):
            main = main_of(self.page(path))
            self.assertIn("Ask the person who invited you", main, path)
            self.assertNotIn("/me/security/go/", main, path)

    def test_configured_actions_offer_continue_through_go(self):
        with client_with(security_flows=FLOWS) as c:
            for path, action in (("/me/security/password", "password"), ("/me/security/protection/passkey", "passkey"),
                                 ("/me/security/protection/authenticator", "totp"),
                                 ("/me/security/recovery/codes", "recovery_codes")):
                self.assertEqual([security.GO_PREFIX + action], hrefs(main_of(self.page(path, client=c))), path)


class Pages(Base):
    def test_hub_lists_the_supplement_rows_and_one_sign_out(self):
        main = main_of(self.page("/me/security"))
        self.assertIn('<h2 class="topic">Account &amp; Security</h2>', main)
        self.assertEqual(["/me/security/password", "/me/security/protection", "/me/security/recovery",
                          "/me/security/sessions", "/signout"], hrefs(main))
        for word in ("everywhere", "score", "Recommended", "recommended"):
            self.assertNotIn(word, main, word)

    def test_passkey_and_authenticator_have_equal_weight(self):
        main = main_of(self.page("/me/security/protection"))
        rows = re.findall(r'<li class="krow">.*?</li>', main)
        self.assertEqual(2, len(rows))
        shape = [re.sub(r">[^<]+<", "><", re.sub(r'href="[^"]*"', "", r)) for r in rows]
        self.assertEqual(shape[0], shape[1])
        self.assertNotIn("recommended", main.lower())

    def test_recovery_shows_the_masked_address_and_the_owner_route(self):
        main = main_of(self.page("/me/security/recovery"))
        self.assertIn("Forgot password?", main)
        self.assertIn("m•••@example.test", main)
        self.assertNotIn("member.a@", main)
        self.assertIn("Ask the person who invited you", main)
        self.assertEqual(["/me/security/recovery/codes"], hrefs(main))

    def test_the_jellyfin_password_copy_shows_only_for_members_with_tv_and_movies(self):
        self.assertIn("TV and Movies keeps its own copy", main_of(self.page("/me/security/password")))
        self.assertNotIn("TV and Movies", main_of(self.page("/me/security/password", BOOKS)))

    def test_without_the_reader_nothing_is_claimed(self):
        main = main_of(self.page("/me/security/protection"))
        self.assertNotIn("No passkey", main)
        self.assertNotIn("iPhone", main)
        for action in security.ACTIONS:
            main = main_of(self.page(security.DONE_PREFIX + action))
            self.assertIn("couldn't confirm", main, action)
            self.assertNotIn("added", main.replace("Added", ""), action)
        body = json.loads(self.on.get(security.JSON_ROUTE, headers=VIDEO).text)
        self.assertEqual({"passkey": "unknown", "totp": "unknown", "recovery_codes": "unknown"}, body["enrollment"])

    def test_pages_carry_the_shell_csp_and_no_inline_script(self):
        for path in PAGES:
            r = self.on.get(path, headers=VIDEO)
            self.assertTrue(r.headers["content-security-policy"].startswith(CSP.decode()), path)
            self.assertEqual("no-store", r.headers["cache-control"], path)
            self.assertNotIn("<script>", r.text)
            self.assertNotIn("style=", main_of(r.text))

    def test_me_links_to_account_and_security(self):
        self.assertIn('href="/me/security"', main_of(self.page("/me")))


class WithReader(unittest.TestCase):
    def setUp(self):
        self.auth = FakeAuth()
        self.client = client_with(AccountReader(self.auth), security_flows=FLOWS)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def main(self, path, headers=VIDEO):
        r = self.client.get(path, headers=headers)
        self.assertEqual(200, r.status_code, path)
        return main_of(r.text)

    def test_protection_lists_only_the_members_own_methods(self):
        main = self.main("/me/security/protection")
        self.assertIn("iPhone", main)
        self.assertIn("Added", main)
        self.assertIn("No passkey or authenticator app yet", self.main("/me/security/protection", OTHER))
        body = json.loads(self.client.get(security.JSON_ROUTE, headers=VIDEO).text)
        self.assertEqual({"passkey": "verified_enrolled", "totp": "verified_absent",
                          "recovery_codes": "unknown"}, body["enrollment"])     # the reader can't see backup codes

    def test_done_says_added_only_for_a_method_created_minutes_ago(self):
        self.assertIn("We couldn't see a change", self.main("/me/security/done/passkey"))
        self.auth.devices[7].append({"name": "MacBook", "meta_model_name": "x.webauthndevice", "created": iso(1),
                                     "confirmed": True})
        main = self.main("/me/security/done/passkey")
        self.assertIn("Passkey added: MacBook", main)
        self.assertIn("We couldn't see a change", self.main("/me/security/done/totp"))

    def test_done_password_needs_a_fresh_change_date(self):
        self.assertIn("We couldn't see a change to your password", self.main("/me/security/done/password"))
        self.auth.users[0]["password_change_date"] = iso(2)
        main = self.main("/me/security/done/password")
        self.assertIn("Your password was changed", main)
        self.assertIn("TV and Movies keeps its own copy", main)

    def test_sessions_list_and_sign_out_one(self):
        r = self.client.get("/me/security/sessions", headers=VIDEO)
        main = main_of(r.text)
        self.assertIn("Safari on iPhone", main)
        self.assertIn("Leeds, GB", main)
        self.assertIn("Firefox on Windows", main)
        self.assertNotIn(S3, main)                        # another member's session never shows
        token = re.search(r'name="t" value="([^"]+)"', main).group(1)
        r = form_post(self.client, "/me/security/sessions", f"t={token}&session={S2}", VIDEO)
        self.assertEqual((303, "/me/security/sessions?r=ended"), (r.status_code, r.headers["location"]))
        self.assertEqual(("DELETE", f"{accountreader.SESSIONS}{S2}/", {}), self.auth.calls[-1])
        self.assertIn("Signed out.", self.main("/me/security/sessions?r=ended"))
        self.assertNotIn("Firefox on Windows", self.main("/me/security/sessions"))

    def test_cannot_sign_out_someone_elses_session(self):
        token = re.search(r'name="t" value="([^"]+)"', self.main("/me/security/sessions")).group(1)
        r = form_post(self.client, "/me/security/sessions", f"t={token}&session={S3}", VIDEO)
        self.assertEqual("/me/security/sessions?r=not_yours", r.headers["location"])
        self.assertFalse([c for c in self.auth.calls if c[0] == "DELETE"])
        self.assertEqual(1, len(self.auth.sessions["member-b"]))

    def test_form_locks(self):
        token = re.search(r'name="t" value="([^"]+)"', self.main("/me/security/sessions")).group(1)
        # another member's token
        r = form_post(self.client, "/me/security/sessions", f"t={token}&session={S3}", OTHER)
        self.assertEqual("/me/security/sessions?r=expired", r.headers["location"])
        # cross-site
        h = dict(VIDEO, **{"Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(403, self.client.post("/me/security/sessions", content=f"t={token}&session={S2}",
                                               headers=h).status_code)
        # extra or missing fields
        self.assertEqual(400, form_post(self.client, "/me/security/sessions", f"t={token}", VIDEO).status_code)
        self.assertEqual(400, form_post(self.client, "/me/security/sessions",
                                        f"t={token}&session={S2}&x=1", VIDEO).status_code)
        self.assertFalse([c for c in self.auth.calls if c[0] == "DELETE"])

    def test_unreadable_reader_says_so_and_never_none(self):
        self.auth.fail = UpstreamTimeout()
        main = self.main("/me/security/protection")
        self.assertIn("couldn't be loaded", main)
        self.assertNotIn("No passkey", main)
        self.assertIn("couldn't be loaded", self.main("/me/security/sessions"))
        self.assertIn("couldn't confirm", self.main("/me/security/done/passkey"))

    def test_post_without_the_reader_is_the_standard_501(self):
        with client_with() as c:
            r = form_post(c, "/me/security/sessions", "t=x&session=" + S1, VIDEO)
            self.assertEqual(501, r.status_code)


class Reader(unittest.TestCase):
    def test_allow_list(self):
        ok = (("GET", accountreader.USERS, {"username": "a"}), ("GET", accountreader.DEVICES, {"user": "7"}),
              ("GET", accountreader.SESSIONS, {"user__username": "a"}),
              ("DELETE", accountreader.SESSIONS + S1 + "/", None))
        for call in ok:
            accountreader.check_request(*call)
        for call in (("GET", "/api/v3/authenticators/admin/static/", {"user": "7"}),
                     ("GET", accountreader.DEVICES, {"user": "7 OR 1"}),
                     ("DELETE", accountreader.SESSIONS + "../users/1/", None),
                     ("POST", "/api/v3/core/users/7/set_password/", None),
                     ("GET", accountreader.USERS, {"username": "a", "is_superuser": "true"}),
                     ("DELETE", "/api/v3/authenticators/admin/webauthn/1/", None)):
            with self.assertRaises(accountreader.ForbiddenAccountRequest, msg=call):
                accountreader.check_request(*call)

    def test_an_ambiguous_or_inactive_account_reads_as_unavailable(self):
        from avrana_home.principal import principal_from_headers
        p = principal_from_headers([(USER, "member-a"), (GROUPS, "avrana-users")])
        auth = FakeAuth()
        self.assertIsNotNone(AccountReader(auth).view(p))
        auth.users.append({"pk": 9, "username": "member-a", "is_active": True})
        self.assertIsNone(AccountReader(auth).view(p))
        auth.users[1:] = [{"pk": 8, "username": "member-b", "is_active": True}]
        auth.users[0]["is_active"] = False
        self.assertIsNone(AccountReader(auth).view(p))

    def test_said_when(self):
        now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
        self.assertEqual("just now", accountreader.said_when(now - timedelta(minutes=3), now))
        self.assertEqual("today", accountreader.said_when(now - timedelta(hours=3), now))
        self.assertEqual("yesterday", accountreader.said_when(now - timedelta(days=1), now))
        self.assertEqual("on 3 Oct 2026", accountreader.said_when(datetime(2026, 10, 3, tzinfo=timezone.utc), now))

    def test_mask_email(self):
        self.assertEqual("m•••@example.net", security.mask_email("member@example.net"))
        for bad in ("", "nope", "@x.test", "a@", "a@b@c"):
            self.assertEqual("", security.mask_email(bad), bad)


class Config(unittest.TestCase):
    def env(self, **extra):
        return dict({"HOME_SECTIONS": "on"}, **extra)

    def test_flows_parse_strictly(self):
        s = Settings.from_env(self.env(HOME_SECURITY_FLOWS="password=avrana-password, totp=avrana-authenticator"))
        self.assertEqual((("password", "avrana-password"), ("totp", "avrana-authenticator")), s.security_flows)
        self.assertEqual((), Settings.from_env(self.env()).security_flows)

    def test_bad_values_refuse_to_start(self):
        for extra in ({"HOME_SECURITY_FLOWS": "sessions=x"}, {"HOME_SECURITY_FLOWS": "password=../x"},
                      {"HOME_SECURITY_FLOWS": "password=a,password=b"}, {"HOME_SECURITY_FLOWS": "password"},
                      {"HOME_SECURITY_FLOWS": "passkey=https://evil.example/"},
                      {"HOME_SECURITY_RETURN_ORIGIN": "https://media.example"},
                      {"HOME_ACCOUNT_READER_URL": "http://127.0.0.1:9000"},
                      {"HOME_ACCOUNT_READER_URL": "http://10.9.9.9:9000", "HOME_ACCOUNT_READER_TOKEN": "x"}):
            with self.assertRaises(SettingsError, msg=extra):
                Settings.from_env(self.env(**extra))


if __name__ == "__main__":
    unittest.main()
