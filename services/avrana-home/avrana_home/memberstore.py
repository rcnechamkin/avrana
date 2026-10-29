"""Home's member store (owner decision S1, 2026-10-28): the one durable thing Home keeps per member. Standard library
only (sqlite3).

One small SQLite file, owned by Home, separate from the disposable cache (HOME-APP.md §9 used to say "no volume to back
up"; with this store on, the volume joins the backup set). It holds the member's profile (the name shown in Avrana
and their photo, Me → My profile), their one account-wide Home (HOME-02: start place, hidden places, section order;
Customize) and whether they hid the device-setup suggestion (ME-02).

  * Key: the verified username, the same key the adapters use. Safe because usernames are never reused (DECISIONS.md,
    2026-10-27). The member comes only from the verified principal, never from a request.
  * Every record carries `version`. A save names the version it started from; a stale save is refused as a conflict and
    nothing is overwritten (no silent last-write-wins across devices).
  * The photo is stored only as Home's own re-encoded bytes (avatar.py), never the upload.
  * `purge(member)` is the offboarding hook: `python3 -m avrana_home.memberstore purge <username>`
    (docs/runbooks/offboarding.md).
  * One process writes it (one uvicorn worker); a lock serialises this process's writes, WAL keeps reads cheap.
  * If the file can't be opened or read, callers get None and render defaults; nothing writes defaults over a record.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS member_profile (
  member TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  avatar BLOB,
  avatar_etag TEXT NOT NULL DEFAULT '',
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS member_home (
  member TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  start TEXT NOT NULL DEFAULT 'all',
  hidden TEXT NOT NULL DEFAULT '',
  shelf_order TEXT NOT NULL DEFAULT '',
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS member_setup (
  member TEXT PRIMARY KEY,
  hidden_card INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
"""
NAME_MAX = 40
MAX_AVATAR_BYTES = 256 * 1024
SAVED, CONFLICT, INVALID, UNAVAILABLE = "saved", "conflict", "invalid", "unavailable"
# Account-wide Home (HOME-02): the places Home can start on or hide, and its sections. Ids only; labels are Home's.
HOME_PLACES = ("watch", "listen", "comics", "books", "read")
HOME_SHELVES = ("continue", "released", "new")
HOME_ALL = "all"


@dataclass(frozen=True)
class Profile:
    version: int                    # 0 = no record yet
    display_name: str               # "" = use the name from the sign-in service
    avatar_etag: str                # "" = no photo (the initial shows)


EMPTY = Profile(0, "", "")


@dataclass(frozen=True)
class HomePrefs:
    """One Home for the account, on every device (HOME-02): no device or browser override exists anywhere. `hidden`
    is stored rather than "visible", so a place the member gains later appears without anyone saving anything."""
    version: int                    # 0 = no record yet (Home's own defaults)
    start: str = HOME_ALL           # the place Home opens on when the address names none
    hidden: Tuple[str, ...] = ()    # places left off Home (presentation only, never access)
    order: Tuple[str, ...] = HOME_SHELVES


HOME_DEFAULT = HomePrefs(0)


def _home_ok(start: str, hidden: Tuple[str, ...], order: Tuple[str, ...]) -> bool:
    """The record's own shape (the app checks it against the member's places): known ids, no repeats, the start not
    hidden, and every section once."""
    return (start in (HOME_ALL,) + HOME_PLACES and len(set(hidden)) == len(hidden)
            and all(h in HOME_PLACES for h in hidden) and start not in hidden
            and sorted(order) == sorted(HOME_SHELVES))

def clean_name(raw: str) -> Optional[str]:
    """The name as stored: NFC, no control or format characters, single spaces, at most NAME_MAX characters. "" means
    "go back to my sign-in name". None for anything that isn't text or is too long after cleaning."""
    if not isinstance(raw, str):
        return None
    text = unicodedata.normalize("NFC", raw)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    text = " ".join(text.split())
    if len(text) > NAME_MAX:
        return None
    return text


class MemberStore:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time):
        self._path = Path(path)
        self._clock = clock
        self._lock = threading.Lock()
        self._db: Optional[sqlite3.Connection] = None

    def __repr__(self) -> str:
        return "MemberStore(<path>)"

    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            db = sqlite3.connect(str(self._path), timeout=2.0, check_same_thread=False, isolation_level=None)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.executescript(SCHEMA)
            self._db = db
        return self._db

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    def profile(self, member: str) -> Optional[Profile]:
        """The member's profile, EMPTY when they have none, or None when the store can't be read."""
        try:
            with self._lock:
                row = self._conn().execute(
                    "SELECT version, display_name, avatar_etag FROM member_profile WHERE member = ?",
                    (member,)).fetchone()
        except sqlite3.Error:
            return None
        return Profile(int(row[0]), str(row[1]), str(row[2])) if row else EMPTY

    def avatar(self, member: str) -> Optional[Tuple[bytes, str]]:
        """(bytes, etag) of the member's photo, or None (no photo, or the store can't be read)."""
        try:
            with self._lock:
                row = self._conn().execute(
                    "SELECT avatar, avatar_etag FROM member_profile WHERE member = ? AND avatar IS NOT NULL",
                    (member,)).fetchone()
        except sqlite3.Error:
            return None
        return (bytes(row[0]), str(row[1])) if row else None

    def _write(self, member: str, expected_version: int, sets: str, values: tuple,
               table: str = "member_profile") -> Tuple[str, Optional[Profile]]:
        """Insert or update one row of a versioned table (member_profile or member_home, fixed names only), only if its
        version is still `expected_version`. Atomic. Returns the profile for member_profile, else None."""
        assert table in ("member_profile", "member_home")
        now = int(self._clock())
        try:
            with self._lock:
                db = self._conn()
                db.execute("BEGIN IMMEDIATE")
                try:
                    row = db.execute(f"SELECT version FROM {table} WHERE member = ?", (member,)).fetchone()
                    current = int(row[0]) if row else 0
                    if current != expected_version:
                        db.execute("ROLLBACK")
                        return CONFLICT, None
                    if row is None:
                        db.execute(f"INSERT INTO {table} (member, version, updated_at) VALUES (?, 0, ?)",
                                   (member, now))
                    db.execute(f"UPDATE {table} SET {sets}, version = version + 1, updated_at = ? "
                               "WHERE member = ?", values + (now, member))
                    db.execute("COMMIT")
                except BaseException:
                    db.execute("ROLLBACK")
                    raise
        except sqlite3.Error:
            return UNAVAILABLE, None
        return SAVED, (self.profile(member) if table == "member_profile" else None)

    def home(self, member: str) -> Optional[HomePrefs]:
        """The member's Home, HOME_DEFAULT when they never saved one, or None when the store can't be read (callers
        then render Home's defaults and write nothing). A record that no longer passes its own checks reads as the
        defaults with its version kept, so the next save replaces it rather than conflicting."""
        try:
            with self._lock:
                row = self._conn().execute(
                    "SELECT version, start, hidden, shelf_order FROM member_home WHERE member = ?",
                    (member,)).fetchone()
        except sqlite3.Error:
            return None
        if not row:
            return HOME_DEFAULT
        start, hidden = str(row[1]), tuple(h for h in str(row[2]).split(",") if h)
        order = tuple(o for o in str(row[3]).split(",") if o) or HOME_SHELVES
        if not _home_ok(start, hidden, order):
            return HomePrefs(int(row[0]))
        return HomePrefs(int(row[0]), start, hidden, order)

    def save_home(self, member: str, start: str, hidden, order, expected_version: int) -> str:
        """Replace the member's Home as a whole (SAVED, CONFLICT, INVALID or UNAVAILABLE)."""
        hidden, order = tuple(hidden), tuple(order)
        if not _home_ok(start, hidden, order):
            return INVALID
        outcome, _ = self._write(member, expected_version, "start = ?, hidden = ?, shelf_order = ?",
                                 (start, ",".join(hidden), ",".join(order)), table="member_home")
        return outcome

    def setup_hidden(self, member: str) -> Optional[int]:
        """The device-setup card version this member hid (ME-02), 0 if they never did, None if unreadable."""
        try:
            with self._lock:
                row = self._conn().execute("SELECT hidden_card FROM member_setup WHERE member = ?",
                                           (member,)).fetchone()
        except sqlite3.Error:
            return None
        return int(row[0]) if row else 0

    def set_setup_hidden(self, member: str, card: int) -> bool:
        """Hide card version `card` (0 shows it again). Presentation only: no guide progress, no device, no upstream."""
        try:
            with self._lock:
                self._conn().execute(
                    "INSERT INTO member_setup (member, hidden_card, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(member) DO UPDATE SET hidden_card = excluded.hidden_card, "
                    "updated_at = excluded.updated_at", (member, int(card), int(self._clock())))
        except sqlite3.Error:
            return False
        return True

    def save_name(self, member: str, raw_name: str, expected_version: int) -> Tuple[str, Optional[Profile]]:
        name = clean_name(raw_name)
        if name is None:
            return INVALID, None
        return self._write(member, expected_version, "display_name = ?", (name,))

    def save_avatar(self, member: str, data: Optional[bytes], expected_version: int) -> Tuple[str, Optional[Profile]]:
        """Store Home's re-encoded photo (avatar.process), or remove it with None."""
        if data is not None and (not isinstance(data, bytes) or not 0 < len(data) <= MAX_AVATAR_BYTES):
            return INVALID, None
        etag = hashlib.sha256(data).hexdigest()[:20] if data is not None else ""
        return self._write(member, expected_version, "avatar = ?, avatar_etag = ?", (data, etag))

    def holds(self, member: str) -> Optional[bool]:
        """Whether any row is kept for this member (None if unreadable): identity_bindings refuses a release until not."""
        try:
            with self._lock:
                db = self._conn()
                return any(db.execute(f"SELECT 1 FROM {table} WHERE member = ?", (member,)).fetchone()
                           for table in ("member_profile", "member_home", "member_setup"))
        except sqlite3.Error:
            return None

    def purge(self, member: str) -> bool:
        """Offboarding: delete everything Home keeps for this member."""
        try:
            with self._lock:
                db = self._conn()
                db.execute("BEGIN IMMEDIATE")
                try:
                    for table in ("member_profile", "member_home", "member_setup"):
                        db.execute(f"DELETE FROM {table} WHERE member = ?", (member,))
                    db.execute("COMMIT")
                except BaseException:
                    db.execute("ROLLBACK")
                    raise
        except sqlite3.Error:
            return False
        return True


def main(argv=None) -> int:
    """Owner-run offboarding step: `docker exec <home container> python3 -m avrana_home.memberstore purge <username>`.
    Deletes the member's profile (name and photo), their Home settings and setup-card state from the file
    HOME_MEMBER_STORE names. Exit 0 done (or nothing was there), 1 the store couldn't be written, 2 refused (bad
    arguments or no store configured)."""
    import os
    import sys
    args = sys.argv[1:] if argv is None else argv
    path = os.environ.get("HOME_MEMBER_STORE", "")
    if len(args) != 2 or args[0] != "purge" or not args[1].strip() or not path:
        print("usage: HOME_MEMBER_STORE=<file> python3 -m avrana_home.memberstore purge <username>", file=sys.stderr)
        return 2
    store = MemberStore(Path(path))
    try:
        ok = store.purge(args[1])
    finally:
        store.close()
    print(f"{'purged' if ok else 'could not purge'} the Home profile of {args[1]}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
