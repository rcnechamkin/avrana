"""Corpus manifest verification (stdlib only).

Two kinds of check, deliberately separated:

HARD (a broken manifest; always fails): well-formed manifest, every source PATH exists, every corpus
document exists and is referenced, each document's own recorded hash matches, no deny-list marker.

SOFT / staleness (a source file drifted since extraction): the source blob hash differs or the literal
anchor text is gone. This is NOT a failure of the default offline suite, because the Assistant is
separately governed and must never block edits to the files it was derived from. Instead `check_stale`
returns the stale entries; the default test prints one WARN line per entry; and any document with a stale
source is treated as not approved: `Corpus.load(strict=True)` (the default, for production-style use)
excludes it from retrieval. Run `--strict` before a corpus approval.

  python -B -m avrana_assistant.corpus_check [--strict] [manifest] [--repo-root DIR]
(from services/avrana-assistant), or run this file directly with `python -B`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import NamedTuple

try:
    from .denylist import find_internal_markers
except ImportError:  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from avrana_assistant.denylist import find_internal_markers

DATA_CLASSES = ("public-help", "member-general")  # classes that may live in the approved corpus
AUDIENCE_KINDS = ("public", "all_members", "any_of_groups")
REVIEW_STATUSES = ("proposed", "approved", "synthetic-fixture")


class Stale(NamedTuple):
    doc_id: str
    source_path: str
    reason: str          # "source_changed" | "anchor_missing" | "source_missing"


def git_blob_hash(data: bytes) -> str:
    """Equivalent of `git hash-object` for a blob. CRLF is normalised to LF first so a Windows checkout
    with autocrlf agrees with the committed blob."""
    data = data.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256_text_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_manifest(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_repo_root(start: Path) -> Path:
    for p in [Path(start).resolve(), *Path(start).resolve().parents]:
        if (p / "AGENTS.md").is_file():
            return p
    return Path(start).resolve()


def check_hard(manifest_path: Path, repo_root: Path) -> list[str]:
    """Problems that mean the manifest itself is broken. Never depends on source CONTENT."""
    manifest_path = Path(manifest_path)
    base = manifest_path.parent
    problems: list[str] = []
    try:
        manifest = load_manifest(manifest_path)
        docs = manifest["documents"]
    except (OSError, ValueError, KeyError) as e:
        return [f"manifest unreadable or malformed: {type(e).__name__}"]
    seen_ids: set[str] = set()
    referenced: set[Path] = set()
    for doc in docs:
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
            if doc.get("review_status") != "synthetic-fixture":
                for f in find_internal_markers(doc_path.read_text(encoding="utf-8")):
                    problems.append(f"{doc_id}: operator-internal marker {f.kind} at offset {f.start}")
        if not doc.get("sources") and doc.get("review_status") != "synthetic-fixture":
            problems.append(f"{doc_id}: no source references")
        for src in doc.get("sources", []):
            for key in ("path", "anchor_text", "blob"):
                if not src.get(key):
                    problems.append(f"{doc_id}: source missing field {key}")
            if src.get("path") and not (Path(repo_root) / src["path"]).is_file():
                problems.append(f"{doc_id}: source path does not exist: {src['path']}")
    docs_dir = base / "docs"
    if docs_dir.is_dir():
        for f in sorted(docs_dir.glob("*.md")):
            if f.resolve() not in referenced:
                problems.append(f"unreferenced corpus file: {f.name}")
    return problems


def check_stale(manifest_path: Path, repo_root: Path) -> list[Stale]:
    """Staleness: source drifted since extraction. A missing source file counts as stale (fail closed)."""
    manifest = load_manifest(manifest_path)
    out: list[Stale] = []
    for doc in manifest.get("documents", []):
        for src in doc.get("sources", []):
            sp = Path(repo_root) / src.get("path", "")
            if not sp.is_file():
                out.append(Stale(doc["id"], src.get("path", ""), "source_missing"))
                continue
            raw = sp.read_bytes()
            if git_blob_hash(raw) != src.get("blob"):
                out.append(Stale(doc["id"], src["path"], "source_changed"))
            anchor = src.get("anchor_text", "")
            if not anchor or anchor not in raw.decode("utf-8", "replace").replace("\r\n", "\n"):
                out.append(Stale(doc["id"], src["path"], "anchor_missing"))
    return out


def stale_doc_ids(manifest_path: Path, repo_root: Path) -> set[str]:
    return {s.doc_id for s in check_stale(manifest_path, repo_root)}


def format_warnings(stale: list[Stale]) -> list[str]:
    lines = [f"WARN corpus stale: {s.doc_id} <- {s.source_path}" for s in stale]
    return list(dict.fromkeys(lines))  # one line per (document, source) even if several reasons apply


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verify the Assistant corpus manifest.")
    ap.add_argument("manifest", nargs="?", default=str(Path(__file__).resolve().parents[1] / "corpus" / "manifest.json"))
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--strict", action="store_true", help="exit non-zero on any staleness (run before approving the corpus)")
    args = ap.parse_args(argv)
    manifest = Path(args.manifest)
    root = Path(args.repo_root) if args.repo_root else find_repo_root(manifest)
    hard = check_hard(manifest, root)
    for p in hard:
        print(f"ERROR corpus: {p}")
    try:
        stale = check_stale(manifest, root)
    except (OSError, ValueError, KeyError):
        stale = []
    for line in format_warnings(stale):
        print(line)
    if hard:
        return 1
    if stale and args.strict:
        print(f"STRICT: {len(stale)} stale source reference(s); re-review the listed documents before approval")
        return 1
    print("corpus ok" if not stale else "corpus ok (stale sources present, non-strict)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
