"""Create a member's missing Jellyfin or Audiobookshelf account, or their own Komga key (ACCOUNT-PROVISIONING.md).

Status: proposed, not deployed. Standard library only. Off unless HOME_PROVISION_ACCOUNTS names a library.

The read adapters stay read-only: their guarded transports keep refusing every non-GET. This module is the only
code in Home that creates LIBRARY accounts (the request brokers may create a member's Shelfarr or Seerr account on
first ask, behind their own switches: HOME-APP.md section 5g), and it makes exactly two kinds of write
(ADAPTER-CONTRACT 15; Home's other upstream writes are Quick Connect approval in quickconnect.py and the request
brokers in requests/):

  * Jellyfin: `POST /Users/New`, then `POST /Users/{id}/Policy` turning the new account into what the LDAP plugin
    makes on a first sign-in (the plugin signs the member in and resets passwords; not an administrator; all
    libraries). It is created with a random password that is used once and discarded, so an account whose policy
    step failed is locked, never open.
  * Audiobookshelf: `POST /api/users` with the member's username and e-mail, type `user`, the server's default
    permissions and a random discarded password. ABS's "match existing by e-mail" then links the member's first
    "Sign in with Avrana" to this account.

  * Komga (owner decision 2026-10-28, "Home does it"): the member's OWN API key, named `avrana-home`, for their
    Continue reading row (docs/runbooks/komga-member-keys.md). Komga makes keys only for the signed-in account,
    so with Home's Komga ADMIN key: find the member's account by e-mail (or create it with the defaults an
    Authentik first sign-in gives), set a random password that is used once and discarded (Komga signs the member
    out of its web app once), sign in as them with it, replace any older `avrana-home` key and file the new key in
    the keys file. The admin key's own account needs no password: its key is made with the admin key itself. Any
    OTHER administrator is never touched. Triggered by a Continue section EMPTY with reason `no_member_key`.

It acts only when a section came back NOT_LINKED with reason `unmapped` (no account with that name in any letter
case), the member holds the library's group, and a fresh upstream read confirms the name (and, for ABS, the
e-mail) is still unused. Never more than one attempt per member and library per hour, one attempt at a time per
member and library, and at most `cap_per_hour` creations in all. Every attempt logs one fixed event; never a
password, token, username, e-mail or upstream id.
"""
from __future__ import annotations

import base64
import collections
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .adapters._base import norm_name
from .contract import REQUIRED_GROUP, SectionResult, SectionState, Service
from .resilience import _NoRedirect

PROVISIONABLE = (Service.JELLYFIN, Service.AUDIOBOOKSHELF, Service.KOMGA)
TRIGGER_REASON = "unmapped"            # MappingFailed reason: no account with that name, in any letter case
KOMGA_TRIGGER = "no_member_key"        # KomgaAdapter: the member has no key of their own yet
KOMGA_KEY_COMMENT = "avrana-home"
KOMGA_OIDC_ROLES = ["FILE_DOWNLOAD", "PAGE_STREAMING"]   # Komga 1.25 KomgaUser defaults (an Authentik first sign-in)
RETRY_AFTER = 3600.0                   # one attempt per member and library per hour
WINDOW = 3600.0
DEFAULT_CAP = 10
TIMEOUT = 5.0
MAX_BODY = 4 * 1024 * 1024
MAX_NAME = 64
LDAP_PROVIDER = "Jellyfin.Plugin.LDAP_Auth.LdapAuthenticationProviderPlugin"


class ProvisionFailed(Exception):
    """`reason` is a fixed identifier (logsafe), never upstream text."""

    def __init__(self, reason: str, terminal: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.terminal = terminal      # True: never retry this member automatically (the owner tool is the repair)


# ---- the one write-capable HTTP helper ---------------------------------------------------------------------
Send = Callable[[str, str, Optional[dict]], Any]      # (method, path, json body or None) -> parsed JSON


def http_sender(base_url: str, headers: Mapping[str, str], timeout: float = TIMEOUT, opener=None) -> Send:
    """JSON over HTTP to ONE upstream. Never a proxy, never a redirect (either could carry the admin credential
    elsewhere), a bounded body, and every failure a fixed `ProvisionFailed` reason."""
    if not base_url.startswith(("http://", "https://")) or base_url.endswith("/"):
        raise ValueError("base_url must be http(s) without a trailing slash")
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    fixed = dict(headers)

    def send(method: str, path: str, body: Optional[dict]) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        hdrs = dict(fixed, Accept="application/json")
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(base_url + path, data=data, method=method, headers=hdrs)
        try:
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read(MAX_BODY + 1)
        except urllib.error.HTTPError as exc:
            raise ProvisionFailed(f"http_{exc.code}" if 400 <= exc.code < 600 else "http_other") from None
        except Exception:
            raise ProvisionFailed("unreachable") from None
        if len(raw) > MAX_BODY:
            raise ProvisionFailed("too_large")
        if not raw.strip():
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise ProvisionFailed("malformed") from None
    return send


def _discarded_password() -> str:
    return secrets.token_urlsafe(32)


def _name_taken(wanted: str, names: Iterable[Any]) -> bool:
    loose = norm_name(wanted)
    return any(isinstance(n, str) and norm_name(n) == loose for n in names)


# ---- per-library creators ----------------------------------------------------------------------------------
class JellyfinCreator:
    service = Service.JELLYFIN

    def __init__(self, send: Send):
        self._send = send

    def create(self, username: str, email: Optional[str]) -> None:
        users = self._send("GET", "/Users", None)
        if not isinstance(users, list):
            raise ProvisionFailed("malformed")
        if _name_taken(username, (u.get("Name") for u in users if isinstance(u, dict))):
            raise ProvisionFailed("exists")
        made = self._send("POST", "/Users/New", {"Name": username, "Password": _discarded_password()})
        uid = made.get("Id") if isinstance(made, dict) else None
        policy = made.get("Policy") if isinstance(made, dict) else None
        if not isinstance(uid, str) or not uid or not isinstance(policy, dict) or made.get("Name") != username:
            raise ProvisionFailed("created_unverified")
        policy = dict(policy, AuthenticationProviderId=LDAP_PROVIDER, PasswordResetProviderId=LDAP_PROVIDER,
                      IsAdministrator=False, IsDisabled=False, EnableAllFolders=True, EnabledFolders=[],
                      EnableContentDeletion=False, EnableContentDeletionFromFolders=[],
                      EnableRemoteControlOfOtherUsers=False)
        self._send("POST", f"/Users/{uid}/Policy", policy)
        check = self._send("GET", f"/Users/{uid}", None)
        got = check.get("Policy") if isinstance(check, dict) else None
        if (not isinstance(got, dict) or got.get("AuthenticationProviderId") != LDAP_PROVIDER
                or got.get("IsAdministrator") is not False):
            raise ProvisionFailed("policy_unverified")       # the account stays locked by its discarded password


class AudiobookshelfCreator:
    service = Service.AUDIOBOOKSHELF

    def __init__(self, send: Send):
        self._send = send

    def create(self, username: str, email: Optional[str]) -> None:
        if not email or "@" not in email:
            raise ProvisionFailed("no_email")              # ABS links the first sign-in by e-mail
        body = self._send("GET", "/api/users", None)
        users = body.get("users") if isinstance(body, dict) else None
        if not isinstance(users, list):
            raise ProvisionFailed("malformed")
        rows = [u for u in users if isinstance(u, dict)]
        if _name_taken(username, (u.get("username") for u in rows)):
            raise ProvisionFailed("exists")
        if any(isinstance(u.get("email"), str) and u["email"].strip().casefold() == email.strip().casefold()
               for u in rows):
            raise ProvisionFailed("email_in_use")          # a second account with it would make the link ambiguous
        made = self._send("POST", "/api/users", {"username": username, "email": email,
                                                 "password": _discarded_password(), "type": "user",
                                                 "isActive": True})
        user = made.get("user") if isinstance(made, dict) else None
        if not isinstance(user, dict) or user.get("username") != username or user.get("type") != "user":
            raise ProvisionFailed("created_unverified")


class KomgaKeyCreator:
    """Makes and files a member's own Komga key. `send` carries the ADMIN key; `as_member(email, password)` returns a
    Send that signs in as that account with HTTP Basic (both from `http_sender`, so no redirect, no proxy)."""
    service = Service.KOMGA

    def __init__(self, send: Send, as_member: Callable[[str, str], Send], store: Any):
        if not getattr(store, "writable", False):
            raise ValueError("Home must be able to write the keys file")
        self._send = send
        self._as_member = as_member
        self._store = store

    @staticmethod
    def _new_key(member: Send) -> str:
        keys = member("GET", "/api/v2/users/me/api-keys", None)
        for k in keys if isinstance(keys, list) else ():
            if isinstance(k, dict) and k.get("comment") == KOMGA_KEY_COMMENT and isinstance(k.get("id"), str):
                member("DELETE", "/api/v2/users/me/api-keys/" + urllib.parse.quote(k["id"], safe=""), None)
        made = member("POST", "/api/v2/users/me/api-keys", {"comment": KOMGA_KEY_COMMENT})
        key = made.get("key") if isinstance(made, dict) else None
        if not isinstance(key, str) or len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
            raise ProvisionFailed("created_unverified")
        return key

    def preflight(self) -> None:
        """Before ANY Komga request: the configured keys file must exist and parse. An absent file reads as "no
        member has a key" and would make every comics member a candidate for a password reset (S-02)."""
        if not self._store.usable():
            raise ProvisionFailed("keys_file_unusable")

    def create(self, username: str, email: Optional[str]) -> None:
        self.preflight()
        wanted = (email or "").strip().casefold()
        if "@" not in wanted:
            raise ProvisionFailed("no_email")              # keys are filed, and Komga accounts found, by e-mail
        if self._store.get(wanted) is not None:
            raise ProvisionFailed("exists")
        if self._store.reset_failed(wanted):
            raise ProvisionFailed("failed_after_reset", terminal=True)   # decided without any Komga request
        me = self._send("GET", "/api/v2/users/me", None)
        users = self._send("GET", "/api/v2/users", None)
        if not isinstance(me, dict) or not isinstance(users, list):
            raise ProvisionFailed("malformed")
        rows = [u for u in users if isinstance(u, dict) and isinstance(u.get("email"), str)
                and isinstance(u.get("id"), str)]
        found = [u for u in rows if u["email"].strip().casefold() == wanted]
        if len(found) > 1:
            raise ProvisionFailed("ambiguous")
        account = found[0] if found else None
        if account is not None and account["id"] == me.get("id"):
            key = self._new_key(self._send)                 # the admin key's own account: no password involved
        elif account is not None and "ADMIN" in (account.get("roles") or ()):
            raise ProvisionFailed("admin")                  # another administrator: never touched
        else:
            password = _discarded_password()
            if account is None:
                made = self._send("POST", "/api/v2/users", {
                    "email": wanted, "password": password, "roles": KOMGA_OIDC_ROLES,
                    "sharedLibraries": {"all": True, "libraryIds": []}})
                if not isinstance(made, dict) or str(made.get("email", "")).casefold() != wanted:
                    raise ProvisionFailed("created_unverified")
                login = made["email"]
            else:
                # Komga makes keys only for the signed-in account, so for any account but the admin key's own this
                # reset is unavoidable today (owner decision S-01 pending). Everything after it is therefore fenced:
                # a failure leaves the member without their old password AND without a key, so it is terminal.
                self._send("PATCH", "/api/v2/users/" + urllib.parse.quote(account["id"], safe="") + "/password",
                           {"password": password})
                try:
                    key = self._new_key(self._as_member(account["email"], password))
                    self._store.put(wanted, key)
                except Exception:
                    self._store.mark_reset_failed(wanted)
                    raise ProvisionFailed("failed_after_reset", terminal=True) from None
                return
            key = self._new_key(self._as_member(login, password))
        self._store.put(wanted, key)


# ---- the policy around them --------------------------------------------------------------------------------
def _valid_username(name: Any) -> bool:
    return (isinstance(name, str) and 0 < len(name) <= MAX_NAME and name == name.strip()
            and name.isprintable() and "/" not in name and "\\" not in name)


class Provisioner:
    """Decides whether to create, and creates at most one account per library per call."""

    def __init__(self, creators: Mapping[Service, Any], cap_per_hour: int = DEFAULT_CAP,
                 clock: Callable[[], float] = time.monotonic, log: Optional[Callable[..., None]] = None):
        for service in creators:
            if service not in PROVISIONABLE:
                raise ValueError("Home creates accounts in Jellyfin and Audiobookshelf, and keys in Komga, only")
        self._creators = dict(creators)
        self._cap = cap_per_hour
        self._clock = clock
        self._log = log or (lambda **_kw: None)
        self._lock = threading.Lock()
        self._busy: set = set()
        self._terminal: set = set()                           # (username, service): never retried until a restart
        self._last: Dict[Tuple[str, Service], float] = {}
        self._made: collections.deque = collections.deque()

    @property
    def services(self) -> Tuple[Service, ...]:
        return tuple(self._creators)

    def candidates(self, sections: Sequence[SectionResult]) -> Tuple[Service, ...]:
        """The libraries whose sections say "no account with this name": the only trigger."""
        out = []
        for s in sections:
            if s.service not in self._creators or s.service in out:
                continue
            if s.service is Service.KOMGA:
                hit = s.section == "continue" and s.state is SectionState.EMPTY and s.reason == KOMGA_TRIGGER
            else:
                hit = s.state is SectionState.NOT_LINKED and s.reason == TRIGGER_REASON
            if hit:
                out.append(s.service)
        return tuple(out)

    def provision(self, principal: Any, sections: Sequence[SectionResult]) -> Tuple[Service, ...]:
        """Returns the libraries in which an account was created now."""
        created = []
        for service in self.candidates(sections):
            if self._attempt(principal, service):
                created.append(service)
        return tuple(created)

    def _attempt(self, principal: Any, service: Service) -> bool:
        if not principal.has_group(REQUIRED_GROUP[service]):
            return self._done(service, "refused", "no_group")
        if not _valid_username(principal.username):
            return self._done(service, "refused", "bad_username")
        key = (principal.username, service)
        now = self._clock()
        preflight = getattr(self._creators[service], "preflight", None)
        refusal = None
        with self._lock:
            if key in self._terminal:
                return False                                  # failed after a destructive step: quiet, owner repairs
            if key in self._busy:
                return False                                  # another tab is creating it: nothing to log
            last = self._last.get(key)
            if last is not None and now - last < RETRY_AFTER:
                return False                                  # tried within the hour: quiet
            if preflight is not None:
                try:
                    preflight()                               # refused here costs no cap slot and no upstream call
                except ProvisionFailed as exc:
                    self._last[key] = now
                    refusal = exc.reason
        if refusal is not None:
            return self._done(service, "refused", refusal)
        with self._lock:
            while self._made and now - self._made[0] >= WINDOW:
                self._made.popleft()
            if len(self._made) >= self._cap:
                capped = True
            else:
                capped = False
                self._busy.add(key)
                self._last[key] = now
                self._made.append(now)                        # counts the attempt, so a failing upstream is capped too
        if capped:
            return self._done(service, "refused", "cap")
        try:
            self._creators[service].create(principal.username, principal.email)
        except ProvisionFailed as exc:
            if exc.terminal:
                with self._lock:
                    self._terminal.add(key)
            return self._done(service, "refused" if exc.reason in ("exists", "email_in_use", "no_email", "admin",
                                                                  "keys_file_unusable")
                              else "failed", exc.reason)
        except Exception as exc:                              # never escapes into the page
            return self._done(service, "failed", type(exc).__name__)
        finally:
            with self._lock:
                self._busy.discard(key)
        self._done(service, "provisioned", "")
        return True

    def _done(self, service: Service, state: str, reason: str) -> bool:
        self._log(service=service.value, state=state, reason=reason)
        return False


def build_provisioner(settings: Any, log: Optional[Callable[..., None]] = None,
                      komga_keys: Any = None) -> Optional[Provisioner]:
    """None unless settings name at least one library (settings.py allows that only with real upstreams and
    jwt_required identity)."""
    wanted = tuple(getattr(settings, "provision_accounts", ()) or ())
    if not wanted:
        return None
    creators: Dict[Service, Any] = {}
    if "jellyfin" in wanted:
        creators[Service.JELLYFIN] = JellyfinCreator(http_sender(
            settings.jellyfin_base_url, {"Authorization": f'MediaBrowser Token="{settings.jellyfin_api_key}"'}))
    if "audiobookshelf" in wanted and settings.audiobookshelf_base_url:
        creators[Service.AUDIOBOOKSHELF] = AudiobookshelfCreator(http_sender(
            settings.audiobookshelf_base_url, {"Authorization": f"Bearer {settings.audiobookshelf_token}"}))
    if "komga" in wanted and komga_keys is not None and settings.komga_admin_token:
        base = settings.komga_base_url

        def as_member(email: str, password: str) -> Send:
            basic = base64.b64encode(f"{email}:{password}".encode("utf-8")).decode("ascii")
            return http_sender(base, {"Authorization": "Basic " + basic})
        creators[Service.KOMGA] = KomgaKeyCreator(
            http_sender(base, {"X-API-Key": settings.komga_admin_token}), as_member, komga_keys)
    return Provisioner(creators, settings.provision_cap_per_hour, log=log) if creators else None
