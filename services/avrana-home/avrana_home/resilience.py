"""Timeouts, call budget, circuit breaker, transport interface and safe failure logging.

Status: proposed, not deployed. Standard library only.

Rules from docs/design/MEDIA-2.0.md section 5: a bounded timeout per call (about 2 s), NO
retries in the request path, a cool-off (about 60 s) after a failure so a struggling service is
not hammered, and errors logged with the service name and error class only (never member
identity, titles, URLs or exception messages, which can carry either).

All time comes from an injectable clock so tests never sleep.
"""
from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Mapping, Optional, Protocol

DEFAULT_TIMEOUT = 2.0
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
        except (urllib.error.URLError, OSError):
            raise UpstreamUnreachable() from None
        if len(body) > max_bytes:
            raise UpstreamTooLarge()
        return TransportResponse(status, body, ctype)


def classify_status(status: int) -> UpstreamHTTPError:
    if status in (401, 403):
        return UpstreamAuthError(status)
    if status == 404:
        return UpstreamNotFound(status)
    return UpstreamHTTPError(status)


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
    """Cool-off circuit. One failure opens it for `cooloff` seconds; calls are then refused with
    no upstream traffic. After the cool-off the next call is allowed through (a trial); a
    failure re-opens it, a success closes it. No retries are ever made inside a request."""

    def __init__(self, clock: Clock, cooloff: float = DEFAULT_COOLOFF):
        self._clock = clock
        self._cooloff = cooloff
        self._open_until = 0.0
        self._seen = False
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            return self._clock.now() >= self._open_until

    def record_failure(self, error_class: str) -> None:
        with self._lock:
            self._seen = True
            self._last_error = error_class
            self._open_until = self._clock.now() + self._cooloff

    def record_success(self) -> None:
        with self._lock:
            self._seen = True
            self._last_error = None
            self._open_until = 0.0

    def snapshot(self, service: str) -> AdapterHealth:
        with self._lock:
            now = self._clock.now()
            if now < self._open_until:
                return AdapterHealth(service, "cooling_off", self._last_error,
                                     int(self._open_until - now) + 1)
            # after a cool-off with no success yet the state is unknown until the next trial call
            state = "ok" if self._seen and self._last_error is None else "unknown"
            return AdapterHealth(service, state, self._last_error, None)
