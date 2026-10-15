"""D-3 proof of concept: prove identity with the outpost's signed JWT instead of trusting bare headers.

Status: PROPOSED, NOT WIRED IN, NOT DEPLOYED. Standard library only. See
docs/design/D3-outpost-identity-proof.md for the design, the Authentik 2026.5.6 source evidence and the
rollout/rollback plan. Nothing imports this module outside its tests.

Why: Gate G1 makes the Authentik outpost the only container that can reach a backend, but anything in the
host network namespace can still send forged X-authentik-* headers. The embedded outpost (2026.5.6) also
sends `X-authentik-jwt`: the raw OIDC ID token of the session (`internal/outpost/proxyv2/application/
mode_common.go`). For proxy providers that token is HS256-signed with the provider's client secret, because
Authentik resets their signing key to none at every startup (`authentik/providers/proxy/models.py`
`set_oauth_defaults`). Verifying the signature, and taking identity only from the verified claims, means a
forger needs the provider's client secret, not just network reach. The token itself may be seen by the
member (the outpost puts it in the browser's sign-out redirect); an HMAC does not reveal its key, whereas a
constant secret header carried in the token would have leaked, which is why that option was rejected.

Rules, all fail closed with a fixed reason code (never token content):
  * compact JWS only, ASCII base64url, bounded size, exactly three non-empty segments;
  * header: alg must equal the verifier's one configured algorithm (HS256 or RS256, never chosen by the
    token); `crit`, `jku`, `jwk`, `x5u`, `x5c` are refused (never fetch or accept a key from the token);
  * HS256: HMAC-SHA256 with the pinned client secret(s), constant-time comparison;
  * RS256: the key is chosen from the pinned set by `kid`, or the single pinned key when the token has no
    kid; RSASSA-PKCS1-v1_5 with SHA-256, signature length equal to the modulus length, representative < n,
    full encoded-message comparison in constant time (no partial parsing of the padding);
  * claims: iss and aud must match the provider, exp required, nbf/iat honoured with a small leeway,
    preferred_username a non-empty string, groups a list of strings; duplicate JSON keys are refused.
Rotation: pin the new secret or key next to the old one, then remove the old one after the session lifetime.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from typing import Callable, Iterable, Mapping, Optional

ALG = "RS256"
HMAC_ALG = "HS256"
MIN_HMAC_SECRET = 32
MAX_TOKEN_LEN = 16384
MIN_MODULUS_BITS = 2048
DEFAULT_LEEWAY = 60
_DIGEST_INFO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")
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
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (binascii.Error, ValueError):
        raise JwtRejected(reason) from None


def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("duplicate key")
        seen[key] = value
    return seen


def _json_object(raw: bytes, reason: str) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError):
        raise JwtRejected(reason) from None
    if not isinstance(value, dict):
        raise JwtRejected(reason)
    return value


class RsaPublicKey:
    """A pinned RSA public key. Build from the provider's JWKS entry (public data)."""

    __slots__ = ("kid", "n", "e", "size")

    def __init__(self, n: int, e: int, kid: Optional[str] = None):
        if not isinstance(n, int) or not isinstance(e, int) or n.bit_length() < MIN_MODULUS_BITS:
            raise ValueError("RSA modulus too small or malformed")
        if e < 3 or e % 2 == 0 or e >= n:
            raise ValueError("RSA exponent malformed")
        if kid is not None and (not isinstance(kid, str) or not kid):
            raise ValueError("kid malformed")
        self.n, self.e, self.kid = n, e, kid
        self.size = (n.bit_length() + 7) // 8

    @classmethod
    def from_jwk(cls, jwk: Mapping) -> "RsaPublicKey":
        if not isinstance(jwk, Mapping) or jwk.get("kty") != "RSA":
            raise ValueError("not an RSA JWK")
        if jwk.get("alg") not in (None, ALG) or jwk.get("use") not in (None, "sig"):
            raise ValueError("JWK is not for RS256 signatures")
        try:
            n = int.from_bytes(_b64url_decode(jwk["n"], "jwk"), "big")
            e = int.from_bytes(_b64url_decode(jwk["e"], "jwk"), "big")
        except (KeyError, TypeError, JwtRejected):
            raise ValueError("JWK n/e malformed") from None
        return cls(n, e, jwk.get("kid"))

    def verify(self, signing_input: bytes, signature: bytes) -> bool:
        if len(signature) != self.size:
            return False
        s = int.from_bytes(signature, "big")
        if s >= self.n:
            return False
        em = pow(s, self.e, self.n).to_bytes(self.size, "big")
        t = _DIGEST_INFO_SHA256 + hashlib.sha256(signing_input).digest()
        if self.size < len(t) + 11:
            return False
        expected = b"\x00\x01" + b"\xff" * (self.size - len(t) - 3) + b"\x00" + t
        return hmac.compare_digest(em, expected)


class OutpostJwtVerifier:
    """Verifies X-authentik-jwt for ONE proxy provider (one issuer, one client id).

    Exactly one mode, fixed at construction, so a token can never choose its own algorithm:
      * `hmac_secrets`: HS256 with the provider's client secret. This is what Authentik 2026.5.6 actually
        uses for proxy providers: `ProxyProvider.set_oauth_defaults()` sets `signing_key = None` at every
        startup, and `OAuth2Provider.jwt_key` then signs with the client secret (HS256).
      * `keys`: RS256 with pinned public keys, for a version or provider that signs with a keypair.
    Several secrets or keys are accepted only for rotation overlap.
    """

    def __init__(self, keys: Iterable[RsaPublicKey] = (), issuer: str = "", audience: str = "",
                 leeway: int = DEFAULT_LEEWAY, clock: Callable[[], float] = time.time,
                 hmac_secrets: Iterable[bytes] = ()):
        self.keys = list(keys)
        self.secrets = list(hmac_secrets)
        if bool(self.keys) == bool(self.secrets):
            raise ValueError("configure exactly one of: pinned RSA keys, HMAC secrets")
        if self.keys:
            if not all(isinstance(k, RsaPublicKey) for k in self.keys):
                raise ValueError("pinned keys must be RsaPublicKey")
            kids = [k.kid for k in self.keys]
            if len(self.keys) > 1 and (None in kids or len(set(kids)) != len(kids)):
                raise ValueError("several pinned keys need distinct kids")
            self.alg = ALG
        else:
            if not all(isinstance(s, bytes) and len(s) >= MIN_HMAC_SECRET for s in self.secrets):
                raise ValueError(f"HMAC secrets must be bytes of at least {MIN_HMAC_SECRET}")
            self.alg = HMAC_ALG
        if not issuer or not audience:
            raise ValueError("issuer and audience are required")
        self.issuer, self.audience, self.leeway, self.clock = issuer, audience, int(leeway), clock

    def _signature_ok(self, header: dict, signing_input: bytes, signature: bytes) -> bool:
        if self.alg == ALG:
            return self._key_for(header).verify(signing_input, signature)
        ok = False
        for secret in self.secrets:  # every secret is tried: no early exit on the first match
            mac = hmac.new(secret, signing_input, hashlib.sha256).digest()
            ok = hmac.compare_digest(mac, signature) or ok
        return ok

    def _key_for(self, header: dict) -> RsaPublicKey:
        kid = header.get("kid")
        if kid is None:
            if len(self.keys) == 1:
                return self.keys[0]
            raise JwtRejected("kid_required")
        if not isinstance(kid, str):
            raise JwtRejected("bad_header")
        for key in self.keys:
            if key.kid == kid:
                return key
        raise JwtRejected("unknown_kid")

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
        if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
            raise JwtRejected("bad_claims")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def principal_from_outpost(headers, verifier: OutpostJwtVerifier):
    """Build a MemberPrincipal from the VERIFIED token. The plain identity headers must agree with it,
    so a request that mixes a valid token with different headers is refused rather than reconciled."""
    from .principal import PrincipalError, _occurrences, principal_from_headers

    tokens = _occurrences(headers, "X-authentik-jwt")
    if len(tokens) != 1:
        raise PrincipalError("missing_header" if not tokens else "duplicate_header")
    try:
        claims = verifier.verify(tokens[0])
    except JwtRejected:
        raise PrincipalError("unverified_identity") from None
    principal = principal_from_headers({"X-authentik-username": claims["preferred_username"],
                                        "X-authentik-groups": "|".join(claims["groups"])})
    for name, expected in (("X-authentik-username", claims["preferred_username"]),
                           ("X-authentik-groups", "|".join(claims["groups"]))):
        sent = _occurrences(headers, name)
        if sent and (len(sent) != 1 or sent[0] != expected):
            raise PrincipalError("identity_mismatch")
    return principal
