"""Members' own Komga API keys, as one JSON file: lower-case email -> key (docs/runbooks/komga-member-keys.md).

Status: proposed, not deployed. Standard library only.

Two writers, one format: the owner-run `tools/komga_member_keys.py` and, when HOME_PROVISION_ACCOUNTS names komga,
Home itself (provision.py, owner decision 2026-10-28 "Home does it"). Home re-reads the file whenever it changes
on disk (size or modification time), so neither writer needs Home restarted. A file that cannot be read or is
malformed is refused WHOLE and the last good keys stay in use; no entry is ever logged or echoed.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from typing import Any, Callable, Dict, Optional, Tuple

MAX_MEMBER_KEYS = 500
KOMGA_KEY = re.compile(r"[0-9a-f]{32}")              # Komga 1.25 ApiKeyGenerator: a UUID v4 without dashes
_EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}")


def member_key_id(email: Any) -> Optional[str]:
    """What a member's own Komga key is filed under: their email, trimmed and case-folded (Komga matches sign-ins
    by email, ignoring case). None for anything that is not a plausible email."""
    if not isinstance(email, str):
        return None
    value = email.strip().casefold()
    return value if _EMAIL.fullmatch(value) else None


class KeysFileError(ValueError):
    """A fixed message, never file content."""


def parse_keys(text: str) -> Tuple[Tuple[str, str], ...]:
    try:
        data = json.loads(text)
    except ValueError:
        raise KeysFileError("not JSON") from None
    if not isinstance(data, dict) or len(data) > MAX_MEMBER_KEYS:
        raise KeysFileError("not a JSON object of at most %d entries" % MAX_MEMBER_KEYS)
    for email, key in data.items():
        if member_key_id(email) != email or not isinstance(key, str) or KOMGA_KEY.fullmatch(key) is None:
            raise KeysFileError("an entry is not lower-case email -> Komga API key")
    return tuple(sorted(data.items()))


def read_keys(path: str) -> Tuple[Tuple[str, str], ...]:
    """The keys in `path`; an absent file is no keys. Raises KeysFileError for anything unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            return parse_keys(fh.read())
    except FileNotFoundError:
        return ()
    except OSError:
        raise KeysFileError("cannot be read") from None


def write_keys(path: str, keys: Dict[str, str]) -> None:
    """Atomically replace `path` (mode 0600) with `keys`."""
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".komga_member_keys.", dir=folder)
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(dict(sorted(keys.items())), fh, indent=1)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class MemberKeyStore:
    """The live view of the keys file. `get` re-reads it when its size or modification time changed; `put` (only
    when `writable`) adds or replaces one member's key. Thread-safe."""

    def __init__(self, path: str, writable: bool = False, initial: Tuple[Tuple[str, str], ...] = (),
                 log: Optional[Callable[..., None]] = None):
        self._path = path
        self._writable = writable
        self._keys: Dict[str, str] = dict(initial)
        self._seen = self._stamp()
        self._lock = threading.Lock()
        self._log = log or (lambda **_kw: None)

    @property
    def writable(self) -> bool:
        return self._writable

    def _stamp(self):
        try:
            st = os.stat(self._path)
        except OSError:
            return None
        return (st.st_size, st.st_mtime_ns)

    def _refresh(self) -> None:
        stamp = self._stamp()
        if stamp == self._seen:
            return
        try:
            keys = dict(read_keys(self._path))
        except KeysFileError:
            self._log(state="refused", reason="malformed")   # the last good keys stay in use
            self._seen = stamp
            return
        self._keys, self._seen = keys, stamp
        self._log(state="reloaded", reason="", count=len(keys))

    def get(self, email: Any) -> Optional[str]:
        key_id = member_key_id(email)
        if key_id is None:
            return None
        with self._lock:
            self._refresh()
            return self._keys.get(key_id)

    def count(self) -> int:
        with self._lock:
            self._refresh()
            return len(self._keys)

    def put(self, email: str, key: str) -> None:
        key_id = member_key_id(email)
        if not self._writable:
            raise PermissionError("the keys file is read-only for Home")
        if key_id is None or KOMGA_KEY.fullmatch(key or "") is None:
            raise ValueError("not an email and a Komga API key")
        with self._lock:
            self._refresh()
            keys = dict(self._keys, **{key_id: key})
            write_keys(self._path, keys)
            self._keys, self._seen = keys, self._stamp()

    def __repr__(self) -> str:
        return "MemberKeyStore(<redacted>)"
