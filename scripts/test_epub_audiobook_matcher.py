#!/usr/bin/env python3
"""Tests for epub_audiobook_matcher. Dependency-free: run `python3 test_epub_audiobook_matcher.py`
(also works under pytest). Builds a throwaway Calibre metadata.db + audiobook tree in a tmp dir."""
import os
import sqlite3
import tempfile
import shutil

import epub_audiobook_matcher as m


# ---- fixture builders ---------------------------------------------------------------------
def _calibre(lib, books):
    """books: list of (title, author, epub_name_or_None, {idtype:val})."""
    os.makedirs(lib, exist_ok=True)
    db = sqlite3.connect(os.path.join(lib, "metadata.db"))
    db.executescript("""
        CREATE TABLE books(id INTEGER PRIMARY KEY, title TEXT, path TEXT);
        CREATE TABLE authors(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE books_authors_link(id INTEGER PRIMARY KEY, book INT, author INT);
        CREATE TABLE data(id INTEGER PRIMARY KEY, book INT, format TEXT, name TEXT);
        CREATE TABLE identifiers(id INTEGER PRIMARY KEY, book INT, type TEXT, val TEXT);
    """)
    for i, (title, author, epub, ids) in enumerate(books, 1):
        path = f"{author}/{title} ({i})"
        db.execute("INSERT INTO books VALUES(?,?,?)", (i, title, path))
        db.execute("INSERT INTO authors VALUES(?,?)", (i, author))
        db.execute("INSERT INTO books_authors_link VALUES(?,?,?)", (i, i, i))
        if epub:
            db.execute("INSERT INTO data VALUES(?,?,?,?)", (i, i, "EPUB", epub))
            os.makedirs(os.path.join(lib, path), exist_ok=True)
            with open(os.path.join(lib, path, epub + ".epub"), "w") as fh:
                fh.write("EPUBDATA-%d" % i)
        for t, v in (ids or {}).items():
            db.execute("INSERT INTO identifiers(book,type,val) VALUES(?,?,?)", (i, t, v))
    db.commit(); db.close()


def _audiobooks(root, folders):
    """folders: list of (author, folder_basename, has_epub)."""
    for author, folder, has_epub in folders:
        d = os.path.join(root, author, folder)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, folder + ".m4b"), "w").close()
        if has_epub:
            open(os.path.join(d, folder + ".epub"), "w").close()


def _run(books, folders):
    tmp = tempfile.mkdtemp()
    try:
        lib, ab = os.path.join(tmp, "cal"), os.path.join(tmp, "ab")
        os.makedirs(ab)
        _calibre(lib, books)
        _audiobooks(ab, folders)
        ebooks = m.load_ebooks(lib)
        audiobooks = m.scan_audiobooks(ab)
        decisions = {d.ebook.title: d for d in (m.classify(e, audiobooks) for e in ebooks)}
        return tmp, lib, ab, decisions
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


# ---- normalization ------------------------------------------------------------------------
def test_author_key_is_order_and_punctuation_insensitive():
    assert m.author_key("James S.A. Corey") == m.author_key("James S. A. Corey")
    assert m.author_key("James S. A. Corey") == m.author_key("Corey, James S. A.")


def test_title_key_strips_asin_and_punctuation():
    assert m.title_key("Cibola Burn [B00K7PP15W]") == m.title_key("Cibola Burn")
    assert m.title_key("A Court of Thorns and Roses: Book 1") == "acourtofthornsandrosesbook1"


# ---- matching tiers -----------------------------------------------------------------------
def test_exact_author_title_links():
    tmp, lib, ab, d = _run(
        [("Cibola Burn", "James S.A. Corey", "Cibola Burn - James S.A. Corey", {})],
        [("James S. A. Corey", "Cibola Burn [B00K7PP15W]", False)])
    try:
        assert d["Cibola Burn"].action == "link" and d["Cibola Burn"].tier == "exact"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_subtitle_prefix_links():
    # audiobook adds ": A Novel"; ebook title is a prefix -> should still link.
    tmp, lib, ab, d = _run(
        [("Anxious People", "Fredrik Backman", "Anxious People - Fredrik Backman", {})],
        [("Fredrik Backman", "Anxious People: A Novel [1797105833]", False)])
    try:
        assert d["Anxious People"].action == "link" and d["Anxious People"].tier == "prefix"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_shared_identifier_links_even_without_title_match():
    tmp, lib, ab, d = _run(
        [("Some Book", "An Author", "Some Book - An Author", {"amazon": "B00K7PP15W"})],
        [("An Author", "Totally Different Title [B00K7PP15W]", False)])
    try:
        assert d["Some Book"].action == "link" and d["Some Book"].tier == "id"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_epub_only_title_is_ignored():
    # ebook with no matching audiobook must never be placed anywhere.
    tmp, lib, ab, d = _run(
        [("Orphan Ebook", "Nobody", "Orphan Ebook - Nobody", {})],
        [("Someone Else", "Unrelated [B000000AA1]", False)])
    try:
        assert d["Orphan Ebook"].action == "no-match"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_existing_epub_is_idempotent_skip():
    tmp, lib, ab, d = _run(
        [("Cibola Burn", "James S.A. Corey", "Cibola Burn - James S.A. Corey", {})],
        [("James S. A. Corey", "Cibola Burn [B00K7PP15W]", True)])  # folder already has an epub
    try:
        assert d["Cibola Burn"].action == "skip-existing"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ambiguous_multiple_candidates_becomes_review():
    tmp, lib, ab, d = _run(
        [("Dune", "Frank Herbert", "Dune - Frank Herbert", {})],
        [("Frank Herbert", "Dune [B00AAAAAA1]", False),
         ("Frank Herbert", "Dune [B00BBBBBB2]", False)])  # two editions, same title
    try:
        assert d["Dune"].action == "review" and d["Dune"].tier == "ambiguous"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_apply_creates_hardlink_and_is_idempotent():
    tmp, lib, ab, d = _run(
        [("Cibola Burn", "James S.A. Corey", "Cibola Burn - James S.A. Corey", {})],
        [("James S. A. Corey", "Cibola Burn [B00K7PP15W]", False)])
    try:
        dec = d["Cibola Burn"]
        assert dec.action == "link"
        st1 = m.do_link(dec.target, dec.ebook.epub_src)
        assert st1 == "linked" and os.path.exists(dec.target)
        # same inode as the canonical (hard link, not a copy)
        assert os.path.samefile(dec.target, dec.ebook.epub_src)
        # canonical still present and untouched
        assert os.path.exists(dec.ebook.epub_src)
        # re-run is idempotent
        assert m.do_link(dec.target, dec.ebook.epub_src) == "already-linked"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS {fn.__name__}")
        except Exception as e:
            failed += 1; print(f"  FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
