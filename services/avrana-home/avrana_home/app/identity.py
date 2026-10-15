"""The ONE identity path: raw ASGI headers -> `principal_from_headers` -> `Viewer`.

This is the only module in the application that reads request headers. The test
`test_route_layer_reads_no_identity_input` fails if any other module in this package touches the
query string, a cookie, a path parameter, a body, a form or `request.headers`.

How headers reach us (verified over a real uvicorn server): `scope["headers"]` is the raw list of
(name, value) byte pairs. uvicorn lowercases names and keeps every repeated header as its own pair,
so duplicates in any case are visible; Starlette's `request.headers` would merge them, so it is not
used. We pass only the four trusted header names, still as raw bytes, to
`principal_from_raw_headers`, which does the strict decoding: identity headers must be pure ASCII,
so any non-ASCII value (UTF-8 or latin-1 mojibake) is no principal. Look-alike names
(`X_authentik_username`, `X-Forwarded-User`) never reach it and confer nothing.

No principal (missing, empty, duplicated, malformed, oversized): the request is served as the
portal serves a request with NO groups. See docs/design/HOME-APP.md, "Identity".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request

from ..principal import (EMAIL_HEADER, GROUPS_HEADER, NAME_HEADER, USERNAME_HEADER,
                         MemberPrincipal, PrincipalError, principal_from_raw_headers)

_TRUSTED_NAMES = frozenset(h.lower() for h in (USERNAME_HEADER, GROUPS_HEADER, EMAIL_HEADER, NAME_HEADER))
_EMPTY = frozenset()


@dataclass(frozen=True)
class Viewer:
    """Who is asking, as far as the application may know. `principal` is None when the identity
    headers do not form a valid principal; `groups` is then empty (nothing is permitted)."""
    principal: Optional[MemberPrincipal]

    @property
    def groups(self) -> frozenset:
        return self.principal.groups if self.principal is not None else _EMPTY


def trusted_pairs(scope) -> list:
    """The raw (bytes, bytes) pairs of the trusted headers only, duplicates kept, names lowercased."""
    return [(bytes(n).lower(), bytes(v)) for n, v in scope.get("headers", ())
            if bytes(n).decode("latin-1").lower() in _TRUSTED_NAMES]


def viewer_from_scope(scope) -> Viewer:
    try:
        return Viewer(principal_from_raw_headers(trusted_pairs(scope)))
    except PrincipalError:
        return Viewer(None)


async def get_viewer(request: Request) -> Viewer:
    """FastAPI dependency. Every route except /healthz (and the loopback-only /readyz, which
    never looks at identity) depends on this."""
    return viewer_from_scope(request.scope)


def new_tab_from_scope(scope) -> Optional[str]:
    """The one display preference a member may ask for in the address: `?new=<library>` (which New this week
    tab to show). Bounded text only; the view-model checks it against the member's own allowlist and
    never echoes it. It confers no identity and no access."""
    from urllib.parse import parse_qsl
    raw = scope.get("query_string") or b""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > 512:
        return None
    for key, value in parse_qsl(bytes(raw).decode("ascii", "ignore"), keep_blank_values=False):
        if key == "new":
            return value[:32]
    return None


def has_identity_headers(scope) -> bool:
    """True when ANY header looks like an outpost identity header (used only to refuse the
    operator detail view; it grants nothing)."""
    for raw_name, _ in scope.get("headers", ()):
        name = raw_name.decode("latin-1").lower().replace("_", "-")
        if name.startswith("x-authentik") or name.startswith("x-forwarded") or name == "forwarded":
            return True
    return False
