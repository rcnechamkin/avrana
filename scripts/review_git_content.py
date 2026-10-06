#!/usr/bin/env python3
"""Review indexed blobs without executing source or printing matching secrets.

This gate is deliberately conservative and complements human diff review. It
cannot detect all secrets or personal information. It has no production access.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import PurePosixPath

MAX_BYTES = 1024 * 1024
BLOCKED_PARTS = {
    '.git', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache',
    'secrets', 'kern_secrets', 'filing_cabinet', 'blackboxes', 'backups',
    'media', 'logs', 'runtime', 'appdata', 'pgdata', 'redisdata', 'profiles',
}
BLOCKED_SUFFIXES = (
    '.db', '.sqlite', '.sqlite3', '.dump', '.pgdump', '.log', '.pyc', '.pyo',
    '.zip', '.tar', '.gz', '.zst', '.deb', '.pem', '.key', '.p12', '.pfx',
    '.mp4', '.mkv', '.m4b', '.mp3', '.epub', '.jpg', '.jpeg', '.png', '.webp',
)
PATTERNS = {
    'private key': re.compile(r'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----'),
    'GitHub credential': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b'),
    'AWS access key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'JWT-shaped value': re.compile(r'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b'),
    'credential in URL': re.compile(r'https?://[^\s/]+:[^\s/@]+@'),
    'literal credential assignment': re.compile(
        r'''(?im)^\s*(?:-\s+)?(?:[A-Za-z0-9_]*(?:password|api_key|token_secret|client_secret|session_key|secret_key))[ \t]*[:=][ \t]*["']?([A-Za-z0-9+/=_-]{16,})["']?[ \t]*[,;]?[ \t]*$'''),
    # a %s on either side is a !Format placeholder (Authentik blueprints), not a credential
    'basic-auth literal': re.compile(r'''b64encode\(\s*b?["'][^"'<%]*:[^"'<%]+["']'''),
}
# Values that are obviously placeholders, not credentials (generate-with-openssl-..., CHANGE_ME).
PLACEHOLDER = re.compile(r'^(?:generate-|change[-_]?me|example|placeholder|test[-_]|dummy|[A-Z0-9_]+_NOT_SET$)', re.I)
# First-party paths whose names collide with blocked state-directory names.
ALLOWED_PREFIXES = ('services/backups/', 'services/media/', 'docs/archive/')
# Third-party or retiring trees: only these files are tracked.
RESTRICTED_TREES = {
    'services/bookstack/': {'docker-compose.yml', '.env.example'},
    'services/mylar3/': set(),
}
ARCHIVE_IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.png', '.webp')


def review_blob(path: str, mode: str, data: bytes) -> list[str]:
    issues = []
    p = PurePosixPath(path)
    if mode not in {'100644', '100755'}:
        issues.append('symlink, submodule or non-regular mode')
    allowed = path.startswith(ALLOWED_PREFIXES)
    if p.is_absolute() or '..' in p.parts or (not allowed and any(x in BLOCKED_PARTS for x in p.parts)):
        issues.append('excluded path')
    for tree, tracked in RESTRICTED_TREES.items():
        if path.startswith(tree) and path[len(tree):] not in tracked:
            issues.append('excluded production/third-party tree')
    is_env = p.name.startswith('.env') or p.name.endswith('.env')
    if (is_env and not p.name.endswith('.env.example')) or p.name == 'settings.local.json':
        issues.append('secret-bearing local configuration')
    low = p.name.lower()
    archive_image = path.startswith('docs/archive/') and low.endswith(ARCHIVE_IMAGE_SUFFIXES)
    if archive_image:
        if len(data) > 5 * MAX_BYTES:
            issues.append('archived image exceeds 5 MiB')
        return issues                      # binary by nature; nothing textual to scan
    if low.endswith(BLOCKED_SUFFIXES) or re.search(r'\.(?:db|sqlite3?)-(?:wal|shm|journal)$|\.log\.', low):
        issues.append('runtime, binary, archive or secret file type')
    if low.endswith('.sql') and 'migrations' not in p.parts:
        issues.append('SQL outside reviewed migration source')
    if len(data) > MAX_BYTES:
        issues.append('file exceeds 1 MiB review limit')
    if b'\0' in data:
        issues.append('binary NUL byte')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        issues.append('non-UTF-8 content')
        return issues
    for label, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            if match.groups() and PLACEHOLDER.match(match.group(1)):
                continue
            issues.append(label)
            break
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--staged', action='store_true', required=True,
                    help='review all indexed file blobs, including staged changes')
    ap.parse_args()
    raw = subprocess.check_output(['git', 'ls-files', '--stage', '-z'])
    if not raw:
        print('FAIL: index is empty; nothing was reviewed')
        return 1
    problems = 0
    count = 0
    for record in raw.split(b'\0'):
        if not record:
            continue
        meta, raw_path = record.split(b'\t', 1)
        mode, oid, stage = meta.decode('ascii').split()
        path = raw_path.decode('utf-8')
        if stage != '0':
            print(f'FAIL {path}: unresolved index stage')
            problems += 1
            continue
        # Read indexed content, not a potentially different working-tree file.
        data = subprocess.check_output(['git', 'cat-file', 'blob', oid])
        issues = review_blob(path, mode, data)
        for issue in issues:
            print(f'FAIL {path}: {issue}')
        problems += bool(issues)
        count += 1
    print(f'Reviewed {count} indexed files; {problems} blocked files. Manual privacy/diff review still required.')
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
