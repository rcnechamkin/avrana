"""RC1 finding S1: the Home deploy stops before build when identity bindings are on but the file is missing.

Runs the guard lines of scripts/deploy-home-beta.sh's remote half with bash in a temporary folder. No ssh, no
docker. Skipped where bash is missing.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy-home-beta.sh"


def guard():
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^if grep -qE '\^\[\[:space:\]\]\*- HOME_IDENTITY_BINDINGS_FILE=.*?^fi$", text)
    assert match, "guard not found"
    return text, match


@unittest.skipIf(shutil.which("bash") is None, "bash not available")
class BindingsGuard(unittest.TestCase):
    def run_guard(self, compose_line, file_text):
        with tempfile.TemporaryDirectory() as live:
            Path(live, "state").mkdir()
            Path(live, "docker-compose.beta-live.yml").write_text(f"    environment:\n{compose_line}\n",
                                                                   encoding="utf-8", newline="\n")
            if file_text is not None:
                Path(live, "state", "identity_bindings.json").write_text(file_text, encoding="utf-8")
            body = f'set -euo pipefail\nLIVE="{Path(live).as_posix()}"\nCOMPOSE=docker-compose.beta-live.yml\n'
            body += guard()[1].group(0) + "\necho passed\n"
            return subprocess.run(["bash", "-c", body], capture_output=True, text=True, timeout=30)

    def test_on_without_a_file_stops(self):
        for text in (None, ""):
            done = self.run_guard("      - HOME_IDENTITY_BINDINGS_FILE=/var/lib/avrana-home/identity_bindings.json", text)
            self.assertEqual(7, done.returncode, done.stderr)
            self.assertIn("initialise it first", done.stderr)

    def test_on_with_a_file_or_off_goes_on(self):
        on = "      - HOME_IDENTITY_BINDINGS_FILE=/var/lib/avrana-home/identity_bindings.json"
        self.assertEqual(0, self.run_guard(on, '{"format": "avrana-identity-bindings"}').returncode)
        self.assertEqual(0, self.run_guard("      # - HOME_IDENTITY_BINDINGS_FILE=/x", None).returncode)

    def test_the_guard_runs_before_build_and_up(self):
        text, match = guard()
        self.assertLess(match.start(), text.index("dc build"))
        self.assertLess(match.start(), text.index("dc up -d"))


if __name__ == "__main__":
    unittest.main()
