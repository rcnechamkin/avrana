"""The Design Foundation mirror stays intact (docs/design/foundation/, AVR-424).

Offline, standard library only. The Party repository holds the source copy of README.md and
tokens.json; MIRROR.sha256 is the record both repositories carry. A change to either file here
fails until the record is updated, which is the prompt to change the Party copy too.
The Media colour roles in tokens.json must also be the colours DESIGN.md declares.
"""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = ROOT / 'docs' / 'design' / 'foundation'

# foundation role -> the colour name in DESIGN.md's front matter
MEDIA_ROLES = {
    'surface': 'ink', 'on_surface': 'paper', 'on_surface_muted': 'ash',
    'outline_quiet': 'rule-quiet', 'outline_control': 'rule-control', 'outline_strong': 'rule-strong',
    'action': 'paper', 'on_action': 'ink',
    'status_ok': 'ok', 'status_warn': 'warn', 'status_error': 'err',
}


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


class DesignFoundationTest(unittest.TestCase):
    def test_mirrored_files_match_their_record(self):
        lines = (FOUNDATION / 'MIRROR.sha256').read_text().splitlines()
        recorded = dict(reversed(line.split()) for line in lines if line.strip())
        self.assertEqual(set(recorded), {'README.md', 'tokens.json'})
        for name, want in recorded.items():
            self.assertEqual(digest(FOUNDATION / name), want,
                             f'{name} changed: change the Party copy first, then update MIRROR.sha256 in both')

    def test_media_roles_are_the_design_specification_colours(self):
        tokens = json.loads((FOUNDATION / 'tokens.json').read_text(encoding='utf-8'))
        media = tokens['themes']['media']['color']
        self.assertLessEqual(set(tokens['roles']), set(media))
        front = (ROOT / 'docs' / 'design' / 'DESIGN.md').read_text(encoding='utf-8').split('---')[1]
        declared = dict(re.findall(r'^\s+([\w-]+):\s*"(#[0-9a-fA-F]{6})"\s*$', front, re.M))
        for role, name in MEDIA_ROLES.items():
            self.assertEqual(media[role].lower(), declared[name].lower(), f'{role} and {name} differ')


if __name__ == '__main__':
    unittest.main()
