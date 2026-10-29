"""Continue's order and New for You in the Jellyfin and Komga adapters (owner requests 2026-10-28). Offline, synthetic
data only; the upstream fields (Jellyfin LastPlayedDate, DateCreated, ProviderIds.TmdbCollection; Komga readProgress.
readDate, created, On Deck) are from the published OpenAPI files and the Komga 1.25.0 source, UNVERIFIED live.

  * Every Continue item carries `active`: when THIS member last touched it (an Up next or On Deck item: its series).
  * New for You is the member's next episode (Jellyfin Up next) or next book (Komga On Deck) that arrived in the last
    30 days, plus a newly added film from a collection the member has watched a film of. Older, started or unrelated
    things are left out. Komga needs the member's own key, as Continue does.
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.adapters.komga import KomgaAdapter
from avrana_home.contract import SectionState
from avrana_home.member_keys import MemberKeyStore, read_keys, write_keys
from avrana_home.principal import principal_from_headers
from avrana_home.resilience import FakeClock
from tests.fake_jellyfin import A, FakeJellyfin, FakeTransport
from tests.fake_komga import FakeKomga
from tests.helpers import make_principal

NOW = datetime.now(timezone.utc)


def stamp(days_ago, hours=0):
    return (NOW - timedelta(days=days_ago, hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.%f0Z")   # .NET's seven digits


def jid(n):
    return f"{n:032x}"


def episode(n, series, created, position=0, played=False, last=None):
    data = {"PlaybackPositionTicks": position, "Played": played}
    if last:
        data["LastPlayedDate"] = last
    return {"Id": jid(n), "Name": f"Episode {n}", "Type": "Episode", "SeriesName": f"Show {series}",
            "SeriesId": jid(1000 + series), "SeriesPrimaryImageTag": "tag", "ParentIndexNumber": 1, "IndexNumber": n,
            "ImageTags": {"Primary": "t"}, "UserData": data, "DateCreated": created}


def film(n, created, collection=None, played=False, last=None):
    data = {"PlaybackPositionTicks": 0, "Played": played}
    if last:
        data["LastPlayedDate"] = last
    ids = {"Tmdb": str(n)}
    if collection:
        ids["TmdbCollection"] = collection
    return {"Id": jid(n), "Name": f"Film {n}", "Type": "Movie", "ImageTags": {"Primary": "t"}, "UserData": data,
            "DateCreated": created, "ProviderIds": ids}


class Jelly(FakeJellyfin):
    """The fake with a member's Up next, watched episodes and films (synthetic)."""

    def __init__(self, clock):
        super().__init__(clock)
        self.next_up, self.watched, self.unwatched_films, self.watched_films = [], [], [], []

    def handle(self, method, path, query):
        query = dict(query or {})
        if path == "/Shows/NextUp":
            self.requests.append((method, path, query))
            return self._json({"Items": self.next_up[:int(query["limit"])]})
        if path == "/Items" and "isPlayed" in query:
            self.requests.append((method, path, query))
            played = query["isPlayed"] == "true"
            if query["includeItemTypes"] == "Episode":
                rows = self.watched if played else []
            else:
                rows = self.watched_films if played else self.unwatched_films
            return self._json({"Items": rows[:int(query["limit"])]})
        return super().handle(method, path, query)


class JellyfinForYou(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = Jelly(self.clock)
        self.adapter = JellyfinAdapter(FakeTransport(self.fake), clock=self.clock)
        self.a = make_principal("member-a", ("avrana-users", "avrana-videos"))

    def test_the_next_episode_is_new_only_when_it_arrived_lately_and_is_not_started(self):
        self.fake.next_up = [episode(1, 1, stamp(2)), episode(2, 2, stamp(90)), episode(3, 3, stamp(1), position=10 ** 8),
                             episode(4, 4, stamp(0, 3))]
        got = self.adapter.for_you_items(self.a)
        self.assertEqual(["Episode 4", "Episode 1"], [i.title for i in got.items])      # newest arrival first
        self.assertEqual("poster", got.items[0].artwork.shape)                          # the show's poster
        self.assertEqual(stamp(0, 3)[:19] + "Z", got.items[0].active)
        self.assertTrue(all(i.position_seconds is None for i in got.items))

    def test_a_new_film_of_a_watched_collection_and_no_other(self):
        self.fake.unwatched_films = [film(10, stamp(3), "777"), film(11, stamp(3), "888"), film(12, stamp(60), "777"),
                                     film(13, stamp(1))]
        self.fake.watched_films = [film(20, stamp(400), "777", played=True)]
        got = self.adapter.for_you_items(self.a)
        self.assertEqual(["Film 10"], [i.title for i in got.items])

    def test_no_collection_among_new_films_asks_nothing_more(self):
        self.fake.unwatched_films = [film(13, stamp(1))]
        self.assertEqual(SectionState.EMPTY, self.adapter.for_you_items(self.a).state)
        played = [q for _m, p, q in self.fake.requests if p == "/Items" and q.get("isPlayed") == "true"]
        self.assertEqual([], played)

    def test_up_next_carries_its_series_last_watch_and_continue_its_own(self):
        self.fake.next_up = [episode(1, 1, stamp(200)), episode(2, 2, stamp(200))]
        self.fake.watched = [episode(50, 2, stamp(300), played=True, last=stamp(1)),
                             episode(51, 1, stamp(300), played=True, last=stamp(9)),
                             episode(52, 2, stamp(300), played=True, last=stamp(20))]
        got = {i.title: i.active for i in self.adapter.next_up_items(self.a).items}
        self.assertEqual({"Episode 1": stamp(9)[:19] + "Z", "Episode 2": stamp(1)[:19] + "Z"}, got)
        query = next(q for _m, p, q in self.fake.requests if p == "/Items" and q.get("isPlayed") == "true")
        self.assertEqual(("DatePlayed", "Descending", "Episode"),
                         (query["sortBy"], query["sortOrder"], query["includeItemTypes"]))

    def test_another_members_watch_history_is_refused(self):
        bad = episode(50, 2, stamp(300), played=True, last=stamp(1))
        bad["UserData"]["UserId"] = "b" * 32
        self.fake.next_up, self.fake.watched = [episode(2, 2, stamp(200))], [bad]
        self.assertEqual(SectionState.UNAVAILABLE, self.adapter.next_up_items(self.a).state)


def book(n, series, created=None, read=None, page=None, pages=40):
    raw = {"id": f"BOOK{n:08d}", "seriesId": f"SERIES{series:04d}", "seriesTitle": f"Series {series}",
           "name": f"Book {n}", "metadata": {"title": f"Book {n}", "number": str(n)},
           "media": {"status": "READY", "pagesCount": pages}}
    if created:
        raw["created"] = created
    if read or page is not None:
        raw["readProgress"] = {"page": page or pages, "completed": page is None, "readDate": read}
    return raw


class OwnKomga:
    def __init__(self):
        self.reading, self.ondeck, self.read, self.requests = [], [], [], []

    def handle(self, method, path, query):
        self.requests.append((method, path, dict(query or {})))
        size = int(query.get("size", "20"))
        rows = {"IN_PROGRESS": self.reading, "READ": self.read}.get(query.get("read_status")) \
            if path == "/api/v1/books" else self.ondeck if path == "/api/v1/books/ondeck" else None
        if rows is None:
            return 400, b"{}", "application/json"
        return 200, json.dumps({"content": rows[:size]}).encode("utf-8"), "application/json"


class KomgaForYou(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.mine = OwnKomga()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "keys")
        write_keys(path, {"alice@example.com": "0123456789abcdef0123456789abcdef"})
        self.adapter = KomgaAdapter(FakeTransport(FakeKomga(self.clock)), clock=self.clock,
                                    owner_confirms_no_member_restrictions=True,
                                    member_keys=MemberKeyStore(path, initial=read_keys(path)),
                                    member_transport=lambda key: FakeTransport(self.mine))
        self.alice = principal_from_headers({"X-authentik-username": "alice", "X-authentik-email": "alice@example.com",
                                             "X-authentik-groups": "avrana-users|avrana-comics"})
        self.bob = principal_from_headers({"X-authentik-username": "bob", "X-authentik-email": "bob@example.com",
                                           "X-authentik-groups": "avrana-users|avrana-comics"})

    def test_an_on_deck_issue_that_arrived_lately_is_new_for_you(self):
        self.mine.ondeck = [book(1, 1, created=stamp(40)), book(2, 2, created=stamp(0, 2)), book(3, 3, created=stamp(5))]
        got = self.adapter.for_you_items(self.alice)
        self.assertEqual(["Book 2", "Book 3"], [i.title for i in got.items])
        self.assertEqual(("next", stamp(0, 2)[:19] + "Z"), (got.items[0].shelf, got.items[0].active))
        self.assertEqual({"/api/v1/books/ondeck"}, {p for _m, p, _q in self.mine.requests})

    def test_without_a_key_it_is_not_offered_and_nothing_is_asked(self):
        got = self.adapter.for_you_items(self.bob)
        self.assertEqual((SectionState.EMPTY, "not_offered"), (got.state, got.reason))
        self.assertEqual([], self.mine.requests)
        plain = KomgaAdapter(FakeTransport(FakeKomga(self.clock)), clock=self.clock,
                             owner_confirms_no_member_restrictions=True)
        self.assertNotIn("for_you", plain.extra_sections)
        self.assertIn("for_you", self.adapter.extra_sections)

    def test_continue_books_carry_their_read_date_and_on_deck_its_series(self):
        self.mine.reading = [book(1, 1, read=stamp(3), page=10)]
        self.mine.ondeck = [book(5, 2), book(6, 3)]
        self.mine.read = [book(4, 2, read=stamp(1)), book(3, 2, read=stamp(8))]
        got = {i.title: i.active for i in self.adapter.continue_items(self.alice).items}
        self.assertEqual({"Book 1": stamp(3)[:19] + "Z", "Book 5": stamp(1)[:19] + "Z", "Book 6": None},
                         got)

    def test_a_failing_read_list_costs_only_the_order(self):
        self.mine.ondeck = [book(5, 2)]
        self.mine.read = None                                              # the fake answers 400
        got = self.adapter.continue_items(self.alice)
        self.assertEqual((SectionState.OK, None), (got.state, got.items[0].active))


if __name__ == "__main__":
    unittest.main()
