"""AVR-365: the operator notice. The OliveTin action writes an ID and a time; Home shows fixed words for it.

What these pin:
  * no HOME_NOTICE_FILE, an absent file (cleared), an unknown ID, bad JSON or an oversized file: no banner, and every
    page is exactly as without the feature;
  * a notice shows on shell pages only, with the words from notice.NOTICES and nothing from the file;
  * a library notice shows only to members whose own groups open that library (the places-bar rule);
  * set, change and clear are picked up without a restart (within RECHECK_SECONDS);
  * Home has no route that writes the notice: every method but GET/HEAD is 501 and the notice paths are the 404.
"""
import json
import tempfile
import unittest
from pathlib import Path

from avrana_home.app import notice
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

NAME = "X-authentik-name"
VIDEO = [(USER, "member-a"), (NAME, "Alice Aardvark"), (GROUPS, "avrana-users|avrana-videos")]
LISTEN = [(USER, "member-b"), (NAME, "Bertram Bobcat"), (GROUPS, "avrana-users|avrana-audiobooks")]
FILM = "aaaa0000000000000000000000000001"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "current.json"

    def write(self, notice_id, set_at="2026-10-27T09:00:00Z"):
        self.path.write_text(json.dumps({"id": notice_id, "set": set_at}), encoding="utf-8")

    def client(self, notice_file=True):
        settings = make_settings(home_sections=True, notice_file=self.path if notice_file else None)
        c = make_client(settings, adapters=[StubAdapter({"member-a": [(FILM, "Synthetic Film", 0.5)]})])
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        self.clock = Clock()
        c.fastapi_app.state.notices._clock = self.clock
        return c


class Pages(Base):
    def test_no_setting_no_file_and_cleared_render_the_same_page(self):
        plain = self.client(notice_file=False).get("/", headers=VIDEO).text
        self.assertNotIn("k-notice", plain.split("<style>")[0] + plain.split("</style>")[1])
        self.assertEqual(plain, self.client().get("/", headers=VIDEO).text)         # file absent = cleared

    def test_a_notice_for_everyone_shows_its_fixed_words_on_shell_pages(self):
        self.write("maintenance")
        c = self.client()
        for path in ("/", "/help", "/me", "/library", "/search"):
            body = c.get(path, headers=VIDEO).text
            with self.subTest(path=path):
                self.assertIn('<aside class="k-notice" aria-label="Notice from Avrana">', body)
                self.assertIn(notice.NOTICES["maintenance"].heading, body)
                self.assertIn(notice.NOTICES["maintenance"].body, body)
                self.assertIn('<details class="k-warn" open>', body)

    def test_nothing_from_the_file_but_the_id_reaches_the_page(self):
        self.path.write_text(json.dumps({"id": "slow", "set": "<script>x</script>", "text": "jellyfin-xq7 is down"}),
                             encoding="utf-8")
        body = self.client().get("/", headers=VIDEO).text
        self.assertIn(notice.NOTICES["slow"].heading, body)
        self.assertNotIn("<script>x", body)
        self.assertNotIn("jellyfin-xq7", body)

    def test_a_library_notice_shows_only_to_members_who_open_that_library(self):
        self.write("video-unavailable")
        c = self.client()
        heading = notice.NOTICES["video-unavailable"].heading
        self.assertIn(heading, c.get("/", headers=VIDEO).text)
        self.assertNotIn(heading, c.get("/", headers=LISTEN).text)
        self.write("audiobooks-unavailable", "2026-10-27T10:00:00Z")
        self.clock.now += notice.RECHECK_SECONDS
        heading = notice.NOTICES["audiobooks-unavailable"].heading
        self.assertNotIn(heading, c.get("/", headers=VIDEO).text)
        self.assertIn(heading, c.get("/me", headers=LISTEN).text)

    def test_no_principal_and_non_shell_pages_never_show_it(self):
        self.write("maintenance")
        c = self.client()
        heading = notice.NOTICES["maintenance"].heading
        self.assertNotIn(heading, c.get("/").text)                                  # no identity: the portal page
        self.assertNotIn(heading, c.get("/nope", headers=VIDEO).text)                # 404 is not a shell page

    def test_set_change_and_clear_are_picked_up_without_a_restart(self):
        c = self.client()
        self.assertNotIn("k-notice\"", c.get("/", headers=VIDEO).text)
        self.write("slow")
        self.assertNotIn(notice.NOTICES["slow"].heading, c.get("/", headers=VIDEO).text)    # within the recheck window
        self.clock.now += notice.RECHECK_SECONDS
        self.assertIn(notice.NOTICES["slow"].heading, c.get("/", headers=VIDEO).text)
        self.write("maintenance", "2026-10-27T11:00:00Z")
        self.clock.now += notice.RECHECK_SECONDS
        body = c.get("/", headers=VIDEO).text
        self.assertIn(notice.NOTICES["maintenance"].heading, body)
        self.assertNotIn(notice.NOTICES["slow"].heading, body)
        self.path.unlink()
        self.clock.now += notice.RECHECK_SECONDS
        self.assertNotIn(notice.NOTICES["maintenance"].heading, c.get("/", headers=VIDEO).text)

    def test_home_cannot_set_a_notice(self):
        c = self.client()
        nf = c.get("/nope", headers=VIDEO).text
        for path in ("/notice", "/notice/set", "/notice/maintenance", "/notice.json"):
            r = c.get(path, headers=VIDEO)
            self.assertEqual((404, nf), (r.status_code, r.text), path)
            for method in ("POST", "PUT", "DELETE", "PATCH"):
                self.assertEqual(501, c.request(method, path, headers=VIDEO).status_code, (method, path))
        self.assertFalse(self.path.exists())


class Board(Base):
    def board(self):
        self.clock = Clock()
        return notice.NoticeBoard(self.path, clock=self.clock)

    def test_bad_files_are_no_notice(self):
        for raw in (b"", b"not json", b"[]", b'{"id": 5, "set": "x"}', b'{"id": "slow"}',
                    b'{"id": "unknown", "set": "x"}', b'{"id": "slow", "set": "' + b"x" * 80 + b'"}',
                    b"\xff\xfe", b'{"id": "slow", "set": "x", "pad": "' + b"y" * notice.MAX_BYTES + b'"}'):
            self.path.write_bytes(raw)
            with self.subTest(raw=raw[:40]):
                self.assertIsNone(self.board().current())

    def test_valid_file_and_revision_changes_when_set_again(self):
        self.write("slow", "a")
        first = self.board().current()
        self.assertEqual("slow", first.notice.id)
        self.write("slow", "b")
        self.assertNotEqual(first.revision, self.board().current().revision)

    def test_unset_path_reads_nothing(self):
        self.assertIsNone(notice.NoticeBoard(None).current())

    def test_visible_notice_scope(self):
        self.write("comics-unavailable")
        active = self.board().current()
        self.assertIsNone(notice.visible_notice(active, {"jellyfin": "/watch"}))
        self.assertIs(active, notice.visible_notice(active, {"komga": "/comics"}))
        self.assertIsNone(notice.visible_notice(None, {"komga": "/comics"}))

    def test_every_notice_has_member_words_and_a_known_library(self):
        from avrana_home.app.viewmodel import SERVICE_LABEL
        for n in notice.NOTICES.values():
            with self.subTest(id=n.id):
                self.assertTrue(n.heading and n.body)
                self.assertTrue(n.service is None or n.service in SERVICE_LABEL)
                for word in ("Jellyfin", "Audiobookshelf", "Komga", "Calibre", "Seerr", "container", "docker"):
                    self.assertNotIn(word.lower(), (n.heading + n.body).lower())


if __name__ == "__main__":
    unittest.main()
