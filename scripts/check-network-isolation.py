#!/usr/bin/env python3
"""Gate G1 drift guard: are the Authentik-proxied backends isolated from their siblings?

Reads `docker network inspect` JSON (a list of network objects, as printed for several networks at
once) from stdin or from the files named on the command line. Offline and read-only: it never runs
docker; scripts/services-health.sh supplies the data. See docs/runbooks/g1-network-isolation.md.

Rules, once the three private networks exist (G1 applied):
  - no backend is attached to authentik_frontend;
  - each backend is attached to its own private network and to no other network that appears in the
    input (at most one network, so it cannot bridge two);
  - each private network has exactly two members: authentik-server and its one backend.

Before apply (none of the private networks exists) it prints one WARN and passes, so a production
health run does not turn red on a change that has been staged but not applied. Some but not all of
the private networks existing is a FAIL (a half-applied or damaged state), and so is unreadable
input.

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


def _members(network):
    """Container names attached to one inspected network."""
    containers = network.get("Containers") or {}
    return sorted(c.get("Name", "") for c in containers.values() if isinstance(c, dict))


def evaluate(networks):
    """networks: list of `docker network inspect` objects. Returns [(level, message)], level in
    OK / WARN / FAIL. Pure: no I/O."""
    by_name = {n.get("Name"): n for n in networks if isinstance(n, dict) and n.get("Name")}
    present = [name for name in PRIVATE if name in by_name]
    results = []

    if not present:
        return [("WARN", f"{PREFIX}: not applied, none of {', '.join(PRIVATE)} exists; the backends "
                         "still share authentik_frontend (docs/runbooks/g1-network-isolation.md)")]
    missing = [name for name in PRIVATE if name not in by_name]
    if missing:
        results.append(("FAIL", f"{PREFIX}: network(s) missing: {', '.join(missing)}"))
    if FRONTEND not in by_name:
        results.append(("FAIL", f"{PREFIX}: {FRONTEND} not in the input, cannot verify the backends left it"))

    memberships = {name: _members(net) for name, net in by_name.items()}
    for private, backend in PRIVATE.items():
        for network, members in memberships.items():
            if network == FRONTEND and backend in members:
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
    try:
        if argv:
            networks = []
            for path in argv:
                with open(path, encoding="utf-8") as handle:
                    networks.extend(parse(handle.read()))
        else:
            networks = parse(sys.stdin.read())
        results = evaluate(networks)
    except (ValueError, OSError) as exc:
        results = [("FAIL", f"{PREFIX}: unreadable network data: {exc}")]
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
