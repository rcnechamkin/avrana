"""The member home preview (tests/ui/home_preview): fixtures only, no network, no credentials.

Skipped where FastAPI is not installed (the preview's README lists the pinned packages).
"""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from fastapi.testclient import TestClient
    from tests.ui.home_preview import fixtures
    from tests.ui.home_preview.app import app
except ImportError:                                    # pragma: no cover
    TestClient = None


@unittest.skipIf(TestClient is None, 'FastAPI, Jinja and httpx are not installed')
class HomePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def page(self, state):
        response = self.client.get('/', params={'state': state})
        self.assertEqual(200, response.status_code, state)
        return response

    def test_every_state_renders_without_script_and_says_it_is_a_preview(self):
        for state in fixtures.STATES:
            response = self.page(state)
            self.assertNotIn('<script', response.text.lower(), state)
            self.assertIn('Preview, fixture data.', response.text, state)
            self.assertIn("default-src 'none'", response.headers['content-security-policy'])
            self.assertNotIn('script-src', response.headers['content-security-policy'])
            self.assertEqual(1, response.text.count('<h1'), state)

    def test_member_copy_has_no_dashes_and_no_first_person(self):
        for state in fixtures.STATES:
            text = re.sub(r'<[^>]+>', ' ', self.page(state).text)
            self.assertIsNone(re.search(r'[–—]', text), state)
            self.assertIsNone(re.search(r"\b(we|our|we're|we've)\b", text, re.I), state)

    def test_a_service_that_is_down_is_said_once_and_its_rows_are_gone(self):
        text = self.page('degraded').text
        self.assertEqual(1, text.count('Movies and TV are unavailable right now.'))
        self.assertNotIn('/art/still/', text)
        self.assertNotIn('/art/poster/', text)
        self.assertIn('/art/square/', text)             # everything else still works

    def test_all_libraries_down_keeps_help_and_account(self):
        text = self.page('unavailable').text
        self.assertIn('role="status"', text)
        self.assertIn('offline this evening', text)
        self.assertNotIn('/art/', text)
        self.assertIn('>Help<', text)
        self.assertIn('Account', text)
        self.assertNotIn('>Watch<', text)

    def test_slow_and_empty_sections_say_so_in_words(self):
        self.assertIn('Audiobooks are taking longer than usual.', self.page('slow').text)
        empty = self.page('empty').text
        self.assertIn('Nothing in progress.', empty)
        self.assertIn('Nothing new in the last 30 days.', empty)

    def test_progress_is_always_beside_words(self):
        text = self.page('healthy').text
        self.assertEqual(text.count('<progress'), text.count('percent '))
        self.assertIn('38 min left', text)

    def test_unknown_states_and_covers_are_not_found(self):
        self.assertEqual(404, self.client.get('/', params={'state': 'nope'}).status_code)
        self.assertEqual(404, self.client.get('/art/poster/not-a-title.svg').status_code)
        self.assertEqual(404, self.client.get('/art/round/dracula.svg').status_code)

    def test_covers_are_drawn_here_and_each_library_keeps_its_shape(self):
        for shelf in fixtures.RECENT:
            slug = shelf['items'][0][0]
            response = self.client.get(f"/art/{shelf['shape']}/{slug}.svg")
            self.assertEqual('image/svg+xml', response.headers['content-type'])
            self.assertNotIn('href', response.text)     # nothing fetched from anywhere
            w, h = fixtures.SHAPES[shelf['shape']]
            self.assertIn(f'viewBox="0 0 {w} {h}"', response.text)
        self.assertEqual({'poster', 'square', 'book', 'comic'}, {s['shape'] for s in fixtures.RECENT})

    def test_before_is_the_portal_from_git(self):
        response = self.client.get('/before')
        self.assertEqual(200, response.status_code)
        self.assertIn('Your Avrana services', response.text)
        self.assertNotIn('Operations', response.text)   # the fixture member is not an admin


if __name__ == '__main__':
    unittest.main()
