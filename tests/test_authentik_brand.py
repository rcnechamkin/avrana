"""AVRANA Brand v1.0.0 Authentik CSS: the generated files agree, the logo is the package's bytes, and the owner's
backup/apply/rollback tool restores the exact pre-change record. Offline: a fake host stands in for Docker,
Postgres, the blueprint watcher and auth.avrana.net."""
import base64
import contextlib
import datetime as dt
import hashlib
import io
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / 'services/authentik/brand'
sys.path.insert(0, str(BRAND))

import build_brand_css as build  # noqa: E402
import brand_css_change as change  # noqa: E402

CSS = (BRAND / 'avrana-brand-v1.css').read_text(encoding='utf-8')
PALETTE = {'#121214', '#edeae4', '#aeaba7', '#8f8c89', '#5e5b57', '#6e6c72', '#161618', '#1e1e21', '#ff8b8b'}


class GeneratedCss(unittest.TestCase):
    def test_build_outputs_agree(self):
        self.assertEqual(build.check_offline(CSS), [])

    def test_wordmark_is_the_pinned_package_file(self):
        found = build.embedded(CSS)
        pin = build.sources()['wordmark_cream']
        self.assertEqual(hashlib.sha256(found['image/svg+xml']).hexdigest(), pin['sha256'])
        self.assertEqual(len(found['image/svg+xml']), pin['bytes'])
        self.assertEqual(CSS.count('data:image/svg+xml'), 1, 'one copy, shared through --avr-wordmark')

    def test_geist_not_embedded_by_default(self):
        self.assertNotIn('font/woff2', build.embedded(CSS))
        self.assertFalse(build.sources()['geist_variable']['embedded'])

    def test_survives_authentik_escaping(self):
        for ch in '<>&\r':
            self.assertNotIn(ch, CSS)
        self.assertEqual(change.as_served(CSS.encode()), CSS)

    def test_no_retyped_wordmark_and_no_mono_ui_face(self):
        self.assertNotIn('content: "AVRANA"', CSS)
        self.assertNotIn('Times New Roman', CSS)
        mono = re.search(r'--ak-font-family-monospace: ([^;]+);', CSS).group(1)
        self.assertTrue(mono.startswith('ui-monospace'))
        ui = re.search(r'textarea \{\n  font-family: ([^;]+);', CSS).group(1)
        self.assertTrue(ui.startswith('"Geist", system-ui'), ui)

    def test_colours_are_brand_tokens(self):
        used = {c.lower() for c in re.findall(r'#[0-9a-fA-F]{6}\b', CSS)}
        self.assertLessEqual(used, PALETTE, used - PALETTE)
        self.assertNotIn('#b9a9e8', used, 'Atomic Purple is Party only')

    def test_logo_is_not_set_through_branding_logo(self):
        text = (ROOT / 'services/authentik/blueprints/avrana-landing.yaml').read_text(encoding='utf-8')
        self.assertNotRegex(text, r'(?m)^\s+branding_(logo|favicon):', 'the logo and favicon fields stay as they are')

    def test_blueprint_keeps_its_other_entries(self):
        text = (ROOT / 'services/authentik/blueprints/avrana-landing.yaml').read_text(encoding='utf-8')
        self.assertEqual(text.count('\n  - model: '), 5)
        for needle in ('domain: authentik-default', 'branding_title: Avrana', 'base: dark',
                       'slug: jellyfin', 'slug: seerr'):
            self.assertIn(needle, text)


OLD_CSS = ':root { --ak-font-family-sans-serif: "Times New Roman", Times, serif; }\n\na,\nb {\n  color: #fff;\n}\n'
WORDMARK_EDIT = '.pf-c-brand::after { content: "AVRANA"; }\n.x > .y { color: #fff; }\n'


def blueprint(css: str) -> bytes:
    body = ''.join(('        ' + line if line else '') + '\n' for line in css.rstrip('\n').split('\n'))
    return ('version: 1\nentries:\n  - model: authentik_brands.brand\n    identifiers:\n      domain: authentik-default\n'
            '    attrs:\n      branding_custom_css: |\n' + body + '\n  - model: authentik_core.application\n'
            '    attrs:\n      name: x\n').encode()


class FakeHost:
    """Postgres rows, the blueprint watcher and the served page, as the real ones behave."""

    def __init__(self, live_css: bytes, prod: Path, watcher_works=True, apply_status='successful'):
        self.files = {}
        self.css = live_css
        self.prod = prod
        self.inst = {'hash': 'old', 'status': 'successful', 'enabled': 'true', 'applied': '2026-08-21T20:16:29'}
        self.clock = dt.datetime(2026, 10, 20, 12, 0, 0, tzinfo=dt.timezone.utc)
        self.watcher_works = watcher_works
        self.apply_status = apply_status
        self.writes = []

    # Host interface
    def psql(self, script):
        if script.startswith('\\set css_b64'):
            b64 = re.match(r"\\set css_b64 '([A-Za-z0-9+/=]*)'", script).group(1)
            self.css = base64.b64decode(b64)
            return 'UPDATE 1\n'
        if 'FROM authentik_brands_brand ORDER BY domain' in script:
            return 'authentik-default|true\n'
        if 'encode(convert_to(branding_custom_css' in script:
            return base64.encodebytes(self.css).decode().replace('\n', '') + '\n'
        if 'row_to_json' in script:
            return json.dumps({'domain': 'authentik-default', 'branding_custom_css': self.css.decode()}) + '\n'
        if 'authentik_blueprints_blueprintinstance' in script:
            i = self.inst
            return f"{i['hash']}|{i['status']}|{i['enabled']}|{i['applied']}\n"
        raise AssertionError(f'unexpected SQL: {script[:60]}')

    def read(self, path):
        return self.files[Path(path)]

    def write_in_place(self, path, data):
        self.writes.append(Path(path))
        self.files[Path(path)] = data
        if Path(path) == self.prod and self.watcher_works:          # tasks.py:99-108, 206-223
            self.tick()
            if self.apply_status == 'successful':
                self.css = build.blueprint_css(data.decode()).encode()
                self.inst['hash'] = hashlib.sha512(data).hexdigest()
                self.inst['applied'] = self.clock.strftime('%Y-%m-%dT%H:%M:%S')
            self.inst['status'] = self.apply_status

    def save(self, path, data):
        assert Path(path) not in self.files
        self.files[Path(path)] = data

    def mkdir(self, path):
        pass

    def fetch(self, url):
        return f'<html><head><style data-id="brand-css">{self.css.decode().translate(change.SERVED_ESCAPES)}</style>'

    def now(self):
        return self.clock

    def sleep(self, seconds):
        self.tick(seconds)

    def tick(self, seconds=1):
        self.clock += dt.timedelta(seconds=seconds)


class ApplyAndRollback(unittest.TestCase):
    PROD = Path('/prod/avrana-landing.yaml')
    NEW = Path('/git/avrana-landing.yaml')

    def setUp(self):
        self.pre_blueprint = blueprint(OLD_CSS)
        self.drifted = (OLD_CSS + WORDMARK_EDIT).encode()       # the 2026-08-21 database-only edit
        self.new_blueprint = blueprint(CSS)
        self.host = FakeHost(self.drifted, self.PROD)
        self.host.files[self.PROD] = self.pre_blueprint
        self.host.files[self.NEW] = self.new_blueprint
        self._pin = change.EXPECTED_PRE_BLUEPRINT_SHA256
        change.EXPECTED_PRE_BLUEPRINT_SHA256 = hashlib.sha256(self.pre_blueprint).hexdigest()
        self.addCleanup(setattr, change, 'EXPECTED_PRE_BLUEPRINT_SHA256', self._pin)

    def run_step(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = change.main(['--prod-blueprint', str(self.PROD), *argv], host=self.host)
        return code, out.getvalue() + err.getvalue()

    def backup(self):
        code, out = self.run_step('backup', '--backup-root', '/b')
        self.assertEqual(code, 0, out)
        return re.search(r'BACKUP_DIR=(\S+)', out).group(1)

    def apply(self, bdir, sha=None):
        return self.run_step('apply', bdir, str(self.NEW), '--expect-sha256',
                             sha or hashlib.sha256(self.new_blueprint).hexdigest())

    def test_backup_records_exact_bytes_and_prints_no_css(self):
        code, out = self.run_step('backup', '--backup-root', '/b')
        self.assertEqual(code, 0)
        bdir = Path(re.search(r'BACKUP_DIR=(\S+)', out).group(1))
        self.assertEqual(self.host.files[bdir / 'branding_custom_css.PRE.css'], self.drifted)
        self.assertEqual(self.host.files[bdir / 'avrana-landing.PRE.yaml'], self.pre_blueprint)
        self.assertNotIn('Times', out)
        self.assertNotIn('AVRANA"', out)
        self.assertEqual(self.host.writes, [], 'backup is read-only')

    def test_apply_then_rollback_restores_the_drifted_record_exactly(self):
        bdir = self.backup()
        code, out = self.apply(bdir)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.host.css, CSS.encode())
        self.assertEqual(self.host.files[self.PROD], self.new_blueprint)
        code, out = self.run_step('verify', bdir)
        self.assertEqual(code, 0, out)
        code, out = self.run_step('rollback', bdir)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.host.files[self.PROD], self.pre_blueprint)
        self.assertEqual(self.host.css, self.drifted, 'the database-only wordmark rules come back too')
        self.assertIn('restored the backed-up branding_custom_css bytes', out)

    def test_rollback_without_drift_needs_no_database_write(self):
        self.host.css = OLD_CSS.encode()
        bdir = self.backup()
        self.assertEqual(self.apply(bdir)[0], 0)
        code, out = self.run_step('rollback', bdir)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.host.css, OLD_CSS.encode())
        self.assertNotIn('restored the backed-up', out)

    def test_refuses_an_unreviewed_file(self):
        bdir = self.backup()
        code, out = self.apply(bdir, sha='0' * 64)
        self.assertEqual(code, 2)
        self.assertIn('is not the reviewed', out)
        self.assertEqual(self.host.files[self.PROD], self.pre_blueprint)

    def test_refuses_when_live_changed_since_backup(self):
        bdir = self.backup()
        self.host.css = b'something else\n'
        code, out = self.apply(bdir)
        self.assertEqual(code, 2)
        self.assertIn('changed since the backup', out)
        self.assertNotIn(self.PROD, self.host.writes)

    def test_refuses_production_drift_from_git(self):
        change.EXPECTED_PRE_BLUEPRINT_SHA256 = '1' * 64
        bdir = self.backup()
        code, out = self.apply(bdir)
        self.assertEqual(code, 2)
        self.assertIn('drift', out)

    def test_stops_when_the_worker_does_not_apply(self):
        self.host.watcher_works = False
        bdir = self.backup()
        code, out = self.apply(bdir)
        self.assertEqual(code, 2)
        self.assertIn('did not apply the blueprint', out)
        self.host.watcher_works = True
        code, out = self.run_step('rollback', bdir)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.host.css, self.drifted)

    def test_stops_on_a_failed_apply(self):
        self.host.apply_status = 'error'
        bdir = self.backup()
        code, out = self.apply(bdir)
        self.assertEqual(code, 2)
        self.assertIn('did not apply', out)


if __name__ == '__main__':
    unittest.main()
