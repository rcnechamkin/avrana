"""AVR-498: verified-JWT member identity (offline; synthetic keys, secrets and identities only).

Reuses the fixture keys and token builders of test_outpost_jwt (pure-Python RSA from a fixed seed; nothing
stored, nothing fetched). Every identity, issuer, audience and secret here is invented.
"""
import base64
import hashlib
import hmac as hm
import inspect
import json
import unittest

from avrana_home import outpost_jwt as oj
from avrana_home import principal as pr
from avrana_home.principal import (MODE_HEADERS, MODE_JWT_LOG_ONLY, MODE_JWT_REQUIRED, PrincipalError,
                                   is_minted_principal, principal_for_request, principal_from_headers,
                                   principal_from_verified_jwt)
from tests.test_outpost_jwt import (AUD, HDR_A, ISS, KEY_A, KEY_B, NOW, SECRET_1, b64, claims,
                                    hs_sign, hs_verifier, make_key, pub, sign, verifier)

HS = {"alg": "HS256", "typ": "JWT"}
HOME_AUD, PORTAL_AUD, KINDLE_AUD = "synthetic-home-client", "synthetic-portal-client", "synthetic-kindle-client"


def req(token=None, **plain):
    pairs = [] if token is None else [("X-authentik-jwt", token)]
    return pairs + [(k.replace("_", "-"), v) for k, v in plain.items()]


def reason_of(fn, *args, **kw):
    with unittest.TestCase().assertRaises(PrincipalError) as caught:
        fn(*args, **kw)
    return caught.exception.reason


class VerifiedPrincipalTests(unittest.TestCase):
    def test_same_type_and_fields_as_the_header_path(self):
        tok = sign(KEY_A, HDR_A, claims(email="a@example.test", name="Member A"))
        p = principal_from_verified_jwt(req(tok), verifier())
        h = principal_from_headers({"X-authentik-username": "member-a",
                                    "X-authentik-groups": "avrana-users|avrana-books"})
        self.assertTrue(is_minted_principal(p))
        self.assertIs(type(p), type(h))
        self.assertEqual(p, h)
        self.assertEqual((p.email, p.name), ("a@example.test", "Member A"))

    def test_two_members_get_different_principals_and_exact_entitlements(self):
        a = principal_from_verified_jwt(req(sign(KEY_A, HDR_A, claims(
            preferred_username="member-a", groups=["avrana-users", "avrana-books"]))), verifier())
        b = principal_from_verified_jwt(req(sign(KEY_A, HDR_A, claims(
            preferred_username="member-b", groups=["avrana-users", "avrana-videos", "authentik Admins"]))),
            verifier())
        self.assertNotEqual(a, b)
        self.assertEqual((a.username, a.groups), ("member-a", frozenset({"avrana-users", "avrana-books"})))
        self.assertEqual(b.groups, frozenset({"avrana-users", "avrana-videos", "authentik Admins"}))
        self.assertFalse(a.has_group("avrana-videos") or a.has_group("authentik Admins"))
        self.assertFalse(b.has_group("avrana-books"))
        self.assertFalse(a.has_group("Avrana-Books"))  # exact, case-sensitive

    def test_identity_comes_from_the_token_not_the_plain_headers(self):
        tok = sign(KEY_A, HDR_A, claims())
        for extra in ({"X_authentik_username": "member-b"}, {"X_authentik_groups": "authentik Admins"},
                      {"X_authentik_groups": "avrana-users|avrana-books|authentik Admins"},
                      {"X_authentik_groups": "avrana-users"}):
            with self.subTest(extra=extra):
                self.assertEqual(reason_of(principal_from_verified_jwt, req(tok, **extra), verifier()),
                                 "identity_mismatch")
        ok = principal_from_verified_jwt(req(tok, X_authentik_username="member-a",
                                             X_authentik_groups="avrana-books|avrana-users"), verifier())
        self.assertEqual(ok.username, "member-a")

    def test_repeated_or_missing_token(self):
        tok = sign(KEY_A, HDR_A, claims())
        self.assertEqual(reason_of(principal_from_verified_jwt, [], verifier()), "missing_header")
        self.assertEqual(reason_of(principal_from_verified_jwt, req(None, X_authentik_username="member-a"),
                                   verifier()), "missing_header")
        self.assertEqual(reason_of(principal_from_verified_jwt,
                                   [("X-authentik-jwt", tok), ("x-AUTHENTIK-jwt", tok)], verifier()),
                         "duplicate_header")
        other = sign(KEY_A, HDR_A, claims(preferred_username="member-b"))
        self.assertEqual(reason_of(principal_from_verified_jwt,
                                   [("X-authentik-jwt", tok), ("X-authentik-jwt", other)], verifier()),
                         "duplicate_header")
        self.assertEqual(reason_of(principal_from_verified_jwt, {"X-authentik-jwt": [tok, tok]}, verifier()),
                         "duplicate_header")
        self.assertEqual(reason_of(principal_from_verified_jwt, {"X-authentik-jwt": 5}, verifier()),
                         "malformed_header")

    def test_unverified_tokens_are_all_one_closed_answer(self):
        forged = sign(make_key(5, kid="kid-a"), HDR_A, claims(groups=["authentik Admins"]))
        none = b64(json.dumps({"alg": "none"}).encode()) + "." + b64(json.dumps(claims()).encode()) + "."
        for tok in (forged, none, "garbage", "", "a.b.c", sign(KEY_A, HDR_A, claims(exp=NOW - 3600)),
                    sign(KEY_A, HDR_A, claims(iss="https://evil.example.test/")),
                    sign(KEY_A, HDR_A, claims(aud="other")), sign(KEY_A, HDR_A, claims(nbf=NOW + 3600)),
                    hs_sign(SECRET_1, HS, claims())):
            with self.subTest(tok=tok[:24]):
                self.assertEqual(reason_of(principal_from_verified_jwt, req(tok, X_authentik_username="member-a"),
                                           verifier()), "unverified_identity")

    def test_any_verifier_failure_including_unexpected_ones_fails_closed(self):
        class Boom:
            def verify(self, token):
                raise RuntimeError("secret detail")

        class NotClaims:
            def verify(self, token):
                return ["preferred_username"]

        for v in (Boom(), NotClaims()):
            exc = None
            try:
                principal_from_verified_jwt(req("x.y.z"), v)
            except PrincipalError as caught:
                exc = caught
            self.assertEqual(exc.reason, "unverified_identity")
            self.assertNotIn("secret", str(exc))

    def test_claims_that_a_lenient_verifier_could_pass_are_still_checked_at_minting(self):
        class Fixed:
            def __init__(self, c):
                self.c = c

            def verify(self, token):
                return self.c

        base = {"preferred_username": "member-a", "groups": ["avrana-users"]}
        for over, reason in (({"preferred_username": ""}, "empty_header"),
                             ({"preferred_username": " member-a"}, "malformed_header"),
                             ({"preferred_username": "mem|ber"}, "malformed_header"),
                             ({"preferred_username": "a" * 151}, "oversized_header"),
                             ({"preferred_username": "member a"}, "malformed_header"),
                             ({"preferred_username": None}, "malformed_header"),
                             ({"groups": []}, "empty_header"),
                             ({"groups": "avrana-users"}, "malformed_header"),
                             ({"groups": ["a|b"]}, "malformed_header"),
                             ({"groups": ["a,b"]}, "malformed_header"),
                             ({"groups": [" a"]}, "malformed_header"),
                             ({"groups": ["a", 5]}, "malformed_header"),
                             ({"groups": ["a\nb"]}, "malformed_header"),
                             ({"groups": ["g%d" % i for i in range(65)]}, "oversized_header")):
            with self.subTest(over=str(over)[:40]):
                self.assertEqual(reason_of(principal_from_verified_jwt, req("x.y.z"), Fixed(dict(base, **over))),
                                 reason)

    def test_display_fields_never_decide_identity(self):
        tok = sign(KEY_A, HDR_A, claims(email="x" * 300, name="bad\nname"))
        p = principal_from_verified_jwt(req(tok), verifier())
        self.assertEqual((p.email, p.name), (None, None))

    def test_not_constructible(self):
        p = principal_from_verified_jwt(req(sign(KEY_A, HDR_A, claims())), verifier())
        with self.assertRaises(TypeError):
            type(p)()


class ReplayAcrossAudiencesTests(unittest.TestCase):
    """One provider per service: a token minted for one service's client must not open another."""

    def setUp(self):
        self.secrets = {"portal": b"portal-secret-" + b"p" * 40, "home": b"home-secret-" + b"h" * 40,
                        "kindle": b"kindle-secret-" + b"k" * 40}
        self.aud = {"portal": PORTAL_AUD, "home": HOME_AUD, "kindle": KINDLE_AUD}

    def v(self, name, secret=None):
        return oj.OutpostJwtVerifier(issuer=ISS, audience=self.aud[name], clock=lambda: NOW,
                                     hmac_secrets=[secret or self.secrets[name]])

    def tok(self, name, secret=None, **over):
        return hs_sign(secret or self.secrets[name], HS, claims(aud=self.aud[name], **over))

    def test_each_service_accepts_only_its_own_token(self):
        for name in self.aud:
            self.assertEqual(principal_from_verified_jwt(req(self.tok(name)), self.v(name)).username, "member-a")
            for other in self.aud:
                if other != name:
                    with self.subTest(minted_for=other, presented_to=name):
                        self.assertEqual(reason_of(principal_from_verified_jwt, req(self.tok(other)), self.v(name)),
                                         "unverified_identity")

    def test_replay_with_audience_edited_needs_the_secret(self):
        h, c, s = self.tok("portal").split(".")
        edited = b64(json.dumps(claims(aud=HOME_AUD)).encode())
        with self.assertRaises(oj.JwtRejected) as caught:
            self.v("home").verify(f"{h}.{edited}.{s}")
        self.assertEqual(caught.exception.reason, "bad_signature")

    def test_a_shared_secret_would_not_save_you_but_the_audience_check_does(self):
        shared = b"shared-secret-" + b"s" * 40
        with self.assertRaises(oj.JwtRejected) as caught:
            self.v("home", shared).verify(self.tok("portal", secret=shared))
        self.assertEqual(caught.exception.reason, "bad_audience")

    def test_audience_list_must_contain_exactly_this_client(self):
        for aud in ([PORTAL_AUD], [PORTAL_AUD, KINDLE_AUD], HOME_AUD + "x", HOME_AUD.upper(), [HOME_AUD + " "]):
            with self.subTest(aud=aud), self.assertRaises(oj.JwtRejected):
                self.v("home").verify(hs_sign(self.secrets["home"], HS, claims(aud=aud)))

    def test_rsa_mode_replay_across_audiences(self):
        portal = oj.OutpostJwtVerifier([pub(KEY_A)], ISS, PORTAL_AUD, clock=lambda: NOW)
        home = oj.OutpostJwtVerifier([pub(KEY_A)], ISS, HOME_AUD, clock=lambda: NOW)
        tok = sign(KEY_A, HDR_A, claims(aud=PORTAL_AUD))
        self.assertTrue(portal.verify(tok))
        self.assertEqual(reason_of(principal_from_verified_jwt, req(tok), home), "unverified_identity")


class ModeTests(unittest.TestCase):
    PLAIN = {"X-authentik-username": "member-a", "X-authentik-groups": "avrana-users|avrana-books"}

    def test_mode_is_required_and_has_no_default(self):
        param = inspect.signature(principal_for_request).parameters["mode"]
        self.assertIs(param.default, inspect.Parameter.empty)
        self.assertEqual(param.kind, inspect.Parameter.KEYWORD_ONLY)
        with self.assertRaises(TypeError):
            principal_for_request(self.PLAIN)
        for bad in (None, "", "JWT_REQUIRED", "jwt", True, "headers ", ["jwt_required"]):
            with self.subTest(mode=bad):
                self.assertEqual(reason_of(principal_for_request, self.PLAIN, mode=bad, verifier=verifier()),
                                 "bad_mode")

    def test_headers_mode_is_the_unchanged_header_path(self):
        self.assertEqual(principal_for_request(self.PLAIN, mode=MODE_HEADERS), principal_from_headers(self.PLAIN))
        self.assertEqual(reason_of(principal_for_request, {}, mode=MODE_HEADERS), "missing_header")

    def test_header_only_identity_is_refused_when_jwt_is_required(self):
        self.assertEqual(reason_of(principal_for_request, self.PLAIN, mode=MODE_JWT_REQUIRED, verifier=verifier()),
                         "missing_header")
        self.assertEqual(reason_of(principal_for_request, dict(self.PLAIN, **{"X-authentik-jwt": ""}),
                                   mode=MODE_JWT_REQUIRED, verifier=verifier()), "unverified_identity")
        self.assertEqual(reason_of(principal_for_request, dict(self.PLAIN, **{"X-authentik-jwt": "not.a.jwt"}),
                                   mode=MODE_JWT_REQUIRED, verifier=verifier()), "unverified_identity")

    def test_required_mode_accepts_a_valid_token_only(self):
        tok = sign(KEY_A, HDR_A, claims())
        p = principal_for_request(dict(self.PLAIN, **{"X-authentik-jwt": tok}), mode=MODE_JWT_REQUIRED,
                                  verifier=verifier())
        self.assertEqual(p.username, "member-a")
        p = principal_for_request({"X-authentik-jwt": tok}, mode=MODE_JWT_REQUIRED, verifier=verifier())
        self.assertEqual(p.groups, frozenset({"avrana-users", "avrana-books"}))

    def test_jwt_modes_without_a_verifier_fail_closed(self):
        for mode in (MODE_JWT_REQUIRED, MODE_JWT_LOG_ONLY):
            self.assertEqual(reason_of(principal_for_request, self.PLAIN, mode=mode), "misconfigured")

    def test_log_only_serves_headers_and_reports_codes_only(self):
        seen = []
        tok = sign(KEY_A, HDR_A, claims())
        cases = [(dict(self.PLAIN), "missing_header"),
                 (dict(self.PLAIN, **{"X-authentik-jwt": tok}), "ok"),
                 (dict(self.PLAIN, **{"X-authentik-jwt": sign(make_key(5, kid="kid-a"), HDR_A, claims())}),
                  "unverified_identity"),
                 (dict(self.PLAIN, **{"X-authentik-jwt": tok, "X-authentik-username": "member-b"}),
                  "identity_mismatch")]
        for headers, code in cases:
            seen.clear()
            p = principal_for_request(headers, mode=MODE_JWT_LOG_ONLY, verifier=verifier(), report=seen.append)
            self.assertEqual(seen, [code])
            self.assertEqual(p.username, headers["X-authentik-username"])

    def test_log_only_never_changes_the_outcome_even_if_reporting_breaks(self):
        def boom(code):
            raise RuntimeError(code)

        p = principal_for_request(self.PLAIN, mode=MODE_JWT_LOG_ONLY, verifier=verifier(), report=boom)
        self.assertEqual(p, principal_from_headers(self.PLAIN))
        # A request with no usable plain headers is still refused in log-only mode.
        self.assertEqual(reason_of(principal_for_request, {"X-authentik-jwt": sign(KEY_A, HDR_A, claims())},
                                   mode=MODE_JWT_LOG_ONLY, verifier=verifier()), "missing_header")

    def test_modes_are_the_documented_three(self):
        self.assertEqual(pr.IDENTITY_MODES, ("headers", "jwt_log_only", "jwt_required"))


class StricterClaimTests(unittest.TestCase):
    def rejects(self, payload, reason, v=None):
        with self.assertRaises(oj.JwtRejected) as caught:
            (v or verifier()).verify(sign(KEY_A, HDR_A, payload))
        self.assertEqual(caught.exception.reason, reason)

    def test_iat_is_required_and_may_not_follow_exp(self):
        self.rejects(claims(iat=...), "bad_claims")
        self.rejects(claims(iat="1"), "bad_claims")
        self.rejects(claims(iat=NOW + 10, exp=NOW + 5), "bad_claims")

    def test_empty_groups_are_refused(self):
        self.rejects(claims(groups=[]), "bad_claims")

    def test_nbf_is_optional_but_checked_when_present(self):
        self.assertTrue(verifier().verify(sign(KEY_A, HDR_A, claims())))
        self.assertTrue(verifier().verify(sign(KEY_A, HDR_A, claims(nbf=NOW - 5))))
        self.rejects(claims(nbf=NOW + 61), "not_yet_valid")

    def test_leeway_is_a_small_bounded_integer(self):
        for bad in (-1, 301, 60.5, "60", None, True):
            with self.subTest(leeway=bad), self.assertRaises(ValueError):
                oj.OutpostJwtVerifier([pub(KEY_A)], ISS, AUD, leeway=bad)
        strict = oj.OutpostJwtVerifier([pub(KEY_A)], ISS, AUD, leeway=0, clock=lambda: NOW)
        self.assertTrue(strict.verify(sign(KEY_A, HDR_A, claims())))
        for payload, reason in ((claims(exp=NOW), "expired"), (claims(iat=NOW + 1), "not_yet_valid")):
            with self.assertRaises(oj.JwtRejected) as caught:
                strict.verify(sign(KEY_A, HDR_A, payload))
            self.assertEqual(caught.exception.reason, reason)

    def test_expiry_boundaries_with_default_leeway(self):
        self.assertTrue(verifier().verify(sign(KEY_A, HDR_A, claims(exp=NOW - 59, iat=NOW - 3600))))
        self.rejects(claims(exp=NOW - 60, iat=NOW - 3600), "expired")

    def test_issuer_and_audience_types(self):
        for payload, reason in ((claims(iss=[ISS]), "bad_issuer"), (claims(iss=ISS + "x"), "bad_issuer"),
                                (claims(aud=None), "bad_audience"), (claims(aud=[]), "bad_audience"),
                                (claims(aud={"a": AUD}), "bad_audience")):
            with self.subTest(payload=str(payload)[:60]):
                self.rejects(payload, reason)

    def test_verifier_configuration_types(self):
        for iss, aud in ((None, AUD), (ISS, None), (5, AUD), (ISS, ["a"])):
            with self.assertRaises(ValueError):
                oj.OutpostJwtVerifier([pub(KEY_A)], iss, aud)


def _der(tag, content):
    n = len(content)
    if n < 128:
        head = bytes([tag, n])
    else:
        size = (n.bit_length() + 7) // 8
        head = bytes([tag, 0x80 | size]) + n.to_bytes(size, "big")
    return head + content


def _int(v):
    raw = v.to_bytes((v.bit_length() + 7) // 8, "big")
    return _der(0x02, (b"\x00" if raw[0] & 0x80 else b"") + raw)


def pem(key, kind="PUBLIC"):
    pkcs1 = _der(0x30, _int(key["n"]) + _int(key["e"]))
    if kind == "RSA PUBLIC":
        body = pkcs1
    else:
        body = _der(0x30, bytes.fromhex("300d06092a864886f70d0101010500") + _der(0x03, b"\x00" + pkcs1))
    text = base64.b64encode(body).decode()
    lines = "\n".join(text[i:i + 64] for i in range(0, len(text), 64))
    return f"-----BEGIN {kind} KEY-----\n{lines}\n-----END {kind} KEY-----\n"


class KeySetTests(unittest.TestCase):
    def test_pem_spki_and_pkcs1_verify_tokens(self):
        for kind in ("PUBLIC", "RSA PUBLIC"):
            key = oj.RsaPublicKey.from_pem(pem(KEY_A, kind), kid="kid-a")
            v = oj.OutpostJwtVerifier([key], ISS, AUD, clock=lambda: NOW)
            self.assertTrue(v.verify(sign(KEY_A, HDR_A, claims())))
            with self.assertRaises(oj.JwtRejected):
                v.verify(sign(KEY_B, dict(HDR_A), claims()))

    def test_jwks_document_with_rotation_overlap(self):
        doc = {"keys": [{"kty": "RSA", "kid": k["kid"], "alg": "RS256", "use": "sig",
                         "n": b64(k["n"].to_bytes(256, "big")), "e": b64(k["e"].to_bytes(3, "big"))}
                        for k in (KEY_A, KEY_B)]}
        for source in (doc, json.dumps(doc)):
            v = oj.OutpostJwtVerifier(oj.RsaPublicKey.from_jwks(source), ISS, AUD, clock=lambda: NOW)
            self.assertTrue(v.verify(sign(KEY_A, HDR_A, claims())))
            self.assertTrue(v.verify(sign(KEY_B, {"alg": "RS256", "kid": "kid-b"}, claims())))

    def test_malformed_key_material_is_refused(self):
        good = pem(KEY_A)
        for bad in (None, "", "garbage", good.replace("PUBLIC", "PRIVATE"),
                    good.replace("END PUBLIC", "END RSA PUBLIC"), good[:-30],
                    good.replace("\n", "", 3)[:-30] + "AAAA\n-----END PUBLIC KEY-----\n",
                    pem(KEY_A, "RSA PUBLIC").replace("RSA PUBLIC", "PUBLIC")):
            with self.subTest(bad=str(bad)[:30]), self.assertRaises(ValueError):
                oj.RsaPublicKey.from_pem(bad)
        for bad in (None, {}, {"keys": []}, {"keys": [{"kty": "oct"}]}, "{", '{"keys": [], "keys": []}', 5):
            with self.subTest(jwks=str(bad)[:30]), self.assertRaises(ValueError):
                oj.RsaPublicKey.from_jwks(bad)


class MutationStyleTests(unittest.TestCase):
    """Systematic negatives: no single-character change, dropped claim or swapped part may be accepted."""

    def test_every_single_character_flip_is_rejected(self):
        good = sign(KEY_A, HDR_A, claims())
        self.assertTrue(verifier().verify(good))
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        step = max(1, len(good) // 97)
        checked = 0
        for i in range(0, len(good), step):
            if good[i] == ".":
                continue
            repl = alphabet[(alphabet.index(good[i]) + 1) % 64]
            with self.subTest(index=i), self.assertRaises(oj.JwtRejected):
                verifier().verify(good[:i] + repl + good[i + 1:])
            checked += 1
        self.assertGreater(checked, 90)

    def test_each_required_claim_dropped_is_rejected_at_the_principal_layer(self):
        for name in ("iss", "aud", "exp", "iat", "preferred_username", "groups"):
            with self.subTest(dropped=name):
                tok = sign(KEY_A, HDR_A, claims(**{name: ...}))
                self.assertEqual(reason_of(principal_from_verified_jwt, req(tok), verifier()), "unverified_identity")

    def test_segment_swaps_between_two_valid_tokens_are_rejected(self):
        a = sign(KEY_A, HDR_A, claims(preferred_username="member-a")).split(".")
        b = sign(KEY_A, HDR_A, claims(preferred_username="member-b", groups=["authentik Admins"])).split(".")
        for combo in ((a[0], b[1], a[2]), (a[0], a[1], b[2]), (b[0], a[1], b[2]), (a[1], a[0], a[2]),
                      (a[0], a[1]), (a[0], a[1], a[2], a[2])):
            with self.subTest(combo=[len(x) for x in combo]), self.assertRaises(oj.JwtRejected):
                verifier().verify(".".join(combo))

    def test_hs_signature_made_with_the_public_modulus_or_empty_key_is_rejected(self):
        h, c = b64(json.dumps({"alg": "HS256"}).encode()), b64(json.dumps(claims()).encode())
        for key in (KEY_A["n"].to_bytes(256, "big"), b"", pem(KEY_A).encode()):
            mac = b64(hm.new(key, f"{h}.{c}".encode(), hashlib.sha256).digest())
            with self.assertRaises(oj.JwtRejected):
                verifier().verify(f"{h}.{c}.{mac}")           # RS256 verifier: bad_alg
        empty_mac = b64(hm.new(b"", f"{h}.{c}".encode(), hashlib.sha256).digest())
        with self.assertRaises(oj.JwtRejected):
            hs_verifier().verify(f"{h}.{c}.{empty_mac}")

    def test_oversized_tokens_are_refused_before_any_work(self):
        big = sign(KEY_A, HDR_A, claims(groups=["g%05d" % i for i in range(3000)]))
        self.assertGreater(len(big), oj.MAX_TOKEN_LEN)
        self.assertEqual(reason_of(principal_from_verified_jwt, req(big), verifier()), "unverified_identity")
        with self.assertRaises(oj.JwtRejected) as caught:
            verifier().verify(big)
        self.assertEqual(caught.exception.reason, "malformed_token")


class ReviewFindingTests(unittest.TestCase):
    """Findings from the independent review of PR #35 (AVR-498)."""

    def rejects(self, payload, reason=None, v=None):
        with self.assertRaises(oj.JwtRejected) as caught:
            (v or verifier()).verify(sign(KEY_A, HDR_A, payload))
        if reason:
            self.assertEqual(caught.exception.reason, reason)

    def test_huge_integers_are_rejected_not_raised(self):
        for name in ("exp", "iat"):
            for value in (10 ** 400, -(10 ** 400), 10 ** 13, 2 ** 1024):
                with self.subTest(claim=name, value=str(value)[:12]):
                    self.rejects(claims(**{name: value}), "bad_claims")
        for value in (10 ** 400, 10 ** 13):  # nbf is optional but, when present, checked the same way
            body = json.dumps(claims())[:-1] + ', "nbf": ' + str(value) + "}"
            with self.subTest(claim="nbf", value=str(value)[:12]), self.assertRaises(oj.JwtRejected):
                verifier().verify(sign(KEY_A, HDR_A, None, raw_claims=b64(body.encode())))
        self.assertTrue(oj._is_number(1_800_000_000) and oj._is_number(-5.5) and oj._is_number(0))
        for bad in (10 ** 400, float("inf"), float("nan"), True, "1", None, 1e12, -1e12):
            self.assertFalse(oj._is_number(bad))

    def test_deeply_nested_json_is_rejected_not_raised(self):
        deep = b64(("[" * 10000).encode())
        good_h, good_c = b64(json.dumps(HDR_A).encode()), b64(json.dumps(claims()).encode())
        for h, c in ((deep, good_c), (good_h, deep)):
            with self.assertRaises(oj.JwtRejected):
                verifier().verify(f"{h}.{c}.{b64(b'x')}")
        with self.assertRaises(oj.JwtRejected):  # validly signed, nested claims
            verifier().verify(sign(KEY_A, HDR_A, None, raw_claims=deep))
        with self.assertRaises(oj.JwtRejected):  # HMAC mode shares the parser
            hs_verifier().verify(f"{deep}.{b64(b'{}')}.{b64(b'x')}")
        self.assertEqual(reason_of(principal_from_verified_jwt, req(f"{deep}.{b64(b'{}')}.{b64(b'x')}"),
                                   verifier()), "unverified_identity")

    def test_token_lifetime_is_capped(self):
        v = verifier()
        self.assertEqual(v.max_lifetime, 86400)
        self.assertTrue(v.verify(sign(KEY_A, HDR_A, claims(iat=NOW - 10, exp=NOW - 10 + 86400))))
        self.rejects(claims(iat=NOW - 10, exp=NOW - 10 + 86401), "bad_claims")
        self.rejects(claims(exp=NOW + 10 ** 10), "bad_claims")
        longer = oj.OutpostJwtVerifier([pub(KEY_A)], ISS, AUD, clock=lambda: NOW, max_lifetime=7 * 86400)
        self.assertTrue(longer.verify(sign(KEY_A, HDR_A, claims(exp=NOW + 5 * 86400))))
        for bad in (0, -1, 30 * 86400 + 1, 3600.5, "3600", None, True):
            with self.subTest(max_lifetime=bad), self.assertRaises(ValueError):
                oj.OutpostJwtVerifier([pub(KEY_A)], ISS, AUD, max_lifetime=bad)

    def test_malformed_pkcs1_signed_with_the_real_private_key_is_rejected(self):
        """Valid RSA signatures over wrong encodings. A check that only compares the hash tail accepts
        these; the whole encoded message must match."""
        h, c = b64(json.dumps(HDR_A).encode()), b64(json.dumps(claims()).encode())
        digest = hashlib.sha256(f"{h}.{c}".encode()).digest()
        k = 256
        good_t = oj._DIGEST_INFO_SHA256 + digest

        def signed(em):
            self.assertEqual(len(em), k)
            return pow(int.from_bytes(em, "big"), KEY_A["d"], KEY_A["n"]).to_bytes(k, "big")

        def frame(t, pad=None):
            pad = b"\xff" * (k - len(t) - 3) if pad is None else pad
            return b"\x00\x01" + pad + b"\x00" + t

        variants = {
            "wrong DigestInfo OID (sha384 OID, sha256 digest)":
                frame(bytes.fromhex("3031300d060960864801650304020205000420") + digest),
            "wrong DigestInfo OID (unknown arc)":
                frame(bytes.fromhex("3031300d060960864801650304020905000420") + digest),
            "DigestInfo with the NULL missing":
                frame(bytes.fromhex("302f300b0609608648016503040201" "0420") + digest),
            "digest only, no DigestInfo": frame(digest),
            "garbage in the padding, correct tail": frame(good_t, b"\xff" * 10 + b"\x41" * (k - len(good_t) - 13)),
            "padding of 0xfe": frame(good_t, b"\xfe" * (k - len(good_t) - 3)),
            "padding byte 0x01 at the end": frame(good_t, b"\xff" * (k - len(good_t) - 4) + b"\x01"),
        }
        for name, em in variants.items():
            with self.subTest(variant=name), self.assertRaises(oj.JwtRejected) as caught:
                verifier().verify(f"{h}.{c}.{b64(signed(em))}")
            self.assertEqual(caught.exception.reason, "bad_signature")
        # Control: the correct encoding with the same key is accepted.
        self.assertTrue(verifier().verify(f"{h}.{c}.{b64(signed(frame(good_t)))}"))


class LogOnlyServesHeadersTests(unittest.TestCase):
    PLAIN = [("X-authentik-username", "member-a"), ("X-authentik-groups", "avrana-users|avrana-books"),
             ("X-authentik-email", "header@example.test"), ("X-authentik-name", "Header Name")]

    def test_display_fields_come_from_the_headers_not_the_token(self):
        tok = sign(KEY_A, HDR_A, claims(email="token@example.test", name="Token Name"))
        p = principal_for_request(self.PLAIN + [("X-authentik-jwt", tok)], mode=MODE_JWT_LOG_ONLY,
                                  verifier=verifier())
        self.assertEqual((p.email, p.name), ("header@example.test", "Header Name"))
        verified = principal_from_verified_jwt(self.PLAIN + [("X-authentik-jwt", tok)], verifier())
        self.assertEqual((verified.email, verified.name), ("token@example.test", "Token Name"))

    def test_valid_token_with_mismatched_headers_never_yields_a_jwt_principal(self):
        tok = sign(KEY_A, HDR_A, claims(preferred_username="member-b", groups=["avrana-users", "authentik Admins"],
                                        email="token@example.test", name="Token Name"))
        seen = []
        p = principal_for_request(self.PLAIN + [("X-authentik-jwt", tok)], mode=MODE_JWT_LOG_ONLY,
                                  verifier=verifier(), report=seen.append)
        self.assertEqual(seen, ["identity_mismatch"])
        self.assertEqual((p.username, p.groups, p.email, p.name),
                         ("member-a", frozenset({"avrana-users", "avrana-books"}), "header@example.test",
                          "Header Name"))
        self.assertFalse(p.has_group("authentik Admins"))


if __name__ == "__main__":
    unittest.main()
