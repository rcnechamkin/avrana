"""Normalize a companion library snapshot into per-connection book rows.

Identity/dedup is by ASIN. Eligibility is derived conservatively: only titles the companion
explicitly marks as an owned purchase become 'purchased'; Audible Plus / borrowed / anything
unclassified is never treated as purchased. Title text is used only to *flag* ambiguous
matches for review, never as an identity key.
"""
from __future__ import annotations

import sqlite3

from .security import valid_asin

# Statuses that mean "do not (re)queue this book automatically".
TERMINAL_OR_ACTIVE = {"queued", "importing", "imported", "excluded"}


def _classify_eligibility(item: dict) -> str:
    """Map a companion library item to purchased | plus | ineligible."""
    status = str(item.get("purchaseStatus") or item.get("status") or "").lower()
    is_plus = bool(item.get("isPlus") or item.get("plus") or "plus" in status)
    owned = bool(item.get("isPurchased") or item.get("owned") or status in {"purchased", "owned", "active"})
    if is_plus and not owned:
        return "plus"
    if owned:
        return "purchased"
    return "ineligible"


def normalize_and_upsert(
    conn: sqlite3.Connection,
    cid: str,
    snapshot: dict,
    existing_asins: set[str],
    on_disk: set[str] | None = None,
) -> dict:
    """Upsert books from a companion snapshot. `existing_asins` = ASINs already present in
    Avrana (from ABS/library), used to mark 'already'. Returns counts + newly-seen ASINs.

    `on_disk` is the companion's filesystem view of the library. When supplied, any book this
    connector believes it imported but which is NOT on disk is reset to 'available' so it can
    be retried. Without that, a download that exited 0 without producing a file (see the
    output check in the companion's _run_backup) leaves a permanently phantom 'imported' row:
    'imported' is terminal, so no rescan would ever revisit it.
    """
    items = snapshot.get("items") or snapshot.get("library") or []
    seen: set[str] = set()
    newly_seen: list[str] = []
    reviewed = 0

    for item in items:
        asin = str(item.get("asin") or "").strip().upper()
        if not valid_asin(asin):
            reviewed += 1
            continue
        seen.add(asin)
        eligibility = _classify_eligibility(item)
        row = conn.execute(
            "SELECT status FROM book WHERE connection_id=? AND asin=?", (cid, asin)
        ).fetchone()
        title = item.get("title")
        author = item.get("author") or item.get("authors")
        narrator = item.get("narrator") or item.get("narrators")
        runtime = item.get("runtimeMinutes") or item.get("runtime_min")
        cover = item.get("coverUrl") or item.get("cover")
        # Ambiguous match flag: companion signalled a soft/title-only match.
        review = bool(item.get("ambiguous") or item.get("needsReview"))

        if row is None:
            newly_seen.append(asin)
            status = "available"
            if eligibility != "purchased":
                status = "excluded" if eligibility == "plus" else "available"
            elif asin in existing_asins:
                status = "already"
            if review:
                status = "review"
            conn.execute(
                "INSERT INTO book(connection_id, asin, title, author, narrator, runtime_min,"
                " cover_url, eligibility, status) VALUES (?,?,?,?,?,?,?,?,?)",
                (cid, asin, title, author, narrator, runtime, cover, eligibility, status),
            )
        else:
            # Preserve lifecycle statuses; only refresh metadata + eligibility.
            keep = row["status"]
            new_status = keep
            if keep == "available" and eligibility == "purchased" and asin in existing_asins:
                new_status = "already"
            elif keep == "imported" and on_disk is not None and asin not in on_disk:
                # An import was recorded that left nothing on disk, so make it retryable.
                new_status = "available"
            conn.execute(
                "UPDATE book SET title=?, author=?, narrator=?, runtime_min=?, cover_url=?,"
                " eligibility=?, status=?, updated_at=datetime('now') "
                "WHERE connection_id=? AND asin=?",
                (title, author, narrator, runtime, cover, eligibility, new_status, cid, asin),
            )
    return {
        "seen": len(seen),
        "newly_seen": newly_seen,
        "review": reviewed,
    }


def select_books(conn: sqlite3.Connection, cid: str, asins: list[str]) -> int:
    """Mark eligible, importable books as selected. Ignores ineligible/already/imported."""
    changed = 0
    for asin in asins:
        cur = conn.execute(
            "UPDATE book SET status='selected', updated_at=datetime('now') "
            "WHERE connection_id=? AND asin=? AND eligibility='purchased' "
            "AND status IN ('available','review')",
            (cid, asin),
        )
        changed += cur.rowcount
    return changed


def select_all_new(conn: sqlite3.Connection, cid: str) -> int:
    cur = conn.execute(
        "UPDATE book SET status='selected', updated_at=datetime('now') "
        "WHERE connection_id=? AND eligibility='purchased' AND status='available'",
        (cid,),
    )
    return cur.rowcount


def exclude_book(conn: sqlite3.Connection, cid: str, asin: str) -> None:
    conn.execute(
        "UPDATE book SET status='excluded', updated_at=datetime('now') "
        "WHERE connection_id=? AND asin=? AND status NOT IN ('imported','importing','queued')",
        (cid, asin),
    )
