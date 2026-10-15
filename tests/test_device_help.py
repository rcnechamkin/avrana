"""Offline checks for the device help topics in docs/member/help/ (AVR-364 groundwork).

Reads Markdown as text only. Tripwires, not proof: a human read on a real device is still required, and
the UNVERIFIED markers may only be removed after one.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELP = ROOT / 'docs' / 'member' / 'help'
TOPICS = {  # file -> (group, host)
    'home-screen.md': ('avrana-users', 'avrana.net'),
    'sign-in.md': ('avrana-users', 'avrana.net'),
    'unavailable.md': ('avrana-users', 'avrana.net'),
    'open-watch.md': ('avrana-videos', 'watch.avrana.net'),
    'open-listen.md': ('avrana-audiobooks', 'listen.avrana.net'),
    'open-books.md': ('avrana-books', 'books.avrana.net'),
    'open-comics.md': ('avrana-comics', 'read.avrana.net'),
}
MARK = '[UNVERIFIED on a real device]'
STEP = re.compile(r'^(\d+)\. (.+)$')
META = re.compile(r'^(slug|group|host|store|url): (.+)$')
FIRST_PERSON = re.compile(r"\b(?:we|our|ours|ourselves|us|my|mine|me|myself|i)\b|"
                          r"\b(?:I'm|I'll|I've|I'd|we're|we'll|we've|let's)\b", re.I)
LIBRARY_TERMS = re.compile(
    r'(?i)jellyfin|swiftfin|wholphin|audiobookshelf|komga|calibre|seerr|shelfarr|omnibus|kindle|audible|'
    r'audiobook|comic|manga|movie|film|ebook|\bTV\b|watch|listen|\bread\b')
SECRETISH = re.compile(r'(?i)password\s*[:=]|api[_ -]?key|token\s*[:=]|secret\s*[:=]')
COMMITMENT = re.compile(
    r'(?i)\bwithin\b|\bguarantee|\balways\b|\bpromise|\b\d+\s*(?:minutes?|hours?|days?)\b|\binstantly\b')


def parse(path):
    t = {'label': None, 'meta': {}, 'platforms': []}
    cur_p = cur_c = None
    for n, line in enumerate(path.read_text(encoding='utf-8').split('\n'), 1):
        m_step, m_meta = STEP.match(line), META.match(line)
        if line.startswith('# '):
            t['label'] = line[2:].strip()
        elif line.startswith('## '):
            cur_p = {'name': line[3:].strip(), 'clients': []}
            t['platforms'].append(cur_p)
            cur_c = None
        elif line.startswith('### '):
            cur_c = {'name': line[4:].strip(), 'meta': {}, 'steps': []}
            cur_p['clients'].append(cur_c)
        elif m_step and cur_c is not None:
            cur_c['steps'].append((n, int(m_step.group(1)), m_step.group(2)))
        elif m_meta:
            (cur_c['meta'] if cur_c else t['meta'])[m_meta.group(1)] = m_meta.group(2).strip()
        elif line.strip():
            raise AssertionError(f'{path.name}:{n}: unexpected line {line!r}')
    return t


class DeviceHelp(unittest.TestCase):
    def test_exactly_the_expected_files(self):
        self.assertEqual(sorted(list(TOPICS) + ['README.md']), sorted(p.name for p in HELP.iterdir()))

    def test_structure_maps_onto_the_shell_format(self):
        slugs = set()
        for name, (group, host) in TOPICS.items():
            t = parse(HELP / name)
            self.assertTrue(t['label'], name)
            self.assertEqual(name[:-3], t['meta'].get('slug'), f'{name}: slug must match the file name')
            self.assertNotIn(t['meta']['slug'], slugs)
            slugs.add(t['meta']['slug'])
            self.assertEqual((group, host), (t['meta'].get('group'), t['meta'].get('host')), name)
            self.assertTrue(t['platforms'], name)
            for p in t['platforms']:
                self.assertTrue(p['clients'], f'{name}: platform {p["name"]!r} has no client')
                for c in p['clients']:
                    self.assertEqual({'store', 'url'}, set(c['meta']), f'{name}: {c["name"]!r}: store and url')
                    for key, val in c['meta'].items():
                        self.assertTrue(val == 'none' or re.fullmatch(r'https://[A-Za-z0-9.\-]+(/\S*)?', val),
                                        f'{name}: {c["name"]!r}: {key} must be exactly none or an https URL')
                    self.assertEqual(c['meta']['store'] == 'none', c['meta']['url'] == 'none',
                                     f'{name}: {c["name"]!r}: store and url must be set together')
                    self.assertTrue(c['steps'], f'{name}: {c["name"]!r} has no steps')
                    self.assertEqual(list(range(1, len(c['steps']) + 1)), [s[1] for s in c['steps']],
                                     f'{name}: {c["name"]!r}: step numbers')

    def test_every_step_is_marked_unverified_and_short(self):
        for name in TOPICS:
            for p in parse(HELP / name)['platforms']:
                for c in p['clients']:
                    for n, _, text in c['steps']:
                        self.assertTrue(text.endswith(MARK), f'{name}:{n}: step lacks {MARK}')
                        body = text[:-len(MARK)].strip()
                        self.assertLessEqual(len(body), 260, f'{name}:{n}: step too long')
                        self.assertNotRegex(body, r'[<>&]', f'{name}:{n}: markup characters in a step')

    def test_marker_is_not_softened_and_nothing_claims_testing(self):
        for name in TOPICS:
            raw = (HELP / name).read_text(encoding='utf-8')
            self.assertNotIn('verified on a real device', raw.replace(MARK, ''),
                             f'{name}: a verified claim or altered marker')
            self.assertNotRegex(raw, r'(?i)\btested\b|\bconfirmed working\b')

    def test_no_dashes_first_person_or_secrets(self):
        for p in HELP.glob('*.md'):
            raw = p.read_bytes().decode('utf-8')
            for ch in ('—', '–'):
                self.assertNotIn(ch, raw, f'{p.name}: dash {ch!r}')
            self.assertNotIn('\r', raw, f'{p.name}: CRLF')
            self.assertIsNone(SECRETISH.search(raw), p.name)
            m = FIRST_PERSON.search(raw)
            self.assertIsNone(m, f'{p.name}: first person: {m.group(0) if m else ""}')

    def test_neutral_topics_name_no_library(self):
        for name, (group, _) in TOPICS.items():
            if group != 'avrana-users':
                continue
            m = LIBRARY_TERMS.search((HELP / name).read_text(encoding='utf-8'))
            self.assertIsNone(m, f'{name}: library term in a topic every member sees: {m.group(0) if m else ""}')

    def test_library_topics_name_only_their_own_service(self):
        own = {'open-watch.md': 'Watch', 'open-listen.md': 'Listen', 'open-books.md': 'Read',
               'open-comics.md': 'Read'}
        for name, word in own.items():
            raw = (HELP / name).read_text(encoding='utf-8')
            for other in ('watch.avrana.net', 'listen.avrana.net', 'books.avrana.net', 'read.avrana.net'):
                if other != TOPICS[name][1]:
                    self.assertNotIn(other, raw, f'{name}: names another library host')
            self.assertIn(word, raw)

    def test_open_decisions_stay_visible(self):
        need = {'sign-in.md': ['D-13', 'D-1'], 'unavailable.md': ['D-15', 'D-1'], 'open-watch.md': ['D-1'],
                'open-listen.md': ['D-1'], 'open-books.md': ['D-1'], 'open-comics.md': ['D-1']}
        for name, ids in need.items():
            raw = (HELP / name).read_text(encoding='utf-8')
            for i in ids:
                self.assertRegex(raw, rf'\[OWNER DECISION {i}[:\]]', f'{name}: {i} marker missing')

    def test_no_invented_commitments(self):
        for name in TOPICS:
            m = COMMITMENT.search((HELP / name).read_text(encoding='utf-8'))
            self.assertIsNone(m, f'{name}: commitment wording {m.group(0) if m else ""}')


if __name__ == '__main__':
    unittest.main()
