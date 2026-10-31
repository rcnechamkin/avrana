"""AVR-790: the LDAP bind flow's load-bearing settings, read from the blueprint text (standard library only).

The behaviour itself is proven against a real Authentik and outpost by tests/authentik_ldap_bind_live.py. These checks keep
a later edit from quietly removing what that proof depends on, in a suite that runs on every pull request.
"""
import pathlib
import re
import unittest

BLUEPRINTS = pathlib.Path(__file__).resolve().parents[1] / 'services' / 'authentik' / 'blueprints'


class BindFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (BLUEPRINTS / 'avrana-ldap-bind.yaml').read_text(encoding='utf-8')
        cls.code = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))

    def test_only_an_outpost_can_run_it_and_a_refusal_never_becomes_a_redirect(self):
        self.assertRegex(self.code, r'(?m)^      authentication: require_outpost$')
        self.assertRegex(self.code, r'(?m)^      denied_action: message$')

    def test_no_authenticator_stage_is_part_of_it(self):
        self.assertNotIn('authentik_stages_authenticator_validate', self.code)

    def test_privileged_accounts_are_refused_and_a_policy_error_refuses(self):
        self.assertIn('if user.is_superuser:', self.code)
        self.assertIn('name="avrana-mfa-required"', self.code)
        self.assertRegex(self.code, r'(?m)^      failure_result: true$')
        self.assertRegex(self.code, r'(?m)^      evaluate_on_plan: false$')
        self.assertRegex(self.code, r'(?m)^      re_evaluate_policies: true$')

    def test_the_cached_bind_lifetime_is_short_and_never_unbounded(self):
        self.assertRegex(self.code, r'(?m)^      session_duration: minutes=5$')
        self.assertRegex(self.code, r'(?m)^      remember_me_offset: seconds=0$')

    def test_other_sessions_survive_a_bind(self):
        self.assertRegex(self.code, r'(?m)^      terminate_other_sessions: false$')


class Pointers(unittest.TestCase):
    def test_the_calibre_provider_uses_the_bind_flow_for_both_pointers(self):
        text = (BLUEPRINTS / 'calibre-web-ldap.yaml').read_text(encoding='utf-8')
        for pointer in ('authentication_flow', 'authorization_flow'):
            self.assertRegex(text, rf'(?m)^      {pointer}: !Find \[authentik_flows\.flow, \[slug, avrana-ldap-bind\]\]$')
        self.assertIn('name: Avrana - LDAP bind flow', text)

    def test_nothing_else_points_at_the_bind_flow(self):
        users = {p.name for p in BLUEPRINTS.glob('*.yaml') if re.search(r'slug, avrana-ldap-bind\b', p.read_text(encoding='utf-8'))}
        self.assertEqual(users, {'calibre-web-ldap.yaml'})


if __name__ == '__main__':
    unittest.main()
