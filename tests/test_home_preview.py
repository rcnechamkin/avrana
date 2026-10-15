"""The member home preview (tests/ui/home_preview): fixtures only, no network, no credentials.

Skipped where FastAPI is not installed (the preview's README lists the pinned packages).
"""
from importlib.util import find_spec
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Imported as the top-level package "home_preview", not as "tests.ui.home_preview": another suite in
# the same run puts services/avrana-home first on sys.path, and its regular package "tests" (which
# blocks every socket on import) would win over this directory and break unrelated suites.
sys.path.insert(0, str(ROOT / 'tests' / 'ui'))
# Skipped only when the preview's packages are missing; any other import error fails loudly.
if all(find_spec(m) for m in ('fastapi', 'jinja2', 'httpx')):
    from fastapi.testclient import TestClient
    from home_preview import fixtures
    from home_preview.app import app
else:                                                  # pragma: no cover
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


    # ---- Search and title pages (AVR-426) ----------------------------------------------------------
    def test_search_and_title_pages_render_every_state_and_viewer_without_script(self):
        for who in fixtures.VIEWERS:
            for state in fixtures.STATES:
                for path, more in (('/search', {'q': 'the'}), ('/search', {}), ('/title/walden', {})):
                    with self.subTest(path=path, state=state, who=who, **more):
                        response = self.client.get(path, params={'state': state, 'who': who, **more})
                        if path.startswith('/title') and who in ('none', 'out'):
                            self.assertEqual(404, response.status_code)
                            continue
                        self.assertEqual(200, response.status_code)
                        self.assertNotIn('<script', response.text.lower())
                        self.assertEqual(1, response.text.count('<h1'))
                        text = re.sub(r'<[^>]+>', ' ', response.text)
                        self.assertIsNone(re.search(r'[–—]', text))
                        self.assertIsNone(re.search(r"\b(we|our|we're|we've)\b", text, re.I))

    def test_search_is_a_plain_form_to_this_site_only(self):
        response = self.page('healthy', '/search')
        self.assertIn("form-action 'self'", response.headers['content-security-policy'])
        form = re.search(r'<form [^>]*>', response.text).group(0)
        self.assertIn('method="get"', form)
        self.assertIn('action="/search"', form)
        self.assertIn('<label for="q">', response.text)          # a visible label, not a placeholder

    def test_search_finds_only_in_the_members_own_libraries(self):
        self.assertIn('Metropolis', self.body('healthy', '/search', q='metropolis'))
        # a books-only member: the film is not found, and the sentence is the one for a title that exists nowhere
        books = self.body('healthy', '/search', q='metropolis', who='books')
        nowhere = self.body('healthy', '/search', q='zzzz', who='books')
        self.assertNotIn('Metropolis</span>', books)
        self.assertEqual(re.sub(r'metropolis|zzzz', 'X', books), re.sub(r'metropolis|zzzz', 'X', nowhere))
        for word in ('Movies and TV', 'movies and TV', 'Audiobooks', 'Comics'):
            self.assertNotIn(word, re.sub(r'<[^>]+>', ' ', books))

    def test_a_restricted_member_finds_its_own_titles_with_or_without_accents(self):
        for q in ('walden', 'WALDEN', 'bronte', 'jane eyre'):
            text = self.body('healthy', '/search', q=q, who='books')
            self.assertIn('href="/title/', text, q)
            self.assertIn('1 found.', text, q)

    def test_every_result_says_where_it_lives_and_opens_its_title_page(self):
        text = self.body('healthy', '/search', q='the')
        rows = re.findall(r'<a class="row" href="([^"]+)">(.*?)</a>', text, re.S)
        self.assertIn(f'{len(rows)} found.', text)                # the count is the number of rows
        self.assertGreater(len(rows), 4)
        for href, row in rows:
            self.assertTrue(href.startswith('/title/'), href)
            self.assertRegex(row, r'In (Movies and TV|Audiobooks|Books|Comics)</span>')
            self.assertIn('alt=""', row)                          # the title is said in words beside it

    def test_search_says_what_could_not_be_searched_once(self):
        degraded = re.sub(r'<[^>]+>', ' ', self.body('degraded', '/search', q='the'))
        self.assertIn('Movies and TV were not searched', degraded)
        self.assertEqual(1, degraded.count('Movies and TV'), 'the outage is said once on a search page')
        # a library still answering: "nothing called" is only claimed for the libraries that did
        slow = re.sub(r'<[^>]+>', ' ', self.body('slow', '/search', q='dracula'))
        self.assertIn('in the libraries that answered', slow)
        self.assertNotIn('in your libraries', slow)
        self.assertNotIn('Metropolis', degraded)
        slow = self.body('slow', '/search', q='the')
        self.assertIn('Audiobooks are taking longer than usual', slow)
        self.assertIn('Try again', slow)
        gone = self.body('unavailable', '/search', q='the')
        self.assertIn('nothing can be searched', gone)
        self.assertIn('disabled', re.search(r'<input id="q"[^>]*>', gone).group(0))
        self.assertNotIn('class="row"', gone)

    def test_the_query_is_escaped_trimmed_and_bounded(self):
        text = self.body('healthy', '/search', q='  <img src=x onerror=1>  ' + 'a' * 300)
        self.assertNotIn('<img src=x', text)
        self.assertIn('&lt;img src=x onerror=1&gt;', text)
        self.assertNotIn('a' * 101, text)

    def test_a_title_in_a_library_the_member_cannot_use_does_not_exist(self):
        for path in ('/title/metropolis', '/title/moby-dick'):
            self.assertEqual(404, self.client.get(path, params={'who': 'books'}).status_code)
        self.assertEqual(404, self.client.get('/title/not-a-title').status_code)
        self.assertEqual(200, self.client.get('/title/walden', params={'who': 'books'}).status_code)

    def test_a_title_page_puts_the_title_then_one_action_then_the_rest(self):
        text = self.body('healthy', '/title/nosferatu')
        order = [text.index(m) for m in ('<h1', 'class="button"', '<progress', 'class="synopsis"', 'class="facts"')]
        self.assertEqual(order, sorted(order))
        self.assertEqual(1, text.count('class="button"'))
        self.assertIn('Resume in Movies and TV', text)
        for claim in ('Playing', 'Now playing', 'started'):              # it opens an app; it never says it played
            self.assertNotIn(claim, text)
        self.assertIn('Watch in Movies and TV', self.body('empty', '/title/nosferatu'))   # no progress, no resume
        self.assertNotIn('<progress', self.body('healthy', '/title/metropolis'))

    def test_a_title_whose_library_is_down_offers_nothing_and_says_so_once(self):
        text = self.body('degraded', '/title/metropolis')
        self.assertNotIn('class="button"', text)
        self.assertNotIn('Metropolis', re.sub(r'<[^>]+>', ' ', text.split('<main', 1)[1]))
        self.assertEqual(1, text.count('Movies and TV are unavailable right now.'))
        # every library down: the operator's notice stays, it says more than the sentence
        self.assertIn('offline this evening', self.body('unavailable', '/title/metropolis'))
        slow = self.body('slow', '/title/moby-dick')
        self.assertNotIn('class="button"', slow)
        self.assertIn('Try again', slow)

    def test_new_cards_open_title_pages_and_continue_cards_hand_off(self):
        text = self.body('healthy')
        rails = text.split('id="h-new"', 1)
        self.assertNotIn('href="/title/', rails[0].split('id="h-continue"', 1)[1])
        self.assertIn('href="/title/metropolis?state=healthy"', rails[1])


if __name__ == '__main__':
    unittest.main()
