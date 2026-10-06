"""The webhook server's two guards (forensic audit N2): the path a webhook names must be a file
under the movie library, and a POST must carry the configured Basic credentials."""
import base64
import os
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("IMAX_RESULTS", tempfile.mkdtemp())
import server  # noqa: E402


class AllowedPathTests(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        (self.root / "movies/Film (2025)").mkdir(parents=True)
        self.inside = self.root / "movies/Film (2025)/film.mkv"
        self.inside.write_bytes(b"x")
        self.outside = self.root / "secret.txt"
        self.outside.write_bytes(b"x")
        self.saved = server.ALLOWED_ROOT
        server.ALLOWED_ROOT = self.root / "movies"

    def tearDown(self):
        server.ALLOWED_ROOT = self.saved

    def test_file_inside_the_library_is_allowed(self):
        self.assertEqual(self.inside.resolve(), server.allowed_path(str(self.inside)))

    def test_outside_traversal_and_directories_are_refused(self):
        self.assertIsNone(server.allowed_path(str(self.outside)))
        self.assertIsNone(server.allowed_path(str(self.root / "movies/../secret.txt")))
        self.assertIsNone(server.allowed_path(str(self.root / "movies/Film (2025)")))
        self.assertIsNone(server.allowed_path(str(self.root / "movies/missing.mkv")))
        self.assertIsNone(server.allowed_path("/etc/passwd"))

    @unittest.skipUnless(hasattr(os, "symlink") and os.name != "nt", "symlinks")
    def test_symlink_pointing_outside_is_refused(self):
        link = self.root / "movies/link.mkv"
        link.symlink_to(self.outside)
        self.assertIsNone(server.allowed_path(str(link)))


class AuthorizedTests(unittest.TestCase):
    def setUp(self):
        self.saved = server.WEBHOOK_USER, server.WEBHOOK_PASSWORD
        server.WEBHOOK_USER, server.WEBHOOK_PASSWORD = "radarr", "s3cret-value"

    def tearDown(self):
        server.WEBHOOK_USER, server.WEBHOOK_PASSWORD = self.saved

    @staticmethod
    def basic(user, password):
        return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    def test_right_credentials_pass(self):
        self.assertTrue(server.authorized(self.basic("radarr", "s3cret-value")))

    def test_wrong_missing_or_malformed_fail(self):
        self.assertFalse(server.authorized(self.basic("radarr", "wrong")))
        self.assertFalse(server.authorized(self.basic("other", "s3cret-value")))
        self.assertFalse(server.authorized(None))
        self.assertFalse(server.authorized("Bearer abc"))
        self.assertFalse(server.authorized("Basic not-base64!"))

    def test_empty_configured_password_never_authorizes(self):
        server.WEBHOOK_PASSWORD = ""
        self.assertFalse(server.authorized(self.basic("radarr", "")))


if __name__ == "__main__":
    unittest.main()
