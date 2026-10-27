"""AVR-365: the OliveTin member-notice action and Avrana Home agree, and the action is operator-only.

Standard library only. Checks the three lists of notice IDs (the action's choices, the script's allowlist, Home's
notice.NOTICES) are the same; that the action is on the admin ACL with fixed choices only; and runs the script in a
temporary directory: a valid ID writes an ID-and-time file Home parses, "clear" removes it, anything else is refused
and writes nothing.
"""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLIVETIN = ROOT / "services" / "olivetin"
CONFIG = (OLIVETIN / "config" / "config.yaml").read_text(encoding="utf-8")
SCRIPT = OLIVETIN / "scripts" / "home-notice.sh"
NOTICE_PY = ROOT / "services" / "avrana-home" / "avrana_home" / "app" / "notice.py"


def home_notice():
    """Load notice.py with its one package import (logsafe) stubbed, so this test needs no framework."""
    import types
    pkg = types.ModuleType("_notice_pkg")
    pkg.__path__ = []
    logsafe = types.ModuleType("_notice_pkg.logsafe")
    logsafe.app_log = None
    logsafe.log_event = lambda *a, **k: None
    sys.modules.setdefault("_notice_pkg", pkg)
    sys.modules["_notice_pkg.logsafe"] = logsafe
    spec = importlib.util.spec_from_file_location("_notice_pkg.notice", NOTICE_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                       # dataclasses look the module up while the class is built
    spec.loader.exec_module(mod)
    return mod


def action_block():
    m = re.search(r"(?ms)^  - id: home_notice\n(.*?)(?=^  - id: |\Z)", CONFIG)
    assert m, "home_notice action missing"
    return m.group(1)


def bash():
    found = shutil.which("bash")
    if found and sys.platform == "win32" and "system32" in found.lower():
        found = None                                   # WSL's launcher, not a POSIX shell for this repo
    return found


class Agreement(unittest.TestCase):
    def test_choices_allowlist_and_home_agree(self):
        choices = re.findall(r"(?m)^          - value: ([a-z-]+)$", action_block())
        allowed = re.search(r'(?m)^ALLOWED="([^"]+)"$', SCRIPT.read_text(encoding="utf-8")).group(1).split()
        self.assertEqual(["clear"] + allowed, choices)
        self.assertEqual(sorted(allowed), sorted(home_notice().NOTICES))

    def test_the_action_is_admin_only_with_fixed_choices(self):
        block = action_block()
        self.assertIn("acls: [avrana-admins]", block)
        self.assertIn("shell: /opt/avrana/scripts/home-notice.sh {{ notice }}", block)
        self.assertEqual(["choices"], re.findall(r"(?m)^\s+type: (\w+)$", block))
        self.assertIn("view: false\n  exec: false\n  logs: false", CONFIG)          # default deny is still in place


@unittest.skipIf(bash() is None, "bash not available")
class Script(unittest.TestCase):
    def run_script(self, *args):
        env = {"AVRANA_NOTICE_FILE": str(self.file), "PATH": str(Path(bash()).parent) + ":/usr/bin:/bin"}
        return subprocess.run([bash(), str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.file = self.dir / "current.json"

    def test_set_writes_a_file_home_reads_and_clear_removes_it(self):
        r = self.run_script("maintenance")
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        doc = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual({"id", "set"}, set(doc))
        self.assertEqual("maintenance", home_notice().parse(self.file.read_bytes()).notice.id)
        self.assertEqual([self.file.name], [p.name for p in self.dir.iterdir()])   # no temp file left behind
        r = self.run_script("clear")
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertFalse(self.file.exists())

    def test_anything_else_is_refused_and_writes_nothing(self):
        for bad in ("", "Maintenance", "maintenance ", "slow; rm -rf /", "../../etc/passwd", "$(id)", "clear2"):
            r = self.run_script(bad)
            with self.subTest(arg=bad):
                self.assertEqual(2, r.returncode, r.stdout)
                self.assertFalse(self.file.exists())
        self.assertEqual(2, self.run_script().returncode)

    def test_a_missing_directory_fails_loudly(self):
        self.file = self.dir / "absent" / "current.json"
        r = self.run_script("slow")
        self.assertEqual(2, r.returncode)
        self.assertIn("not mounted", r.stdout)


if __name__ == "__main__":
    unittest.main()
