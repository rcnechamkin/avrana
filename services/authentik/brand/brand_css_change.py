#!/usr/bin/env python3
"""Owner-run, on host avrana: back up, apply, verify and roll back the AVRANA Brand v1.0.0 Authentik CSS.

Nothing runs against production unless the owner runs it. Each step needs the owner's approval for that step
(AGENTS.md). The order is fixed:

    python3 brand_css_change.py backup                         # read-only; prints BACKUP_DIR
    python3 brand_css_change.py apply BACKUP_DIR NEW.yaml --expect-sha256 HEX
    python3 brand_css_change.py verify BACKUP_DIR              # read-only, any time after apply
    python3 brand_css_change.py rollback BACKUP_DIR            # restores the exact pre-change record

How the change lands. Brand.branding_custom_css is declared in the avrana-landing.yaml blueprint, and the
worker re-applies a blueprint when its file changes (authentik/blueprints/v1/tasks.py:99-108, and hourly when
its hash differs, tasks.py:185). So apply writes the reviewed blueprint over the production copy, in place
(the watcher listens for created and modified events only, tasks.py:63-66), waits for that instance's
last_applied_hash to equal the file's SHA-512, then checks the database value and the CSS Authentik serves.

Rollback writes the backed-up blueprint back, waits for that apply, then, if the database value still differs
from the backed-up one (the 2026-08-21 wordmark rules were a database-only edit on top of the blueprint), writes
the backed-up bytes back exactly. Stops on anything unexpected. Never prints CSS or record contents, only sizes
and hashes. No restart, no compose, no proxy change.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROD_BLUEPRINT = Path('/home/cody/avrana/services/authentik/blueprints/avrana-landing.yaml')
BACKUP_ROOT = Path('/mnt/avrana_media/.backups')
INSTANCE_PATH = 'avrana/avrana-landing.yaml'          # relative to /blueprints in the worker
BRAND_DOMAIN = 'authentik-default'
FLOW_URL = 'https://auth.avrana.net/if/flow/default-authentication-flow/'
PG_CONTAINER = 'authentik-postgresql'
# Git main's avrana-landing.yaml (b934931), imported from the live tree. A different production file is drift:
# stop and run scripts/drift-check.py first.
EXPECTED_PRE_BLUEPRINT_SHA256 = '87b08d4b34df8dbab6aa79ee72b519adf350cde81d645bf235b6ce52ef803200'
WAIT_SECONDS = 180
# django.utils.html._json_script_escapes, applied to the CSS before it is served (authentik/brands/utils.py:63)
SERVED_ESCAPES = {ord('>'): '\\u003E', ord('<'): '\\u003C', ord('&'): '\\u0026'}
BRAND_CSS_BLOCK = re.compile(r'<style data-id="brand-css">(.*?)</style>', re.S)


class Stop(Exception):
    """Something unexpected: nothing further is done."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Host:
    """The only place that touches the host. Tests replace it."""

    def __init__(self, pg_container: str = PG_CONTAINER):
        self.pg = pg_container

    def psql(self, script: str) -> str:
        cmd = ['docker', 'exec', '-i', self.pg, 'psql', '-X', '-U', 'authentik', '-d', 'authentik',
               '-v', 'ON_ERROR_STOP=1', '-A', '-t']
        done = subprocess.run(cmd, input=script, capture_output=True, text=True, check=False)
        if done.returncode:
            raise Stop(f'psql exited {done.returncode} (stderr not shown; it may echo SQL)')
        return done.stdout

    def read(self, path: Path) -> bytes:
        return path.read_bytes()

    def write_in_place(self, path: Path, data: bytes) -> None:
        # Same inode, one write, then trim: the watcher sees modifications, never a rename. An apply that reads
        # a half-written file is superseded by the apply of the final event; wait_applied accepts only the
        # full file's hash, which the worker records only on success (tasks.py:206-223).
        with open(path, 'r+b') as f:
            f.write(data)
            f.truncate(len(data))
            f.flush()
            os.fsync(f.fileno())

    def save(self, path: Path, data: bytes) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)

    def mkdir(self, path: Path) -> None:
        path.mkdir(mode=0o700)

    def fetch(self, url: str) -> str:
        req = urllib.request.Request(url, headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode('utf-8')

    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


# --- reads -----------------------------------------------------------------------------------------------

def brand_domains(host: Host) -> list[tuple[str, bool]]:
    out = host.psql('SELECT domain || \'|\' || "default"::text FROM authentik_brands_brand ORDER BY domain;\n')
    rows = [line.rsplit('|', 1) for line in out.splitlines() if line]
    return [(d, flag == 'true') for d, flag in rows]


def db_css(host: Host) -> bytes:
    out = host.psql("SELECT translate(encode(convert_to(branding_custom_css, 'UTF8'), 'base64'), E'\\n', '') "
                    f"FROM authentik_brands_brand WHERE domain = '{BRAND_DOMAIN}';\n")
    lines = [line for line in out.splitlines() if line]
    if len(lines) != 1:
        raise Stop(f'expected one brand {BRAND_DOMAIN!r}, found {len(lines)}')
    return base64.b64decode(lines[0], validate=True)


def brand_record(host: Host) -> bytes:
    out = host.psql(f"SELECT row_to_json(b)::text FROM authentik_brands_brand b WHERE domain = '{BRAND_DOMAIN}';\n")
    lines = [line for line in out.splitlines() if line]
    if len(lines) != 1:
        raise Stop(f'expected one brand {BRAND_DOMAIN!r}, found {len(lines)}')
    json.loads(lines[0])
    return (lines[0] + '\n').encode('utf-8')


def instance(host: Host) -> dict:
    out = host.psql("SELECT last_applied_hash || '|' || status || '|' || enabled::text || '|' || "
                    "to_char(last_applied AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS') "
                    f"FROM authentik_blueprints_blueprintinstance WHERE path = '{INSTANCE_PATH}';\n")
    lines = [line for line in out.splitlines() if line]
    if len(lines) != 1:
        raise Stop(f'expected one blueprint instance for {INSTANCE_PATH}, found {len(lines)}')
    h, status, enabled, applied = lines[0].split('|')
    return {'last_applied_hash': h, 'status': status, 'enabled': enabled == 'true', 'last_applied': applied}


def served_css(host: Host, url: str) -> str:
    found = BRAND_CSS_BLOCK.findall(host.fetch(url))
    if len(found) != 1:
        raise Stop(f'expected one brand-css block at {url}, found {len(found)}')
    return found[0]


def as_served(css: bytes) -> str:
    return css.decode('utf-8').translate(SERVED_ESCAPES)


# --- steps -----------------------------------------------------------------------------------------------

def backup(host: Host, args) -> Path:
    stamp = host.now().strftime('%Y%m%dT%H%M%SZ')
    out = args.backup_root / f'authentik-branding-{stamp}'
    domains = brand_domains(host)
    others = [d for d, _ in domains if d != BRAND_DOMAIN and not d.startswith('fallback')]
    defaults = [d for d, flag in domains if flag]
    css = db_css(host)
    record = brand_record(host)
    blueprint = host.read(args.prod_blueprint)
    inst = instance(host)
    served = served_css(host, args.url)
    host.mkdir(out)
    host.save(out / 'branding.PRE.json', record)
    host.save(out / 'branding_custom_css.PRE.css', css)
    host.save(out / 'avrana-landing.PRE.yaml', blueprint)
    manifest = {
        'taken_utc': stamp,
        'brand_domains': domains,
        'branding_custom_css': {'bytes': len(css), 'sha256': sha256(css)},
        'served_matches_db': served == as_served(css),
        'blueprint': {'path': str(args.prod_blueprint), 'bytes': len(blueprint), 'sha256': sha256(blueprint),
                      'sha512': hashlib.sha512(blueprint).hexdigest(),
                      'matches_git_main': sha256(blueprint) == EXPECTED_PRE_BLUEPRINT_SHA256},
        'blueprint_instance': inst,
        'record_sha256': sha256(record),
    }
    host.save(out / 'MANIFEST.json', (json.dumps(manifest, indent=1, sort_keys=True) + '\n').encode())
    print(f'BACKUP_DIR={out}')
    print(f"live CSS {len(css)} B sha256 {sha256(css)}; served matches database: {manifest['served_matches_db']}")
    print(f"production blueprint sha256 {sha256(blueprint)} (Git main: {manifest['blueprint']['matches_git_main']}); "
          f"instance status {inst['status']}, enabled {inst['enabled']}")
    if others or defaults != [BRAND_DOMAIN]:
        print(f'WARN brands present: {domains}. Another brand may serve auth.avrana.net; apply will refuse.')
    return out


def load_backup(host: Host, out: Path) -> dict:
    manifest = json.loads(host.read(out / 'MANIFEST.json'))
    css = host.read(out / 'branding_custom_css.PRE.css')
    blueprint = host.read(out / 'avrana-landing.PRE.yaml')
    if sha256(css) != manifest['branding_custom_css']['sha256'] or sha256(blueprint) != manifest['blueprint']['sha256']:
        raise Stop('backup files do not match their MANIFEST.json')
    return {'manifest': manifest, 'css': css, 'blueprint': blueprint}


def wait_applied(host: Host, blueprint: bytes, since: str) -> dict:
    want = hashlib.sha512(blueprint).hexdigest()
    waited = 0
    while waited <= WAIT_SECONDS:
        inst = instance(host)
        if inst['last_applied_hash'] == want and inst['last_applied'] >= since:
            if inst['status'] != 'successful':
                raise Stop(f"blueprint applied with status {inst['status']}; check the worker log")
            return inst
        host.sleep(5)
        waited += 5
    raise Stop(f'the worker did not apply the blueprint within {WAIT_SECONDS}s. Do not retry blindly: check '
               '`docker logs authentik-worker`; the hourly discovery will also apply it (hash changed)')


def apply(host: Host, args) -> None:
    pre = load_backup(host, args.backup_dir)
    m = pre['manifest']
    if [d for d, flag in m['brand_domains'] if flag] != [BRAND_DOMAIN] or any(
            d != BRAND_DOMAIN and not d.startswith('fallback') for d, _ in m['brand_domains']):
        raise Stop(f"brand set is not just {BRAND_DOMAIN}: {m['brand_domains']}")
    if not m['blueprint']['matches_git_main']:
        raise Stop('the production blueprint is not Git main\'s; reconcile drift (scripts/drift-check.py) first')
    if not m['blueprint_instance']['enabled']:
        raise Stop('the blueprint instance is disabled; the file change would not apply')
    new = host.read(args.new_blueprint)
    if sha256(new) != args.expect_sha256.lower():
        raise Stop(f'{args.new_blueprint} sha256 {sha256(new)} is not the reviewed {args.expect_sha256}')
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_brand_css import blueprint_css            # the same parser the build and tests use
    want_css = blueprint_css(new.decode('utf-8')).encode('utf-8')
    if sha256(db_css(host)) != m['branding_custom_css']['sha256'] or sha256(host.read(args.prod_blueprint)) != m['blueprint']['sha256']:
        raise Stop('the live brand CSS or blueprint changed since the backup; take a new backup')
    since = host.now().strftime('%Y-%m-%dT%H:%M:%S')
    host.write_in_place(args.prod_blueprint, new)
    print(f'wrote {args.prod_blueprint} ({len(new)} B); waiting for the worker to apply it')
    wait_applied(host, new, since)
    report(host, args.url, want_css, 'new')


def report(host: Host, url: str, want_css: bytes, label: str) -> None:
    got = db_css(host)
    if got != want_css:
        raise Stop(f'database CSS sha256 {sha256(got)} is not the {label} {sha256(want_css)}: run rollback')
    served = served_css(host, url)
    if served != as_served(want_css):
        raise Stop(f'{url} serves CSS sha256 {sha256(served.encode())}, not the {label} CSS: run rollback')
    print(f'OK database and {url} carry the {label} CSS ({len(want_css)} B, sha256 {sha256(want_css)})')


def verify(host: Host, args) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_brand_css import blueprint_css
    live = host.read(args.prod_blueprint)
    report(host, args.url, blueprint_css(live.decode('utf-8')).encode('utf-8'), 'production blueprint')


def rollback(host: Host, args) -> None:
    pre = load_backup(host, args.backup_dir)
    since = host.now().strftime('%Y-%m-%dT%H:%M:%S')
    if host.read(args.prod_blueprint) != pre['blueprint']:
        host.write_in_place(args.prod_blueprint, pre['blueprint'])
        print(f'restored {args.prod_blueprint}; waiting for the worker to apply it')
        wait_applied(host, pre['blueprint'], since)
    if db_css(host) != pre['css']:
        b64 = base64.b64encode(pre['css']).decode('ascii')
        out = host.psql(f"\\set css_b64 '{b64}'\n"
                        "UPDATE authentik_brands_brand SET branding_custom_css = "
                        f"convert_from(decode(:'css_b64', 'base64'), 'UTF8') WHERE domain = '{BRAND_DOMAIN}';\n")
        if 'UPDATE 1' not in out:
            raise Stop('the database restore did not update exactly one brand')
        print('restored the backed-up branding_custom_css bytes in the database')
    report(host, args.url, pre['css'], 'backed-up')


def main(argv=None, host: Host | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--prod-blueprint', type=Path, default=PROD_BLUEPRINT)
    ap.add_argument('--url', default=FLOW_URL)
    sub = ap.add_subparsers(dest='step', required=True)
    b = sub.add_parser('backup')
    b.add_argument('--backup-root', type=Path, default=BACKUP_ROOT)
    a = sub.add_parser('apply')
    a.add_argument('backup_dir', type=Path)
    a.add_argument('new_blueprint', type=Path)
    a.add_argument('--expect-sha256', required=True)
    v = sub.add_parser('verify')
    v.add_argument('backup_dir', type=Path)
    r = sub.add_parser('rollback')
    r.add_argument('backup_dir', type=Path)
    args = ap.parse_args(argv)
    host = host or Host()
    try:
        {'backup': backup, 'apply': apply, 'verify': verify, 'rollback': rollback}[args.step](host, args)
    except Stop as e:
        print(f'STOP {e}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
