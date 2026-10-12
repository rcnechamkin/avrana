"""Timeouts, call budget, circuit breaker, transport interface and safe failure logging.

Status: proposed, not deployed. Standard library only.

Rules from docs/design/MEDIA-2.0.md section 5: a bounded timeout per call (about 2 s), NO
retries in the request path, a cool-off (about 60 s) after repeated service-wide failures so a
struggling service is not hammered (see `counts_toward_breaker` for exactly which failures count), and errors logged with the service name and error class only (never member
identity, titles, URLs or exception messages, which can carry either).

All time comes from an injectable clock so tests never sleep.
"""
from __future__ import annotations

import http.client
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Mapping, Optional, Protocol

DEFAULT_TIMEOUT = 2.0
REQUEST_BUDGET = DEFAULT_TIMEOUT   # one deadline for a whole request: mapping AND work together
DEFAULT_TRIAL_LEASE = 30.0
DEFAULT_COOLOFF = 60.0
MAX_JSON_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024

log = logging.getLogger("avrana_home")


class Clock(Protocol):
    def now(self) -> float: ...


class SystemClock:
    def now(self) -> float:
        return time.monotonic()


class FakeClock:
    """Test clock: time moves only when told to."""

    def __init__(self, start: float = 1000.0):
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# ---- errors: classes carry NO message content that could include identity or URLs ---------
class UpstreamError(Exception):
    pass


class UpstreamTimeout(UpstreamError):
    pass


class UpstreamUnreachable(UpstreamError):
    pass


class UpstreamHTTPError(UpstreamError):
    def __init__(self, status: int):
        super().__init__(f"http {status}")
        self.status = status


class UpstreamAuthError(UpstreamHTTPError):
    """401 or 403 from the upstream: the service credential is wrong or too weak."""


class UpstreamNotFound(UpstreamHTTPError):
    """404. Benign for a single item; does not trip the circuit."""


class UpstreamMalformed(UpstreamError):
    """Body was not the JSON shape the contract expects."""


class UpstreamTooLarge(UpstreamError):
    pass


class UpstreamMisbehaved(UpstreamError):
    """Response contradicts the request scope (for example another member's identity)."""


def log_failure(service: str, exc: BaseException) -> None:
    # service name and error class only: no message, no URL, no member, no title
    log.warning("adapter_failure service=%s error=%s", service, type(exc).__name__)


# ---- transport ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TransportResponse:
    status: int
    body: bytes
    content_type: str = ""


class Transport(Protocol):
    """Injectable I/O. The base URL and the credential live INSIDE the transport; adapters,
    results and logs never see them."""

    def request(self, method: str, path: str, query: Optional[Mapping[str, str]],
                timeout: float, max_bytes: int) -> TransportResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # a redirect could carry the credential elsewhere
        return None


class UrllibTransport:
    """Real transport (not used by any test against a network; an opener can be injected).
    Never follows redirects, bounds the body, maps failures to UpstreamError classes."""

    def __init__(self, base_url: str, auth_headers: Mapping[str, str], opener=None):
        if not base_url.startswith(("http://", "https://")) or base_url.endswith("/"):
            raise ValueError("base_url must be http(s) without a trailing slash")
        self._base = base_url
        self._headers = dict(auth_headers)
        self._opener = opener or urllib.request.build_opener(_NoRedirect)

    def __repr__(self) -> str:
        return "UrllibTransport(<redacted>)"

    def request(self, method, path, query, timeout, max_bytes):
        from urllib.parse import urlencode
        url = self._base + path + (("?" + urlencode(query)) if query else "")
        req = urllib.request.Request(url, method=method, headers=self._headers)
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                body = resp.read(max_bytes + 1)
                status = resp.status
                ctype = resp.headers.get("Content-Type", "") if resp.headers else ""
        except urllib.error.HTTPError as exc:
            raise classify_status(exc.code) from None
        except TimeoutError:
            raise UpstreamTimeout() from None
        except urllib.error.URLError as exc:
            raise (UpstreamTimeout() if isinstance(exc.reason, TimeoutError) else UpstreamUnreachable()) from None
        except (http.client.HTTPException, OSError):
            raise UpstreamUnreachable() from None
        except (ValueError, RecursionError):
            raise UpstreamMalformed() from None
        if len(body) > max_bytes:
            raise UpstreamTooLarge()
        return TransportResponse(status, body, ctype)


def classify_status(status: int) -> UpstreamHTTPError:
    if status in (401, 403):
        return UpstreamAuthError(status)
    if status == 404:
        return UpstreamNotFound(status)
    return UpstreamHTTPError(status)


def counts_toward_breaker(exc: BaseException, member_scoped: bool = False) -> bool:
    """Shared-circuit policy. Only SERVICE-WIDE evidence counts: timeouts, connection errors,
    5xx, 429, unexpected 3xx, 401 (the service credential is refused), malformed or oversized
    payloads, and responses that contradict the request scope. A 404 and other 4xx describe one
    member's or one item's request, so they never open the circuit that every member shares.
    A 403 counts only when it is not on a member-scoped call (403 on the user list means the
    service credential lacks rights; 403 on one member's call is about that member). Both auth
    behaviours are UNVERIFIED against a real Jellyfin."""
    if isinstance(exc, UpstreamNotFound):
        return False
    if isinstance(exc, UpstreamAuthError):
        return not (member_scoped and exc.status == 403)
    if isinstance(exc, UpstreamHTTPError):
        return exc.status >= 500 or exc.status == 429 or 300 <= exc.status < 400
    return isinstance(exc, UpstreamError)


_MALFORMED = (RecursionError, ValueError, TypeError, KeyError, IndexError, AttributeError,
              ArithmeticError, MemoryError)


def coerce(exc: BaseException) -> Optional[UpstreamError]:
    """Convert anything an upstream (or a transport) can provoke into an UpstreamError. Returns
    None for exceptions that are not upstream-controlled (programming errors), which propagate."""
    if isinstance(exc, UpstreamError):
        return exc
    if isinstance(exc, TimeoutError):
        return UpstreamTimeout()
    if isinstance(exc, (http.client.HTTPException, OSError)):
        return UpstreamUnreachable()
    if isinstance(exc, _MALFORMED):
        return UpstreamMalformed()
    return None


# ---- per-section time budget -------------------------------------------------------------
class CallBudget:
    """Bounds one section to roughly `total` seconds across several requests."""

    def __init__(self, clock: Clock, total: float = DEFAULT_TIMEOUT):
        self._clock = clock
        self._deadline = clock.now() + total

    def remaining(self) -> float:
        left = self._deadline - self._clock.now()
        if left <= 0:
            raise UpstreamTimeout()
        return left


# ---- circuit -----------------------------------------------------------------------------
@dataclass(frozen=True)
class AdapterHealth:
    service: str
    state: str                       # "unknown" | "ok" | "cooling_off"
    last_error_class: Optional[str] = None
    retry_in_seconds: Optional[int] = None

    def to_dict(self) -> dict:
        return {"service": self.service, "state": self.state,
                "last_error_class": self.last_error_class,
                "retry_in_seconds": self.retry_in_seconds}


class CircuitBreaker:
    """Cool-off circuit shared by every member of one adapter.

    * Only `threshold` CONSECUTIVE counted failures open it (see `counts_toward_breaker`), so a
      single unlucky request cannot shut the service for everyone; any success resets the run.
    * Open for `cooloff` seconds: `acquire()` refuses with no upstream traffic.
    * Half-open after the cool-off: exactly ONE trial call is admitted at a time; success closes,
      one failure re-opens for a full cool-off, a neutral result frees the slot. The trial holds a
      lease: if it never reports (a caller vanished), one new trial is admitted after the lease
      and the lost trial's epoch is invalidated.
    * Every opening bumps an epoch. Results carry the token they were admitted with; a result whose
      token is stale (a hung call finishing late) is ignored and may not populate a cache.
    No retries are ever made inside a request.
    """

    def __init__(self, clock: Clock, cooloff: float = DEFAULT_COOLOFF, threshold: int = 3,
                 trial_lease: float = DEFAULT_TRIAL_LEASE):
        self._clock = clock
        self._lease = trial_lease
        self._trial_until = 0.0
        self._cooloff = cooloff
        self._threshold = max(1, threshold)
        self._open_until = 0.0
        self._opened = False
        self._trial = False
        self._failures = 0
        self._epoch = 0
        self._seen = False
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()

    def acquire(self) -> Optional[int]:
        with self._lock:
            if self._clock.now() < self._open_until:
                return None
            if self._opened:
                now = self._clock.now()
                if self._trial:
                    if now < self._trial_until:
                        return None
                    self._epoch += 1             # the lost trial's late result must be ignored
                self._trial = True
                self._trial_until = now + self._lease
            return self._epoch

    def valid(self, token: Optional[int]) -> bool:
        with self._lock:
            return token is not None and token == self._epoch

    def success(self, token: Optional[int]) -> bool:
        with self._lock:
            if token != self._epoch:
                return False
            self._seen = True
            self._failures = 0
            self._opened = False
            self._trial = False
            self._open_until = 0.0
            self._last_error = None
            return True

    def failure(self, error_class: str, token: Optional[int]) -> bool:
        with self._lock:
            if token != self._epoch:
                return False
            self._seen = True
            self._last_error = error_class
            self._failures += 1
            if self._opened or self._failures >= self._threshold:
                self._open()
            return True

    def neutral(self, token: Optional[int]) -> None:
        with self._lock:
            if token == self._epoch:
                self._trial = False

    def force_open(self, error_class: str) -> None:
        with self._lock:
            self._seen = True
            self._last_error = error_class
            self._open()

    def _open(self) -> None:
        self._open_until = self._clock.now() + self._cooloff
        self._opened = True
        self._trial = False
        self._failures = 0
        self._epoch += 1

    def snapshot(self, service: str) -> AdapterHealth:
        with self._lock:
            now = self._clock.now()
            if now < self._open_until:
                return AdapterHealth(service, "cooling_off", self._last_error,
                                     int(self._open_until - now) + 1)
            # after a cool-off with no success yet the state is unknown until the trial call
            state = "ok" if self._seen and not self._opened else "unknown"
            return AdapterHealth(service, state, self._last_error, None)
