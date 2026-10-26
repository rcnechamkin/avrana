"""AVR-718 (MK-4): Home's Concept K hero, the Recently added wording and the Continue progress rule. SYNTHETIC data only.

Tier A (standard library): the view-model picks the member's own next thing (the first Continue item, else the first
Recently added item), never an item from a library said to be down; one primary hand-off whose words never claim
playback; Details only where a title page exists; the progress rule in 5% steps beside the words; the MK-4 stylesheet
block (yellow only for the member's own state, Cream progress, no new image source).
Tier B (framework): the markup (eyebrow inside the heading, one hand-off link, art only from /art, the letter frame
without art), and two members through the real transport, each seeing only their own hero.
"""
import re
import unittest
from pathlib import Path

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import build_home

from .support import GROUPS, USER, make_client, make_settings, require_framework

TEMPLATES = Path(__file__).resolve().parents[1] / "avrana_home" / "app" / "templates"
TILES = [("watch", Trusted("Watch"), Trusted("Movies")), ("listen", Trusted("Listen"), Trusted("Audio")),
         ("comics", Trusted("Comics"), Trusted("Comics")), ("books", Trusted("Books"), Trusted("Books")),
         ("help", Trusted("Help"), Trusted("Guides"))]
HOST = {"jellyfin": "https://watch.avrana.net/web/#/details?id=", "audiobookshelf": "https://listen.avrana.net/item/",
        "komga": "https://read.avrana.net/book/", "calibre-web": "https://books.avrana.net/book/"}
JF1, JF2 = "a" * 32, "b" * 32
TITLED = frozenset({"jellyfin", "audiobookshelf", "komga", "calibre-web"})
# Words a hand-off must never use: it opens the library at the item, it does not start anything (AVR-384).
PLAYBACK_CLAIMS = re.compile(r"(?i)\b(play|playing|now playing|watching now|started|starts)\b")


def item(service, upstream, title, kind="movie", progress=None, art=None, series=None, subtitle=None):
    return {"id": f"{service}:{upstream}", "service": service, "kind": kind, "title": title, "series": series,
            "subtitle": subtitle, "handoff_url": HOST[service] + upstream, "progress": progress,
            "artwork": {"ref": art} if art else None}


def sec(service, section, state, items=()):
    return {"service": service, "section": section, "state": state, "items": list(items), "reason": None}


def view(*sections):
    return {"sections": list(sections)}


SAVED = {"position_seconds": 1800, "duration_seconds": 6000}          # 30% through, a saved position
FRACTION_ONLY = {"fraction": 0.4}                                       # progress, but no position: never "Resume"


class HeroViewModel(unittest.TestCase):
    def test_continue_hero_is_the_first_continue_item_with_honest_words(self):
        v = view(sec("jellyfin", "continue", "ok", [item("jellyfin", JF1, "Harbour", progress=SAVED,
                                                         art=f"jellyfin/primary/{JF1}")]),
                 sec("jellyfin", "recent", "ok", [item("jellyfin", JF2, "Newer")]))
        hero = build_home(v, TILES, title_services=TITLED).hero
        self.assertEqual(("continue", "Harbour", "poster"), (hero.state, hero.title, hero.shape))
        self.assertEqual("Resume in Jellyfin", hero.action)
        self.assertEqual(HOST["jellyfin"] + JF1, hero.action_href)
        self.assertEqual("1 hour 10 minutes left · Movies and TV", hero.meta)
        self.assertEqual(f"/art/jellyfin/primary/{JF1}", hero.image)
        self.assertEqual(f"/title/jellyfin/{JF1}", hero.details_href)

    def test_each_library_gets_its_own_hand_off_and_resume_needs_a_saved_position(self):
        cases = [
            (sec("jellyfin", "continue", "ok", [item("jellyfin", JF1, "F", progress=FRACTION_ONLY)]), "Open in Jellyfin"),
            (sec("audiobookshelf", "continue", "ok", [item("audiobookshelf", "li_abcdef1", "A", "audiobook", SAVED)]),
             "Listen in Audiobookshelf"),
            (sec("komga", "recent", "ok", [item("komga", "BOOKAAAA01", "C", "comic")]), "Read in Komga"),
            (sec("calibre-web", "recent", "ok", [item("calibre-web", "17", "B", "ebook")]), "Open in Calibre-Web"),
            (sec("jellyfin", "recent", "ok", [item("jellyfin", JF1, "R", progress=SAVED)]), "Open in Jellyfin"),
        ]
        for section, words in cases:
            with self.subTest(words=words):
                hero = build_home(view(section), TILES).hero
                self.assertEqual(words, hero.action)
                self.assertNotRegex(hero.action, PLAYBACK_CLAIMS)

    def test_nothing_in_progress_shows_the_first_recently_added_whatever_the_tab(self):
        v = view(sec("jellyfin", "continue", "empty"),
                 sec("jellyfin", "recent", "ok", [item("jellyfin", JF1, "Film", series="Saga")]),
                 sec("komga", "recent", "ok", [item("komga", "BOOKAAAA01", "Comic", "comic")]))
        for tab in (None, "komga", "jellyfin"):
            hero = build_home(v, TILES, new_tab=tab).hero
            self.assertEqual(("recent", "Film", "Saga · Movies and TV"), (hero.state, hero.title, hero.meta), tab)
        only = build_home(view(sec("komga", "recent", "ok", [item("komga", "BOOKAAAA01", "Comic", "comic")])), TILES).hero
        self.assertEqual(("recent", "comic", "Comics"), (only.state, only.shape, only.meta))   # kicker_of: no "Comic · Comics"

    def test_a_library_said_to_be_down_never_supplies_the_hero(self):
        # Movies and TV answer from the cache (ok) but also said unavailable: its card stays, the hero moves on.
        v = view(sec("jellyfin", "continue", "ok", [item("jellyfin", JF1, "Stale", progress=SAVED)]),
                 sec("jellyfin", "recent", "unavailable"),
                 sec("audiobookshelf", "continue", "ok", [item("audiobookshelf", "li_abcdef1", "Book", "audiobook", SAVED)]))
        home = build_home(v, TILES)
        self.assertEqual("Book", home.hero.title)
        self.assertIn("Stale", [c.title for c in home.continue_items])
        self.assertTrue(any("unavailable" in n for n in home.notices))
        down_only = view(sec("jellyfin", "continue", "ok", [item("jellyfin", JF1, "Stale", progress=SAVED)]),
                         sec("jellyfin", "recent", "unavailable"))
        self.assertIsNone(build_home(down_only, TILES).hero)

    def test_states_with_nothing_of_the_members_own_have_no_hero(self):
        self.assertIsNone(build_home(view(), [TILES[-1]]).hero)                                  # H5 no library
        self.assertIsNone(build_home(view(sec("jellyfin", "continue", "unavailable"),
                                          sec("jellyfin", "recent", "unavailable")), TILES).hero)   # resting
        self.assertIsNone(build_home(view(sec("jellyfin", "continue", "not_linked")), TILES).hero)  # not set up
        self.assertIsNone(build_home(view(sec("jellyfin", "continue", "empty"),
                                          sec("jellyfin", "recent", "empty")), TILES).hero)         # nothing at all

    def test_details_only_where_a_title_page_exists_and_the_id_is_valid(self):
        good = view(sec("jellyfin", "continue", "ok", [item("jellyfin", JF1, "F", progress=SAVED)]))
        self.assertIsNone(build_home(good, TILES).hero.details_href)                 # no title services: no Details
        self.assertIsNone(build_home(good, TILES, title_services=frozenset({"komga"})).hero.details_href)
        bad = view(sec("jellyfin", "continue", "ok", [dict(item("jellyfin", JF1, "F", progress=SAVED), id="jellyfin:../x")]))
        self.assertIsNone(build_home(bad, TILES, title_services=TITLED).hero.details_href)
        other = view(sec("jellyfin", "continue", "ok", [dict(item("jellyfin", JF1, "F", progress=SAVED), id=f"komga:{JF1}")]))
        self.assertIsNone(build_home(other, TILES, title_services=TITLED).hero.details_href)

    def test_no_art_and_foreign_art_refs_leave_the_letter_frame(self):
        v = view(sec("jellyfin", "continue", "ok", [item("jellyfin", JF1, "F", progress=SAVED,
                                                         art="https://evil.example/x.png")]))
        self.assertIsNone(build_home(v, TILES).hero.image)

    def test_a_hand_off_off_its_own_host_never_becomes_the_hero(self):
        stray = dict(item("jellyfin", JF1, "F", progress=SAVED), handoff_url="https://listen.avrana.net/item/li_abcdef1")
        self.assertIsNone(build_home(view(sec("jellyfin", "continue", "ok", [stray])), TILES).hero)

    def test_progress_rule_in_five_percent_steps_beside_words_only(self):
        v = view(sec("jellyfin", "continue", "ok", [item("jellyfin", JF1, "A", progress=SAVED),
                                                    item("jellyfin", JF2, "B", progress={"percent": 42}),
                                                    item("jellyfin", "c" * 32, "C")]),
                 sec("jellyfin", "recent", "ok", [item("jellyfin", "d" * 32, "D", progress=SAVED)]))
        home = build_home(v, TILES)
        self.assertEqual([30, 40, None], [c.bar for c in home.continue_items])
        self.assertEqual([None], [c.bar for c in home.new_items])           # Recently added: no rule

    def test_recently_added_wording_is_not_date_bounded(self):
        v = view(sec("jellyfin", "recent", "empty"), sec("komga", "recent", "ok", [item("komga", "BOOKAAAA01", "C", "comic")]))
        self.assertEqual("Nothing recently added in Movies and TV.", build_home(v, TILES, new_tab="jellyfin").new_said)
        self.assertEqual("Nothing recently added.", build_home(view(sec("jellyfin", "recent", "empty")), TILES).new_said)


class Stylesheet(unittest.TestCase):
    def setUp(self):
        css = (TEMPLATES / "home.css").read_text(encoding="utf-8")
        marker = "  /* ---- MK-4 Home (AVR-718) ---- */\n"
        self.assertEqual(1, css.count(marker))
        # MK-4's block runs from its marker to the next slice's marker (MK-5 appends its own blocks after it)
        self.block = re.split(r"\n  /\* ---- MK-(?!4 )", css.split(marker, 1)[1], maxsplit=1)[0]
        self.rules = re.sub(r"/\*.*?\*/", "", self.block, flags=re.S)

    def test_yellow_marks_only_the_members_own_state_and_progress_is_cream(self):
        self.assertIn(".hero-title .k-eyebrow.yours::before{", self.rules)
        self.assertIn("background:var(--accent);", re.search(r"\.k-eyebrow\.yours::before\{[^}]*\}", self.rules).group(0))
        self.assertEqual(1, self.rules.count("var(--accent)"))            # the signal bar, nothing else
        self.assertIn(".frame .bar .fill{display:block;height:100%;border-radius:inherit;background:var(--cream);}", self.rules)
        for banned in ("#e8cf8a", "#b9a9e8", "purple", "--accent-selected", "--accent-lens"):
            self.assertNotIn(banned, self.rules.lower())

    def test_the_backdrop_is_css_on_the_same_image_and_no_new_image_source(self):
        self.assertRegex(self.rules, r"\.hero-glow \.art\{[^}]*filter:blur\(")
        self.assertNotIn("url(", self.rules)                               # art only arrives as <img src="/art/...">
        self.assertNotIn("backdrop-filter", re.search(r"\.hero-glow\{[^}]*\}", self.rules).group(0))

    def test_the_block_names_no_section_library_or_member_word(self):
        # home.css ships on every shell page, revoked members included: the revocation and isolation tests read the
        # whole page for words like these, so the stylesheet (comments too) must never carry them.
        for word in ("Continue", "Resume", "Recently", "New this week", "Jellyfin", "Audiobook", "audiobook",
                     "listening", "Komga", "komga", "Comic", "Calibre", "calibre", "Movies", "Books"):
            self.assertNotIn(word, self.block, word)

    def test_section_headings_use_the_shelf_role_on_home_only(self):
        self.assertIn("body:has(.mast.at-home) .shelf h2{font-size:var(--text-shelf);", self.rules)
        self.assertIn("text-transform:none", re.search(r"\.shelf h2\{[^}]*\}", self.rules).group(0))

    def test_the_display_title_wraps_and_is_never_fitted_to_its_title(self):
        title = re.search(r"\.hero-title \.k-display\{[^}]*\}", self.rules).group(0)
        self.assertIn("font-size:min(var(--text-display),calc(0.5rem + 12.5vw))", title)   # 48px at default text
        self.assertNotIn("white-space:nowrap", title)
        self.assertIn("overflow-wrap:break-word", title)
        self.assertNotIn("anywhere", title)


class Markup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_framework()
        cls.env = make_client(make_settings(home_sections=False)).fastapi_app.state.env

    def render(self, v, **kw):
        return self.env.get_template("_sections.html").render(home=build_home(v, TILES, **kw))

    def hero_of(self, html):
        found = re.findall(r'<section class="hero[^"]*".*?</section>', html, flags=re.S)
        self.assertEqual(1, len(found))
        return found[0]

    def test_continue_hero_markup(self):
        v = view(sec("jellyfin", "continue", "ok", [item("jellyfin", JF1, "Harbour <b>&", progress=SAVED,
                                                         art=f"jellyfin/primary/{JF1}")]))
        hero = self.hero_of(self.render(v, title_services=TITLED))
        self.assertIn('<section class="hero w-poster" aria-labelledby="h-hero">', hero)
        self.assertIn('<h2 id="h-hero" class="hero-title"><span class="k-eyebrow yours">Continue<span class="sr">: </span>'
                      '</span> <span class="k-display">Harbour &lt;b&gt;&amp;</span></h2>', hero)
        links = re.findall(r"<a [^>]*>", hero)
        self.assertEqual([f'<a class="hero-go" href="{HOST["jellyfin"]}{JF1}">', f'<a class="hero-details" href="/title/jellyfin/{JF1}">'], links)
        # the visible words start each link's name; the title follows for screen readers; no aria-label hides them
        self.assertIn('>Resume in Jellyfin<span class="sr">: Harbour &lt;b&gt;&amp;</span></a>', hero)
        self.assertIn('>Details<span class="sr">: Harbour &lt;b&gt;&amp;</span></a>', hero)
        self.assertNotIn("aria-label=", hero)
        imgs = re.findall(r"<img[^>]*>", hero)
        self.assertEqual(2, len(imgs))                                     # crisp and blurred: the same /art image
        for tag in imgs:
            self.assertEqual(f'<img class="art" src="/art/jellyfin/primary/{JF1}" alt="" width="160" height="240" loading="lazy">', tag)
        self.assertIn('<span class="hero-glow" aria-hidden="true">', hero)
        self.assertNotRegex(hero, r"style=|<script|on\w+=")

    def test_recently_added_hero_is_stone_and_no_art_shows_the_letter(self):
        v = view(sec("komga", "recent", "ok", [item("komga", "BOOKAAAA01", "zebra", "comic")]))
        html = self.render(v)
        hero = self.hero_of(html)
        self.assertIn('<section class="hero w-comic no-art" aria-labelledby="h-hero">', hero)
        self.assertIn('<span class="k-eyebrow">Recently added<span class="sr">: </span></span>', hero)
        self.assertNotIn("yours", hero)
        self.assertNotIn("<img", hero)
        self.assertNotIn("hero-glow", hero)
        self.assertIn('<span class="frame"><span class="ph" aria-hidden="true">Z</span></span>', hero)
        self.assertNotIn("hero-details", hero)                             # no title services: no Details
        self.assertIn('<h2 id="h-new">Recently added</h2>', html)
        self.assertIn('aria-label="Recently added, by library"', html)
        self.assertNotIn("New this week", html)

    def test_continue_cards_carry_the_rule_and_keep_one_link(self):
        v = view(sec("jellyfin", "continue", "ok", [item("jellyfin", JF1, "A", progress=SAVED)]))
        html = self.render(v)
        card = re.search(r'<li class="w-poster"><a class="card".*?</li>', html, flags=re.S).group(0)
        self.assertEqual(1, card.count("<a "))
        self.assertIn('<span class="bar" aria-hidden="true"><span class="fill pc30"></span></span></span>', card)
        self.assertNotRegex(re.search(r"<a [^>]*>", card).group(0), r"aria-label")

    def test_no_hero_without_anything_of_the_members_own(self):
        html = self.render(view(sec("jellyfin", "continue", "empty"), sec("jellyfin", "recent", "empty")))
        self.assertNotIn('class="hero', html)


A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
B = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos|avrana-books|avrana-comics")]


def main_of(text):
    return re.split(r"<main(?:\s[^>]*)?>", text)[1].split("</main>")[0]


class TwoMembers(unittest.TestCase):
    """Through the real transport against the mock Jellyfin: each member's hero is their own."""

    @classmethod
    def setUpClass(cls):
        require_framework()
        from dev.mock_jellyfin import MockJellyfin
        cls.mock = MockJellyfin(slow_seconds=3.0).start()
        cls.client = make_client(make_settings(home_sections=True, jellyfin_base_url=cls.mock.url, timeout=0.6))
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.mock.stop()

    def hero(self, headers):
        text = self.client.get("/", headers=headers).text
        found = re.findall(r'<section class="hero[^"]*".*?</section>', main_of(text), flags=re.S)
        self.assertEqual(1, len(found))
        return text, found[0]

    def test_each_member_sees_only_their_own_hero(self):
        a_text, a = self.hero(A)
        b_text, b = self.hero(B)
        self.assertIn("Synthetic Film One", a)
        self.assertIn("Synthetic Film Two", b)
        for mine, theirs, page in ((a, "bbbb", a_text), (b, "aaaa", b_text)):
            self.assertNotIn(theirs, page)                                 # no id, art ref or hand-off of the other
            self.assertEqual(1, mine.count('class="hero-go"'))
            href = re.search(r'<a class="hero-go" href="([^"]*)">', mine).group(1)
            self.assertTrue(href.startswith("https://watch.avrana.net/web/#/details?id="), href)
            for src in re.findall(r'src="([^"]*)"', mine):
                self.assertTrue(src.startswith("/art/jellyfin/primary/"), src)
        self.assertNotIn("Synthetic Film Two", a_text)
        self.assertNotIn("Synthetic Film One", b_text)

    def test_the_library_tab_still_lands_on_recently_added(self):
        text, _hero = self.hero(A)
        self.assertIn('<a class="tab" href="/#h-new">', text)
        self.assertIn('<h2 id="h-new">Recently added</h2>', text)


if __name__ == "__main__":
    unittest.main()
