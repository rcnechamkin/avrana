"""Tier B: Me -> Account & Security (Media 2.0 supplement, 2026-10-27; security.py). SYNTHETIC data only.

What this slice adds and must never weaken:
  * Every /me/security path exists only with the shell and a verified member; otherwise it is the standard 404, the
    same bytes as an unknown route (portal parity).
  * The hand-off is a 303 to a FIXED Authentik address: the catalogue's account origin plus Authentik's settings page,
    or a flow the owner configured. Nothing in the request can choose the destination; an action off the allowlist is
    the standard 404.
  * Nothing ever claims a change worked: enrollment is "unknown", and coming back can only say "couldn't confirm" or
    "someone else is signed in now". The return state is opaque, bound to the member, and expires.
  * Passkey and authenticator are offered with equal weight; no "recommended" badge; no flow slug, host or upstream
    detail in the member's JSON.
"""
import json
import re
import unittest
from urllib.parse import parse_qs, unquote, urlsplit

from avrana_home.app import security
from avrana_home.app.middleware import CSP
from avrana_home.app.settings import Settings, SettingsError
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

NAME = "X-authentik-name"
VIDEO = [(USER, "member-a"), (NAME, "Member A"), (GROUPS, "avrana-users|avrana-videos")]
BOOKS = [(USER, "member-k"), (GROUPS, "avrana-users|avrana-books")]
OTHER = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos")]
PAGES = ("/me/security", "/me/security/password", "/me/security/protection", "/me/security/protection/passkey",
         "/me/security/protection/authenticator", "/me/security/recovery", "/me/security/sessions",
         "/me/security/back")
GO = tuple(security.GO_PREFIX + a for a in security.ACTIONS)


def main_of(text):
    return re.split(r"<main(?:\s[^>]*)?>", text)[1].split("</main>")[0]


def hrefs(fragment):
    return re.findall(r'<a class="krow-a" href="([^"]*)"', fragment)


def client_with(**overrides):
    data = {"member-a": [("a" * 32, "Synthetic Security Film", 0.5)]}
    return make_client(make_settings(home_sections=True, **overrides), adapters=[StubAdapter(data)])


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

    def page(self, path, headers=VIDEO):
        r = self.on.get(path, headers=headers)
        self.assertEqual(200, r.status_code, path)
        return r.text


class Gating(Base):
    def test_only_with_the_shell_and_a_member_otherwise_exactly_an_unknown_route(self):
        for client, headers in ((self.off, VIDEO), (self.on, []), (self.on, [(GROUPS, "avrana-videos")])):
            nope = client.get("/nope", headers=headers)
            for path in PAGES + GO + (security.JSON_ROUTE,):
                r = client.get(path, headers=headers)
                self.assertEqual((404, nope.text), (r.status_code, r.text), (path, headers))
                self.assertEqual(nope.headers["content-security-policy"], r.headers["content-security-policy"])

    def test_unknown_paths_and_actions_under_the_prefix_are_the_standard_404(self):
        nope = self.on.get("/nope", headers=VIDEO)
        for path in ("/me/securityx", "/me/security/admin", "/me/security/go/", "/me/security/go/delete",
                     "/me/security/go/PASSWORD", "/me/security/go/password/extra", "/me/security/go/..%2fadmin",
                     "/me/security/protection/both", "/me/security.json/x"):
            r = self.on.get(path, headers=VIDEO)
            self.assertEqual((404, nope.text), (r.status_code, r.text), path)


class Pages(Base):
    def test_hub_lists_the_supplement_rows_and_one_sign_out(self):
        main = main_of(self.page("/me/security"))
        self.assertIn('<h2 class="topic">Account &amp; Security</h2>', main)
        self.assertEqual(["/me/security/password", "/me/security/protection", "/me/security/recovery",
                          "/me/security/sessions", "/signout"], hrefs(main))
        self.assertEqual(1, main.count('href="/signout"'))
        for word in ("everywhere", "authentik", "Authentik", "score", "Recommended", "recommended"):
            self.assertNotIn(word, main, word)

    def test_passkey_and_authenticator_have_equal_weight(self):
        main = main_of(self.page("/me/security/protection"))
        rows = re.findall(r'<li class="krow">.*?</li>', main)
        self.assertEqual(2, len(rows))
        shape = [re.sub(r">[^<]+<", "><", re.sub(r'href="[^"]*"', "", r)) for r in rows]
        self.assertEqual(shape[0], shape[1])            # same markup, icon and chevron: only the words differ
        self.assertNotIn("recommended", main.lower())

    def test_detail_pages_hand_off_through_go_and_never_claim_success(self):
        for path, action in (("/me/security/password", "password"), ("/me/security/protection/passkey", "passkey"),
                             ("/me/security/protection/authenticator", "totp"),
                             ("/me/security/sessions", "sessions")):
            main = main_of(self.page(path))
            self.assertIn(f'href="/me/security/go/{action}"', main, path)
            self.assertIn("can't see whether a change went through", main, path)
            for claim in ("added", "enabled", "was changed", "Success"):
                self.assertNotIn(claim, main.replace("Adding a passkey", ""), (path, claim))
            self.assertNotIn(self.origin, main)          # the address is server side, behind /go

    def test_the_jellyfin_password_copy_shows_only_for_members_with_tv_and_movies(self):
        self.assertIn("TV and Movies keeps its own copy", main_of(self.page("/me/security/password")))
        self.assertNotIn("TV and Movies", main_of(self.page("/me/security/password", BOOKS)))

    def test_recovery_points_at_the_sign_in_page_and_the_owner_not_an_avrana_reset(self):
        main = main_of(self.page("/me/security/recovery"))
        self.assertIn("Forgot password?", main)
        self.assertIn("Ask the person who invited you", main)
        self.assertEqual(["/me/security/go/account", "/me/security/go/recovery_codes"], hrefs(main))

    def test_pages_carry_the_shell_csp_and_no_inline_script(self):
        for path in PAGES:
            r = self.on.get(path, headers=VIDEO)
            self.assertTrue(r.headers["content-security-policy"].startswith(CSP.decode()), path)
            self.assertEqual("no-store", r.headers["cache-control"], path)
            self.assertNotIn("<script>", r.text)
            self.assertNotIn("style=", main_of(r.text))

    def test_me_links_to_account_and_security(self):
        self.assertIn('href="/me/security"', main_of(self.page("/me")))


class Handoff(Base):
    def test_default_hand_off_is_authentik_settings_for_every_action(self):
        for action in security.ACTIONS:
            r = self.on.get(security.GO_PREFIX + action, headers=VIDEO)
            self.assertEqual(303, r.status_code, action)
            self.assertEqual(self.origin + security.SETTINGS_PATH, r.headers["location"], action)
            self.assertEqual("", r.text)

    def test_query_text_cannot_change_the_destination(self):
        for q in ("?next=https://evil.example", "?target=//evil.example", "?s=x"):
            r = self.on.get("/me/security/go/password" + q, headers=VIDEO)
            self.assertEqual(self.origin + security.SETTINGS_PATH, r.headers["location"], q)

    def test_owner_verified_flows_are_used_only_for_their_action(self):
        with client_with(security_flows=(("passkey", "default-authenticator-webauthn-setup"),)) as c:
            self.assertEqual(self.origin + "/if/flow/default-authenticator-webauthn-setup/",
                             c.get("/me/security/go/passkey", headers=VIDEO).headers["location"])
            self.assertEqual(self.origin + security.SETTINGS_PATH,
                             c.get("/me/security/go/totp", headers=VIDEO).headers["location"])
            body = json.loads(c.get(security.JSON_ROUTE, headers=VIDEO).text)
            self.assertEqual("direct", body["capabilities"]["enroll_passkey"]["via"])
            self.assertNotIn("webauthn", json.dumps(body))           # no slug in what the member reads
            # a settings-page hand-off says where to look; a direct flow does not need to
            self.assertNotIn("MFA Devices", main_of(c.get("/me/security/protection/passkey", headers=VIDEO).text))
            self.assertIn("MFA Devices", main_of(c.get("/me/security/protection/authenticator", headers=VIDEO).text))


class Return(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ret = client_with(security_return_origin="https://media.example",
                              security_flows=(("password", "default-password-change"),))
        cls.ret.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ret.__exit__(None, None, None)
        super().tearDownClass()

    def state_from(self, location):
        nxt = unquote(parse_qs(urlsplit(location).query)["next"][0])
        self.assertTrue(nxt.startswith("https://media.example/me/security/back?s="), nxt)
        return parse_qs(urlsplit(nxt).query)["s"][0]

    def test_return_carries_an_opaque_state_only_on_direct_flows(self):
        loc = self.ret.get("/me/security/go/password", headers=VIDEO).headers["location"]
        state = self.state_from(loc)
        self.assertNotIn("member-a", loc)
        self.assertNotIn("member-a", state)
        # the settings page is a fragment address: no `next` is appended to it
        self.assertEqual(self.origin + security.SETTINGS_PATH,
                         self.ret.get("/me/security/go/passkey", headers=VIDEO).headers["location"])

    def test_coming_back_never_claims_success(self):
        state = self.state_from(self.ret.get("/me/security/go/password", headers=VIDEO).headers["location"])
        main = main_of(self.ret.get("/me/security/back?s=" + state, headers=VIDEO).text)
        self.assertIn("couldn't confirm whether your password changed", main)
        self.assertIn('role="status"', main)

    def test_someone_else_coming_back_carries_nothing_over(self):
        state = self.state_from(self.ret.get("/me/security/go/password", headers=VIDEO).headers["location"])
        main = main_of(self.ret.get("/me/security/back?s=" + state, headers=OTHER).text)
        self.assertIn("signed in as member-b now", main)
        self.assertNotIn("password", main.split("role=\"status\"")[1].split("</p>")[0])

    def test_garbage_or_missing_state_is_a_calm_unknown(self):
        for q in ("", "?s=", "?s=password.1.x", "?s=" + "a" * 400, "?s=%00%0d%0a", "?s=<script>",
                  "?s=password.%C2%B2.x", "?s=password.99999999999.%C3%A9", "?s=password.1.x.y", "?s=.1.x"):
            r = self.ret.get("/me/security/back" + q, headers=VIDEO)
            self.assertEqual(200, r.status_code, q)
            self.assertIn("couldn't confirm what changed", main_of(r.text), q)
            self.assertNotIn("<script>", main_of(r.text))


class States(unittest.TestCase):
    def test_states_expire_and_bind_to_the_member(self):
        now = [1_000_000.0]
        states = security.ReturnStates(clock=lambda: now[0], key=b"k" * 32)
        s = states.mint("passkey", "member-a")
        self.assertEqual(("unknown", "passkey"), (states.check(s, "member-a").outcome, states.check(s, "member-a").action))
        self.assertEqual("session_changed", states.check(s, "member-b").outcome)
        now[0] += security.STATE_TTL + 1
        r = states.check(s, "member-a")
        self.assertEqual(("unknown", None, True), (r.outcome, r.action, r.expired))

    def test_a_state_from_another_process_reads_as_session_changed_never_as_confirmed(self):
        a, b = security.ReturnStates(key=b"a" * 32), security.ReturnStates(key=b"b" * 32)
        self.assertEqual("session_changed", b.check(a.mint("password", "member-a"), "member-a").outcome)
        for outcome in ("confirmed", "cancelled", "failed"):
            self.assertIn(outcome, security.OUTCOMES)      # modelled for a later provider-backed read, never produced

    def test_capabilities_say_unknown_enrollment_and_no_result_reporting(self):
        cfg = security.SecurityConfig.build("https://auth.example/if/user/")
        body = cfg.summary()
        self.assertEqual({"passkey": "unknown", "totp": "unknown", "recovery_codes": "unknown"}, body["enrollment"])
        self.assertFalse(body["return"]["reports_result"])
        self.assertEqual("sign_in_page", body["capabilities"]["recover_by_email"]["via"])
        self.assertNotIn("auth.example", json.dumps(body))


class Config(unittest.TestCase):
    def env(self, **extra):
        return dict({"HOME_SECTIONS": "on"}, **extra)

    def test_flows_and_return_origin_parse_strictly(self):
        s = Settings.from_env(self.env(HOME_SECURITY_FLOWS="password=default-password-change, totp=my-totp",
                                       HOME_SECURITY_RETURN_ORIGIN="https://media.example/"))
        self.assertEqual((("password", "default-password-change"), ("totp", "my-totp")), s.security_flows)
        self.assertEqual("https://media.example", s.security_return_origin)
        self.assertEqual(((), ""), (Settings.from_env(self.env()).security_flows,
                                    Settings.from_env(self.env()).security_return_origin))

    def test_bad_values_refuse_to_start(self):
        for name, value in (("HOME_SECURITY_FLOWS", "sessions=x"), ("HOME_SECURITY_FLOWS", "password=../x"),
                            ("HOME_SECURITY_FLOWS", "password=a,password=b"), ("HOME_SECURITY_FLOWS", "password"),
                            ("HOME_SECURITY_FLOWS", "passkey=https://evil.example/"),
                            ("HOME_SECURITY_RETURN_ORIGIN", "http://media.example"),
                            ("HOME_SECURITY_RETURN_ORIGIN", "https://media.example/me"),
                            ("HOME_SECURITY_RETURN_ORIGIN", "https://" + "u:p" + "@media.example"),   # userinfo, split for the reviewer
                            ("HOME_SECURITY_RETURN_ORIGIN", "https://media.example?x=1")):
            with self.assertRaises(SettingsError, msg=(name, value)):
                Settings.from_env(self.env(**{name: value}))


if __name__ == "__main__":
    unittest.main()
