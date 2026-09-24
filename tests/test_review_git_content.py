import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'review', Path(__file__).resolve().parents[1] / 'scripts/review_git_content.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class ContentGateTests(unittest.TestCase):
    def test_source_and_documentation(self):
        self.assertEqual([], review.review_blob('docs/OPERATIONS.md', '100644', b'# Operations\n'))
        self.assertEqual([], review.review_blob('services/demo/config.py', '100644', b'import os\n'))

    def test_private_runtime_paths(self):
        for path in ['.env', '.env.production', 'services/bookstack/README.md',
                     'filing_cabinet/note.md', 'services/demo/data/app.db-wal',
                     'backup.tar.zst', 'services/demo/logs/debug.txt']:
            with self.subTest(path=path):
                self.assertTrue(review.review_blob(path, '100644', b'content'))

    def test_binary_large_and_symlink(self):
        self.assertTrue(review.review_blob('source.py', '120000', b'/outside'))
        self.assertTrue(review.review_blob('source.py', '100644', b'a\0b'))
        self.assertTrue(review.review_blob('source.py', '100644', b'a' * (review.MAX_BYTES + 1)))

    def test_secret_detection_without_value_output(self):
        samples = [b'-----BEGIN ' + b'OPENSSH PRIVATE KEY-----',
                   b'ghp_' + b'X' * 36,
                   b'client_secret = "' + b'Z' * 32 + b'"']
        for sample in samples:
            issues = review.review_blob('source.py', '100644', sample)
            self.assertTrue(issues)
            self.assertNotIn(sample.decode(), '\n'.join(issues))

    def test_only_migration_sql_is_candidate(self):
        self.assertTrue(review.review_blob('dump.sql', '100644', b'SELECT 1;'))
        self.assertEqual([], review.review_blob('app/migrations/001_init.sql', '100644', b'CREATE TABLE demo (id INTEGER);'))


if __name__ == '__main__':
    unittest.main()
