"""Tier B: the identity path, fail-closed matrix, header behaviour over a REAL uvicorn server.

Every case below sends identity headers that WOULD grant Movies and TV if they were accepted; the
assertion is that nothing is granted, nothing is revealed and no adapter is called. The same
cases run through the Starlette test client and (a representative set) over a real socket, because
repeated headers and header-name case are decided by the server, not the framework.
"""
import unittest

from dev.mock_jellyfin import MockJellyfin

from .support import GROUPS, USER, RealServer, make_client, make_settings, require_framework, wire

require_framework()

GOOD_GROUPS = "avrana-users|avrana-videos"
OK = [(USER, "member-a"), (GROUPS, GOOD_GROUPS)]

CASES = {
    "missing_everything": [],
    "missing_groups": [(USER, "member-a")],
    "missing_username": [(GROUPS, GOOD_GROUPS)],
    "empty_username": [(USER, ""), (GROUPS, GOOD_GROUPS)],
    "empty_groups": [(USER, "member-a"), (GROUPS, "")],
    "blank_groups": [(USER, "member-a"), (GROUPS, "   ")],
    "separator_only_groups": [(USER, "member-a"), (GROUPS, "|,|")],
    "duplicate_username_same": [(USER, "member-a"), (USER, "member-a"), (GROUPS, GOOD_GROUPS)],
    "duplicate_username_different": [(USER, "member-a"), (USER, "member-b"), (GROUPS, GOOD_GROUPS)],
    "duplicate_groups_good_first": [(USER, "member-a"), (GROUPS, GOOD_GROUPS), (GROUPS, "avrana-users")],
    "duplicate_groups_good_second": [(USER, "member-a"), (GROUPS, "avrana-users"), (GROUPS, GOOD_GROUPS)],
    "duplicate_groups_identical": [(USER, "member-a"), (GROUPS, GOOD_GROUPS), (GROUPS, GOOD_GROUPS)],
    "duplicate_mixed_case_name": [(USER, "member-a"), ("X-authentik-groups", GOOD_GROUPS),
                                  ("x-AUTHENTIK-GROUPS", GOOD_GROUPS)],
    "duplicate_user_mixed_case": [("X-AUTHENTIK-USERNAME", "member-a"), ("x-authentik-username", "member-a"),
                                  (GROUPS, GOOD_GROUPS)],
    "username_with_pipe": [(USER, "member|a"), (GROUPS, GOOD_GROUPS)],
    "username_with_comma": [(USER, "member,a"), (GROUPS, GOOD_GROUPS)],
    "username_with_tab": [(USER, "mem\tber"), (GROUPS, GOOD_GROUPS)],
    "username_with_crlf": [(USER, "member-a\r\nX-authentik-groups: authentik Admins"), (GROUPS, GOOD_GROUPS)],
    "groups_with_crlf": [(USER, "member-a"), (GROUPS, "avrana-users\r\nX-authentik-username: member-b")],
    "oversized_username": [(USER, "a" * 151), (GROUPS, GOOD_GROUPS)],
    "oversized_groups_header": [(USER, "member-a"), (GROUPS, "avrana-videos|" + "g" * 5000)],
    "too_many_groups": [(USER, "member-a"), (GROUPS, "|".join(f"g{i}" for i in range(65)) + "|avrana-videos")],
    "oversized_single_group": [(USER, "member-a"), (GROUPS, "avrana-videos|" + "g" * 129)],
    "underscore_name_spoof": [("X_authentik_username", "member-a"), ("X_authentik_groups", GOOD_GROUPS)],
    "underscore_groups_spoof": [(USER, "member-a"), ("X_authentik_groups", GOOD_GROUPS)],
    "forwarded_user_spoof": [("X-Forwarded-User", "member-a"), ("X-Forwarded-Groups", GOOD_GROUPS)],
    "remote_user_spoof": [("Remote-User", "member-a"), ("X-Remote-Groups", GOOD_GROUPS)],
    "authorization_spoof": [("Authorization", "Bearer member-a"), ("Cookie", "groups=avrana-videos")],
    "lookalike_names": [("X-authentik-usernam", "member-a"), ("X-authentik-group", GOOD_GROUPS),
                        ("X-authentik-groups-x", GOOD_GROUPS), ("Y-X-authentik-groups", GOOD_GROUPS)],
    "dev_switch_headers": [("X-Dev-Identity", "member-a"), ("Cookie", "avrana_dev_identity=member-a")],
}
# Exact bytes: the test client re-encodes header values, so these go through the raw ASGI scope
# and over a real socket only.
RAW_CASES = {
    "invalid_utf8_username": [(b"X-authentik-username", b"\xff\xfe"), (b"X-authentik-groups", GOOD_GROUPS.encode())],
    "invalid_utf8_groups": [(b"X-authentik-username", b"member-a"), (b"X-authentik-groups", b"avrana-videos|\xc3")],
    "non_nfc_username": [(b"X-authentik-username", ("e" + chr(0x301)).encode()), (b"X-authentik-groups", GOOD_GROUPS.encode())],
    "nbsp_in_username": [(b"X-authentik-username", ("mem" + chr(0xa0) + "ber").encode()), (b"X-authentik-groups", GOOD_GROUPS.encode())],
    "bidi_override_username": [(b"X-authentik-username", ("member" + chr(0x202e) + "a").encode()), (b"X-authentik-groups", GOOD_GROUPS.encode())],
}
# The over-the-socket subset: those that survive HTTP framing and are decided by the server.
WIRE_CASES = [k for k in CASES if not any(isinstance(v, str) and ("\r" in v or "\n" in v or
              any(ord(c) > 127 for c in v)) for _k, v in CASES[k])
              ]


def tile_paths(text):
    import re
    return re.findall(r'<a class="tile" href="/([^"]*)"', text)


class FailClosedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = MockJellyfin().start()
        cls.settings = make_settings(home_sections=True, jellyfin_base_url=cls.mock.url, timeout=1.0)
        cls.client = make_client(cls.settings)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.mock.stop()

    def setUp(self):
        self.mock.reset()

    def test_control_the_good_headers_do_grant(self):
        r = self.client.get("/", headers=OK)
        self.assertEqual(["watch", "request", "help"], tile_paths(r.text))
        self.assertIn("Continue watching", r.text)
        self.assertEqual(200, self.client.get("/watch", headers=OK).status_code)   # the interstitial

    def test_every_bad_identity_is_treated_as_no_groups(self):
        for name, headers in CASES.items():
            with self.subTest(case=name):
                self.mock.reset()
                home = self.client.get("/", headers=headers)
                self.assertEqual(200, home.status_code)
                self.assertEqual(["help"], tile_paths(home.text))
                self.assertNotIn("<h2", home.text)                     # no sections, no sentence
                self.assertNotIn("Movies", home.text)
                for route in ("/watch", "/request", "/read", "/ops", "/help/movies", "/home.json"):
                    r = self.client.get(route, headers=headers)
                    self.assertEqual(404, r.status_code, route)
                    self.assertIn("That page does not exist.", r.text)
                acct = self.client.get("/account", headers=headers)
                self.assertEqual(200, acct.status_code)
                self.assertIn("<dt>Signed in</dt><dd>yes</dd>", acct.text)
                self.assertNotIn("member-a", acct.text)
                self.assertNotIn("Watch", acct.text.split("Your access")[1])
                self.assertEqual([], self.mock.paths(), "adapter reached the upstream")

    def test_denied_identity_pages_equal_a_request_with_no_headers(self):
        base_home = self.client.get("/").content
        base_404 = self.client.get("/watch").content
        for name, headers in CASES.items():
            with self.subTest(case=name):
                self.assertEqual(base_home, self.client.get("/", headers=headers).content)
                self.assertEqual(base_404, self.client.get("/watch", headers=headers).content)

    def test_extra_trusted_headers_cannot_rescue_a_bad_principal(self):
        r = self.client.get("/", headers=[(GROUPS, GOOD_GROUPS), ("X-authentik-email", "a@example.test"),
                                          ("X-authentik-name", "Member A")])
        self.assertEqual(["help"], tile_paths(r.text))

    def test_display_headers_never_decide_anything(self):
        """Email and name are display-only. A hostile value is dropped, not an error."""
        r = self.client.get("/account", headers=OK + [("X-authentik-name", "x" * 300)])
        self.assertEqual(200, r.status_code)
        self.assertIn("<dt>Username</dt><dd>member-a</dd>", r.text)
        self.assertNotIn("<dt>Name</dt>", r.text)
        r = self.client.get("/account", headers=OK + [("X-authentik-name", "A"), ("X-authentik-name", "B")])
        self.assertNotIn("<dt>Name</dt>", r.text)

    def test_default_app_ignores_the_development_switch_entirely(self):
        headers = [("X-Dev-Identity", "member-a"), ("Cookie", "avrana_dev_identity=member-a")]
        self.assertEqual(["help"], tile_paths(self.client.get("/", headers=headers).text))
        self.assertEqual(404, self.client.get("/_dev/identity", headers=headers).status_code)
        self.assertEqual(404, self.client.get("/_dev/identity/member-a").status_code)
        self.assertNotIn("DEVELOPMENT", self.client.get("/", headers=headers).text)

    def test_no_user_controlled_identity_anywhere_else(self):
        """A user id, username or group in the query string, path, cookie or body changes nothing."""
        base = self.client.get("/", headers=OK).content
        for target in ("/?user=member-b", "/?username=member-b&groups=authentik+Admins", "/?userId=x",
                       "/?as=member-b", "/?uid=bbbbbbbbbbbb4bbb8bbbbbbbbbbbbbbb"):
            self.assertEqual(base, self.client.get(target, headers=OK).content, target)
        r = self.client.get("/", headers=OK + [("Cookie", "user=member-b; groups=authentik Admins")])
        self.assertEqual(base, r.content)
        self.assertNotIn("Synthetic Film Two", self.client.get("/home.json?userId=bbbb", headers=OK).text)
        post = self.client.post("/", headers=OK, content=b"username=member-b")
        self.assertEqual(501, post.status_code)


def _raw(value):
    return value if isinstance(value, bytes) else value.encode("latin-1")


class RawScopeTests(unittest.TestCase):
    """Exact header bytes, straight into the ASGI app (no client re-encoding)."""

    @classmethod
    def setUpClass(cls):
        cls.mock = MockJellyfin().start()
        cls.app = make_client(make_settings(home_sections=True, jellyfin_base_url=cls.mock.url,
                                            timeout=1.0)).fastapi_app

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def call(self, headers, path="/"):
        import asyncio
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(m):
            sent.append(m)

        scope = {"type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
                 "query_string": b"", "client": ("203.0.113.9", 1), "headers": [
                     (_raw(k).lower(), _raw(v)) for k, v in headers]}
        asyncio.run(self.app(scope, receive, send))
        return sent[0]["status"], b"".join(m.get("body", b"") for m in sent[1:]).decode("utf-8")

    def test_byte_level_malformed_identities_fail_closed(self):
        for name, headers in RAW_CASES.items():
            with self.subTest(case=name):
                self.mock.reset()
                status, body = self.call(headers)
                self.assertEqual(200, status)
                self.assertEqual(["help"], tile_paths(body), name)
                self.assertEqual(404, self.call(headers, "/watch")[0], name)
                self.assertEqual([], self.mock.paths())

    def test_ascii_is_accepted_and_non_ascii_is_not(self):
        ok = [(b"X-authentik-username", ("m" + chr(0xe9) + "mber").encode()), (b"X-authentik-groups", b"avrana-users")]
        status, body = self.call(ok, "/account")
        self.assertNotIn("<dt>Username</dt>", body)         # non-ASCII username: no principal (I-5)
        ascii_ok = [(b"X-authentik-username", b"member-a"), (b"X-authentik-groups", b"avrana-users")]
        self.assertIn("<dt>Username</dt><dd>member-a</dd>", self.call(ascii_ok, "/account")[1])


class RealServerHeaderTests(unittest.TestCase):
    """Duplicate headers and header-name case as a real server delivers them."""

    @classmethod
    def setUpClass(cls):
        cls.mock = MockJellyfin().start()
        client = make_client(make_settings(home_sections=True, jellyfin_base_url=cls.mock.url, timeout=1.0))
        cls.client_app = client.fastapi_app
        cls.server = RealServer(cls.client_app).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)
        cls.mock.stop()

    def setUp(self):
        self.mock.reset()

    def get(self, headers, target="/"):
        return self.server.get(target, headers)

    def test_control_good_headers_over_a_socket(self):
        r = self.get(OK)
        self.assertEqual(200, r.status)
        self.assertEqual(["watch", "request", "help"], tile_paths(r.text))

    def test_server_keeps_repeated_headers_separate_and_lowercases_names(self):
        """What uvicorn (h11) really hands the application, observed rather than assumed."""
        seen = []
        inner = self.client_app

        async def probe(scope, receive, send):
            if scope["type"] == "http":
                seen.append(list(scope["headers"]))
            await inner(scope, receive, send)

        with RealServer(probe) as srv:
            srv.get("/", [("X-Authentik-Groups", "a"), ("x-authentik-groups", "b"),
                          ("X_Authentik_Groups", "c"), (USER, "member-a")])
        pairs = [(k, v) for k, v in seen[0] if k.startswith((b"x-authentik", b"x_authentik"))]
        self.assertEqual([(b"x-authentik-groups", b"a"), (b"x-authentik-groups", b"b"),
                          (b"x_authentik_groups", b"c"), (b"x-authentik-username", b"member-a")], pairs)

    def test_every_wire_case_fails_closed_over_a_real_socket(self):
        for name in WIRE_CASES:
            with self.subTest(case=name):
                r = self.get(CASES[name])
                self.assertEqual(200, r.status, name)
                self.assertEqual(["help"], tile_paths(r.text), name)
                self.assertEqual(404, self.get(CASES[name], "/watch").status, name)
        self.assertEqual([], self.mock.paths())

    def test_duplicate_groups_in_both_orders_and_mixed_case_over_a_socket(self):
        for headers in (
                [(USER, "member-a"), (GROUPS, GOOD_GROUPS), (GROUPS, "avrana-users")],
                [(USER, "member-a"), (GROUPS, "avrana-users"), (GROUPS, GOOD_GROUPS)],
                [(USER, "member-a"), ("x-authentik-GROUPS", GOOD_GROUPS), ("X-AUTHENTIK-groups", GOOD_GROUPS)],
                [("X-Authentik-Username", "member-a"), ("x-authentik-username", "member-a"), (GROUPS, GOOD_GROUPS)]):
            r = self.get(headers, "/watch")
            self.assertEqual(404, r.status, headers)
        self.assertEqual([], self.mock.paths())

    def test_header_name_case_variants_are_one_header_when_single(self):
        for name in ("X-Authentik-Groups", "x-authentik-groups", "X-AUTHENTIK-GROUPS"):
            r = self.get([(USER, "member-a"), (name, GOOD_GROUPS)], "/watch")
            self.assertEqual(200, r.status, name)           # the watch interstitial for a permitted member

    def test_crlf_injection_on_the_wire_becomes_a_duplicate_and_fails_closed(self):
        raw = (b"GET /watch HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n"
               b"X-authentik-username: member-a\r\nX-authentik-groups: avrana-users|avrana-videos\r\n"
               b"X-authentik-groups: avrana-users\r\n\r\n")
        self.assertEqual(404, self.server.exchange(raw).status)

    def test_raw_non_ascii_header_bytes_fail_closed_over_a_socket(self):
        raw = (b"GET /watch HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n"
               b"X-authentik-username: member-\xff\r\nX-authentik-groups: avrana-users|avrana-videos\r\n\r\n")
        self.assertEqual(404, self.server.exchange(raw).status)

    def test_non_ascii_usernames_get_no_principal_over_real_http(self):
        """Owner decision (HOME-APP.md I-5): identity headers must be pure ASCII. Valid UTF-8, the
        latin-1 mojibake a lenient decoder would produce, and raw latin-1 are all refused."""
        utf8 = ("m" + chr(0xe9) + "mber").encode("utf-8")
        mojibake = utf8.decode("latin-1").encode("utf-8")
        latin1 = ("m" + chr(0xe9) + "mber").encode("latin-1")
        for label, raw_name in (("utf8", utf8), ("mojibake", mojibake), ("latin1", latin1)):
            headers = [(b"X-authentik-username", raw_name),
                       (b"X-authentik-groups", b"avrana-users|avrana-videos")]
            r = self.server.get("/account", headers)
            self.assertEqual(200, r.status, label)
            self.assertIn("<dt>Signed in</dt>", r.text, label)
            self.assertNotIn("<dt>Username</dt>", r.text, label)
            self.assertEqual(404, self.server.get("/watch", headers).status, label)
        self.assertEqual([], self.mock.paths())

    def test_non_ascii_display_name_is_shown_only_when_valid_utf8(self):
        base = [(USER, "member-a"), (GROUPS, "avrana-users")]
        good = self.server.get("/account", base + [(b"X-authentik-name", b"M" + chr(0xe9).encode("utf-8"))])
        self.assertIn("<dt>Name</dt><dd>M" + chr(0xe9) + "</dd>", good.text)
        bad = self.server.get("/account", base + [(b"X-authentik-name", b"M\xe9")])
        self.assertEqual(200, bad.status)
        self.assertIn("<dd>member-a</dd>", bad.text)
        self.assertNotIn("<dt>Name</dt>", bad.text)

    def test_oversized_header_block_is_refused_by_the_server_without_a_page(self):
        raw = (b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\nX-authentik-groups: "
               + b"g" * 70000 + b"\r\n\r\n")
        r = self.server.exchange(raw)
        self.assertIn(r.status, (400, 431, -1))
        self.assertNotIn("tile", r.text)

    def test_raw_byte_cases_fail_closed_over_a_socket(self):
        for name, headers in RAW_CASES.items():
            with self.subTest(case=name):
                self.assertEqual(404, self.get(headers, "/watch").status, name)
        self.assertEqual([], self.mock.paths())

    def test_server_spoof_headers_confer_nothing(self):
        for headers in (CASES["underscore_name_spoof"], CASES["forwarded_user_spoof"],
                        CASES["remote_user_spoof"], CASES["lookalike_names"]):
            self.assertEqual(404, self.get(headers, "/watch").status, headers)


if __name__ == "__main__":
    unittest.main()
