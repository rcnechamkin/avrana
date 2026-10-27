"""tools/check_member_links.py end to end (AVR-375): Home's real settings, real transports and the dev mocks of
Jellyfin and Audiobookshelf on loopback ports. Synthetic accounts only."""
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path

from dev.mock_audiobookshelf import MockAudiobookshelf
from dev.mock_jellyfin import MockJellyfin

from .support import require_framework

require_framework()

HOME = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_member_links_e2e", HOME / "tools" / "check_member_links.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.jf = MockJellyfin().start()
        self.addCleanup(self.jf.stop)
        self.ab = MockAudiobookshelf().start()
        self.addCleanup(self.ab.stop)
        self.env = {"HOME_SECTIONS": "on", "HOME_UPSTREAM_MODE": "mock",
                    "JELLYFIN_BASE_URL": self.jf.url, "AUDIOBOOKSHELF_BASE_URL": self.ab.url}

    def run_tool(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = tool.main(["--json", *argv], self.env)
        return code, {(r["username"], r["service"]): r["verdict"] for r in json.loads(out.getvalue())["members"]}

    def test_synthetic_members_link_in_both_libraries(self):
        code, got = self.run_tool("member-a", "member-b")
        self.assertEqual(code, 0)
        self.assertEqual(got, {("member-a", "jellyfin"): "linked", ("member-a", "audiobookshelf"): "linked",
                               ("member-b", "jellyfin"): "linked", ("member-b", "audiobookshelf"): "linked"})

    def test_a_case_variant_and_a_stranger_get_fix_rows(self):
        code, got = self.run_tool("Member-A", "nobody")
        self.assertEqual(code, 1)
        self.assertEqual(got[("Member-A", "jellyfin")], "case_or_unicode_mismatch")
        self.assertEqual(got[("Member-A", "audiobookshelf")], "case_or_unicode_mismatch")
        self.assertEqual(got[("nobody", "jellyfin")], "unmapped")
        self.assertEqual(got[("nobody", "audiobookshelf")], "unmapped")

    def test_a_library_that_is_down_is_unreachable_not_a_crash(self):
        self.jf.stop()
        code, got = self.run_tool("member-a")
        self.assertEqual(code, 1)
        self.assertEqual(got[("member-a", "jellyfin")], "unreachable")
        self.assertEqual(got[("member-a", "audiobookshelf")], "linked")


if __name__ == "__main__":
    unittest.main()
