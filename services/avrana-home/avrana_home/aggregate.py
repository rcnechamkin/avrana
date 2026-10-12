"""Gather sections from several adapters independently, and summarise adapter health.

Status: proposed, not deployed. Standard library only.

One failing, slow or hung adapter yields UNAVAILABLE for its own section only; the others
still return. Sections run concurrently with a hard wall-clock cap as a backstop to the
per-call timeouts (a transport that ignores its timeout cannot hold the page).
"""
from __future__ import annotations

import concurrent.futures as cf
from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

from .contract import DEFAULT_LIMIT, MediaAdapter, SectionResult, SectionState
from .principal import MemberPrincipal
from .resilience import log_failure

DEFAULT_HARD_CAP = 3.0
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
           hard_cap: float = DEFAULT_HARD_CAP) -> HomeSections:
    if not isinstance(principal, MemberPrincipal):
        raise TypeError("gather takes a MemberPrincipal")
    wanted = [s for s in sections if s in _METHODS]
    jobs = [(a, s) for a in adapters for s in wanted]
    if not jobs:
        return HomeSections(())
    pool = cf.ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="avrana-section")
    futures = [pool.submit(getattr(a, _METHODS[s]), principal, limit) for a, s in jobs]
    done, _ = cf.wait(futures, timeout=hard_cap)
    pool.shutdown(wait=False, cancel_futures=True)   # a hung call must not hold the response
    out = []
    for (adapter, section), fut in zip(jobs, futures):
        if fut not in done:
            adapter.breaker.record_failure("HardCap")
            out.append(SectionResult(adapter.service, section, SectionState.UNAVAILABLE, reason="hard_cap"))
            continue
        try:
            out.append(fut.result())
        except Exception as exc:  # an adapter bug must cost its own section only
            log_failure(adapter.service.value, exc)
            adapter.breaker.record_failure(type(exc).__name__)
            out.append(SectionResult(adapter.service, section, SectionState.UNAVAILABLE,
                                     reason=type(exc).__name__))
    return HomeSections(tuple(out))


def health_summary(adapters: Sequence[MediaAdapter]) -> dict:
    """Per-adapter state for a future /healthz. No member data, no upstream calls: the state is
    what the request path last observed (unknown until the first call)."""
    rows = [a.health().to_dict() for a in adapters]
    degraded = any(r["state"] == "cooling_off" for r in rows)
    return {"home": "ok", "libraries": "degraded" if degraded else "ok", "adapters": rows}
