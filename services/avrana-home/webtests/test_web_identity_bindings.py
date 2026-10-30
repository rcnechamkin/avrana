"""RC1 finding S1: a username is accepted only as the Authentik user that holds it (identity_bindings.py).

Synthetic only: the HS256 secret is a fixture, tokens are minted here, `sub` values are invented. The scenarios are
the ones the S1 investigation found Home exposed to: a member deleted and a NEW Authentik user given the same name
(invitation or administrator rename) inheriting the old member's Jellyfin history, requests and profile; the file
seeded from Authentik (so the FIRST request of a recreated user is already refused); and the file missing, deleted
or broken (everyone refused, never reseeded). Offline: loopback only (the mock Jellyfin).
"""
import contextlib
import io
import json
import logging
import os
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from avrana_home import identity_bindings as ib
from avrana_home.app.settings import Settings, SettingsError

from .support import make_client, make_settings, require_framework
from .test_web_jwt_identity import AUD, ISS, JWT, JWT_ENV, SECRET, mint

A1, A2, B1 = "synthetic-sub-member-a", "synthetic-sub-member-a-RECREATED", "synthetic-sub-member-b"
B_GROUPS = ["avrana-users", "avrana-videos"]


class SettingsTests(unittest.TestCase):
    def test_needs_jwt_required_and_an_existing_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "identity_bindings.json")
            ok = Settings.from_mapping(dict(JWT_ENV, HOME_IDENTITY_MODE="jwt_required", HOME_IDENTITY_BINDINGS_FILE=path))
            self.assertEqual(path, ok.identity_bindings_file)
            for mode in ("jwt_log_only", None):
                env = dict(JWT_ENV, HOME_IDENTITY_BINDINGS_FILE=path)
                if mode:
                    env["HOME_IDENTITY_MODE"] = mode
                else:
                    env = {"HOME_IDENTITY_BINDINGS_FILE": path}
                with self.subTest(mode=mode), self.assertRaises(SettingsError):
                    Settings.from_mapping(env)
            with self.assertRaises(SettingsError):
                Settings.from_mapping(dict(JWT_ENV, HOME_IDENTITY_MODE="jwt_required",
                                           HOME_IDENTITY_BINDINGS_FILE=os.path.join(tmp, "missing", "b.json")))

    def test_off_by_default(self):
        self.assertEqual("", Settings.from_mapping(dict(JWT_ENV, HOME_IDENTITY_MODE="jwt_required")).identity_bindings_file)


class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_framework()
        from dev.mock_jellyfin import MockJellyfin
        cls.mock = MockJellyfin().start()
        cls.base = dict(home_sections=True, jellyfin_base_url=cls.mock.url, timeout=1.0, identity_mode="jwt_required",
                        jwt_issuer=ISS, jwt_audience=AUD, jwt_secret=SECRET)
        cls.unbound = make_client(make_settings(**cls.base))
        cls.unbound.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.unbound.__exit__(None, None, None)
        cls.mock.stop()

    def setUp(self):
        self.mock.reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "identity_bindings.json")
        # The owner's migration (init --seed): member-a is bound to the Authentik user that holds the name today.
        ib.write_state(self.path, ib.State("2026-10-29T00:00:00+00:00", {"member-a": ib.digest(A1)}, {}))
        self.client = make_client(make_settings(**self.base, identity_bindings_file=self.path))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.records = []
        test = self

        class Capture(logging.Handler):
            def emit(self, record):
                test.records.append(record)
        log, handler = logging.getLogger("avrana_home.app"), Capture(level=logging.DEBUG)
        old = log.level
        log.setLevel(logging.INFO)
        log.addHandler(handler)
        self.addCleanup(lambda: (log.removeHandler(handler), log.setLevel(old)))

    def as_(self, sub, user="member-a", groups=None):
        claims = {"sub": sub, "preferred_username": user}
        if groups:
            claims["groups"] = groups
        return [(JWT, mint(**claims))]

    def reasons(self):
        return [r.avrana_fields["reason"] for r in self.records if r.msg == "identity_jwt"]

    def release(self, name, jellyfin_names):
        def jf(method, path, body):
            return [{"Name": n, "Id": str(i)} for i, n in enumerate(jellyfin_names)]
        with contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()):
            code = ib.main(["--file", self.path, "release", name, "--other-apps-cleared"], env={},
                           senders=(jf, None, None))
        return code, err.getvalue()

    def test_a_seeded_member_sees_their_own_home(self):
        r = self.client.get("/home.json", headers=self.as_(A1))
        self.assertEqual(200, r.status_code)
        self.assertEqual(self.unbound.get("/home.json", headers=self.as_(A1)).json(), r.json())
        self.assertNotIn(A1, Path(self.path).read_text())          # only a digest of the sub is kept
        self.assertEqual(200, self.client.get("/home.json", headers=self.as_(A1)).status_code)   # same user again

    def test_a_member_who_joined_after_the_seed_binds_at_first_sign_in(self):
        self.assertEqual(200, self.client.get("/home.json", headers=self.as_(B1, "member-b", B_GROUPS)).status_code)
        self.assertEqual(ib.digest(B1), ib.read_state(self.path).bindings["member-b"])
        self.assertEqual(404, self.client.get("/home.json", headers=self.as_("other", "member-b", B_GROUPS)).status_code)

    def test_a_recreated_user_with_the_same_name_gets_nothing_of_the_old_members(self):
        # No earlier sign-in by the real member-a: the seed, not "whoever came first", decides.
        self.mock.reset()
        nobody = self.client.get("/").content
        for path in ("/", "/library", "/continue", "/me", "/account", "/search?q=Synthetic"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).content, self.client.get(path, headers=self.as_(A2)).content)
        self.assertEqual(404, self.client.get("/home.json", headers=self.as_(A2)).status_code)
        self.assertEqual(nobody, self.client.get("/", headers=self.as_(A2)).content)
        self.assertEqual([], self.mock.paths())                    # nothing of member-a's was asked for
        self.assertIn("identity_changed", self.reasons())
        self.assertFalse(any(A2 in repr(vars(r)) or A1 in repr(vars(r)) for r in self.records))
        self.assertEqual(200, self.client.get("/home.json", headers=self.as_(A1)).status_code)   # the real one still

    def test_a_letter_case_twin_of_a_bound_name_is_refused(self):
        self.assertEqual(404, self.client.get("/home.json", headers=self.as_(A2, "Member-A")).status_code)
        self.assertIn("name_reserved", self.reasons())
        self.assertNotIn("Member-A", ib.read_state(self.path).bindings)

    def test_another_member_is_unaffected(self):
        self.client.get("/", headers=self.as_(A1))
        r = self.client.get("/home.json", headers=self.as_(B1, "member-b", B_GROUPS))
        self.assertEqual(200, r.status_code)
        self.assertEqual(self.unbound.get("/home.json", headers=self.as_(B1, "member-b", B_GROUPS)).json(), r.json())

    def test_a_token_without_sub_is_refused_when_bindings_are_on(self):
        nobody = self.client.get("/").content
        self.assertEqual(nobody, self.client.get("/", headers=[(JWT, mint(sub=...))]).content)
        self.assertIn("no_subject", self.reasons())
        self.assertEqual(200, self.unbound.get("/home.json", headers=[(JWT, mint(sub=...))]).status_code)  # off: as before

    def test_release_is_refused_while_jellyfin_holds_the_name_then_lets_the_new_user_bind(self):
        self.client.get("/", headers=self.as_(A1))
        code, err = self.release("member-a", ["member-b", "MEMBER-A"])
        self.assertEqual((2, True), (code, "jellyfin still has an account" in err))
        self.assertEqual(404, self.client.get("/home.json", headers=self.as_(A2)).status_code)
        self.assertEqual(0, self.release("member-a", ["member-b"])[0])   # after offboard.py --purge
        self.assertEqual(200, self.client.get("/home.json", headers=self.as_(A2)).status_code)
        self.assertEqual(404, self.client.get("/home.json", headers=self.as_(A1)).status_code)   # now the old one is out

    def test_a_deleted_file_refuses_everyone_and_is_not_recreated(self):
        self.assertEqual(200, self.client.get("/home.json", headers=self.as_(A1)).status_code)
        os.unlink(self.path)
        for headers in (self.as_(A1), self.as_(A2), self.as_(B1, "member-b", B_GROUPS)):
            self.assertEqual(404, self.client.get("/home.json", headers=headers).status_code)
        self.assertFalse(os.path.exists(self.path))
        self.assertIn("bindings_unavailable", self.reasons())

    def test_a_never_initialised_file_refuses_everyone(self):
        os.unlink(self.path)
        with make_client(make_settings(**self.base, identity_bindings_file=self.path)) as fresh:
            self.assertEqual(404, fresh.get("/home.json", headers=self.as_(A1)).status_code)
        self.assertFalse(os.path.exists(self.path))

    def test_a_broken_file_refuses_everyone_until_it_is_good_again(self):
        self.client.get("/", headers=self.as_(A1))
        good = Path(self.path).read_text()
        Path(self.path).write_text("{not json")
        self.assertEqual(404, self.client.get("/home.json", headers=self.as_(A1)).status_code)
        self.assertEqual(404, self.client.get("/home.json", headers=self.as_(B1, "member-b", B_GROUPS)).status_code)
        self.assertIn("bindings_unavailable", self.reasons())
        Path(self.path).write_text(good)
        self.assertEqual(200, self.client.get("/home.json", headers=self.as_(A1)).status_code)


class WarmCacheBindingTests(unittest.TestCase):
    """T-09: the member A1 warms every cache and store Home keeps for them, THEN the recreated user A2 (same username,
    different sub) presents on every route that holds member data. Each answer must be exactly the signed-out one,
    nothing may be asked of any upstream for A2, and nothing of A1's may appear in a body."""

    MARK_NAME = "Aurelia Q Markerson"
    GETS = ("/", "/library", "/continue", "/home.json", "/search?q=Synthetic", "{title}", "{art}", "/me", "/me/tv",
            "/me/profile", "/me/avatar", "/me/home", "/request/watch?q=film", "/request/mine")
    FORM = [("Content-Type", "application/x-www-form-urlencoded"), ("Sec-Fetch-Site", "same-origin")]

    @classmethod
    def setUpClass(cls):
        require_framework()
        from dev.mock_jellyfin import MockJellyfin
        cls.mock = MockJellyfin().start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        from fastapi.testclient import TestClient
        from avrana_home.app.main import create_app
        from avrana_home.memberstore import MemberStore
        from avrana_home.requests.seerr import SeerrRequests
        from avrana_home.resilience import TransportResponse
        from .support import PeerOverride
        from .test_web_watch_requests import FakeSeerr
        self.mock.reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = os.path.join(self.tmp.name, "identity_bindings.json")
        ib.write_state(path, ib.State("2026-10-29T00:00:00+00:00", {"member-a": ib.digest(A1)}, {}))
        self.store = MemberStore(Path(self.tmp.name) / "members.sqlite3")
        self.addCleanup(self.store.close)
        # Stored bytes are served as they are; a recognisable WebP-shaped blob stands in for the re-encoded photo (no PIL here).
        self.photo = b"RIFF\x24\x00\x00\x00WEBPVP8 SYNTHETIC-PHOTO-OF-MEMBER-A-0123456789"
        self.assertEqual("saved", self.store.save_avatar("member-a", self.photo, 0)[0])
        self.assertEqual("saved", self.store.save_name("member-a", self.MARK_NAME, 1)[0])
        self.assertEqual("saved", self.store.save_home("member-a", "watch", ("books",),
                                                       ("new", "continue", "released"), 0))

        class Seerr(FakeSeerr):                # member-a's Jellyfin id (the mock's fixture) is Seerr user 5
            def request(self, method, path, query, timeout, max_bytes, **kw):
                if path == "/api/v1/user":
                    self.calls.append((method, path, dict(query or {}), None, None))
                    users = {"pageInfo": {}, "results": [
                        {"id": 5, "permissions": 32, "jellyfinUserId": "aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa"}]}
                    return TransportResponse(200, json.dumps(users).encode())
                return super().request(method, path, query, timeout, max_bytes, **kw)
        self.seerr = Seerr()
        base = dict(home_sections=True, jellyfin_base_url=self.mock.url, timeout=1.0, identity_mode="jwt_required",
                    jwt_issuer=ISS, jwt_audience=AUD, jwt_secret=SECRET, watch_requests=True,
                    seerr_base_url="http://127.0.0.1:1")
        app = create_app(make_settings(**base, identity_bindings_file=path), member_store=self.store,
                         watch_requests=SeerrRequests(self.seerr, timeout=1.0))
        self.client = TestClient(PeerOverride(app, ("203.0.113.7", 50000)), base_url="http://portal.test",
                                 follow_redirects=False, raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.records = []
        test = self

        class Capture(logging.Handler):
            def emit(self, record):
                test.records.append(record)
        log, handler = logging.getLogger("avrana_home.app"), Capture(level=logging.DEBUG)
        old = log.level
        log.setLevel(logging.INFO)
        log.addHandler(handler)
        self.addCleanup(lambda: (log.removeHandler(handler), log.setLevel(old)))

    def as_(self, sub, user="member-a"):
        return [(JWT, mint(sub=sub, preferred_username=user))]

    def routes(self, home_html):
        title = re.search(r'href="(/title/jellyfin/[0-9a-f]+)"', home_html).group(1)
        art = re.search(r'(?:src|href)="(/art/jellyfin/[a-z]+/[0-9a-f]+)"', home_html).group(1)
        return [p.format(title=title, art=art) for p in self.GETS]

    @staticmethod
    def titles_in(doc):
        found, stack = set(), [doc]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                found.update(v for k, v in node.items() if k in ("title", "name") and isinstance(v, str) and v)
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        return found

    def test_a_warm_cache_never_serves_the_recreated_user(self):
        # 1. A1 warms everything, for real.
        a1 = self.as_(A1)
        routes = self.routes(self.client.get("/", headers=a1).text)
        warm = {}
        for path in routes:
            r = self.client.get(path, headers=a1)
            if path != "/request/mine":        # My requests needs a Seerr list the fake does not serve: only probed
                self.assertEqual(200, r.status_code, path)
            warm[path] = r
        self.assertEqual(self.photo, warm["/me/avatar"].content)
        self.assertIn(self.MARK_NAME, warm["/me/profile"].text)
        titles = self.titles_in(warm["/home.json"].json())
        self.assertTrue(titles, "A1's home.json carries titles to look for")
        self.assertIn("Synthetic Film", warm["/request/watch?q=film"].text)
        form = re.search(r'<form method="post" action="/request/watch"[^>]*>(.*?)</form>',
                         warm["/request/watch?q=film"].text, re.S)
        fields = dict(re.findall(r'name="([a-z_]+)" value="([^"]*)"', form.group(1)))
        self.assertIn("token", fields)

        # 2. The signed-out answers, for comparison (no identity at all).
        nobody = {p: self.client.get(p) for p in routes}
        for path in ("/home.json", "/me/avatar", "/me/profile", "/me/tv", "/me/home", "/request/watch?q=film"):
            self.assertEqual(404, nobody[path].status_code, path)          # the catalogue's signed-out answer
        watch_body = urlencode(fields)
        nobody_watch = self.client.post("/request/watch", content=watch_body, headers=self.FORM)
        nobody_signout = self.client.post("/signout", content="", headers=self.FORM)
        nobody_tv = self.client.post("/me/tv", content="t=x&code=123456", headers=self.FORM)
        self.assertEqual((404, 501, 501), (nobody_watch.status_code, nobody_signout.status_code, nobody_tv.status_code))
        self.mock.reset()
        self.seerr.calls.clear()

        # 3. A2: the same username, a different sub.
        a2 = self.as_(A2)
        bodies = []
        for path in routes:
            with self.subTest(path=path):
                r = self.client.get(path, headers=a2)
                bodies.append((path, r.content))          # collected first: step 5 stands on its own
                self.assertEqual((nobody[path].status_code, nobody[path].content), (r.status_code, r.content), path)
        for label, target, body, ref in (("POST /request/watch", "/request/watch", watch_body, nobody_watch),
                                         ("POST /signout", "/signout", "", nobody_signout),
                                         ("POST /me/tv", "/me/tv", "t=x&code=123456", nobody_tv)):
            with self.subTest(label):
                r = self.client.post(target, content=body, headers=self.FORM + a2)    # /request/watch: A1's own form
                bodies.append((label, r.content))
                self.assertEqual((ref.status_code, ref.content), (r.status_code, r.content), label)

        # 4. Nothing was asked of any upstream, nothing approved, no request written.
        self.assertEqual([], self.mock.paths())
        self.assertEqual([], self.mock.approvals)
        self.assertEqual([], self.seerr.calls)

        # 5. None of A1's titles, ids, photo or preferences in any A2 body.
        ids = {m for p in routes for m in re.findall(r"[0-9a-f]{32}", p)}
        seerr_titles = {"Synthetic Film", "Asked Film"}
        for path, body in bodies:
            text = body.decode("utf-8", "replace")
            baseline = nobody.get(path)
            for mark in sorted(titles | seerr_titles | ids | {self.MARK_NAME}):
                if baseline is not None and mark in baseline.text:
                    continue                    # the signed-out page itself says it (for example an echoed search term)
                self.assertNotIn(mark, text, f"{path}: {mark}")
            self.assertNotIn(self.photo, body, path)
            self.assertNotIn(b"/me/avatar?v=", body, path)

        # 6. The refusal is the binding's own, and the real A1 is unharmed by it.
        reasons = [r.avrana_fields["reason"] for r in self.records if r.msg == "identity_jwt"]
        self.assertIn("identity_changed", reasons)
        self.assertEqual(200, self.client.get("/home.json", headers=a1).status_code)
        self.assertEqual(self.photo, self.client.get("/me/avatar", headers=a1).content)


if __name__ == "__main__":
    unittest.main()
