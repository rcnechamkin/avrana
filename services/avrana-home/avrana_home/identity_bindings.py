"""Identity bindings (RC1, finding S1): each Authentik username is bound to the ONE Authentik user it first arrived as.

Home keys every member's data by the username in the signed token: their Jellyfin and Audiobookshelf accounts (exact
name), their requests in Shelfarr and Omnibus, their profile in the member store, their cache. Authentik keeps
usernames unique only among the users that exist NOW. If a member is deleted and a new user later gets the same name
(by invitation, or an administrator's rename), that new person would inherit everything Home finds under the name.

The token's `sub` tells them apart: the Home providers use Authentik's `hashed_user_id`, which is fixed for one
Authentik user and different for a recreated one. Home records username -> sha256(sub) the first time it sees a
username and from then on accepts that username only with the same `sub`. A different `sub` is no principal (the
signed-out page) and the log line `identity_jwt reason=identity_changed`; nothing about the member is read.

The owner releases a name on purpose, after offboarding the previous person's upstream accounts:

    python3 -m avrana_home.identity_bindings release <username>      # --file defaults to DEFAULT_PATH

Fail closed: a file that cannot be read or parsed, or a new binding that cannot be written, refuses the request and
keeps the last good bindings. One JSON object, written atomically (mode 0600), re-read when it changes on disk.
Standard library only. No `sub` and no binding is ever logged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
from typing import Callable, Dict, Optional

MAX_BINDINGS = 5000
DEFAULT_PATH = "/var/lib/avrana-home/identity_bindings.json"     # docker-compose.beta-live.yml
_DIGEST = re.compile(r"[0-9a-f]{64}")
OK, NO_SUBJECT, CHANGED, UNAVAILABLE = "ok", "no_subject", "identity_changed", "bindings_unavailable"


class BindingsFileError(ValueError):
    """A fixed message, never file content."""


def digest(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


def parse_bindings(text: str) -> Dict[str, str]:
    try:
        data = json.loads(text)
    except ValueError:
        raise BindingsFileError("not JSON") from None
    if not isinstance(data, dict) or len(data) > MAX_BINDINGS:
        raise BindingsFileError("not a JSON object of at most %d entries" % MAX_BINDINGS)
    for name, value in data.items():
        if not isinstance(name, str) or not name or not isinstance(value, str) or not _DIGEST.fullmatch(value):
            raise BindingsFileError("an entry is not username -> sha256 hex")
    return dict(data)


def read_bindings(path: str) -> Dict[str, str]:
    """The bindings in `path`; an absent file is none yet. Raises BindingsFileError for anything unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            return parse_bindings(fh.read())
    except FileNotFoundError:
        return {}
    except OSError:
        raise BindingsFileError("cannot be read") from None


def write_bindings(path: str, bindings: Dict[str, str]) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".identity_bindings.", dir=folder)
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(dict(sorted(bindings.items())), fh, indent=1)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class IdentityBindings:
    """The live view of the bindings file. `check` binds a new username, or compares a known one. Thread-safe."""

    def __init__(self, path: str, log: Optional[Callable[..., None]] = None):
        self._path = path
        self._lock = threading.Lock()
        self._log = log or (lambda **_kw: None)
        self._bindings: Dict[str, str] = {}
        self._seen = None
        self._broken = False
        with self._lock:
            self._refresh()

    def _stamp(self):
        try:
            st = os.stat(self._path)
        except OSError:
            return None
        return (st.st_size, st.st_mtime_ns)

    def _refresh(self) -> None:
        stamp = self._stamp()
        if stamp == self._seen and not self._broken:
            return
        try:
            self._bindings = read_bindings(self._path)
            self._broken = False
        except BindingsFileError:
            self._broken = True                     # refuse until the file is good again
            self._log(state="refused", reason="malformed")
        self._seen = stamp

    def check(self, username: str, subject: Optional[str]) -> str:
        if not isinstance(subject, str) or not subject:
            return NO_SUBJECT
        want = digest(subject)
        with self._lock:
            self._refresh()
            if self._broken:
                return UNAVAILABLE
            have = self._bindings.get(username)
            if have is not None:
                return OK if have == want else CHANGED
            if len(self._bindings) >= MAX_BINDINGS:
                return UNAVAILABLE
            bindings = dict(self._bindings, **{username: want})
            try:
                write_bindings(self._path, bindings)
            except OSError:
                self._log(state="refused", reason="unwritable")
                return UNAVAILABLE
            self._bindings, self._seen = bindings, self._stamp()
            self._log(state="bound", reason="", count=len(bindings))
            return OK

    def __repr__(self) -> str:
        return "IdentityBindings(<redacted>)"


def main(argv=None) -> int:
    """Owner tool, run inside the Home container (or against a copy of ./state): list names, count, release one."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", default=DEFAULT_PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("count")
    sub.add_parser("list")
    rel = sub.add_parser("release")
    rel.add_argument("username")
    args = ap.parse_args(argv)
    try:
        bindings = read_bindings(args.file)
    except BindingsFileError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if args.cmd == "count":
        print(len(bindings))
    elif args.cmd == "list":
        for name in sorted(bindings):
            print(name)
    else:
        if args.username not in bindings:
            print("not bound", file=sys.stderr)
            return 1
        del bindings[args.username]
        write_bindings(args.file, bindings)
        print(f"released; it binds again at that name's next sign-in ({len(bindings)} left)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
