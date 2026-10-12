"""Small disposable TTL cache. In memory only; deleting it (restarting) costs speed, nothing else.

Status: proposed, not deployed. Standard library only.

Misuse resistance by API shape:
  * Member data goes through `MemberCache.for_member(principal)`, which requires a real,
    parser-minted `MemberPrincipal` (a string or look-alike is rejected). The returned scope can
    only read, write and delete keys inside that member's partition; there is no call that lists,
    scans or reads across members.
  * The member's partition key is the exact username from the principal. Case, whitespace and
    unicode variants are different principals, so they get different partitions.
  * `SharedCache` is a separate class with a separate store, only for data that does NOT depend on
    who is asking. Nothing in the adapter layer uses it for library, progress or artwork data,
    because those depend on the member's permissions.
  * Stored values should be immutable result objects (frozen dataclasses and tuples).

Bounds (so one member cannot push everyone else out):
  * a total entry bound and a total byte bound;
  * a per-member entry quota and a per-member byte quota, enforced by evicting THAT member's own
    oldest-expiring entries first;
  * under global pressure, entries are evicted from the member holding the most bytes first.
An entry larger than the per-member byte quota is not stored at all.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Tuple

from .principal import MemberPrincipal, is_minted_principal
from .resilience import Clock

MAX_ENTRIES = 2048
MAX_BYTES = 32 * 1024 * 1024
MEMBER_MAX_ENTRIES = 128
MEMBER_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_SIZE = 512


class _TTLStore:
    def __init__(self, clock: Clock, max_entries: int, max_bytes: int,
                 owner_max_entries: int, owner_max_bytes: int):
        self._clock = clock
        self._max = max_entries
        self._max_bytes = max_bytes
        self._owner_max = owner_max_entries
        self._owner_max_bytes = owner_max_bytes
        self._data: Dict[Tuple, Tuple[float, Any, int, str]] = {}   # key -> expires, value, size, owner
        self._usage: Dict[str, list] = {}                            # owner -> [entries, bytes]
        self._bytes = 0
        self._lock = threading.Lock()

    # -- internals (lock held) --
    def _drop(self, key: Tuple) -> None:
        _, _, size, owner = self._data.pop(key)
        self._bytes -= size
        use = self._usage[owner]
        use[0] -= 1
        use[1] -= size
        if use[0] <= 0:
            del self._usage[owner]

    def _oldest_of(self, owner: str) -> Optional[Tuple]:
        keys = [k for k, v in self._data.items() if v[3] == owner]
        return min(keys, key=lambda k: self._data[k][0]) if keys else None

    def _purge_expired(self) -> None:
        now = self._clock.now()
        for k in [k for k, v in self._data.items() if v[0] <= now]:
            self._drop(k)

    # -- API --
    def get(self, key: Tuple) -> Optional[Any]:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            if self._clock.now() >= hit[0]:
                self._drop(key)
                return None
            return hit[1]

    def set(self, owner: str, key: Tuple, value: Any, ttl: float, size: int = DEFAULT_SIZE) -> None:
        if ttl <= 0 or size > self._owner_max_bytes:
            return
        with self._lock:
            if key in self._data:
                self._drop(key)
            use = self._usage.get(owner, [0, 0])
            if use[0] >= self._owner_max or use[1] + size > self._owner_max_bytes:
                self._purge_expired()
            while True:                                   # the member's own quota: evict own entries
                use = self._usage.get(owner, [0, 0])
                if use[0] < self._owner_max and use[1] + size <= self._owner_max_bytes:
                    break
                victim = self._oldest_of(owner)
                if victim is None:
                    return
                self._drop(victim)
            if len(self._data) >= self._max or self._bytes + size > self._max_bytes:
                self._purge_expired()
            while len(self._data) >= self._max or self._bytes + size > self._max_bytes:
                heaviest = max(self._usage, key=lambda o: (self._usage[o][1], self._usage[o][0]),
                               default=None)
                victim = self._oldest_of(heaviest) if heaviest is not None else None
                if victim is None:
                    return
                self._drop(victim)
            self._data[key] = (self._clock.now() + ttl, value, size, owner)
            u = self._usage.setdefault(owner, [0, 0])
            u[0] += 1
            u[1] += size
            self._bytes += size

    def delete(self, key: Tuple) -> None:
        with self._lock:
            if key in self._data:
                self._drop(key)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._usage.clear()
            self._bytes = 0

    def total_bytes(self) -> int:
        with self._lock:
            return self._bytes

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


class MemberScope:
    """A view bound to one member. Has no way to name another member."""

    def __init__(self, store: _TTLStore, member: str):
        self._store = store
        self._member = member

    def get(self, service: str, name: str) -> Optional[Any]:
        return self._store.get((self._member, service, name))

    def set(self, service: str, name: str, value: Any, ttl: float, size: int = DEFAULT_SIZE) -> None:
        self._store.set(self._member, (self._member, service, name), value, ttl, size)

    def delete(self, service: str, name: str) -> None:
        self._store.delete((self._member, service, name))


class MemberCache:
    def __init__(self, clock: Clock, max_entries: int = MAX_ENTRIES, max_bytes: int = MAX_BYTES,
                 member_max_entries: int = MEMBER_MAX_ENTRIES,
                 member_max_bytes: int = MEMBER_MAX_BYTES):
        self._store = _TTLStore(clock, max_entries, max_bytes, member_max_entries, member_max_bytes)

    def for_member(self, principal: MemberPrincipal) -> MemberScope:
        if not is_minted_principal(principal):
            raise TypeError("the member cache is keyed by a parser-minted MemberPrincipal")
        return MemberScope(self._store, principal.username)

    def clear(self) -> None:
        self._store.clear()

    def total_bytes(self) -> int:
        return self._store.total_bytes()

    def __len__(self) -> int:
        return len(self._store)


class SharedCache:
    """For permission-independent data only. Never use for library, progress or artwork."""

    def __init__(self, clock: Clock, max_entries: int = MAX_ENTRIES):
        self._store = _TTLStore(clock, max_entries, MAX_BYTES, max_entries, MAX_BYTES)

    def get(self, namespace: str, name: str) -> Optional[Any]:
        return self._store.get(("shared", namespace, name))

    def set(self, namespace: str, name: str, value: Any, ttl: float, size: int = DEFAULT_SIZE) -> None:
        self._store.set("shared", ("shared", namespace, name), value, ttl, size)
