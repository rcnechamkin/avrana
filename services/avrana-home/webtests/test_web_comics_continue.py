"""Owner review 2026-10-28 (live beta): comics in Home's Continue rail and hero. SYNTHETIC data only.

Tier A (standard library): an On Deck book (contract shelf "next", no progress) says "Up next" on its card and in the
hero, never passing for a started one; a "<series> #<number>" title does not repeat the series below it but keeps the
number; every Continue card has a second line; the rail is marked "mixed" when a still shares it with taller covers,
"stills" when it holds stills alone; the MK-10 stylesheet block (no new colour, no library words, no new image source).
Tier B (framework): the rail's classes and the still's blurred copy in the markup.
"""
import re
import unittest
from pathlib import Path

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import CardVM, build_home, rail_shape

from .support import make_client, make_settings, require_framework

TEMPLATES = Path(__file__).resolve().parents[1] / "avrana_home" / "app" / "templates"
TILES = [("watch", Trusted("Watch"), Trusted("Movies")), ("listen", Trusted("Listen"), Trusted("Audio")),
         ("comics", Trusted("Comics"), Trusted("Comics")), ("help", Trusted("Help"), Trusted("Guides"))]
HOST = {"jellyfin": "https://watch.avrana.net/web/#/details?id=", "audiobookshelf": "https://listen.avrana.net/item/",
        "komga": "https://read.avrana.net/book/"}
JF1 = "a" * 32
READING = {"fraction": 0.4, "percent": 40, "position_seconds": None, "duration_seconds": None}
SAVED = {"position_seconds": 1800, "duration_seconds": 6000}


def item(service, upstream, title, kind, progress=None, series=None, subtitle=None, shelf=None, art=True):
    out = {"id": f"{service}:{upstream}", "service": service, "kind": kind, "title": title, "series": series,
           "subtitle": subtitle, "handoff_url": HOST[service] + upstream, "progress": progress,
           "artwork": {"ref": f"{service}/book/{upstream}" if service == "komga" else f"{service}/primary/{upstream}"}
           if art else None}
    if shelf:
        out["shelf"] = shelf
    return out


def cont(service, *items):
    return {"service": service, "section": "continue", "state": "ok", "items": list(items), "reason": None}


READ = item("komga", "BOOKREAD0001", "Synthetic Saga #2", "comic", READING, series="Synthetic Saga", subtitle="#2")
NEXT = item("komga", "BOOKNEXT0001", "Synthetic Saga #3", "comic", series="Synthetic Saga", subtitle="#3", shelf="next")
EPISODE = item("jellyfin", JF1, "Synthetic Pilot", "episode", SAVED, series="Synthetic Harbour", subtitle="S1 E3")


class ContinueComics(unittest.TestCase):
    def test_on_deck_says_up_next_and_in_progress_says_how_far(self):
        home = build_home({"sections": [cont("komga", READ, NEXT)]}, TILES)
        self.assertEqual([("40 percent read", 40, "Open"), ("Up next", None, "Open")],
                         [(c.progress, c.bar, c.action) for c in home.continue_items])

    def test_an_up_next_hero_says_so(self):
        hero = build_home({"sections": [cont("komga", NEXT)]}, TILES).hero
        self.assertEqual(("continue", "Synthetic Saga #3", "Up next · Comics", None, "Read in Komga"),
                         (hero.state, hero.title, hero.facts, hero.left, hero.action))
        hero = build_home({"sections": [cont("komga", READ)]}, TILES).hero
        self.assertEqual(("#2 · Comics", "40 percent read"), (hero.facts, hero.left))

    def test_up_next_needs_the_shelf_and_no_progress(self):
        started = dict(NEXT, progress=READING)
        other = dict(NEXT, shelf="new")
        home = build_home({"sections": [cont("komga", started, other)]}, TILES)
        self.assertEqual(["40 percent read", None], [c.progress for c in home.continue_items])

    def test_a_series_and_number_title_keeps_only_the_number_below_it(self):
        home = build_home({"sections": [cont("komga", READ)]}, TILES)
        self.assertEqual(("Synthetic Saga #2", "#2"), (home.continue_items[0].title, home.continue_items[0].line))
        titled = item("komga", "BOOKTITL0001", "The Quiet Issue", "comic", READING, series="Synthetic Saga",
                      subtitle="#4")
        home = build_home({"sections": [cont("komga", titled)]}, TILES)
        self.assertEqual("Synthetic Saga · #4", home.continue_items[0].line)

    def test_every_continue_card_has_a_second_line(self):
        movie = item("jellyfin", JF1, "Synthetic Film", "movie", SAVED)
        bare = item("komga", "BOOKBARE0001", "Synthetic One-Shot", "comic", READING)
        home = build_home({"sections": [cont("jellyfin", movie), cont("komga", bare)]}, TILES)
        self.assertEqual(["Movie", "Comic"], [c.line for c in home.continue_items])

    def test_the_rail_says_when_stills_share_it_with_covers(self):
        mixed = build_home({"sections": [cont("jellyfin", EPISODE), cont("komga", READ)]}, TILES)
        self.assertEqual("mixed", mixed.continue_rail)
        self.assertEqual("stills", build_home({"sections": [cont("jellyfin", EPISODE)]}, TILES).continue_rail)
        self.assertEqual("", build_home({"sections": [cont("komga", READ, NEXT)]}, TILES).continue_rail)
        self.assertEqual("", rail_shape(()))

    def test_an_episode_with_its_series_poster_is_a_poster_card(self):
        poster = dict(EPISODE, artwork={"ref": "jellyfin/primary/" + "b" * 32, "alt": "Poster", "shape": "poster"})
        home = build_home({"sections": [cont("jellyfin", poster), cont("komga", READ)]}, TILES)
        self.assertEqual(["poster", "comic"], [c.shape for c in home.continue_items])
        self.assertEqual("", home.continue_rail)                          # no still left: nothing to even out
        self.assertEqual(("poster", "/art/jellyfin/primary/" + "b" * 32), (home.hero.shape, home.hero.image))
        self.assertEqual("S1 E3 · Synthetic Harbour", home.continue_items[0].line)   # still says which episode
        for odd in ({"ref": "jellyfin/primary/" + "b" * 32, "shape": "banner"}, {"ref": "../x", "shape": "poster"}):
            home = build_home({"sections": [cont("jellyfin", dict(EPISODE, artwork=odd))]}, TILES)
            self.assertEqual("still", home.continue_items[0].shape, odd)
        self.assertEqual("mixed", rail_shape([CardVM("a", "h", "still", None, None), CardVM("b", "h", "square", None, None)]))


class Stylesheet(unittest.TestCase):
    def setUp(self):
        css = (TEMPLATES / "home.css").read_text(encoding="utf-8")
        marker = "  /* ---- MK-10 Mixed rails (owner review 2026-10-28) ---- */\n"
        self.assertEqual(1, css.count(marker))
        self.block = re.split(r"\n  /\* ---- MK-", css.split(marker, 1)[1], maxsplit=1)[0]
        self.rules = re.sub(r"/\*.*?\*/", "", self.block, flags=re.S)

    def test_a_still_among_covers_stands_the_rails_height_over_its_own_blurred_copy(self):
        self.assertIn(".rail.mixed>li.w-still{--fh:var(--art-h);}", self.rules)
        self.assertRegex(self.rules, r"\.frame \.glow \.art\{[^}]*filter:blur\(")
        self.assertIn("@media (prefers-contrast:more){.frame .glow{display:none;}}", self.rules)
        self.assertIn("@media (forced-colors:active){.frame .glow{display:none;}}", self.rules)

    def test_titles_keep_two_lines_of_room_in_the_rail(self):
        self.assertIn(".rail.cont .t{min-height:2.6em;}", self.rules)

    def test_the_hero_has_no_rules_here(self):
        # The cover-beside-the-words hero went with H3 refined (owner decision 2026-10-29): one picture for every shape.
        self.assertNotIn(".hero", self.rules)

    def test_no_new_colour_image_source_or_library_word(self):
        self.assertNotIn("url(", self.rules)
        self.assertNotIn("--accent", self.rules)
        self.assertNotRegex(self.rules, r"#[0-9a-fA-F]{6}\b")
        for word in ("Continue", "Resume", "Recently", "Jellyfin", "Audiobook", "Komga", "komga", "Comic", "comic",
                     "Calibre", "Movies", "Books", "deck", "Deck"):
            self.assertNotIn(word, self.block, word)


class Markup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_framework()
        cls.env = make_client(make_settings(home_sections=False)).fastapi_app.state.env

    def rail(self, *sections):
        html = self.env.get_template("_sections.html").render(home=build_home({"sections": list(sections)}, TILES))
        return re.search(r'<section class="shelf" aria-labelledby="h-continue">.*?</section>', html, flags=re.S).group(0)

    def test_a_mixed_rail_gives_only_the_still_its_blurred_copy(self):
        rail = self.rail(cont("jellyfin", EPISODE), cont("komga", READ))
        self.assertIn('<ul class="rail cont mixed">', rail)
        still = re.search(r'<li class="w-still">.*?</li>', rail, flags=re.S).group(0)
        cover = re.search(r'<li class="w-comic">.*?</li>', rail, flags=re.S).group(0)
        src = f"/art/jellyfin/primary/{JF1}"
        self.assertIn(f'<span class="glow" aria-hidden="true"><img class="art" src="{src}" alt="" width="160" '
                      f'height="240" loading="lazy"></span><img class="art" src="{src}"', still)
        self.assertEqual(2, still.count("<img"))                           # the same /art image, twice
        self.assertNotIn("glow", cover)
        self.assertEqual(1, still.count("<a "))
        self.assertNotRegex(rail, r"style=|<script|on\w+=")

    def test_other_rails_have_no_blurred_copy(self):
        stills = self.rail(cont("jellyfin", EPISODE))
        self.assertIn('<ul class="rail cont stills">', stills)
        self.assertNotIn("glow", stills)
        covers = self.rail(cont("komga", READ, NEXT))
        self.assertIn('<ul class="rail cont">', covers)
        self.assertNotIn("glow", covers)
        self.assertIn('<span class="d" aria-hidden="true">Up next</span>', covers)
        self.assertIn('<span class="sr">, Up next</span>', covers)

    def test_a_still_without_art_has_no_blurred_copy(self):
        rail = self.rail(cont("jellyfin", dict(EPISODE, artwork=None)), cont("komga", READ))
        self.assertIn('<ul class="rail cont mixed">', rail)
        self.assertNotIn("glow", rail)


if __name__ == "__main__":
    unittest.main()
