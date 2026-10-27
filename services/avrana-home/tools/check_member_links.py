#!/usr/bin/env python3
"""Owner-run, read-only check that each member's libraries will link in Home (AVR-375). Standard library plus Home.

    python tools/check_member_links.py alice bob          # or: --file members.txt (one username per line)
    python tools/check_member_links.py --json alice bob   # for scripts: one JSON document on stdout

WHY. Members never handle API keys: Home reads each library with the one service key and links a member to
the upstream account whose name equals their Authentik username EXACTLY (IDENTITY-MAPPING.md section 1, owner
decision: username match, no link table). The only thing that can go wrong per member is that the names do
not line up. This tool runs Home's own mapping code, with Home's own settings, for each username given, and
says in plain words what (if anything) the owner has to rename, create or enable. Run it after inviting a
member and after renaming accounts.

WHAT IT DOES. It reads the same `HOME_*` / upstream variables Home is started with (`Settings.from_env`), so
it checks exactly what the running Home would do. For Jellyfin and Audiobookshelf it calls the adapters'
mapping hook, which reads the upstream user list (one GET per service and member; the adapters' route guard
allows nothing else). Komga and Calibre-Web are shared views with nothing to link (ADAPTER-CONTRACT 12.2,
13.2). It never writes upstream, never prints a credential, an upstream id or another account's name: only
the username it was given, the service and a fixed verdict.

WHO RUNS IT. The owner, where Home's configuration lives. Against real libraries that is a read of the user
list with the service key, so it needs the owner's go-ahead like any other live read; no agent runs it there.
With the default mock settings (`HOME_UPSTREAM_MODE=mock`, `dev/run_dev.py`'s loopback mocks) it is offline.

EXIT. 0 every given member links everywhere they can; 1 at least one does not (or a library could not be
reached); 2 refused (bad arguments or configuration, nothing was checked).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Callable, Iterable, List, Mapping, Optional, Sequence

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HOME not in sys.path:
    sys.path.insert(0, HOME)

from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter  # noqa: E402
from avrana_home.adapters.jellyfin import JellyfinAdapter  # noqa: E402
from avrana_home.contract import REQUIRED_GROUP, AmbiguousMappingError, MappingFailed, Service  # noqa: E402
from avrana_home.principal import PrincipalError, principal_from_headers  # noqa: E402

ALL_GROUPS = "|".join(["avrana-users"] + sorted(REQUIRED_GROUP.values()))
LABEL = {Service.JELLYFIN: "Jellyfin", Service.AUDIOBOOKSHELF: "Audiobookshelf",
         Service.KOMGA: "Komga", Service.CALIBRE_WEB: "Calibre-Web"}
SHARED = (Service.KOMGA, Service.CALIBRE_WEB)

# verdict -> what the owner does about it ({svc} the library, {user} the Authentik username). Fixed text only.
FIX = {
    "linked": "Nothing to do.",
    "shared": "Nothing to link: every member with the group sees the shared {svc} view.",
    "unmapped": "No {svc} account is named exactly '{user}'. Create one with that name, or rename theirs to it.",
    "case_or_unicode_mismatch": "An account in {svc} differs from '{user}' only in capitals or look-alike characters. "
                                "Rename it to exactly '{user}'.",
    "ambiguous": "More than one {svc} account matches '{user}'. Rename or delete the extra one.",
    "disabled": "The {svc} account '{user}' is disabled. Enable it if they should have access.",
    "unreachable": "{svc} did not answer (or answered something Home cannot read). Check the service, then "
                   "run this again.",
    "invalid_username": "'{user}' cannot be an Authentik username Home accepts (empty, too long, leading or trailing "
                        "spaces, '|' or ',', or non-ASCII). Fix it in Authentik.",
}


class Refused(Exception):
    pass


def read_usernames(args: argparse.Namespace) -> List[str]:
    names: List[str] = list(args.usernames)
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            names += [line.strip() for line in fh if line.strip() and not line.lstrip().startswith("#")]
    seen, out = set(), []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    if not out:
        raise Refused("give at least one username (arguments or --file)")
    return out


def build_mappers(settings) -> dict:
    """service -> callable(principal) raising MappingFailed / AmbiguousMappingError, or None when shared or off.
    The adapters are built exactly as `app.main.build_adapters` builds them (same transport, same headers)."""
    from avrana_home.app.main import build_adapters
    from avrana_home.cache import MemberCache
    from avrana_home.resilience import SystemClock
    adapters = {a.service: a for a in build_adapters(settings, MemberCache(SystemClock()))}
    mappers = {}
    for service in (Service.JELLYFIN, Service.AUDIOBOOKSHELF):
        adapter = adapters.get(service)
        if isinstance(adapter, (JellyfinAdapter, AudiobookshelfAdapter)):
            mappers[service] = adapter._resolve_user          # the mapping hook itself, no cache in between
    for service in SHARED:
        if service in adapters:
            mappers[service] = None
    return mappers


def verdict(mapper: Optional[Callable], principal) -> str:
    if mapper is None:
        return "shared"
    try:
        mapper(principal)
    except MappingFailed as exc:
        return exc.reason if exc.reason in FIX else "unmapped"
    except AmbiguousMappingError:
        return "ambiguous"
    except Exception:                                         # transport, timeout, malformed: no detail printed
        return "unreachable"
    return "linked"


def check(usernames: Sequence[str], mappers: Mapping) -> List[dict]:
    rows = []
    for user in usernames:
        try:
            principal = principal_from_headers({"X-authentik-username": user, "X-authentik-groups": ALL_GROUPS})
        except PrincipalError:
            rows.append({"username": user, "service": None, "verdict": "invalid_username",
                         "fix": FIX["invalid_username"].format(user=user, svc="")})
            continue
        for service, mapper in mappers.items():
            v = verdict(mapper, principal)
            rows.append({"username": user, "service": service.value, "verdict": v,
                         "fix": FIX[v].format(user=user, svc=LABEL[service])})
    return rows


def render(rows: Iterable[dict]) -> str:
    lines = []
    for r in rows:
        svc = LABEL.get(Service(r["service"]), r["service"]) if r["service"] else "-"
        mark = "ok  " if r["verdict"] in ("linked", "shared") else "FIX "
        lines.append(f"{mark} {r['username']:<24} {svc:<15} {r['fix']}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None, environ: Optional[Mapping[str, str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Check that members' library accounts link in Home (read-only).")
    ap.add_argument("usernames", nargs="*", help="Authentik usernames, exactly as in Authentik")
    ap.add_argument("--file", help="file with one username per line (# comments allowed)")
    ap.add_argument("--json", action="store_true", help="print one JSON document instead of a table")
    args = ap.parse_args(argv)
    try:
        usernames = read_usernames(args)
        from avrana_home.app.settings import Settings
        try:
            settings = Settings.from_env(os.environ if environ is None else environ)
        except Exception as exc:                              # settings refuse with a message, never a secret
            raise Refused(f"Home's settings were refused: {type(exc).__name__}: {exc}")
        if not settings.home_sections:
            raise Refused("Home sections are off in these settings (HOME_SECTIONS), so nothing would link")
        mappers = build_mappers(settings)
    except (Refused, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    rows = check(usernames, mappers)
    print(json.dumps({"members": rows}, indent=2) if args.json else render(rows))
    return 0 if all(r["verdict"] in ("linked", "shared") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
