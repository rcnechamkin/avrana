"""Tier A (standard library): development-only code must never reach a production image.

`dev/` holds the mock upstreams and the identity shim. Nothing in the `avrana_home` package may import
it, and if an image build context for this service ever exists it must exclude `dev/` (and `tests/`).
"""
import ast
import unittest
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
REPO = HOME.parents[1]
DEV_ROOTS = {"dev", "tests", "webtests"}


class DevIsolationTests(unittest.TestCase):
    def test_the_package_never_imports_dev_code(self):
        offenders = []
        for path in (HOME / "avrana_home").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "__import__":
                    names = [str(getattr(node.args[0], "value", ""))] if node.args else []
                for name in names:
                    if name.split(".")[0] in DEV_ROOTS:
                        offenders.append(f"{path.relative_to(HOME)}: {name}")
        self.assertEqual([], offenders)

    def test_no_string_path_to_dev_in_the_package(self):
        for path in (HOME / "avrana_home").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in ("dev_identity", "mock_jellyfin", "mock_audiobookshelf", "mock_komga", "fake_abs",
                           "fake_komga"):
                self.assertNotIn(needle, text, f"{path.name} mentions {needle}")

    def test_any_image_build_context_for_this_service_excludes_dev(self):
        """No Dockerfile exists yet (HOME-APP.md, known gaps). When one does, it must not COPY the whole
        service directory without a .dockerignore that lists dev/ and tests/."""
        files = [p for base in (HOME, REPO) for p in base.glob("*") if p.name.lower().startswith("dockerfile")]
        files += list(HOME.rglob("Dockerfile*"))
        for dockerfile in set(files):
            text = dockerfile.read_text(encoding="utf-8")
            if "avrana-home" not in text and dockerfile.parent != HOME:
                continue
            ignore = dockerfile.parent / ".dockerignore"
            listed = ignore.read_text(encoding="utf-8").split() if ignore.is_file() else []
            copies_dev = any(line.strip().upper().startswith(("COPY", "ADD")) and "dev" in line.split()
                             for line in text.splitlines())
            self.assertFalse(copies_dev, f"{dockerfile} copies dev/")
            self.assertTrue({"dev", "dev/", "tests", "tests/"} & set(listed) and
                            ("dev" in listed or "dev/" in listed),
                            f"{dockerfile}: a .dockerignore next to it must list dev/ (and tests/)")


if __name__ == "__main__":
    unittest.main()
