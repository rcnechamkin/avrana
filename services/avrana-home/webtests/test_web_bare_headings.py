"""Home never prints a section heading over nothing, and never repeats a heading id (RC2 review D-01, D-02, U-07).

D-01: Continue empty while a library's Continue is down left a bare "Continue" heading under the banner.
D-02: Listen with Audiobooks not set up left a bare "New to Avrana" heading under the banner.
U-07: on Listen, New Releases and New to Avrana both got id="h-new".
The rule (docs/design/DESIGN.md, "Nothing to show"): a section stands only with a card or a line of its own; when the
library is down or not set up the banner already says so, and the section is left out. SYNTHETIC adapters, real app."""
import re
import unittest

from .plan_adapters import ALL_GROUPS, adapters_for
from .support import GROUPS, USER, make_client, make_settings, require_framework

require_framework()

from avrana_home.contract import Service  # noqa: E402

MEMBER = [(USER, "member-a"), (GROUPS, ALL_GROUPS)]


def get(plans, url):
    with make_client(make_settings(home_sections=True), adapters=adapters_for(plans)) as client:
        r = client.get(url, headers=MEMBER)
    assert r.status_code == 200, (url, r.status_code)
    return r.text


def main_of(text):
    return re.split(r"<main(?:\s[^>]*)?>", text, maxsplit=1)[1].split("</main>")[0]


def empty_headings(main):
    """Headings of sections that hold neither a card, a line of text, a nav nor a notice."""
    bad = []
    for chunk in main.split("<section")[1:]:
        body = chunk.split("</section>")[0]
        if 'class="hero ' in body.split(">", 1)[0]:
            continue
        for h in re.findall(r"<h2[^>]*>([^<]*)</h2>", body):
            if not re.search(r"<li\b|class=\"said\"|<p\b|<nav\b", body):
                bad.append(h)
    return bad


def duplicate_ids(text):
    ids = re.findall(r'\sid="([^"]+)"', text)
    return sorted({i for i in ids if ids.count(i) > 1})


class BareHeadings(unittest.TestCase):
    def test_d01_continue_empty_and_books_down_has_no_bare_continue(self):
        plan = {Service.KOMGA: {"continue": "empty"}, Service.CALIBRE_WEB: {"continue": "unavailable", "recent": "unavailable"},
                Service.JELLYFIN: {"continue": "empty"}, Service.AUDIOBOOKSHELF: {"continue": "empty"}}
        text = get(plan, "/?for=read")
        self.assertIn("Books are unavailable right now.", text)
        self.assertEqual([], empty_headings(main_of(text)))
        self.assertNotIn('id="h-continue"', text)

    def test_d01_an_empty_continue_with_nothing_down_keeps_its_heading_and_line(self):
        text = get({s: {"continue": "empty"} for s in (Service.KOMGA, Service.CALIBRE_WEB)}, "/?for=read")
        self.assertIn('id="h-continue"', text)
        self.assertIn("Nothing in progress.", text)
        self.assertEqual([], empty_headings(main_of(text)))

    def test_d02_audiobooks_not_set_up_has_no_bare_new_to_avrana(self):
        plan = {Service.AUDIOBOOKSHELF: {"continue": "empty", "recent": "not_linked", "shelves": "not_linked"}}
        text = get(plan, "/?for=listen")
        self.assertIn("Audiobooks are not set up for your account yet.", text)
        self.assertEqual([], empty_headings(main_of(text)))
        self.assertNotIn('id="h-new"', text)


class UniqueIds(unittest.TestCase):
    def test_u07_listen_new_releases_and_new_to_avrana_have_their_own_ids(self):
        text = get({}, "/?for=listen")
        main = main_of(text)
        self.assertEqual([], duplicate_ids(text))
        self.assertRegex(main, r'<h2 id="h-released">New Releases</h2>')
        self.assertRegex(main, r'<h2 id="h-new">New to Avrana</h2>')

    def test_every_route_keeps_its_heading_ids_unique(self):
        for url in ("/", "/?for=watch", "/?for=listen", "/?for=read", "/?for=comics", "/?for=books", "/?more=new",
                    "/?more=released&for=listen"):
            with self.subTest(url=url):
                self.assertEqual([], duplicate_ids(get({}, url)))

    def test_show_more_links_point_at_the_section_they_belong_to(self):
        text = get({}, "/?for=listen")
        for anchor in re.findall(r'href="[^"]*#(h-[a-z]+)"', text):
            self.assertIn(f'id="{anchor}"', text, anchor)


if __name__ == "__main__":
    unittest.main()
