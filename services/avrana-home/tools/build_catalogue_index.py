#!/usr/bin/env python3
"""Build Home's catalogue-id index: which outside identifiers already sit in which library (host-run, read-only).

Status: proposed, not installed. Standard library only. Design: docs/design/API-CAPS-AND-MATCHING.md section 2.

The reading apps' APIs carry no ISBN or ComicVine id, but the tools that fetched the files stamped them, in the
same id spaces the request tools search with. This joins them once, so Home can say "Already in Books" exactly
instead of guessing from titles:

  * ebooks      Calibre metadata.db `identifiers` (hardcover-id, isbn)           -> Calibre book id (= Calibre-Web id)
  * audiobooks  Shelfarr's mirror of Audiobookshelf (`library_items`: isbn, asin) -> Audiobookshelf item id
  * comics      Omnibus `Series` (cvId, folderPath) joined by path to Komga `SERIES` (URL) -> Komga series id

Catalogue identifiers only: no users, no progress, no requests, no titles in the output (title keys are folded,
lower-case word keys used for a "likely" tier, never shown). Every database is opened `mode=ro`. A source that
cannot be read is skipped and counted, never fatal; the previous index stays in place if nothing could be read.

Usage:
  build_catalogue_index.py --out PATH [--calibre-db P] [--shelfarr-db P] [--omnibus-db P] [--komga-db P]
  build_catalogue_index.py --dry-run ...      print the counts only
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import pathlib
import re
import sqlite3
import sys
import unicodedata
from urllib.parse import unquote

VERSION = 1
HOME = pathlib.Path("/home/cody/avrana/services")
DEFAULTS = {
    "calibre_db": pathlib.Path("/mnt/avrana_media/calibre-library/metadata.db"),
    "shelfarr_db": HOME / "shelfarr/data/production.sqlite3",
    "omnibus_db": HOME / "omnibus/config/omnibus.db",
    "komga_db": HOME / "komga/config/database.sqlite",
}
# Mount roots, stripped so the three comic tools agree on "<Publisher>/<Series (Year)>".
KOMGA_ROOT = "/avrana_media/avrana_media/comics/"
OMNIBUS_ROOTS = ("/mylar-library/", "/data/")
CALIBRE_ID = re.compile(r"[0-9]{1,9}")
ABS_ID = re.compile(r"(?:li_[a-z0-9]{8,40}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
KOMGA_ID = re.compile(r"[0-9A-Z]{13}")
HARDCOVER = re.compile(r"[0-9]{1,12}")
ASIN = re.compile(r"[0-9A-Z]{10}")
MAX_ENTRIES = 200_000


def isbn13(raw) -> str | None:
    """ISBN-13 digits for an ISBN-10 or ISBN-13 (hyphens and spaces ignored), or None when the checksum fails."""
    digits = re.sub(r"[^0-9Xx]", "", str(raw or "")).upper()
    if len(digits) == 10 and digits[:9].isdigit():
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(digits))
        if total % 11:
            return None
        digits = "978" + digits[:9]
        return digits + str((10 - sum((3 if i % 2 else 1) * int(c) for i, c in enumerate(digits)) % 10) % 10)
    if len(digits) == 13 and digits.isdigit():
        check = (10 - sum((3 if i % 2 else 1) * int(c) for i, c in enumerate(digits[:12])) % 10) % 10
        return digits if check == int(digits[12]) else None
    return None


_ARTICLES = re.compile(r"^(?:the|a|an) ")


def title_key(title, author) -> str | None:
    """A folded "title|surname" key for the LIKELY tier: subtitle and leading article dropped, punctuation and
    accents folded, the first author's last word. Home shows a likely match as a hint only, never as owned."""
    def fold(text):
        text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
        return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())
    main = fold(re.split(r"[:(\[]", str(title or ""), 1)[0])
    main = _ARTICLES.sub("", main)
    first_author = re.split(r"[,;&]| and ", str(author or ""), 1)[0]
    surname = fold(first_author).split(" ")[-1] if fold(first_author) else ""
    if len(main) < 2 or not surname:
        return None
    return f"t:{main}|{surname}"


@contextlib.contextmanager
def ro(path: pathlib.Path):
    if not pathlib.Path(path).is_file():
        raise FileNotFoundError(str(path))
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        yield db
    finally:
        db.close()


def from_calibre(path) -> tuple[dict, dict]:
    exact, likely = {}, {}
    with ro(path) as db:
        for book, kind, val in db.execute("SELECT book, type, val FROM identifiers"):
            book = str(book)
            if not CALIBRE_ID.fullmatch(book):
                continue
            kind = (kind or "").lower()
            if kind in ("hardcover-id", "hardcover") and HARDCOVER.fullmatch(str(val or "")):
                exact.setdefault(f"hardcover:{val}", book)
            elif kind in ("isbn", "isbn13", "isbn10") and isbn13(val):
                exact.setdefault(f"isbn:{isbn13(val)}", book)
        rows = db.execute("SELECT b.id, b.title, (SELECT a.name FROM books_authors_link l JOIN authors a "
                          "ON a.id = l.author WHERE l.book = b.id ORDER BY l.id LIMIT 1) FROM books b")
        for book, title, author in rows:
            key = title_key(title, author)
            if key and CALIBRE_ID.fullmatch(str(book)):
                likely.setdefault(key, str(book))
    return exact, likely


def from_shelfarr(path) -> tuple[dict, dict]:
    exact, likely = {}, {}
    with ro(path) as db:
        rows = db.execute("SELECT audiobookshelf_id, title, author, isbn, asin FROM library_items "
                          "WHERE COALESCE(missing, 0) = 0 AND COALESCE(library_platform, 'audiobookshelf') "
                          "= 'audiobookshelf'")
        for item, title, author, isbn, asin in rows:
            item = str(item or "")
            if not ABS_ID.fullmatch(item):
                continue
            if isbn13(isbn):
                exact.setdefault(f"isbn:{isbn13(isbn)}", item)
            if asin and ASIN.fullmatch(str(asin).upper()):
                exact.setdefault(f"asin:{str(asin).upper()}", item)
            key = title_key(title, author)
            if key:
                likely.setdefault(key, item)
    return exact, likely


def _rel(path: str, roots) -> str | None:
    for root in roots:
        if path.startswith(root):
            rel = path[len(root):].strip("/")
            return rel.lower() if rel else None
    return None


def from_comics(omnibus_path, komga_path) -> dict:
    with ro(komga_path) as db:
        komga = {}
        for sid, url in db.execute("SELECT ID, URL FROM SERIES WHERE DELETED_DATE IS NULL"):
            path = unquote(str(url or "")).removeprefix("file:")
            rel = _rel(path, (KOMGA_ROOT,))
            if rel and KOMGA_ID.fullmatch(str(sid)):
                komga[rel] = str(sid)
    out = {}
    with ro(omnibus_path) as db:
        for cv, folder in db.execute("SELECT cvId, folderPath FROM Series WHERE cvId IS NOT NULL"):
            rel = _rel(str(folder or ""), OMNIBUS_ROOTS)
            if rel and rel in komga and str(cv).isdigit():
                out.setdefault(f"comicvine:{cv}", komga[rel])
    return out


def build(paths: dict) -> tuple[dict, dict]:
    index = {"version": VERSION, "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "ebook": {}, "ebook_likely": {}, "audiobook": {}, "audiobook_likely": {}, "comic": {}}
    report = {}
    steps = (("calibre", lambda: from_calibre(paths["calibre_db"]), ("ebook", "ebook_likely")),
             ("shelfarr", lambda: from_shelfarr(paths["shelfarr_db"]), ("audiobook", "audiobook_likely")),
             ("comics", lambda: (from_comics(paths["omnibus_db"], paths["komga_db"]),), ("comic",)))
    for name, run, targets in steps:
        try:
            parts = run()
        except (sqlite3.Error, OSError) as exc:
            report[name] = f"skipped ({type(exc).__name__})"
            continue
        for target, part in zip(targets, parts):
            index[target] = dict(list(part.items())[:MAX_ENTRIES])
        report[name] = ", ".join(f"{t}={len(index[t])}" for t in targets)
    return index, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--dry-run", action="store_true")
    for name, default in DEFAULTS.items():
        parser.add_argument("--" + name.replace("_", "-"), type=pathlib.Path, default=default)
    args = parser.parse_args(argv)
    if not args.dry_run and not args.out:
        parser.error("--out is required unless --dry-run")
    index, report = build({k: getattr(args, k) for k in DEFAULTS})
    print("catalogue index: " + "; ".join(f"{k} {v}" for k, v in report.items()))
    if all(str(v).startswith("skipped") for v in report.values()):
        print("catalogue index: nothing could be read; the previous index is kept", file=sys.stderr)
        return 2
    if args.dry_run:
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_name(args.out.name + ".tmp")
    tmp.write_text(json.dumps(index, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
