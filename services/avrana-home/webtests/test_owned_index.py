"""Tier A/B: the catalogue-id index (requests/owned.py), its builder (tools/build_catalogue_index.py) and "Already in"
on the book request page. SYNTHETIC data only."""
import importlib.util
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from avrana_home.requests.owned import OwnedIndex, isbn13, title_key
from avrana_home.requests.shelfarr import ShelfarrRequests
from .support import GROUPS, USER, PeerOverride, StubAdapter, make_settings, require_framework
from .test_web_book_requests import FakeShelfarr

TOOL = Path(__file__).resolve().parents[1] / "tools" / "build_catalogue_index.py"
spec = importlib.util.spec_from_file_location("build_catalogue_index", TOOL)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

BOTH = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-books|avrana-audiobooks")]
LISTENER = [(USER, "member-l"), (GROUPS, "avrana-users|avrana-audiobooks")]


class Keys(unittest.TestCase):
    def test_isbn(self):
        self.assertEqual("9780441013593", isbn13("0-441-01359-7"))
        self.assertEqual("9780441013593", isbn13("978-0-441-01359-3"))
        self.assertIsNone(isbn13("9780441013594"))
        self.assertIsNone(isbn13("0441013598"))
        self.assertIsNone(isbn13(None))

    def test_title_key(self):
        self.assertEqual("t:dune|herbert", title_key("Dune: Deluxe Edition", "Frank Herbert"))
        self.assertEqual("t:hobbit|tolkien", title_key("The Hobbit (Illustrated)", "J. R. R. Tolkien, Christopher Tolkien"))
        self.assertEqual("t:les miserables|hugo", title_key("Les Misérables", "Victor Hugo"))
        self.assertIsNone(title_key("A", "Someone"))
        self.assertIsNone(title_key("Title", ""))

    def test_builder_and_home_agree(self):
        samples = [("Dune: Deluxe", "Frank Herbert"), ("The Way of Kings", "Brandon Sanderson & X"),
                   ("Ça", "Stephen King"), ("A Memory Called Empire (Teixcalaan, #1)", "Arkady Martine")]
        for t, a in samples:
            self.assertEqual(builder.title_key(t, a), title_key(t, a))
        for n in ("0-441-01359-7", "9780441013593", "123", "080442957X"):
            self.assertEqual(builder.isbn13(n), isbn13(n))


def write_index(d, **tables):
    path = Path(d) / "ids.json"
    built = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    path.write_text(json.dumps(dict({"version": 1, "built": built}, **tables)), encoding="utf-8")
    return path


class Loader(unittest.TestCase):
    def test_validates_and_reloads(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_index(d, ebook={"hardcover:1": "45", "hardcover:2": "../x", "evil": "1"},
                               audiobook_likely={"t:dune|herbert": "li_abcdef12"},
                               comic={"comicvine:9": "0MEC2AAWWZCMN"})
            now = [0.0]
            idx = OwnedIndex(path, clock=lambda: now[0])
            self.assertEqual("45", idx.exact("ebook", ["isbn:9780441013593", "hardcover:1"]))
            self.assertIsNone(idx.exact("ebook", ["hardcover:2"]))
            self.assertEqual("li_abcdef12", idx.likely("audiobook", "t:dune|herbert"))
            self.assertEqual("0MEC2AAWWZCMN", idx.exact("comic", ["comicvine:9"]))
            path.write_text("{not json", encoding="utf-8")
            now[0] += 61
            self.assertIsNone(idx.exact("ebook", ["hardcover:1"]))       # malformed: no claims at all
            path.unlink()
            now[0] += 61
            self.assertIsNone(idx.exact("ebook", ["hardcover:1"]))

    def test_wrong_version_and_no_path(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ids.json"
            path.write_text(json.dumps({"version": 2, "ebook": {"hardcover:1": "45"}}), encoding="utf-8")
            self.assertIsNone(OwnedIndex(path).exact("ebook", ["hardcover:1"]))
        self.assertIsNone(OwnedIndex(None).exact("ebook", ["hardcover:1"]))


class Builder(unittest.TestCase):
    def test_build_from_synthetic_schemas(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cal = sqlite3.connect(d / "metadata.db")
            cal.executescript("""
                CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT);
                CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY, book INTEGER, author INTEGER);
                CREATE TABLE identifiers (id INTEGER PRIMARY KEY, book INTEGER, type TEXT, val TEXT);
                INSERT INTO books VALUES (45, 'Synthetic Dune: Deluxe');
                INSERT INTO authors VALUES (1, 'Frank Herbert');
                INSERT INTO books_authors_link VALUES (1, 45, 1);
                INSERT INTO identifiers VALUES (1, 45, 'hardcover-id', '312460'), (2, 45, 'isbn', '0-441-01359-7'),
                                               (3, 45, 'hardcover-slug', 'dune'), (4, 45, 'isbn', 'bogus');
            """)
            cal.commit(); cal.close()
            sh = sqlite3.connect(d / "shelfarr.sqlite3")
            sh.executescript("""
                CREATE TABLE library_items (audiobookshelf_id TEXT, title TEXT, author TEXT, isbn TEXT, asin TEXT,
                                            missing BOOLEAN, library_platform TEXT);
                INSERT INTO library_items VALUES ('11111111-2222-3333-4444-555555555555', 'Synthetic Dune', 'Frank Herbert',
                                                  NULL, 'B00B7NPRY8', 0, 'audiobookshelf'),
                                                 ('li_gone0001', 'Gone', 'X', NULL, 'B000000001', 1, 'audiobookshelf');
            """)
            sh.commit(); sh.close()
            km = sqlite3.connect(d / "komga.sqlite")
            km.executescript("""
                CREATE TABLE SERIES (ID TEXT, URL TEXT, DELETED_DATE TEXT);
                INSERT INTO SERIES VALUES ('0MEC2AAWWZCMN', 'file:/avrana_media/avrana_media/comics/DC%20Comics/Batman%20(2016)', NULL),
                                          ('0MEC2AAWWZCMX', 'file:/avrana_media/avrana_media/comics/Image/Old%20(1999)', '2026');
            """)
            km.commit(); km.close()
            om = sqlite3.connect(d / "omnibus.db")
            om.executescript("""
                CREATE TABLE Series (cvId INTEGER, folderPath TEXT);
                INSERT INTO Series VALUES (91750, '/mylar-library/DC Comics/Batman (2016)'), (1, '/data/Image/Old (1999)'),
                                          (NULL, '/data/Indie/Unmatched (2020)');
            """)
            om.commit(); om.close()
            index, report = builder.build({"calibre_db": d / "metadata.db", "shelfarr_db": d / "shelfarr.sqlite3",
                                           "omnibus_db": d / "omnibus.db", "komga_db": d / "komga.sqlite"})
        self.assertEqual({"hardcover:312460": "45", "isbn:9780441013593": "45"}, index["ebook"])
        self.assertEqual({"t:synthetic dune|herbert": "45"}, index["ebook_likely"])
        self.assertEqual({"asin:B00B7NPRY8": "11111111-2222-3333-4444-555555555555"}, index["audiobook"])
        self.assertEqual({"comicvine:91750": "0MEC2AAWWZCMN"}, index["comic"])
        text = json.dumps(index)
        self.assertNotIn("Synthetic Dune: Deluxe", text)      # titles only as folded keys
        self.assertNotIn("member", text)

    def test_missing_source_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "nope.db"
            index, report = builder.build({k: missing for k in builder.DEFAULTS})
        self.assertTrue(all(v.startswith("skipped") for v in report.values()))
        self.assertEqual({}, index["ebook"])


class FakeAbs(StubAdapter):
    """Audiobookshelf-shaped: `visible` maps username -> item ids that member can open."""
    from avrana_home.contract import Service as _S
    service = _S.AUDIOBOOKSHELF

    def __init__(self, visible):
        super().__init__({u: [] for u in visible})
        self.visible = visible
        self.item_calls = 0

    def _item(self, user, item_id):
        from avrana_home.contract import Kind, MediaItem, SectionResult, build_handoff_url
        self.item_calls += 1
        if item_id not in self.visible.get(user.upstream_id, ()):
            from avrana_home.resilience import ItemGone
            raise ItemGone(404)
        return SectionResult.of(self.service, "item", (MediaItem(
            id=f"audiobookshelf:{item_id}", service=self.service, kind=Kind.AUDIOBOOK, title="Synthetic Dune",
            handoff_url=build_handoff_url(self.service, item_id)),))


class RequestPage(unittest.TestCase):
    def client(self, index_path, adapters=None):
        from fastapi.testclient import TestClient
        from avrana_home.app.main import create_app
        self.shelfarr = FakeShelfarr()
        self.shelfarr.search_body = {"results": [
            {"work_id": "openlibrary:OL1W", "title": "Synthetic Dune", "author": "Frank Herbert",
             "has_ebook": True, "has_audiobook": True,
             "sources": [{"work_id": "hardcover:312460"}], "editions": [{"isbn_13": "9780441013593"}]},
            {"work_id": "hardcover:999", "title": "Other Book", "author": "A. Writer",
             "has_ebook": True, "has_audiobook": True}]}
        settings = make_settings(home_sections=True, book_requests=True, shelfarr_base_url="http://127.0.0.1:1",
                                 library_ids_file=index_path)
        app = create_app(settings, adapters=adapters or [StubAdapter({})],
                         book_requests=ShelfarrRequests(self.shelfarr))
        c = TestClient(PeerOverride(app, ("203.0.113.7", 50000)), base_url="http://portal.test",
                       follow_redirects=False, raise_server_exceptions=False)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def test_owned_ebook_replaces_its_button_and_likely_audiobook_is_a_hint(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_index(d, ebook={"hardcover:312460": "45"},
                               audiobook_likely={"t:synthetic dune|herbert": "li_abcdef12"})
            r = self.client(path).get("/request/books", params={"q": "dune"}, headers=BOTH)
        self.assertEqual(200, r.status_code)
        first = r.text.split("<li>")[1]
        self.assertIn("Already in Books.", first)
        self.assertIn('href="https://books.avrana.net/book/45"', first)
        self.assertNotIn("Ask for the ebook", first)
        self.assertIn("Ask for the audiobook", first)              # likely only: the button stays
        self.assertIn("Audiobooks may already have this.", first)
        self.assertIn('href="/search?q=Synthetic+Dune"', first)
        second = r.text.split("<li>")[2]
        self.assertNotIn("Already in", second)
        self.assertIn("Ask for the ebook", second)

    def test_a_library_the_member_does_not_hold_is_never_mentioned(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_index(d, ebook={"hardcover:312460": "45"})
            r = self.client(path).get("/request/books", params={"q": "dune"}, headers=LISTENER)
        self.assertNotIn("Books.", r.text.replace("Audiobooks", ""))
        self.assertNotIn("books.avrana.net", r.text)

    def test_owned_audiobook_only_after_the_members_own_lookup(self):
        abs_ = FakeAbs({"member-a": {"11111111-2222-3333-4444-555555555555"}, "member-l": set()})
        with tempfile.TemporaryDirectory() as d:
            path = write_index(d, audiobook={"isbn:9780441013593": "11111111-2222-3333-4444-555555555555"})
            c = self.client(path, adapters=[StubAdapter({}), abs_])
            a = c.get("/request/books", params={"q": "dune"}, headers=BOTH)
            l = c.get("/request/books", params={"q": "dune"}, headers=LISTENER)
        first = a.text.split("<li>")[1]
        self.assertIn("Already in Audiobooks.", first)
        self.assertIn('href="/title/audiobookshelf/11111111-2222-3333-4444-555555555555"', first)
        self.assertNotIn("Ask for the audiobook", first)
        self.assertNotIn("Already in", l.text)                    # the same file, not visible to this member
        self.assertIn("Ask for the audiobook", l.text.split("<li>")[1])
        self.assertEqual(2, abs_.item_calls)

    def test_no_index_no_claims(self):
        r = self.client(None).get("/request/books", params={"q": "dune"}, headers=BOTH)
        self.assertNotIn("Already in", r.text)
        self.assertNotIn("may already have", r.text)


if __name__ == "__main__":
    unittest.main()
