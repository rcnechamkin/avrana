"""A fake Komga for the S-01 key lifecycle (komga_keys.py): accounts that sign in with HTTP Basic (email + password)
or an API key, and the `/api/v2/users/me...` routes, as Komga master's UserController declares them (read 2026-10-30;
UNVERIFIED against the deployed version). No sockets: it is a urllib-style opener for provision.http_sender.
Synthetic accounts only."""
import base64
import io
import json
import urllib.error


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeKeyKomga:
    def __init__(self):
        self.accounts = {"U1": {"id": "U1", "email": "Alice@Example.com", "roles": ["FILE_DOWNLOAD", "USER"]},
                         "U2": {"id": "U2", "email": "bob@example.com", "roles": ["USER"]}}
        self.passwords = {"U1": "alice-synthetic-pw", "U2": "bob-synthetic-pw"}
        self.keys = {"U1": [{"id": "K-own", "comment": "phone", "key": "f" * 32}]}
        self.calls = []            # (method, path, who)
        self.serial = 0
        self.down = False          # every request: connection refused
        self.status = {}           # (method, path prefix) -> forced HTTP status

    # ---- helpers for tests -------------------------------------------------------------------------------------
    def mint_for(self, uid, comment="avrana-home"):
        self.serial += 1
        key = f"{self.serial:032x}"
        self.keys.setdefault(uid, []).append({"id": f"K{self.serial}", "comment": comment, "key": key})
        return key, f"K{self.serial}"

    def comments(self, uid):
        return sorted(k["comment"] for k in self.keys.get(uid, []))

    def headers_seen(self):
        return self._headers

    # ---- the opener ---------------------------------------------------------------------------------------------
    _headers = ()

    def _who(self, headers):
        key = headers.get("X-api-key")
        if key:
            for uid, keys in self.keys.items():
                if any(k["key"] == key for k in keys):
                    return uid
            return None
        auth = headers.get("Authorization", "")
        if auth.startswith("Basic "):
            email, _, pw = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
            for uid, acc in self.accounts.items():
                if acc["email"].casefold() == email.casefold() and self.passwords.get(uid) == pw:
                    return uid
        return None

    def open(self, req, timeout=None):
        if self.down:
            raise urllib.error.URLError("refused")
        path = "/" + req.full_url.split("://", 1)[1].split("/", 1)[1]
        method = req.get_method()
        headers = dict(req.header_items())
        self._headers = tuple(headers.items())
        who = self._who(headers)
        self.calls.append((method, path, who))
        for (m, prefix), status in self.status.items():
            if m == method and path.startswith(prefix):
                return self._fail(req, status)
        if who is None:
            return self._fail(req, 401)
        body = json.loads(req.data) if req.data else None
        if path == "/api/v2/users/me" and method == "GET":
            return self._ok(self.accounts[who])
        if path == "/api/v2/users/me/api-keys" and method == "GET":
            return self._ok([dict(k, key="******") for k in self.keys.get(who, [])])
        if path == "/api/v2/users/me/api-keys" and method == "POST":
            key, kid = self.mint_for(who, body["comment"])
            return self._ok({"id": kid, "userId": who, "key": key, "comment": body["comment"]})
        if path.startswith("/api/v2/users/me/api-keys/") and method == "DELETE":
            kid = path.rsplit("/", 1)[1]
            mine = self.keys.get(who, [])
            if not any(k["id"] == kid for k in mine):
                return self._fail(req, 404)
            self.keys[who] = [k for k in mine if k["id"] != kid]
            return _Resp(b"")
        return self._fail(req, 404)

    @staticmethod
    def _ok(obj):
        return _Resp(json.dumps(obj).encode("utf-8"))

    @staticmethod
    def _fail(req, status):
        raise urllib.error.HTTPError(req.full_url, status, "synthetic", {}, io.BytesIO(b""))
