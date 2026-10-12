"""Gather sections from several adapters independently, and summarise adapter health.

Status: proposed, not deployed. Standard library only.

One failing, slow or hung adapter yields UNAVAILABLE for its own section only; the others
still return. Sections run concurrently with a hard wall-clock cap as a backstop to the
per-call timeouts (a transport that ignores its timeout cannot hold the page).

Hung calls: Python cannot kill a thread, so concurrency is BOUNDED instead. Work runs on one
shared, fixed-size pool (never a pool per request); each adapter allows only a few in-flight
upstream calls, and further requests get UNAVAILABLE ("busy") immediately without starting any
work. At the hard cap the adapter's circuit is force-opened, which also bumps its epoch: a hung
call that finishes late can neither close the circuit nor populate a cache. Queued work that has
not started when the cap hits is cancelled and touches no circuit.
"""
from __future__ import annotations

import concurrent.futures as cf
import queue
import threading
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

from .contract import DEFAULT_LIMIT, MediaAdapter, SectionResult, SectionState
from .principal import MemberPrincipal, is_minted_principal
from .resilience import REQUEST_BUDGET, log_failure

DEFAULT_HARD_CAP = REQUEST_BUDGET + 1.0   # always above one request's own deadline
HARD_CAP_MARGIN = 1.0
POOL_WORKERS = 48          # >= adapters x per-adapter in-flight cap (4 x 8 = 32) with headroom


class _DaemonPool:
    """A fixed-size pool of DAEMON threads. `concurrent.futures.ThreadPoolExecutor` threads are
    joined at interpreter exit, so one hung upstream call would keep a shutting-down process alive;
    these are not. Same `submit` shape, returns a `concurrent.futures.Future` (cancellable while
    queued)."""

    def __init__(self, workers: int, prefix: str):
        self._q: "queue.SimpleQueue" = queue.SimpleQueue()
        self._workers = workers
        self._prefix = prefix
        self._threads: list = []
        self._lock = threading.Lock()

    def submit(self, fn, *args) -> cf.Future:
        fut: cf.Future = cf.Future()
        self._q.put((fut, fn, args))
        with self._lock:
            if len(self._threads) < self._workers:
                t = threading.Thread(target=self._run, name=f"{self._prefix}-{len(self._threads)}",
                                     daemon=True)
                self._threads.append(t)
                t.start()
        return fut

    def _run(self) -> None:
        while True:
            fut, fn, args = self._q.get()
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn(*args))
            except BaseException as exc:          # delivered through the future, never lost
                fut.set_exception(exc)

    def shutdown(self, wait: bool = True) -> None:   # pragma: no cover - daemon threads just end
        pass


_pool = None
_pool_lock = threading.Lock()


def _shared_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = _DaemonPool(POOL_WORKERS, "avrana-section")
        return _pool


def derive_hard_cap(adapters: Sequence[MediaAdapter]) -> float:
    """The wall-clock backstop for a page: the longest request deadline any of these adapters
    enforces, plus a margin. An adapter built with a larger timeout therefore gets a larger cap
    instead of being cut off by a constant; with no adapters (or defaults) it is DEFAULT_HARD_CAP."""
    longest = max((getattr(a, "request_timeout", REQUEST_BUDGET) for a in adapters), default=REQUEST_BUDGET)
    return longest + HARD_CAP_MARGIN


_METHODS = {"continue": "continue_items", "recent": "recent_items"}


@dataclass(frozen=True)
class HomeSections:
    sections: Tuple[SectionResult, ...]

    def member_view(self) -> dict:
        """JSON-serialisable view for the UI. NOT_PERMITTED sections are omitted entirely so the
        caller renders absence, with no hint that the service exists."""
        return {"sections": [s.to_dict() for s in self.sections
                             if s.state is not SectionState.NOT_PERMITTED]}


def gather(principal: MemberPrincipal, adapters: Sequence[MediaAdapter],
           sections: Iterable[str] = ("continue", "recent"), limit: int = DEFAULT_LIMIT,
           hard_cap: Optional[float] = None) -> HomeSections:
    if not is_minted_principal(principal):
        raise TypeError("gather takes a parser-minted MemberPrincipal")
    wanted = [s for s in sections if s in _METHODS]
    jobs = [(a, s) for a in adapters for s in wanted]
    if not jobs:
        return HomeSections(())
    if hard_cap is None:
        hard_cap = derive_hard_cap(adapters)
    pool = _shared_pool()
    futures = [pool.submit(getattr(a, _METHODS[s]), principal, limit) for a, s in jobs]
    done, pending = cf.wait(futures, timeout=hard_cap)
    never_started = {fut for fut in pending if fut.cancel()}   # queued work is dropped; running work is not
    out = []
    for (adapter, section), fut in zip(jobs, futures):
        if fut in never_started:
            # It never ran, so it is no evidence about the adapter: no circuit is touched.
            out.append(SectionResult(adapter.service, section, SectionState.UNAVAILABLE, reason="queued"))
            continue
        if fut not in done:
            adapter.breaker.force_open("HardCap")
            out.append(SectionResult(adapter.service, section, SectionState.UNAVAILABLE, reason="hard_cap"))
            continue
        try:
            out.append(fut.result())
        except Exception as exc:
            # A programming error in OUR adapter code (upstream-provoked failures never reach here):
            # it costs its own section only, is logged by class, and opens that adapter circuit.
            log_failure(adapter.service.value, exc)
            adapter.breaker.force_open(type(exc).__name__)
            out.append(SectionResult(adapter.service, section, SectionState.UNAVAILABLE,
                                     reason=type(exc).__name__))
    return HomeSections(tuple(out))


def health_summary(adapters: Sequence[MediaAdapter]) -> dict:
    """Per-adapter state for a future /healthz. No member data, no upstream calls: the state is
    what the request path last observed (unknown until the first call)."""
    rows = [a.health().to_dict() for a in adapters]
    degraded = any(r["state"] in ("cooling_off", "failing") for r in rows)
    return {"home": "ok", "libraries": "degraded" if degraded else "ok", "adapters": rows}
