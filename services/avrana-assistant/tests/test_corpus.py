"""Corpus manifest tests (AVR-397): sources exist, hashes current, docs referenced, no internal markers."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
REPO = SERVICE.parents[1]
sys.path.insert(0, str(SERVICE))

from avrana_assistant import corpus_check, denylist  # noqa: E402

MANIFEST = SERVICE / "corpus" / "manifest.json"


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = corpus_check.load_manifest(MANIFEST)

    def test_manifest_is_proposed_not_approved(self):
        self.assertIn("proposed", self.manifest["status"])
        for doc in self.manifest["documents"]:
            self.assertEqual(doc["review_status"], "proposed", doc["id"])

    def test_every_manifest_source_path_exists(self):
        for doc in self.manifest["documents"]:
            self.assertTrue(doc["sources"], doc["id"])
            for src in doc["sources"]:
                self.assertTrue((REPO / src["path"]).is_file(), f"{doc['id']}: {src['path']}")

    def test_every_recorded_blob_hash_matches(self):
        for doc in self.manifest["documents"]:
            for src in doc["sources"]:
                actual = corpus_check.git_blob_hash((REPO / src["path"]).read_bytes())
                self.assertEqual(actual, src["blob"],
                                 f"{doc['id']}: {src['path']} changed since extraction; re-review the document")

    def test_blob_hash_agrees_with_git(self):
        # Cross-check the Python implementation against git itself when git is available.
        src = self.manifest["documents"][0]["sources"][0]
        try:
            out = subprocess.run(["git", "-C", str(REPO), "rev-parse", f"HEAD:{src['path']}"],
                                 capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git unavailable or file not yet committed at HEAD")
        self.assertEqual(corpus_check.git_blob_hash((REPO / src["path"]).read_bytes()), out)

    def test_anchor_text_present_in_each_source(self):
        for doc in self.manifest["documents"]:
            for src in doc["sources"]:
                text = (REPO / src["path"]).read_bytes().decode("utf-8").replace("\r\n", "\n")
                self.assertIn(src["anchor_text"], text, f"{doc['id']}: {src['anchor']}")

    def test_every_doc_is_referenced_and_every_reference_exists(self):
        listed = {(MANIFEST.parent / d["path"]).resolve() for d in self.manifest["documents"]}
        on_disk = {p.resolve() for p in (MANIFEST.parent / "docs").glob("*.md")}
        self.assertEqual(listed, on_disk)

    def test_doc_hashes_current(self):
        self.assertEqual(corpus_check.verify_manifest(MANIFEST, REPO), [])

    def test_ids_unique_and_audiences_valid(self):
        ids = [d["id"] for d in self.manifest["documents"]]
        self.assertEqual(len(ids), len(set(ids)))
        for d in self.manifest["documents"]:
            self.assertIn(d["audience"]["kind"], corpus_check.AUDIENCE_KINDS)
            self.assertIn(d["data_class"], corpus_check.DATA_CLASSES)
            if d["data_class"] == "public-help":
                self.assertEqual(d["audience"]["kind"], "public", d["id"])

    def test_gaps_recorded(self):
        self.assertTrue(any("D-1" in g["owner_decision"] for g in self.manifest["gaps"]))

    def test_no_operator_markers_in_corpus_docs(self):
        for doc in self.manifest["documents"]:
            text = (MANIFEST.parent / doc["path"]).read_text(encoding="utf-8")
            findings = denylist.find_internal_markers(text)
            self.assertEqual([(f.kind, f.start) for f in findings], [], doc["id"])

    def test_corpus_docs_do_not_name_unrelated_services_in_general_docs(self):
        # Audience-neutral documents must not enumerate services (existence leak).
        general = [d for d in self.manifest["documents"] if d["audience"]["kind"] != "any_of_groups"]
        self.assertGreaterEqual(len(general), 6)
        banned = ("jellyfin", "audiobookshelf", "komga", "calibre", "seerr", "swiftfin", "movie", "film",
                  "tv", "audiobook", "comic", "manga", "ebook", "kindle", "playback", "watch.", "listen.",
                  "read.avrana", "books.avrana")
        for d in general:
            text = (MANIFEST.parent / d["path"]).read_text(encoding="utf-8").lower()
            words = set(__import__("re").findall(r"[a-z0-9.]+", text))
            for word in banned:
                hit = word in words or (word.endswith(".") and word in text) or (
                    len(word) > 4 and word in text)
                self.assertFalse(hit, f"{d['id']} names {word}")


class DenylistSelfTests(unittest.TestCase):
    """The deny-list must catch what it claims to; strings are assembled at runtime."""

    def kinds(self, text):
        return {f.kind for f in denylist.find_internal_markers(text)}

    def test_private_ip_and_port(self):
        self.assertIn("ip_address", self.kinds("host at " + ".".join(["192", "168", "1", "20"])))
        self.assertIn("port", self.kinds("http://example.net" + ":" + "8096"))

    def test_paths_and_container_names(self):
        self.assertIn("filesystem_path", self.kinds("see /" + "home/someone/app"))
        self.assertIn("filesystem_path", self.kinds("data in /" + "mnt/disk"))
        self.assertIn("internal_name", self.kinds("restart the authentik-worker container"))
        self.assertIn("internal_name", self.kinds("run docker ps"))

    def test_admin_hostnames_but_not_member_hostnames(self):
        self.assertIn("admin_hostname", self.kinds("open ops" + ".avrana.net"))
        self.assertNotIn("admin_hostname", self.kinds("open https://watch.avrana.net and https://avrana.net"))

    def test_secret_shapes(self):
        self.assertIn("provider_key_shape", self.kinds("key sk-" + "a1" * 15))
        self.assertIn("jwt_shape", self.kinds("eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12))
        self.assertIn("long_hex", self.kinds("0123456789abcdef" * 2))
        self.assertIn("credential_assignment", self.kinds("pass" + "word: hunter22x"))
        self.assertIn("env_var_name", self.kinds("set SERVICE_API_KEY"))
        self.assertIn("identity_header", self.kinds("X-authentik-groups"))

    def test_plain_member_text_is_clean(self):
        text = ("Install Swiftfin from the App Store. Add server: https://watch.avrana.net and sign in "
                "with your Avrana username and password. The link expires after 30 minutes at 10:30.")
        self.assertEqual(self.kinds(text), set())

    def test_findings_never_contain_matched_text(self):
        f = denylist.find_internal_markers("token: abcdef123456")[0]
        self.assertFalse(hasattr(f, "text"))

    def test_redact_removes_secret(self):
        secret = "sk-" + "z9" * 15
        out, findings = denylist.redact(f"my key is {secret} ok")
        self.assertNotIn(secret, out)
        self.assertTrue(findings)

    def test_verify_manifest_detects_staleness(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "docs").mkdir()
            (d / "docs" / "a.md").write_text("Hello member.\n", encoding="utf-8")
            (d / "src.txt").write_text("source anchor\n", encoding="utf-8")
            manifest = {"documents": [{
                "id": "a", "title": "A", "path": "docs/a.md", "audience": {"kind": "public"},
                "data_class": "public-help", "review_status": "proposed",
                "doc_sha256": corpus_check.sha256_text_file(d / "docs" / "a.md"),
                "sources": [{"path": "src.txt", "anchor": "x", "anchor_text": "source anchor",
                             "blob": corpus_check.git_blob_hash(b"source anchor\n")}]}]}
            (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(corpus_check.verify_manifest(d / "manifest.json", d), [])
            (d / "src.txt").write_text("source anchor changed\n", encoding="utf-8")
            problems = corpus_check.verify_manifest(d / "manifest.json", d)
            self.assertTrue(any("changed since extraction" in p for p in problems))
            (d / "docs" / "b.md").write_text("orphan\n", encoding="utf-8")
            self.assertTrue(any("unreferenced" in p for p in corpus_check.verify_manifest(d / "manifest.json", d)))


if __name__ == "__main__":
    unittest.main()
