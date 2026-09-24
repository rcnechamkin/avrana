"""Identity extraction and authorization.

Three modes (config.auth_mode):
  - "oidc"   (default): identity comes from a signed session cookie set after the Authentik
              OIDC login (see oidc.py). Matches the ABS/Komga pattern on this host.
  - "header": identity comes from Authentik proxy-outpost headers (deployment behind an
              outpost). Only trustworthy if the app is not directly reachable.
  - "dev":    a static identity from DEV_IDENTITY, for tests only.

Authorization always requires membership of `required_group`.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import Settings

SESSION_COOKIE = "avrana_ac_session"


@dataclass(frozen=True)
class Identity:
    sub: str
    username: str
    email: str
    groups: tuple[str, ...]


def _split_groups(raw) -> tuple[str, ...]:
    if isinstance(raw, (list, tuple)):
        return tuple(str(g).strip() for g in raw if str(g).strip())
    if not raw:
        return ()
    parts = [g.strip() for chunk in str(raw).split("|") for g in chunk.split(",")]
    return tuple(g for g in parts if g)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def session_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="avrana-audible-session")


def _from_session_cookie(request: Request, settings: Settings) -> Identity | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        data = session_serializer(settings.secret_key).loads(
            raw, max_age=settings.session_ttl_seconds
        )
    except BadSignature:
        return None
    except Exception:
        return None
    return Identity(
        sub=str(data.get("sub", "")),
        username=str(data.get("username", "")),
        email=str(data.get("email", "")),
        groups=_split_groups(data.get("groups")),
    )


def get_identity(request: Request, settings: Settings = Depends(get_settings)) -> Identity:
    ident: Identity | None = None
    if settings.dev_identity:
        sub, username, email, groups = (settings.dev_identity.split(":", 3) + ["", "", "", ""])[:4]
        ident = Identity(sub, username or sub, email, _split_groups(groups))
    elif settings.auth_mode == "header":
        h = request.headers
        sub = h.get(settings.hdr_sub, "").strip()
        if sub:
            ident = Identity(
                sub=sub,
                username=h.get(settings.hdr_username, sub).strip(),
                email=h.get(settings.hdr_email, "").strip(),
                groups=_split_groups(h.get(settings.hdr_groups, "")),
            )
    else:  # oidc
        ident = _from_session_cookie(request, settings)

    if ident is None or not ident.sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if settings.required_group not in ident.groups:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Requires the '{settings.required_group}' role"
        )
    return ident
