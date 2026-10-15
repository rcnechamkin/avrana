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

    def page(self, state, path='/', **more):
        response = self.client.get(path, params={'state': state, **more})
        self.assertEqual(200, response.status_code, f'{path} {state}')
        return response

    def body(self, state, path='/', **more):
        """The design itself: the page without the preview's own bar of switches."""
        return self.page(state, path, **more).text.split('</aside>', 1)[1]

    def test_every_state_renders_without_script_and_says_it_is_a_preview(self):
        for path in ('/', '/new'):
            for state in fixtures.STATES:
                response = self.page(state, path)
                self.assertNotIn('<script', response.text.lower(), state)
                self.assertIn('Preview, fixture data.', response.text, state)
                self.assertIn("default-src 'none'", response.headers['content-security-policy'])
                self.assertNotIn('script-src', response.headers['content-security-policy'])
                self.assertEqual(1, response.text.count('<h1'), f'{path} {state}')

    def test_member_copy_has_no_dashes_and_no_first_person(self):
        for path in ('/', '/new'):
            for state in fixtures.STATES:
                text = re.sub(r'<[^>]+>', ' ', self.page(state, path).text)
                self.assertIsNone(re.search(r'[–—]', text), state)
                self.assertIsNone(re.search(r"\b(we|our|we're|we've)\b", text, re.I), state)

    def test_the_places_come_first_libraries_request_and_help(self):
        text = self.body('healthy')
        bar = text[text.index('<nav class="places"'):text.index('</nav>')]
        self.assertEqual(['Watch', 'Listen', 'Read', 'Request', 'Help'], re.findall(r'<a [^>]*>([^<]+)</a>', bar))
        # before anything else on the page: the bar is ahead of Continue and of what is new
        self.assertLess(text.index('class="places"'), text.index('id="h-continue"'))
        self.assertLess(text.index('id="h-continue"'), text.index('id="h-new"'))
        self.assertNotIn('class="tile', text)           # no second set of tiles under the shelves

    def test_home_is_bounded_one_continue_row_and_one_new_row(self):
        for tab in ('all', 'video', 'audio', 'books', 'comics'):
            text = self.body('healthy', new=tab)
            self.assertEqual(2, text.count('<ul class="rail'), tab)
            first, second = text.split('<ul class="rail')[1:]
            self.assertLessEqual(first.split('</ul>')[0].count('<li'), fixtures.CONTINUE_MOST, tab)
            self.assertLessEqual(second.split('</ul>')[0].count('<li'), fixtures.NEW_MOST, tab)
            self.assertEqual(1, text.count('aria-current="true"'), tab)      # the tab on screen says so
        # Continue is one row of whatever was left, in either kind of library
        mixed = self.body('healthy').split('<ul class="rail')[1]
        self.assertIn('/art/still/', mixed)
        self.assertIn('/art/square/', mixed)
        self.assertNotIn('Continue watching', self.body('healthy'))
        self.assertNotIn('Recently added', self.body('healthy'))

    def test_new_tabs_are_links_and_all_is_the_newest_of_each_library(self):
        text = self.body('healthy')
        tabs = text[text.index('<nav class="tabs"'):].split('</nav>')[0]
        self.assertEqual(['All', 'Movies and TV', 'Audiobooks', 'Books', 'Comics'], re.findall(r'>([^<>]+)</a>', tabs))
        row = text.split('<ul class="rail tall">')[1].split('</ul>')[0]
        for shape in ('poster', 'square', 'book', 'comic'):
            self.assertEqual(1, row.count(f'/art/{shape}/'), shape)
        audio = self.body('healthy', new='audio')
        row = audio.split('<ul class="rail tall">')[1].split('</ul>')[0]
        self.assertEqual(fixtures.NEW_MOST, row.count('/art/square/'))
        self.assertIn('Everything new in audiobooks', audio)
        self.assertIn('/new?state=healthy&amp;lib=audio', audio)
        self.assertIn('aria-current="true"', self.body('healthy', new='nonsense'))   # an unknown tab is All

    def test_the_new_page_lists_one_library_at_a_time(self):
        text = self.body('healthy', '/new')
        self.assertEqual(len(fixtures.RECENT[0]['items']), text.count('/art/poster/'))
        self.assertNotIn('/art/square/', text)
        comics = self.body('healthy', '/new', lib='comics')
        self.assertEqual(len(fixtures.RECENT[3]['items']), comics.count('/art/comic/'))
        self.assertIn('All comics', comics)
        self.assertIn('Back to the home page', comics)
        self.assertIn('>Request</a>', comics)            # the places are on this page too
        self.assertIn('Audiobooks are taking longer than usual.', self.body('slow', '/new', lib='audio'))
        self.assertIn('Nothing new here this week.', self.body('empty', '/new', lib='audio'))
        gone = self.body('degraded', '/new')
        self.assertNotIn('/art/poster/', gone)           # the library that is down has no tab
        self.assertNotIn('lib=video', gone)

    def test_a_service_that_is_down_is_said_once_struck_in_the_bar_and_its_items_are_gone(self):
        text = self.body('degraded')
        self.assertEqual(1, text.count('Movies and TV are unavailable right now.'))
        self.assertIn('<s>Watch</s>', text)
        self.assertNotIn('to=Watch', text)               # it is not a link while it is down
        self.assertIn('>Listen</a>', text)
        self.assertNotIn('/art/still/', text)
        self.assertNotIn('/art/poster/', text)
        self.assertNotIn('new=video', text)
        self.assertIn('/art/square/', text)             # everything else still works

    def test_all_libraries_down_keeps_request_help_and_account(self):
        text = self.body('unavailable')
        self.assertIn('role="status"', text)
        self.assertIn('offline this evening', text)
        self.assertNotIn('/art/', text)
        for label in ('Request', 'Help'):
            self.assertIn(f'>{label}</a>', text)
        self.assertIn('Account', text)
        for label in ('Watch', 'Listen', 'Read'):
            self.assertIn(f'<s>{label}</s>', text)
            self.assertNotIn(f'to={label}', text)

    def test_slow_and_empty_sections_say_so_in_words(self):
        slow = self.body('slow')
        self.assertIn('Audiobooks are taking longer than usual.', slow)
        self.assertIn('Try again', slow)
        self.assertIn('/art/still/', slow)               # what did answer is still there
        self.assertIn('Audiobooks are taking longer than usual.', self.body('slow', new='audio'))
        empty = self.body('empty')
        self.assertIn('Nothing in progress.', empty)
        self.assertIn('Nothing new in audiobooks this week.', self.body('empty', new='audio'))

    def test_progress_is_always_beside_words(self):
        text = self.page('healthy').text
        self.assertEqual(text.count('<progress'), text.count('percent '))
        self.assertIn('38 min left', text)

    def test_unknown_states_and_covers_are_not_found(self):
        self.assertEqual(404, self.client.get('/', params={'state': 'nope'}).status_code)
        self.assertEqual(404, self.client.get('/new', params={'state': 'nope'}).status_code)
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

    # ---- AVR-478: the account control and what each viewer may see -------------------------------
    LIBRARY_WORDS = {'video': ('Watch', 'Movies and TV', 'movies and TV'),
                     'audio': ('Listen', 'Audiobooks', 'audiobooks'),
                     'comics': ('Comics', 'comics'),
                     'books': ('Books', 'books')}

    def test_the_account_control_is_the_same_short_menu_on_every_page(self):
        for path in ('/', '/new'):
            for state in fixtures.STATES:
                with self.subTest(path=path, state=state):
                    text = self.body(state, path)
                    menu = text[text.index('<details class="account">'):text.index('</details>')]
                    self.assertEqual(1, text.count('<details class="account">'))
                    # its name starts with the word on screen (label in name), with no stray space before the comma
                    label, inner = re.search(r'<summary aria-label="([^"]*)">(.*?)</summary>', menu).groups()
                    self.assertEqual('Account, signed in as Ada Lovelace', label)
                    self.assertEqual('Account', re.sub(r'<[^>]+>', '', re.sub(r'<span class="mono"[^>]*>.*?</span>', '', inner)))
                    self.assertIn('aria-hidden="true">A</span>', menu)   # the initial is decoration; the word names it
                    self.assertEqual(['Account and security', 'Help', 'Sign out'], re.findall(r'<a [^>]*>([^<]+)</a>', menu))
                    for never in ('@', 'avrana-', 'authentik', '/me', 'role="menu"', 'role="menuitem"'):
                        self.assertNotIn(never, menu)
                    # it comes before the wordmark and the places, so it is in the same place every time
                    self.assertLess(text.index('<details class="account">'), text.index('class="places"'))

    def test_signed_out_gets_sign_in_and_help_and_nothing_of_the_libraries(self):
        for path in ('/', '/new'):
            for state in fixtures.STATES:
                with self.subTest(path=path, state=state):
                    text = self.body(state, path, who='out')
                    self.assertNotIn('<details', text)
                    self.assertIn('>Sign in</a>', text)
                    bar = text[text.index('<nav class="places"'):text.index('</nav>', text.index('<nav class="places"'))]
                    self.assertEqual(['Help'], re.findall(r'<a [^>]*>([^<]+)</a>', bar))
                    for words in self.LIBRARY_WORDS.values():
                        for word in words:
                            self.assertNotIn(word, text)
                    self.assertNotIn('class="card"', text)
                    visible = re.sub(r'<[^>]+>', ' ', text)
                    for never in ('Request', 'Account and security', 'Continue', 'unavailable'):
                        self.assertNotIn(never, visible)

    def test_a_library_the_member_cannot_use_is_never_named_in_any_state(self):
        for who, held in (('books', {'books'}), ('none', set())):
            for path in ('/', '/new'):
                for state in fixtures.STATES:
                    with self.subTest(who=who, path=path, state=state):
                        text = self.body(state, path, who=who)
                        for library, words in self.LIBRARY_WORDS.items():
                            if library in held:
                                continue
                            for word in words:
                                self.assertNotIn(word, text)
                        bar = text[text.index('<nav class="places"'):text.index('</nav>', text.index('<nav class="places"'))]
                        expected = (['Read'] if held else []) + ['Request', 'Help']
                        self.assertEqual(expected, re.findall(r'>([A-Z][a-z]+)<', bar))
                        if not held:
                            self.assertIn('No library is shared with this account yet.', text)
                            self.assertNotIn('class="card"', text)
        # the books member is told nothing about a service it cannot use being down
        self.assertNotIn('class="banner"', self.body('degraded', who='books'))
        self.assertNotIn('id="h-continue"', self.body('healthy', who='books'))   # Continue is video and audio only

    def test_every_link_keeps_the_viewer(self):
        for path in ('/', '/new'):
            text = self.body('healthy', path, who='books')
            for href in re.findall(r'href="(/(?:new)?\?[^"]*)"', text):
                self.assertIn('who=books', href, href)

    def test_account_controls_are_large_enough_and_never_hidden_behind_an_icon(self):
        css = (ROOT / 'tests/ui/home_preview/static/home.css').read_text(encoding='utf-8')
        summary = re.search(r'\.account summary \{([^}]*)\}', css).group(1)
        self.assertIn('min-height: 2.75rem', summary)
        self.assertIn('min-width: 2.75rem', summary)
        self.assertIn('min-height: 2.75rem', re.search(r'\.menu a \{([^}]*)\}', css).group(1))
        self.assertIn('max-width: calc(100vw - 2.5rem)', re.search(r'\.menu \{([^}]*)\}', css).group(1))
        # a text link is a 44px target in both directions, even a short word such as Help
        link = re.search(r'\.link \{([^}]*)\}', css).group(1)
        self.assertIn('min-height: 2.75rem', link)
        self.assertIn('min-width: 2.75rem', link)

    def test_the_skip_link_fits_every_viewer(self):
        for who in fixtures.VIEWERS:
            for path in ('/', '/new'):
                skip = re.search(r'<a class="skip" href="#content">([^<]+)</a>', self.body('healthy', path, who=who)).group(1)
                self.assertNotIn('left', skip, f'{path} {who}')   # not every viewer has anything to continue

    def test_unknown_viewers_are_not_found(self):
        self.assertEqual(404, self.client.get('/', params={'who': 'admin'}).status_code)
        self.assertEqual(404, self.client.get('/new', params={'who': ''}).status_code)

    def test_before_is_the_portal_from_git(self):
        response = self.client.get('/before')
        self.assertEqual(200, response.status_code)
        self.assertIn('Your Avrana services', response.text)
        self.assertNotIn('Operations', response.text)   # the fixture member is not an admin


if __name__ == '__main__':
    unittest.main()
