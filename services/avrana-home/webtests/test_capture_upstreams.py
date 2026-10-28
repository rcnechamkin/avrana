"""Tier A: the owner-run capture tool (tools/capture_upstreams.py). Offline: a 127.0.0.1 stub server only.

Everything here is synthetic. The sentinel strings below stand in for credentials, e-mail addresses,
usernames, hosts and paths; the tests prove they never reach the output, the printed text or a request
that the adapters would not make. No real server, account or credential is involved.
"""
import importlib.util
from copy import copy
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
        '<link rel="http://opds-spec.org/image/thumbnail" href="/opds/cover_240_240/42"/>'
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
    "/api/v1/books": {"content": [{"id": KG_BOOK, "seriesId": KG_SERIES, "name": "Secret Comic",
                                          "url": "/data/comics/Secret Comic.cbz"}]},
    f"/api/v1/books/{KG_BOOK}": {"id": KG_BOOK, "seriesId": KG_SERIES, "name": "Secret Comic",
                                 "url": "/data/comics/Secret Comic.cbz", "number": 3},
    f"/api/v1/series/{KG_SERIES}": {"id": KG_SERIES, "libraryId": "KGLIB1234567", "metadata": {"title": "Secret Series"}},
    f"/api/v1/books/{KG_BOOK}/thumbnail": PNG,
    "/opds/new": OPDS,
    "/opds/cover_240_240/42": PNG,
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
                if stub.redirect_users and path == "/api/v1/books":
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
        self.assertIn("/opds/cover_240_240/42", out)           # numeric book id kept: shape evidence
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

    def test_json_flags_named_like_credentials_are_not_refused(self):
        # Real Jellyfin /Users carries these on every user; the member-mapping fixture must be writable.
        users = [{"Name": "member-a", "Id": "0" * 31 + "1", "HasPassword": True, "HasConfiguredPassword": True,
                  "HasConfiguredEasyPassword": False, "Policy": {"PasswordResetProviderId": None,
                                                                 "IsAdministrator": False}}]
        text = json.dumps(users)
        self.assertEqual([], cap.scan_for_secrets(text))
        resp = cap.Response(200, text.encode(), "application/json")
        files, manifest, refused = cap.build_outputs([cap.Capture("jellyfin", "users", "/Users", resp, "json")],
                                                     cap.Redactor([], [], "member-a", []))
        self.assertEqual([], refused)
        self.assertEqual(1, len(files))
        # ...while a real value under the same names is still refused
        for leak in ('"password": "hunter22"', '"Password": "true-ish-value"', "secret=trueandfalse"):
            self.assertIn("credential-parameter", cap.scan_for_secrets(leak), leak)

    def test_slash_path_forms_are_redacted_and_scanned(self):
        r = cap.Redactor([], [], "", [])
        for path in ("file:///home/ann/x.mkv", "c:/users/ann/doc.txt", "//nas01/share/a.mkv"):
            self.assertIn("file-url-or-slash-path", cap.scan_for_secrets(f"note {path} end"), path)
            out = r.redact_text(f"note {path} end")
            self.assertNotIn("ann", out)
            self.assertNotIn("nas01", out)
            self.assertEqual([], cap.scan_for_secrets(out), out)
        # URLs and API routes are not paths
        self.assertEqual([], cap.scan_for_secrets("https://host.invalid/x and /api/v1/books/ID00000001"))

    def test_re_review_leaks_are_closed(self):
        r = cap.Redactor([], [], "owner1", [])
        body = {"media": {"coverPath": "/audiobooks/Author Name/Book Title/cover.jpg"},
                "itemTagsSelected": ["Family Secret"], "Policy": {"BlockedTags": ["kids-only-ann"],
                                                                  "EnabledDevices": ["deviceidABC123def456"]},
                "labelsAllow": ["anns-shelf"], "note": "\\\\?\\UNC\\srv\\share\\ann.mkv"}
        out = json.dumps(r.redact_json(body))
        for bad in ("Author Name", "Book Title", "Family Secret", "kids-only-ann", "deviceidABC123def456",
                    "anns-shelf", "srv", "ann.mkv"):
            self.assertNotIn(bad, out)
        self.assertEqual([], cap.scan_for_secrets(out))
        self.assertIn("windows-path", cap.scan_for_secrets("x \\\\?\\UNC\\srv\\share\\f y"))

    def test_a_file_that_still_matches_is_refused_not_written(self):
        leak = "Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0LmNb"        # secret-like, under an innocent key
        resp = cap.Response(200, json.dumps({"Items": [{"Id": JF_ITEM, "Type": leak}]}).encode(), "application/json")
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
            for line in ("GET /Users", "GET /UserItems/Resume", "GET /api/users",
                         "GET /api/v1/books", "GET /opds/new"):
                self.assertIn(line, out)
            self.assertNotIn("/api/v2/users", out)               # Komga is a shared view: no admin-only call

    def test_dry_run_plans_every_member(self):
        with Stub() as stub:
            code, out, err = run(["--dry-run", "--members", "alice,bob"], stub.env())
            self.assertEqual(0, code)
            self.assertEqual([], stub.hits)
            self.assertEqual(2, out.count("GET /UserItems/Resume"), out)
            self.assertGreaterEqual(out.count("GET /api/users/"), 2, out)

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
            allowed = set(BODIES) | {"/opds/cover_240_240/9999", f"/api/users/{ABS_BOB}"}
            self.assertTrue({h[1] for h in stub.hits} <= allowed, {h[1] for h in stub.hits} - allowed)
            self.assertNotIn("/api/v2/users", {h[1] for h in stub.hits})
            for must in ("/Users", "/api/users", "/api/v1/books", "/opds/new", f"/api/users/{ABS_ALICE}",
                         f"/api/items/{ABS_ITEM}", f"/api/v1/books/{KG_BOOK}"):
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
            self.assertEqual(["/api/v1/books"], [h[1] for h in stub.hits])
            m = json.loads((Path(d) / "c" / "manifest.json").read_text())
            self.assertEqual(302, m["entries"][0]["status"])
            self.assertEqual("redirect_refused", m["entries"][0]["error"])
            self.assertIsNone(m["entries"][0]["file"])

    def test_a_body_over_the_cap_is_refused(self):
        big = {"x": "a" * (cap.MAX_JSON_BYTES + 10)}
        with Stub(overrides={"/api/v1/books": big}) as stub, tempfile.TemporaryDirectory() as d:
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
        body = {"content": [{"id": KG_BOOK, "seriesId": KG_SERIES, "metadata": {"number": leak}}]}
        with Stub(overrides={"/api/v1/books": body}) as stub, tempfile.TemporaryDirectory() as d:
            code, out, err = run(["--out", str(Path(d) / "c"), "--services", "komga"], stub.env())
            self.assertEqual(3, code)
            self.assertIn("REFUSED", err)
            self.assertNotIn(leak, out + err)
            self.assertNotIn("komga-latest-01.json", outputs(Path(d) / "c"))


# ---- strict allowlisting (owner decision): unknown fields are dropped before any redaction -----------------
def _caps(service, route, path, body, kind="json"):
    raw = body if isinstance(body, bytes) else (body.encode() if isinstance(body, str) else json.dumps(body).encode())
    return cap.Capture(service, route, path, cap.Response(200, raw, "application/json"), kind)


def _built(service, route, path, body, keep=False, kind="json", own=""):
    c = _caps(service, route, path, body, kind)
    files, manifest, refused = cap.build_outputs([c], cap.Redactor([], [], own, []), keep)
    return {k: v.decode() for k, v in files.items()}, manifest, refused


LEAKS = ["ann-secret-leak", "coverpath leak", "ExternalUrls", "ProviderIds", "tt0123456", "LastLoginDate",
         "2031-01-01", "Hostname", "nas-host-leak", "ServerName", "DeviceName", "phone-ann", "EnabledDevices",
         "deviceidABC123def456", "kids-only-ann", "anns-shelf", "wikipedia", "imdb.com", "9780306406157",
         "B00LEAKASIN", "Cover Path With Spaces"]


class Allowlist(unittest.TestCase):
    def test_an_unknown_field_is_dropped_including_nested_and_list_cases(self):
        body = {"Items": [{"Id": JF_ITEM, "Type": "Movie", "Name": "Film", "NewUnknownField": "ann-secret-leak",
                           "ImageTags": {"Primary": "0f" * 16, "Logo": "ann-secret-leak"},
                           "UserData": {"PlaybackPositionTicks": 5, "Rating": "ann-secret-leak",
                                        "Nested": {"deep": "ann-secret-leak"}},
                           "People": [{"Name": "ann-secret-leak"}], "Tags": ["ann-secret-leak"]},
                          "not-an-object", 7],
                "TotalRecordCount": 1, "Extra": {"x": "ann-secret-leak"}}
        files, _, refused = _built("jellyfin", "items", "/Items", body)
        self.assertEqual([], refused)
        out = json.loads(files["jellyfin-items-01.json"])
        self.assertEqual(["Items"], list(out))
        self.assertEqual(1, len(out["Items"]))                        # list shape kept; non-objects dropped
        self.assertEqual({"Id", "Type", "Name", "ImageTags", "UserData"}, set(out["Items"][0]))
        self.assertEqual(["Primary"], list(out["Items"][0]["ImageTags"]))
        self.assertEqual(["PlaybackPositionTicks"], list(out["Items"][0]["UserData"]))
        self.assertNotIn("ann-secret-leak", files["jellyfin-items-01.json"])

    def test_every_route_has_a_spec_and_only_the_adapter_fields(self):
        for key in (("jellyfin", "users"), ("jellyfin", "resume"), ("jellyfin", "latest"), ("jellyfin", "items"),
                    ("audiobookshelf", "users"), ("audiobookshelf", "user"), ("audiobookshelf", "item"),
                    ("komga", "latest"), ("komga", "book")):
            self.assertIn(key, cap.ALLOWLIST)
        self.assertNotIn(("komga", "users"), cap.ALLOWLIST)
        self.assertNotIn(("komga", "series"), cap.ALLOWLIST)        # not a shared-view route (#50)
        self.assertIsNone(cap.spec_for("komga", "users"))

    def test_a_route_without_an_allowlist_is_never_written(self):
        files, manifest, refused = _built("komga", "users", "/api/v2/users", [{"id": KG_USER, "email": EMAIL}])
        self.assertEqual({}, files)
        self.assertEqual("no_allowlist", manifest[0]["error"])
        self.assertIsNone(manifest[0]["file"])

    def test_wrong_shape_and_unparseable_bodies_are_not_written(self):
        files, manifest, _ = _built("jellyfin", "items", "/Items", "not json at all ann-secret-leak")
        self.assertEqual({}, files)
        self.assertEqual("not_parseable", manifest[0]["error"])
        files, manifest, _ = _built("jellyfin", "items", "/Items", "just a string")
        self.assertEqual("not_parseable", manifest[0]["error"])
        files, manifest, _ = _built("komga", "book", "/api/v1/books/{id}", 42)
        self.assertEqual({}, files)
        self.assertEqual("unexpected_shape", manifest[0]["error"])

    def test_external_urls_and_provider_ids_are_dropped_by_default_and_kept_on_opt_in(self):
        item = {"Id": JF_ITEM, "Type": "Movie", "Name": "Film",
                "ExternalUrls": [{"Name": "IMDb", "Url": "https://www.imdb.com/title/tt0123456"}],
                "ProviderIds": {"Imdb": "tt0123456", "Tmdb": "424242", "Other": "ann-secret-leak"}}
        files, _, _ = _built("jellyfin", "items", "/Items", {"Items": [item]})
        text = files["jellyfin-items-01.json"]
        for bad in ("ExternalUrls", "imdb.com", "ProviderIds", "tt0123456", "424242"):
            self.assertNotIn(bad, text)
        files, _, refused = _built("jellyfin", "items", "/Items", {"Items": [item]}, keep=True)
        self.assertEqual([], refused)
        out = json.loads(files["jellyfin-items-01.json"])["Items"][0]
        self.assertEqual({"Imdb": "tt0123456", "Tmdb": "424242"}, out["ProviderIds"])   # opt-in keeps only the named ids
        self.assertNotIn("ExternalUrls", out)                                          # URLs are never kept
        self.assertNotIn("ann-secret-leak", json.dumps(out))
        abs_item = {"id": ABS_ITEM, "libraryId": "lib_secret1", "mediaType": "book",
                    "media": {"metadata": {"title": "T", "explicit": False, "isbn": "9780306406157",
                                           "asin": "B00LEAKASIN", "links": ["https://x.example/ann"]}}}
        for keep in (False, True):
            files, _, _ = _built("audiobookshelf", "item", "/api/items/{id}", abs_item, keep=keep)
            text = files["audiobookshelf-item-01.json"]
            self.assertEqual(keep, "9780306406157" in text and "B00LEAKASIN" in text)
            self.assertNotIn("x.example", text)
        files, _, _ = _built("komga", "book", "/api/v1/books/{id}", {"id": KG_BOOK, "metadata": {
            "title": "T", "isbn": "9780306406157", "links": [{"url": "https://x.example/ann"}]}}, keep=True)
        self.assertIn("9780306406157", files["komga-book-01.json"])
        self.assertNotIn("x.example", files["komga-book-01.json"])

    def test_opds_keeps_only_the_elements_the_adapter_reads(self):
        feed = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/"><title>Secret Catalogue</title><updated>2031-01-01T00:00:00Z</updated>'
                '<link rel="self" href="/opds/new?ann=1"/><entry><title>Secret Book</title><id>urn:uuid:aaaa</id>'
                '<updated>2031-01-01T00:00:00Z</updated><author><name>Jane Secret</name><uri>http://who.example/jane</uri></author>'
                '<dc:identifier>isbn:9780306406157</dc:identifier><summary>wikipedia leak</summary>'
                '<link rel="x" href="https://www.imdb.com/title/tt0123456"/>'
                '<link rel="y" href="/opds/cover_240_240/42"/><link rel="z" href="/opds/download/42/epub/"/>'
                '<link rel="w" href="/opds/author/9"/></entry></feed>')
        for keep in (False, True):
            files, _, refused = _built("calibre-web", "new", "/opds/new", feed, keep=keep, kind="xml")
            self.assertEqual([], refused)
            text = files["calibre-web-new-01.xml"]
            for bad in ("Catalogue", "2031", "urn:uuid", "who.example", "wikipedia", "imdb.com", "tt0123456",
                        "/opds/author", "ann=1", "Jane", "Secret Book"):
                self.assertNotIn(bad, text)
            self.assertIn("/opds/cover_240_240/42", text)
            self.assertIn("/opds/download/42/epub/", text)
            self.assertEqual(keep, "9780306406157" in text)
            self.assertEqual("Title", re.search(r"<title>(Title) \d+</title>", text).group(1))

    def test_abs_lastupdate_is_kept_and_tags_follow_the_pseudonyms(self):
        body = {"id": ABS_ALICE, "username": "alice", "token": "SENTINEL-ABS-USERTOKEN", "lastSeen": 1900000000000,
                "permissions": {"accessAllLibraries": False, "accessAllTags": False, "accessExplicitContent": True,
                                "selectedTagsNotAccessible": True, "download": True},
                "librariesAccessible": ["lib_secret1"], "itemTagsSelected": ["kids-only-ann"],
                "mediaProgress": [{"userId": ABS_ALICE, "libraryItemId": ABS_ITEM, "progress": 0.5,
                                   "lastUpdate": 1700000000000, "ebookLocation": "ann-secret-leak", "startedAt": 5}]}
        files, _, refused = _built("audiobookshelf", "user", "/api/users/{id}", body)
        self.assertEqual([], refused)
        out = json.loads(files["audiobookshelf-user-01.json"])
        self.assertEqual(1700000000000, out["mediaProgress"][0]["lastUpdate"])
        for bad in ("lastSeen", "token", "ebookLocation", "startedAt", "download", "kids-only-ann", "lib_secret1"):
            self.assertNotIn(bad, files["audiobookshelf-user-01.json"])

    def test_every_earlier_leak_is_absent_by_construction(self):
        jf = {"Items": [{"Id": JF_ITEM, "Type": "Movie", "Name": "Film",
                         "ExternalUrls": [{"Url": "https://www.imdb.com/title/tt0123456"}, {"Url": "https://en.wikipedia.org/x"}],
                         "ProviderIds": {"Imdb": "tt0123456"}, "Path": "/data/Cover Path With Spaces/x.mkv",
                         "Tags": ["anns-shelf"], "LastPlayedDate": "2031-01-01T00:00:00Z"}]}
        users = [{"Name": "alice", "Id": JF_ALICE, "LastLoginDate": "2031-01-01T00:00:00Z",
                  "Policy": {"IsDisabled": False, "EnabledDevices": ["deviceidABC123def456"], "BlockedTags": ["kids-only-ann"]},
                  "ServerName": "nas-host-leak", "Hostname": "nas-host-leak", "DeviceName": "phone-ann"}]
        absu = {"users": [{"id": ABS_ALICE, "username": "alice", "email": EMAIL, "isActive": True,
                           "lastSeen": 1900000000000, "token": "SENTINEL-ABS-USERTOKEN"}]}
        absi = {"id": ABS_ITEM, "libraryId": "lib_secret1", "mediaType": "book", "path": "/audiobooks/Cover Path With Spaces",
                "media": {"coverPath": "/audiobooks/Cover Path With Spaces/cover.jpg", "tags": [], "duration": 5,
                          "metadata": {"title": "T", "explicit": False, "description": "ann-secret-leak"}}}
        kg = {"content": [{"id": KG_BOOK, "seriesId": KG_SERIES, "libraryId": "KGLIB1234567", "name": "N",
                           "url": "/data/comics/Cover Path With Spaces.cbz", "created": "2031-01-01T00:00:00Z",
                           "metadata": {"title": "T", "number": "1", "links": [{"url": "https://wikipedia.org/x"}],
                                        "tags": ["anns-shelf"], "isbn": "9780306406157"}}]}
        built = [_built("jellyfin", "items", "/Items", jf), _built("jellyfin", "users", "/Users", users),
                 _built("audiobookshelf", "users", "/api/users", absu), _built("audiobookshelf", "item", "/api/items/{id}", absi),
                 _built("komga", "latest", "/api/v1/books", kg)]
        blob = "\n".join(v for files, _, _ in built for v in files.values())
        self.assertTrue(blob)
        for bad in LEAKS + ["en.wikipedia.org", "wikipedia.org", EMAIL, "SENTINEL-ABS-USERTOKEN", "lastSeen",
                            "created", "LastPlayedDate", "BlockedTags", "sharingLabels", "description", "coverPath"]:
            self.assertNotIn(bad, blob, f"{bad!r} survived the allowlist")
        self.assertEqual([], cap.scan_for_secrets(blob))

    def test_show_allowlist_prints_per_route_fields_and_makes_no_request(self):
        with Stub() as stub:
            code, out, err = run(["--show-allowlist"], {})                  # no credentials needed
            self.assertEqual(0, code, err)
            self.assertEqual([], stub.hits)
            for line in ("[jellyfin]", "[audiobookshelf]", "[komga]", "[calibre-web]", "Items.UserData.PlaybackPositionTicks",
                         "mediaProgress.lastUpdate", "content.metadata.number", "entry/title", "dropped (default)"):
                self.assertIn(line, out)
            self.assertIn("never requested", out)                           # no /api/v2/users
            self.assertNotIn("ProviderIds.Imdb,", out.split("(only with")[0])
            self.assertIn("only with --keep-provider-ids", out)
            for bad in ("ExternalUrls", "LastLoginDate", "Hostname", "coverPath", "EnabledDevices"):
                self.assertNotIn(bad, out)
        code, out, _ = run(["--show-allowlist", "--keep-provider-ids", "--services", "jellyfin"], {})
        self.assertEqual(0, code)
        self.assertIn("KEPT (--keep-provider-ids)", out)
        self.assertNotIn("[komga]", out)
        code, _, err = run(["--show-allowlist", "--services", "nope"], {})
        self.assertEqual(1, code)

    def test_komga_makes_no_users_call_even_with_members_and_images(self):
        with Stub() as stub, tempfile.TemporaryDirectory() as d:
            code, out, err = run(["--services", "komga", "--members", "alice", "--images", "--out", str(Path(d) / "c")],
                                 stub.env())
            self.assertEqual(0, code, err)
            paths = {h[1] for h in stub.hits}
            self.assertNotIn("/api/v2/users", paths)
            self.assertTrue({"/api/v1/books", f"/api/v1/books/{KG_BOOK}"} <= paths)
            self.assertFalse(any(x.startswith("/api/v1/series") for x in paths), paths)
            self.assertNotIn("komga-users-01.json", outputs(Path(d) / "c"))

    def test_the_run_keeps_only_allowlisted_fields_end_to_end(self):
        bodies = dict(BODIES)
        bodies["/Items"] = {"Items": [{"Id": JF_ITEM, "Name": "Secret Film", "Type": "Movie",
                                       "ExternalUrls": [{"Url": "https://www.imdb.com/title/tt0123456"}],
                                       "ProviderIds": {"Imdb": "tt0123456"}, "LastLoginDate": "2031-01-01"}]}
        with Stub(overrides=bodies) as stub, tempfile.TemporaryDirectory() as d:
            code, out, err = run(["--services", "jellyfin", "--members", "alice", "--out", str(Path(d) / "c")], stub.env())
            self.assertEqual(0, code, err)
            blob = "\n".join(outputs(Path(d) / "c").values())
            for bad in ("imdb.com", "tt0123456", "ExternalUrls", "ProviderIds", "LastLoginDate"):
                self.assertNotIn(bad, blob)
            m = json.loads(outputs(Path(d) / "c")["manifest.json"])
            self.assertTrue(m["field_allowlist"])
            self.assertFalse(m["provider_ids_kept"])
        with Stub(overrides=bodies) as stub, tempfile.TemporaryDirectory() as d:
            code, out, err = run(["--services", "jellyfin", "--members", "alice", "--keep-provider-ids",
                                  "--out", str(Path(d) / "c")], stub.env())
            self.assertEqual(0, code, err)
            blob = "\n".join(outputs(Path(d) / "c").values())
            self.assertNotIn("imdb.com", blob)
            self.assertNotIn("ExternalUrls", blob)
            self.assertIn("tt0123456", blob)


# ---- search routes (AVR-383) and the creator/year fields: only what the adapters in the checkout make ----------
TERM = "zzqxterm"
ABS_LIB = "lib_secret1"
OPDS_SEARCH = OPDS.replace("<author><name>Jane Secret</name></author>",
                           "<author><name>Jane Secret</name></author><published>2008-03-01T00:00:00+00:00</published>"
                           "<published2>leak-published2</published2>")
SEARCH_BODIES = dict(BODIES)
SEARCH_BODIES.update({
    f"/api/users/{ABS_ALICE}": {"id": ABS_ALICE, "username": "alice", "isActive": True,
                                "permissions": {"accessAllLibraries": False}, "librariesAccessible": [ABS_LIB],
                                "mediaProgress": []},
    f"/api/libraries/{ABS_LIB}/search": {"book": [{"libraryItem": {
        "id": ABS_ITEM, "libraryId": ABS_LIB, "mediaType": "book", "path": "/audiobooks/Secret",
        "media": {"metadata": {"title": "Secret Book", "authorName": "Jane Secret", "publishedYear": "2011",
                               "explicit": False, "description": "leak-description"}, "tags": []}},
        "matchKey": "title", "matchText": "leak-matchtext"}], "authors": [{"name": "leak-author-list"}]},
    "/api/v1/books": {"content": [{"id": KG_BOOK, "name": "Secret Comic", "url": "/data/comics/x.cbz",
                                   "metadata": {"title": "Secret Comic", "releaseDate": "2019-04-01",
                                                "summary": "leak-summary",
                                                "authors": [{"name": "Jane Secret", "role": "writer"}]}}]},
    "/opds/search": OPDS_SEARCH,
    "/opds/cover_240_240/42": PNG,
})


def _search_routes():
    """The search routes of the adapters on feat/home-2.0 (AVR-383), for checkouts whose adapters have them."""
    from avrana_home.adapters._base import Route
    from avrana_home.resilience import ItemGone, RouteMissing, UserGone
    lib = r"(?:lib_[a-z0-9]{3,40}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    return {
        "jellyfin": (Route("items", r"/Items", ("userId", "ids", "fields", "enableUserData", "enableImageTypes",
                                                 "searchTerm", "includeItemTypes", "recursive", "limit"),
                           user_scoped=True, not_found=UserGone),),
        "audiobookshelf": (Route("libraries", r"/api/libraries", (), user_scoped=False, not_found=RouteMissing),
                           Route("search", r"/api/libraries/" + lib + r"/search", ("q", "limit"), user_scoped=False,
                                 not_found=ItemGone)),
        # The one /api/v1/books route also carries Recently added's `sort` since 2026-10-28; it is matched first.
        "komga": (Route("search", r"/api/v1/books", ("search", "sort", "page", "size"), user_scoped=False,
                        not_found=RouteMissing),),
        "calibre-web": (Route("search", r"/opds/search", ("query",), user_scoped=False, not_found=RouteMissing),
                        Route("cover", r"/opds/cover_240_240/[0-9]{1,9}", (), user_scoped=False, not_found=ItemGone)),
    }


def without_search_routes(routes):
    """Model an older adapter explicitly, independently of this checkout's search support."""
    result = []
    for route in routes:
        if route.name == "search":
            continue
        route = copy(route)
        route.query_keys = route.query_keys - {"searchTerm", "search", "q", "query"}
        result.append(route)
    return tuple(result)


class SearchCapture(unittest.TestCase):
    def with_search_routes(self):
        """Give the tool the feat/home-2.0 search routes for this test, as a checkout with those adapters would."""
        extra = _search_routes()
        saved = {k: v["routes"] for k, v in cap.SERVICES.items()}
        for name, routes in extra.items():
            if name in cap.SERVICES:
                cap.SERVICES[name]["routes"] = tuple(routes) + tuple(cap.SERVICES[name]["routes"])
        self.addCleanup(lambda: [cap.SERVICES[k].__setitem__("routes", v) for k, v in saved.items()])

    def test_without_search_routes_in_the_adapters_nothing_is_requested(self):
        saved = {name: service["routes"] for name, service in cap.SERVICES.items()}
        for name, routes in saved.items():
            cap.SERVICES[name]["routes"] = without_search_routes(routes)
        self.addCleanup(lambda: [cap.SERVICES[name].__setitem__("routes", routes)
                                 for name, routes in saved.items()])
        with Stub(overrides=SEARCH_BODIES) as stub, tempfile.TemporaryDirectory() as d:
            code, out, err = run(["--members", "alice", "--search-term", TERM, "--out", str(Path(d) / "c")],
                                 stub.env())
            self.assertEqual(0, code, err)
            for h in stub.hits:
                self.assertNotIn(TERM, h[2], h[1])                    # the term never left the process
            self.assertNotIn("/opds/search", {h[1] for h in stub.hits})
            self.assertIn("search route not in this checkout's adapters", out)
            blob = "\n".join(outputs(Path(d) / "c").values()) + out + err
            self.assertNotIn(TERM, blob)

    def test_with_search_routes_the_search_is_captured_get_only_and_allowlisted(self):
        self.with_search_routes()
        with Stub(overrides=SEARCH_BODIES) as stub, tempfile.TemporaryDirectory() as d:
            code, out, err = run(["--members", "alice", "--own-username", "owner1", "--search-term", TERM,
                                  "--images", "--out", str(Path(d) / "c")], stub.env())
            self.assertEqual(0, code, err)
            self.assertEqual({"GET"}, {h[0] for h in stub.hits})
            searched = [h for h in stub.hits if TERM in h[2]]
            self.assertEqual({"/Items", f"/api/libraries/{ABS_LIB}/search", "/api/v1/books", "/opds/search"},
                             {h[1] for h in searched})
            self.assertFalse([h for h in stub.hits if TERM in h[1]])             # never in a path
            self.assertIn("/opds/cover_240_240/42", {h[1] for h in stub.hits})   # the cover route the adapters use
            self.assertNotIn("/opds/thumb_cover/42", {h[1] for h in stub.hits})
            files = outputs(Path(d) / "c")
            blob = "\n".join(files.values()) + out + err
            self.assertNotIn(TERM, blob)
            for bad in ("leak-description", "leak-matchtext", "leak-author-list", "leak-summary", "leak-published2",
                        "/audiobooks/", "/data/", "Secret", "Jane"):
                self.assertNotIn(bad, blob, bad)
            self.assertEqual([], cap.scan_for_secrets(blob))
            abs_search = json.loads(files["audiobookshelf-search-01.json"])
            meta = abs_search["book"][0]["libraryItem"]["media"]["metadata"]
            self.assertEqual("2011", meta["publishedYear"])                      # the year field is kept
            self.assertNotEqual("Jane Secret", meta["authorName"])               # the creator is pseudonymised
            kg = json.loads(files["komga-search-01.json"])["content"][0]["metadata"]
            self.assertEqual(("2019-04-01", "writer"), (kg["releaseDate"], kg["authors"][0]["role"]))
            self.assertIn("<published>2008-03-01T00:00:00+00:00</published>", files["calibre-web-search-01.xml"])
            jf = json.loads(files["jellyfin-search-01.json"])
            self.assertNotIn("Overview", json.dumps(jf))

    def test_a_term_that_is_not_a_plain_word_is_refused_before_any_request(self):
        for bad in ("a", "ab", "*", "x" * 41, "../../etc", "a%20b", "café", "a\r\nb", "a&b=c"):
            with Stub() as stub, tempfile.TemporaryDirectory() as d:
                code, out, err = run(["--search-term", bad, "--out", str(Path(d) / "c")], stub.env())
                self.assertEqual(1, code, bad)
                self.assertEqual([], stub.hits)
                if len(bad) > 2:
                    self.assertNotIn(bad, out + err)                       # the refused term is not echoed

    def test_dry_run_never_prints_the_term(self):
        self.with_search_routes()
        with Stub() as stub:
            code, out, err = run(["--dry-run", "--members", "alice", "--search-term", TERM], stub.env())
            self.assertEqual(0, code, err)
            self.assertEqual([], stub.hits)
            self.assertNotIn(TERM, out + err)
            self.assertIn("search=%3Cterm%3E", out)                            # a placeholder, encoded

    def test_every_search_route_has_an_allowlist(self):
        for key in (("jellyfin", "search"), ("audiobookshelf", "search"), ("audiobookshelf", "libraries"),
                    ("komga", "search")):
            self.assertIsNotNone(cap.spec_for(*key), key)
        self.assertNotIn(("komga", "users"), cap.ALLOWLIST)

    def test_the_term_from_the_environment_is_preferred_and_redacted_wherever_it_appears(self):
        self.with_search_routes()
        bodies = dict(SEARCH_BODIES)
        bodies["/api/v1/books"] = {"content": [{"id": KG_BOOK, "metadata": {
            "title": "Secret Comic", "authors": [{"name": "Jane Secret", "role": TERM}]}}]}
        with Stub(overrides=bodies) as stub, tempfile.TemporaryDirectory() as d:
            code, out, err = run(["--services", "komga", "--search-term", "otherword", "--out", str(Path(d) / "c")],
                                 stub.env(AVRANA_CAPTURE_SEARCH_TERM=TERM))
            self.assertEqual(0, code, err)
            sent = [h for h in stub.hits if h[1] == "/api/v1/books" and "search=" in h[2]]   # not Recently added
            self.assertEqual(1, len(sent))
            self.assertIn("search=" + TERM, sent[0][2])                 # the environment wins over the argument
            files = outputs(Path(d) / "c")
            blob = "\n".join(files.values()) + out + err
            self.assertNotIn(TERM, blob)                                  # replaced, like a credential
            self.assertIn(cap.REDACTED, files["komga-search-01.json"])
            self.assertEqual([], cap.scan_for_secrets(blob, [TERM]))

    def test_the_final_scan_refuses_the_term_as_a_literal(self):
        self.assertIn("literal-secret", cap.scan_for_secrets("a role of " + TERM, [TERM]))

    def test_jellyfin_legacy_users_items_search_shape(self):
        from avrana_home.adapters._base import Route
        from avrana_home.resilience import UserGone
        legacy = Route("search", r"/Users/(?P<user>[0-9a-f]{32})/Items",
                       ("searchTerm", "includeItemTypes", "recursive", "limit", "fields", "enableImageTypes",
                        "enableUserData"), user_scoped=True, bind_in="path", not_found=UserGone)
        saved = cap.SERVICES["jellyfin"]["routes"]
        cap.SERVICES["jellyfin"]["routes"] = (legacy,) + without_search_routes(saved)  # explicitly model the legacy adapter
        self.addCleanup(cap.SERVICES["jellyfin"].__setitem__, "routes", saved)
        bodies = dict(SEARCH_BODIES)
        bodies[f"/Users/{JF_ALICE}/Items"] = {"Items": [{"Id": JF_ITEM, "Name": "Secret Film", "Type": "Movie",
                                                         "ProductionYear": 2001, "Overview": "leak-overview"}]}
        with Stub(overrides=bodies) as stub, tempfile.TemporaryDirectory() as d:
            code, out, err = run(["--services", "jellyfin", "--members", "alice", "--search-term", TERM,
                                  "--out", str(Path(d) / "c")], stub.env())
            self.assertEqual(0, code, err)
            searched = [h for h in stub.hits if TERM in h[2]]
            self.assertEqual([f"/Users/{JF_ALICE}/Items"], [h[1] for h in searched])   # the user id in the path
            self.assertNotIn("userId=", searched[0][2])
            files = outputs(Path(d) / "c")
            jf = json.loads(files["jellyfin-search-01.json"])
            self.assertEqual(2001, jf["Items"][0]["ProductionYear"])
            blob = "\n".join(files.values())
            self.assertNotIn("leak-overview", blob)
            self.assertNotIn(TERM, blob)

    def test_published_year_is_kept_only_as_four_digits(self):
        spec = cap.spec_for("audiobookshelf", "item")
        for raw, kept in (("2011", True), ("2011 (first ed.)", False), (2011, False), ("201", False),
                          ("２０１１", False), (None, False), ("2011\n", False)):
            got = cap.allow_json(spec, {"id": ABS_ITEM, "media": {"metadata": {"publishedYear": raw}}})
            self.assertEqual(kept, "publishedYear" in got["media"]["metadata"], repr(raw))


if __name__ == "__main__":
    unittest.main()
