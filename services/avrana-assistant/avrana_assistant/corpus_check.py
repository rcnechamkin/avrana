"""Corpus manifest verification (stdlib only).

Staleness detection: every corpus document records the source files it was derived from, the git blob
hash of each source at extraction time, and a literal anchor string that must still appear in the source.
If a source changes, `verify_manifest` reports it so the corpus document can be re-reviewed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .denylist import find_internal_markers

DATA_CLASSES = ("public-help", "member-general")  # classes that may live in the approved corpus
AUDIENCE_KINDS = ("public", "all_members", "any_of_groups")
REVIEW_STATUSES = ("proposed", "approved", "synthetic-fixture")


def git_blob_hash(data: bytes) -> str:
    """Equivalent of `git hash-object` for a blob. CRLF is normalised to LF first so a Windows checkout
    with autocrlf agrees with the committed blob."""
    data = data.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256_text_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_manifest(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_manifest(manifest_path: Path, repo_root: Path, *, check_sources: bool = True) -> list[str]:
    """Return a list of human-readable problems; empty means the manifest is consistent."""
    manifest_path = Path(manifest_path)
    base = manifest_path.parent
    manifest = load_manifest(manifest_path)
    problems: list[str] = []
    seen_ids: set[str] = set()
    referenced: set[Path] = set()
    for doc in manifest.get("documents", []):
        doc_id = doc.get("id", "<missing id>")
        if doc_id in seen_ids:
            problems.append(f"{doc_id}: duplicate id")
        seen_ids.add(doc_id)
        for key in ("id", "title", "path", "audience", "data_class", "sources", "review_status", "doc_sha256"):
            if key not in doc:
                problems.append(f"{doc_id}: missing field {key}")
        if doc.get("data_class") not in DATA_CLASSES and doc.get("review_status") != "synthetic-fixture":
            problems.append(f"{doc_id}: data_class {doc.get('data_class')!r} not allowed in the corpus")
        if doc.get("review_status") not in REVIEW_STATUSES:
            problems.append(f"{doc_id}: bad review_status")
        aud = doc.get("audience", {})
        if aud.get("kind") not in AUDIENCE_KINDS:
            problems.append(f"{doc_id}: bad audience kind")
        if aud.get("kind") == "any_of_groups" and not aud.get("groups"):
            problems.append(f"{doc_id}: any_of_groups needs groups")
        doc_path = base / doc.get("path", "")
        referenced.add(doc_path.resolve())
        if not doc_path.is_file():
            problems.append(f"{doc_id}: document file missing: {doc.get('path')}")
        else:
            if doc.get("doc_sha256") and sha256_text_file(doc_path) != doc["doc_sha256"]:
                problems.append(f"{doc_id}: document changed since review (doc_sha256 mismatch)")
            text = doc_path.read_text(encoding="utf-8")
            if doc.get("review_status") != "synthetic-fixture":
                for f in find_internal_markers(text):
                    problems.append(f"{doc_id}: operator-internal marker {f.kind} at offset {f.start}")
        if not doc.get("sources") and doc.get("review_status") != "synthetic-fixture":
            problems.append(f"{doc_id}: no source references")
        if check_sources:
            for src in doc.get("sources", []):
                sp = repo_root / src["path"]
                if not sp.is_file():
                    problems.append(f"{doc_id}: source missing: {src['path']}")
                    continue
                raw = sp.read_bytes()
                if git_blob_hash(raw) != src.get("blob"):
                    problems.append(f"{doc_id}: source changed since extraction: {src['path']} "
                                    f"(now {git_blob_hash(raw)})")
                anchor_text = src.get("anchor_text", "")
                if not anchor_text or anchor_text not in raw.decode("utf-8").replace("\r\n", "\n"):
                    problems.append(f"{doc_id}: anchor text not found in {src['path']}")
    docs_dir = base / "docs"
    if docs_dir.is_dir():
        for f in sorted(docs_dir.glob("*.md")):
            if f.resolve() not in referenced:
                problems.append(f"unreferenced corpus file: {f.name}")
    return problems
