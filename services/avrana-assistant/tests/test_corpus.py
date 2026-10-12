"""Corpus manifest tests (AVR-397).

HARD checks fail the suite. Source STALENESS never does: it prints WARN lines and passes, so the
Assistant cannot block edits to the files it was derived from (portal, onboarding, ...).
"""
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
REPO = SERVICE.parents[1]
sys.path.insert(0, str(SERVICE))

from avrana_assistant import corpus_check, denylist  # noqa: E402
from avrana_assistant.datatypes import Principal  # noqa: E402
from avrana_assistant.retrieval import Corpus, Retriever  # noqa: E402

MANIFEST = SERVICE / "corpus" / "manifest.json"


class HardManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = corpus_check.load_manifest(MANIFEST)

    def test_manifest_is_proposed_not_approved(self):
        self.assertIn("proposed", self.manifest["status"])
        for doc in self.manifest["documents"]:
            self.assertEqual(doc["review_status"], "proposed", doc["id"])

    def test_hard_checks_pass(self):
        self.assertEqual(corpus_check.check_hard(MANIFEST, REPO), [])

    def test_every_manifest_source_path_exists(self):
        for doc in self.manifest["documents"]:
            self.assertTrue(doc["sources"], doc["id"])
            for src in doc["sources"]:
                self.assertTrue((REPO / src["path"]).is_file(), f"{doc['id']}: {src['path']}")

    def test_every_doc_is_referenced_and_every_reference_exists(self):
        listed = {(MANIFEST.parent / d["path"]).resolve() for d in self.manifest["documents"]}
        on_disk = {p.resolve() for p in (MANIFEST.parent / "docs").glob("*.md")}
        self.assertEqual(listed, on_disk)

    def test_ids_unique_and_audiences_valid(self):
        ids = [d["id"] for d in self.manifest["documents"]]
        self.assertEqual(len(ids), len(set(ids)))
        for d in self.manifest["documents"]:
            self.assertIn(d["audience"]["kind"], corpus_check.AUDIENCE_KINDS)
            self.assertIn(d["data_class"], corpus_check.DATA_CLASSES)
            if d["data_class"] == "public-help":
                self.assertEqual(d["audience"]["kind"], "public", d["id"])

    def test_request_doc_audience_is_videos_only(self):
        d = next(x for x in self.manifest["documents"] if x["id"] == "request-movies-tv")
        self.assertEqual(d["audience"], {"kind": "any_of_groups", "groups": ["avrana-videos"]})

    def test_gaps_recorded(self):
        self.assertTrue(any("D-1" in g["owner_decision"] for g in self.manifest["gaps"]))

    def test_no_operator_markers_in_corpus_docs(self):
        for doc in self.manifest["documents"]:
            text = (MANIFEST.parent / doc["path"]).read_text(encoding="utf-8")
            self.assertEqual([(f.kind, f.start) for f in denylist.find_internal_markers(text)], [], doc["id"])

    def test_anchors_do_not_encode_group_names(self):
        for doc in self.manifest["documents"]:
            for src in doc["sources"]:
                self.assertIsNone(re.search(r"avrana-[a-z]+|library-contributors", src["anchor_text"]),
                                  f"{doc['id']}: anchor quotes a volatile group name")

    def test_general_docs_do_not_enumerate_services(self):
        # Audience-neutral documents must not name services or media types (existence leak).
        general = [d for d in self.manifest["documents"] if d["audience"]["kind"] != "any_of_groups"]
        self.assertGreaterEqual(len(general), 6)
        banned = ("jellyfin", "audiobookshelf", "komga", "calibre", "seerr", "swiftfin", "movie", "film",
                  "tv", "audiobook", "comic", "manga", "ebook", "kindle", "playback", "watch.", "listen.",
                  "read.avrana", "books.avrana")
        for d in general:
            text = (MANIFEST.parent / d["path"]).read_text(encoding="utf-8").lower()
            words = set(re.findall(r"[a-z0-9.]+", text))
            for word in banned:
                hit = word in words or (word.endswith(".") and word in text) or (len(word) > 4 and word in text)
                self.assertFalse(hit, f"{d['id']} names {word}")


class StalenessWarningTest(unittest.TestCase):
    """SOFT: reports drift against the real sources as WARN lines but never fails."""

    def test_sources_not_stale_or_warn(self):
        stale = corpus_check.check_stale(MANIFEST, REPO)
        for line in corpus_check.format_warnings(stale):
            print(line, file=sys.stderr)
        # Deliberately no assertion on `stale`: run `corpus_check.py --strict` before approving the corpus.
        self.assertIsInstance(stale, list)


def quiet_main(args):
    with contextlib.redirect_stdout(io.StringIO()):
        return corpus_check.main(args)


def make_temp_corpus(tmp: Path, *, blob_ok=True, anchor_ok=True):
    """A self-contained manifest, docs and a fake source tree; independent of the real portal.py."""
    (tmp / "AGENTS.md").write_text("x\n", encoding="utf-8")
    (tmp / "src").mkdir()
    source = b"line one\nthe stable anchor sentence\nline three\n"
    (tmp / "src" / "page.txt").write_bytes(source)
    (tmp / "c" / "docs").mkdir(parents=True)
    doc = tmp / "c" / "docs" / "alpha.md"
    doc.write_text("# Alpha\n\nInstall the app and sign in.\n", encoding="utf-8")
    other = tmp / "c" / "docs" / "beta.md"
    other.write_text("# Beta\n\nContact support for anything else.\n", encoding="utf-8")

    def entry(did, path, blob, anchor):
        return {"id": did, "title": did, "path": f"docs/{did}.md", "audience": {"kind": "all_members"},
                "data_class": "member-general", "review_status": "proposed",
                "doc_sha256": corpus_check.sha256_text_file(path),
                "sources": [{"path": "src/page.txt", "anchor": "a", "anchor_text": anchor, "blob": blob}]}

    good = corpus_check.git_blob_hash(source)
    manifest = {"status": "proposed", "documents": [
        entry("alpha", doc, good if blob_ok else "0" * 40, "the stable anchor sentence" if anchor_ok else "gone text"),
        entry("beta", other, good, "the stable anchor sentence")]}
    mp = tmp / "c" / "manifest.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    return mp


class StrictAndNonStrictTests(unittest.TestCase):
    def test_clean_temp_corpus_has_no_stale_entries(self):
        with tempfile.TemporaryDirectory() as d:
            mp = make_temp_corpus(Path(d))
            self.assertEqual(corpus_check.check_hard(mp, Path(d)), [])
            self.assertEqual(corpus_check.check_stale(mp, Path(d)), [])
            self.assertEqual(quiet_main([str(mp), "--repo-root", d, "--strict"]), 0)

    def test_wrong_blob_hash_is_stale_not_hard(self):
        with tempfile.TemporaryDirectory() as d:
            mp = make_temp_corpus(Path(d), blob_ok=False)
            self.assertEqual(corpus_check.check_hard(mp, Path(d)), [])
            stale = corpus_check.check_stale(mp, Path(d))
            self.assertEqual([(s.doc_id, s.reason) for s in stale], [("alpha", "source_changed")])
            self.assertEqual(corpus_check.format_warnings(stale), ["WARN corpus stale: alpha <- src/page.txt"])

    def test_missing_anchor_is_stale_not_hard(self):
        with tempfile.TemporaryDirectory() as d:
            mp = make_temp_corpus(Path(d), anchor_ok=False)
            self.assertEqual(corpus_check.check_hard(mp, Path(d)), [])
            self.assertEqual([(s.doc_id, s.reason) for s in corpus_check.check_stale(mp, Path(d))],
                             [("alpha", "anchor_missing")])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            mp = make_temp_corpus(Path(d), blob_ok=False, anchor_ok=False)
            self.assertEqual(quiet_main([str(mp), "--repo-root", d]), 0)            # non-strict passes
            self.assertEqual(quiet_main([str(mp), "--repo-root", d, "--strict"]), 1)  # strict fails

    def test_hard_failures_still_fail(self):
        with tempfile.TemporaryDirectory() as d:
            mp = make_temp_corpus(Path(d))
            (Path(d) / "src" / "page.txt").unlink()
            self.assertTrue(any("source path does not exist" in p for p in corpus_check.check_hard(mp, Path(d))))
            self.assertEqual(quiet_main([str(mp), "--repo-root", d]), 1)
        with tempfile.TemporaryDirectory() as d:
            mp = make_temp_corpus(Path(d))
            (Path(d) / "c" / "docs" / "alpha.md").write_text("changed after review\n", encoding="utf-8")
            self.assertTrue(any("doc_sha256" in p for p in corpus_check.check_hard(mp, Path(d))))
            (Path(d) / "c" / "docs" / "gamma.md").write_text("orphan\n", encoding="utf-8")
            self.assertTrue(any("unreferenced" in p for p in corpus_check.check_hard(mp, Path(d))))
        with tempfile.TemporaryDirectory() as d:
            mp = make_temp_corpus(Path(d))
            (Path(d) / "c" / "docs" / "beta.md").write_text("see /" + "home/x/app\n", encoding="utf-8")
            self.assertTrue(any("operator-internal" in p for p in corpus_check.check_hard(mp, Path(d))))

    def test_non_strict_load_keeps_stale_docs_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            mp = make_temp_corpus(Path(d), blob_ok=False)
            c = Corpus.load(mp, strict=False, repo_root=Path(d))
            self.assertTrue(c.docs["alpha"].stale)
            self.assertFalse(c.docs["beta"].stale)
            res = Retriever(c).search(Principal("synthetic-x", frozenset()), "install the app and sign in")
            self.assertIn("alpha", [p.doc_id for p in res.passages])

    def test_strict_is_the_default_and_excludes_stale_docs(self):
        with tempfile.TemporaryDirectory() as d:
            mp = make_temp_corpus(Path(d), blob_ok=False)
            c = Corpus.load(mp, repo_root=Path(d))        # default: strict
            self.assertTrue(c.strict)
            self.assertIsNone(c.get("alpha", Principal("synthetic-x", frozenset())))
            res = Retriever(c).search(Principal("synthetic-x", frozenset()), "install the app and sign in")
            self.assertNotIn("alpha", [p.doc_id for p in res.passages])

    def test_strict_load_fails_closed_on_hard_problems(self):
        from avrana_assistant.retrieval import CorpusError
        with tempfile.TemporaryDirectory() as d:
            mp = make_temp_corpus(Path(d))
            (Path(d) / "src" / "page.txt").unlink()
            with self.assertRaises(CorpusError):
                Corpus.load(mp, repo_root=Path(d))


class DenylistSelfTests(unittest.TestCase):
    """The deny-list must catch what it claims to; strings are assembled at runtime."""

    def kinds(self, text):
        return {f.kind for f in denylist.find_internal_markers(text)}

    def test_blob_hash_matches_git_known_value(self):
        self.assertEqual(corpus_check.git_blob_hash(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

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


if __name__ == "__main__":
    unittest.main()
