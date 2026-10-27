"""tools/check_member_links.py (AVR-375): the owner's one-command check that members' library accounts link.
The real Jellyfin adapter's mapping hook over the synthetic fake (no sockets), plus the tool's refusals."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path

from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.contract import Service
from avrana_home.resilience import FakeClock, UpstreamUnreachable
from tests.fake_jellyfin import FakeJellyfin, FakeTransport

HOME = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_member_links", HOME / "tools" / "check_member_links.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def jellyfin_mapper(fake=None):
    fake = fake or FakeJellyfin(FakeClock())
    return JellyfinAdapter(FakeTransport(fake), clock=fake.clock)._resolve_user, fake


def verdicts(rows):
    return {(r["username"], r["service"]): r["verdict"] for r in rows}


class Verdicts(unittest.TestCase):
    def test_exact_case_disabled_unmapped_and_shared(self):
        mapper, _ = jellyfin_mapper()
        rows = tool.check(["member-a", "Member-A", "member-c", "nobody"],
                          {Service.JELLYFIN: mapper, Service.KOMGA: None})
        self.assertEqual(verdicts(rows), {
            ("member-a", "jellyfin"): "linked", ("member-a", "komga"): "shared",
            ("Member-A", "jellyfin"): "case_or_unicode_mismatch", ("Member-A", "komga"): "shared",
            ("member-c", "jellyfin"): "disabled", ("member-c", "komga"): "shared",
            ("nobody", "jellyfin"): "unmapped", ("nobody", "komga"): "shared"})

    def test_two_accounts_with_the_same_name_are_ambiguous(self):
        fake = FakeJellyfin(FakeClock())
        twin = dict(fake.users[0], Id="dddddddd-dddd-4ddd-8ddd-dddddddddddd")
        fake.users.append(twin)
        mapper, _ = jellyfin_mapper(fake)
        self.assertEqual(verdicts(tool.check(["member-a"], {Service.JELLYFIN: mapper})),
                         {("member-a", "jellyfin"): "ambiguous"})

    def test_an_unreachable_library_is_reported_without_detail(self):
        def down(principal):
            raise UpstreamUnreachable("http://10.0.0.9:8096 secret-ish detail")
        rows = tool.check(["member-a"], {Service.JELLYFIN: down})
        self.assertEqual(rows[0]["verdict"], "unreachable")
        self.assertNotIn("10.0.0.9", json.dumps(rows))

    def test_an_invalid_username_is_one_row_and_reaches_no_library(self):
        calls = []
        rows = tool.check([" padded"], {Service.JELLYFIN: lambda p: calls.append(p)})
        self.assertEqual([r["verdict"] for r in rows], ["invalid_username"])
        self.assertEqual(calls, [])

    def test_output_names_no_upstream_id_or_other_account(self):
        mapper, fake = jellyfin_mapper()
        out = tool.render(tool.check(["member-a", "Member-A"], {Service.JELLYFIN: mapper}))
        for user in fake.users:
            self.assertNotIn(user["Id"].replace("-", "").lower(), out.lower())
        self.assertNotIn("member-b", out)
        self.assertNotIn("synthetic-admin", out)

    def test_only_the_user_list_is_read(self):
        mapper, fake = jellyfin_mapper()
        tool.check(["member-a", "nobody"], {Service.JELLYFIN: mapper})
        self.assertEqual({(m, p) for m, p, _ in fake.requests}, {("GET", "/Users")})


class Main(unittest.TestCase):
    def run_main(self, argv, environ):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tool.main(argv, environ)
        return code, out.getvalue(), err.getvalue()

    def test_no_usernames_is_refused(self):
        code, _, err = self.run_main([], {})
        self.assertEqual(code, 2)
        self.assertIn("at least one username", err)

    def test_sections_off_is_refused(self):
        code, _, err = self.run_main(["member-a"], {"HOME_SECTIONS": "off"})
        self.assertEqual(code, 2)
        self.assertIn("sections are off", err)

    def test_exit_codes_and_json(self):
        mapper, _ = jellyfin_mapper()
        real = tool.build_mappers
        tool.build_mappers = lambda settings: {Service.JELLYFIN: mapper}
        try:
            env = {"HOME_SECTIONS": "on", "HOME_UPSTREAM_MODE": "mock", "JELLYFIN_BASE_URL": "http://127.0.0.1:9"}
            self.assertEqual(self.run_main(["member-a"], env)[0], 0)
            code, out, _ = self.run_main(["--json", "member-a", "nobody"], env)
            self.assertEqual(code, 1)
            self.assertEqual([r["verdict"] for r in json.loads(out)["members"]], ["linked", "unmapped"])
        finally:
            tool.build_mappers = real

    def test_file_input_skips_comments_blanks_and_duplicates(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write("# members\nmember-a\n\nmember-b\nmember-a\n")
        try:
            args = tool.argparse.Namespace(usernames=["member-b"], file=fh.name)
            self.assertEqual(tool.read_usernames(args), ["member-b", "member-a"])
        finally:
            _os.unlink(fh.name)

    def test_a_file_saved_with_a_byte_order_mark_reads_its_first_name_whole(self):
        import tempfile
        with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as fh:
            fh.write(b"\xef\xbb\xbfmember-a\r\nmember-b\r\n")     # PowerShell 5.1 Out-File style
        try:
            args = tool.argparse.Namespace(usernames=[], file=fh.name)
            self.assertEqual(tool.read_usernames(args), ["member-a", "member-b"])
        finally:
            _os.unlink(fh.name)

    def test_an_invalid_username_with_invisible_characters_is_shown_escaped(self):
        rows = tool.check(["\u200bmember-a", "bad\x1b[2Jname"], {Service.JELLYFIN: lambda p: None})
        self.assertEqual([r["username"] for r in rows], [r"\u200bmember-a", r"bad\x1b[2Jname"])
        self.assertTrue(all(r["fix"].isprintable() for r in rows))


if __name__ == "__main__":
    unittest.main()
