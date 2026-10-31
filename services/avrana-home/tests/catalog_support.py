"""Shared by the catalogue adapter tests. Offline, SYNTHETIC data only."""
import json

from avrana_home.contract import SectionState
from avrana_home.principal import principal_from_headers
from avrana_home.resilience import TransportResponse, classify_status

UID_A, UID_B = "a" * 32, "b" * 32
ABS_A, ABS_B = "00000000-0000-4000-8000-00000000000a", "00000000-0000-4000-8000-00000000000b"
LIB_1, LIB_2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
KEY_A, KEY_B = "a" * 32, "b" * 32
ALL = "avrana-videos|avrana-audiobooks|avrana-comics|avrana-books"
SIZES = (0, 1, 24, 25, 50, 1000, 25000)


def member(name, groups=ALL):
    return principal_from_headers({"X-authentik-username": name, "X-authentik-groups": groups,
                                   "X-authentik-email": f"{name}@example.org"})


class Wire:
    """A Transport over a `handle(path, query) -> (status, body)`. Counts every call."""

    def __init__(self, handle, ctype="application/json"):
        self.handle, self.ctype, self.calls = handle, ctype, []

    def request(self, method, path, query, timeout, max_bytes):
        self.calls.append((path, dict(query or {})))
        status, body = self.handle(path, dict(query or {}))
        if status >= 400:
            raise classify_status(status)
        return TransportResponse(status, body if isinstance(body, bytes) else json.dumps(body).encode(), self.ctype)


def walk(adapter, who, group, size=24, most=1100):
    """Every page until the adapter says there is no next: all entries, and the calls' page count."""
    seen, page = [], 1
    while True:
        out = adapter.catalog(who, group, page, size)
        assert out.state in (SectionState.OK, SectionState.EMPTY), out
        seen += list(out.items)
        if not out.has_next:
            return seen, page
        page += 1
        assert page < most, "the walk did not end"


