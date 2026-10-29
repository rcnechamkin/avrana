"""Me -> Account & Security (Media 2.0 supplement AS-01..AS-11, 2026-10-27; owner decision 2026-10-28). Standard
library only, no request object.

The owner's rule (2026-10-28): members never think about the sign-in service by name and are never sent to its own
pages. So Avrana owns every screen a member reads or manages, and the service only runs the moments that must prove who
the member is (a new password, adding a passkey or an authenticator app, backup codes). Each of those is one
single-purpose step on the sign-in screen, styled as Avrana (services/authentik/brand/), that returns on its own to
`/me/security/done/<action>` (services/authentik/blueprints/avrana-account.yaml ends every flow with that redirect).

  * The capability map (`capabilities`) offers an action only when the owner has applied its flow and named it in
    `HOME_SECURITY_FLOWS`. There is no fallback to the service's user settings page any more: an action without a
    verified flow says "ask the person who invited you" instead of sending the member anywhere.
  * The hand-off (`target`) is a fixed table built from the catalogue's account address and the configured slugs; the
    action is matched against an allowlist, so nothing from the request can choose a destination (no open redirect).
  * What the member has set up, and where they're signed in, are read natively (accountreader.py) when the owner has
    given Home the scoped reader. Without it the pages say what they can't show; they never claim "none".
  * Coming back proves nothing by itself (AS-08). The done page says "added" only when a fresh read shows a method of
    that kind created in the last few minutes, or a password changed in that window; otherwise it says it couldn't
    confirm, and lists what is there.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple
from urllib.parse import urlsplit

PREFIX = "/me/security"
JSON_ROUTE = "/me/security.json"
GO_PREFIX = PREFIX + "/go/"
DONE_PREFIX = PREFIX + "/done/"
SESSIONS_ROUTE = PREFIX + "/sessions"

# Actions a member can be handed off for: each is one owner-applied flow on the sign-in screen.
ACTIONS = ("password", "passkey", "totp", "recovery_codes")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")

ENROLLMENT_STATES = ("verified_enrolled", "verified_absent", "unknown")
OUTCOMES = ("confirmed", "unknown")

# Detail pages under /me/security: route -> (page id, the action its "Continue" hands off to, or None).
PAGES = {
    PREFIX: ("hub", None),
    PREFIX + "/password": ("password", "password"),
    PREFIX + "/protection": ("protection", None),
    PREFIX + "/protection/passkey": ("passkey", "passkey"),
    PREFIX + "/protection/authenticator": ("authenticator", "totp"),
    PREFIX + "/recovery": ("recovery", None),
    PREFIX + "/recovery/codes": ("codes", "recovery_codes"),
    SESSIONS_ROUTE: ("sessions", None),
}

# What the done page names, in words (never the action id).
ACTION_WORDS = {"password": "your password", "passkey": "a passkey", "totp": "an authenticator app",
                "recovery_codes": "backup codes"}
# Which kind of sign-in method (accountreader kinds) each enrolment action adds.
ACTION_KIND = {"passkey": "passkey", "totp": "authenticator", "recovery_codes": "backup_codes"}


class SecurityConfigError(ValueError):
    pass


def parse_flows(raw: str) -> Tuple[Tuple[str, str], ...]:
    """`HOME_SECURITY_FLOWS`: "password=<slug>,passkey=<slug>,...". Only ACTIONS keys, each once, each a plain flow
    slug. Anything else is a configuration error, never a silent fallback."""
    out: Dict[str, str] = {}
    for part in (p.strip() for p in raw.split(",")):
        if not part:
            continue
        key, sep, slug = part.partition("=")
        key, slug = key.strip(), slug.strip()
        if not sep or key not in ACTIONS:
            raise SecurityConfigError(f"HOME_SECURITY_FLOWS: unknown action (allowed: {', '.join(ACTIONS)})")
        if key in out:
            raise SecurityConfigError("HOME_SECURITY_FLOWS: an action is listed twice")
        if not SLUG.fullmatch(slug):
            raise SecurityConfigError("HOME_SECURITY_FLOWS: a flow slug must be lowercase letters, digits and hyphens")
        out[key] = slug
    return tuple(sorted(out.items()))


def auth_origin(account_address: str) -> str:
    """The sign-in service's origin, from the catalogue's fixed account address (portal.ACCOUNT_URL)."""
    parts = urlsplit(account_address)
    if parts.scheme != "https" or not parts.netloc:
        raise SecurityConfigError("the catalogue's account address must be an https address")
    return f"https://{parts.netloc}"


@dataclass(frozen=True)
class Capability:
    available: bool
    via: str                         # "secure_step" | "sign_in_page" | "avrana"
    reason: Optional[str] = None     # "not_configured", when unavailable

    def to_dict(self) -> dict:
        out = {"available": self.available, "via": self.via}
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass(frozen=True)
class SecurityConfig:
    origin: str                                  # https://auth.example
    flows: Tuple[Tuple[str, str], ...] = ()      # owner-applied, owner-verified flows
    reader: bool = False                         # Home has the scoped account reader (accountreader.py)

    @classmethod
    def build(cls, account_address: str, flows=(), reader: bool = False) -> "SecurityConfig":
        return cls(auth_origin(account_address), tuple(flows), reader)

    def available(self, action: str) -> bool:
        return action in dict(self.flows)

    def target(self, action: str) -> Optional[str]:
        """The fixed flow address for an allowlisted, configured action, or None. Never built from request text, and
        never the service's general user pages."""
        if action not in ACTIONS:
            return None
        slug = dict(self.flows).get(action)
        return f"{self.origin}/if/flow/{slug}/" if slug else None

    def _cap(self, action: str) -> Capability:
        return (Capability(True, "secure_step") if self.available(action)
                else Capability(False, "secure_step", "not_configured"))

    def capabilities(self) -> Dict[str, Capability]:
        """Every account is a local account today (no external sources are configured: docs/services/authentik.md), so a
        password exists to change. Recovery by email runs only on the sign-in page: the recovery flow requires an
        unauthenticated session (blueprints/avrana-recovery.yaml)."""
        native = Capability(True, "avrana") if self.reader else Capability(False, "avrana", "not_configured")
        return {
            "change_password": self._cap("password"),
            "enroll_passkey": self._cap("passkey"),
            "enroll_totp": self._cap("totp"),
            "manage_recovery_codes": self._cap("recovery_codes"),
            "recover_by_email": Capability(True, "sign_in_page"),
            "view_methods": native,
            "view_auth_sessions": native,
            "end_auth_session": native,
        }

    def summary(self, view=None) -> dict:
        """GET /me/security.json: what the member can do and how, with no flow slug, host or member identifier.
        `view` (accountreader.AccountView or None) turns "unknown" into verified states."""
        def state(kind: str) -> str:
            if view is None:
                return "unknown"
            if view.of(kind):
                return "verified_enrolled"
            # The reader's role is not given the backup-code device permission (that permission can read the codes
            # themselves), so their absence from the list proves nothing.
            return "unknown" if kind == "backup_codes" else "verified_absent"
        return {
            "schema_version": 2,
            "capabilities": {k: c.to_dict() for k, c in self.capabilities().items()},
            "enrollment": {"passkey": state("passkey"), "totp": state("authenticator"),
                           "recovery_codes": state("backup_codes")},
            "sign_out": {"scope": "this_device_avrana_session"},
        }


def action_from_route(route: str, prefix: str = GO_PREFIX) -> Optional[str]:
    """`/me/security/go/<action>` (or `/done/<action>`) -> the action, only when it is on the allowlist."""
    if not route.startswith(prefix):
        return None
    action = route[len(prefix):]
    return action if action in ACTIONS else None


def handoff_headers(config: SecurityConfig, action: str) -> Optional[Dict[str, str]]:
    """Headers of the `/me/security/go/<action>` 303: the fixed flow address, or None when the action isn't set up (the
    route then answers the standard 404, as for an unknown action)."""
    target = config.target(action)
    return {"Location": target} if target else None


def sessions_result_headers(outcome: str, allowed) -> Dict[str, str]:
    """The 303 back to "Where you're signed in" after a sign-out post. `outcome` is a fixed id from `allowed`."""
    if outcome not in allowed:
        raise ValueError("not an outcome")
    return {"Location": f"{SESSIONS_ROUTE}?r={outcome}"}


def mask_email(email: str) -> str:
    """"m•••@example.net" for the member's own page on a possibly shared screen. "" for anything that isn't an address."""
    local, at, domain = (email or "").strip().partition("@")
    if not at or not local or not domain or "@" in domain:
        return ""
    return local[0] + "•••@" + domain


# ---- view models for the templates ------------------------------------------------------------------------------

@dataclass(frozen=True)
class SecurityPageVM:
    page: str                        # PAGES id, or "done"
    action: Optional[str]            # the action "Continue" hands off to (or the one just finished)
    go_href: Optional[str]           # /me/security/go/<action>, only when that action is set up
    jellyfin_copy: bool              # the member has TV and Movies, whose password is a separate copy
    signout_href: str
    username: str
    reader: bool                     # Home can read the member's methods and sessions
    view: object = None              # accountreader.AccountView, or None when not read or unreadable
    email: str = ""                  # masked recovery address, or ""
    outcome: Optional[str] = None    # done page: "confirmed" | "unknown"
    added_name: str = ""             # done page: the new method's own label, when confirmed
    now: Optional[datetime] = None
    token: str = ""                  # sessions page: the form token for "Sign out"
    result: Optional[str] = None     # sessions page: the outcome of the last sign-out

    @property
    def action_words(self) -> str:
        return ACTION_WORDS.get(self.action or "", "")


def build_page(route: str, config: SecurityConfig, *, groups, username: str, signout_href: str,
               view=None, email: str = "", now: Optional[datetime] = None, token: str = "",
               result: Optional[str] = None) -> Optional[SecurityPageVM]:
    tv = "avrana-videos" in groups
    done = action_from_route(route, DONE_PREFIX)
    if done is not None:
        outcome, added = "unknown", ""
        if view is not None and now is not None:
            from ..accountreader import recent
            if done == "password":
                outcome = "confirmed" if recent(view.password_changed, now) else "unknown"
            else:
                fresh = [m for m in view.of(ACTION_KIND[done]) if recent(m.created, now)]
                if fresh:
                    outcome, added = "confirmed", fresh[0].name
        return SecurityPageVM("done", done, None, tv, signout_href, username, config.reader, view, email, outcome,
                              added, now)
    entry = PAGES.get(route)
    if entry is None:
        return None
    page, action = entry
    go = (GO_PREFIX + action) if action and config.available(action) else None
    return SecurityPageVM(page, action, go, tv, signout_href, username, config.reader, view, email, now=now,
                          token=token, result=result)
