"""Validate imported migration ordering and queue invariants in memory only.

No application imports, filesystem databases, credentials or network access.
"""
from pathlib import Path
import sqlite3
import unittest

MIGRATIONS = (Path(__file__).resolve().parents[1] /
              'services/avrana-audible-connector/connector/app/migrations')


class AudibleSchemaTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript((MIGRATIONS / '001_init.sql').read_text())

    def tearDown(self):
        self.db.close()

    def add_connection(self, ident, scanned):
        self.db.execute(
            'INSERT INTO connection (id,authentik_sub,profile_id,audible_email,marketplace,last_scan_at) '
            'VALUES (?,?,?,?,?,?)',
            (ident, 'synthetic-subject', ident, ident + '@example.invalid', 'test', scanned))

    def test_upgrade_baselines_only_previously_scanned_accounts(self):
        self.add_connection('scanned', '2026-01-01T00:00:00Z')
        self.add_connection('new', None)
        self.db.executescript((MIGRATIONS / '002_baseline.sql').read_text())
        rows = dict(self.db.execute('SELECT id,baselined FROM connection'))
        self.assertEqual({'scanned': 1, 'new': 0}, rows)

    def test_only_one_active_job_per_connection_and_book(self):
        self.add_connection('account', None)
        sql = 'INSERT INTO job (id,connection_id,asin,status) VALUES (?,?,?,?)'
        self.db.execute(sql, ('first', 'account', 'SYNTHETIC-BOOK', 'queued'))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(sql, ('duplicate', 'account', 'SYNTHETIC-BOOK', 'running'))
        self.db.execute("UPDATE job SET status='succeeded' WHERE id='first'")
        self.db.execute(sql, ('retry', 'account', 'SYNTHETIC-BOOK', 'queued'))
        self.assertEqual(2, self.db.execute('SELECT count(*) FROM job').fetchone()[0])


if __name__ == '__main__':
    unittest.main()
