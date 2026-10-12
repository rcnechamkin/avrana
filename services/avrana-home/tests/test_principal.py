import unittest

from avrana_home.principal import (MemberPrincipal, PrincipalError, parse_groups,
                                   principal_from_headers, principal_or_none)

U, G = "X-authentik-username", "X-authentik-groups"


def good(**over):
    h = {U: "member-a", G: "avrana-users|avrana-videos"}
    h.update(over)
    return h


class PrincipalTests(unittest.TestCase):
    def reason(self, headers):
        with self.assertRaises(PrincipalError) as cm:
            principal_from_headers(headers)
        self.assertIsNone(principal_or_none(headers))
        return cm.exception.reason

    def test_happy_path(self):
        p = principal_from_headers(good())
        self.assertEqual(p.username, "member-a")
        self.assertEqual(p.groups, frozenset({"avrana-users", "avrana-videos"}))

    def test_header_names_case_insensitive(self):
        p = principal_from_headers({"x-AUTHENTIK-username": "member-a", "X-Authentik-Groups": "g"})
        self.assertEqual(p.username, "member-a")

    def test_missing(self):
        self.assertEqual(self.reason({G: "g"}), "missing_header")
        self.assertEqual(self.reason({U: "member-a"}), "missing_header")
        self.assertEqual(self.reason({}), "missing_header")

    def test_empty(self):
        self.assertEqual(self.reason(good(**{U: ""})), "empty_header")
        self.assertEqual(self.reason(good(**{G: ""})), "empty_header")
        self.assertEqual(self.reason(good(**{G: "  "})), "empty_header")
        self.assertEqual(self.reason(good(**{G: "|,|"})), "empty_header")

    def test_duplicated_as_list_pairs_and_case_variants(self):
        self.assertEqual(self.reason({U: ["member-a", "member-b"], G: "g"}), "duplicate_header")
        self.assertEqual(self.reason([(U, "member-a"), (U, "member-a"), (G, "g")]), "duplicate_header")
        self.assertEqual(self.reason([(U, "member-a"), (U.lower(), "member-b"), (G, "g")]),
                         "duplicate_header")
        self.assertEqual(self.reason({U: "member-a", G: ["g", "h"]}), "duplicate_header")

    def test_malformed_username(self):
        for bad in (" member-a", "member-a ", "member\na", "member\x00a", "a|b", "a,b",
                    "member​a", "member-́".replace("-", "e"), "é"):
            self.assertEqual(self.reason(good(**{U: bad})), "malformed_header", repr(bad))

    def test_non_string_value(self):
        self.assertEqual(self.reason(good(**{U: b"member-a"})), "malformed_header")
        self.assertEqual(self.reason(good(**{G: 5})), "malformed_header")

    def test_oversized(self):
        self.assertEqual(self.reason(good(**{U: "a" * 151})), "oversized_header")
        self.assertEqual(self.reason(good(**{G: "g" * 5000})), "oversized_header")
        self.assertEqual(self.reason(good(**{G: "|".join(f"g{i}" for i in range(65))})),
                         "oversized_header")
        self.assertEqual(self.reason(good(**{G: "g" * 129})), "oversized_header")
        principal_from_headers(good(**{U: "a" * 150}))      # boundary is accepted

    def test_control_chars_in_groups(self):
        self.assertEqual(self.reason(good(**{G: "g\x00h"})), "malformed_header")
        self.assertEqual(self.reason(good(**{G: "g\r\nX-Evil: 1"})), "malformed_header")

    def test_groups_exact_match_semantics_like_portal(self):
        self.assertEqual(parse_groups("a| b ,c||"), {"a", "b", "c"})
        p = principal_from_headers(good(**{G: "Avrana-Videos"}))
        self.assertFalse(p.has_group("avrana-videos"))          # case-sensitive
        p = principal_from_headers(good(**{G: "avrana-videos-extra"}))
        self.assertFalse(p.has_group("avrana-videos"))          # no prefix matching

    def test_optional_headers_never_decide_identity(self):
        p = principal_from_headers(good(**{"X-authentik-email": "member-a@example.invalid",
                                           "X-authentik-name": "Member A"}))
        self.assertEqual(p.email, "member-a@example.invalid")
        p = principal_from_headers([(U, "member-a"), (G, "g"), ("X-authentik-email", "x"),
                                    ("X-authentik-email", "y")])
        self.assertIsNone(p.email)                                # duplicate optional: dropped
        p = principal_from_headers(good(**{"X-authentik-name": "bad\x00"}))
        self.assertIsNone(p.name)

    def test_cannot_be_constructed_directly(self):
        with self.assertRaises(TypeError):
            MemberPrincipal(username="member-a", groups=frozenset({"avrana-videos"}))

    def test_replace_and_mint_reuse_and_subclassing_cannot_forge(self):
        import copy
        import dataclasses
        import pickle
        p = principal_from_headers(good())
        with self.assertRaises(TypeError):
            dataclasses.replace(p, username="member-b")
        for kwargs in ({"_mint": getattr(p, "_mint", object())},
                       {"_mint": getattr(p, "_sealed", object())}, {}):
            with self.assertRaises(TypeError):
                MemberPrincipal(username="member-b", groups=frozenset({"avrana-videos"}), **kwargs)
        with self.assertRaises(TypeError):
            class Forged(MemberPrincipal):
                pass
        with self.assertRaises(Exception):
            p.username = "member-b"
        with self.assertRaises(Exception):
            p.groups = frozenset({"authentik Admins"})
        with self.assertRaises(TypeError):
            pickle.loads(pickle.dumps(p))
        self.assertIs(copy.copy(p), p)              # immutable: a copy is the same object
        self.assertIs(copy.deepcopy(p), p)
        self.assertEqual(p, principal_from_headers(good()))
        self.assertEqual(hash(p), hash(principal_from_headers(good())))

    def test_consumers_reject_anything_that_is_not_an_exact_minted_principal(self):
        from avrana_home.cache import MemberCache
        from avrana_home.resilience import FakeClock
        from avrana_home.contract import MediaAdapter
        impostor = object.__new__(MemberPrincipal)            # skips the parser entirely
        with self.assertRaises(TypeError):
            MemberCache(FakeClock()).for_member(impostor)
        with self.assertRaises(TypeError):
            MediaAdapter._require_principal(impostor)

        class Duck:
            username = "member-a"
            groups = frozenset({"avrana-videos"})
        with self.assertRaises(TypeError):
            MediaAdapter._require_principal(Duck())

    def test_non_mapping_input_fails_closed(self):
        for bad in (None, 5, "X-authentik-username: a", b"x", object(), [1, 2], [("a",)],
                    [("a", "b", "c")], iter([(U, "a"), (G, "g")])):
            self.assertIsNone(principal_or_none(bad), repr(bad))
            with self.assertRaises(PrincipalError):
                principal_from_headers(bad)

    def test_unicode_separators_and_nbsp_rejected_in_usernames(self):
        for bad in ("member a", "member a", "member a", "member a",
                    "member　a", " member-a", "member-a ", "membera"):
            self.assertEqual(self.reason(good(**{U: bad})), "malformed_header", repr(bad))
        principal_from_headers(good(**{U: "member a"}))        # an ordinary space is allowed
        self.assertEqual(self.reason(good(**{G: "avrana-videos|bad name"})), "malformed_header")

    def test_frozen_and_repr_redacted(self):
        p = principal_from_headers(good())
        with self.assertRaises(Exception):
            p.username = "member-b"
        self.assertNotIn("member-a", repr(p))
        self.assertNotIn("member-a", str(p))


if __name__ == "__main__":
    unittest.main()
