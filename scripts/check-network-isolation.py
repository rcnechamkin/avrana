#!/usr/bin/env python3
"""Gate G1 drift guard: are the Authentik-proxied backends isolated from their siblings?

Usage: check-network-isolation.py [--applied] [FILE...]

Reads `docker network inspect` JSON (a list of network objects, as printed for several networks at
once) from stdin or from the files named on the command line. Offline and read-only: it never runs
docker; scripts/services-health.sh supplies the data. See docs/runbooks/g1-network-isolation.md.

Rules, once the three private networks exist (G1 applied):
  - no backend is attached to authentik_frontend;
  - each backend is attached to its own private network and to no other network that appears in the
    input (at most one network, so it cannot bridge two);
  - each private network has exactly two members: authentik-server and its one backend.

Before apply (none of the private networks exists, and --applied is not given) it prints one WARN and
passes, so a production health run does not turn red on a change that is staged but not applied.
With --applied (the owner's sign-off marker, see the runbook) the same state is a FAIL: the networks
have gone, or the change was rolled back without clearing the marker. Some but not all of the private
networks existing is a FAIL either way, and so is anything unreadable or oddly shaped (fail closed).

Output: OK lines on stdout, WARN and FAIL lines on stderr. Exit 0 when there is no FAIL, else 1.
"""
import json
import sys

FRONTEND = "authentik_frontend"
SERVER = "authentik-server"
# private network -> the one backend that may share it with the Authentik server
PRIVATE = {
    "authentik_portal": "avrana-portal",
    "authentik_kindle": "avrana-kindle-connector",
    "authentik_olivetin": "olivetin",
}

PREFIX = "network isolation (G1)"


class Shape(ValueError):
    """The inspect data does not have the shape docker prints."""


def _members(network):
    """Sorted container names attached to one inspected network. Raises Shape on odd data."""
    containers = network.get("Containers")
    if containers is None:
        return []
    if not isinstance(containers, dict):
        raise Shape(f"Containers is a {type(containers).__name__}, not an object")
    names = []
    for value in containers.values():
        if not isinstance(value, dict) or not isinstance(value.get("Name"), str) or not value["Name"]:
            raise Shape("a container entry has no usable Name")
        names.append(value["Name"])
    return sorted(names)


def evaluate(networks, applied=False):
    """networks: list of `docker network inspect` objects. Returns [(level, message)], level in
    OK / WARN / FAIL. Pure: no I/O. Never raises on odd shapes."""
    if not isinstance(networks, list):
        return [("FAIL", f"{PREFIX}: network data is not a list")]
    names = []
    for item in networks:
        if not isinstance(item, dict) or not isinstance(item.get("Name"), str) or not item["Name"]:
            return [("FAIL", f"{PREFIX}: a network entry has no usable Name")]
        names.append(item["Name"])
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        return [("FAIL", f"{PREFIX}: duplicate network name(s) in the data: {', '.join(duplicates)}")]
    by_name = dict(zip(names, networks))
    present = [name for name in PRIVATE if name in by_name]

    if not present:
        if applied:
            return [("FAIL", f"{PREFIX}: marked applied but none of {', '.join(PRIVATE)} exists "
                             "(removed, or rolled back without clearing the marker)")]
        return [("WARN", f"{PREFIX}: not applied, none of {', '.join(PRIVATE)} exists; the backends "
                         "still share authentik_frontend (docs/runbooks/g1-network-isolation.md)")]

    results = []
    missing = [name for name in PRIVATE if name not in by_name]
    if missing:
        results.append(("FAIL", f"{PREFIX}: network(s) missing: {', '.join(missing)}"))
    if FRONTEND not in by_name:
        results.append(("FAIL", f"{PREFIX}: {FRONTEND} not in the input, cannot verify the backends left it"))

    memberships = {}
    unreadable = False
    for name, network in by_name.items():
        try:
            memberships[name] = _members(network)
        except Shape as exc:
            # Any network we cannot read could hold a backend: fail closed, report them all.
            unreadable = True
            results.append(("FAIL", f"{PREFIX}: {name}: {exc}"))
    if unreadable:
        return results

    for private, backend in PRIVATE.items():
        if backend in memberships.get(FRONTEND, []):
            results.append(("FAIL", f"{PREFIX}: {backend} is attached to {FRONTEND}"))
        elsewhere = sorted(n for n, m in memberships.items()
                           if backend in m and n != private and n != FRONTEND)
        if elsewhere:
            results.append(("FAIL", f"{PREFIX}: {backend} is also attached to {', '.join(elsewhere)}"))
        if private in memberships:
            members = memberships[private]
            expected = sorted([SERVER, backend])
            if members != expected:
                extra = sorted(set(members) - set(expected))
                absent = sorted(set(expected) - set(members))
                detail = []
                if extra:
                    detail.append("unexpected " + ", ".join(extra))
                if absent:
                    detail.append("absent " + ", ".join(absent))
                if len(members) != len(set(members)):
                    detail.append("duplicate member names")
                results.append(("FAIL", f"{PREFIX}: {private} members must be exactly "
                                        f"{expected[0]} and {expected[1]}: " + "; ".join(detail)))

    if not any(level == "FAIL" for level, _ in results):
        results.append(("OK", f"{PREFIX}: {len(PRIVATE)} private networks, two members each; "
                              f"no backend on {FRONTEND}"))
    return results


def parse(text):
    """JSON text -> list of network objects. Raises ValueError when it is not one."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"not valid JSON ({exc})") from exc
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data or not all(isinstance(n, dict) for n in data):
        raise ValueError("expected a non-empty JSON list of network objects")
    return data


def main(argv):
    applied = "--applied" in argv
    paths = [a for a in argv if a != "--applied"]
    try:
        if paths:
            networks = []
            for path in paths:
                with open(path, encoding="utf-8") as handle:
                    networks.extend(parse(handle.read()))
        else:
            networks = parse(sys.stdin.read())
        results = evaluate(networks, applied=applied)
    except (ValueError, OSError) as exc:
        results = [("FAIL", f"{PREFIX}: unreadable network data: {exc}")]
    except Exception as exc:  # fail closed on anything unforeseen, never a traceback
        results = [("FAIL", f"{PREFIX}: internal error {type(exc).__name__}: {exc}")]
    failed = False
    for level, message in results:
        if level == "OK":
            print(f"OK   {message}")
        else:
            print(f"{level} {message}", file=sys.stderr)
            failed = failed or level == "FAIL"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
