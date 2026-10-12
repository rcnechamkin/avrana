"""Trusted member principal, built only from Authentik outpost headers.

Status: proposed, not deployed. Standard library only.

The principal is the ONLY way a member identity enters an adapter. It is built by exactly
one function, `principal_from_headers`, and that function fails closed: any problem with the
identity headers raises `PrincipalError` and no principal exists. There is no default, guest
or anonymous principal. Nothing downstream accepts a username from a query string, request
body, cookie or model output; adapters take a `MemberPrincipal`, never a string.

Trust model: the headers are only trustworthy because Gate G1 (private per-backend networks)
makes the Authentik outpost the only thing that can reach the application. Until G1 is applied
and verified in production this code must not read real member data.

Group parsing is deliberately identical in meaning to `services/avrana-portal/portal.py::
parse_groups`: Authentik joins groups with '|', ',' is tolerated, surrounding whitespace is
stripped, empty fragments are dropped, and matching is exact and case-sensitive.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class MemberPrincipal:
    username: str
    groups: frozenset
    email: Optional[str] = None
    name: Optional[str] = None
    _mint: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._mint is not _MINT:
            raise TypeError("MemberPrincipal can only be built by principal_from_headers")

    def has_group(self, group: str) -> bool:
        return group in self.groups

    def __repr__(self) -> str:  # never put identity in reprs that may reach logs
        return "MemberPrincipal(<redacted>)"


def parse_groups(raw: str) -> set:
    """Same semantics as the portal's parse_groups (exact, case-sensitive members)."""
    for sep in ("|", ","):
        raw = raw.replace(sep, "\n")
    return {g.strip() for g in raw.split("\n") if g.strip()}


def _occurrences(headers: HeaderInput, wanted: str) -> list:
    """All values for a header name, case-insensitive, across repeated entries."""
    wanted = wanted.lower()
    pairs = headers.items() if isinstance(headers, Mapping) else headers
    found = []
    for name, value in pairs:
        if not isinstance(name, str) or name.lower() != wanted:
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
    # control, format, surrogate, private-use and unassigned code points are never legitimate
    return any(unicodedata.category(c)[0] == "C" for c in text)


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
    if value is None or value == "" or len(value) > MAX_OPTIONAL_LEN or _bad_chars(value):
        return None
    return value


def principal_from_headers(headers: HeaderInput) -> MemberPrincipal:
    """Build the principal or raise PrincipalError. `headers` is a mapping whose values may be
    a str or a list of str, or an iterable of (name, value) pairs, so duplicates are visible."""
    username = _clean_username(_single(headers, USERNAME_HEADER, required=True))
    groups = _clean_groups(_single(headers, GROUPS_HEADER, required=True))
    return MemberPrincipal(
        username=username, groups=groups,
        email=_optional(headers, EMAIL_HEADER), name=_optional(headers, NAME_HEADER),
        _mint=_MINT)


def principal_or_none(headers: HeaderInput) -> Optional[MemberPrincipal]:
    try:
        return principal_from_headers(headers)
    except PrincipalError:
        return None
