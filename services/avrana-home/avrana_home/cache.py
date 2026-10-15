"""The one disposable cache: a stdlib `sqlite3` store, in memory by default.

Status: proposed, not deployed. Standard library only.

This follows the approved design (`docs/design/MEDIA-2.0.md` section 3: "a small SQLite file ...
disposable: deleting it costs a slower first page, nothing else"). There is exactly ONE mechanism,
`DisposableCache` (the engine); `MemberCache` and `SharedCache` are thin facades over it with the
interfaces the adapters already use. Only `MemberCache` has a member API (`for_member`,
`purge_member`); `SharedCache` has none, so a shared cache can never be asked about a member.

Two databases are attached to one connection, both behind one lock and one quota code path:

  * `main`   : `:memory:` by default; a FILE only if the application configures a path. Only data
               classes listed in `persist_classes` (default: just "catalogue") are ever written here.
  * `member` : always `:memory:`. Every other class, in particular everything keyed by a member
               (`member_progress`, `member_mapping`, `artwork`), lives only here by default, so
               per-member watch state never reaches a disk file unless the owner decides it may
               (an open decision, see ADAPTER-CONTRACT.md section 5).

Disposable by construction: a file database is DELETED AND RECREATED at start (never migrated, never
a system of record, never backed up), created mode 0600 with O_EXCL (and O_NOFOLLOW where the
platform has it), `PRAGMA secure_delete=ON`, rollback journal and temporary tables kept in memory
(no sidecar or temp files), schema version in `user_version`, an `application_id` marking the file as
ours. An EXISTING file at the configured path is deleted only if it is a regular file that is empty
or carries that `application_id`; anything else is refused (one log line, by reason class only) and
the cache runs in memory. Two caches may not share one path (the second is refused loudly).
`close()` removes the file. Any sqlite error is a MISS and the cache is rebuilt; no exception from
the database, the encoder or the decoder ever reaches a caller.

Keys: a member's partition key and every entry key are HMAC-SHA256 under a per-process random key
generated at start (every part length-prefixed, so no two part lists give one input), so neither a
file nor a memory dump holds usernames, service names, item ids or artwork references as key
material. VALUES (titles, progress, image bytes) are stored as plaintext; that is why member classes
stay out of the file.

Bounds are in STORED bytes: the cache measures the encoded payload itself (the text column plus any
binary column plus a fixed per-row overhead); a caller cannot declare a smaller size. A total entry
and byte bound, a per-member entry and byte quota (a member over quota evicts only their own entries;
under global pressure the member holding the most bytes loses entries first), and an entry larger
than the per-member byte quota is not stored. Within one member eviction goes by class (artwork, then
section data, then the mapping last) and then by age.
"""
from __future__ import annotations

import dataclasses
import enum
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import stat
import threading
import typing
from typing import Any, Dict, List, Optional, Tuple

from .principal import MemberPrincipal, is_minted_principal
from .resilience import Clock, log

MAX_ENTRIES = 2048
MAX_BYTES = 32 * 1024 * 1024
MEMBER_MAX_ENTRIES = 128
MEMBER_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_SIZE = 512            # kept for source compatibility: callers can no longer declare a size
STORED_OVERHEAD = 200         # fixed per-row cost added to the measured payload (keys, class, expiry)
SCHEMA_VERSION = 2
APPLICATION_ID = int.from_bytes(b"AVRC", "big")

# Data classes. Member-scoped writes may use the first three; shared writes only "catalogue".
KNOWN_CLASSES = ("member_progress", "member_mapping", "catalogue", "artwork")
MEMBER_CLASSES = ("member_progress", "member_mapping", "artwork")
DEFAULT_PERSIST_CLASSES = frozenset({"catalogue"})
# Eviction order inside one owner: lowest first. The mapping goes last because losing it costs a
# user-list round trip on the next request while losing a section only costs that section.
_PRIORITY_SQL = ("CASE dclass WHEN 'artwork' THEN 0 WHEN 'member_progress' THEN 1 "
                 "WHEN 'catalogue' THEN 2 ELSE 3 END")


class CachePathInUseError(RuntimeError):
    """Another live cache already owns this file path."""


class _PathRefused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_PATHS_IN_USE: set = set()
_PATHS_LOCK = threading.Lock()


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


# ---- value codec: JSON for primitives, tagged JSON for registered immutable domain types ------
_REGISTRY: Dict[str, type] = {}
_HINTS: Dict[type, Dict[str, Any]] = {}


def register_cacheable(*types: type) -> None:
    """Whitelist dataclasses and enums that may be stored (and rebuilt) by name."""
    for t in types:
        _REGISTRY[t.__name__] = t


def _enc(v: Any, blobs: List[bytes]) -> Any:
    if isinstance(v, enum.Enum):
        if _REGISTRY.get(type(v).__name__) is not type(v):
            raise TypeError("unregistered enum")
        return {"$e": [type(v).__name__, v.value]}
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (bytes, bytearray)):
        if blobs:
            raise TypeError("one binary field per entry")
        blobs.append(bytes(v))
        return {"$blob": 0}
    if isinstance(v, tuple):
        return {"$t": [_enc(x, blobs) for x in v]}
    if isinstance(v, list):
        return [_enc(x, blobs) for x in v]
    if dataclasses.is_dataclass(v) and not isinstance(v, type) and _REGISTRY.get(type(v).__name__) is type(v):
        return {"$d": type(v).__name__, "f": {f.name: _enc(getattr(v, f.name), blobs)
                                               for f in dataclasses.fields(v)}}
    raise TypeError("not cacheable")


def _conforms(v: Any, hint: Any) -> bool:
    """Does a decoded value have the declared field type? (A tampered row must not become a
    wrongly-typed domain object.)"""
    if hint is Any:
        return True
    origin = typing.get_origin(hint)
    if origin is typing.Union:
        return any(_conforms(v, a) for a in typing.get_args(hint))
    if origin is tuple:
        args = typing.get_args(hint)
        if len(args) == 2 and args[1] is Ellipsis:
            return isinstance(v, tuple) and all(_conforms(x, args[0]) for x in v)
        return isinstance(v, tuple) and len(v) == len(args) and all(_conforms(x, a) for x, a in zip(v, args))
    if hint is type(None):
        return v is None
    if hint is bool:
        return isinstance(v, bool)
    if hint is int:
        return isinstance(v, int) and not isinstance(v, bool)
    if hint is float:
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if isinstance(hint, type):
        return isinstance(v, hint)
    return False


def _dec(o: Any, blob: Optional[bytes]) -> Any:
    if isinstance(o, list):
        return [_dec(x, blob) for x in o]
    if isinstance(o, dict):
        if "$blob" in o:
            if len(o) != 1 or type(o["$blob"]) is not int or o["$blob"] != 0 or blob is None:
                raise ValueError("bad blob reference")
            return bytes(blob)
        if "$t" in o:
            if len(o) != 1 or not isinstance(o["$t"], list):
                raise ValueError("bad tuple")
            return tuple(_dec(x, blob) for x in o["$t"])
        if "$e" in o:
            pair = o["$e"]
            if len(o) != 1 or not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str):
                raise ValueError("bad enum")
            cls = _REGISTRY[pair[0]]
            if not (isinstance(cls, type) and issubclass(cls, enum.Enum)):
                raise ValueError("not an enum")
            return cls(pair[1])
        if "$d" in o:
            if set(o) != {"$d", "f"} or not isinstance(o["f"], dict) or not isinstance(o["$d"], str):
                raise ValueError("bad record")
            cls = _REGISTRY[o["$d"]]
            if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
                raise ValueError("not a record")
            names = {f.name for f in dataclasses.fields(cls)}
            if set(o["f"]) != names:
                raise ValueError("wrong fields")
            fields = {k: _dec(x, blob) for k, x in o["f"].items()}
            hints = _HINTS.get(cls)
            if hints is None:
                hints = _HINTS[cls] = typing.get_type_hints(cls)
            for name, value in fields.items():
                if not _conforms(value, hints[name]):
                    raise ValueError("wrong field type")
            return cls(**fields)
        raise ValueError("unknown tag")
    return o


def _dumps(value: Any) -> Tuple[str, Optional[bytes]]:
    """(JSON text, binary payload or None). Raises for anything that is not a registered type."""
    blobs: List[bytes] = []
    text = json.dumps(_enc(value, blobs), separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return text, (blobs[0] if blobs else None)


def _loads(text: str, blob: Optional[bytes] = None) -> Any:
    return _dec(json.loads(text), blob)


_TABLE = ("CREATE TABLE IF NOT EXISTS {s}.entries ("
          "k TEXT PRIMARY KEY, owner TEXT NOT NULL, class TEXT NOT NULL, expires REAL NOT NULL, "
          "size INTEGER NOT NULL, value TEXT NOT NULL, data BLOB)")
_INDEX = "CREATE INDEX IF NOT EXISTS {s}.entries_owner ON entries(owner, expires)"
_VIEW = ("CREATE TEMP VIEW IF NOT EXISTS all_entries AS "
         "SELECT 'main' AS db, k, owner, class AS dclass, expires, size, value, data FROM main.entries "
         "UNION ALL SELECT 'member' AS db, k, owner, class AS dclass, expires, size, value, data "
         "FROM member.entries")
_CHUNK = 400


class DisposableCache:
    """The engine. No member API here: see `MemberCache`."""
    APPLICATION_ID = APPLICATION_ID

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
        self._claimed: Optional[str] = None
        self._owned = False                           # did WE create the file at self.path?
        self._hkey = secrets.token_bytes(32)          # per process, never stored: files die with restarts
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._closed = False
        if path:
            key = _path_key(path)
            with _PATHS_LOCK:
                if key in _PATHS_IN_USE:
                    raise CachePathInUseError("another cache already uses this path")
                _PATHS_IN_USE.add(key)
            self._claimed = key
        try:
            self._open()
        except BaseException:
            self._release_claim()
            raise

    # ---- lifecycle -------------------------------------------------------------------------
    def _release_claim(self) -> None:
        if self._claimed is not None:
            with _PATHS_LOCK:
                _PATHS_IN_USE.discard(self._claimed)
            self._claimed = None

    def _remove_files(self) -> None:
        if not self.path:
            return
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(self.path + suffix)
            except OSError:
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
            if self.path:
                try:
                    self._conn = self._create(self.path, trusted=self._owned)
                    self._owned = True
                    return
                except _PathRefused as exc:
                    log.warning("cache_path_refused reason=%s", exc.reason)
                    self._owned = False
                except (sqlite3.Error, OSError) as exc:
                    log.warning("cache_path_unusable error=%s", type(exc).__name__)
                    if self._owned:
                        self._remove_files()
                    self._owned = False
                self._release_claim()
                self.path = None                      # the file cannot be used: memory only
            try:
                self._conn = self._create(None, trusted=False)
            except (sqlite3.Error, OSError):
                self._conn = None
                self._closed = True                   # cannot even build memory: behave as all misses

    @staticmethod
    def _is_ours(path: str) -> bool:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags)
        try:
            header = os.read(fd, 100)
        finally:
            os.close(fd)
        return (len(header) >= 72 and header[:16] == b"SQLite format 3\x00"
                and int.from_bytes(header[68:72], "big") == APPLICATION_ID)

    def _prepare_path(self, path: str, trusted: bool) -> None:
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(st.st_mode):
            raise _PathRefused("not_a_regular_file")
        if st.st_size > 0 and not trusted:
            try:
                ours = self._is_ours(path)
            except OSError:
                raise _PathRefused("unreadable") from None
            if not ours:
                raise _PathRefused("not_a_cache_file")
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass

    def _create(self, path: Optional[str], trusted: bool) -> sqlite3.Connection:
        created = False
        if path:
            self._prepare_path(path, trusted)
            flags = (os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_BINARY", 0))
            fd = os.open(path, flags, 0o600)
            os.close(fd)
            created = True
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        conn = sqlite3.connect(path or ":memory:", check_same_thread=False, isolation_level=None)
        try:
            conn.execute("PRAGMA temp_store=MEMORY")          # no temp files, ever
            conn.execute("PRAGMA secure_delete=ON")
            conn.execute("PRAGMA synchronous=OFF")
            conn.execute("PRAGMA journal_mode=MEMORY")
            conn.execute("PRAGMA application_id=%d" % APPLICATION_ID)
            conn.execute("ATTACH DATABASE ':memory:' AS member")
            conn.execute("PRAGMA member.secure_delete=ON")
            for schema in ("main", "member"):
                conn.execute(_TABLE.format(s=schema))
                conn.execute(_INDEX.format(s=schema))
            conn.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)
            conn.execute(_VIEW)
        except BaseException:
            conn.close()
            if created:
                self._remove_files_at(path)
            raise
        return conn

    @staticmethod
    def _remove_files_at(path: str) -> None:
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
            self._conn = None
            self._closed = True
            if self._owned:
                self._remove_files()                  # a disposable file does not outlive its cache
                self._owned = False
            self._release_claim()

    def _rebuild(self) -> None:
        with self._lock:
            self._open()

    # ---- plumbing --------------------------------------------------------------------------
    def _exec(self, sql: str, params=()):
        return self._conn.execute(sql, params)

    def _h(self, *parts: str) -> str:
        mac = hmac.new(self._hkey, digestmod=hashlib.sha256)
        for part in parts:
            raw = part.encode("utf-8", "surrogatepass")
            mac.update(len(raw).to_bytes(4, "big"))          # length-prefixed: parts cannot run together
            mac.update(raw)
        return mac.hexdigest()

    def _db_for(self, data_class: str) -> str:
        return "main" if data_class in self._persist else "member"

    def _delete_key(self, k: str) -> None:
        for schema in ("main", "member"):
            self._exec("DELETE FROM %s.entries WHERE k=?" % schema, (k,))

    def _delete_many(self, victims: List[Tuple[str, str]]) -> None:
        by_db: Dict[str, List[str]] = {}
        for db, key in victims:
            by_db.setdefault(db, []).append(key)
        for db, keys in by_db.items():
            for i in range(0, len(keys), _CHUNK):
                chunk = keys[i:i + _CHUNK]
                self._exec("DELETE FROM %s.entries WHERE k IN (%s)" % (db, ",".join("?" * len(chunk))), chunk)

    def _purge_expired(self, now: float) -> None:
        for schema in ("main", "member"):
            self._exec("DELETE FROM %s.entries WHERE expires<=?" % schema, (now,))

    def _usage(self, owner: Optional[str] = None):
        if owner is None:
            return self._exec("SELECT count(*), coalesce(sum(size),0) FROM all_entries").fetchone()
        return self._exec("SELECT count(*), coalesce(sum(size),0) FROM all_entries WHERE owner=?",
                          (owner,)).fetchone()

    def _candidates(self, owner: str):
        return self._exec("SELECT db, k, size FROM all_entries WHERE owner=? ORDER BY %s, expires"
                          % _PRIORITY_SQL, (owner,))

    # ---- engine operations (keys are already hashed) ----------------------------------------
    def _get(self, k: str) -> Optional[Any]:
        with self._lock:
            if self._conn is None:
                return None
            try:
                row = self._exec("SELECT db, expires, value, data FROM all_entries WHERE k=?", (k,)).fetchone()
                if row is None:
                    return None
                if self._clock.now() >= row[1]:
                    self._exec("DELETE FROM %s.entries WHERE k=?" % row[0], (k,))
                    return None
                try:
                    return _loads(row[2], row[3])
                except Exception:                       # tampered or corrupt row: a miss, and gone
                    self._exec("DELETE FROM %s.entries WHERE k=?" % row[0], (k,))
                    return None
            except sqlite3.Error:
                self._rebuild()
                return None

    def _refuse(self, k: str) -> None:
        """A write that is not stored must not leave the previous value behind."""
        self._delete(k)

    def _set(self, owner: str, k: str, data_class: str, value: Any, ttl: float, size: Any = None) -> None:
        # `size` is accepted for source compatibility and IGNORED: the stored length is measured here.
        if (not isinstance(ttl, (int, float)) or isinstance(ttl, bool)
                or not 0 < ttl < math.inf):               # also refuses NaN
            return self._refuse(k)
        try:
            text, blob = _dumps(value)
            text.encode("utf-8")
        except Exception:                                 # RecursionError, OverflowError, ... : not stored
            return self._refuse(k)
        stored = len(text.encode("utf-8")) + (len(blob) if blob is not None else 0) + STORED_OVERHEAD
        if stored > self._owner_max_bytes or stored > self._max_bytes:
            return self._refuse(k)
        with self._lock:
            if self._conn is None:
                return
            try:
                self._exec("BEGIN IMMEDIATE")
                try:
                    self._delete_key(k)
                    now = self._clock.now()
                    count, used = self._usage(owner)
                    if count + 1 > self._owner_max or used + stored > self._owner_max_bytes:
                        self._purge_expired(now)
                        count, used = self._usage(owner)
                        if count + 1 > self._owner_max or used + stored > self._owner_max_bytes:
                            self._evict_owner(owner, count, used, stored)
                    count, used = self._usage()
                    if count + 1 > self._max or used + stored > self._max_bytes:
                        self._purge_expired(now)
                        count, used = self._usage()
                        if count + 1 > self._max or used + stored > self._max_bytes:
                            self._evict_global(count, used, stored)
                    self._exec("INSERT INTO %s.entries (k, owner, class, expires, size, value, data) "
                               "VALUES (?,?,?,?,?,?,?)" % self._db_for(data_class),
                               (k, owner, data_class, now + ttl, stored, text, blob))
                    self._exec("COMMIT")
                except BaseException:
                    try:
                        self._exec("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    raise
            except sqlite3.Error:
                self._rebuild()

    def _evict_owner(self, owner: str, count: int, used: int, stored: int) -> None:
        """One pass: the member's own entries, lowest class first, oldest first, until the new entry fits."""
        victims = []
        for db, key, size in self._candidates(owner).fetchall():
            if count + 1 <= self._owner_max and used + stored <= self._owner_max_bytes:
                break
            victims.append((db, key))
            count -= 1
            used -= size
        self._delete_many(victims)

    def _evict_global(self, count: int, used: int, stored: int) -> None:
        """One pass: the heaviest member pays first (their own lowest class, oldest entries)."""
        stats = {row[0]: [row[1], row[2]] for row in self._exec(
            "SELECT owner, sum(size), count(*) FROM all_entries GROUP BY owner")}
        iterators: Dict[str, Any] = {}
        victims = []
        while count + 1 > self._max or used + stored > self._max_bytes:
            if not stats:
                break
            heavy = max(stats, key=lambda o: (stats[o][0], stats[o][1]))
            if heavy not in iterators:
                iterators[heavy] = iter(self._candidates(heavy).fetchall())
            nxt = next(iterators[heavy], None)
            if nxt is None:
                del stats[heavy]
                continue
            db, key, size = nxt
            victims.append((db, key))
            stats[heavy][0] -= size
            stats[heavy][1] -= 1
            count -= 1
            used -= size
        self._delete_many(victims)

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

    def set(self, service: str, name: str, value: Any, ttl: float, size: Any = None,
            data_class: str = "member_progress") -> None:
        """`size` is ignored (kept so existing callers still bind): the cache measures what it stores."""
        if data_class not in MEMBER_CLASSES:
            raise ValueError("member-scoped entries must use one of %s" % (MEMBER_CLASSES,))
        self._cache._set(self._cache._h("owner", self._member), self._key(service, name),
                         data_class, value, ttl)

    def delete(self, service: str, name: str) -> None:
        self._cache._delete(self._key(service, name))


class MemberCache(DisposableCache):
    """Per-member data (the adapters use this one). Member data goes through `for_member`, which
    requires a parser-minted principal; the scope it returns can only read, write and delete inside
    that member's partition, and no call lists or scans across members."""

    def for_member(self, principal: MemberPrincipal) -> MemberScope:
        if not is_minted_principal(principal):
            raise TypeError("the member cache is keyed by a parser-minted MemberPrincipal")
        return MemberScope(self, principal.username)

    def purge_member(self, principal: MemberPrincipal) -> int:
        """Offboarding: forget everything cached for one member (both databases). Returns the count."""
        if not is_minted_principal(principal):
            raise TypeError("purge_member takes a parser-minted MemberPrincipal")
        return self._purge_owner(self._h("owner", principal.username))


class SharedCache(DisposableCache):
    """For permission-independent data only. Never use for library, progress or artwork. It has no
    member API at all."""

    def __init__(self, clock: Clock, max_entries: int = MAX_ENTRIES, path: Optional[str] = None,
                 persist_classes=DEFAULT_PERSIST_CLASSES):
        super().__init__(clock, max_entries=max_entries, member_max_entries=max_entries, path=path,
                         persist_classes=persist_classes)

    def get(self, namespace: str, name: str) -> Optional[Any]:
        return self._get(self._h("shared", namespace, name))

    def set(self, namespace: str, name: str, value: Any, ttl: float, size: Any = None,
            data_class: str = "catalogue") -> None:
        if data_class != "catalogue":
            raise ValueError("the shared cache only holds the 'catalogue' class")
        self._set(self._h("shared-owner"), self._h("shared", namespace, name), data_class, value, ttl)
