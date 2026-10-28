"""Me -> Account & Security (Media 2.0 supplement AS-01..AS-11, 2026-10-27). Standard library only, no request object.

Avrana owns the menu, the words and the hand-off; Authentik owns every credential operation. Nothing here collects a
password, shows a QR code, reads a passkey or holds a recovery code, and nothing here can say a change succeeded:

  * The capability map (`capabilities`) says, per action, how the member reaches it: a flow the owner has verified on
    the deployed Authentik (`HOME_SECURITY_FLOWS`, "direct"), or Authentik's own user settings page ("account_settings",
    the documented fallback in docs/services/authentik-sessions-passkeys.md). No flow slug is guessed: with nothing
    configured, every action goes to the settings page.
  * Enrollment state is always "unknown". Home has no member-scoped read of Authentik devices (the outpost passes an
    identity, not an API token) and must not borrow an administrator token (supplement section 6), so it never says
    "Passkey added".
  * The hand-off (`target`) is a fixed table built from the catalogue's account address; the action is matched against
    an allowlist, so nothing from the request can choose a destination (no open redirect).
  * The return (`ReturnStates`): only when the owner sets HOME_SECURITY_RETURN_ORIGIN (after checking that the deployed
    Authentik honours `next` to that host) does the hand-off carry `next=<origin>/me/security/back?s=<state>`. The state
    is an opaque HMAC over action, expiry and the member's username under a per-process random key: no storage, no
    secret in the address, short-lived. Coming back can only ever report `unknown` (the same member; Authentik passes
    no trustworthy result) or `session_changed` (someone else is signed in now). `confirmed`, `cancelled` and `failed`
    are in the model for a later provider-backed read and are never produced here.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import quote, urlsplit

PREFIX = "/me/security"
JSON_ROUTE = "/me/security.json"
BACK_ROUTE = PREFIX + "/back"
GO_PREFIX = PREFIX + "/go/"

# Actions a member can be handed off for. Only these four may name an owner-verified direct flow; the others always
# use the settings page (Authentik's sessions list and the account's email live there).
FLOW_ACTIONS = ("password", "passkey", "totp", "recovery_codes")
ACTIONS = FLOW_ACTIONS + ("sessions", "account")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
SETTINGS_PATH = "/if/user/#/settings"

ENROLLMENT_STATES = ("verified_enrolled", "verified_absent", "unknown")
OUTCOMES = ("confirmed", "cancelled", "unknown", "failed", "session_changed")
STATE_TTL = 15 * 60
_MAX_STATE = 160
_STATE = re.compile(r"([a-z_]{1,32})\.([0-9]{1,12})\.([A-Za-z0-9_-]{1,64})\Z")

# Detail pages under /me/security: route -> (page id, the action its "Continue securely" hands off to, or None).
PAGES = {
    PREFIX: ("hub", None),
    PREFIX + "/password": ("password", "password"),
    PREFIX + "/protection": ("protection", None),
    PREFIX + "/protection/passkey": ("passkey", "passkey"),
    PREFIX + "/protection/authenticator": ("authenticator", "totp"),
    PREFIX + "/recovery": ("recovery", None),
    PREFIX + "/sessions": ("sessions", "sessions"),
}

# What the back page names, in words (never the action id).
ACTION_WORDS = {"password": "your password", "passkey": "a passkey", "totp": "an authenticator app",
                "recovery_codes": "your backup codes", "sessions": "where you're signed in",
                "account": "your account details"}


class SecurityConfigError(ValueError):
    pass


def parse_flows(raw: str) -> Tuple[Tuple[str, str], ...]:
    """`HOME_SECURITY_FLOWS`: "password=<slug>,passkey=<slug>,...". Only FLOW_ACTIONS keys, each once, each a plain
    Authentik flow slug. Anything else is a configuration error, never a silent fallback."""
    out: Dict[str, str] = {}
    for part in (p.strip() for p in raw.split(",")):
        if not part:
            continue
        key, sep, slug = part.partition("=")
        key, slug = key.strip(), slug.strip()
        if not sep or key not in FLOW_ACTIONS:
            raise SecurityConfigError(f"HOME_SECURITY_FLOWS: unknown action (allowed: {', '.join(FLOW_ACTIONS)})")
        if key in out:
            raise SecurityConfigError("HOME_SECURITY_FLOWS: an action is listed twice")
        if not SLUG.fullmatch(slug):
            raise SecurityConfigError("HOME_SECURITY_FLOWS: a flow slug must be lowercase letters, digits and hyphens")
        out[key] = slug
    return tuple(sorted(out.items()))


def parse_return_origin(raw: str) -> str:
    """`HOME_SECURITY_RETURN_ORIGIN`: "" (off) or exactly "https://<host>[:port]", no path, query or credentials."""
    raw = raw.strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise SecurityConfigError("HOME_SECURITY_RETURN_ORIGIN is not a valid address") from None
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise SecurityConfigError("HOME_SECURITY_RETURN_ORIGIN must be https://<host> with nothing after it")
    return f"https://{parts.hostname}" + (f":{port}" if port else "")


def auth_origin(account_address: str) -> str:
    """The Authentik origin, from the catalogue's fixed account address (portal.ACCOUNT_URL)."""
    parts = urlsplit(account_address)
    if parts.scheme != "https" or not parts.netloc:
        raise SecurityConfigError("the catalogue's account address must be an https address")
    return f"https://{parts.netloc}"


@dataclass(frozen=True)
class Capability:
    available: bool
    via: str                         # "direct" | "account_settings" | "sign_in_page"
    reason: Optional[str] = None     # "not_configured" | "unsupported_account" | "unsupported_client", when unavailable

    def to_dict(self) -> dict:
        out = {"available": self.available, "via": self.via}
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass(frozen=True)
class SecurityConfig:
    origin: str                                  # https://auth.example
    flows: Tuple[Tuple[str, str], ...] = ()      # owner-verified direct flows
    return_origin: str = ""                      # "" = no `next` on the hand-off

    @classmethod
    def build(cls, account_address: str, flows=(), return_origin: str = "") -> "SecurityConfig":
        return cls(auth_origin(account_address), tuple(flows), return_origin)

    def via(self, action: str) -> str:
        return "direct" if action in dict(self.flows) else "account_settings"

    def target(self, action: str) -> Optional[str]:
        """The fixed Authentik address for an allowlisted action, or None. Never built from request text."""
        if action not in ACTIONS:
            return None
        slug = dict(self.flows).get(action)
        return f"{self.origin}/if/flow/{slug}/" if slug else self.origin + SETTINGS_PATH

    def capabilities(self) -> Dict[str, Capability]:
        """Every account is a local Authentik account today (no external sources are configured: docs/services/
        authentik.md), so a password exists to change. Recovery by email runs only on the sign-in page: the recovery
        flow requires an unauthenticated session (blueprints/avrana-recovery.yaml)."""
        return {
            "change_password": Capability(True, self.via("password")),
            "enroll_passkey": Capability(True, self.via("passkey")),
            "enroll_totp": Capability(True, self.via("totp")),
            "manage_recovery_codes": Capability(True, self.via("recovery_codes")),
            "recover_by_email": Capability(True, "sign_in_page"),
            "view_auth_sessions": Capability(True, "account_settings"),
        }

    def summary(self) -> dict:
        """GET /me/security.json: what the member can do and how, with no flow slug, host or member data."""
        return {
            "schema_version": 1,
            "capabilities": {k: c.to_dict() for k, c in self.capabilities().items()},
            "enrollment": {"passkey": "unknown", "totp": "unknown", "recovery_codes": "unknown"},
            "return": {"carries_state": bool(self.return_origin), "reports_result": False},
            "sign_out": {"scope": "this_device_avrana_session"},
        }


def action_from_route(route: str) -> Optional[str]:
    """`/me/security/go/<action>` -> the action, only when it is on the allowlist."""
    if not route.startswith(GO_PREFIX):
        return None
    action = route[len(GO_PREFIX):]
    return action if action in ACTIONS else None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class ReturnResult:
    outcome: str                     # one of OUTCOMES; here only "unknown" or "session_changed"
    action: Optional[str] = None     # known only for a valid state from this member
    expired: bool = False


class ReturnStates:
    """Mints and checks the opaque return state. The key is random per process: a restart (or a second worker) simply
    makes older states read as "unknown, no action", which claims nothing."""

    def __init__(self, clock: Callable[[], float] = time.time, key: Optional[bytes] = None):
        self._key = key or secrets.token_bytes(32)
        self._clock = clock

    def _sig(self, action: str, exp: int, username: str) -> str:
        msg = f"{action}|{exp}|{username}".encode("utf-8")
        return _b64(hmac.new(self._key, msg, hashlib.sha256).digest()[:18])

    def mint(self, action: str, username: str) -> str:
        exp = int(self._clock()) + STATE_TTL
        return f"{action}.{exp}.{self._sig(action, exp, username)}"

    def check(self, state: Optional[str], username: str) -> ReturnResult:
        # The exact shape mint() writes, ASCII only: "²".isdigit() is True but int() refuses it, and compare_digest
        # raises on non-ASCII text, so anything looser turned a crafted address into a 500.
        match = _STATE.fullmatch(state) if isinstance(state, str) and len(state) <= _MAX_STATE else None
        if match is None or match.group(1) not in ACTIONS:
            return ReturnResult("unknown")
        action, exp_text, sig = match.groups()
        exp = int(exp_text)
        if exp < self._clock():
            return ReturnResult("unknown", expired=True)
        if not hmac.compare_digest(sig, self._sig(action, exp, username)):
            # Minted for someone else (or not by us): carry nothing over, and say who is signed in now.
            return ReturnResult("session_changed")
        return ReturnResult("unknown", action=action)


def handoff_location(config: SecurityConfig, states: ReturnStates, action: str, username: str) -> Optional[str]:
    """Where `/me/security/go/<action>` sends the member: the fixed target, plus `next` with an opaque state only when
    the owner has turned the return on. The state never carries a secret, a token or the username."""
    target = config.target(action)
    if target is None:
        return None
    if not config.return_origin or "#" in target:
        return target
    back = f"{config.return_origin}{BACK_ROUTE}?s={states.mint(action, username)}"
    return f"{target}?next={quote(back, safe='')}"


def handoff_headers(config: SecurityConfig, states: ReturnStates, action: str, username: str) -> Dict[str, str]:
    """Headers of the `/me/security/go/<action>` 303 (like pwa.signout_headers): the fixed address above, nothing else.
    `action` has already been matched against ACTIONS by `action_from_route`."""
    location = handoff_location(config, states, action, username)
    if location is None:
        raise ValueError("not an allowlisted action")
    return {"Location": location}


# ---- view models for the templates ------------------------------------------------------------------------------

@dataclass(frozen=True)
class SecurityPageVM:
    page: str                        # PAGES id, or "back"
    action: Optional[str]            # the action "Continue securely" hands off to
    go_href: Optional[str]           # /me/security/go/<action>
    leaves_to_settings: bool         # the hand-off lands on the general settings page, so the page says where to look
    jellyfin_copy: bool              # the member has TV and Movies, whose password is a separate copy
    signout_href: str
    username: str
    result: Optional[ReturnResult] = None

    @property
    def action_words(self) -> str:
        return ACTION_WORDS.get(self.action or "", "")


def build_page(route: str, config: SecurityConfig, *, groups, username: str, signout_href: str,
               result: Optional[ReturnResult] = None) -> Optional[SecurityPageVM]:
    if route == BACK_ROUTE:
        action = result.action if result is not None else None
        return SecurityPageVM("back", action, None, False, False, signout_href, username, result)
    entry = PAGES.get(route)
    if entry is None:
        return None
    page, action = entry
    return SecurityPageVM(
        page, action, (GO_PREFIX + action) if action else None,
        bool(action) and config.via(action) == "account_settings",
        "avrana-videos" in groups, signout_href, username)
