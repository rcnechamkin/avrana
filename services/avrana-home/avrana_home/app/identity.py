"""The ONE identity path: raw ASGI headers -> `principal_from_headers` -> `Viewer`.

This is the only module in the application that reads request headers. The test
`test_route_layer_reads_no_identity_input` fails if any other module in this package touches the
query string, a cookie, a path parameter, a body, a form or `request.headers`.

How headers reach us (verified over a real uvicorn server, see the web tests):
  * `scope["headers"]` is the raw list of (name, value) byte pairs. uvicorn lowercases names and
    keeps every repeated header as its own pair, so duplicates (any case) are visible. Starlette's
    `request.headers` would merge them, which is why it is NOT used here.
  * Values are decoded as UTF-8 with surrogate escapes: invalid bytes become lone surrogates, which
    the principal parser rejects as malformed (fail closed). Authentik sends UTF-8.
  * Only the four headers the principal parser knows are passed on; look-alikes such as
    `X_authentik_username` or `X-Forwarded-User` never reach it and confer nothing.

No principal (missing, empty, duplicated, malformed, oversized): the request is served as the
portal serves a request with NO groups. See docs/design/HOME-APP.md, "Identity".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request

from ..principal import (EMAIL_HEADER, GROUPS_HEADER, NAME_HEADER, USERNAME_HEADER,
                         MemberPrincipal, principal_or_none)

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
    pairs = []
    for raw_name, raw_value in scope.get("headers", ()):
        name = raw_name.decode("latin-1").lower()
        if name in _TRUSTED_NAMES:
            pairs.append((name, raw_value.decode("utf-8", "surrogateescape")))
    return pairs


def viewer_from_scope(scope) -> Viewer:
    return Viewer(principal_or_none(trusted_pairs(scope)))


async def get_viewer(request: Request) -> Viewer:
    """FastAPI dependency. Every route except /healthz (and the loopback-only /readyz, which
    never looks at identity) depends on this."""
    return viewer_from_scope(request.scope)


def has_identity_headers(scope) -> bool:
    """True when ANY header looks like an outpost identity header (used only to refuse the
    operator detail view; it grants nothing)."""
    for raw_name, _ in scope.get("headers", ()):
        name = raw_name.decode("latin-1").lower().replace("_", "-")
        if name.startswith("x-authentik") or name.startswith("x-forwarded") or name == "forwarded":
            return True
    return False
