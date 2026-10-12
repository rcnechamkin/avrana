"""Small disposable TTL cache. In memory only; deleting it (restarting) costs speed, nothing else.

Status: proposed, not deployed. Standard library only.

Misuse resistance by API shape:
  * Member data goes through `MemberCache.for_member(principal)`, which requires a real
    `MemberPrincipal` (a string is rejected). The returned scope can only read and write keys
    inside that member's partition; there is no call that lists, scans or reads across members.
  * The member's partition key is the exact username from the principal. Case, whitespace and
    unicode variants are different principals, so they get different partitions.
  * `SharedCache` is a separate class with a separate name, only for data that does NOT depend on
    who is asking (for example a public configuration value). Nothing in the adapter layer uses it
    for library, progress or artwork data, because those depend on the member's permissions.
  * Stored values should be immutable result objects (frozen dataclasses and tuples).
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Tuple

from .principal import MemberPrincipal
from .resilience import Clock

MAX_ENTRIES = 2048


class _TTLStore:
    def __init__(self, clock: Clock, max_entries: int = MAX_ENTRIES):
        self._clock = clock
        self._max = max_entries
        self._data: Dict[Tuple, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Tuple) -> Optional[Any]:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            expires, value = hit
            if self._clock.now() >= expires:
                del self._data[key]
                return None
            return value

    def set(self, key: Tuple, value: Any, ttl: float) -> None:
        if ttl <= 0:
            return
        with self._lock:
            if len(self._data) >= self._max:
                self._evict()
            self._data[key] = (self._clock.now() + ttl, value)

    def _evict(self) -> None:
        now = self._clock.now()
        for k in [k for k, (exp, _) in self._data.items() if exp <= now]:
            del self._data[k]
        while len(self._data) >= self._max:          # still full: drop the oldest-expiring
            del self._data[min(self._data, key=lambda k: self._data[k][0])]

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

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

    def set(self, service: str, name: str, value: Any, ttl: float) -> None:
        self._store.set((self._member, service, name), value, ttl)


class MemberCache:
    def __init__(self, clock: Clock, max_entries: int = MAX_ENTRIES):
        self._store = _TTLStore(clock, max_entries)

    def for_member(self, principal: MemberPrincipal) -> MemberScope:
        if not isinstance(principal, MemberPrincipal):
            raise TypeError("the member cache is keyed by MemberPrincipal, never a raw string")
        return MemberScope(self._store, principal.username)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


class SharedCache:
    """For permission-independent data only. Never use for library, progress or artwork."""

    def __init__(self, clock: Clock, max_entries: int = MAX_ENTRIES):
        self._store = _TTLStore(clock, max_entries)

    def get(self, namespace: str, name: str) -> Optional[Any]:
        return self._store.get(("shared", namespace, name))

    def set(self, namespace: str, name: str, value: Any, ttl: float) -> None:
        self._store.set(("shared", namespace, name), value, ttl)
