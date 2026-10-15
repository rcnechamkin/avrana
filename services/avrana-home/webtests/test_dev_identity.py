"""Tier A: the development identity shim cannot be enabled by accident, and forges nothing else.

Driven through the raw ASGI interface with a recording inner app, so no framework is needed.
"""
import asyncio
import unittest

from avrana_home.app.settings import MOCK_API_KEY, Settings
from dev.dev_identity import (DEV_IDENTITIES, DevIdentityMiddleware, DevIdentityRefused,
                              check_startup)

from .support import make_settings

GOOD = make_settings(home_sections=True)


def checked():
    return check_startup(enabled=True, host="127.0.0.1", settings=GOOD)


async def drive(mw, headers, path="/", method="GET"):
    """Run one request through `mw`; return (status, response headers, body)."""
    sent = []
    scope = {"type": "http", "method": method, "path": path, "raw_path": path.encode(),
             "headers": headers, "query_string": b""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await mw(scope, receive, send)
    start = sent[0]
    body = b"".join(m.get("body", b"") for m in sent[1:])
    return start["status"], dict(start["headers"]), body


class Recorder:
    """Inner app: records the headers it was given and answers HTML or JSON."""

    def __init__(self, ctype=b"text/html; charset=utf-8", body=b"<html><body><p>hi</p></body></html>"):
        self.seen = None
        self.ctype, self.body = ctype, body

    async def __call__(self, scope, receive, send):
        self.seen = [(k.decode(), v.decode()) for k, v in scope["headers"]]
        await send({"type": "http.response.start", "status": 200, "headers": [
            (b"content-type", self.ctype), (b"content-length", str(len(self.body)).encode())]})
        await send({"type": "http.response.body", "body": self.body})


def run(coro):
    return asyncio.run(coro)


class StartupRefusalTests(unittest.TestCase):
    def test_default_is_refused_without_the_explicit_setting(self):
        with self.assertRaises(DevIdentityRefused):
            check_startup(enabled=False, host="127.0.0.1", settings=GOOD)
        with self.assertRaises(DevIdentityRefused):
            check_startup(enabled=None, host="127.0.0.1", settings=GOOD)
        with self.assertRaises(DevIdentityRefused):
            check_startup(enabled="yes", host="127.0.0.1", settings=GOOD)

    def test_non_loopback_bind_is_refused(self):
        for host in ("0.0.0.0", "::", "192.0.2.5", "localhost", "", "avrana.net", "127.0.0.2", "10.0.0.1"):
            with self.subTest(host=host), self.assertRaises(DevIdentityRefused):
                check_startup(enabled=True, host=host, settings=GOOD)

    def test_loopback_literals_are_accepted(self):
        for host in ("127.0.0.1", "::1"):
            self.assertIsNotNone(check_startup(enabled=True, host=host, settings=GOOD))

    def test_real_upstream_is_refused(self):
        real = Settings.from_mapping({"HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes",
                                      "JELLYFIN_BASE_URL": "http://jellyfin.internal:8096",
                                      "JELLYFIN_API_KEY": "fake-key-for-test"})
        with self.assertRaises(DevIdentityRefused):
            check_startup(enabled=True, host="127.0.0.1", settings=real)

    def test_non_mock_upstream_url_or_key_is_refused_even_if_settings_were_edited(self):
        from dataclasses import replace
        for edit in ({"jellyfin_base_url": "http://watch.avrana.net"},
                     {"jellyfin_base_url": "http://192.0.2.10:8096"},
                     {"jellyfin_api_key": "some-other-fake-key"},
                     {"upstream_mode": "real"}):
            with self.subTest(edit=edit), self.assertRaises(DevIdentityRefused):
                check_startup(enabled=True, host="127.0.0.1", settings=replace(GOOD, **edit))

    def test_the_middleware_cannot_be_built_without_the_sealed_check(self):
        for token in (None, True, object(), "checked"):
            with self.subTest(token=token), self.assertRaises(DevIdentityRefused):
                DevIdentityMiddleware(Recorder(), checked=token)
        DevIdentityMiddleware(Recorder(), checked=checked())

    def test_the_default_application_package_knows_nothing_about_the_shim(self):
        from pathlib import Path
        pkg = Path(__file__).resolve().parents[1] / "avrana_home"
        for path in pkg.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for word in ("dev_identity", "DevIdentity", "_dev/identity", "x-dev-identity", "avrana_dev_identity"):
                self.assertNotIn(word, text.replace("`dev_identity`", ""), f"{path.name}: {word}")


class HeaderHandlingTests(unittest.TestCase):
    def setUp(self):
        self.inner = Recorder()
        self.mw = DevIdentityMiddleware(self.inner, checked=checked())

    def seen(self, name):
        return [v for k, v in self.inner.seen if k == name]

    def test_nothing_selected_means_no_identity_at_all(self):
        run(drive(self.mw, []))
        self.assertEqual([], [k for k, _ in self.inner.seen if k.startswith("x-authentik")])

    def test_client_supplied_identity_headers_are_never_trusted(self):
        hostile = [(b"X-authentik-username", b"member-a"), (b"x-authentik-groups", b"authentik Admins"),
                   (b"X_authentik_username", b"member-a"), (b"x_authentik_groups", b"authentik Admins"),
                   (b"X-Authentik-Email", b"evil@example.test"), (b"x-authentik-uid", b"1"),
                   (b"X-Forwarded-User", b"member-a"), (b"Remote-User", b"member-a"),
                   (b"x-authentik-groups", b"avrana-videos")]
        run(drive(self.mw, hostile))
        names = [k for k, _ in self.inner.seen]
        self.assertFalse([n for n in names if "authentik" in n or "forwarded-user" in n or n == "remote-user"], names)

    def test_selected_identity_replaces_every_client_value(self):
        run(drive(self.mw, [(b"x-dev-identity", b"member-a"), (b"X-authentik-username", b"synthetic-admin"),
                            (b"x-authentik-groups", b"authentik Admins"), (b"X_authentik_groups", b"authentik Admins")]))
        self.assertEqual(["member-a"], self.seen("x-authentik-username"))
        self.assertEqual(["avrana-users|avrana-videos|avrana-audiobooks"], self.seen("x-authentik-groups"))
        self.assertNotIn("x-dev-identity", [k for k, _ in self.inner.seen])
        self.assertFalse([k for k, _ in self.inner.seen if "_" in k and "authentik" in k])

    def test_selection_by_cookie_and_unknown_names_select_nothing(self):
        run(drive(self.mw, [(b"cookie", b"x=1; avrana_dev_identity=member-b; y=2")]))
        self.assertEqual(["member-b"], self.seen("x-authentik-username"))
        for bad in (b"synthetic-admin2", b"member-a\r\nX-authentik-groups: authentik Admins", b"", b"../x",
                    b"MEMBER-A"):
            run(drive(self.mw, [(b"x-dev-identity", bad)]))
            self.assertEqual([], self.seen("x-authentik-username"), bad)
            run(drive(self.mw, [(b"cookie", b"avrana_dev_identity=" + bad)]))
            self.assertEqual([], self.seen("x-authentik-username"), bad)

    def test_every_synthetic_identity_uses_example_test_addresses(self):
        for name, who in DEV_IDENTITIES.items():
            self.assertTrue(who["email"].endswith("@example.test"), name)

    def test_only_html_gets_the_banner_and_length_is_fixed_up(self):
        status, headers, body = run(drive(self.mw, [(b"x-dev-identity", b"member-a")]))
        self.assertIn(b"DEVELOPMENT IDENTITY: member-a", body)
        self.assertEqual(str(len(body)).encode(), headers[b"content-length"])
        self.assertTrue(body.startswith(b"<html><body><div role=\"note\""))
        json_app = DevIdentityMiddleware(Recorder(b"application/json", b'{"a": 1}'), checked=checked())
        _s, _h, jbody = run(drive(json_app, [(b"x-dev-identity", b"member-a")]))
        self.assertEqual(b'{"a": 1}', jbody)

    def test_banner_is_present_even_when_no_identity_is_selected(self):
        _s, _h, body = run(drive(self.mw, []))
        self.assertIn(b"DEVELOPMENT IDENTITY: none", body)

    def test_head_requests_pass_through_untouched(self):
        status, headers, body = run(drive(self.mw, [(b"x-dev-identity", b"member-a")], method="HEAD"))
        self.assertEqual(200, status)
        self.assertNotIn(b"DEVELOPMENT", body)


class SwitcherTests(unittest.TestCase):
    def setUp(self):
        self.inner = Recorder()
        self.mw = DevIdentityMiddleware(self.inner, checked=checked())

    def test_switcher_lists_every_synthetic_identity_and_never_reaches_the_app(self):
        status, headers, body = run(drive(self.mw, [], "/_dev/identity"))
        self.assertEqual(200, status)
        self.assertIsNone(self.inner.seen)
        for name in DEV_IDENTITIES:
            self.assertIn(f"/_dev/identity/{name}".encode(), body)
        self.assertIn(b"DEVELOPMENT IDENTITY", body)

    def test_choosing_sets_a_cookie_and_redirects_to_a_fixed_location(self):
        status, headers, _ = run(drive(self.mw, [], "/_dev/identity/member-a"))
        self.assertEqual(303, status)
        self.assertEqual(b"/", headers[b"location"])
        self.assertIn(b"avrana_dev_identity=member-a", headers[b"set-cookie"])
        self.assertIn(b"HttpOnly", headers[b"set-cookie"])

    def test_unknown_choice_sets_nothing(self):
        for path in ("/_dev/identity/evil", "/_dev/identity/member-a%0d%0aSet-Cookie:x=1", "/_dev/identity/../x"):
            status, headers, _ = run(drive(self.mw, [], path))
            self.assertEqual(404, status, path)
            self.assertNotIn(b"set-cookie", headers)

    def test_switcher_responses_carry_the_hygiene_headers(self):
        _s, headers, _b = run(drive(self.mw, [], "/_dev/identity"))
        for name in (b"cache-control", b"referrer-policy", b"x-content-type-options",
                     b"content-security-policy"):
            self.assertIn(name, headers)
        self.assertNotIn(b"script-src", headers[b"content-security-policy"])
        self.assertIn(b"default-src 'none'", headers[b"content-security-policy"])


if __name__ == "__main__":
    unittest.main()
