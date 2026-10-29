"""Komga's `week` section for Home's "This week in comics" card (owner request 2026-10-29). Offline, synthetic data.
Every comic issue Komga first scanned in the last seven days, newest first, NOT one per series; novels left out."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import json
import unittest
from datetime import datetime, timedelta, timezone

from avrana_home.adapters.komga import KomgaAdapter
from avrana_home.contract import Kind, SectionState
from avrana_home.resilience import FakeClock
from tests.fake_jellyfin import FakeTransport
from tests.helpers import make_principal


def book(n, series, days_ago, epub=False):
    created = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    media = {"status": "READY", "mediaProfile": "EPUB" if epub else "DIVINA"}
    return {"id": f"WEEK{n:08d}", "seriesId": f"SER{series:05d}", "seriesTitle": f"Series {series}",
            "name": f"Book {n}", "created": created, "metadata": {"title": f"Book {n}", "number": str(n)},
            "media": media}


class Komga:
    def __init__(self, books):
        self.books, self.requests = books, []

    def handle(self, method, path, query):
        self.requests.append((path, dict(query or {})))
        size = int(query.get("size", "20"))
        return 200, json.dumps({"content": self.books[:size]}).encode(), "application/json"


class Week(unittest.TestCase):
    def test_every_comic_of_the_week_newest_first_not_one_per_series(self):
        fake = Komga([book(1, 1, 0.5), book(2, 1, 1), book(3, 2, 2, epub=True), book(4, 3, 6.5), book(5, 4, 8)])
        clock = FakeClock()
        a = KomgaAdapter(FakeTransport(fake), clock=clock, owner_confirms_no_member_restrictions=True)
        got = a.week_items(make_principal("member-a", ("avrana-comics",)))
        self.assertEqual(["Book 1", "Book 2", "Book 4"], [i.title for i in got.items])
        self.assertTrue(all(i.kind is Kind.COMIC for i in got.items))
        self.assertEqual(("created,desc", "100"), (fake.requests[0][1]["sort"], fake.requests[0][1]["size"]))

    def test_nothing_this_week_is_empty(self):
        a = KomgaAdapter(FakeTransport(Komga([book(5, 4, 9)])), clock=FakeClock(),
                         owner_confirms_no_member_restrictions=True)
        self.assertEqual(SectionState.EMPTY, a.week_items(make_principal("member-a", ("avrana-comics",))).state)


if __name__ == "__main__":
    unittest.main()
