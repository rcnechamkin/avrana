"""Offline checks for the member-content drafts (AVR-361, S1-6).

Reads Markdown and the portal source as text only. It never imports or runs the portal or the
offboarding script, and never touches a service.

Several checks here are TRIPWIRES, not proof: the personal-data scan, the invented-commitment scan and the
neutral-core vocabulary scan catch the common ways a draft can go wrong, and each states its limit where
it is defined. A human read of the drafts is still required before anything is published.
"""
import re
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMBER = ROOT / 'docs' / 'member'
DRAFTS = ['welcome.md', 'help.md', 'house-rules-and-privacy.md']
REGISTER = MEMBER / 'DECISIONS-NEEDED.md'
RUNBOOK = ROOT / 'docs' / 'runbooks' / 'offboarding.md'
PORTAL = ROOT / 'services' / 'avrana-portal' / 'portal.py'
OFFBOARD = ROOT / 'scripts' / 'offboard.py'
FIVE_DOCS = [MEMBER / n for n in DRAFTS] + [REGISTER, RUNBOOK]

COMMENT = re.compile(r'<!--.*?-->', re.S)
PLACEHOLDER = re.compile(r'\[(OWNER DECISION|UNVERIFIED|PROPOSED RULE) ([DUR]-\d+)[^\]]*\]')
KIND_LETTER = {'OWNER DECISION': 'D', 'UNVERIFIED': 'U', 'PROPOSED RULE': 'R'}
IF_MARK = re.compile(r'<!--\s*if:\s*([^>]*?)\s*-->')
ENDIF_MARK = re.compile(r'<!--\s*endif\s*-->')
ANY_COND = re.compile(r'<!--\s*(?:if:[^>]*?|endif)\s*-->')
BLOCK = re.compile(r'<!--\s*if:\s*([^>]*?)\s*-->(.*?)<!--\s*endif\s*-->', re.S)
SOURCE_PATH = re.compile(
    r'\b((?:docs|services|scripts|deploy|tests)/[A-Za-z0-9_./\-]+?\.(?:md|py|sh|yaml|yml|txt|json))')
# path:line, path:a-b and continuations such as "path:12-14, :20" or "path:12, 30-31". A bare file name
# (portal.py:627) is resolved against the unique file of that name under docs, services, scripts, deploy
# and tests.
CITE = re.compile(
    r'(?P<path>(?:(?:docs|services|scripts|deploy|tests)/[A-Za-z0-9_./\-]+?'
    r'|[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*?)\.(?:md|py|sh|yaml|yml|txt|json))'
    r':(?P<rest>\d+(?:-\d+)?(?:,\s*`?:?\d+(?:-\d+)?)*)')

# Marker ids that must stay visible, with the MINIMUM number of occurrences per file. Member drafts count
# bracketed markers ("[OWNER DECISION D-12 ...]"); the runbook counts bare ids outside comments. Replacing
# one of several occurrences with an invented answer lowers a count and fails. Lowering a number here is an
# owner-visible act: do it only when an owner decision has been made and recorded.
EXPECTED_MARKERS = {
    'welcome.md': {'D-1': 1, 'D-11': 1, 'D-12': 1, 'D-13': 2, 'D-15': 1, 'U-1': 1, 'U-3': 1, 'U-7': 1,
                   'U-8': 1, 'U-19': 1},
    'help.md': {'D-1': 2, 'D-12': 1, 'D-13': 2, 'D-14': 1, 'D-15': 1, 'D-16': 1, 'U-6': 1, 'U-7': 1,
                'U-8': 1},
    'house-rules-and-privacy.md': {'D-1': 1, 'D-7': 2, 'D-9': 1, 'D-17': 2, 'R-1': 1, 'R-2': 1, 'R-3': 1,
                                   'R-4': 1, 'R-5': 1, 'R-6': 1, 'U-4': 2, 'U-5': 1, 'U-6': 2, 'U-7': 2,
                                   'U-8': 2, 'U-9': 2, 'U-10': 1, 'U-11': 1, 'U-12': 1, 'U-13': 1,
                                   'U-14': 1, 'U-15': 1, 'U-16': 1, 'U-19': 1},
}
EXPECTED_RUNBOOK_IDS = {'D-17': 4, 'U-2': 2, 'U-5': 1, 'U-8': 1, 'U-14': 1, 'U-17': 2, 'U-18': 2, 'U-20': 2}

# Groups a member-facing block may name. Cross-checked against the portal in a test.
MEMBER_GROUPS = {'avrana-videos', 'avrana-audiobooks', 'avrana-books', 'avrana-comics', 'avrana-requests',
                 'library-contributors'}

# Pinned topic -> group table, in document order: (first heading or bold label in the block, groups).
# 'avrana-requests' on the help.md Requests block documents the OPEN state of decision D-14: on main the
# portal gates the Requests help topic on avrana-requests; PR #4 proposes avrana-videos. Changing either
# side silently must fail. When the owner decides, change this table and the block together.
BLOCK_GROUPS = {
    'welcome.md': [
        ('Movies and TV', ('avrana-videos',)),
        ('Audiobooks', ('avrana-audiobooks',)),
        ('Ebooks and Send to Kindle', ('avrana-books',)),
        ('Comics and manga', ('avrana-comics',)),
        ('Asking for a film or show', ('avrana-videos',)),
        ('Asking for an ebook or audiobook', ('avrana-books', 'avrana-audiobooks')),
        ('Asking for a comic or manga', ('avrana-comics',)),
        ('Adding your own Audible books', ('library-contributors',)),
    ],
    'help.md': [
        ('Movies and TV', ('avrana-videos',)),
        ('Audiobooks', ('avrana-audiobooks',)),
        ('Books', ('avrana-books',)),
        ('Comics', ('avrana-comics',)),
        ('Requests', ('avrana-requests',)),
        ('Audiobooks', ('avrana-audiobooks',)),
        ('Comics, in a browser', ('avrana-comics',)),
        ('Books', ('avrana-books',)),
        ('Movies and TV', ('avrana-videos',)),
        ('Asking for a film or show', ('avrana-videos',)),
        ('Asking for a book or comic', ('avrana-books', 'avrana-audiobooks', 'avrana-comics')),
        ('Adding Audible books', ('library-contributors',)),
        ('Movies and TV', ('avrana-videos',)),
        ('Comics', ('avrana-comics',)),
        ('Films and shows', ('avrana-videos',)),
        ('Ebooks and audiobooks', ('avrana-books', 'avrana-audiobooks')),
        ('Comics and manga', ('avrana-comics',)),
        ('Send to Kindle', ('avrana-books',)),
    ],
    'house-rules-and-privacy.md': [
        ('Movies and TV', ('avrana-videos',)),
        ('Adding Audible books', ('library-contributors',)),
        ('Movies and TV: viewing', ('avrana-videos',)),
        ('Audiobooks', ('avrana-audiobooks',)),
        ('Comics and manga', ('avrana-comics',)),
        ('Ebooks and your Kindle address', ('avrana-books',)),
        ('Ebook and audiobook requests', ('avrana-books', 'avrana-audiobooks')),
        ('Adding Audible books', ('library-contributors',)),
    ],
}

# Time and quantity phrases the member drafts may contain WITHOUT a decision marker in the same sentence,
# with exact counts. Each is a repository fact, not a promise: session lengths
# (docs/services/authentik-sessions-passkeys.md:21-33), "straight away" and "at once" for the audiobook
# service password (docs/services/authentik.md:21), nightly backups (services/backups/README.md:12-20) and
# the off-host retention rule (services/backups/OFFHOST.md:28-37). Built from the text as it stands.
# A new or changed phrase (for example "replies within 24 hours", or "30 days" becoming "90 days")
# changes the counts and fails until the owner confirms the repository supports it.
# LIMIT: this is a keyword tripwire. A promise worded without any of these words passes.
COMMITMENT = re.compile(
    r'(?i)\bwithin\s+\w+(?:\s+\w+)?\s+(?:seconds?|minutes?|hours?|days?|weeks?|months?)\b'
    r'|\b\d+\s*(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?|times)\b'
    r'|\balways\b|\bguarantee[sd]?\b|\bnever\s+share[sd]?\b|\bat once\b|\bstraight away\b'
    r'|\bimmediately\b|\binstantly\b|\bright away\b|\bpromptly\b|\bpromise[sd]?\b|\bforever\b'
    r'|\bevery\s+(?:day|night|hour|week|month)\b|\bwithin\b|\bno more than\b|\bat most\b|\bat least\b'
    r'|\b24/7\b|\bsame day\b|\bnext day\b')
ALLOWED_COMMITMENTS = {
    'welcome.md': {'30 days': 1, '180 days': 1, 'straight away': 1},
    'help.md': {'at once': 1},
    'house-rules-and-privacy.md': {'30 days': 2, '180 days': 1, 'every night': 1, '90 days': 1},
}

# Citations whose line CONTENT matters to a statement in a document: (document, literal citation as
# written, repo file, line, text that line must contain). Kills a wrong line number that still falls
# inside the file, and code drift under a cited line.
PINNED_CITES = [
    (MEMBER / 'help.md', 'portal.py:627', 'services/avrana-portal/portal.py', 627, 'Recommended'),
    (MEMBER / 'help.md', 'portal.py:272-295', 'services/avrana-portal/portal.py', 272, 'avrana-requests'),
    (MEMBER / 'help.md', ':56 (tile gated', 'services/avrana-portal/portal.py', 56, 'avrana-videos'),
    (MEMBER / 'welcome.md', 'portal.py:357-358', 'services/avrana-portal/portal.py', 358, 'sign_out'),
    (RUNBOOK, 'scripts/offboard.py:99-102', 'scripts/offboard.py', 101, "'{username}'"),
    (RUNBOOK, 'offboard.py:99-102, 203-204', 'scripts/offboard.py', 204, "'{u}'"),
    (RUNBOOK, 'scripts/offboard.py:218-220', 'scripts/offboard.py', 218, 'authentik_user'),
    (RUNBOOK, 'scripts/offboard.py:75-76', 'scripts/offboard.py', 76, '.stdout'),
]

# Personal-data tripwire (see test_no_personal_data_shapes). The e-mail rule has no allow-listed address:
# no document names one. Only these reserved example domains are tolerated.
ALLOWED_EMAIL_DOMAINS = {'example.invalid', 'example.com'}
ALLOWED_EMAILS = set()
# Capitalised word pairs are skipped when either word is a product, place or interface term used in the
# documents, or when the first word is an ordinary sentence opener. "Ask Cody" is the existing portal copy
# quoted in the register (services/avrana-portal/portal.py:562).
PAIR_PRODUCT_WORDS = {
    'Avrana', 'Authentik', 'Jellyfin', 'Seerr', 'Audible', 'Amazon', 'Kindle', 'Komga', 'Shelfarr',
    'Omnibus', 'Swiftfin', 'Wholphin', 'Quick', 'Connect', 'Media', 'Player', 'Account', 'Help', 'Request',
    'Personal', 'Document', 'Calibre', 'Audiobookshelf', 'Tracearr', 'Backblaze', 'Linear', 'Django',
    'Docker', 'Postgres', 'Cloudflare', 'Apple', 'Android', 'Google', 'Fire', 'Stick', 'Roku', 'Samsung',
    'Face', 'Moon', 'Pocket', 'Panels', 'Reader', 'Send', 'Manage', 'Sign', 'Home', 'House', 'Rules',
}
PAIR_SENTENCE_OPENERS = {
    'The', 'Your', 'Ask', 'Choose', 'Open', 'What', 'Whether', 'Adding', 'Approved', 'Leaving', 'This',
    'That', 'These', 'Those', 'When', 'Where', 'Which', 'Who', 'How', 'Why', 'Each', 'Every', 'Any',
    'Some', 'Many', 'Most', 'Both', 'Only', 'Also', 'Then', 'There', 'Here', 'After', 'Before', 'Until',
    'With', 'Without', 'Check', 'Confirm', 'Decide', 'Do', 'Does', 'Never', 'Always', 'Note', 'See',
    'Say', 'Tell', 'Use', 'Verify', 'Run', 'Read', 'Record', 'Keep', 'Set', 'Delete', 'Restart', 'Repeat',
    'Compare', 'Add', 'Remove', 'Press', 'Type', 'Go', 'Sign', 'Search', 'Install', 'Download', 'Write',
}
PAIR_ALLOWED = {'Ask Cody'}
STREET_SUFFIX = (r'(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Court|Ct|Way|Place|Pl|'
                 r'Terrace|Crescent|Close|Circle)')
PERSONAL_SHAPES = {
    'phone number': re.compile(
        r'(?<![\w.-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)[ .-]?|\d{2,4}[ .-])\d{3,4}[ .-]\d{3,4}(?![\w-])'
        r'|\+\d{1,3}[ .-]?\d[\d .()-]{7,}\d'),
    'street address': re.compile(
        r'\b\d{1,5}[A-Za-z]?\s+(?:[A-Z][a-z]+\s+){1,3}' + STREET_SUFFIX + r'\b\.?|\bP\.?O\.?\s*Box\s+\d+',
        re.I),
}


def read(path):
    return path.read_text(encoding='utf-8')


def body(text):
    """Member-visible prose: no comments, no placeholders, no fenced code."""
    text = COMMENT.sub('', text)
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    return PLACEHOLDER.sub('', text)


def prose_with_markers(text):
    """Prose as an owner would read it: no comments or code, placeholders kept."""
    text = COMMENT.sub('', text)
    return re.sub(r'```.*?```', '', text, flags=re.S)


def core(text):
    """Neutral core: body with every conditional block removed."""
    text = re.sub(r'<!--\s*if:[^>]*?-->.*?<!--\s*endif\s*-->', '', text, flags=re.S)
    return body(text)


def portal_text():
    return read(PORTAL)


def portal_groups():
    """Group names the portal itself uses, from its quoted strings."""
    return set(re.findall(r'"(avrana-[a-z]+|library-contributors|authentik Admins)"', portal_text()))


def real_groups():
    return portal_groups() | {'avrana-users'}  # avrana-users is the portal's own gate, named in its docstring


def unescape(s):
    return (s.replace('&amp;', '&').replace('&nbsp;', ' ').replace('&#8209;', '-').replace('&rsquo;', "'"))


def portal_vocabulary():
    """Device, app, service and tile names, derived from the portal's own tables (SERVICES, CHOOSERS, HELP).

    Independent of the documents on purpose. Generic words that are not a product (browser, Android,
    iPhone, iPad) are left out; everything else the portal names must never appear in a neutral core.
    """
    src = portal_text()
    terms = set()
    services = re.search(r'^SERVICES = \[(.*?)^\]', src, re.S | re.M).group(1)
    services = re.sub(r'(?m)^\s*#.*$', '', services)
    for label, desc, _path in re.findall(
            r'\(\s*(?:"[^"]+"|\([^)]*\)),\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)"', services):
        terms.add(unescape(label))
    choosers = re.sub(r'(?m)^\s*#.*$', '', re.search(r'^CHOOSERS = \[(.*?)^\]', src, re.S | re.M).group(1))
    for label, _desc in re.findall(r'\(\s*"([^"]+)",\s*"([^"]+)"', choosers):
        terms.add(unescape(label))
    help_src = re.sub(r'(?m)^\s*#.*$', '', re.search(r'^HELP = \[(.*?)^\]\n', src, re.S | re.M).group(1))
    for name in re.findall(r'\(\s*"([^"]+)",\s*(?:"[^"]*"|None),\s*(?:"[^"]*"|None),\s*\[', help_src):
        terms.add(name)
    for platform in re.findall(r'(?m)^        \("([^"]+)", \[\s*$', help_src):
        for part in re.split(r',\s*|\s+and\s+', platform):
            terms.add(part.strip())
    for _grp, topic in re.findall(r'(?m)^    \("(avrana-[a-z]+)", "([^"]+)"', help_src):
        terms.add(topic)
    generic = {'Any browser', 'Web browser', 'Android', 'iPhone', 'iPad', 'iPhone and iPad', 'Windows',
               'Operations', 'Contribute'}
    return {t for t in terms if t and t not in generic}


def split_sentences(text):
    return [s for s in re.split(r'(?<=[.!?])\s+|\n\s*\n|\n(?=\s*(?:[-*]|\d+\.)\s)', text) if s.strip()]


def citations(text):
    """Yield (path, [(start, end), ...]) for every path:line citation in text."""
    for m in CITE.finditer(text):
        spans = []
        for part in re.findall(r'\d+(?:-\d+)?', m.group('rest')):
            a, _, b = part.partition('-')
            spans.append((int(a), int(b or a)))
        yield m.group('path'), spans


def repo_index():
    index = {}
    for top in ('docs', 'services', 'scripts', 'deploy', 'tests'):
        for p in (ROOT / top).rglob('*'):
            if p.is_file() and 'archive' not in p.parts:
                index.setdefault(p.name, []).append(p)
    return index


def lines_of(path):
    return path.read_text(encoding='utf-8', errors='replace').splitlines()


def span_ok(lines, start, end):
    """In range, and a single line must be non-empty; a range must contain at least one non-empty line."""
    if not (1 <= start <= end <= len(lines)):
        return False
    if end - start > 150:
        return False
    return any(lines[i - 1].strip() for i in range(start, end + 1)) and (
        start != end or bool(lines[start - 1].strip()))


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

    def test_no_dashes_or_first_person_anywhere(self):
        """Member prose (placeholders included) and the runbook: no first person, no em or en dashes.

        Dashes are checked in the raw text, comments included, for all five documents. The runbook
        quotes the request type "remove my data" (a phrase a member uses); that quoted name is removed
        before the first-person scan, nothing else is.
        """
        first_person = re.compile(r"\b(?:we|our|ours|ourselves|us|my|mine|me|myself|i)\b|"
                                  r"\b(?:I'm|I'll|I've|I'd|we're|we'll|we've|let's)\b", re.I)
        for path in FIVE_DOCS:
            raw = read(path)
            for ch in ('\u2014', '\u2013'):
                self.assertNotIn(ch, raw, f'{path.name}: dash {ch!r}')
            self.assertNotIn(' -- ', prose_with_markers(raw), path.name)
            text = prose_with_markers(raw).replace('"remove my data"', '')
            m = first_person.search(text)
            self.assertIsNone(m, f'{path.name}: first person: {m.group(0) if m else ""} '
                                 f'near {text[max(0, m.start() - 40):m.end() + 40]!r}' if m else '')

    def test_no_personal_data_shapes(self):
        """Tripwire for private member information in the five documents. NOT proof.

        It looks for e-mail addresses, phone-number shapes, street-address shapes and capitalised
        two-word pairs that look like a first and last name. It cannot know a name it has not seen: a
        single first name, a lower-case name, an initial, or an address written in words will pass.
        The name check skips pairs containing a product, place or interface word used in the documents
        and sentence-opening words (see PAIR_PRODUCT_WORDS and PAIR_SENTENCE_OPENERS). A human read of
        every draft is still required.
        """
        pair = re.compile(r'(?=\b([A-Z][a-z]{2,})[ \t]+([A-Z][a-z]{2,})\b)')
        for path in FIVE_DOCS:
            text = read(path)
            for m in re.finditer(r'[\w.+-]+@([\w-]+(?:\.[\w-]+)+)', text):
                ok = m.group(0) in ALLOWED_EMAILS or m.group(1).lower() in ALLOWED_EMAIL_DOMAINS
                self.assertTrue(ok, f'{path.name}: e-mail address {m.group(0)}')
            scrubbed = re.sub(r'\b\d{4}-\d{2}-\d{2}(?:T[\d:\-Z]+)?\b', '', text)
            for label, pat in PERSONAL_SHAPES.items():
                m = pat.search(scrubbed)
                self.assertIsNone(m, f'{path.name}: {label}: {m.group(0) if m else ""}')
            for m in pair.finditer(text):
                first, second = m.group(1), m.group(2)
                if f'{first} {second}' in PAIR_ALLOWED:
                    continue
                if first in PAIR_PRODUCT_WORDS or second in PAIR_PRODUCT_WORDS:
                    continue
                if first in PAIR_SENTENCE_OPENERS:
                    continue
                self.fail(f'{path.name}: possible person name {first} {second!r}; if this is a product or '
                          f'place word, add it to PAIR_PRODUCT_WORDS')

    def test_scanner_shapes_catch_what_they_claim(self):
        """The tripwires themselves: shapes they must flag and ordinary text they must not."""
        phone = PERSONAL_SHAPES['phone number']
        street = PERSONAL_SHAPES['street address']
        for hit in ('call 555-867-5309 today', 'call (555) 867-5309', 'call +44 20 7946 0958'):
            self.assertIsNotNone(phone.search(hit), hit)
        for miss in ('since 2026-09-20T09-34-23Z', 'about 90 days', 'items 123-456 of the list'):
            self.assertIsNone(phone.search(re.sub(r'\b\d{4}-\d{2}-\d{2}(?:T[\d:\-Z]+)?\b', '', miss)), miss)
        for hit in ('lives at 42 Maple Street', '7 Old Mill Road.', 'PO Box 123'):
            self.assertIsNotNone(street.search(hit), hit)
        self.assertIsNone(street.search('keeps the newest 7 complete copies'))

    def test_placeholder_occurrences_are_pinned(self):
        """Each marker keeps at least the pinned number of occurrences, and no unpinned id appears."""
        for name in DRAFTS:
            found = Counter(m.group(2) for m in PLACEHOLDER.finditer(read(MEMBER / name)))
            expected = EXPECTED_MARKERS[name]
            self.assertFalse(set(found) - set(expected), f'{name}: unpinned markers {sorted(set(found) - set(expected))}')
            for ident, minimum in expected.items():
                self.assertGreaterEqual(found.get(ident, 0), minimum,
                                        f'{name}: {ident} appears {found.get(ident, 0)} time(s), expected '
                                        f'at least {minimum}; an answer may have replaced a placeholder')
        text = COMMENT.sub('', read(RUNBOOK))
        found = Counter(re.findall(r'\b([DUR]-\d+)\b', text))
        self.assertFalse(set(found) - set(EXPECTED_RUNBOOK_IDS),
                         f'runbook: unpinned ids {sorted(set(found) - set(EXPECTED_RUNBOOK_IDS))}')
        for ident, minimum in EXPECTED_RUNBOOK_IDS.items():
            self.assertGreaterEqual(found.get(ident, 0), minimum, f'runbook: {ident}')

    def test_no_invented_commitments(self):
        """Time and quantity promises need a decision marker in the same sentence, or must be pinned.

        Sentences are split on full stops, blank lines and list items. A phrase in a sentence that holds a
        placeholder is the owner's open question and is skipped. Everything else must match
        ALLOWED_COMMITMENTS exactly (counts included), so a new promise or a changed number fails.
        """
        for name in DRAFTS:
            text = COMMENT.sub('', read(MEMBER / name))
            found = Counter()
            for sentence in split_sentences(text):
                if PLACEHOLDER.search(sentence):
                    continue
                for m in COMMITMENT.finditer(sentence):
                    found[m.group(0).lower()] += 1
            self.assertEqual(dict(found), ALLOWED_COMMITMENTS[name],
                             f'{name}: time or quantity phrases changed; each must be backed by the '
                             f'repository and then added to ALLOWED_COMMITMENTS')

    def test_commitment_scanner_catches_known_promises(self):
        def scan(s):
            return [m.group(0).lower() for sent in split_sentences(s) if not PLACEHOLDER.search(sent)
                    for m in COMMITMENT.finditer(sent)]
        self.assertIn('within 24 hours', scan('An admin replies within 24 hours.'))
        self.assertIn('90 days', scan('A normal sign-in lasts 90 days.'))
        self.assertIn('guarantee', scan('We guarantee removal.'))
        self.assertIn('always', scan('Requests are always approved.'))
        self.assertEqual([], scan('[OWNER DECISION D-17: removal within 30 days] Then nothing.'))

    def test_leaving_section_is_a_placeholder_not_a_promise(self):
        text = read(MEMBER / 'house-rules-and-privacy.md')
        section = text.split('## Leaving Avrana', 1)[1]
        section = COMMENT.sub('', section)
        self.assertIn('[OWNER DECISION D-17', section)
        self.assertIn('[OWNER DECISION D-1', section)
        section = PLACEHOLDER.sub('', section)
        for phrase in ('switched off', 'switched back on', 'deleted from each', 'cannot be undone',
                       'Nothing is deleted', 'history is kept'):
            self.assertNotIn(phrase, section, phrase)

    def test_no_claim_that_account_sign_out_ends_the_session(self):
        """U-19: what the portal Sign out ends is unverified. No draft may state that it ends Avrana's session."""
        for name in DRAFTS:
            text = body(read(MEMBER / name))
            self.assertNotRegex(text, r'(?is)sign(?:ing)?\s+out[^.]{0,80}(?:as well|everywhere)', name)
            self.assertNotRegex(text, r'(?i)sign out from the Account page', name)
        for name in ('welcome.md', 'house-rules-and-privacy.md'):
            self.assertIn('U-19', read(MEMBER / name), name)

    def test_run_by_one_person_is_not_claimed(self):
        for name in DRAFTS:
            text = body(read(MEMBER / name))
            self.assertNotRegex(text, r'(?i)run by (?:one|a single) person|one[- ]person', name)

    def test_no_server_load_claim_in_core(self):
        for name in DRAFTS:
            self.assertNotRegex(core(read(MEMBER / name)), r'(?i)easier on the server|server load', name)

    def test_neutral_core_does_not_hint_at_other_services(self):
        hints = re.compile(r'(?i)one service|another (?:one|service)|other services?|any service|'
                           r'each service|every service|holds its own copy|their own way|'
                           r'a different service|some services')
        for name in DRAFTS:
            m = hints.search(core(read(MEMBER / name)))
            self.assertIsNone(m, f'{name}: neutral core implies other services: {m.group(0) if m else ""}')

    def test_register_d14_states_both_gating_options(self):
        text = read(REGISTER)
        section = text.split('### D-14', 1)[1].split('\n### ', 1)[0]
        self.assertIn('on `main`', section)
        self.assertIn('PR #4', section)
        self.assertIn('avrana-requests', section)
        self.assertIn('avrana-videos', section)
        self.assertRegex(section, r'(?i)not decided|owner has not decided')

    def test_help_requests_block_follows_the_pinned_group(self):
        """The Requests help block and the portal on main agree today; the pin makes any change deliberate."""
        portal = portal_text()
        m = re.search(r'\(\s*"(avrana-[a-z]+)",\s*"Requests"', portal)
        self.assertIsNotNone(m)
        self.assertEqual('avrana-requests', m.group(1),
                         'the portal changed which group gates the Requests help topic: update D-14, the '
                         'help.md block and BLOCK_GROUPS together')

    def test_help_recommended_sentence_matches_the_portal(self):
        help_text = body(read(MEMBER / 'help.md'))
        self.assertNotRegex(help_text, r'(?i)marks one app as recommended for each device')
        self.assertRegex(help_text, r'(?i)more than one app')
        self.assertIn('len(clients) > 1', portal_text())

    def test_no_email_addresses_anywhere(self):
        for path in FIVE_DOCS:
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
        for path in FIVE_DOCS:
            for target in link.findall(COMMENT.sub('', read(path))):
                if re.match(r'[a-z]+:', target) or target.startswith('#'):
                    continue
                dest = (path.parent / target.split('#', 1)[0]).resolve()
                self.assertTrue(dest.exists(), f'{path.name}: broken link {target}')

    def test_cited_sources_exist(self):
        for path in FIVE_DOCS:
            text = read(path)
            cited = SOURCE_PATH.findall(text)
            self.assertTrue(cited, path.name)
            for rel in set(cited):
                self.assertTrue((ROOT / rel).is_file(), f'{path.name}: cited path missing: {rel}')

    def test_cited_lines_exist_and_are_not_blank(self):
        """Every path:line citation: the file exists, each line number is inside it and not blank.

        A range must lie inside the file and contain at least one non-blank line. A bare file name
        (portal.py:627) is resolved against the files of that name under docs, services, scripts, deploy
        and tests; it passes when at least one of them satisfies the citation. LIMIT: this proves the line
        exists, not that it says what the sentence claims; PINNED_CITES covers the ones that matter most.
        """
        index = repo_index()
        checked = 0
        for path in FIVE_DOCS:
            text = COMMENT.sub(lambda m: m.group(0), read(path))
            for cited, spans in citations(text):
                if '/' in cited:
                    candidates = [ROOT / cited]
                else:
                    candidates = index.get(cited, [])
                self.assertTrue(candidates, f'{path.name}: cited file not found: {cited}')
                for start, end in spans:
                    ok = any(c.is_file() and span_ok(lines_of(c), start, end) for c in candidates)
                    self.assertTrue(ok, f'{path.name}: bad citation {cited}:{start}-{end}')
                    checked += 1
        self.assertGreater(checked, 200)

    def test_pinned_citations_hold(self):
        for doc, literal, rel, line, needle in PINNED_CITES:
            self.assertTrue(literal in read(doc), f'{doc.name}: citation {literal} was changed or removed')
            lines = lines_of(ROOT / rel)
            self.assertLessEqual(line, len(lines), rel)
            self.assertIn(needle, lines[line - 1], f'{rel}:{line} no longer holds {needle!r}')

    def test_citation_checker_rejects_bad_lines(self):
        lines = ['a', '', 'c']
        self.assertTrue(span_ok(lines, 1, 1))
        self.assertTrue(span_ok(lines, 1, 3))
        self.assertFalse(span_ok(lines, 2, 2), 'blank line')
        self.assertFalse(span_ok(lines, 4, 4), 'past the end')
        self.assertFalse(span_ok(lines, 3, 2), 'reversed')
        self.assertEqual([('docs/a.md', [(5, 6), (9, 9)])],
                         list(citations('see `docs/a.md:5-6, :9` here')))

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

    def test_group_names_are_exactly_member_groups(self):
        """Every if: group is one of the real member groups, and the set agrees with the portal."""
        self.assertTrue(MEMBER_GROUPS <= portal_groups(), sorted(MEMBER_GROUPS - portal_groups()))
        self.assertFalse(MEMBER_GROUPS & {'authentik Admins', 'avrana-users'})
        for name in DRAFTS:
            for m in IF_MARK.finditer(read(MEMBER / name)):
                for g in (x.strip() for x in m.group(1).split('|')):
                    self.assertIn(g, MEMBER_GROUPS, f'{name}: {g!r} is not a member-facing group name')

    def test_topic_to_group_table_matches_documents(self):
        for name in DRAFTS:
            actual = []
            for m in BLOCK.finditer(read(MEMBER / name)):
                inner = COMMENT.sub('', m.group(2)).strip()
                lab = re.search(r'^#{2,4} (.+)$|^\W*\*\*([^*]+?)[.:]\*\*', inner, re.M)
                self.assertIsNotNone(lab, f'{name}: block without a heading or bold label: {inner[:50]!r}')
                label = lab.group(1) or lab.group(2)
                actual.append((label, tuple(g.strip() for g in m.group(1).split('|'))))
            self.assertEqual(BLOCK_GROUPS[name], actual,
                             f'{name}: a topic moved to a different group, or a block was added or removed. '
                             f'If intended (for example after decision D-14), update BLOCK_GROUPS.')

    def test_neutral_core_names_no_library(self):
        terms = re.compile(
            r'(?i)jellyfin|swiftfin|wholphin|audiobookshelf|audiobooth|absorb|komga|calibre|seerr|'
            r'shelfarr|omnibus|kindle|audible|audiobook|comic|manga|movie|film|ebook|\bTV\b|amazon|'
            r'television|panels|moon\+')
        for name in DRAFTS:
            m = terms.search(core(read(MEMBER / name)))
            self.assertIsNone(m, f'{name}: library term in neutral core: {m.group(0) if m else ""}')

    def test_neutral_core_vocabulary_derived_from_the_portal(self):
        """No device, app, service or tile name from the portal's tables may appear outside a block.

        The list is read from services/avrana-portal/portal.py (SERVICES, CHOOSERS, HELP), not from the
        documents. Names are matched as whole words, case-sensitively for tile names so that the ordinary
        verbs watch, listen, read and request stay usable but "Watch", "Listen", "Read" and "Request" as
        tile names do not. LIMIT: a product the portal does not list is not known to this check.
        """
        vocab = portal_vocabulary()
        for expected in ('Roku', 'Jellyfin', 'Audiobookshelf', 'Kindle', 'Watch', 'Listen',
                         'Read', 'Request', 'Swiftfin', 'Apple TV', 'Fire TV', 'Books', 'Comics'):
            self.assertIn(expected, vocab)
        for name in DRAFTS:
            text = core(read(MEMBER / name))
            for term in sorted(vocab):
                m = re.search(r'(?<![\w+])' + re.escape(term) + r'(?![\w+])', text)
                self.assertIsNone(m, f'{name}: {term!r} in neutral core')

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

    def test_runbook_forbids_yes_flag(self):
        text = read(RUNBOOK)
        self.assertRegex(text, r'do not use `--yes`')
        for m in re.finditer(r'`--yes`', text):
            before = text[max(0, m.start() - 40):m.start()].lower()
            self.assertTrue(('do not use' in before) or ('skips that prompt' in text[max(0, m.start() - 60):m.start() + 60]),
                            f'`--yes` mentioned without a prohibition: {before!r}')
        self.assertNotRegex(text, r'(?i)(?<!do not )use `--yes`')

    def test_runbook_has_no_secrets_or_dashes(self):
        text = read(RUNBOOK)
        self.assertNotRegex(text, r'\b[A-Za-z0-9_\-]{40,}\b')
        self.assertNotIn('-----BEGIN', text)
        self.assertNotIn('\u2014', text)
        self.assertNotIn('\u2013', text)

    # --- runbook content tied to the tool's actual behaviour -----------------------------------

    def packet(self):
        m = re.search(r'(?ms)^## Packet\n(.*?)(?=^## )', read(RUNBOOK))
        self.assertIsNotNone(m, 'runbook has no "## Packet" section')
        return m.group(1)

    def test_runbook_has_the_eight_field_packet(self):
        expected = ['Approval requested', 'Why it is needed and what it unblocks', 'Blast radius and downtime',
                    'Preconditions', 'Verification', 'Rollback', 'Evidence to record', 'Unverified assumptions']
        parts = re.split(r'(?m)^(\d)\. \*\*(.+?)\.\*\*', self.packet())
        found = [(parts[i], parts[i + 1], parts[i + 2]) for i in range(1, len(parts) - 2, 3)]
        self.assertEqual([str(n) for n in range(1, 9)], [n for n, _, _ in found])
        for (number, label, text), want in zip(found, expected):
            self.assertTrue(label.startswith(want), f'field {number}: {label!r}')
            self.assertGreater(len(re.sub(r'\s+', ' ', text).strip()), 40, f'field {number} is empty')
        flat = re.sub(r'\s+', ' ', self.packet())
        self.assertRegex(flat, r'no rollback for a purge')
        self.assertIn('cannot be undone', flat)
        self.assertRegex(flat, r'(?i)yes or no')

    def test_runbook_verify_section_matches_the_tool(self):
        text = read(RUNBOOK)
        verify = text.split('\n## Verify\n', 1)[1].split('\n## ', 1)[0]
        flat = re.sub(r'\s+', ' ', verify)
        self.assertIn('prints no disabled or active flag', flat)
        self.assertIn('UNMATCHED', verify)
        self.assertIn('PASS  authentik/<user> no longer exists', verify)
        self.assertRegex(flat, r'(?i)Authentik admin UI')
        for service in ('Jellyfin dashboard', 'Audiobookshelf, Settings, Users', 'Seerr, Users'):
            self.assertIn(service, verify)
        # The tool itself, as text: the audit must still lack a disabled flag for the three services,
        # and verify() must still read Authentik through a helper that drops the exit code and stderr.
        src = read(OFFBOARD)
        audit = src.split('def audit():', 1)[1].split('\nif __name__', 1)[0]
        self.assertNotIn('IsDisabled', audit)
        self.assertNotIn('isActive', audit)
        self.assertIn('active=', audit)
        self.assertIn('capture_output=True, text=True).stdout', src)
        self.assertNotIn('returncode', src)
        verify_src = src.split('def verify(', 1)[1].split('\ndef main', 1)[0]
        self.assertNotIn('matches["abs"]', verify_src)
        self.assertNotIn('matches["seerr"]', verify_src)
        self.assertNotIn('ABS', verify_src)
        self.assertNotIn('SEERR', verify_src)

    def test_runbook_unsafe_interpolation_lines_are_exact(self):
        lines = lines_of(OFFBOARD)
        self.assertIn("lower('{username}')", lines[100])   # line 101
        self.assertIn("lower('{u}')", lines[203])          # line 204
        self.assertIn('{u!r}', lines[195])                 # line 196
        self.assertIn('shlex.quote', lines[198])           # line 199
        text = read(RUNBOOK)
        pre = text.split('## Step 1', 1)[0]
        self.assertIn('[A-Za-z0-9._-]+', pre)
        self.assertRegex(pre, r'(?i)refuse any other username')
        self.assertIn('line 101', pre)
        self.assertIn('line 204', pre)
        self.assertIn('shlex.quote', pre)
        self.assertNotRegex(pre, r'196-204')

    def test_runbook_principle_four_names_its_exception(self):
        text = read(RUNBOOK)
        principles = text.split('## Principles', 1)[1].split('\n## ', 1)[0]
        item4 = re.search(r'(?s)\n4\. (.*?)\n5\. ', principles).group(1)
        self.assertIn('Step 4 item 6', item4)
        self.assertRegex(item4, r'(?i)production change')
        self.assertIn('irreversible', item4.lower())
        self.assertIn('exception', item4.lower())
        self.assertIn('profiles/<profile_id>', item4)

    def test_runbook_warns_about_seerr_sessions(self):
        text = re.sub(r'\s+', ' ', read(RUNBOOK))
        self.assertIn('REASONED', text)
        self.assertIn('U-20', text)
        self.assertRegex(text, r'(?i)open Seerr session may keep working')

    def test_runbook_manual_steps_are_tagged(self):
        """Step 4: every manual item carries a status word, and the ungrounded ones carry UNGROUNDED."""
        step4 = read(RUNBOOK).split('## Step 4.', 1)[1].split('\n## ', 1)[0]
        items = re.split(r'(?m)^(\d)\. \*\*', step4)
        found = {int(items[i]): items[i + 1] for i in range(1, len(items) - 1, 2)}
        self.assertEqual(list(range(1, 10)), sorted(found))
        for number, text in found.items():
            self.assertRegex(text, r'Grounded|UNGROUNDED|UNVERIFIED', f'Step 4 item {number} has no status')
        for number in (2, 3, 4, 5, 6, 8):
            self.assertIn('UNGROUNDED', found[number], f'Step 4 item {number} lost its UNGROUNDED tag')


if __name__ == '__main__':
    unittest.main()
