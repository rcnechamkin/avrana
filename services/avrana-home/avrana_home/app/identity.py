"""The ONE identity path: raw ASGI headers -> `principal_for_request` -> `Viewer`.

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

Identity mode (AVR-498, `HOME_IDENTITY_MODE`, default `headers`): `headers` is the behaviour above,
unchanged. `jwt_log_only` serves the header identity and also checks `X-authentik-jwt`, logging one
fixed reason code through logsafe (never a token, name or group). `jwt_required` takes identity only
from a verified token; a header-only request has no principal. Every failure is "no principal".

No principal (missing, empty, duplicated, malformed, oversized): the request is served as the
portal serves a request with NO groups. See docs/design/HOME-APP.md, "Identity".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Request

from ..identity_bindings import OK as BOUND_OK, IdentityBindings
from ..outpost_jwt import OutpostJwtVerifier
from ..principal import (EMAIL_HEADER, GROUPS_HEADER, JWT_HEADER, MAX_GROUPS_HEADER_LEN, MAX_OPTIONAL_LEN,
                         MAX_USERNAME_LEN, MODE_HEADERS, MODE_JWT_REQUIRED, NAME_HEADER, USERNAME_HEADER,
                         MemberPrincipal, PrincipalError, decode_raw_headers, principal_for_request)
from .logsafe import app_log, log_event
from .settings import IDENTITY_MODES, Settings, SettingsError

_TRUSTED_NAMES = frozenset(h.lower() for h in (USERNAME_HEADER, GROUPS_HEADER, EMAIL_HEADER, NAME_HEADER))
_JWT_NAMES = _TRUSTED_NAMES | {JWT_HEADER.lower()}
_EMPTY = frozenset()
_MAX_SEARCH_ADDRESS = 2048      # raw bytes of the address query
_MAX_SEARCH_TERM = 300         # characters kept; contract.clean_query refuses > 256 and cuts to 100


@dataclass(frozen=True)
class Viewer:
    """Who is asking, as far as the application may know. `principal` is None when the identity
    headers do not form a valid principal; `groups` is then empty (nothing is permitted)."""
    principal: Optional[MemberPrincipal]

    @property
    def groups(self) -> frozenset:
        return self.principal.groups if self.principal is not None else _EMPTY


def trusted_pairs(scope, names=_TRUSTED_NAMES) -> list:
    """The raw (bytes, bytes) pairs of the trusted headers only, duplicates kept, names lowercased."""
    return [(bytes(n).lower(), bytes(v)) for n, v in scope.get("headers", ())
            if bytes(n).decode("latin-1").lower() in names]


def _report(code: str) -> None:
    log_event(app_log, logging.INFO, "identity_jwt", reason=code)   # fixed codes only


def _without_malformed_jwt(raw: list) -> list:
    """Drops a non-ASCII token header (reported as `malformed_header`) or one longer than
    MAX_JWT_HEADER_LEN (`oversized_header`) so it cannot take the plain header identity down with it
    in log-only mode. In jwt_required the request then simply has no token and fails closed exactly as
    a missing token does."""
    jwt = JWT_HEADER.lower().encode("ascii")
    kept = []
    for name, value in raw:
        if name == jwt:
            if len(value) > MAX_JWT_HEADER_LEN:
                _report("oversized_header")
                continue
            try:
                value.decode("ascii")
            except UnicodeDecodeError:
                _report("malformed_header")
                continue
        kept.append((name, value))
    return kept


class IdentityResolver:
    """Built once per app from `Settings`. In `headers` mode it holds no verifier and does exactly
    what the application did before AVR-498."""

    def __init__(self, mode: str = MODE_HEADERS, verifier: Optional[OutpostJwtVerifier] = None,
                 allowed_users=(), bindings: Optional[IdentityBindings] = None):
        if mode not in IDENTITY_MODES or (mode != MODE_HEADERS and verifier is None):
            raise SettingsError("identity mode is not usable")
        if allowed_users and mode != MODE_JWT_REQUIRED:
            raise SettingsError("an allowlist needs jwt_required")
        if bindings is not None and mode != MODE_JWT_REQUIRED:
            raise SettingsError("identity bindings need jwt_required")
        self.mode, self.verifier = mode, verifier
        self.allowed = frozenset(allowed_users)
        self.bindings = bindings

    @classmethod
    def from_settings(cls, settings: Settings) -> "IdentityResolver":
        mode = getattr(settings, "identity_mode", MODE_HEADERS)
        if mode == MODE_HEADERS:
            if getattr(settings, "allowed_users", ()):
                raise SettingsError("an allowlist needs jwt_required")
            return cls(MODE_HEADERS)
        secrets = [s.encode("utf-8") for s in (settings.jwt_secret, settings.jwt_secret_previous) if s]
        try:
            verifier = OutpostJwtVerifier(issuer=settings.jwt_issuer, audience=settings.jwt_audience,
                                          hmac_secrets=secrets)
        except ValueError:
            raise SettingsError("the JWT identity settings are not usable") from None
        path = getattr(settings, "identity_bindings_file", "")
        bindings = None
        if path:
            bindings = IdentityBindings(path, log=lambda **f: log_event(app_log, logging.INFO, "identity_bindings", **f))
        return cls(mode, verifier, getattr(settings, "allowed_users", ()), bindings)

    def viewer(self, scope) -> Viewer:
        names = _TRUSTED_NAMES if self.mode == MODE_HEADERS else _JWT_NAMES
        raw = trusted_pairs(scope, names)
        if self.mode != MODE_HEADERS:
            raw = _without_malformed_jwt(raw)
        try:
            pairs = decode_raw_headers(raw, extra_ascii=(JWT_HEADER,))
            principal = principal_for_request(pairs, mode=self.mode, verifier=self.verifier,
                                              report=_report)
        except PrincipalError:
            return Viewer(None)
        if self.allowed and principal is not None and principal.username not in self.allowed:
            _report("not_allowed")                    # a verified member who is not a beta tester
            return Viewer(None)
        if self.bindings is not None and principal is not None:
            # S1: this username is accepted only as the Authentik user it was first seen as (identity_bindings.py).
            outcome = self.bindings.check(principal.username, principal.subject)
            if outcome != BOUND_OK:
                _report(outcome)                      # fixed codes only: no name, no sub
                return Viewer(None)
        return Viewer(principal)


_HEADERS_ONLY = IdentityResolver()


def viewer_from_scope(scope) -> Viewer:
    return _HEADERS_ONLY.viewer(scope)


async def get_viewer(request: Request) -> Viewer:
    """FastAPI dependency. Every route except /healthz (and the loopback-only /readyz, which
    never looks at identity) depends on this."""
    resolver = getattr(request.app.state, "identity", None)
    if resolver is None:                          # an app built without create_app: today's behaviour
        resolver = _HEADERS_ONLY
    return resolver.viewer(request.scope)


def new_tab_from_scope(scope) -> Optional[str]:
    """The one display preference a member may ask for in the address of Home: `?new=<library>` (which Recently
    added tab to show). Bounded text only; the view-model checks it against the member's own allowlist and
    never echoes it. It confers no identity and no access."""
    return _choice_from_scope(scope, "new")


def release_chip_from_scope(scope) -> Optional[str]:
    """Home's New Releases chip (owner request 2026-10-28): `?rel=<kind>`. Exactly as `?new=`: bounded text only,
    checked by the view-model against the chips it offers this member, never echoed. It confers no identity and no
    access."""
    return _choice_from_scope(scope, "rel")


def more_from_scope(scope) -> Optional[str]:
    """Which Home rail shows its extra cards without script (owner request 2026-10-28): `?more=<rail>`. Bounded text
    only, checked by the view-model against its fixed list, never echoed. It confers no identity and no access."""
    return _choice_from_scope(scope, "more")


def library_chip_from_scope(scope) -> Optional[str]:
    """The one display preference a member may ask for in the address of /library: `?lib=<library>` (which filter
    chip is chosen; MK-5a, AVR-719). Exactly as `?new=` on Home: bounded text only, checked by the view-model
    against the member's own libraries, never echoed. It confers no identity and no access."""
    return _choice_from_scope(scope, "lib")


def if_none_match_from_scope(scope) -> Optional[str]:
    """The request's If-None-Match value for `/art` revalidation, or None when absent, repeated or over 512 bytes.
    Only ever compared with the validator of an image the member was just allowed to fetch (artwork.not_modified);
    it confers no identity and no access."""
    found = [v for k, v in scope.get("headers", ()) if bytes(k).lower() == b"if-none-match"]
    if len(found) != 1 or len(found[0]) > 512:
        return None
    return bytes(found[0]).decode("latin-1")


def home_filter_from_scope(scope) -> Optional[str]:
    """Home's filter (owner decision 2026-10-27): `?for=<place>` shows Home for one library place only (Watch,
    Listen, Read). Exactly as `?new=`: bounded text only, checked by the view-model against the member's own places,
    never echoed. It confers no identity and no access."""
    return _choice_from_scope(scope, "for")


def library_view_from_scope(scope) -> Optional[str]:
    """The Library's layout (owner decision 2026-10-27): `?view=<large|small|details|list>`. Bounded text only,
    checked by the view-model against its fixed list, never echoed. It confers no identity and no access."""
    return _choice_from_scope(scope, "view")


def show_from_scope(scope) -> Optional[int]:
    """`?show=<TMDB id>` on /request/watch: which show's seasons to list (the season picker). Digits only, at most
    nine; anything else is None (the page then shows the search). It confers no identity and no access: the seasons
    are read from Seerr as the member."""
    value = _choice_from_scope(scope, "show")
    return int(value) if value and value.isdigit() and len(value) <= 9 and int(value) > 0 else None


def tv_result_from_scope(scope) -> Optional[str]:
    """`?r=<outcome>` on /me/tv after a post (forms.py). Bounded text only; the page checks it against the fixed
    outcome list and never echoes it. It confers no identity and no access."""
    return _choice_from_scope(scope, "r")


def same_origin_form_post(scope) -> bool:
    """True only for a browser form post from this site: `Content-Type: application/x-www-form-urlencoded`, and
    `Sec-Fetch-Site: same-origin`, or (older browsers, no Sec-Fetch-Site) an `Origin` whose host equals `Host`. Each
    header must appear exactly once. A cross-site page can't forge either header (forms.py, CSRF locks)."""
    return _same_origin_post(scope) == "application/x-www-form-urlencoded"


def same_origin_upload_post(scope) -> Optional[str]:
    """Me → My profile (avatar.py): the full `multipart/form-data; boundary=…` Content-Type of a same-origin browser
    post (the same Sec-Fetch-Site / Origin locks as above), or None."""
    full = _same_origin_post(scope, full=True)
    if full is None or not full.lower().startswith("multipart/form-data") or len(full) > 200:
        return None
    return full


def _same_origin_post(scope, full: bool = False) -> Optional[str]:
    """The post's Content-Type (bare, lower case; or `full` as sent) when the same-origin locks hold, else None."""
    wanted = {b"content-type", b"sec-fetch-site", b"origin", b"host"}
    seen: dict = {}
    for raw_name, raw_value in scope.get("headers", ()):
        name = bytes(raw_name).lower()
        if name in wanted:
            if name in seen:
                return None
            try:
                seen[name] = bytes(raw_value).decode("ascii").strip()
            except UnicodeDecodeError:
                return None
    sent = seen.get(b"content-type", "")
    ctype = sent if full else sent.split(";", 1)[0].strip().lower()
    site = seen.get(b"sec-fetch-site")
    if site is not None:
        return ctype if site == "same-origin" else None
    origin, host = seen.get(b"origin", "").lower(), seen.get(b"host", "").lower()      # host names ignore case
    for scheme in ("https://", "http://"):
        if origin.startswith(scheme):
            return ctype if host and origin[len(scheme):] == host else None
    return None


def customize_from_scope(scope) -> Optional[str]:
    """`?from=home` on /me/home's editor (Customize opened from Home's heading: Cancel and Save go back to Home).
    Bounded text only; the caller compares it with the one fixed value and never echoes it."""
    return _choice_from_scope(scope, "from")


def security_result_from_scope(scope) -> Optional[str]:
    """`?r=<outcome>` on /me/security/sessions after a sign-out post (accountreader.py). Bounded text only; the page
    checks it against the fixed outcome list and never echoes it. It confers no identity and no access."""
    return _choice_from_scope(scope, "r")


def content_length_from_scope(scope) -> Optional[int]:
    """The request's single, plain-decimal Content-Length, or None (absent, repeated, chunked, malformed). Read by the
    middleware's POST gate only (middleware.py)."""
    found = [v for k, v in scope.get("headers", ()) if bytes(k).lower() == b"content-length"]
    chunked = any(bytes(k).lower() == b"transfer-encoding" for k, _ in scope.get("headers", ()))
    if len(found) != 1 or chunked or not bytes(found[0]).isdigit() or len(found[0]) > 9:
        return None
    return int(found[0])


def _choice_from_scope(scope, name: str) -> Optional[str]:
    from urllib.parse import parse_qsl
    raw = scope.get("query_string") or b""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > 512:
        return None
    for key, value in parse_qsl(bytes(raw).decode("ascii", "ignore"), keep_blank_values=False):
        if key == name:
            return value[:32]
    return None


def search_term_from_scope(scope) -> Optional[str]:
    """The one thing a member may type in the address of /search: `?q=<term>`. Bounded text only.
    None: no `q` at all (an empty search box). A string, possibly empty: a term for `contract.clean_query`
    to judge (an oversized address gives "", which that function refuses). The term confers no identity and
    no access, is never echoed raw, and is never logged."""
    from urllib.parse import parse_qsl
    raw = scope.get("query_string") or b""
    if not isinstance(raw, (bytes, bytearray)):
        return None
    if len(raw) > _MAX_SEARCH_ADDRESS:
        return ""
    try:
        pairs = parse_qsl(bytes(raw).decode("ascii", "ignore"), keep_blank_values=False, max_num_fields=8)
    except ValueError:
        return ""
    for key, value in pairs:
        if key == "q":
            return value[:_MAX_SEARCH_TERM]
    return None


# h11's default (max_incomplete_event_size): the same limit, now independent of how the bytes were read. Counted as
# name + value + ": " and CRLF per header line, close to the wire size (AVR-732).
MAX_HEADER_BYTES = 16 * 1024
# Home's own ceiling for the X-authentik-jwt header (AVR-732). Tighter than outpost_jwt.MAX_TOKEN_LEN (16384), which
# stays as it is because services/avrana-portal vendors that verifier byte for byte (tests/test_portal_jwt.py). A
# longer token header is dropped before verification (`oversized_header`): no token, so jwt_required fails closed.
# Real outpost ID tokens are a few KiB; a groups claim mirroring the 4096-byte groups header is ~5.5 KiB in base64.
MAX_JWT_HEADER_LEN = 8192
# The one budget inside that limit (owner, 2026-10-26: keep 16 KiB; token plus other headers must fit). Each identity
# header at its own parser maximum (principal.py, outpost_jwt.py), the token included; whatever is left is for every
# other header (Host, Cookie, User-Agent, Accept...). A request inside this budget is never refused as too large.
IDENTITY_HEADER_BUDGET = {
    JWT_HEADER: MAX_JWT_HEADER_LEN,
    USERNAME_HEADER: MAX_USERNAME_LEN,
    GROUPS_HEADER: MAX_GROUPS_HEADER_LEN,
    EMAIL_HEADER: MAX_OPTIONAL_LEN,
    NAME_HEADER: MAX_OPTIONAL_LEN,
}
OTHER_HEADERS_BUDGET = MAX_HEADER_BYTES - sum(len(name) + size + 4 for name, size in IDENTITY_HEADER_BUDGET.items())
if OTHER_HEADERS_BUDGET < 3 * 1024:                    # checked at import: a parser limit raised alone fails loudly
    raise RuntimeError("identity header limits leave under 3 KiB of the 16 KiB header budget")


def header_bytes(headers) -> int:
    return sum(len(k) + len(v) + 4 for k, v in headers)


def header_block_too_large(scope) -> bool:
    """AVR-732: the request's whole header block is over MAX_HEADER_BYTES (the middleware answers 431 before
    routing or identity). Sizes only: no header is decoded or interpreted."""
    return header_bytes(scope.get("headers", ())) > MAX_HEADER_BYTES


def _single_header(scope, wanted: bytes, limit: int) -> Optional[str]:
    """The one ASCII value of header `wanted` (lower case), or None when it is absent, repeated, non-ASCII or longer
    than `limit`."""
    found = [bytes(v) for k, v in scope.get("headers", ()) if bytes(k).lower() == wanted]
    if len(found) != 1 or len(found[0]) > limit:
        return None
    try:
        return found[0].decode("ascii").strip()
    except UnicodeDecodeError:
        return None


def intake_bearer_from_scope(scope) -> Optional[str]:
    """The Komga key intake's credential (app/intake.py): the token of a single `Authorization: Bearer <token>`
    header, or None. It identifies the enrollment stage as a caller, never a member, and confers no identity."""
    value = _single_header(scope, b"authorization", 600)
    if value is None or not value.startswith("Bearer "):
        return None
    token = value[len("Bearer "):].strip()
    return token or None


def intake_is_json(scope) -> bool:
    """The intake's body type: exactly one Content-Type whose bare type is application/json."""
    value = _single_header(scope, b"content-type", 100)
    return value is not None and value.split(";", 1)[0].strip().lower() == "application/json"


def has_identity_headers(scope) -> bool:
    """True when ANY header looks like an outpost identity header (used only to refuse the
    operator detail view; it grants nothing)."""
    for raw_name, _ in scope.get("headers", ()):
        name = raw_name.decode("latin-1").lower().replace("_", "-")
        if name.startswith("x-authentik") or name.startswith("x-forwarded") or name == "forwarded":
            return True
    return False
