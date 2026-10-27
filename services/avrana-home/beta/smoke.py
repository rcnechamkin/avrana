#!/usr/bin/env python3
"""Smoke-test a running fixture-only beta container (standard library only).

    BETA_URL=http://127.0.0.1:18096 HOME_JWT_ISSUER=... HOME_JWT_AUDIENCE=... HOME_JWT_SECRET[_FILE]=... \
        python3 services/avrana-home/beta/smoke.py

Mints HS256 tokens over the SAME synthetic secret the container was started with (never a real Authentik
secret: CI generates a throwaway one) and checks what checklist section 5 tests 3 to 5 expect, without
Authentik: a verified token gets the member view; no token, forged plain headers and a token signed with
another key get 404 on the gated routes. Exit 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def mint(secret: str, issuer: str, audience: str, username: str = "member-a",
         groups=("avrana-users", "avrana-videos")) -> str:
    now = int(time.time())
    claims = {"iss": issuer, "aud": audience, "exp": now + 600, "iat": now - 5, "sub": "smoke",
              "preferred_username": username, "groups": list(groups)}
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(claims).encode())
    mac = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(mac)}"


def read_secret() -> str:
    """HOME_JWT_SECRET, or the file HOME_JWT_SECRET_FILE names (inside the beta container, where the secret is
    mounted as a file and never in the environment). The value is never printed."""
    path = os.environ.get("HOME_JWT_SECRET_FILE", "").strip()
    if path:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    return os.environ["HOME_JWT_SECRET"]


def status(url: str, headers: dict) -> int:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main() -> int:
    base = os.environ.get("BETA_URL", "http://127.0.0.1:18096").rstrip("/")
    iss, aud = os.environ["HOME_JWT_ISSUER"], os.environ["HOME_JWT_AUDIENCE"]
    key = read_secret()
    # Behind HOME_ALLOWED_USERS (the deployed beta) only an allowed name gets the member view: use the first one.
    allowed = [u.strip() for u in os.environ.get("HOME_ALLOWED_USERS", "").split(",") if u.strip()]
    good = mint(key, iss, aud, username=os.environ.get("SMOKE_USERNAME") or (allowed[0] if allowed else "member-a"))
    wrong = mint("SMOKE-WRONG-KEY-not-the-container-one-0123456789", iss, aud)
    forged = {"X-authentik-username": "member-a", "X-authentik-groups": "avrana-users|avrana-videos"}
    checks = [
        ("/healthz answers", "/healthz", {}, 200),
        ("verified token: member view", "/home.json", {"X-authentik-jwt": good}, 200),
        ("no identity: 404", "/home.json", {}, 404),
        ("forged plain headers: 404", "/home.json", forged, 404),
        ("forged plain headers on /watch: 404", "/watch", forged, 404),
        ("token from another key: 404", "/home.json", {"X-authentik-jwt": wrong}, 404),
        ("signed-out Home still renders (help only)", "/", {}, 200),
    ]
    failed = 0
    for name, path, headers, want in checks:
        got = status(base + path, headers)
        ok = got == want
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {path} -> {got} (want {want})")
    print(f"{len(checks) - failed}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
