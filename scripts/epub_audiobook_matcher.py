#!/usr/bin/env python3
"""Associate owned EPUBs with their matching audiobook so Audiobookshelf shows a "Read" button.

ABS has no cross-folder ebook matcher (upstream feature #3062), so the association is done by
placing the EPUB *inside* the audiobook's item folder. This tool finds, for each EPUB in the
Calibre library, the one audiobook it belongs to and **hard-links** the EPUB into that folder.

Conservative by construction:
  * Identity first: a shared identifier (ISBN/ASIN) wins; then exact normalized author+title;
    then same-author + title-prefix (handles the ubiquitous ": A Novel" / ": Book N" / series
    suffix on audiobook titles). Only these three tiers auto-link.
  * Weaker signals (fuzzy title, multiple candidates, author-only) become REVIEW items, never
    auto-links.
  * Never moves, renames, copies, or deletes the canonical Calibre file — it only creates a
    hard link (same filesystem => no extra space, no second copy of the bytes).
  * Never creates an ABS entry for an EPUB that has no audiobook (EPUB-only titles are ignored).
  * Idempotent: if the audiobook folder already holds an .epub (e.g. a manual association, or a
    previous run) it is left untouched.
  * Dry-run by default; prints exactly what it WOULD do. Pass --apply to make changes.

Not a Whispersync clone — this is purely file placement for ABS's read-along/download button.

Usage:
  epub_audiobook_matcher.py            # dry-run report
  epub_audiobook_matcher.py --apply    # create the hard links
  epub_audiobook_matcher.py --json     # machine-readable report
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher

CALIBRE_LIBRARY = "/mnt/avrana_media/calibre-library"
AUDIOBOOKS_ROOT = "/mnt/avrana_media/audiobooks"
ASIN_RE = re.compile(r"\[([A-Z0-9]{10})\]\s*$")
FUZZY_REVIEW_THRESHOLD = 0.90   # same-author fuzzy title at/above this => REVIEW (never auto)
MIN_PREFIX_LEN = 5              # ignore trivially-short title prefixes


# ---- normalization (pure) -----------------------------------------------------------------
def _alnum_tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t]


def author_key(name: str) -> str:
    """Order-insensitive author key: sorted alnum tokens. Matches 'James S.A. Corey',
    'James S. A. Corey', and Calibre's 'Corey, James S. A.' to the same value."""
    return "".join(sorted(_alnum_tokens(name)))


def strip_asin(name: str) -> str:
    return ASIN_RE.sub("", name).strip()


def title_key(title: str) -> str:
    """Normalized title: drop a trailing [ASIN], lowercase, keep only alphanumerics."""
    return "".join(_alnum_tokens(strip_asin(title)))


# ---- data ---------------------------------------------------------------------------------
@dataclass
class Ebook:
    book_id: int
    title: str
    author: str
    ids: dict           # {type: val} from Calibre identifiers
    epub_src: str       # absolute path to the .epub in the Calibre library
    akey: str = ""
    tkey: str = ""


@dataclass
class Audiobook:
    folder: str         # absolute path to the item folder
    author: str
    title: str          # folder basename WITHOUT the [ASIN]
    asin: str | None
    has_epub: bool
    akey: str = ""
    tkey: str = ""


@dataclass
class Decision:
    ebook: Ebook
    action: str                     # link | skip-existing | review | no-match
    tier: str = ""                  # id | exact | prefix | fuzzy | ambiguous | author-only
    audiobook: Audiobook | None = None
    target: str | None = None
    detail: str = ""
    candidates: list = field(default_factory=list)


# ---- indexing -----------------------------------------------------------------------------
def load_ebooks(library: str) -> list[Ebook]:
    db = os.path.join(library, "metadata.db")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out: list[Ebook] = []
    for bid, title, path in c.execute("SELECT id, title, path FROM books"):
        row = c.execute(
            "SELECT name FROM data WHERE book=? AND format='EPUB' LIMIT 1", (bid,)
        ).fetchone()
        if not row:
            continue  # no EPUB for this book -> nothing to associate
        epub_src = os.path.join(library, path, row[0] + ".epub")
        author = (c.execute(
            "SELECT a.name FROM authors a JOIN books_authors_link l ON l.author=a.id "
            "WHERE l.book=? ORDER BY l.id LIMIT 1", (bid,)).fetchone() or [""])[0]
        ids = {t: v for t, v in c.execute(
            "SELECT type, val FROM identifiers WHERE book=?", (bid,))}
        out.append(Ebook(bid, title, author, ids, epub_src,
                         author_key(author), title_key(title)))
    c.close()
    return out


def scan_audiobooks(root: str) -> list[Audiobook]:
    out: list[Audiobook] = []
    for author in sorted(os.listdir(root)):
        apath = os.path.join(root, author)
        if not os.path.isdir(apath):
            continue
        for folder in sorted(os.listdir(apath)):
            fpath = os.path.join(apath, folder)
            if not os.path.isdir(fpath):
                continue
            m = ASIN_RE.search(folder)
            title = strip_asin(folder)
            has_epub = any(f.lower().endswith(".epub") for f in os.listdir(fpath))
            out.append(Audiobook(fpath, author, title, m.group(1) if m else None,
                                  has_epub, author_key(author), title_key(folder)))
    return out


# ---- matching (pure over the indexes) -----------------------------------------------------
def _prefix_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    lo, hi = sorted((a, b), key=len)
    return len(lo) >= MIN_PREFIX_LEN and hi.startswith(lo)


def classify(ebook: Ebook, audiobooks: list[Audiobook]) -> Decision:
    same_author = [ab for ab in audiobooks if ab.akey and ab.akey == ebook.akey]

    # Tier 1: a shared identifier value (e.g. the same ASIN on both sides). Rare across audio
    # vs text editions, but authoritative when present.
    id_vals = {str(v).upper() for v in ebook.ids.values() if v}
    id_hits = [ab for ab in audiobooks if ab.asin and ab.asin.upper() in id_vals]

    # Tier 2/3 candidates among same-author audiobooks.
    exact = [ab for ab in same_author if ab.tkey == ebook.tkey]
    prefix = [ab for ab in same_author if ab not in exact and _prefix_match(ebook.tkey, ab.tkey)]

    confident = id_hits or exact or prefix
    tier = "id" if id_hits else "exact" if exact else "prefix" if prefix else ""

    if confident:
        if len(confident) > 1:
            return Decision(ebook, "review", "ambiguous",
                            detail=f"{len(confident)} confident audiobook candidates",
                            candidates=[ab.folder for ab in confident])
        ab = confident[0]
        if ab.has_epub:
            return Decision(ebook, "skip-existing", tier, ab,
                            detail="audiobook folder already has an .epub")
        target = os.path.join(ab.folder, os.path.basename(ab.folder) + ".epub")
        return Decision(ebook, "link", tier, ab, target=target)

    # Weak signals -> REVIEW, never auto-link.
    fuzzy = [(ab, SequenceMatcher(None, ebook.tkey, ab.tkey).ratio()) for ab in same_author]
    fuzzy = sorted([(ab, r) for ab, r in fuzzy if r >= FUZZY_REVIEW_THRESHOLD],
                   key=lambda x: -x[1])
    if fuzzy:
        return Decision(ebook, "review", "fuzzy",
                        detail="; ".join(f"{ab.title} ({r:.0%})" for ab, r in fuzzy[:4]),
                        candidates=[ab.folder for ab, _ in fuzzy])
    if same_author:
        return Decision(ebook, "review", "author-only",
                        detail=f"{len(same_author)} audiobook(s) by this author, no title match",
                        candidates=[ab.folder for ab in same_author[:6]])
    return Decision(ebook, "no-match")


# ---- apply --------------------------------------------------------------------------------
def do_link(target: str, src: str) -> str:
    """Hard-link src -> target. Returns a status string. Never touches src."""
    if not os.path.exists(src):
        return "src-missing"
    if os.path.exists(target):
        # Same inode already? then it's done; otherwise leave the existing file alone.
        try:
            if os.path.samefile(target, src):
                return "already-linked"
        except OSError:
            pass
        return "target-exists"
    os.link(src, target)   # hard link; same fs required (both under /mnt/avrana_media)
    return "linked"


# ---- report -------------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Associate EPUBs with audiobooks for ABS.")
    ap.add_argument("--library", default=CALIBRE_LIBRARY)
    ap.add_argument("--audiobooks", default=AUDIOBOOKS_ROOT)
    ap.add_argument("--apply", action="store_true", help="create the hard links (default: dry-run)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    ebooks = load_ebooks(args.library)
    audiobooks = scan_audiobooks(args.audiobooks)
    decisions = [classify(e, audiobooks) for e in ebooks]

    results = []
    for d in decisions:
        status = "dry-run"
        if d.action == "link" and args.apply:
            status = do_link(d.target, d.ebook.epub_src)
        results.append({
            "ebook": d.ebook.title, "author": d.ebook.author,
            "action": d.action, "tier": d.tier,
            "audiobook": os.path.basename(d.audiobook.folder) if d.audiobook else None,
            "target": d.target, "detail": d.detail, "candidates": d.candidates,
            "apply_status": status if d.action == "link" else None,
        })

    if args.json:
        print(json.dumps({"ebooks": len(ebooks), "audiobooks": len(audiobooks),
                          "results": results}, indent=2))
        return 0

    counts: dict = {}
    print(f"EPUBs in library: {len(ebooks)}   audiobook folders: {len(audiobooks)}   "
          f"mode: {'APPLY' if args.apply else 'dry-run'}\n")
    for r in results:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
        icon = {"link": "LINK", "skip-existing": "skip", "review": "REVIEW",
                "no-match": "----"}[r["action"]]
        line = f"  [{icon}] {r['ebook']!r} by {r['author']}"
        if r["action"] == "link":
            line += f"  ->  {r['audiobook']}/  ({r['tier']})"
            if r["apply_status"]:
                line += f"  [{r['apply_status']}]"
        elif r["action"] == "skip-existing":
            line += f"  ({r['audiobook']} already has an epub)"
        elif r["action"] == "review":
            line += f"  ({r['tier']}: {r['detail']})"
        print(line)
    print("\nsummary:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if not args.apply and counts.get("link"):
        print("re-run with --apply to create the hard links.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
