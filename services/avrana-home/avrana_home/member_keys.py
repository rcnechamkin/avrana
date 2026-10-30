"""Members' own Komga API keys, as one JSON file: lower-case email -> key (docs/runbooks/komga-member-keys.md).

Status: deployed in the live member beta since 2026-10-29 (revision 2cb228f; Komga member keys on). Standard library only.

Writers, one format: the owner-run `tools/komga_member_keys.py`; Home's key intake (`PUT /internal/komga-key/...`,
filled by the enrollment stage) and Me -> Comics "Connect comics" / "Disconnect" (komga_keys.py; ADR "Komga member keys
are minted where the password lives", docs/runbooks/komga-key-lifecycle.md); and `scripts/offboard.py`. (Home's
admin-key provisioning of keys was deleted 2026-10-30, AVR-784.) Home re-reads the file whenever it changes on disk (size or modification time), so no writer needs Home restarted. A file that cannot be read or is
malformed is refused WHOLE and the last good keys stay in use; no entry is ever logged or echoed.

Every write takes the exclusive cross-process lock on `<file>.lock` (identity_bindings.file_lock), re-reads the file
under it and replaces it atomically, so two writers never lose each other's entry. Komga's id for each key Home filed
(needed to revoke it: Komga's key list masks the key itself) is kept in a sidecar, `<file>.ids` (lower-case email ->
key id), so the keys file keeps the one format the owner tool and older Home revisions read.

    python3 -m avrana_home.member_keys count [--file PATH]     # how many members have a key: a number, nothing else
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from typing import Any, Callable, Dict, Optional, Tuple

from .identity_bindings import file_lock

MAX_MEMBER_KEYS = 500
KOMGA_KEY = re.compile(r"[0-9a-f]{32}")              # Komga 1.25 ApiKeyGenerator: a UUID v4 without dashes
KOMGA_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")    # Komga's ApiKey.id (a TSID string); only ever a path segment
DEFAULT_PATH = "/var/lib/avrana-home/komga_member_keys"     # docker-compose.beta-live.yml
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


def parse_ids(text: str) -> Dict[str, str]:
    """The `.ids` sidecar: lower-case email -> Komga key id. Malformed entries are dropped, never fatal: an id only
    makes a revoke more precise (komga_keys.KomgaKeyClient.revoke falls back to Komga's own list)."""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {e: i for e, i in data.items()
            if member_key_id(e) == e and isinstance(i, str) and KOMGA_KEY_ID.fullmatch(i)}


def read_ids(path: str) -> Dict[str, str]:
    try:
        with open(path + ".ids", encoding="utf-8") as fh:
            return parse_ids(fh.read())
    except OSError:
        return {}


def write_keys(path: str, keys: Dict[str, str], prefix: str = ".komga_member_keys.") -> None:
    """Atomically replace `path` (mode 0600) with `keys`."""
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=prefix, dir=folder)
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

    def put(self, email: str, key: str, komga_id: Optional[str] = None) -> bool:
        """File `key` (and Komga's id for it, when known) for `email`. Returns False when exactly that key was already
        filed (nothing written), True when it was added or replaced an older one. An older key is NOT revoked in Komga
        here: Connect and the enrollment stage remove their own older `avrana-home` key before they mint."""
        key_id = member_key_id(email)
        if not self._writable:
            raise PermissionError("the keys file is read-only for Home")
        if key_id is None or not isinstance(key, str) or KOMGA_KEY.fullmatch(key) is None:
            raise ValueError("not an email and a Komga API key")
        if komga_id is not None and (not isinstance(komga_id, str) or KOMGA_KEY_ID.fullmatch(komga_id) is None):
            raise ValueError("not a Komga key id")
        with self._lock, file_lock(self._path):
            keys = dict(read_keys(self._path))          # under the lock: another writer may have written since
            ids = read_ids(self._path)
            same = keys.get(key_id) == key and (komga_id is None or ids.get(key_id) == komga_id)
            if not same:
                if key_id not in keys and len(keys) >= MAX_MEMBER_KEYS:
                    raise ValueError("the keys file is full")
                if keys.get(key_id) != key:
                    ids.pop(key_id, None)               # an id belongs to the key it came with
                keys[key_id] = key
                if komga_id is not None:
                    ids[key_id] = komga_id
                write_keys(self._path, keys)
                write_keys(self._path + ".ids", ids, prefix=".komga_member_keys_ids.")
            self._keys, self._seen = keys, self._stamp()
            return not same

    def komga_id(self, email: Any) -> Optional[str]:
        """Komga's id for the key Home filed for `email`, when Home was told it (intake, Connect); else None."""
        key_id = member_key_id(email)
        if key_id is None:
            return None
        with self._lock:
            return read_ids(self._path).get(key_id)

    def remove(self, email: Any) -> Optional[Tuple[str, Optional[str]]]:
        """Drop `email`'s entry. Returns the (key, Komga key id or None) that was filed, or None when there was none.
        The key is returned only so the caller can revoke it in Komga; it is never logged."""
        key_id = member_key_id(email)
        if not self._writable:
            raise PermissionError("the keys file is read-only for Home")
        if key_id is None:
            return None
        with self._lock, file_lock(self._path):
            keys = dict(read_keys(self._path))
            ids = read_ids(self._path)
            key = keys.pop(key_id, None)
            komga_id = ids.pop(key_id, None)
            if key is not None:
                write_keys(self._path, keys)
                write_keys(self._path + ".ids", ids, prefix=".komga_member_keys_ids.")
            self._keys, self._seen = keys, self._stamp()
        return None if key is None else (key, komga_id)

    def __repr__(self) -> str:
        return "MemberKeyStore(<redacted>)"


def main(argv=None) -> int:
    """`count`: how many members have a key, read from the file (the owner's check after an enrollment). Prints one
    number; never an email or a key. Exit 2 when the file cannot be read."""
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m avrana_home.member_keys")
    ap.add_argument("command", choices=("count",))
    ap.add_argument("--file", default=DEFAULT_PATH)
    args = ap.parse_args(argv)
    try:
        print(len(read_keys(args.file)))
    except KeysFileError as exc:
        print(f"refused: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
