"""Tier A: the owner-run capture tool (tools/capture_upstreams.py). Offline: a 127.0.0.1 stub server only.

Everything here is synthetic. The sentinel strings below stand in for credentials, e-mail addresses,
usernames, hosts and paths; the tests prove they never reach the output, the printed text or a request
that the adapters would not make. No real server, account or credential is involved.
"""
import importlib.util
import io
import json
import re
import socketserver
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("capture_upstreams", HOME / "tools" / "capture_upstreams.py")
cap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cap)

JF_KEY, ABS_TOKEN, KOMGA_TOKEN = "SENTINEL-JF-KEY-9f3a1c", "SENTINEL-ABS-TOKEN-7d2e5b", "SENTINEL-KG-TOKEN-4b8c0e"
CW_USER, CW_PASS = "viewer-sentinel", "SENTINEL-CW-PASS-3e6a9d"
JF_ALICE, JF_BOB, JF_OWNER = "a1b2c3d4e5f60718293a4b5c6d7e8f90", "b1b2c3d4e5f60718293a4b5c6d7e8f91", "c1b2c3d4e5f60718293a4b5c6d7e8f92"
JF_ITEM = "d1b2c3d4e5f60718293a4b5c6d7e8f93"
ABS_ALICE, ABS_BOB = "11111111-2222-3333-4444-555555555501", "11111111-2222-3333-4444-555555555502"
ABS_ITEM = "li_abcdef123456"
KG_USER, KG_BOOK, KG_SERIES = "KGUSER123456", "KGBOOK123456", "KGSERI123456"
EMAIL = "alice.secret@private-domain.example"

OPDS = ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
        '<title>Secret Catalogue</title><id>urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</id>'
        '<entry><title>Secret Book</title><author><name>Jane Secret</name></author>'
        '<link rel="http://opds-spec.org/image/thumbnail" href="/opds/thumb_cover/42"/>'
        '<link rel="enclosure" href="http://media.private-domain.example/opds/download/42/epub/"/>'
        '<content>Mailed to alice.secret@private-domain.example from 10.1.2.3</content></entry></feed>')
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32

BODIES = {
    "/Users": [{"Name": "alice", "Id": JF_ALICE, "Policy": {"IsDisabled": False}},
               {"Name": "bob", "Id": JF_BOB, "Policy": {"IsDisabled": False}},
               {"Name": "owner1", "Id": JF_OWNER, "Policy": {"IsDisabled": False}}],
    "/UserItems/Resume": {"Items": [{"Id": JF_ITEM, "Name": "Secret Film", "Type": "Movie",
                                     "Path": "/data/movies/Secret Film.mkv", "AccessToken": "SENTINEL-LEAK-1",
                                     "UserData": {"PlaybackPositionTicks": 5, "Key": "abc", "UserId": JF_ALICE}}],
                          "TotalRecordCount": 1},
    "/Items/Latest": [{"Id": JF_ITEM, "Name": "Secret Film", "Type": "Movie", "ImageTags": {"Primary": "0f" * 16}}],
    "/Items": {"Items": [{"Id": JF_ITEM, "Name": "Secret Film", "Type": "Movie",
                          "Overview": f"Seen by alice at 10.1.2.3 mail {EMAIL}"}]},
    f"/Items/{JF_ITEM}/Images/Primary": PNG,
    "/api/users": {"users": [{"id": ABS_ALICE, "username": "alice", "token": "SENTINEL-ABS-USERTOKEN"},
                             {"id": ABS_BOB, "username": "bob", "token": "SENTINEL-ABS-USERTOKEN2"}]},
    f"/api/users/{ABS_ALICE}": {"id": ABS_ALICE, "username": "alice", "token": "SENTINEL-ABS-USERTOKEN",
                                "mediaProgress": [{"libraryItemId": ABS_ITEM, "userId": ABS_ALICE, "progress": 0.5}]},
    f"/api/items/{ABS_ITEM}": {"id": ABS_ITEM, "libraryId": "lib_secret1", "mediaType": "book",
                               "path": "/audiobooks/Secret Author/Secret Book",
                               "media": {"metadata": {"title": "Secret Book", "authorName": "Jane Secret", "explicit": False}}},
    "/api/v2/users": [{"id": KG_USER, "email": EMAIL, "sharedAllLibraries": True}],
    "/api/v1/books/latest": {"content": [{"id": KG_BOOK, "seriesId": KG_SERIES, "name": "Secret Comic",
                                          "url": "/data/comics/Secret Comic.cbz"}]},
    f"/api/v1/books/{KG_BOOK}": {"id": KG_BOOK, "seriesId": KG_SERIES, "name": "Secret Comic",
                                 "url": "/data/comics/Secret Comic.cbz", "number": 3},
    f"/api/v1/series/{KG_SERIES}": {"id": KG_SERIES, "libraryId": "KGLIB1234567", "metadata": {"title": "Secret Series"}},
    f"/api/v1/books/{KG_BOOK}/thumbnail": PNG,
    "/opds/new": OPDS,
    "/opds/thumb_cover/42": PNG,
}
EXPECT_AUTH = {
    "/Users": f'MediaBrowser Token="{JF_KEY}"', "/UserItems/Resume": f'MediaBrowser Token="{JF_KEY}"',
    "/Items/Latest": f'MediaBrowser Token="{JF_KEY}"', "/Items": f'MediaBrowser Token="{JF_KEY}"',
}


class _Server(ThreadingHTTPServer):
    def server_bind(self):                    # the stock one calls getfqdn(), which these tests forbid
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


class Stub:
    """A loopback server. `hits` records (method, path, query, has_auth_ok)."""

    def __init__(self, overrides=None, redirect_users=False):
        stub = self
        self.hits = []
        self.overrides = overrides or {}
        self.redirect_users = redirect_users

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _serve(self):
                path, _, query = self.path.partition("?")
                auth = self.headers.get("Authorization", "") + "|" + self.headers.get("X-API-Key", "")
                good = any(t in auth for t in (JF_KEY, ABS_TOKEN, KOMGA_TOKEN)) or "Basic" in auth
                stub.hits.append((self.command, path, query, good))
                if stub.redirect_users and path == "/api/v2/users":
                    self.send_response(302)
                    self.send_header("Location", "/redirect-target")
                    self.end_headers()
                    return
                if not good:
                    self.send_response(401)
                    self.end_headers()
                    return
                body = stub.overrides.get(path, BODIES.get(path))
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if isinstance(body, bytes):
                    ctype, data = "image/png", body
                elif isinstance(body, str):
                    ctype, data = "application/atom+xml", body.encode()
                else:
                    ctype, data = "application/json", json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _serve

        self.server = _Server(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def env(self, **extra):
        env = {"AVRANA_CAPTURE_JELLYFIN_URL": self.url, "AVRANA_CAPTURE_JELLYFIN_KEY": JF_KEY,
               "AVRANA_CAPTURE_AUDIOBOOKSHELF_URL": self.url, "AVRANA_CAPTURE_AUDIOBOOKSHELF_TOKEN": ABS_TOKEN,
               "AVRANA_CAPTURE_KOMGA_URL": self.url, "AVRANA_CAPTURE_KOMGA_TOKEN": KOMGA_TOKEN,
               "AVRANA_CAPTURE_CALIBRE_WEB_URL": self.url, "AVRANA_CAPTURE_CALIBRE_WEB_USER": CW_USER,
               "AVRANA_CAPTURE_CALIBRE_WEB_PASSWORD": CW_PASS}
        env.update(extra)
        return env


def run(argv, env):
    out, err = io.StringIO(), io.StringIO()
    code = cap.main(argv, env=env, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def outputs(d):
    return {p.name: p.read_text(encoding="utf-8") for p in Path(d).iterdir()}


SENTINELS = [JF_KEY, ABS_TOKEN, KOMGA_TOKEN, CW_PASS, CW_USER, "SENTINEL-LEAK-1", "SENTINEL-ABS-USERTOKEN",
             EMAIL, "private-domain.example", "10.1.2.3", "127.0.0.1", "/data/", "/audiobooks/", "Secret",
             "alice", "bob", JF_ALICE, JF_ITEM, ABS_ITEM, ABS_ALICE, KG_BOOK, KG_USER]


class RedactionUnits(unittest.TestCase):
    def red(self, **kw):
        return cap.Redactor(kw.pop("secrets", ["TOPSECRETVALUE1"]), kw.pop("hosts", ["media.example.org"]),
                            kw.pop("own", "owner1"), kw.pop("users", ["alice", "bob"]))

    def test_secrets_and_credential_shapes(self):
        r = self.red()
        text = ('Authorization: Bearer abcdef123456 and MediaBrowser Token="zzz999xxx" and Basic dXNlcjpwYXNz '
                'plus ?api_key=hunter22 &token=abc123 and TOPSECRETVALUE1 end')
        out = r.redact_text(text)
        for bad in ("abcdef123456", "zzz999xxx", "dXNlcjpwYXNz", "hunter22", "abc123", "TOPSECRETVALUE1"):
            self.assertNotIn(bad, out)
        self.assertEqual([], cap.scan_for_secrets(out, ["TOPSECRETVALUE1"]))

    def test_sensitive_keys_by_name_but_not_booleans(self):
        out = self.red().redact_json({"AccessToken": "x1", "session": {"a": "b"}, "HasPassword": True,
                                      "apiKey": "k2", "Key": "k3", "note": "fine"})
        self.assertEqual("[REDACTED]", out["AccessToken"])
        self.assertEqual("[REDACTED]", out["apiKey"])
        self.assertEqual("[REDACTED]", out["Key"])
        self.assertIs(True, out["HasPassword"])
        self.assertEqual("fine", out["note"])

    def test_emails_are_consistent_and_gone(self):
        r = self.red()
        a = r.redact_text("Mail Bob.Smith@Example.COM and bob.smith@example.com")
        self.assertNotIn("example.com", a.lower())
        self.assertEqual(1, len(set(re.findall(r"user\d+@example\.invalid", a))))

    def test_usernames_other_than_owner(self):
        r = self.red()
        out = r.redact_json({"Name": "alice"}, users_route=True)
        self.assertRegex(out["Name"], r"member-[a-z]")
        self.assertEqual("owner1", r.redact_json({"Name": "owner1"}, users_route=True)["Name"])
        text = r.redact_text("alice watched with Alice and owner1 and bob")
        self.assertNotIn("alice", text.lower())
        self.assertIn("owner1", text)
        self.assertNotIn("bob", text)

    def test_hosts_ips_and_urls(self):
        r = self.red()
        out = r.redact_text("see https://watch.private.example/web/#/x and media.example.org and 192.168.1.20 "
                            "and fe80::1ff:fe23:4567:890a and http://10.0.0.5:8096/Users")
        for bad in ("private.example", "media.example.org", "192.168.1.20", "fe80", "10.0.0.5"):
            self.assertNotIn(bad, out)
        self.assertIn("host.invalid", out)

    def test_file_paths(self):
        r = self.red()
        out = r.redact_json({"path": "/data/movies/a.mkv", "File": "C:\\Media\\a.mkv",
                             "note": "stored at /mnt/user/media/x and \\\\nas\\share\\y"})
        self.assertEqual("[path]", out["path"])
        self.assertNotIn("Media", out["note"] + out["File"])
        self.assertNotIn("/mnt", out["note"])
        self.assertNotIn("nas", out["note"])
        # an API route is NOT a file path
        self.assertEqual("/api/v1/books/abc", r.redact_text("/api/v1/books/abc"))

    def test_ids_titles_consistent_and_shape_kept(self):
        r = self.red()
        body = {"Id": JF_ITEM, "Name": "Secret Film", "SeriesId": JF_ITEM, "Overview": "x"}
        out = r.redact_json(body)
        self.assertRegex(out["Id"], r"^[0-9a-f]{32}$")
        self.assertEqual(out["Id"], out["SeriesId"])
        self.assertNotEqual(JF_ITEM, out["Id"])
        self.assertEqual("Title 1", out["Name"])
        self.assertEqual("Title 1", r.redact_json({"name": "Secret Film"})["name"])
        self.assertEqual(out["Id"], r.redact_text(f"/Items/{JF_ITEM}/Images/Primary").split("/")[2])
        self.assertEqual([], cap.scan_for_secrets(json.dumps(out)))

    def test_xml_titles_and_ids(self):
        r = self.red()
        r.learn([cap.Capture("calibre-web", "new", "/opds/new", cap.Response(200, OPDS.encode(), "x"), "xml")])
        out = r.redact_xml(OPDS)
        for bad in ("Secret", "Jane", "alice.secret", "10.1.2.3", "private-domain", "aaaaaaaa-bbbb"):
            self.assertNotIn(bad, out)
        self.assertIn("/opds/thumb_cover/42", out)           # numeric book id kept: shape evidence
        self.assertEqual([], cap.scan_for_secrets(out))


class FinalScan(unittest.TestCase):
    def test_each_pattern_is_caught(self):
        samples = {
            "email": "x a@b.example y", "ipv4": "at 8.8.4.4 now", "bearer-or-basic": "Bearer abcdefgh1234",
            "auth-token": 'Token="abcd1234"', "credential-parameter": '"password": "hunter22"',
            "private-key": "-----BEGIN RSA " + "PRIVATE KEY-----", "host-in-url": "https://real.example/x",
            "windows-path": "C:\\\\Users\\\\me", "unix-path": "in /home/me/x", "long-token": "k " + "Ab3" * 12}
        for name, text in samples.items():
            self.assertIn(name, cap.scan_for_secrets(text), name)

    def test_literal_secret_and_host(self):
        self.assertIn("literal-secret", cap.scan_for_secrets("abc SECRETVAL xyz", ["SECRETVAL"]))
        self.assertIn("configured-host", cap.scan_for_secrets("abc Media.Example.Org", [], ["media.example.org"]))

    def test_clean_text_passes(self):
        text = json.dumps({"Id": "0" * 31 + "1", "Name": "Title 1", "u": "member-a", "h": "https://host.invalid/x",
                           "api": "/api/v1/books/ID00000001", "e": "user1@example.invalid", "tok": "[REDACTED]"})
        self.assertEqual([], cap.scan_for_secrets(text))

    def test_a_file_that_still_matches_is_refused_not_written(self):
        leak = "Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0LmNb"        # secret-like, under an innocent key
        resp = cap.Response(200, json.dumps({"Items": [{"Id": JF_ITEM, "Note": leak}]}).encode(), "application/json")
        c = cap.Capture("jellyfin", "items", "/Items", resp, "json")
        files, manifest, refused = cap.build_outputs([c], cap.Redactor([], [], "", []))
        self.assertEqual({}, files)
        self.assertEqual(1, len(refused))
        self.assertIn("long-token", refused[0])
        self.assertNotIn(leak, refused[0])
        self.assertIsNone(manifest[0]["file"])


class Guards(unittest.TestCase):
    def test_base_url_rules(self):
        for bad in ("ftp://x.example", "http://media.example", "https://" + "who:what" + "@media.example",
                    "https://media.example/?k=v", "media.example", "https://"):
            with self.assertRaises(cap.CaptureError, msg=bad):
                cap.validate_base_url(bad)
        self.assertEqual("https://media.example/sub", cap.validate_base_url("https://media.example/sub/"))
        self.assertEqual("http://127.0.0.1:8096", cap.validate_base_url("http://127.0.0.1:8096"))
        self.assertEqual("http://media.example", cap.validate_base_url("http://media.example", True))

    def test_credentials_are_never_arguments(self):
        for flag in ("--token", "--api-key", "--password", "--url", "--key"):
            with self.assertRaises(SystemExit):
                cap.parse_args([flag, "x"])

    def test_the_tool_only_requests_what_the_adapters_allow(self):
        with Stub() as stub:
            c = cap.Client("jellyfin", stub.url, {}, 2.0)
            for path, q, bound in [("/Sessions", None, None), ("/Users/Me", None, None),
                                   ("/Items/" + JF_ITEM + "/Download", None, JF_ALICE),
                                   ("/UserItems/Resume", {"userId": JF_ALICE}, None),
                                   ("/UserItems/Resume", {"userId": JF_ALICE, "evil": "1"}, JF_ALICE)]:
                with self.assertRaises(cap.CaptureError, msg=path):
                    c.get(path, q, bound)
            self.assertEqual([], stub.hits)
        from avrana_home.adapters._base import check_request
        from avrana_home.contract import ForbiddenRequest
        for m in ("POST", "PUT", "DELETE", "PATCH", "get"):
            with self.assertRaises(ForbiddenRequest):
                check_request(cap.SERVICES["jellyfin"]["routes"], cap.SERVICES["jellyfin"]["bound"], m, "/Users", None, None)

    def test_output_inside_the_repository_is_refused(self):
        with Stub() as stub:
            code, out, err = run(["--members", "alice", "--out", str(HOME / "tools" / "captured")], stub.env())
            self.assertEqual(1, code)
            self.assertIn("Git work tree", err)
            self.assertEqual([], stub.hits)
            self.assertFalse((HOME / "tools" / "captured").exists())

    def test_half_configured_service_is_a_config_error_naming_only_variables(self):
        env = {"AVRANA_CAPTURE_KOMGA_URL": "http://127.0.0.1:1"}
        code, out, err = run(["--dry-run"], env)
        self.assertEqual(1, code)
        self.assertIn("AVRANA_CAPTURE_KOMGA_TOKEN", err)
        self.assertNotIn("127.0.0.1", err + out)

    def test_nothing_configured(self):
        code, out, err = run(["--dry-run"], {})
        self.assertEqual(1, code)


class Runs(unittest.TestCase):
    def test_dry_run_makes_no_request_and_prints_no_secret_or_host(self):
        with Stub() as stub:
            code, out, err = run(["--dry-run", "--members", "alice", "--images"], stub.env())
            self.assertEqual(0, code)
            self.assertEqual([], stub.hits)
            text = out + err
            for bad in (JF_KEY, ABS_TOKEN, KOMGA_TOKEN, CW_PASS, CW_USER, "127.0.0.1", str(stub.server.server_address[1])):
                self.assertNotIn(bad, text)
            self.assertIn("DRY RUN", out)
            for line in ("GET /Users", "GET /UserItems/Resume", "GET /api/users", "GET /api/v2/users",
                         "GET /api/v1/books/latest", "GET /opds/new"):
                self.assertIn(line, out)

    def test_dry_run_writes_nothing(self):
        with Stub() as stub, tempfile.TemporaryDirectory() as d:
            target = Path(d) / "out"
            run(["--dry-run", "--out", str(target)], stub.env())
            self.assertFalse(target.exists())

    def test_full_run_is_get_only_allow_listed_and_redacted(self):
        with Stub() as stub, tempfile.TemporaryDirectory() as d:
            target = Path(d) / "cap"
            code, out, err = run(["--members", "alice,bob", "--own-username", "owner1", "--images",
                                  "--calibre-probe-id", "9999", "--out", str(target)], stub.env())
            self.assertEqual(0, code, err)
            self.assertEqual({"GET"}, {h[0] for h in stub.hits})
            self.assertTrue(all(h[3] for h in stub.hits), "a request went out without the right credential")
            allowed = set(BODIES) | {"/opds/thumb_cover/9999", f"/api/users/{ABS_BOB}"}
            self.assertTrue({h[1] for h in stub.hits} <= allowed, {h[1] for h in stub.hits} - allowed)
            for must in ("/Users", "/api/users", "/api/v2/users", "/opds/new", f"/api/users/{ABS_ALICE}",
                         f"/api/items/{ABS_ITEM}", f"/api/v1/books/{KG_BOOK}", f"/api/v1/series/{KG_SERIES}"):
                self.assertIn(must, {h[1] for h in stub.hits})
            files = outputs(target)
            self.assertIn("manifest.json", files)
            blob = "\n".join(files.values()) + out + err
            for bad in SENTINELS:
                self.assertNotIn(bad, blob, f"{bad!r} reached the output")
            self.assertEqual([], cap.scan_for_secrets(blob))
            self.assertIn("owner1", files["jellyfin-users-01.json"])          # the owner's own name is kept
            self.assertRegex(files["jellyfin-users-01.json"], r"member-[a-z]")
            self.assertNotIn(b"\x89PNG".decode("latin-1"), blob)
            meta = [n for n in files if n.endswith(".meta.json")]
            self.assertTrue(meta)
            self.assertEqual(40, json.loads(files[meta[0]])["bytes"])
            m = json.loads(files["manifest.json"])
            self.assertTrue(m["readonly_get_only"])
            self.assertTrue(all("127.0.0.1" not in json.dumps(e) for e in m["entries"]))
            self.assertTrue(any(e["status"] == 404 for e in m["entries"]))   # the probe id: status kept as evidence

    def test_without_members_only_user_lists_are_fetched(self):
        with Stub() as stub, tempfile.TemporaryDirectory() as d:
            code, *_ = run(["--out", str(Path(d) / "c"), "--services", "jellyfin,audiobookshelf"], stub.env())
            self.assertEqual(0, code)
            self.assertEqual({"/Users", "/api/users"}, {h[1] for h in stub.hits})

    def test_a_redirect_is_not_followed(self):
        with Stub(redirect_users=True) as stub, tempfile.TemporaryDirectory() as d:
            code, out, err = run(["--out", str(Path(d) / "c"), "--services", "komga"], stub.env())
            self.assertEqual(0, code)
            self.assertEqual(["/api/v2/users"], [h[1] for h in stub.hits])
            m = json.loads((Path(d) / "c" / "manifest.json").read_text())
            self.assertEqual(302, m["entries"][0]["status"])
            self.assertEqual("redirect_refused", m["entries"][0]["error"])
            self.assertIsNone(m["entries"][0]["file"])

    def test_a_body_over_the_cap_is_refused(self):
        big = {"x": "a" * (cap.MAX_JSON_BYTES + 10)}
        with Stub(overrides={"/api/v2/users": big}) as stub, tempfile.TemporaryDirectory() as d:
            code, out, err = run(["--out", str(Path(d) / "c"), "--services", "komga"], stub.env())
            self.assertEqual(0, code)
            m = json.loads((Path(d) / "c" / "manifest.json").read_text())
            self.assertEqual("too_large", m["entries"][0]["error"])
            self.assertEqual(["manifest.json"], sorted(outputs(Path(d) / "c")))

    def test_wrong_credential_yields_a_status_not_a_leak(self):
        with Stub() as stub, tempfile.TemporaryDirectory() as d:
            env = stub.env(AVRANA_CAPTURE_KOMGA_TOKEN="WRONG-TOKEN-VALUE-123")
            code, out, err = run(["--out", str(Path(d) / "c"), "--services", "komga"], env)
            self.assertEqual(0, code)
            self.assertNotIn("WRONG-TOKEN-VALUE-123", out + err + "".join(outputs(Path(d) / "c").values()))
            self.assertIn("HTTP 401", out)

    def test_unreachable_server_reports_without_the_url(self):
        env = {"AVRANA_CAPTURE_KOMGA_URL": "http://127.0.0.1:9", "AVRANA_CAPTURE_KOMGA_TOKEN": KOMGA_TOKEN}
        with tempfile.TemporaryDirectory() as d:
            code, out, err = run(["--out", str(Path(d) / "c"), "--timeout", "1"], env)
            self.assertEqual(0, code)
            self.assertNotIn("127.0.0.1", out + err)
            self.assertNotIn(KOMGA_TOKEN, out + err)

    def test_final_scan_refusal_gives_exit_3_and_no_file(self):
        leak = "Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0LmNb"
        with Stub(overrides={"/api/v2/users": [{"id": KG_USER, "note": leak}]}) as stub, tempfile.TemporaryDirectory() as d:
            code, out, err = run(["--out", str(Path(d) / "c"), "--services", "komga"], stub.env())
            self.assertEqual(3, code)
            self.assertIn("REFUSED", err)
            self.assertNotIn(leak, out + err)
            self.assertNotIn("komga-users-01.json", outputs(Path(d) / "c"))


if __name__ == "__main__":
    unittest.main()
