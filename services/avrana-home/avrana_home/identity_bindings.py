"""Identity bindings (RC1, finding S1): each Authentik username is bound to the ONE Authentik user that holds it.

Home keys every member's data by the username in the signed token: their Jellyfin and Audiobookshelf accounts (exact
name), their requests in Shelfarr and Omnibus, their profile in the member store, their cache. Authentik keeps
usernames unique only among the users that exist NOW. If a member is deleted and a new user later gets the same name
(by invitation, or an administrator's rename), that new person would inherit everything Home finds under the name.

The token's `sub` tells them apart: the Home providers use Authentik's `hashed_user_id`, which is `User.uid`,
sha256("<user pk>-<install id>") (authentik/core/models.py, providers/oauth2/id_token.py, 2026.5): fixed for one
Authentik user and different for a recreated one. The file maps username -> sha256(sub).

  * Seeded, never guessed. The owner creates the file once from Authentik itself (`init --seed`, the seed made by
    scripts/identity-bindings-seed.py inside `ak shell`), so existing members are bound to the Authentik user that
    holds the name today, not to whoever signs in first. `init --reserve-upstream` also RESERVES every Jellyfin and
    Audiobookshelf account name with no Authentik user behind it: nobody can ever be bound to such a name (or any
    letter-case variant) until the owner releases it.
  * After that a name Home has never seen (a member who joined later) is bound at its first sign-in. A name that
    differs only in letter case or Unicode form from a bound or reserved one is refused, not bound.
  * Fail closed. No file (never initialised, or deleted), a file that cannot be read or parsed, a binding that cannot
    be written, or a file that LOST a binding Home had seen without a release record: every request is refused
    (`bindings_unavailable`). Home never creates or reseeds the file. Recovery is the owner's (`init --seed`, which
    merges and never overwrites a differing binding; then restart Home).
  * Cross-process safe. Every write takes an exclusive lock on `<file>.lock` (flock; msvcrt on Windows), re-reads the
    file under the lock and replaces it atomically, so two Home workers, or Home and the owner's tool, never lose a
    binding or both claim one name: the first writer wins and the other sees the binding it made.
  * Release is checked. `release <username>` refuses while Jellyfin or Audiobookshelf still has an account under the
    name (any letter case), while the member store still holds a row for it, and unless the owner states that the
    other apps were cleared (docs/runbooks/identity-bindings.md).

A different `sub` for a bound name is no principal (the signed-out page) and the log line
`identity_jwt reason=identity_changed`; nothing about the member is read. Standard library only. No `sub` and no
binding is ever logged.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
import unicodedata
from typing import Any, Callable, Dict, Iterable, Iterator, Mapping, Optional, Sequence, Tuple

try:
    import fcntl
except ImportError:                                  # Windows (tests and the owner's laptop)
    fcntl = None
    import msvcrt

MAX_BINDINGS = 5000
DEFAULT_PATH = "/var/lib/avrana-home/identity_bindings.json"     # docker-compose.beta-live.yml
FORMAT, VERSION = "avrana-identity-bindings", 2
SEED_FORMAT, SEED_VERSION = "avrana-identity-seed", 1
RESERVED = "reserved"
_DIGEST = re.compile(r"[0-9a-f]{64}")
OK, NO_SUBJECT, CHANGED, UNAVAILABLE = "ok", "no_subject", "identity_changed", "bindings_unavailable"
NAME_RESERVED = "name_reserved"
LOCK_TIMEOUT = 10.0


class BindingsFileError(ValueError):
    """A fixed message, never file content."""


def digest(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


def loose(name: str) -> str:
    """The same folding the adapters use for 'is this the same name in another letter case' (adapters/_base.py)."""
    return unicodedata.normalize("NFKC", name).casefold().strip()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _valid_name(name: Any) -> bool:
    return isinstance(name, str) and 0 < len(name) <= 150 and name == name.strip()


class State:
    """One parsed file: `bindings` maps username -> sha256 hex or RESERVED; `released` maps username -> when."""
    __slots__ = ("initialized", "bindings", "released")

    def __init__(self, initialized: str, bindings: Dict[str, str], released: Dict[str, str]):
        self.initialized, self.bindings, self.released = initialized, bindings, released

    def to_json(self) -> dict:
        return {"format": FORMAT, "version": VERSION, "initialized": self.initialized,
                "bindings": dict(sorted(self.bindings.items())), "released": dict(sorted(self.released.items()))}


def parse_state(text: str) -> State:
    try:
        data = json.loads(text)
    except ValueError:
        raise BindingsFileError("not JSON") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("version") != VERSION:
        raise BindingsFileError("not an identity bindings file of version %d" % VERSION)
    initialized, bindings, released = data.get("initialized"), data.get("bindings"), data.get("released")
    if not isinstance(initialized, str) or not initialized:
        raise BindingsFileError("not initialised")
    if not isinstance(bindings, dict) or not isinstance(released, dict) or len(bindings) > MAX_BINDINGS:
        raise BindingsFileError("bindings or released is not an object of at most %d entries" % MAX_BINDINGS)
    for name, value in bindings.items():
        if not _valid_name(name) or not isinstance(value, str) or not (value == RESERVED or _DIGEST.fullmatch(value)):
            raise BindingsFileError("an entry is not username -> sha256 hex or reserved")
    for name, value in released.items():
        if not _valid_name(name) or not isinstance(value, str) or len(released) > MAX_BINDINGS:
            raise BindingsFileError("a released entry is not username -> time")
    folded: Dict[str, str] = {}
    for name in bindings:
        if folded.setdefault(loose(name), name) != name:
            raise BindingsFileError("two entries differ only in letter case")
    return State(initialized, dict(bindings), dict(released))


def read_state(path: str) -> State:
    """The file at `path`. Raises BindingsFileError when it is missing or unreadable: there is no empty default."""
    try:
        text = None
        for _ in range(200 if fcntl is None else 1):  # Windows: the file is being replaced this instant
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                break
            except PermissionError:
                if fcntl is not None:
                    raise
                time.sleep(0.005)
        if text is None:
            raise BindingsFileError("cannot be read")
        return parse_state(text)
    except FileNotFoundError:
        raise BindingsFileError("missing (initialise it with `init --seed`)") from None
    except OSError:
        raise BindingsFileError("cannot be read") from None


def _replace(tmp: str, path: str) -> None:
    """os.replace. On Windows a reader holding the file open makes it fail for a moment; Linux never does."""
    deadline = time.monotonic() + 2.0
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if fcntl is not None or time.monotonic() >= deadline:
                raise
            time.sleep(0.005)


def write_state(path: str, state: State) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".identity_bindings.", dir=folder)
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(state.to_json(), fh, indent=1)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        _replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if fcntl is not None:                            # make the rename itself durable
        dfd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


@contextlib.contextmanager
def file_lock(path: str, timeout: float = LOCK_TIMEOUT) -> Iterator[None]:
    """An exclusive lock shared by every process that writes `path`. Raises OSError if it cannot be had in time."""
    fd = os.open(path + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


def decide(state: State, username: str, want: str) -> Optional[str]:
    """The outcome for a name already in `state`, or None when it is new and may be bound."""
    have = state.bindings.get(username)
    if have is not None:
        return OK if have == want else (NAME_RESERVED if have == RESERVED else CHANGED)
    folded = loose(username)
    if any(loose(name) == folded for name in state.bindings):
        return NAME_RESERVED                         # a letter-case or Unicode twin of a bound or reserved name
    return None


class IdentityBindings:
    """The live view of the bindings file. `check` compares a known username or binds a new one. Thread- and
    process-safe."""

    def __init__(self, path: str, log: Optional[Callable[..., None]] = None):
        self._path = path
        self._lock = threading.Lock()
        self._log = log or (lambda **_kw: None)
        self._state: Optional[State] = None
        self._known: set = set()                     # every name Home has seen bound: losing one is tampering
        self._seen: Any = "unread"                 # never equal to a stamp, so the first look always reads
        self._broken: Optional[str] = None
        with self._lock:
            self._refresh()

    @property
    def available(self) -> bool:
        with self._lock:
            self._refresh()
            return self._broken is None

    def _stamp(self):
        try:
            st = os.stat(self._path)
        except OSError:
            return None
        return (st.st_ino, st.st_size, st.st_mtime_ns)

    def _adopt(self, state: State) -> bool:
        lost = {name for name in self._known if name not in state.bindings and name not in state.released}
        if lost:
            self._broken = "shrunk"
            self._log(state="refused", reason="shrunk", count=len(lost))
            return False
        self._state, self._broken = state, None
        self._known = {n for n, v in state.bindings.items() if v != RESERVED}
        return True

    def _refresh(self) -> None:
        stamp = self._stamp()
        if stamp == self._seen and self._broken is None:
            return
        if self._broken == "shrunk" and stamp == self._seen:
            return
        self._seen = stamp
        try:
            state = read_state(self._path)
        except BindingsFileError:
            reason = "missing" if stamp is None else "malformed"
            if self._broken != reason:
                self._log(state="refused", reason=reason)
            self._broken = reason
            return
        self._adopt(state)

    def check(self, username: str, subject: Optional[str]) -> str:
        if not isinstance(subject, str) or not subject:
            return NO_SUBJECT
        if not _valid_name(username):
            return UNAVAILABLE
        want = digest(subject)
        with self._lock:
            self._refresh()
            if self._broken is not None:
                return UNAVAILABLE
            outcome = decide(self._state, username, want)
            if outcome is not None:
                return outcome
            try:
                with file_lock(self._path):
                    state = read_state(self._path)   # another process may have written since our last look
                    if not self._adopt(state):
                        return UNAVAILABLE
                    outcome = decide(state, username, want)
                    if outcome is not None:
                        return outcome
                    if len(state.bindings) >= MAX_BINDINGS:
                        return UNAVAILABLE
                    state.bindings[username] = want
                    state.released.pop(username, None)
                    write_state(self._path, state)
            except BindingsFileError:
                self._broken = "missing" if self._stamp() is None else "malformed"
                self._log(state="refused", reason=self._broken)
                return UNAVAILABLE
            except OSError:
                self._log(state="refused", reason="unwritable")
                return UNAVAILABLE
            self._adopt(state)
            self._seen = self._stamp()
            self._log(state="bound", reason="", count=len(state.bindings))
            return OK

    def knows_digest(self, want: str) -> Optional[bool]:
        """Whether some username is bound to this subject digest (sha256 of a token `sub`): the Komga key intake's
        "known member" rule (komga_keys.KeyIntake). None when the file is unavailable. Never binds anything."""
        if not isinstance(want, str) or _DIGEST.fullmatch(want) is None:
            return False
        with self._lock:
            self._refresh()
            if self._broken is not None or self._state is None:
                return None
            return want in self._state.bindings.values()

    def __repr__(self) -> str:
        return "IdentityBindings(<redacted>)"


# ---- owner tool --------------------------------------------------------------------------------------------
def parse_seed(text: str) -> Dict[str, str]:
    """A seed from scripts/identity-bindings-seed.py: {"format", "version", "users": {username: sha256(sub)}}."""
    try:
        data = json.loads(text)
    except ValueError:
        raise BindingsFileError("seed is not JSON") from None
    users = data.get("users") if isinstance(data, dict) else None
    if (not isinstance(data, dict) or data.get("format") != SEED_FORMAT or data.get("version") != SEED_VERSION
            or not isinstance(users, dict) or len(users) > MAX_BINDINGS):
        raise BindingsFileError("not an identity seed of version %d" % SEED_VERSION)
    for name, value in users.items():
        if not _valid_name(name) or not isinstance(value, str) or not _DIGEST.fullmatch(value):
            raise BindingsFileError("a seed entry is not username -> sha256 hex")
    return dict(users)


def merge_seed(state: Optional[State], seed: Mapping[str, str], reserve: Iterable[str]) -> Tuple[State, list]:
    """`state` plus every seed binding and reservation it lacks. Never overwrites: returns the conflicting names."""
    state = state or State(_now(), {}, {})
    merged = State(state.initialized, dict(state.bindings), dict(state.released))
    conflicts = []
    for name, value in sorted(seed.items()):
        outcome = decide(merged, name, value)
        if outcome is None:
            merged.bindings[name] = value
        elif outcome != OK:
            conflicts.append(name)
    for name in sorted(set(reserve)):
        if not _valid_name(name):
            continue
        if decide(merged, name, "") is None:
            merged.bindings[name] = RESERVED     # an upstream account with no Authentik user behind it
    return merged, conflicts


Send = Callable[[str, str, Optional[dict]], Any]


class CheckFailed(Exception):
    """A library could not be asked. Never a pass."""


def upstream_names(jellyfin: Optional[Send], audiobookshelf: Optional[Send]) -> Dict[str, list]:
    """Every account name in each library, from Home's own keys. Raises CheckFailed on any failure."""
    try:
        return _upstream_names(jellyfin, audiobookshelf)
    except Exception as exc:
        raise CheckFailed(type(exc).__name__) from None


def _upstream_names(jellyfin: Optional[Send], audiobookshelf: Optional[Send]) -> Dict[str, list]:
    names: Dict[str, list] = {}
    if jellyfin is not None:
        users = jellyfin("GET", "/Users", None)
        if not isinstance(users, list):
            raise BindingsFileError("jellyfin /Users is not a list")
        names["jellyfin"] = [u.get("Name") for u in users if isinstance(u, dict) and isinstance(u.get("Name"), str)]
    if audiobookshelf is not None:
        body = audiobookshelf("GET", "/api/users", None)
        users = body.get("users") if isinstance(body, dict) else None
        if not isinstance(users, list):
            raise BindingsFileError("audiobookshelf /api/users is not a list")
        names["audiobookshelf"] = [u.get("username") for u in users
                                   if isinstance(u, dict) and isinstance(u.get("username"), str)]
    return names


def release_blockers(username: str, names: Mapping[str, Sequence[str]], member_rows: bool) -> list:
    """Why `username` may not be released yet (empty when it may)."""
    folded = loose(username)
    out = [f"{library} still has an account named like it (delete it: scripts/offboard.py --purge)"
           for library, held in sorted(names.items()) if any(loose(n) == folded for n in held)]
    if member_rows:
        out.append("the member store still holds it (python3 -m avrana_home.memberstore purge <username>)")
    return out


def _settings_senders(env: Mapping[str, str]) -> Tuple[Optional[Send], Optional[Send], Any]:
    """Home's own Jellyfin and Audiobookshelf access and member store, from the container's settings."""
    from .app.settings import Settings
    from .provision import http_sender
    settings = Settings.from_env(env)
    if settings.upstream_mode != "real" or not settings.jellyfin_base_url:
        raise BindingsFileError("release needs Home's real Jellyfin settings (run it inside the Home container)")
    jf = http_sender(settings.jellyfin_base_url, {"Authorization": f'MediaBrowser Token="{settings.jellyfin_api_key}"'})
    abs_ = (http_sender(settings.audiobookshelf_base_url, {"Authorization": f"Bearer {settings.audiobookshelf_token}"})
            if settings.audiobookshelf_base_url else None)
    return jf, abs_, settings.member_store


def _member_rows(store_path: Any, username: str) -> bool:
    if not store_path:
        return False
    from .memberstore import MemberStore
    store = MemberStore(store_path)
    try:
        return store.holds(username) is not False    # unreadable counts as holding: a check that failed is no pass
    finally:
        store.close()


def main(argv=None, env: Optional[Mapping[str, str]] = None, senders=None) -> int:
    """Owner tool, run inside the Home container: initialise from a seed, list, count, reserve or release a name."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", default=DEFAULT_PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init", help="create the file from an Authentik seed, or merge a newer seed into it")
    init.add_argument("--seed", required=True)
    init.add_argument("--reserve-upstream", action="store_true",
                      help="also reserve every Jellyfin/Audiobookshelf name that has no Authentik user")
    sub.add_parser("count")
    sub.add_parser("list")
    res = sub.add_parser("reserve")
    res.add_argument("username")
    rel = sub.add_parser("release")
    rel.add_argument("username")
    rel.add_argument("--other-apps-cleared", action="store_true",
                     help="the owner has deleted this person's Shelfarr, Omnibus, Calibre-Web and Komga accounts")
    args = ap.parse_args(argv)
    env = os.environ if env is None else env

    def fail(message: str, code: int = 2) -> int:
        print(f"refused: {message}", file=sys.stderr)
        return code

    try:
        if args.cmd in ("count", "list"):
            state = read_state(args.file)
            if args.cmd == "count":
                bound = sum(1 for v in state.bindings.values() if v != RESERVED)
                print(f"{bound} bound, {len(state.bindings) - bound} reserved, {len(state.released)} released")
            else:
                for name in sorted(state.bindings):
                    print(f"{name}\t{'reserved' if state.bindings[name] == RESERVED else 'bound'}")
            return 0
        with file_lock(args.file):
            if args.cmd == "init":
                with open(args.seed, encoding="utf-8") as fh:
                    seed = parse_seed(fh.read())
                try:
                    state = read_state(args.file)
                except BindingsFileError:
                    if os.path.exists(args.file):
                        raise                         # unreadable: fix or move it aside by hand, never overwrite
                    state = None
                reserve: list = []
                if args.reserve_upstream:
                    jf, abs_, _store = senders if senders is not None else _settings_senders(env)
                    for held in upstream_names(jf, abs_).values():
                        reserve.extend(n for n in held if n not in seed)
                merged, conflicts = merge_seed(state, seed, reserve)
                if conflicts:
                    return fail("these names are bound to a different Authentik user than the seed says; nothing "
                                "was written: " + ", ".join(conflicts))
                write_state(args.file, merged)
                bound = sum(1 for v in merged.bindings.values() if v != RESERVED)
                print(f"{'merged into' if state else 'initialised'} {args.file}: {bound} bound, "
                      f"{len(merged.bindings) - bound} reserved. Restart Home if it refused the old file.")
                return 0
            state = read_state(args.file)
            name = args.username
            if args.cmd == "reserve":
                if decide(state, name, "") is not None:
                    return fail("already bound or reserved (or a letter-case twin is)", 1)
                state.bindings[name] = RESERVED
                write_state(args.file, state)
                print("reserved")
                return 0
            if name not in state.bindings:
                return fail("not bound", 1)
            if not args.other_apps_cleared:
                return fail("confirm the other apps first: see docs/runbooks/identity-bindings.md")
            jf, abs_, store = senders if senders is not None else _settings_senders(env)
            blockers = release_blockers(name, upstream_names(jf, abs_), _member_rows(store, name))
            if blockers:
                return fail("; ".join(blockers))
            del state.bindings[name]
            state.released[name] = _now()
            write_state(args.file, state)
            print("released; the next Authentik user with this name is bound at their first sign-in")
            return 0
    except BindingsFileError as exc:
        return fail(str(exc))
    except CheckFailed as exc:
        return fail(f"a check could not run ({exc})")
    except OSError as exc:
        return fail(f"{type(exc).__name__} (check the folder and the lock)")
    except Exception as exc:                          # an upstream that could not be asked is not a pass
        return fail(f"a check could not run ({type(exc).__name__})")


if __name__ == "__main__":
    sys.exit(main())
