#!/usr/bin/env python3
"""Owner-run: give members' Continue reading row in Home their OWN Komga API key. Standard library only.

    python3 tools/komga_member_keys.py --member alice@example.com     # one member (new or existing)
    python3 tools/komga_member_keys.py --all                          # every Komga account, asked one by one
    python3 tools/komga_member_keys.py --remove alice@example.com     # revoke Home's key for one member
    python3 tools/komga_member_keys.py --list                         # who has a key (reads the file only)

WHY. Komga's On Deck and in-progress lists belong to whoever is signed in, and Komga makes API keys only for the
account that is signed in (`/api/v2/users/me/api-keys`); no admin route makes one for somebody else. Members sign
in through Authentik and never see their Komga password. So, for each member, this tool uses a TEMPORARY admin
key to set a random password nobody keeps, signs in as the member with it, makes (or remakes) the key named
`avrana-home`, and files it under the member's email for Home. Owner decision 2026-10-28;
docs/runbooks/komga-member-keys.md.

WHAT IT CHANGES IN KOMGA (each step is shown and confirmed first):
  * an existing member: their Komga password is replaced (Komga signs them out of its web app once; their
    Authentik sign-in is unchanged), and any older `avrana-home` key of theirs is deleted;
  * a member with no Komga account yet (`--member` only): the account is created by email with the defaults an
    Authentik first sign-in gives (download and page streaming, every library, no restriction). Komga links a
    later Authentik sign-in to it by email (KomgaOAuth2UserService, findByEmailIgnoreCase);
  * an ADMIN account is never touched, and neither is any account `--skip` names (Home's shared viewer).

WHAT IT WRITES. The keys file (default ../secrets/komga_member_keys next to Home's compose file): a JSON object of
lower-case email -> key, mode 0600, replaced atomically. Home reads it as KOMGA_MEMBER_KEYS_FILE when it starts.
It never prints a key, a password or the admin key. The admin key is typed at a hidden prompt; revoke it in
Komga afterwards (Account settings -> API keys).

EXIT. 0 done; 1 at least one member failed (the others are kept); 2 refused (nothing changed).
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import secrets
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Sequence

KEY_COMMENT = "avrana-home"
DEFAULT_URL = "http://127.0.0.1:25600"          # Komga's loopback port on avrana (docs/SERVICES.md)
DEFAULT_KEYS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "secrets",
                            "komga_member_keys")
# What Komga 1.25 gives an account its Authentik first sign-in creates (KomgaUser defaults).
OIDC_DEFAULT_ROLES = ["FILE_DOWNLOAD", "PAGE_STREAMING"]
TIMEOUT = 15.0


class KomgaError(Exception):
    """A refused or failed Komga call. The message is the method, path and status only."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):     # a redirect could carry the credential elsewhere
        return None


class Komga:
    """The few Komga calls this tool makes. `send(method, url, headers, body)` -> (status, bytes) is injectable
    for tests; by default it is urllib without redirects."""

    def __init__(self, base_url: str, send: Optional[Callable] = None):
        self.base = base_url.rstrip("/")
        self._send = send or self._urllib

    @staticmethod
    def _urllib(method, url, headers, body):
        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with opener.open(req, timeout=TIMEOUT) as resp:
                return resp.status, resp.read(1 << 20)
        except urllib.error.HTTPError as exc:
            return exc.code, b""

    def call(self, method: str, path: str, auth: Dict[str, str], payload=None, ok=(200,)):
        headers = dict(auth, Accept="application/json")
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        status, data = self._send(method, self.base + path, headers, body)
        if status not in ok:
            raise KomgaError(f"{method} {path.split('?')[0]} answered {status}")
        if not data:
            return None
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError:
            raise KomgaError(f"{method} {path.split('?')[0]} answered something that is not JSON") from None


def admin_auth(key: str) -> Dict[str, str]:
    return {"X-API-Key": key}


def basic_auth(email: str, password: str) -> Dict[str, str]:
    token = base64.b64encode(f"{email}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": "Basic " + token}


def norm(email: str) -> str:
    return email.strip().casefold()


# ---- Komga steps ----------------------------------------------------------------------------
def users(komga: Komga, admin: Dict[str, str]) -> List[dict]:
    got = komga.call("GET", "/api/v2/users", admin)
    if not isinstance(got, list):
        raise KomgaError("GET /api/v2/users answered something that is not a list")
    return [u for u in got if isinstance(u, dict) and isinstance(u.get("email"), str) and isinstance(u.get("id"), str)]


def create_user(komga: Komga, admin: Dict[str, str], email: str, password: str) -> dict:
    return komga.call("POST", "/api/v2/users", admin,
                      {"email": email, "password": password, "roles": OIDC_DEFAULT_ROLES,
                       "sharedLibraries": {"all": True, "libraryIds": []}}, ok=(200, 201))


def set_password(komga: Komga, admin: Dict[str, str], user_id: str, password: str) -> None:
    komga.call("PATCH", f"/api/v2/users/{urllib.parse.quote(user_id, safe='')}/password", admin,
               {"password": password}, ok=(200, 204))


def drop_home_keys(komga: Komga, member: Dict[str, str]) -> int:
    keys = komga.call("GET", "/api/v2/users/me/api-keys", member) or []
    dropped = 0
    for k in keys if isinstance(keys, list) else ():
        if isinstance(k, dict) and k.get("comment") == KEY_COMMENT and isinstance(k.get("id"), str):
            komga.call("DELETE", f"/api/v2/users/me/api-keys/{urllib.parse.quote(k['id'], safe='')}", member,
                       ok=(200, 204))
            dropped += 1
    return dropped


def make_home_key(komga: Komga, member: Dict[str, str]) -> str:
    got = komga.call("POST", "/api/v2/users/me/api-keys", member, {"comment": KEY_COMMENT})
    key = got.get("key") if isinstance(got, dict) else None
    if not isinstance(key, str) or len(key) != 32 or not all(c in "0123456789abcdef" for c in key):
        raise KomgaError("POST /api/v2/users/me/api-keys answered without a usable key")
    return key


# ---- the keys file --------------------------------------------------------------------------
def load_keys(path: str) -> Dict[str, str]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ValueError("the keys file is not a JSON object of email -> key")
    return dict(data)


def save_keys(path: str, keys: Dict[str, str]) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".komga_member_keys.", dir=folder)
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(dict(sorted(keys.items())), fh, indent=1)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---- one member -----------------------------------------------------------------------------
def provision(komga: Komga, admin: Dict[str, str], account: Optional[dict], email: str,
              password: Callable[[], str] = lambda: secrets.token_urlsafe(24)) -> str:
    """The member's new `avrana-home` key. `account` is their Komga user, or None to create it."""
    pw = password()
    if account is None:
        account = create_user(komga, admin, email, pw)
        login = email
    else:
        set_password(komga, admin, account["id"], pw)
        login = account["email"]
    member = basic_auth(login, pw)
    drop_home_keys(komga, member)
    return make_home_key(komga, member)


def revoke(komga: Komga, admin: Dict[str, str], account: dict,
           password: Callable[[], str] = lambda: secrets.token_urlsafe(24)) -> int:
    pw = password()
    set_password(komga, admin, account["id"], pw)
    return drop_home_keys(komga, basic_auth(account["email"], pw))


def is_admin(account: dict) -> bool:
    roles = account.get("roles")
    return isinstance(roles, list) and "ADMIN" in roles


# ---- command line ---------------------------------------------------------------------------
def run(args, komga: Komga, admin_key: str, ask: Callable[[str], bool], out=print) -> int:
    admin = admin_auth(admin_key)
    keys = load_keys(args.keys_file)
    try:
        accounts = users(komga, admin)
    except KomgaError as exc:
        out(f"refused: {exc} (is the key an ADMIN account's key?)")
        return 2
    by_email = {norm(a["email"]): a for a in accounts}
    skip = {norm(e) for e in args.skip}
    failed = changed = 0

    if args.remove:
        for email in map(norm, args.remove):
            account = by_email.get(email)
            if account is not None and not is_admin(account) and ask(
                    f"{email}: delete their {KEY_COMMENT} key in Komga (signs them out of Komga once)?"):
                try:
                    revoke(komga, admin, account)
                except KomgaError as exc:
                    out(f"{email}: FAILED: {exc}")
                    failed += 1
                    continue
            if keys.pop(email, None) is not None:
                changed += 1
            out(f"{email}: Home no longer holds a key")
    else:
        targets = list(map(norm, args.member)) if args.member else sorted(by_email)
        for email in targets:
            account = by_email.get(email)
            if email in skip:
                out(f"{email}: skipped (--skip)")
                continue
            if account is not None and is_admin(account):
                out(f"{email}: skipped (an ADMIN account is never touched)")
                continue
            if account is None and not args.member:
                continue
            what = ("create their Komga account (Authentik sign-in defaults) and a key"
                    if account is None else
                    "replace their Komga password (signs them out of Komga once) and make a new key")
            if not ask(f"{email}: {what}?"):
                out(f"{email}: left alone")
                continue
            try:
                keys[email] = provision(komga, admin, account, email)
            except KomgaError as exc:
                out(f"{email}: FAILED: {exc}")
                failed += 1
                continue
            changed += 1
            save_keys(args.keys_file, keys)       # after every member: a later failure loses nothing
            out(f"{email}: key filed")
    if changed:
        save_keys(args.keys_file, keys)
        out(f"{changed} change(s) written to {args.keys_file}. Recreate Home to load them "
            "(docs/runbooks/komga-member-keys.md), then revoke the temporary admin key in Komga.")
    else:
        out("Nothing changed.")
    return 1 if failed else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--member", action="append", default=[], metavar="EMAIL")
    what.add_argument("--all", action="store_true")
    what.add_argument("--remove", action="append", default=[], metavar="EMAIL")
    what.add_argument("--list", action="store_true")
    ap.add_argument("--skip", action="append", default=[], metavar="EMAIL",
                    help="never touch this account (Home's shared viewer account, for one)")
    ap.add_argument("--komga-url", default=DEFAULT_URL)
    ap.add_argument("--keys-file", default=DEFAULT_KEYS)
    ap.add_argument("--yes", action="store_true", help="do not ask before each member")
    args = ap.parse_args(argv)
    try:
        keys = load_keys(args.keys_file)
    except (OSError, ValueError) as exc:
        print(f"refused: {args.keys_file}: {exc}", file=sys.stderr)
        return 2
    if args.list:
        for email in sorted(keys):
            print(email)
        print(f"{len(keys)} member(s) have a key in {args.keys_file}")
        return 0
    if not os.path.isdir(os.path.dirname(os.path.abspath(args.keys_file))):
        print(f"refused: the folder for {args.keys_file} does not exist", file=sys.stderr)
        return 2
    admin_key = getpass.getpass("Temporary Komga ADMIN API key (hidden): ").strip()
    if not admin_key:
        print("refused: no admin key", file=sys.stderr)
        return 2

    def ask(question: str) -> bool:
        if args.yes:
            print(question + " yes (--yes)")
            return True
        return input(question + " [y/N] ").strip().lower() in ("y", "yes")

    return run(args, Komga(args.komga_url), admin_key, ask)


if __name__ == "__main__":
    sys.exit(main())
