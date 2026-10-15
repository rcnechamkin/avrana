"""Trusted member principal, built only from Authentik outpost headers.

Status: proposed, not deployed. Standard library only.

The principal is the ONLY way a member identity enters an adapter. It is built by exactly
one function, `principal_from_headers`, and that function fails closed: any problem with the
identity headers raises `PrincipalError` and no principal exists. There is no default, guest
or anonymous principal. Nothing downstream accepts a username from a query string, request
body, cookie or model output; adapters take a `MemberPrincipal`, never a string.

Construction guarantee (stated honestly): there is no SUPPORTED construction path other than the
header parser, and accidental or careless copies with changed fields are rejected: the class is
not a dataclass (so `dataclasses.replace` fails), cannot be subclassed, cannot be called directly,
is immutable, and cannot be copied or pickled into a different identity. Consumers check
`is_minted_principal` (exact type plus the parser's seal). Python cannot stop code that is
already running in this process from using `object.__new__` and `object.__setattr__`; that is
out of scope, and such code could equally edit the headers parser itself.

Trust model: the headers are only trustworthy because Gate G1 (private per-backend networks)
makes the Authentik outpost the only thing that can reach the application. Until G1 is applied
and verified in production this code must not read real member data.

Group parsing is deliberately identical in meaning to `services/avrana-portal/portal.py::
parse_groups`: Authentik joins groups with '|', ',' is tolerated, surrounding whitespace is
stripped, empty fragments are dropped, and matching is exact and case-sensitive.
"""
from __future__ import annotations

import unicodedata
from typing import Iterable, Mapping, Optional, Sequence, Union

USERNAME_HEADER = "X-authentik-username"
GROUPS_HEADER = "X-authentik-groups"
EMAIL_HEADER = "X-authentik-email"
NAME_HEADER = "X-authentik-name"

MAX_USERNAME_LEN = 150      # Authentik's own username limit
MAX_GROUPS_HEADER_LEN = 4096
MAX_GROUPS = 64
MAX_GROUP_LEN = 128
MAX_OPTIONAL_LEN = 254

_MINT = object()  # construction guard: only this module hands it out


class PrincipalError(Exception):
    """No principal could be built. `reason` is a fixed code, never header content."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


HeaderInput = Union[Mapping[str, Union[str, Sequence[str]]], Iterable[tuple]]


class MemberPrincipal:
    """Immutable, parser-minted identity. Not constructible, subclassable, copyable or replaceable."""

    __slots__ = ("username", "groups", "email", "name", "_sealed")

    def __init__(self, *args, **kwargs):
        raise TypeError("MemberPrincipal can only be built by principal_from_headers")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("MemberPrincipal cannot be subclassed")

    def __setattr__(self, name, value):
        raise AttributeError("MemberPrincipal is immutable")

    def __delattr__(self, name):
        raise AttributeError("MemberPrincipal is immutable")

    def __reduce__(self):
        raise TypeError("MemberPrincipal cannot be pickled or copied into another identity")

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __eq__(self, other):
        return (type(other) is MemberPrincipal and self.username == other.username
                and self.groups == other.groups)

    def __hash__(self):
        return hash((self.username, self.groups))

    def has_group(self, group: str) -> bool:
        return group in self.groups

    def __repr__(self) -> str:  # never put identity in reprs that may reach logs
        return "MemberPrincipal(<redacted>)"

    __str__ = __repr__


def _mint_principal(username, groups, email, name) -> MemberPrincipal:
    p = object.__new__(MemberPrincipal)
    for attr, value in (("username", username), ("groups", groups), ("email", email),
                        ("name", name), ("_sealed", _MINT)):
        object.__setattr__(p, attr, value)
    return p


def is_minted_principal(value) -> bool:
    """True only for an exact MemberPrincipal that the header parser produced."""
    try:
        return type(value) is MemberPrincipal and object.__getattribute__(value, "_sealed") is _MINT
    except AttributeError:
        return False


def parse_groups(raw: str) -> set:
    """Same semantics as the portal's parse_groups (exact, case-sensitive members)."""
    for sep in ("|", ","):
        raw = raw.replace(sep, "\n")
    return {g.strip() for g in raw.split("\n") if g.strip()}


def _occurrences(headers: HeaderInput, wanted: str) -> list:
    """All values for a header name, case-insensitive, across repeated entries."""
    wanted = wanted.lower()
    if isinstance(headers, Mapping):
        pairs = list(headers.items())
    elif isinstance(headers, (list, tuple)):
        pairs = headers
    else:
        raise PrincipalError("malformed_input")
    found = []
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise PrincipalError("malformed_input")
        name, value = pair
        if not isinstance(name, str):
            raise PrincipalError("malformed_input")     # a header with a non-text name is never skipped
        if name.lower() != wanted:
            continue
        if isinstance(value, (list, tuple)):
            found.extend(value)
        else:
            found.append(value)
    return found


def _single(headers: HeaderInput, name: str, required: bool) -> Optional[str]:
    values = _occurrences(headers, name)
    if len(values) > 1:
        raise PrincipalError("duplicate_header")
    if not values:
        if required:
            raise PrincipalError("missing_header")
        return None
    value = values[0]
    if not isinstance(value, str):
        raise PrincipalError("malformed_header")
    return value


def _bad_chars(text: str) -> bool:
    """Control, format, surrogate, private-use and unassigned code points; line and paragraph
    separators; and every space other than the ordinary ASCII space (NBSP, em space, ideographic
    space, ...) are never legitimate in an identity."""
    for c in text:
        cat = unicodedata.category(c)
        if cat[0] == "C" or cat in ("Zl", "Zp") or (cat == "Zs" and c != " "):
            return True
    return False


def _clean_username(raw: str) -> str:
    if raw == "":
        raise PrincipalError("empty_header")
    if len(raw) > MAX_USERNAME_LEN:
        raise PrincipalError("oversized_header")
    if raw != raw.strip():
        raise PrincipalError("malformed_header")
    if _bad_chars(raw) or "|" in raw or "," in raw or "\n" in raw:
        raise PrincipalError("malformed_header")
    if unicodedata.normalize("NFC", raw) != raw:
        raise PrincipalError("malformed_header")
    return raw


def _clean_groups(raw: str) -> frozenset:
    if raw.strip() == "":
        raise PrincipalError("empty_header")
    if len(raw) > MAX_GROUPS_HEADER_LEN:
        raise PrincipalError("oversized_header")
    if _bad_chars(raw):
        raise PrincipalError("malformed_header")
    groups = parse_groups(raw)
    if not groups:
        raise PrincipalError("empty_header")
    if len(groups) > MAX_GROUPS or any(len(g) > MAX_GROUP_LEN for g in groups):
        raise PrincipalError("oversized_header")
    return frozenset(groups)


def _optional(headers: HeaderInput, name: str) -> Optional[str]:
    """Display-only extras. Any problem drops the value; it never decides identity."""
    try:
        value = _single(headers, name, required=False)
    except PrincipalError:
        return None
    if value is None:
        return None
    value = value.strip()
    if value == "" or len(value) > MAX_OPTIONAL_LEN or _bad_chars(value):
        return None
    return value


def principal_from_headers(headers: HeaderInput) -> MemberPrincipal:
    """Build the principal or raise PrincipalError. `headers` is a mapping whose values may be
    a str or a list of str, or an iterable of (name, value) pairs, so duplicates are visible."""
    username = _clean_username(_single(headers, USERNAME_HEADER, required=True))
    groups = _clean_groups(_single(headers, GROUPS_HEADER, required=True))
    return _mint_principal(username, groups, _optional(headers, EMAIL_HEADER),
                           _optional(headers, NAME_HEADER))


def principal_or_none(headers) -> Optional[MemberPrincipal]:
    try:
        return principal_from_headers(headers)
    except PrincipalError:
        return None


def principal_from_raw_headers(raw_headers) -> MemberPrincipal:
    """Build the principal from the RAW header list of the server (a list of `(bytes, bytes)`
    pairs, as ASGI provides), so duplicates stay visible and nothing is decoded loosely.

    Decoding is strict: header names must be ASCII; the identity headers (`X-authentik-username`,
    `X-authentik-groups`) must be pure ASCII, so any non-ASCII or non-UTF-8 value, including the
    latin-1 mojibake a lenient decoder would produce, yields no principal. The display-only headers
    are decoded as strict UTF-8 and silently dropped if they are not. Raises PrincipalError."""
    if not isinstance(raw_headers, (list, tuple)):
        raise PrincipalError("malformed_input")
    identity = {USERNAME_HEADER.lower().encode("ascii"), GROUPS_HEADER.lower().encode("ascii")}
    display = {EMAIL_HEADER.lower().encode("ascii"), NAME_HEADER.lower().encode("ascii")}
    pairs = []
    for pair in raw_headers:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise PrincipalError("malformed_input")
        name, value = pair
        if not isinstance(name, (bytes, bytearray)) or not isinstance(value, (bytes, bytearray)):
            raise PrincipalError("malformed_input")
        try:
            lname = bytes(name).decode("ascii").lower()
        except UnicodeDecodeError:
            raise PrincipalError("malformed_input") from None
        key = lname.encode("ascii")
        if key in identity:
            try:
                pairs.append((lname, bytes(value).decode("ascii")))
            except UnicodeDecodeError:
                raise PrincipalError("malformed_header") from None
        elif key in display:
            try:
                pairs.append((lname, bytes(value).decode("utf-8")))
            except UnicodeDecodeError:
                pairs.append((lname, "\x00"))          # dropped by the display-only cleaner
    return principal_from_headers(pairs)


# --- Verified-JWT identity (AVR-498). Additive: nothing above this line changed. -----------------------
#
# `principal_from_verified_jwt` mints the SAME MemberPrincipal as `principal_from_headers`, from the claims
# of a token that `outpost_jwt.OutpostJwtVerifier` has verified (signature, algorithm, issuer, audience,
# expiry). The plain identity headers are never a source of identity on this path; if they are present they
# must agree with the claims, otherwise the request is refused. `principal_for_request` is the one entry
# point a service should call: the mode is an explicit argument with NO default, so JWT enforcement can
# never switch on (or off) by omission. Offline only; nothing here is wired into a service.

JWT_HEADER = "X-authentik-jwt"
MODE_HEADERS = "headers"            # today's behaviour: identity from the plain headers
MODE_JWT_LOG_ONLY = "jwt_log_only"  # serve from headers, verify the token and report a reason code
MODE_JWT_REQUIRED = "jwt_required"  # identity only from a verified token; header-only requests refused
IDENTITY_MODES = (MODE_HEADERS, MODE_JWT_LOG_ONLY, MODE_JWT_REQUIRED)


def _claim_text(claims, name: str, limit: int) -> Optional[str]:
    value = claims.get(name)
    if not isinstance(value, str) or value == "" or len(value) > limit or _bad_chars(value):
        return None
    return value


def principal_from_verified_jwt(headers: HeaderInput, verifier) -> MemberPrincipal:
    """Verify `X-authentik-jwt` with `verifier` (anything with `.verify(token) -> claims` that raises on
    any problem) and mint the principal from the verified claims only. Raises PrincipalError with a fixed
    reason: missing_header, duplicate_header, malformed_header, unverified_identity (the verifier refused
    for any reason), identity_mismatch (plain headers disagree with the claims), and the same
    empty/oversized/malformed codes as the header path for the username and groups."""
    tokens = _occurrences(headers, JWT_HEADER)
    if not tokens:
        raise PrincipalError("missing_header")
    if len(tokens) != 1:
        raise PrincipalError("duplicate_header")
    if not isinstance(tokens[0], str):
        raise PrincipalError("malformed_header")
    try:
        claims = verifier.verify(tokens[0])
    except Exception:  # every verifier failure, expected or not, is the same closed answer
        raise PrincipalError("unverified_identity") from None
    if not isinstance(claims, Mapping):
        raise PrincipalError("unverified_identity")
    raw_user, raw_groups = claims.get("preferred_username"), claims.get("groups")
    if not isinstance(raw_user, str) or not isinstance(raw_groups, (list, tuple)) or not all(
            isinstance(g, str) and g == g.strip() and g and "|" not in g and "," not in g for g in raw_groups):
        raise PrincipalError("malformed_header")
    username = _clean_username(raw_user)
    groups = _clean_groups("|".join(raw_groups))
    if groups != frozenset(raw_groups):
        raise PrincipalError("malformed_header")  # a group was altered or dropped by parsing: refuse
    for name, expected in ((USERNAME_HEADER, username), (GROUPS_HEADER, "|".join(raw_groups))):
        sent = _occurrences(headers, name)
        if sent and (len(sent) != 1 or not isinstance(sent[0], str)
                     or (sent[0] != expected and (name == USERNAME_HEADER
                                                  or parse_groups(sent[0]) != set(groups)))):
            raise PrincipalError("identity_mismatch")
    return _mint_principal(username, groups, _claim_text(claims, "email", MAX_OPTIONAL_LEN),
                           _claim_text(claims, "name", MAX_OPTIONAL_LEN))


def principal_for_request(headers: HeaderInput, *, mode: str, verifier=None, report=None) -> MemberPrincipal:
    """The single entry point for services. `mode` is required (no default) and must be one of
    IDENTITY_MODES; anything else, or a JWT mode without a verifier, fails closed.

    headers       -> `principal_from_headers` (unchanged behaviour).
    jwt_log_only  -> still serves the header principal, but also runs the verified path and calls
                     `report(code)` with a fixed code: "ok", "mismatch" or a PrincipalError reason.
                     Reporting never changes the outcome and never carries token or identity content.
    jwt_required  -> `principal_from_verified_jwt` only; a request with identity headers but no valid token
                     is refused."""
    if mode not in IDENTITY_MODES:
        raise PrincipalError("bad_mode")
    if mode == MODE_HEADERS:
        return principal_from_headers(headers)
    if verifier is None:
        raise PrincipalError("misconfigured")
    if mode == MODE_JWT_REQUIRED:
        return principal_from_verified_jwt(headers, verifier)
    served = principal_from_headers(headers)
    try:
        code = "ok" if principal_from_verified_jwt(headers, verifier) == served else "mismatch"
    except PrincipalError as exc:
        code = exc.reason
    try:
        if report is not None:
            report(code)
    except Exception:
        pass
    return served
