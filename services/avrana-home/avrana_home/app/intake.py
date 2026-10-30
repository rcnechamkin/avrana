"""Home's Komga key intake (S-01; docs/runbooks/komga-key-lifecycle.md): `PUT /internal/komga-key/<subject>`. Pure
functions; main.py reads the headers (identity.py) and the body (forms.py) and calls komga_keys.KeyIntake.

Who may call it: only the Authentik enrollment stage `avrana-komga-key-mint`. Every lock must hold, in this order:

  1. HOME_KEY_INTAKE_TOKEN is configured (settings.py). Without it the middleware has no PUT path at all: 501.
  2. The peer address is inside HOME_INTERNAL_CIDR (the Docker network Home shares with authentik-server alone,
     `authentik_home_beta`), and the request carries NO outpost or proxy header (X-authentik-*, X-Forwarded-*,
     Forwarded): the public path reaches Home through the embedded outpost in that same container, so its requests
     come from the same address but always carry those headers. The /readyz pattern (main.py). Otherwise: the 501 any
     other PUT gets, so nothing outside can tell the path exists.
  3. `Authorization: Bearer <HOME_KEY_INTAKE_TOKEN>`, compared in constant time. Otherwise 401.
  4. `Content-Type: application/json`, a body of at most middleware.MAX_INTAKE_BODY bytes (413 before the app), holding
     exactly `key` and `source` and optionally `key_id`, nothing else. Otherwise 415 / 400.

Then KeyIntake decides (the subject rule is in komga_keys.KeyIntake.allowed). Every answer has an EMPTY body: the key
is never echoed, and neither is the subject. 204 filed or unchanged (idempotent: the same key again is 204 and writes
nothing; a different key replaces the filed one and revokes nothing remotely); 403 unknown subject; 422 a key Komga
refuses or a malformed key; 503 Komga or the keys file unavailable (the enrollment stage logs it and the member uses
Connect comics).
"""
from __future__ import annotations

import hmac
import ipaddress
import json
from typing import Optional, Tuple

from ..komga_keys import BAD_KEY, FILED, KOMGA_DOWN, SAME, SOURCES, STORE_DOWN, SUBJECT, UNKNOWN_SUBJECT

PREFIX = "/internal/komga-key/"
ROUTE_LABEL = PREFIX + "{subject}"
FIELDS = frozenset({"key", "source", "key_id"})
STATUS = {FILED: 204, SAME: 204, UNKNOWN_SUBJECT: 403, BAD_KEY: 422, KOMGA_DOWN: 503, STORE_DOWN: 503}


def subject_from_route(route: str) -> Optional[str]:
    """The 64-hex subject digest from the normalised path, or None. It names whose key this is; it is never a
    viewer identity and grants nothing (the bearer token does)."""
    if not route.startswith(PREFIX):
        return None
    tail = route[len(PREFIX):]
    return tail if SUBJECT.fullmatch(tail) else None


def peer_allowed(host: Optional[str], networks) -> bool:
    if not host or not networks:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if getattr(addr, "ipv4_mapped", None) is not None:
        addr = addr.ipv4_mapped
    return any(addr.version == net.version and addr in net for net in networks)


def token_ok(given: Optional[str], expected: str) -> bool:
    if not expected or not isinstance(given, str):
        return False
    return hmac.compare_digest(given.encode("utf-8", "replace"), expected.encode("utf-8"))


def parse_body(raw: Optional[bytes]) -> Optional[Tuple[str, str, Optional[str]]]:
    """(key, source, key_id or None) from the JSON body, or None for anything but exactly that shape. The values are
    checked again by KeyIntake; here only the shape."""
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or not set(data) <= FIELDS or not {"key", "source"} <= set(data):
        return None
    key, source, key_id = data.get("key"), data.get("source"), data.get("key_id")
    if not isinstance(key, str) or source not in SOURCES or not (key_id is None or isinstance(key_id, str)):
        return None
    return key, source, key_id
