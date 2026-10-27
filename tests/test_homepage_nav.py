"""AVR-366: the operator Homepage stays grouped by pipeline and matches the services that exist.

Standard library only (the config is read with regular expressions, not a YAML parser). Checks: every group in
services.yaml has a layout entry in settings.yaml and the reverse; every `container:` a tile names is an expected
container (deploy/docker/expected-containers.txt), so a retired service cannot linger as a tile; retired BookStack and
a self-link are gone; the Libation tile no longer opens Audiobookshelf.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "deploy" / "homepage" / "config"
SERVICES = (CONFIG / "services.yaml").read_text(encoding="utf-8")
SETTINGS = (CONFIG / "settings.yaml").read_text(encoding="utf-8")
EXPECTED = {line.split("#", 1)[0].strip()
            for line in (ROOT / "deploy" / "docker" / "expected-containers.txt").read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()}


def tiles():
    """{tile name: its block text}."""
    out, name = {}, None
    for line in SERVICES.splitlines():
        m = re.match(r"^    - ([^:]+):$", line)
        if m:
            name = m.group(1)
            out[name] = []
        elif re.match(r"^- ", line):
            name = None
        elif name:
            out[name].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


class HomepageNav(unittest.TestCase):
    def test_groups_and_layout_agree(self):
        groups = re.findall(r"(?m)^- ([^:]+):$", SERVICES)
        layout = re.findall(r"(?m)^  ([^:\s][^:]*):$", SETTINGS.split("layout:", 1)[1])
        self.assertEqual(["Video", "Audiobooks", "Books", "Comics", "Operations"], groups)
        self.assertEqual(groups, layout)

    def test_every_tile_container_is_an_expected_container(self):
        for name, block in tiles().items():
            for container in re.findall(r"(?m)^        container: (\S+)$", block):
                with self.subTest(tile=name):
                    self.assertIn(container, EXPECTED)

    def test_retired_and_self_tiles_are_gone(self):
        names = set(tiles())
        self.assertNotIn("BookStack", names)
        self.assertNotIn("Homepage", names)
        self.assertNotIn("bookstack", SERVICES.split("#")[0].lower())

    def test_libation_links_to_its_status_not_audiobookshelf(self):
        block = tiles()["Libation"]
        href = re.search(r"(?m)^        href: (\S+)$", block).group(1)
        self.assertTrue(href.endswith(":8087"), href)
        self.assertNotIn(":13378", href)


if __name__ == "__main__":
    unittest.main()
