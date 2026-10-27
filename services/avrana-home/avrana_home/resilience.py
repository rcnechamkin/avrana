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
import io
import logging
import math
import socket
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


class FanOutSpent(UpstreamError):
    """OUR per-item lookups used up the section's budget after the service had already answered in this
    request (Audiobookshelf Continue: one lookup per progress entry). The section is UNAVAILABLE for this
    member, but it is no evidence that the service is down, so it never counts toward the shared circuit."""
    pass


class UpstreamHTTPError(UpstreamError):
    def __init__(self, status: int):
        super().__init__(f"http {status}")
        self.status = status


class UpstreamAuthError(UpstreamHTTPError):
    """401 or 403 from the upstream: the service credential is wrong or too weak."""


class UpstreamNotFound(UpstreamHTTPError):
    """A bare 404 from a transport. What it MEANS is declared by the route it came from (see the
    three subclasses); a 404 nobody classified is treated as route drift and counts."""


class UserGone(UpstreamNotFound):
    """404 on a route addressed by the bound upstream USER: that account no longer exists. One
    member's problem: never counted."""


class ItemGone(UpstreamNotFound):
    """404 on a route addressed by one ITEM: that item is absent (or hidden). Never counted."""


class RouteMissing(UpstreamNotFound):
    """404 on a FIXED route (no user, no item in the address): the route itself is gone, which is
    service-wide drift. Counted."""


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


READ_CHUNK = 16 * 1024
MAX_TRANSPORT_TIMEOUT = 30.0     # a larger (finite) timeout is capped; a non-finite one is refused


class _Abort:
    """Kills the connection of ONE request when its total deadline passes, so a read blocked in the
    kernel (a slow-drip upstream that sends a byte just often enough to keep a per-socket timeout from
    ever firing) is interrupted instead of holding the worker. `fired` tells the caller why it failed."""

    def __init__(self, deadline: float = float("inf"), now=time.monotonic) -> None:
        self._lock = threading.Lock()
        self._sock = None
        self.fired = False
        self.deadline = deadline
        self.now = now

    def attach(self, sock) -> None:
        with self._lock:
            self._sock = sock
            if self.fired:
                self._kill(sock)

    def fire(self) -> None:
        with self._lock:
            self.fired = True
            if self._sock is not None:
                self._kill(self._sock)

    @staticmethod
    def _kill(sock) -> None:
        for fn in (lambda: sock.shutdown(socket.SHUT_RDWR), sock.close):
            try:
                fn()
            except (OSError, ValueError):
                pass


class _DeadlineRaw(io.RawIOBase):
    """Reads a socket so that EVERY blocking receive is bounded by what is left of the request deadline: the
    socket timeout is set to the time left before each `recv_into`, and a passed deadline raises
    TimeoutError. This is what bounds the status line, the headers and a silent upstream (a timer that merely
    shuts the socket down from another thread is not reliable on every platform, notably Windows)."""

    def __init__(self, sock, abort: _Abort, on_close=None):
        super().__init__()
        self._sock = sock
        self._abort = abort
        self._on_close = on_close

    def readable(self) -> bool:
        return True

    def close(self) -> None:
        was_open = not self.closed
        super().close()
        if was_open and self._on_close is not None:
            self._on_close()

    def readinto(self, buffer) -> int:
        left = self._abort.deadline - self._abort.now()
        if left <= 0 or self._abort.fired:
            raise TimeoutError("deadline")
        self._sock.settimeout(left)
        return self._sock.recv_into(buffer)


class _DeadlineSocket:
    """The connection's socket as http.client sees it: reads go through `_DeadlineRaw`, everything else
    (sendall, close, shutdown, ...) is the real socket's."""

    def __init__(self, sock, abort: _Abort):
        self._s = sock
        self._abort = abort
        self._refs = 0                  # readers handed out; like socket.makefile, they keep the socket open
        self._closed = False
        self._lock = threading.Lock()

    def makefile(self, mode="rb", buffering=None, **kw):
        if mode != "rb":
            return self._s.makefile(mode, buffering, **kw)
        with self._lock:
            self._refs += 1
        return io.BufferedReader(_DeadlineRaw(self._s, self._abort, self._release), READ_CHUNK)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            last = self._refs == 0
        if last:
            self._s.close()

    def _release(self) -> None:
        with self._lock:
            self._refs -= 1
            last = self._closed and self._refs == 0
        if last:
            self._s.close()

    def __getattr__(self, name):
        return getattr(self._s, name)


def _tracked(base, slot):
    """A connection class that tells the CURRENT request's `_Abort` which socket it is using (before and
    after any TLS wrap). `slot` is the transport's thread-local holder: `do_open` builds the connection in
    the calling thread, so it finds the abort of the request that thread is running, which lets one opener
    serve every request. The TLS handshake itself is bounded only by the per-operation timeout."""
    class Tracked(base):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._abort = abort = slot.abort
            create = self._create_connection
            self._create_connection = lambda *ca, **ck: _attached(abort, create(*ca, **ck))

        def connect(self):
            super().connect()
            self._abort.attach(self.sock)                # the real socket, for the timer to close
            self.sock = _DeadlineSocket(self.sock, self._abort)
    return Tracked


def _attached(abort: _Abort, sock):
    abort.attach(sock)
    return sock


class _TrackedHTTP(urllib.request.HTTPHandler):
    def __init__(self, slot):
        super().__init__()
        self._slot = slot

    def http_open(self, req):
        return self.do_open(_tracked(http.client.HTTPConnection, self._slot), req)


class _TrackedHTTPS(urllib.request.HTTPSHandler):
    def __init__(self, slot):
        super().__init__()
        self._slot = slot

    def https_open(self, req):
        return self.do_open(_tracked(http.client.HTTPSConnection, self._slot), req,
                            context=self._context)


class UrllibTransport:
    """Real transport (not used by any test against a network; an opener can be injected).
    Never follows redirects, bounds the body, maps failures to UpstreamError classes.

    `timeout` is a TOTAL monotonic deadline for the whole request (connect, headers and body), not a
    per-socket-operation timeout: the body is read in chunks against the deadline, and a timer closes
    the connection at the deadline so a read blocked on a slow-drip upstream is interrupted. The caller
    (and its in-flight slots) therefore get control back at about the deadline. Not covered: name
    resolution and the TLS handshake, which Python cannot interrupt (each is bounded only by the
    per-operation timeout). With an injected opener the deadline is checked between chunks only.
    Every blocking receive (status line, headers, body) has its socket timeout set to the time LEFT, so the
    bound does not depend on the timer interrupting a blocked call. A finite timeout is capped at
    MAX_TRANSPORT_TIMEOUT; NaN and infinities are refused (UpstreamTimeout, no I/O)."""

    def __init__(self, base_url: str, auth_headers: Mapping[str, str], opener=None):
        if not base_url.startswith(("http://", "https://")) or base_url.endswith("/"):
            raise ValueError("base_url must be http(s) without a trailing slash")
        self._base = base_url
        self._headers = dict(auth_headers)
        self._slot = threading.local()        # the abort of the request the calling thread is running
        # Built ONCE: urllib's build_opener costs ~25 ms on Windows (proxy discovery, handler scan), which
        # per request ate a fifth of a 0.6 s section budget that spans a member's sequential calls.
        # ProxyHandler({}): never a proxy from HTTP(S)_PROXY or the Windows registry, which would receive the
        # upstream's bearer token (the Audiobookshelf one is admin-capable) over a plain-http base URL.
        self._opener = opener if opener is not None else urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect, _TrackedHTTP(self._slot), _TrackedHTTPS(self._slot))

    def __repr__(self) -> str:
        return "UrllibTransport(<redacted>)"

    def request(self, method, path, query, timeout, max_bytes):
        from urllib.parse import urlencode
        url = self._base + path + (("?" + urlencode(query)) if query else "")
        req = urllib.request.Request(url, method=method, headers=self._headers)
        if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout)
                or not timeout > 0):
            raise UpstreamTimeout()                      # NaN, infinities, zero, negatives, bools, non-numbers
        timeout = min(float(timeout), MAX_TRANSPORT_TIMEOUT)
        deadline = time.monotonic() + timeout
        abort = _Abort(deadline)
        self._slot.abort = abort
        timer = threading.Timer(timeout, abort.fire)
        timer.daemon = True
        timer.start()

        def late() -> bool:
            return abort.fired or time.monotonic() >= deadline
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                status = resp.status
                ctype = resp.headers.get("Content-Type", "") if resp.headers else ""
                read = getattr(resp, "read1", None) or resp.read
                parts, size = [], 0
                while size <= max_bytes:
                    left = deadline - time.monotonic()
                    if left <= 0 or abort.fired:
                        raise UpstreamTimeout()
                    part = read(min(READ_CHUNK, max_bytes + 1 - size))
                    if not part:
                        break
                    parts.append(part)
                    size += len(part)
                body = b"".join(parts)
                if abort.fired:                          # never a truncated success when the timer fired
                    raise UpstreamTimeout()
        except UpstreamTimeout:
            raise
        except urllib.error.HTTPError as exc:
            raise classify_status(exc.code) from None
        except TimeoutError:
            raise UpstreamTimeout() from None
        except urllib.error.URLError as exc:
            raise (UpstreamTimeout() if late() or isinstance(exc.reason, TimeoutError)
                   else UpstreamUnreachable()) from None
        except (http.client.HTTPException, OSError):
            raise (UpstreamTimeout() if late() else UpstreamUnreachable()) from None
        except (ValueError, RecursionError):
            raise (UpstreamTimeout() if late() else UpstreamMalformed()) from None
        finally:
            timer.cancel()
            self._slot.abort = None
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
    member's or one item's request, so they never open the circuit that every member shares (a 404 counts only when the ROUTE
    declares it means the route is gone: RouteMissing or unclassified).
    A 403 counts only when it is not on a member-scoped call (403 on the user list means the
    service credential lacks rights; 403 on one member's call is about that member). Both auth
    behaviours are UNVERIFIED against a real Jellyfin."""
    if isinstance(exc, (UserGone, ItemGone, FanOutSpent)):
        return False
    if isinstance(exc, UpstreamNotFound):
        return True              # RouteMissing, or a 404 nobody classified: drift
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
    # "unknown"     never heard from, or a cool-off ended and the trial call has not reported
    # "ok"          closed, no failure in the current run
    # "failing"     closed, but 1..threshold-1 CONSECUTIVE counted failures so far (early outage)
    # "cooling_off" open: no upstream traffic until retry_in_seconds has passed
    state: str
    last_error_class: Optional[str] = None
    retry_in_seconds: Optional[int] = None
    consecutive_failures: int = 0

    def to_dict(self) -> dict:
        return {"service": self.service, "state": self.state,
                "last_error_class": self.last_error_class,
                "retry_in_seconds": self.retry_in_seconds,
                "consecutive_failures": self.consecutive_failures}


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

    def closed(self) -> bool:
        """True while the circuit has not opened (no cool-off, no half-open trial pending). Read-only."""
        with self._lock:
            return not self._opened and self._clock.now() >= self._open_until

    def acquire(self, trial: bool = True) -> Optional[int]:
        """A token for one call, or None (open, or the half-open trial is taken). `trial=False` (artwork, review
        of #57) never takes the half-open trial: it is refused whenever the circuit has opened and not yet been
        closed again by a real trial, so only a call that reports success or failure can close it."""
        with self._lock:
            if self._clock.now() < self._open_until:
                return None
            if self._opened and not trial:
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
            if self._opened or not self._seen:
                return AdapterHealth(service, "unknown", self._last_error, None, 0)
            if self._failures > 0:
                return AdapterHealth(service, "failing", self._last_error, None, self._failures)
            return AdapterHealth(service, "ok", self._last_error, None, 0)
