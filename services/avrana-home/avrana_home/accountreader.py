"""Me -> Account & Security, read natively (owner decision 2026-10-28: members never see the sign-in service's own
pages). Standard library only.

Home shows the member's own sign-in methods and sign-in sessions on its own pages, and can sign out one of those
sessions, through the sign-in service's API with a dedicated, permission-scoped service account (docs/runbooks/
account-reader.md). The token can do exactly what this module's allow-list sends, and the service account's role should
grant no more:

  GET    /api/v3/core/users/?username=<u>                       the member's account: id, active, last password change
  GET    /api/v3/authenticators/admin/all/?user=<id>            the member's sign-in methods (names and dates only)
  GET    /api/v3/core/authenticated_sessions/?user__username=<u>  the member's sign-in sessions
  DELETE /api/v3/core/authenticated_sessions/<uuid>/            sign out ONE of them, after it is found in that list

Guardrails:
  * the member comes only from the verified principal (real mode needs jwt_required: settings.py); the account id comes
    only from an exact, single username match, never from the request;
  * a session is ended only when its uuid is in a fresh read of that member's own sessions;
  * nothing that can unlock an account is ever read: the device list endpoint carries names, kinds and dates, not
    backup codes or keys (the per-kind admin endpoints are not on the allow-list for exactly that reason);
  * no write but the one session sign-out: no password, device or user changes are possible through this module;
  * answers are read once per member per READ_TTL, so a reload costs nothing upstream; a sign-out and the "back from
    the sign-in screen" page read fresh.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from .principal import is_minted_principal
from .resilience import DEFAULT_TIMEOUT, MAX_JSON_BYTES, UpstreamError, UpstreamHTTPError, UpstreamTimeout

USERS = "/api/v3/core/users/"
DEVICES = "/api/v3/authenticators/admin/all/"
SESSIONS = "/api/v3/core/authenticated_sessions/"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_USERNAME = re.compile(r"[^\x00-\x1f\x7f]{1,150}\Z")
READ_TTL = 30.0
READ_ENTRIES = 512
MAX_ROWS = 50

# Kinds of sign-in method, from the device's model name (Authentik's `meta_model_name`). Anything else is "other" and
# is listed by name only, never guessed at.
PASSKEY, AUTHENTICATOR, BACKUP_CODES, OTHER = "passkey", "authenticator", "backup_codes", "other"
_KIND = (("webauthn", PASSKEY), ("totp", AUTHENTICATOR), ("static", BACKUP_CODES))

# end_session() outcomes, each a fixed id the page turns into words.
ENDED, NOT_YOURS, UNAVAILABLE, UNKNOWN = "ended", "not_yours", "unavailable", "unknown"
END_OUTCOMES = (ENDED, NOT_YOURS, UNAVAILABLE, UNKNOWN)


class ForbiddenAccountRequest(Exception):
    pass


def check_request(method: str, path: str, query: Optional[Dict[str, str]]) -> None:
    """The allow-list above, exactly. A programming error raises before anything is sent."""
    q = dict(query or {})
    if method == "GET" and path == USERS and set(q) == {"username"} and _USERNAME.fullmatch(q["username"]):
        return
    if method == "GET" and path == DEVICES and set(q) == {"user"} and q["user"].isdigit() and len(q["user"]) <= 12:
        return
    if method == "GET" and path == SESSIONS and set(q) == {"user__username"} and _USERNAME.fullmatch(q["user__username"]):
        return
    if (method == "DELETE" and not q and path.startswith(SESSIONS) and path.endswith("/")
            and _UUID.fullmatch(path[len(SESSIONS):-1])):
        return
    raise ForbiddenAccountRequest()


def _when(raw) -> Optional[datetime]:
    if not isinstance(raw, str) or not 10 <= len(raw) <= 40:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _text(raw, limit: int = 80) -> str:
    if not isinstance(raw, str):
        return ""
    clean = "".join(ch for ch in raw if ch.isprintable()).strip()
    return clean[:limit]


@dataclass(frozen=True)
class Method:
    kind: str                         # PASSKEY | AUTHENTICATOR | BACKUP_CODES | OTHER
    name: str                         # the member's own label for it ("iPhone"), plain text
    created: Optional[datetime]
    last_used: Optional[datetime]


@dataclass(frozen=True)
class Session:
    uuid: str
    device: str                       # "Safari on iPhone", plain text, or ""
    place: str                        # "Leeds, GB" when the service knows it, or ""
    last_used: Optional[datetime]


@dataclass(frozen=True)
class AccountView:
    methods: Tuple[Method, ...]
    sessions: Tuple[Session, ...]
    password_changed: Optional[datetime]

    def of(self, kind: str) -> Tuple[Method, ...]:
        return tuple(m for m in self.methods if m.kind == kind)


def _kind(model_name) -> str:
    name = model_name.lower() if isinstance(model_name, str) else ""
    for needle, kind in _KIND:
        if needle in name:
            return kind
    return OTHER


def _method(raw) -> Optional[Method]:
    if not isinstance(raw, dict):
        return None
    if raw.get("confirmed") is False:
        return None                   # half-finished setups are not a way in, so not listed as one
    return Method(_kind(raw.get("meta_model_name") or raw.get("type")), _text(raw.get("name")) or "",
                  _when(raw.get("created")), _when(raw.get("last_used")))


def _device_words(agent) -> str:
    if not isinstance(agent, dict):
        return ""
    browser = _text((agent.get("user_agent") or {}).get("family") if isinstance(agent.get("user_agent"), dict) else "", 40)
    os_name = _text((agent.get("os") or {}).get("family") if isinstance(agent.get("os"), dict) else "", 40)
    device = agent.get("device") if isinstance(agent.get("device"), dict) else {}
    model = _text(device.get("family"), 40)
    if model.lower() in ("other", "generic smartphone", "mac", ""):
        model = ""
    where = model or os_name
    browser = "" if browser.lower() == "other" else browser
    where = "" if where.lower() == "other" else where
    if browser and where:
        return f"{browser} on {where}"
    return browser or where


def _session(raw) -> Optional[Session]:
    if not isinstance(raw, dict) or not isinstance(raw.get("uuid"), str) or not _UUID.fullmatch(raw["uuid"]):
        return None
    geo = raw.get("geo_ip") if isinstance(raw.get("geo_ip"), dict) else {}
    place = ", ".join(p for p in (_text(geo.get("city"), 40), _text(geo.get("country"), 4)) if p)
    return Session(raw["uuid"], _device_words(raw.get("user_agent")), place, _when(raw.get("last_used")))


def _results(body: bytes) -> List:
    data = json.loads(body)
    rows = data.get("results") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("results")
    return rows[:MAX_ROWS]


class AccountReader:
    def __init__(self, transport, *, timeout: float = DEFAULT_TIMEOUT, clock: Callable[[], float] = time.monotonic):
        self._transport = transport
        self._timeout = timeout
        self._clock = clock
        self._seen: Dict[str, Tuple[float, AccountView]] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "AccountReader(<redacted>)"

    def _call(self, method: str, path: str, query=None):
        check_request(method, path, query)
        resp = self._transport.request(method, path, query, self._timeout, MAX_JSON_BYTES)
        if resp.status not in ((200,) if method == "GET" else (204, 200)):
            raise UpstreamHTTPError(resp.status)
        return resp

    def _account(self, username: str) -> Optional[dict]:
        rows = _results(self._call("GET", USERS, {"username": username}).body)
        exact = [r for r in rows if isinstance(r, dict) and r.get("username") == username]
        if len(exact) != 1:
            return None
        row = exact[0]
        pk = row.get("pk")
        if row.get("is_active") is not True or not isinstance(pk, int) or isinstance(pk, bool) or pk <= 0:
            return None
        return row

    def _read(self, username: str) -> Optional[AccountView]:
        account = self._account(username)
        if account is None:
            return None
        methods = tuple(m for m in (_method(r) for r in _results(
            self._call("GET", DEVICES, {"user": str(account["pk"])}).body)) if m is not None)
        sessions = tuple(s for s in (_session(r) for r in _results(
            self._call("GET", SESSIONS, {"user__username": username}).body)) if s is not None)
        newest = datetime.min.replace(tzinfo=timezone.utc)
        return AccountView(
            tuple(sorted(methods, key=lambda m: m.created or newest, reverse=True)),
            tuple(sorted(sessions, key=lambda s: s.last_used or newest, reverse=True)),
            _when(account.get("password_change_date")))

    def view(self, principal, *, fresh: bool = False) -> Optional[AccountView]:
        """The member's own methods and sessions, or None when they can't be read (unmatched account, upstream trouble).
        None is shown as "couldn't load", never as "you have none"."""
        if not is_minted_principal(principal):
            return None
        username = principal.username
        now = self._clock()
        if not fresh:
            with self._lock:
                hit = self._seen.get(username)
            if hit is not None and hit[0] > now:
                return hit[1]
        try:
            result = self._read(username)
        except (UpstreamError, ValueError, ForbiddenAccountRequest):
            return None
        if result is not None:
            with self._lock:
                if len(self._seen) >= READ_ENTRIES:
                    self._seen = {k: v for k, v in self._seen.items() if v[0] > now}
                    if len(self._seen) >= READ_ENTRIES:
                        self._seen.clear()
                self._seen[username] = (now + READ_TTL, result)
        return result

    def end_session(self, principal, session_uuid: str) -> str:
        """Sign out one of the member's own sessions. The uuid must be in a fresh read of their sessions."""
        if not is_minted_principal(principal) or not isinstance(session_uuid, str) or not _UUID.fullmatch(session_uuid):
            return NOT_YOURS
        current = self.view(principal, fresh=True)
        if current is None:
            return UNAVAILABLE
        if session_uuid not in {s.uuid for s in current.sessions}:
            return NOT_YOURS
        try:
            self._call("DELETE", SESSIONS + session_uuid + "/")
        except UpstreamTimeout:
            outcome = UNKNOWN
        except UpstreamHTTPError as exc:
            outcome = ENDED if exc.status == 404 else UNAVAILABLE       # already gone is what was asked for
        except (UpstreamError, ForbiddenAccountRequest):
            outcome = UNKNOWN
        else:
            outcome = ENDED
        with self._lock:
            self._seen.pop(principal.username, None)
        return outcome


def recent(when: Optional[datetime], since: datetime, window_seconds: float = 15 * 60) -> bool:
    """True when `when` is within the window before `since` (the page's "you're back" evidence)."""
    return when is not None and 0 <= (since - when).total_seconds() <= window_seconds


def said_when(when: Optional[datetime], now: datetime) -> str:
    """Plain words for a date on the member's own page: "just now", "today", "yesterday", "on 3 Oct 2026"."""
    if when is None:
        return ""
    seconds = (now - when).total_seconds()
    if -300 <= seconds < 600:
        return "just now"
    if when.date() == now.date():
        return "today"
    if (now.date() - when.date()).days == 1:
        return "yesterday"
    return f"on {when.day} {when.strftime('%b')} {when.year}"
