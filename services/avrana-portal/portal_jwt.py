"""Trimmed, HS256-only copy of the Avrana outpost JWT verifier for the single-file portal (AVR-498).

Status: vendored from services/avrana-home/avrana_home/outpost_jwt.py. NOT enabled anywhere: the portal imports
this module only when AVRANA_IDENTITY_MODE is jwt_log_only or jwt_required. Standard library only.

Why a copy: the portal image holds plain files and no package path. The shared pieces below are copied
VERBATIM and tests/test_portal_jwt.py compares each one, by source, with the canonical module, and pins this
file's SHA-256, so drift in either direction fails verification. Only the HS256 mode exists here: no RSA, JWKS
or PEM code. The pieces that differ on purpose are `__init__` and `_signature_ok`.

Rules, all fail closed with a fixed reason code (never token content): see the canonical module's docstring.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import re
import time
from typing import Callable, Iterable

HMAC_ALG = "HS256"
MIN_HMAC_SECRET = 32
MAX_TOKEN_LEN = 16384
DEFAULT_LEEWAY = 60
MAX_LEEWAY = 300
_B64URL = re.compile(r"[A-Za-z0-9_-]+")
_FORBIDDEN_HEADER_KEYS = ("crit", "jku", "jwk", "x5u", "x5c")


class JwtRejected(Exception):
    """The token is not acceptable. `reason` is a fixed code, never token content."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _b64url_decode(segment: str, reason: str) -> bytes:
    if not segment or not _B64URL.fullmatch(segment) or len(segment) % 4 == 1:
        raise JwtRejected(reason)
    try:
        raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (binascii.Error, ValueError):
        raise JwtRejected(reason) from None
    # Canonical form only: non-zero trailing bits would let two strings carry the same bytes.
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != segment:
        raise JwtRejected(reason)
    return raw


def _no_constants(name):
    raise ValueError("non-finite number")


def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("duplicate key")
        seen[key] = value
    return seen


def _json_object(raw: bytes, reason: str) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constants)
    except (UnicodeDecodeError, ValueError):
        raise JwtRejected(reason) from None
    if not isinstance(value, dict):
        raise JwtRejected(reason)
    return value


class OutpostJwtVerifier:
    """Verifies X-authentik-jwt for ONE proxy provider (one issuer, one client id), HS256 only."""

    def __init__(self, issuer: str = "", audience: str = "", hmac_secrets: Iterable[bytes] = (),
                 leeway: int = DEFAULT_LEEWAY, clock: Callable[[], float] = time.time):
        self.secrets = list(hmac_secrets)
        if not self.secrets:
            raise ValueError("configure at least one HMAC secret")
        if not all(isinstance(s, bytes) and len(s) >= MIN_HMAC_SECRET for s in self.secrets):
            raise ValueError(f"HMAC secrets must be bytes of at least {MIN_HMAC_SECRET}")
        self.alg = HMAC_ALG
        if not issuer or not audience:
            raise ValueError("issuer and audience are required")
        if not isinstance(leeway, int) or isinstance(leeway, bool) or not 0 <= leeway <= MAX_LEEWAY:
            raise ValueError(f"leeway must be an integer 0..{MAX_LEEWAY} seconds")
        if not isinstance(issuer, str) or not isinstance(audience, str):
            raise ValueError("issuer and audience must be strings")
        self.issuer, self.audience, self.leeway, self.clock = issuer, audience, leeway, clock

    def _signature_ok(self, header: dict, signing_input: bytes, signature: bytes) -> bool:
        ok = False
        for secret in self.secrets:  # every secret is tried: no early exit on the first match
            mac = hmac.new(secret, signing_input, hashlib.sha256).digest()
            ok = hmac.compare_digest(mac, signature) or ok
        return ok

    def verify(self, token) -> dict:
        if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LEN or not token.isascii():
            raise JwtRejected("malformed_token")
        parts = token.split(".")
        if len(parts) != 3:
            raise JwtRejected("malformed_token")
        header = _json_object(_b64url_decode(parts[0], "malformed_token"), "bad_header")
        if header.get("alg") != self.alg:
            raise JwtRejected("bad_alg")
        if any(k in header for k in _FORBIDDEN_HEADER_KEYS):
            raise JwtRejected("bad_header")
        signature = _b64url_decode(parts[2], "malformed_token")
        if not self._signature_ok(header, (parts[0] + "." + parts[1]).encode("ascii"), signature):
            raise JwtRejected("bad_signature")
        claims = _json_object(_b64url_decode(parts[1], "malformed_token"), "bad_claims")
        self._check_claims(claims)
        return claims

    def _check_claims(self, claims: dict) -> None:
        now = self.clock()
        if claims.get("iss") != self.issuer:
            raise JwtRejected("bad_issuer")
        aud = claims.get("aud")
        if not (aud == self.audience or (isinstance(aud, list) and self.audience in aud
                                         and all(isinstance(a, str) for a in aud))):
            raise JwtRejected("bad_audience")
        exp = claims.get("exp")
        if not _is_number(exp):
            raise JwtRejected("bad_claims")
        if now >= exp + self.leeway:
            raise JwtRejected("expired")
        iat = claims.get("iat")
        if not _is_number(iat):  # iat is required: Authentik ID tokens always carry it
            raise JwtRejected("bad_claims")
        if iat > exp:
            raise JwtRejected("bad_claims")
        for name in ("nbf", "iat"):
            if name in claims:
                if not _is_number(claims[name]):
                    raise JwtRejected("bad_claims")
                if claims[name] > now + self.leeway:
                    raise JwtRejected("not_yet_valid")
        user = claims.get("preferred_username")
        groups = claims.get("groups")
        if not isinstance(user, str) or not user:
            raise JwtRejected("bad_claims")
        if (not isinstance(groups, list) or not groups
                or not all(_is_group_name(g) for g in groups)):
            raise JwtRejected("bad_claims")


def _is_group_name(value) -> bool:
    # A name that contains a separator or edge whitespace would split differently in the "|"-joined header
    # and in OliveTin's space/comma handling, so it could become a different group: refuse it.
    return (isinstance(value, str) and value != "" and value == value.strip()
            and not any(sep in value for sep in "|,"))


def _is_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))
