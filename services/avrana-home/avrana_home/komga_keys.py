"""Members' own Komga keys after S-01: minted where the password lives, consumed by Home (docs/DECISIONS.md, "Komga
member keys are minted where the password lives"; docs/runbooks/komga-key-lifecycle.md). Standard library only.

Home never holds a Komga admin credential for keys and never sets or changes a member's Komga password. A member's key
reaches the keys file (member_keys.py) in one of two ways, both ending in `KeyIntake.file`:

  * Enrollment (Authentik stage `avrana-komga-key-mint`, services/authentik/blueprints/avrana-enrollment.yaml): while
    the new member's chosen password is still in the flow, Authentik signs in to Komga AS the member, makes the key
    named `avrana-home` and PUTs it to `/internal/komga-key/<subject>` with the intake token (app/intake.py).
  * A password reset (Authentik policy `avrana-komga-password-sync`, services/authentik/blueprints/avrana-recovery.yaml;
    docs/runbooks/komga-password-sync.md): the same mint, with `source` `recovery`, right after the policy set the
    member's Komga password to the new Avrana one, so a reset never leaves an obsolete Komga password behind.
  * "Connect comics" on Me -> Comics: the member types their password once; `KomgaKeyClient.mint` signs in to Komga as
    them with HTTP Basic, replaces their older `avrana-home` key and returns the new one. The password lives only in
    that call's arguments and the request header it builds; it is never logged, stored, put in a URL or in an
    exception (every failure is a fixed `ProvisionFailed` reason, raised `from None`).

Before filing, Home asks Komga who the key belongs to (`GET /api/v2/users/me` with the key) and files it under THAT
account's email, so a key can only ever be filed for the account it opens. "Disconnect" and offboarding revoke the key
in Komga as the member, with the key itself (`DELETE /api/v2/users/me/api-keys/{id}`; Komga allows an API key to manage
its own user's keys, UserController + SecurityConfiguration, read from Komga master 2026-10-30) and then drop it here.

The Komga routes (all `/api/v2/users/me...`, as the signed-in account only; an admin cannot mint another user's key):
    GET    /api/v2/users/me                    -> {id, email, roles, ...}
    GET    /api/v2/users/me/api-keys           -> [{id, comment, key: "******", ...}]   (the key is masked)
    POST   /api/v2/users/me/api-keys           {"comment"} -> {id, key, comment, ...}  (the only time the key is shown)
    DELETE /api/v2/users/me/api-keys/{id}      -> 204; 404 when it is not this account's key
"""
from __future__ import annotations

import base64
import hashlib
import re
import urllib.parse
from typing import Any, Callable, Optional, Tuple

from .member_keys import KOMGA_KEY, KOMGA_KEY_ID, KeysFileError, member_key_id
from .provision import ProvisionFailed, http_sender

KEY_COMMENT = "avrana-home"
SUBJECT = re.compile(r"[0-9a-f]{64}")          # sha256 hex of the Authentik `sub` (identity_bindings.digest)
SOURCES = ("enrollment", "recovery", "connect")
MAX_PASSWORD = 256

# KeyIntake outcomes (fixed ids: logged, and mapped to HTTP statuses by app/intake.py).
FILED, SAME, UNKNOWN_SUBJECT, BAD_KEY, KOMGA_DOWN, STORE_DOWN = (
    "filed", "unchanged", "unknown_subject", "bad_key", "komga_unavailable", "store_unavailable")


def subject_ref(subject: str) -> str:
    """What the logs carry for a subject: 12 hex of a domain-separated hash. Not the binding digest itself, so a log
    line cannot be joined to the identity bindings file."""
    return hashlib.sha256(b"komga-key-intake|" + subject.encode("ascii", "replace")).hexdigest()[:12]


class KomgaKeyClient:
    """The member-side Komga calls. `opener` is for tests (a urllib-style opener); otherwise http_sender's own (no
    proxy, no redirect)."""

    def __init__(self, base_url: str, opener: Any = None, timeout: float = 5.0):
        if not base_url.startswith(("http://", "https://")) or base_url.endswith("/"):
            raise ValueError("base_url must be http(s) without a trailing slash")
        self._base, self._opener, self._timeout = base_url, opener, timeout

    def _with_key(self, key: str):
        return http_sender(self._base, {"X-API-Key": key}, timeout=self._timeout, opener=self._opener)

    def mint(self, email: str, password: str) -> Tuple[str, str]:
        """Sign in to Komga as `email` with `password` (HTTP Basic), remove the account's older `avrana-home` keys and
        make a new one. Returns (key, Komga key id). `wrong_password` when Komga refuses the sign-in."""
        if not isinstance(email, str) or "@" not in email or not isinstance(password, str) or not password \
                or len(password) > MAX_PASSWORD or ":" in email:
            raise ProvisionFailed("bad_input")
        try:
            basic = base64.b64encode(f"{email}:{password}".encode("utf-8")).decode("ascii")
        except UnicodeEncodeError:
            raise ProvisionFailed("bad_input") from None
        member = http_sender(self._base, {"Authorization": "Basic " + basic}, timeout=self._timeout,
                             opener=self._opener)
        del basic, password
        try:
            keys = member("GET", "/api/v2/users/me/api-keys", None)
        except ProvisionFailed as exc:
            raise ProvisionFailed("wrong_password" if exc.reason == "http_401" else exc.reason) from None
        for k in keys if isinstance(keys, list) else ():
            if isinstance(k, dict) and k.get("comment") == KEY_COMMENT and isinstance(k.get("id"), str):
                member("DELETE", "/api/v2/users/me/api-keys/" + urllib.parse.quote(k["id"], safe=""), None)
        made = member("POST", "/api/v2/users/me/api-keys", {"comment": KEY_COMMENT})
        key = made.get("key") if isinstance(made, dict) else None
        komga_id = made.get("id") if isinstance(made, dict) else None
        if not isinstance(key, str) or KOMGA_KEY.fullmatch(key) is None \
                or not isinstance(komga_id, str) or KOMGA_KEY_ID.fullmatch(komga_id) is None:
            raise ProvisionFailed("created_unverified")
        return key, komga_id

    def owner_of(self, key: str) -> str:
        """The lower-case email of the Komga account `key` opens. `bad_key` when Komga refuses the key."""
        try:
            me = self._with_key(key)("GET", "/api/v2/users/me", None)
        except ProvisionFailed as exc:
            raise ProvisionFailed("bad_key" if exc.reason in ("http_401", "http_403") else exc.reason) from None
        email = member_key_id(me.get("email")) if isinstance(me, dict) else None
        if email is None:
            raise ProvisionFailed("malformed")
        return email

    def revoke(self, key: str, komga_id: Optional[str]) -> str:
        """Delete the key in Komga, as its own account. Returns "revoked", or "already_gone" when Komga no longer
        accepts the key (it was deleted in Komga already). With no stored id, every `avrana-home` key of the account
        is deleted (they are all Home's). Raises ProvisionFailed for anything else (Komga unreachable)."""
        send = self._with_key(key)
        try:
            if komga_id is not None and KOMGA_KEY_ID.fullmatch(komga_id):
                try:
                    send("DELETE", "/api/v2/users/me/api-keys/" + urllib.parse.quote(komga_id, safe=""), None)
                    return "revoked"
                except ProvisionFailed as exc:
                    if exc.reason != "http_404":
                        raise
            listed = send("GET", "/api/v2/users/me/api-keys", None)
            ours = [k["id"] for k in (listed if isinstance(listed, list) else ())
                    if isinstance(k, dict) and k.get("comment") == KEY_COMMENT and isinstance(k.get("id"), str)]
            for kid in ours:
                send("DELETE", "/api/v2/users/me/api-keys/" + urllib.parse.quote(kid, safe=""), None)
            return "revoked" if ours else "already_gone"
        except ProvisionFailed as exc:
            if exc.reason in ("http_401", "http_403"):
                return "already_gone"                  # the key itself no longer signs in: nothing left to revoke
            raise


class KeyIntake:
    """Files a member's key that came from outside Home (the enrollment stage) or from Connect. `known(subject)` says
    whether a subject digest is bound to a member in the identity bindings file (True / False / None = unknown because
    the file is unavailable or not configured)."""

    def __init__(self, store: Any, client: KomgaKeyClient, known: Callable[[str], Optional[bool]],
                 log: Optional[Callable[..., None]] = None):
        if not getattr(store, "writable", False):
            raise ValueError("Home must be able to write the keys file")
        self._store, self._client, self._known = store, client, known
        self._log = log or (lambda **_kw: None)

    def allowed(self, subject: str, source: str) -> bool:
        """The subject rule for the HTTP intake. A subject bound in the identity bindings file is a known member:
        accepted from any source. An unknown one (no binding yet, or the file unavailable or not configured) is
        accepted ONLY from Authentik's own stages: `enrollment` runs before the member's first sign-in, so before Home
        has bound them, and `recovery` may run for a member who has never opened Home."""
        if source in ("enrollment", "recovery"):
            return True
        return self._known(subject) is True

    def file(self, subject: str, source: str, key: str, komga_id: Optional[str] = None,
             signed_in: bool = False) -> str:
        """One outcome id. The key is checked with Komga and filed under the email of the account it opens.
        `signed_in` is True only for Home's own Connect, where the member is the verified principal of the request
        (no subject rule applies to a member acting for themselves)."""
        if SUBJECT.fullmatch(subject or "") is None or source not in SOURCES:
            raise ValueError("not a subject digest and a known source")
        outcome = self._file(subject, source, key, komga_id, signed_in)
        self._log(service="komga", state=outcome, reason=source, ref=subject_ref(subject))
        return outcome

    def _file(self, subject: str, source: str, key: str, komga_id: Optional[str], signed_in: bool) -> str:
        if not signed_in and not self.allowed(subject, source):
            return UNKNOWN_SUBJECT
        if not isinstance(key, str) or KOMGA_KEY.fullmatch(key) is None:
            return BAD_KEY
        if komga_id is not None and (not isinstance(komga_id, str) or KOMGA_KEY_ID.fullmatch(komga_id) is None):
            return BAD_KEY
        try:
            email = self._client.owner_of(key)
        except ProvisionFailed as exc:
            return BAD_KEY if exc.reason == "bad_key" else KOMGA_DOWN
        try:
            changed = self._store.put(email, key, komga_id)
        except (KeysFileError, OSError, ValueError, PermissionError):
            return STORE_DOWN
        return FILED if changed else SAME
