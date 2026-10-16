"""D-3 proof of concept tests (offline, synthetic keys and identities, standard library only).

RSA keys are generated here in pure Python from a fixed seed, so no key material is stored in the
repository and nothing is fetched. Tokens are shaped like the Authentik 2026.5.6 proxy-provider ID token
(iss, aud = client id, exp, iat, preferred_username, groups); every value is invented.
"""
import base64
import hashlib
import hmac
import json
import random
import unittest

from avrana_home import outpost_jwt as oj
from avrana_home.principal import PrincipalError, is_minted_principal

ISS = "https://auth.example.test/application/o/avrana-portal/"
AUD = "synthetic-portal-client-id"
NOW = 1_800_000_000


def _probable_prime(bits, rng):
    small = [p for p in range(3, 2000, 2) if all(p % q for q in range(3, int(p ** 0.5) + 1, 2))]
    while True:
        n = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if any(n % p == 0 for p in small):
            continue
        d, r = n - 1, 0
        while d % 2 == 0:
            d, r = d // 2, r + 1
        for _ in range(24):
            x = pow(rng.randrange(2, n - 2), d, n)
            if x in (1, n - 1):
                continue
            for _ in range(r - 1):
                x = pow(x, 2, n)
                if x == n - 1:
                    break
            else:
                break
        else:
            return n


def make_key(seed, kid=None, bits=2048):
    rng = random.Random(seed)
    e = 65537
    while True:
        p, q = _probable_prime(bits // 2, rng), _probable_prime(bits // 2, rng)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e and (p * q).bit_length() == bits:
            n = p * q
            return {"n": n, "e": e, "d": pow(e, -1, phi), "kid": kid}


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign(key, header, claims, raw_header=None, raw_claims=None):
    h = raw_header if raw_header is not None else b64(json.dumps(header).encode())
    c = raw_claims if raw_claims is not None else b64(json.dumps(claims).encode())
    k = (key["n"].bit_length() + 7) // 8
    t = oj._DIGEST_INFO_SHA256 + hashlib.sha256(f"{h}.{c}".encode()).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    s = pow(int.from_bytes(em, "big"), key["d"], key["n"]).to_bytes(k, "big")
    return f"{h}.{c}.{b64(s)}"


def claims(**over):
    base = {"iss": ISS, "aud": AUD, "exp": NOW + 3600, "iat": NOW - 10, "sub": "synthetic-sub",
            "preferred_username": "member-a", "groups": ["avrana-users", "avrana-books"]}
    base.update(over)
    return {k: v for k, v in base.items() if v is not ...}


def pub(key):
    return oj.RsaPublicKey(key["n"], key["e"], key["kid"])


KEY_A = make_key(1, kid="kid-a")
KEY_B = make_key(2, kid="kid-b")
HDR_A = {"alg": "RS256", "typ": "JWT", "kid": "kid-a"}


def verifier(*keys, **kw):
    return oj.OutpostJwtVerifier([pub(k) for k in (keys or (KEY_A,))], ISS, AUD, clock=lambda: NOW, **kw)


class AcceptTests(unittest.TestCase):
    def test_valid_token_is_accepted_and_claims_returned(self):
        got = verifier().verify(sign(KEY_A, HDR_A, claims()))
        self.assertEqual((got["preferred_username"], got["groups"]), ("member-a", ["avrana-users", "avrana-books"]))

    def test_single_pinned_key_accepts_a_token_without_kid(self):
        self.assertTrue(verifier().verify(sign(KEY_A, {"alg": "RS256"}, claims())))

    def test_audience_list_containing_the_client_id(self):
        self.assertTrue(verifier().verify(sign(KEY_A, HDR_A, claims(aud=[AUD, "other"]))))

    def test_leeway_allows_small_clock_skew(self):
        self.assertTrue(verifier().verify(sign(KEY_A, HDR_A, claims(exp=NOW - 30, iat=NOW - 3600))))

    def test_jwk_round_trip(self):
        jwk = {"kty": "RSA", "alg": "RS256", "use": "sig", "kid": "kid-a",
               "n": b64(KEY_A["n"].to_bytes(256, "big")), "e": b64(KEY_A["e"].to_bytes(3, "big"))}
        v = oj.OutpostJwtVerifier([oj.RsaPublicKey.from_jwk(jwk)], ISS, AUD, clock=lambda: NOW)
        self.assertTrue(v.verify(sign(KEY_A, HDR_A, claims())))


class RejectTests(unittest.TestCase):
    def rejects(self, token, reason, v=None):
        with self.assertRaises(oj.JwtRejected) as caught:
            (v or verifier()).verify(token)
        self.assertEqual(caught.exception.reason, reason)

    def test_forged_headers_without_a_key_cannot_produce_a_token(self):
        good = sign(KEY_A, HDR_A, claims())
        h, c, s = good.split(".")
        forged_claims = b64(json.dumps(claims(groups=["authentik Admins"])).encode())
        self.rejects(f"{h}.{forged_claims}.{s}", "bad_signature")
        self.rejects(sign(make_key(3, kid="kid-a"), HDR_A, claims()), "bad_signature")

    def test_header_tampering_breaks_the_signature(self):
        h, c, s = sign(KEY_A, HDR_A, claims()).split(".")
        self.rejects(f"{b64(json.dumps(dict(HDR_A, typ='at+jwt')).encode())}.{c}.{s}", "bad_signature")

    def test_alg_none_and_hmac_confusion(self):
        c = b64(json.dumps(claims()).encode())
        none = b64(json.dumps({"alg": "none"}).encode())
        self.rejects(none + "." + c + ".", "bad_alg")
        self.rejects(none + "." + c + ".AA", "bad_alg")
        h = b64(json.dumps({"alg": "HS256", "kid": "kid-a"}).encode())
        mac = hmac.new(KEY_A["n"].to_bytes(256, "big"), f"{h}.{c}".encode(), hashlib.sha256).digest()
        self.rejects(f"{h}.{c}.{b64(mac)}", "bad_alg")
        for alg in ("rs256", "RS256 ", "PS256", "RS512", None, ["RS256"]):
            self.rejects(sign(KEY_A, {"alg": alg, "kid": "kid-a"}, claims()), "bad_alg")

    def test_key_material_in_the_token_is_never_used(self):
        for extra in ({"jku": "https://evil.example/jwks"}, {"x5u": "https://evil.example/c"},
                      {"jwk": {"kty": "RSA"}}, {"x5c": ["AA"]}, {"crit": ["exp"]}):
            self.rejects(sign(KEY_A, dict(HDR_A, **extra), claims()), "bad_header")

    def test_kid_selection(self):
        self.rejects(sign(KEY_A, dict(HDR_A, kid="unknown"), claims()), "unknown_kid")
        self.rejects(sign(KEY_A, {"alg": "RS256"}, claims()), "kid_required", verifier(KEY_A, KEY_B))
        self.rejects(sign(KEY_A, dict(HDR_A, kid=5), claims()), "bad_header")
        # A valid signature by key A presented under key B's kid is checked against B: refused.
        self.rejects(sign(KEY_A, dict(HDR_A, kid="kid-b"), claims()), "bad_signature", verifier(KEY_A, KEY_B))

    def test_signature_shape(self):
        h, c, s = sign(KEY_A, HDR_A, claims()).split(".")
        raw = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        self.rejects(f"{h}.{c}.{b64(raw[:-1])}", "bad_signature")
        self.rejects(h + "." + c + "." + b64(bytes(1) + raw), "bad_signature")
        self.rejects(f"{h}.{c}.{b64(KEY_A['n'].to_bytes(256, 'big'))}", "bad_signature")   # s == n
        self.rejects(f"{h}.{c}.{b64(bytes(256))}", "bad_signature")

    def test_malformed_padding_with_the_right_hash_is_refused(self):
        """Signed with the REAL key, correct SHA-256 at the end, wrong PKCS#1 structure: every variant must
        fail, so the verifier compares the whole encoded message rather than parsing it loosely."""
        h = b64(json.dumps(HDR_A).encode())
        c = b64(json.dumps(claims()).encode())
        digest = hashlib.sha256(f"{h}.{c}".encode()).digest()
        t = oj._DIGEST_INFO_SHA256 + digest
        k = 256
        variants = {
            "block type 2": b"\x00\x02" + b"\xff" * (k - len(t) - 3) + b"\x00" + t,
            "no separator": b"\x00\x01" + b"\xff" * (k - len(t) - 2) + t,
            "garbage in padding": b"\x00\x01" + b"\xff" * 10 + b"\x41" * (k - len(t) - 13) + b"\x00" + t,
            "bare digest": b"\x00\x01" + b"\xff" * (k - len(digest) - 3) + b"\x00" + digest,
            "sha1 digestinfo": b"\x00\x01" + b"\xff" * (k - 35 - 3) + b"\x00"
                               + bytes.fromhex("3021300906052b0e03021a05000414") + digest[:20],
        }
        for name, em in variants.items():
            with self.subTest(variant=name):
                self.assertEqual(len(em), k)
                s = pow(int.from_bytes(em, "big"), KEY_A["d"], KEY_A["n"]).to_bytes(k, "big")
                self.rejects(f"{h}.{c}.{b64(s)}", "bad_signature")

    def test_claims(self):
        cases = {
            "bad_issuer": [claims(iss="https://auth.example.test/application/o/other/"), claims(iss=...)],
            "bad_audience": [claims(aud="other"), claims(aud=["other"]), claims(aud=...), claims(aud=[AUD, 5])],
            "expired": [claims(exp=NOW - 61)],
            "not_yet_valid": [claims(nbf=NOW + 61), claims(iat=NOW + 61)],
            "bad_claims": [claims(exp=...), claims(exp="9999999999"), claims(exp=True), claims(nbf="0"),
                           claims(preferred_username=...), claims(preferred_username=""),
                           claims(preferred_username=["member-a"]), claims(groups=...),
                           claims(groups="authentik Admins"), claims(groups=["ok", 5]),
                           claims(groups=[""]), claims(groups=["avrana-users|authentik Admins"]),
                           claims(groups=["avrana-users,authentik Admins"]), claims(groups=[" authentik Admins"]),
                           claims(groups=["authentik Admins\t"]), claims(exp=float("nan")),
                           claims(exp=float("inf")), claims(iat=float("-inf")),
                           claims(sub=float("nan"))],
        }
        for reason, payloads in cases.items():
            for payload in payloads:
                with self.subTest(reason=reason, payload=payload):
                    self.rejects(sign(KEY_A, HDR_A, payload), reason)

    def test_malformed_tokens(self):
        good = sign(KEY_A, HDR_A, claims())
        for bad in (None, 5, b"x", "", "a.b", good + ".x", good.replace(".", "..", 1), good + "=",
                    good[:-2] + "+/", "é" + good, "x" * (oj.MAX_TOKEN_LEN + 1)):
            with self.subTest(bad=str(bad)[:20]):
                self.rejects(bad, "malformed_token")

    def test_group_names_with_inner_spaces_are_kept_whole(self):
        got = verifier().verify(sign(KEY_A, HDR_A, claims(groups=["authentik Admins"])))
        self.assertEqual(got["groups"], ["authentik Admins"])

    def test_non_finite_numbers_spelled_as_json_overflow(self):
        raw = json.dumps(claims())[:-1] + ', "nbf": 1e999}'
        self.rejects(sign(KEY_A, HDR_A, None, raw_claims=b64(raw.encode())), "bad_claims")

    def test_non_canonical_base64_is_refused(self):
        good = sign(KEY_A, HDR_A, claims())
        h, c, s = good.split(".")
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        checked = []
        for name, seg in (("header", h), ("claims", c), ("signature", s)):
            if len(seg) % 4 == 0:
                continue  # no spare bits in this segment
            spare = 2 if len(seg) % 4 == 2 else 4  # unused low bits in the last character
            i = alphabet.index(seg[-1])
            twin = seg[:-1] + alphabet[i | ((1 << spare) - 1)] if i & ((1 << spare) - 1) == 0 else None
            if twin is None:
                continue
            self.assertEqual(base64.urlsafe_b64decode(twin + "=" * (-len(twin) % 4)),
                             base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
            parts = {"header": (twin, c, s), "claims": (h, twin, s), "signature": (h, c, twin)}[name]
            checked.append(name)
            with self.subTest(segment=name):
                self.rejects(".".join(parts), "malformed_token")
        self.assertIn("signature", checked)  # a 2048-bit signature always has spare bits

    def test_duplicate_json_keys_and_non_objects(self):
        dup = b'{"alg":"RS256","alg":"none"}'
        self.rejects(sign(KEY_A, None, claims(), raw_header=b64(dup)), "bad_header")
        self.rejects(sign(KEY_A, None, claims(), raw_header=b64(b'["RS256"]')), "bad_header")
        dup_claims = json.dumps(claims())[:-1] + ', "preferred_username": "admin"}'
        self.rejects(sign(KEY_A, HDR_A, None, raw_claims=b64(dup_claims.encode())), "bad_claims")
        self.rejects(sign(KEY_A, HDR_A, None, raw_claims=b64(b"[1]")), "bad_claims")

    def test_rejection_reasons_never_carry_token_content(self):
        try:
            verifier().verify(sign(KEY_A, HDR_A, claims(preferred_username=..., groups=["secret-group"])))
        except oj.JwtRejected as exc:
            self.assertNotIn("secret-group", str(exc))


class RotationTests(unittest.TestCase):
    def test_overlap_then_retire(self):
        old_token = sign(KEY_A, HDR_A, claims())
        new_token = sign(KEY_B, {"alg": "RS256", "kid": "kid-b"}, claims())
        overlap = verifier(KEY_A, KEY_B)
        self.assertTrue(overlap.verify(old_token) and overlap.verify(new_token))
        retired = verifier(KEY_B)
        self.assertTrue(retired.verify(new_token))
        with self.assertRaises(oj.JwtRejected):
            retired.verify(old_token)
        # Rollback is restoring the previous pin set: old tokens verify again.
        self.assertTrue(verifier(KEY_A).verify(old_token))

    def test_verifier_configuration_fails_closed(self):
        for bad in ([], [object()]):
            with self.assertRaises(ValueError):
                oj.OutpostJwtVerifier(bad, ISS, AUD)
        with self.assertRaises(ValueError):
            oj.OutpostJwtVerifier([pub(dict(KEY_A, kid=None)), pub(dict(KEY_B, kid=None))], ISS, AUD)
        with self.assertRaises(ValueError):
            oj.OutpostJwtVerifier([pub(KEY_A)], "", AUD)
        with self.assertRaises(ValueError):
            oj.RsaPublicKey(make_key(4, bits=1024)["n"], 65537)
        with self.assertRaises(ValueError):
            oj.RsaPublicKey(KEY_A["n"], 4)
        for jwk in ({"kty": "EC"}, {"kty": "RSA", "n": "!!", "e": "AQAB"}, {"kty": "RSA", "alg": "HS256", "n": "AA", "e": "AQAB"}):
            with self.assertRaises(ValueError):
                oj.RsaPublicKey.from_jwk(jwk)


SECRET_1 = b"synthetic-client-secret-one-" + b"x" * 40
SECRET_2 = b"synthetic-client-secret-two-" + b"y" * 40


def hs_sign(secret, header, payload):
    h = b64(json.dumps(header).encode())
    c = b64(json.dumps(payload).encode())
    return f"{h}.{c}.{b64(hmac.new(secret, f'{h}.{c}'.encode(), hashlib.sha256).digest())}"


def hs_verifier(*secrets):
    return oj.OutpostJwtVerifier(issuer=ISS, audience=AUD, clock=lambda: NOW,
                                 hmac_secrets=secrets or (SECRET_1,))


class Hs256Tests(unittest.TestCase):
    """Authentik 2026.5.6 proxy providers: HS256 with the client secret (no kid)."""

    def rejects(self, token, reason, v=None):
        with self.assertRaises(oj.JwtRejected) as caught:
            (v or hs_verifier()).verify(token)
        self.assertEqual(caught.exception.reason, reason)

    def test_valid_token(self):
        got = hs_verifier().verify(hs_sign(SECRET_1, {"alg": "HS256", "typ": "JWT"}, claims()))
        self.assertEqual(got["preferred_username"], "member-a")

    def test_wrong_secret_and_tampering(self):
        self.rejects(hs_sign(SECRET_2, {"alg": "HS256"}, claims()), "bad_signature")
        h, c, s = hs_sign(SECRET_1, {"alg": "HS256"}, claims()).split(".")
        forged = b64(json.dumps(claims(groups=["authentik Admins"])).encode())
        self.rejects(f"{h}.{forged}.{s}", "bad_signature")
        self.rejects(f"{h}.{c}.{s[:-3]}", "bad_signature")   # 30-byte MAC: wrong length

    def test_the_mode_is_fixed_by_configuration_not_by_the_token(self):
        self.rejects(sign(KEY_A, HDR_A, claims()), "bad_alg")                      # RS256 to an HS verifier
        with self.assertRaises(oj.JwtRejected) as caught:                         # HS256 to an RS verifier
            verifier().verify(hs_sign(SECRET_1, {"alg": "HS256"}, claims()))
        self.assertEqual(caught.exception.reason, "bad_alg")
        none = b64(json.dumps({"alg": "none"}).encode())
        self.rejects(none + "." + b64(json.dumps(claims()).encode()) + ".", "bad_alg")
        for alg in ("hs256", "HS384", "HS512", None):
            self.rejects(hs_sign(SECRET_1, {"alg": alg}, claims()), "bad_alg")

    def test_claims_are_checked_in_hmac_mode_too(self):
        self.rejects(hs_sign(SECRET_1, {"alg": "HS256"}, claims(aud="other-provider")), "bad_audience")
        self.rejects(hs_sign(SECRET_1, {"alg": "HS256"}, claims(exp=NOW - 61)), "expired")

    def test_secret_rotation_overlap_and_rollback(self):
        old, new = (hs_sign(s, {"alg": "HS256"}, claims()) for s in (SECRET_1, SECRET_2))
        both = hs_verifier(SECRET_1, SECRET_2)
        self.assertTrue(both.verify(old) and both.verify(new))
        self.rejects(old, "bad_signature", hs_verifier(SECRET_2))
        self.assertTrue(hs_verifier(SECRET_1).verify(old))

    def test_configuration_fails_closed(self):
        for kwargs in ({}, {"hmac_secrets": [b"short"]}, {"hmac_secrets": ["str-not-bytes" * 4]},
                       {"hmac_secrets": [SECRET_1], "keys": [pub(KEY_A)]}):
            with self.subTest(kwargs=str(kwargs)[:40]), self.assertRaises(ValueError):
                oj.OutpostJwtVerifier(issuer=ISS, audience=AUD, **kwargs)

    def test_principal_from_an_hs256_token(self):
        tok = hs_sign(SECRET_1, {"alg": "HS256"}, claims())
        p = oj.principal_from_outpost([("X-authentik-jwt", tok), ("X-authentik-username", "member-a")], hs_verifier())
        self.assertEqual(p.username, "member-a")


class PrincipalTests(unittest.TestCase):
    def headers(self, token, **extra):
        pairs = [("X-authentik-jwt", token)]
        pairs += [(k.replace("_", "-"), v) for k, v in extra.items()]
        return pairs

    def test_principal_comes_from_verified_claims(self):
        tok = sign(KEY_A, HDR_A, claims())
        p = oj.principal_from_outpost(self.headers(tok, X_authentik_username="member-a",
                                                   X_authentik_groups="avrana-users|avrana-books"), verifier())
        self.assertTrue(is_minted_principal(p))
        self.assertEqual(p.username, "member-a")
        self.assertTrue(p.has_group("avrana-books"))

    def test_forged_plain_headers_next_to_a_valid_token_are_refused(self):
        tok = sign(KEY_A, HDR_A, claims())
        for extra in ({"X_authentik_groups": "authentik Admins"}, {"X_authentik_username": "member-b"}):
            with self.subTest(extra=extra), self.assertRaises(PrincipalError) as caught:
                oj.principal_from_outpost(self.headers(tok, **extra), verifier())
            self.assertEqual(caught.exception.reason, "identity_mismatch")

    def test_host_namespace_forger_without_the_key_gets_nothing(self):
        forged = sign(make_key(5, kid="kid-a"), HDR_A, claims(groups=["authentik Admins"]))
        with self.assertRaises(PrincipalError) as caught:
            oj.principal_from_outpost(self.headers(forged, X_authentik_groups="authentik Admins"), verifier())
        self.assertEqual(caught.exception.reason, "unverified_identity")

    def test_missing_or_repeated_token(self):
        tok = sign(KEY_A, HDR_A, claims())
        for headers, reason in (([("X-authentik-username", "member-a")], "missing_header"),
                                ([("X-authentik-jwt", tok), ("x-authentik-JWT", tok)], "duplicate_header")):
            with self.subTest(reason=reason), self.assertRaises(PrincipalError) as caught:
                oj.principal_from_outpost(headers, verifier())
            self.assertEqual(caught.exception.reason, reason)


if __name__ == "__main__":
    unittest.main()
