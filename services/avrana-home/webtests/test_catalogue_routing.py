"""Tier A: the catalogue seam and the portal-parity routing decisions, framework-free.

`routing.decide` is compared with the stdlib portal (in memory) for every fixture identity and
every route: same status and same redirect target. The full-body comparison is the Tier B parity
suite; this tier proves the decision logic needs no framework.
"""
import tempfile
import unittest
from pathlib import Path

from avrana_home.app import catalogue
from avrana_home.app.catalogue import CatalogueError, Trusted
from avrana_home.app.routing import AccountFacts, decide, normalise_target
from avrana_home.principal import principal_from_headers

from .support import IDENTITIES, PORTAL_PATH, ident_headers, portal, portal_request

CAT = catalogue.load(PORTAL_PATH)

ROUTES = (["/", "/account", "/help", "/healthz", "/read", "/request", "/nope", "/admin", "/WATCH",
           "/help/nope", "/help/movies/extra", "/ops/x", "/read/comics"]
          + [f"/help/{s}" for s in portal.HELP_SLUGS.values()]
          + [f"/{s[3]}" for s in portal.SERVICES])


def groups_for(name):
    g = IDENTITIES[name]
    return frozenset(g or [])


class CatalogueTests(unittest.TestCase):
    def test_tables_equal_the_portals(self):
        self.assertEqual(len(portal.SERVICES), len(CAT.services))
        for raw, svc in zip(portal.SERVICES, CAT.services):
            self.assertEqual((raw[3], raw[4]), (svc.path, svc.host))
            self.assertEqual(raw[1], str(svc.label))
            self.assertEqual(raw[2], str(svc.desc))
        self.assertEqual([c[2] for c in portal.CHOOSERS], [c.path for c in CAT.choosers])
        self.assertEqual(portal.HOME_ORDER, list(CAT.home_order))
        self.assertEqual(portal.SSO_INIT, CAT.sso_init)
        self.assertEqual(set(portal.INTERSTITIALS), set(CAT.interstitials))
        self.assertEqual({portal.HELP_SLUGS[h[1]] for h in portal.HELP}, {t.slug for t in CAT.help_topics})

    def test_catalogue_text_is_marked_trusted_and_nothing_else_is(self):
        self.assertIsInstance(CAT.services[0].label, Trusted)
        self.assertIsInstance(CAT.help_topics[0].label, Trusted)
        self.assertNotIsInstance(CAT.services[0].path, Trusted)
        self.assertNotIsInstance("request input", Trusted)

    def test_load_has_no_import_time_effect_and_fails_cleanly(self):
        with self.assertRaises(CatalogueError):
            catalogue.load("/nonexistent/portal.py")
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "tables.py"
            bad.write_text("raise RuntimeError('secret-looking detail')\n", encoding="utf-8")
            with self.assertRaises(CatalogueError) as cm:
                catalogue.load(bad)
            self.assertNotIn("secret-looking", str(cm.exception))      # class only, never the message
            partial = Path(d) / "partial.py"
            partial.write_text("SERVICES = []\n", encoding="utf-8")
            with self.assertRaises(CatalogueError):
                catalogue.load(partial)

    def test_redirect_targets_are_a_fixed_table(self):
        self.assertEqual("https://read.avrana.net/oauth2/authorization/authentik",
                         CAT.redirect_target(CAT.service("comics")))
        self.assertEqual("https://ops.avrana.net", CAT.redirect_target(CAT.service("ops")))


class NormaliseTests(unittest.TestCase):
    def test_matches_the_portals_route_normalisation(self):
        cases = {"/": "/", "": "/", "/watch": "/watch", "/watch/": "/watch", "/watch//": "/watch",
                 "/watch?x=1": "/watch", "/watch/?x=1": "/watch", "/watch#f": "/watch",
                 "//watch": "/watch", "///watch": "/watch", "//": "/", "/help/": "/help",
                 "/WATCH": "/WATCH", "/%77atch": "/%77atch", "/watch%2f": "/watch%2f",
                 "/watch;x": "/watch;x", "/a?b#c": "/a"}
        for target, want in cases.items():
            with self.subTest(target=target):
                self.assertEqual(want, normalise_target(target))


class DecisionParityTests(unittest.TestCase):
    def test_status_and_location_match_the_portal_for_every_identity_and_route(self):
        for ident in IDENTITIES:
            groups = groups_for(ident)
            for route in ROUTES:
                want = portal_request(route, ident_headers(ident, "member-a")
                                      if IDENTITIES[ident] else [])
                got = decide(normalise_target(route), groups, CAT)
                with self.subTest(ident=ident, route=route):
                    self.assertEqual(want.status, got.status)
                    self.assertEqual(want.location, got.location)

    def test_denied_and_unknown_are_the_same_decision(self):
        unknown = decide("/definitely-not-a-route", frozenset(), CAT)
        for route in ("/watch", "/ops", "/read", "/request", "/help/movies", "/contribute"):
            self.assertEqual(unknown, decide(route, frozenset(), CAT))

    def test_account_facts_come_only_from_the_principal(self):
        p = principal_from_headers({"X-authentik-username": "member-a",
                                    "X-authentik-groups": "avrana-users",
                                    "X-authentik-name": "Member A"})
        d = decide("/account", p.groups, CAT, AccountFacts(name="Member A", username="member-a"))
        self.assertEqual([("Name", "Member A"), ("Username", "member-a")], d.context["facts"])
        d = decide("/account", frozenset(), CAT, None)
        self.assertEqual([("Signed in", "yes")], d.context["facts"])

    def test_decide_has_no_request_input_beyond_path_and_groups(self):
        import inspect
        self.assertEqual(["route", "groups", "cat", "facts"], list(inspect.signature(decide).parameters))


if __name__ == "__main__":
    unittest.main()
