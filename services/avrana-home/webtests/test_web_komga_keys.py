"""Tier B: S-01 through the HTTP layer. The Komga key intake (`PUT /internal/komga-key/<subject>`, app/intake.py) and
Me -> Comics (app/comics.py): auth, network rule, idempotency, size limit, CSRF, and that no key or password ever
appears in a response or a log line. Synthetic accounts; the fake Komga is an in-process opener (no sockets)."""
import ipaddress
import json
import logging
import os
import tempfile
import unittest

from .support import GROUPS, USER, PeerOverride, make_settings, require_framework

require_framework()

from avrana_home.adapters.komga import KomgaAdapter  # noqa: E402
from avrana_home.identity_bindings import digest  # noqa: E402
from avrana_home.komga_keys import KomgaKeyClient  # noqa: E402
from avrana_home.member_keys import MemberKeyStore, read_keys, write_keys  # noqa: E402
from avrana_home.resilience import UrllibTransport  # noqa: E402

from .support import HOME, _load  # noqa: E402

# Loaded by path: importing the `tests` package would install its socket guard in this process (webtests need loopback).
FakeKeyKomga = _load("fake_komga_keys_for_web", HOME / "tests" / "fake_komga_keys.py").FakeKeyKomga
NOWHERE = "http://127.0.0.1:9"          # the shared and member reads are never reached by these pages

TOKEN = "i" * 40
INSIDE = ("172.30.0.5", 40000)
OUTSIDE = ("203.0.113.7", 40000)
SUBJECT = digest("synthetic-sub-new-member")
ALICE = [(USER, "alice"), (GROUPS, "avrana-users|avrana-comics"), ("X-authentik-email", "Alice@Example.com")]
NO_COMICS = [(USER, "carol"), (GROUPS, "avrana-users|avrana-videos"), ("X-authentik-email", "carol@example.com")]
SAME = {"Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": "same-origin"}


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(f"{record.getMessage()} {vars(record)!r}")


class Fixture(unittest.TestCase):
    intake = True
    connect = True

    def setUp(self):
        from fastapi.testclient import TestClient
        from avrana_home.app.main import create_app
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "komga_member_keys")
        write_keys(self.path, {})
        self.store = MemberKeyStore(self.path, writable=True)
        self.komga = FakeKeyKomga()
        adapter = KomgaAdapter(UrllibTransport(NOWHERE, {"X-API-Key": "x"}), owner_confirms_no_member_restrictions=True,
                               member_keys=self.store,
                               member_transport=lambda key: UrllibTransport(NOWHERE, {"X-API-Key": key}))
        settings = make_settings(home_sections=True, komga_base_url="http://komga.test",
                                 key_intake_token=TOKEN if self.intake else "",
                                 internal_cidrs=(ipaddress.ip_network("172.30.0.0/16"),) if self.intake else (),
                                 komga_connect=self.connect)
        self.app = create_app(settings, adapters=[adapter],
                              komga_key_client=KomgaKeyClient("http://komga.test", opener=self.komga))
        adapter.cache = self.app.state.cache
        self.clients = {}
        for name, peer in (("inside", INSIDE), ("outside", OUTSIDE)):
            self.clients[name] = TestClient(PeerOverride(self.app, peer), base_url="http://portal.test",
                                            follow_redirects=False, raise_server_exceptions=False)
        self.cap = Capture()
        for name in ("avrana_home", "uvicorn"):
            logging.getLogger(name).addHandler(self.cap)
            self.addCleanup(logging.getLogger(name).removeHandler, self.cap)
        logging.getLogger("avrana_home").setLevel(logging.DEBUG)

    def put(self, body, subject=SUBJECT, token=TOKEN, peer="inside", headers=None, raw=None):
        h = {"Content-Type": "application/json"}
        if token is not None:
            h["Authorization"] = "Bearer " + token
        h.update(headers or {})
        data = raw if raw is not None else json.dumps(body).encode()
        return self.clients[peer].put("/internal/komga-key/" + subject, content=data, headers=h)

    def logs(self):
        return "\n".join(self.cap.lines)


class IntakeTests(Fixture):
    def test_a_good_put_files_the_key_under_its_komga_account_and_is_idempotent(self):
        key, kid = self.komga.mint_for("U2")
        r = self.put({"key": key, "key_id": kid, "source": "enrollment"})
        self.assertEqual((r.status_code, r.content), (204, b""))
        self.assertEqual(dict(read_keys(self.path)), {"bob@example.com": key})
        r = self.put({"key": key, "key_id": kid, "source": "enrollment"})
        self.assertEqual((r.status_code, r.content), (204, b""))
        key2, kid2 = self.komga.mint_for("U2")
        self.assertEqual(self.put({"key": key2, "key_id": kid2, "source": "enrollment"}).status_code, 204)
        self.assertEqual(dict(read_keys(self.path)), {"bob@example.com": key2})
        self.assertIn(key, [k["key"] for k in self.komga.keys["U2"]])      # replaced here, nothing revoked remotely
        for secret in (key, key2, SUBJECT, TOKEN, "bob@"):
            self.assertNotIn(secret, self.logs())
        self.assertIn("komga_key_intake", self.logs())

    def test_auth_failures_are_401_and_file_nothing(self):
        key, _ = self.komga.mint_for("U2")
        for token in (None, "", "x" * 40, TOKEN + "x", TOKEN[:-1]):
            with self.subTest(token=token):
                r = self.put({"key": key, "source": "enrollment"}, token=token)
                self.assertEqual((r.status_code, r.content), (401, b""))
        r = self.put({"key": key, "source": "enrollment"}, token=None, headers={"Authorization": "Basic " + TOKEN})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(read_keys(self.path), ())
        self.assertNotIn(TOKEN, self.logs())

    def test_outside_the_docker_network_or_through_the_proxy_it_is_the_plain_501(self):
        key, _ = self.komga.mint_for("U2")
        cases = ({"peer": "outside"}, {"headers": {"X-Forwarded-For": "203.0.113.7"}},
                 {"headers": {"X-authentik-username": "alice"}}, {"headers": {"Forwarded": "for=1.2.3.4"}})
        for kw in cases:
            with self.subTest(kw=kw):
                r = self.put({"key": key, "source": "enrollment"}, **kw)
                self.assertEqual(r.status_code, 501)
                self.assertNotIn(b"komga", r.content.lower())
        self.assertEqual(read_keys(self.path), ())

    def test_body_rules(self):
        key, _ = self.komga.mint_for("U2")
        too_big = json.dumps({"key": key, "source": "enrollment", "key_id": "k" * 600}).encode()
        self.assertEqual(self.put(None, raw=too_big).status_code, 413)
        self.assertEqual(self.put({"key": key, "source": "enrollment"},
                                  headers={"Content-Type": "text/plain"}).status_code, 415)
        for body in ({"key": key}, {"key": key, "source": "owner"}, {"key": key, "source": "enrollment", "x": 1},
                     [key], {"key": 5, "source": "enrollment"}):
            with self.subTest(body=body):
                self.assertEqual(self.put(body).status_code, 400)
        self.assertEqual(self.put(None, raw=b"{not json").status_code, 400)
        self.assertEqual(self.put({"key": "9" * 32, "source": "enrollment"}).status_code, 422)   # Komga refuses it
        self.assertEqual(self.put({"key": key, "source": "enrollment"}, subject="ABC").status_code, 404)
        self.assertEqual(read_keys(self.path), ())

    def test_unknown_subject_is_refused_unless_enrollment(self):
        key, _ = self.komga.mint_for("U2")
        self.assertEqual(self.put({"key": key, "source": "connect"}).status_code, 403)
        self.assertEqual(read_keys(self.path), ())

    def test_komga_down_is_503(self):
        key, _ = self.komga.mint_for("U2")
        self.komga.down = True
        self.assertEqual(self.put({"key": key, "source": "enrollment"}).status_code, 503)

    def test_other_methods_and_paths_stay_501(self):
        c = self.clients["inside"]
        h = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}
        self.assertEqual(c.post("/internal/komga-key/" + SUBJECT, content=b"{}", headers=h).status_code, 501)
        self.assertEqual(c.put("/internal/komga-key/" + SUBJECT + "/x", content=b"{}", headers=h).status_code, 501)
        self.assertEqual(c.put("/me", content=b"{}", headers=h).status_code, 501)
        self.assertEqual(c.get("/internal/komga-key/" + SUBJECT).status_code, 404)


class IntakeOff(Fixture):
    intake = False

    def test_without_the_token_every_put_is_501(self):
        key, _ = self.komga.mint_for("U2")
        self.assertEqual(self.put({"key": key, "source": "enrollment"}).status_code, 501)


class MeComicsDisconnect(Fixture):
    def page(self, headers=ALICE, query=""):
        return self.clients["outside"].get("/me/comics" + query, headers=dict(headers))

    def token(self):
        return self.app.state.form_tokens.issue("comics", "alice")

    def post(self, body, headers=ALICE, site="same-origin"):
        h = dict(dict(headers), **dict(SAME, **{"Sec-Fetch-Site": site}))
        return self.clients["outside"].post("/me/comics", content=body.encode(), headers=h)

    def test_me_shows_the_comics_row_only_to_comics_members(self):
        me = self.clients["outside"].get("/me", headers=dict(ALICE))
        self.assertIn("/me/comics", me.text)
        self.assertIn("Not connected", me.text)
        self.assertNotIn("/me/comics", self.clients["outside"].get("/me", headers=dict(NO_COMICS)).text)
        self.assertEqual(self.page(NO_COMICS).status_code, 404)

    def test_disconnect_revokes_in_komga_and_drops_the_key(self):
        key, kid = self.komga.mint_for("U1")
        self.store.put("alice@example.com", key, kid)
        page = self.page()
        self.assertIn("Disconnect", page.text)
        self.assertNotIn(key, page.text)
        r = self.post(f"t={self.token()}&do=disconnect")
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/me/comics?r=disconnected"))
        self.assertEqual(read_keys(self.path), ())
        self.assertEqual(self.komga.comments("U1"), ["phone"])
        self.assertIn("Comics disconnected", self.page(query="?r=disconnected").text)
        self.assertNotIn(key, self.logs())

    def test_komga_down_still_disconnects_here_and_says_how_to_finish(self):
        key, kid = self.komga.mint_for("U1")
        self.store.put("alice@example.com", key, kid)
        self.komga.down = True
        r = self.post(f"t={self.token()}&do=disconnect")
        self.assertEqual(r.headers["location"], "/me/comics?r=disconnected_here")
        self.assertEqual(read_keys(self.path), ())
        self.assertIn("avrana-home", self.page(query="?r=disconnected_here").text)

    def test_csrf_and_token_locks(self):
        key, kid = self.komga.mint_for("U1")
        self.store.put("alice@example.com", key, kid)
        self.assertEqual(self.post(f"t={self.token()}&do=disconnect", site="cross-site").status_code, 403)
        self.assertEqual(self.post("t=1.abc&do=disconnect").headers["location"], "/me/comics?r=expired")
        self.assertEqual(self.post(f"t={self.token()}&do=other").status_code, 400)
        self.assertEqual(self.post(f"t={self.token()}&do=disconnect&evil=1").status_code, 400)
        self.assertEqual(self.post(f"t={self.token()}&do=disconnect", headers=NO_COMICS).status_code, 501)
        self.assertEqual(dict(read_keys(self.path)), {"alice@example.com": key})

    def test_nothing_to_disconnect(self):
        r = self.post(f"t={self.token()}&do=disconnect")
        self.assertEqual(r.headers["location"], "/me/comics?r=not_connected")


class ConnectOff(Fixture):
    connect = False

    def test_without_the_switch_me_comics_does_not_exist(self):
        c = self.clients["outside"]
        self.assertEqual(c.get("/me/comics", headers=dict(ALICE)).status_code, 404)
        self.assertEqual(c.post("/me/comics", content=b"do=disconnect", headers=dict(dict(ALICE), **SAME)).status_code,
                         501)
        self.assertNotIn("/me/comics", c.get("/me", headers=dict(ALICE)).text)


if __name__ == "__main__":
    unittest.main()
