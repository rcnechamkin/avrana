"""Offline checks for the member-content drafts (AVR-361, S1-6).

Reads Markdown and the portal source as text only. It never imports or runs the portal or the
offboarding script, and never touches a service.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMBER = ROOT / 'docs' / 'member'
DRAFTS = ['welcome.md', 'help.md', 'house-rules-and-privacy.md']
REGISTER = MEMBER / 'DECISIONS-NEEDED.md'
RUNBOOK = ROOT / 'docs' / 'runbooks' / 'offboarding.md'
PORTAL = ROOT / 'services' / 'avrana-portal' / 'portal.py'
OFFBOARD = ROOT / 'scripts' / 'offboard.py'

COMMENT = re.compile(r'<!--.*?-->', re.S)
PLACEHOLDER = re.compile(r'\[(OWNER DECISION|UNVERIFIED|PROPOSED RULE) ([DUR]-\d+)[^\]]*\]')
KIND_LETTER = {'OWNER DECISION': 'D', 'UNVERIFIED': 'U', 'PROPOSED RULE': 'R'}
IF_MARK = re.compile(r'<!--\s*if:\s*([^>]*?)\s*-->')
ENDIF_MARK = re.compile(r'<!--\s*endif\s*-->')
ANY_COND = re.compile(r'<!--\s*(?:if:[^>]*?|endif)\s*-->')
SOURCE_PATH = re.compile(
    r'\b((?:docs|services|scripts|deploy|tests)/[A-Za-z0-9_./\-]+?\.(?:md|py|sh|yaml|yml|txt|json))')


def read(path):
    return path.read_text(encoding='utf-8')


def body(text):
    """Member-visible prose: no comments, no placeholders, no fenced code."""
    text = COMMENT.sub('', text)
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    return PLACEHOLDER.sub('', text)


def core(text):
    """Neutral core: body with every conditional block removed."""
    text = re.sub(r'<!--\s*if:[^>]*?-->.*?<!--\s*endif\s*-->', '', text, flags=re.S)
    return body(text)


def real_groups():
    names = set(re.findall(r'"(avrana-[a-z]+|library-contributors|authentik Admins)"', read(PORTAL)))
    names.add('avrana-users')  # the portal's own gate, named in its docstring and docs
    return names


class MemberContent(unittest.TestCase):
    def test_files_exist(self):
        for name in DRAFTS + ['DECISIONS-NEEDED.md']:
            self.assertTrue((MEMBER / name).is_file(), name)
        self.assertTrue(RUNBOOK.is_file())

    def test_implementer_note_at_top(self):
        for name in DRAFTS:
            head = read(MEMBER / name)[:3500]
            self.assertIn('NOTE TO THE IMPLEMENTER', head, name)
            self.assertIn('Neutral core', head.replace('neutral core', 'Neutral core'), name)
            self.assertRegex(head, r'(?i)conditional|if: group', name)

    def test_no_operator_internal_markers(self):
        patterns = {
            'private ip': r'\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|'
                          r'172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|127\.0\.0\.1)\b',
            'port': r'\w:\d{2,5}\b',
            'host path': r'/home/|/mnt/|/var/|/etc/',
            'container or compose name': r'authentik-(?:server|worker|postgresql|ldap)|avrana-portal|'
                                         r'docker[- ]compose|docker exec|calibre-web-automated|'
                                         r'avrana-kindle-connector|olivetin|beszel',
            'admin hostname': r'\bops\.|\bhomepage\b',
            'operator tool name': r'(?i)tracearr',
            'secret shaped': r'\b[A-Za-z0-9_\-]{32,}\b|-----BEGIN|(?i:password\s*=)',
            'e-mail address': r'[\w.+-]+@[\w-]+\.[\w.]+',
        }
        for name in DRAFTS:
            text = COMMENT.sub('', read(MEMBER / name))
            for label, pat in patterns.items():
                m = re.search(pat, text)
                self.assertIsNone(m, f'{name}: {label}: {m.group(0) if m else ""}')

    def test_no_dashes_or_first_person_in_member_text(self):
        first_person = re.compile(r"\b(?:we|our|ours|ourselves|us|my|mine|me|myself|i)\b|"
                                  r"\b(?:I'm|I'll|I've|I'd|we're|we'll|we've|let's)\b", re.I)
        for name in DRAFTS:
            text = body(read(MEMBER / name))
            for ch in ('\u2014', '\u2013'):
                self.assertNotIn(ch, text, f'{name}: dash {ch!r}')
            self.assertNotIn(' -- ', text, name)
            m = first_person.search(text)
            self.assertIsNone(m, f'{name}: first person: {m.group(0) if m else ""}')

    def test_no_email_addresses_anywhere(self):
        for path in [MEMBER / n for n in DRAFTS] + [REGISTER, RUNBOOK]:
            m = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', read(path))
            self.assertIsNone(m, f'{path.name}: {m.group(0) if m else ""}')

    def test_placeholders_and_register_agree(self):
        reg_ids = set(re.findall(r'^### ([DUR]-\d+)\s*$', read(REGISTER), re.M))
        self.assertTrue(reg_ids)
        used = set()
        for name in DRAFTS:
            for kind, ident in PLACEHOLDER.findall(read(MEMBER / name)):
                self.assertEqual(KIND_LETTER[kind], ident[0], f'{name}: {kind} {ident}')
                used.add(ident)
        self.assertFalse(used - reg_ids, f'placeholders missing from register: {sorted(used - reg_ids)}')
        runbook_ids = set(re.findall(r'\b([DUR]-\d+)\b', read(RUNBOOK)))
        self.assertFalse(runbook_ids - reg_ids, f'runbook ids missing: {sorted(runbook_ids - reg_ids)}')
        orphans = reg_ids - used - runbook_ids
        self.assertFalse(orphans, f'register entries used nowhere: {sorted(orphans)}')

    def test_register_entries_have_substance(self):
        text = read(REGISTER)
        sections = re.split(r'^### ', text, flags=re.M)[1:]
        for sec in sections:
            ident = sec.split('\n', 1)[0].strip()
            if ident.startswith('D-'):
                for key in ('**Question:**', '**Options', '**Changes', '**Blocked:**'):
                    self.assertIn(key, sec, ident)
            self.assertGreater(len(sec), 80, ident)

    def test_relative_links_resolve(self):
        link = re.compile(r'(?<!!)\[[^\]]*\]\(([^)\s]+)\)')
        for path in [MEMBER / n for n in DRAFTS] + [REGISTER, RUNBOOK]:
            for target in link.findall(COMMENT.sub('', read(path))):
                if re.match(r'[a-z]+:', target) or target.startswith('#'):
                    continue
                dest = (path.parent / target.split('#', 1)[0]).resolve()
                self.assertTrue(dest.exists(), f'{path.name}: broken link {target}')

    def test_cited_sources_exist(self):
        for path in [MEMBER / n for n in DRAFTS] + [REGISTER, RUNBOOK]:
            text = read(path)
            cited = SOURCE_PATH.findall(text)
            self.assertTrue(cited, path.name)
            for rel in set(cited):
                self.assertTrue((ROOT / rel).is_file(), f'{path.name}: cited path missing: {rel}')

    def test_conditional_markers_well_formed(self):
        groups = real_groups()
        for name in DRAFTS:
            text = read(MEMBER / name)
            depth = 0
            for m in ANY_COND.finditer(text):
                tok = m.group(0)
                if re.match(r'<!--\s*if:', tok):
                    self.assertEqual(depth, 0, f'{name}: nested or unclosed block')
                    depth = 1
                    names = [g.strip() for g in IF_MARK.match(tok).group(1).split('|')]
                    self.assertTrue(all(names), f'{name}: empty group in {tok}')
                    for g in names:
                        self.assertIn(g, groups, f'{name}: unknown group {g!r}')
                else:
                    self.assertEqual(depth, 1, f'{name}: endif without if')
                    depth = 0
            self.assertEqual(depth, 0, f'{name}: block not closed')
            # Markers must be written exactly as documented, not as near misses.
            stray = re.findall(r'<!--\s*(?:if|endif)\b(?!:)(?!\s*-->)[^>]*-->', text)
            self.assertFalse(stray, f'{name}: malformed marker {stray}')

    def test_neutral_core_names_no_library(self):
        terms = re.compile(
            r'(?i)jellyfin|swiftfin|wholphin|audiobookshelf|audiobooth|absorb|komga|calibre|seerr|'
            r'shelfarr|omnibus|kindle|audible|audiobook|comic|manga|movie|film|ebook|\bTV\b|amazon|'
            r'television|panels|moon\+')
        for name in DRAFTS:
            m = terms.search(core(read(MEMBER / name)))
            self.assertIsNone(m, f'{name}: library term in neutral core: {m.group(0) if m else ""}')

    def test_every_block_is_conditional_and_nonempty(self):
        for name in DRAFTS:
            blocks = re.findall(r'<!--\s*if:[^>]*?-->(.*?)<!--\s*endif\s*-->', read(MEMBER / name), re.S)
            self.assertGreaterEqual(len(blocks), 1, name)
            for b in blocks:
                self.assertTrue(body(b).strip(), f'{name}: empty block')

    def test_runbook_flags_are_real(self):
        flags = set(re.findall(r'add_argument\(\s*"(--[a-z-]+)"', read(OFFBOARD)))
        self.assertTrue({'--apply', '--purge', '--audit', '--yes'} <= flags)
        used = set(re.findall(r'(?<![\w-])(--[a-z][a-z-]+)', read(RUNBOOK)))
        allowed = flags | {'--staged'}
        self.assertFalse(used - allowed, f'runbook cites unknown flags: {sorted(used - allowed)}')
        text = read(RUNBOOK)
        for needle in ('--audit', '--apply', '--purge', 'dry run', 'Irreversible', 'UNGROUNDED'):
            self.assertIn(needle.lower(), text.lower(), needle)

    def test_runbook_has_no_secrets_or_dashes(self):
        text = read(RUNBOOK)
        self.assertNotRegex(text, r'\b[A-Za-z0-9_\-]{40,}\b')
        self.assertNotIn('-----BEGIN', text)
        self.assertNotIn('\u2014', text)
        self.assertNotIn('\u2013', text)


if __name__ == '__main__':
    unittest.main()
