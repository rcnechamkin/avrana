"""The one disposable cache: a stdlib `sqlite3` store, in memory by default.

Status: proposed, not deployed. Standard library only.

This follows the approved design (`docs/design/MEDIA-2.0.md` section 3: "a small SQLite file ...
disposable: deleting it costs a slower first page, nothing else"). There is exactly ONE mechanism,
`DisposableCache`; `MemberCache` and `SharedCache` are thin facades over it with the interfaces the
adapters already use.

Two databases are attached to one connection, both behind one lock and one quota code path:

  * `main`   : `:memory:` by default; a FILE only if the application configures a path. Only data
               classes listed in `persist_classes` (default: just "catalogue") are ever written here.
  * `member` : always `:memory:`. Every other class, in particular everything keyed by a member
               (`member_progress`, `member_mapping`, `artwork`), lives only here by default, so
               per-member watch state never reaches a disk file unless the owner decides it may
               (an open decision, see ADAPTER-CONTRACT.md section 5).

Disposable by construction: a file database is DELETED AND RECREATED at start (never migrated, never
a system of record, never backed up), created mode 0600, `PRAGMA secure_delete=ON`, rollback journal
kept in memory (no sidecar files), schema version in `user_version`. Any sqlite error is a MISS and the
cache is rebuilt; no database exception ever reaches a caller. A path that cannot be used degrades to
memory.

Keys: a member's partition key and every entry key are HMAC-SHA256 under a per-process random key
generated at start, so neither a file nor a memory dump holds usernames, service names, item ids or
artwork references as key material, and a file left on disk is useless after a restart. VALUES (titles,
progress, image bytes) are stored as plaintext JSON; that is why member classes stay out of the file.

Member-scoped misuse resistance by API shape: member data goes through `MemberCache.for_member(
principal)`, which requires a parser-minted principal; the returned scope can only read, write and
delete inside that member's partition; there is no call that lists or scans across members.
`SharedCache` is a separate facade for permission-independent data and only accepts "catalogue".

Bounds: a total entry bound and byte bound, a per-member entry and byte quota (a member over quota
evicts only their own oldest entries; under global pressure the member holding the most bytes loses
entries first), and an entry larger than the per-member byte quota is not stored.
"""
from __future__ import annotations

import base64
import dataclasses
import enum
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from typing import Any, Dict, Optional

from .principal import MemberPrincipal, is_minted_principal
from .resilience import Clock

MAX_ENTRIES = 2048
MAX_BYTES = 32 * 1024 * 1024
MEMBER_MAX_ENTRIES = 128
MEMBER_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_SIZE = 512
SCHEMA_VERSION = 1

# Data classes. Member-scoped writes may use the first three; shared writes only "catalogue".
KNOWN_CLASSES = ("member_progress", "member_mapping", "catalogue", "artwork")
MEMBER_CLASSES = ("member_progress", "member_mapping", "artwork")
DEFAULT_PERSIST_CLASSES = frozenset({"catalogue"})


# ---- value codec: JSON for primitives, tagged JSON for registered immutable domain types ------
_REGISTRY: Dict[str, type] = {}


def register_cacheable(*types: type) -> None:
    """Whitelist dataclasses and enums that may be stored (and rebuilt) by name."""
    for t in types:
        _REGISTRY[t.__name__] = t


def _enc(v: Any) -> Any:
    if isinstance(v, enum.Enum):
        if _REGISTRY.get(type(v).__name__) is not type(v):
            raise TypeError("unregistered enum")
        return {"$e": [type(v).__name__, v.value]}
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (bytes, bytearray)):
        return {"$b": base64.b64encode(bytes(v)).decode("ascii")}
    if isinstance(v, tuple):
        return {"$t": [_enc(x) for x in v]}
    if isinstance(v, list):
        return [_enc(x) for x in v]
    if dataclasses.is_dataclass(v) and not isinstance(v, type) and _REGISTRY.get(type(v).__name__) is type(v):
        return {"$d": type(v).__name__, "f": {f.name: _enc(getattr(v, f.name)) for f in dataclasses.fields(v)}}
    raise TypeError("not cacheable")


def _dec(o: Any) -> Any:
    if isinstance(o, list):
        return [_dec(x) for x in o]
    if isinstance(o, dict):
        if "$b" in o:
            return base64.b64decode(o["$b"])
        if "$t" in o:
            return tuple(_dec(x) for x in o["$t"])
        if "$e" in o:
            name, value = o["$e"]
            return _REGISTRY[name](value)
        if "$d" in o:
            return _REGISTRY[o["$d"]](**{k: _dec(x) for k, x in o["f"].items()})
        raise ValueError("unknown tag")
    return o


def _dumps(value: Any) -> str:
    return json.dumps(_enc(value), separators=(",", ":"))


def _loads(text: str) -> Any:
    return _dec(json.loads(text))


_TABLE = ("CREATE TABLE IF NOT EXISTS {s}.entries ("
          "k TEXT PRIMARY KEY, owner TEXT NOT NULL, class TEXT NOT NULL, expires REAL NOT NULL, "
          "size INTEGER NOT NULL, value TEXT NOT NULL)")
_INDEX = "CREATE INDEX IF NOT EXISTS {s}.entries_owner ON entries(owner, expires)"
_VIEW = ("CREATE TEMP VIEW IF NOT EXISTS all_entries AS "
         "SELECT 'main' AS db, k, owner, expires, size, value FROM main.entries "
         "UNION ALL SELECT 'member' AS db, k, owner, expires, size, value FROM member.entries")


class DisposableCache:
    def __init__(self, clock: Clock, max_entries: int = MAX_ENTRIES, max_bytes: int = MAX_BYTES,
                 member_max_entries: int = MEMBER_MAX_ENTRIES, member_max_bytes: int = MEMBER_MAX_BYTES,
                 path: Optional[str] = None, persist_classes=DEFAULT_PERSIST_CLASSES):
        self._clock = clock
        self._max = max_entries
        self._max_bytes = max_bytes
        self._owner_max = member_max_entries
        self._owner_max_bytes = member_max_bytes
        persist = frozenset(persist_classes)
        if not persist <= set(KNOWN_CLASSES):
            raise ValueError("unknown data class in persist_classes")
        self._persist = persist
        self.path = path
        self._hkey = secrets.token_bytes(32)          # per process, never stored: files die with restarts
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._closed = False
        self._open()

    # ---- lifecycle -------------------------------------------------------------------------
    def _remove_files(self) -> None:
        if not self.path:
            return
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(self.path + suffix)
            except FileNotFoundError:
                pass

    def _open(self) -> None:
        """(Re)create the store from nothing. Never raises: failure leaves an in-memory store."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None
            for attempt_path in ((self.path, None) if self.path else (None,)):
                try:
                    self._conn = self._create(attempt_path)
                    if attempt_path is None and self.path:
                        self.path = None              # the file could not be used: memory only
                    return
                except (sqlite3.Error, OSError):
                    self._conn = None
            self._closed = True                       # cannot even build memory: behave as all misses

    def _create(self, path: Optional[str]) -> sqlite3.Connection:
        if path:
            for suffix in ("", "-journal", "-wal", "-shm"):
                try:
                    os.remove(path + suffix)
                except FileNotFoundError:
                    pass
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(fd)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        conn = sqlite3.connect(path or ":memory:", check_same_thread=False, isolation_level=None)
        try:
            conn.execute("PRAGMA secure_delete=ON")
            conn.execute("PRAGMA synchronous=OFF")
            conn.execute("PRAGMA journal_mode=MEMORY")
            conn.execute("ATTACH DATABASE ':memory:' AS member")
            conn.execute("PRAGMA member.secure_delete=ON")
            for schema in ("main", "member"):
                conn.execute(_TABLE.format(s=schema))
                conn.execute(_INDEX.format(s=schema))
            conn.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)
            conn.execute(_VIEW)
        except BaseException:
            conn.close()
            raise
        return conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
            self._conn = None
            self._closed = True

    def _rebuild(self) -> None:
        with self._lock:
            self._open()

    # ---- plumbing --------------------------------------------------------------------------
    def _exec(self, sql: str, params=()):
        return self._conn.execute(sql, params)

    def _h(self, *parts: str) -> str:
        return hmac.new(self._hkey, "\x1f".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()

    def _db_for(self, data_class: str) -> str:
        return "main" if data_class in self._persist else "member"

    def _delete_key(self, k: str) -> None:
        for schema in ("main", "member"):
            self._exec("DELETE FROM %s.entries WHERE k=?" % schema, (k,))

    def _purge_expired(self, now: float) -> None:
        for schema in ("main", "member"):
            self._exec("DELETE FROM %s.entries WHERE expires<=?" % schema, (now,))

    def _usage(self, owner: Optional[str] = None):
        if owner is None:
            return self._exec("SELECT count(*), coalesce(sum(size),0) FROM all_entries").fetchone()
        return self._exec("SELECT count(*), coalesce(sum(size),0) FROM all_entries WHERE owner=?",
                          (owner,)).fetchone()

    def _evict_oldest_of(self, owner: str) -> bool:
        row = self._exec("SELECT db, k FROM all_entries WHERE owner=? ORDER BY expires LIMIT 1",
                         (owner,)).fetchone()
        if row is None:
            return False
        self._exec("DELETE FROM %s.entries WHERE k=?" % row[0], (row[1],))
        return True

    # ---- engine operations (keys are already hashed) ----------------------------------------
    def _get(self, k: str) -> Optional[Any]:
        with self._lock:
            if self._conn is None:
                return None
            try:
                row = self._exec("SELECT db, expires, value FROM all_entries WHERE k=?", (k,)).fetchone()
                if row is None:
                    return None
                if self._clock.now() >= row[1]:
                    self._exec("DELETE FROM %s.entries WHERE k=?" % row[0], (k,))
                    return None
                try:
                    return _loads(row[2])
                except (ValueError, KeyError, TypeError):
                    self._exec("DELETE FROM %s.entries WHERE k=?" % row[0], (k,))
                    return None
            except sqlite3.Error:
                self._rebuild()
                return None

    def _set(self, owner: str, k: str, data_class: str, value: Any, ttl: float, size: int) -> None:
        if ttl <= 0 or size > self._owner_max_bytes:
            return
        try:
            payload = _dumps(value)
        except (TypeError, ValueError, OverflowError):
            return                                     # not a cacheable type: simply not stored
        with self._lock:
            if self._conn is None:
                return
            try:
                self._exec("BEGIN IMMEDIATE")
                try:
                    self._delete_key(k)
                    count, used = self._usage(owner)
                    if count >= self._owner_max or used + size > self._owner_max_bytes:
                        self._purge_expired(self._clock.now())
                    while True:                         # the member's own quota: evict their own entries
                        count, used = self._usage(owner)
                        if count < self._owner_max and used + size <= self._owner_max_bytes:
                            break
                        if not self._evict_oldest_of(owner):
                            break
                    count, used = self._usage()
                    if count >= self._max or used + size > self._max_bytes:
                        self._purge_expired(self._clock.now())
                    while True:                         # global pressure: the heaviest member pays first
                        count, used = self._usage()
                        if count < self._max and used + size <= self._max_bytes:
                            break
                        heavy = self._exec("SELECT owner FROM (SELECT owner, sum(size) s, count(*) c "
                                           "FROM all_entries GROUP BY owner) ORDER BY s DESC, c DESC LIMIT 1"
                                           ).fetchone()
                        if heavy is None or not self._evict_oldest_of(heavy[0]):
                            break
                    self._exec("INSERT INTO %s.entries (k, owner, class, expires, size, value) "
                               "VALUES (?,?,?,?,?,?)" % self._db_for(data_class),
                               (k, owner, data_class, self._clock.now() + ttl, size, payload))
                    self._exec("COMMIT")
                except BaseException:
                    try:
                        self._exec("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    raise
            except sqlite3.Error:
                self._rebuild()

    def _delete(self, k: str) -> None:
        with self._lock:
            if self._conn is None:
                return
            try:
                self._delete_key(k)
            except sqlite3.Error:
                self._rebuild()

    def _purge_owner(self, owner: str) -> int:
        with self._lock:
            if self._conn is None:
                return 0
            try:
                n = 0
                for schema in ("main", "member"):
                    n += self._exec("DELETE FROM %s.entries WHERE owner=?" % schema, (owner,)).rowcount
                return n
            except sqlite3.Error:
                self._rebuild()
                return 0

    # ---- public API ------------------------------------------------------------------------
    def for_member(self, principal: MemberPrincipal) -> "MemberScope":
        if not is_minted_principal(principal):
            raise TypeError("the member cache is keyed by a parser-minted MemberPrincipal")
        return MemberScope(self, principal.username)

    def purge_member(self, principal: MemberPrincipal) -> int:
        """Offboarding: forget everything cached for one member. Returns the number of entries."""
        if not is_minted_principal(principal):
            raise TypeError("purge_member takes a parser-minted MemberPrincipal")
        return self._purge_owner(self._h("owner", principal.username))

    def clear(self) -> None:
        with self._lock:
            if self._conn is None:
                return
            try:
                for schema in ("main", "member"):
                    self._exec("DELETE FROM %s.entries" % schema)
            except sqlite3.Error:
                self._rebuild()

    def total_bytes(self) -> int:
        with self._lock:
            if self._conn is None:
                return 0
            try:
                return int(self._usage()[1])
            except sqlite3.Error:
                self._rebuild()
                return 0

    def __len__(self) -> int:
        with self._lock:
            if self._conn is None:
                return 0
            try:
                return int(self._usage()[0])
            except sqlite3.Error:
                self._rebuild()
                return 0


class MemberScope:
    """A view bound to one member. Has no way to name another member."""

    def __init__(self, cache: DisposableCache, member: str):
        self._cache = cache
        self._member = member

    def _key(self, service: str, name: str) -> str:
        return self._cache._h("key", self._member, service, name)

    def get(self, service: str, name: str) -> Optional[Any]:
        return self._cache._get(self._key(service, name))

    def set(self, service: str, name: str, value: Any, ttl: float, size: int = DEFAULT_SIZE,
            data_class: str = "member_progress") -> None:
        if data_class not in MEMBER_CLASSES:
            raise ValueError("member-scoped entries must use one of %s" % (MEMBER_CLASSES,))
        self._cache._set(self._cache._h("owner", self._member), self._key(service, name),
                         data_class, value, ttl, size)

    def delete(self, service: str, name: str) -> None:
        self._cache._delete(self._key(service, name))


class MemberCache(DisposableCache):
    """Per-member data (the adapters use this one)."""


class SharedCache(DisposableCache):
    """For permission-independent data only. Never use for library, progress or artwork."""

    def __init__(self, clock: Clock, max_entries: int = MAX_ENTRIES, path: Optional[str] = None,
                 persist_classes=DEFAULT_PERSIST_CLASSES):
        super().__init__(clock, max_entries=max_entries, member_max_entries=max_entries, path=path,
                         persist_classes=persist_classes)

    def get(self, namespace: str, name: str) -> Optional[Any]:
        return self._get(self._h("shared", namespace, name))

    def set(self, namespace: str, name: str, value: Any, ttl: float, size: int = DEFAULT_SIZE,
            data_class: str = "catalogue") -> None:
        if data_class != "catalogue":
            raise ValueError("the shared cache only holds the 'catalogue' class")
        self._set(self._h("owner", "shared"), self._h("shared", namespace, name), data_class,
                  value, ttl, size)
