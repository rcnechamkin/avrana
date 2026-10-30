"""Synthetic adapters whose answer, per section, is a plan: ok / empty / unavailable / not_linked.

Used by the degraded-route tests (test_web_degraded_matrix.py, test_web_released_fallback.py): the REAL app, router, view
models and templates run on top of these, so a state only the live libraries produce (for example Audiobooks and Comics
with nothing added lately) can be put through HTTP without a mock server. Everything here is synthetic.
"""
from __future__ import annotations

from avrana_home.contract import (ArtworkRef, Kind, MappingFailed, MediaAdapter, MediaItem, SectionResult, SectionState,
                                  Service, UpstreamUser, build_handoff_url)

SERVICES = (Service.JELLYFIN, Service.AUDIOBOOKSHELF, Service.KOMGA, Service.CALIBRE_WEB)
KIND = {Service.JELLYFIN: Kind.MOVIE, Service.AUDIOBOOKSHELF: Kind.AUDIOBOOK, Service.KOMGA: Kind.COMIC,
        Service.CALIBRE_WEB: Kind.EBOOK}
# The sections each real adapter offers (extra_sections plus the core pair); Komga's for_you is behind a flag.
OFFERED = {Service.JELLYFIN: ("continue", "recent", "next_up", "released", "for_you"),
           Service.AUDIOBOOKSHELF: ("continue", "recent", "shelves", "released", "for_you"),
           Service.KOMGA: ("continue", "recent", "shelves", "released", "week"),
           Service.CALIBRE_WEB: ("continue", "recent", "released")}
STATES = ("ok", "empty", "unavailable", "not_linked")
SHELVES = ("new", "classics", "short", "epic")
ALL_GROUPS = "avrana-users|avrana-videos|avrana-audiobooks|avrana-comics|avrana-books"
COMICS_GROUPS = "avrana-users|avrana-comics"


def upstream_id(service, n):
    return {Service.JELLYFIN: f"{n:032x}", Service.AUDIOBOOKSHELF: f"li_synthetic{n:03d}",
            Service.KOMGA: f"SYNTHKOMGA{n:03d}", Service.CALIBRE_WEB: str(n)}[service]


class PlanAdapter(MediaAdapter):
    """`plan` maps a section name to a state (default ok). `linked=False` makes the whole library not_linked, the way an
    unmapped member is. `distinct` gives each section its own ids (otherwise the sections overlap, as live data does).
    `released_override` is for tests that need a custom list of upstream ids for a section: {section: [ids]}."""

    def __init__(self, service, plan=None, linked=True, distinct=True, count=5, reason="UpstreamMisbehaved", **kw):
        self.service = service
        self.extra_sections = frozenset(s for s in OFFERED[service] if s not in ("continue", "recent"))
        super().__init__(**kw)
        self.plan, self.linked, self.distinct, self.count, self.reason = dict(plan or {}), linked, distinct, count, reason
        self.asked = []

    def _resolve_user(self, principal):
        if not self.linked:
            raise MappingFailed("unmapped")
        return UpstreamUser(self.service, "1")

    def _result(self, section):
        self.asked.append(section)
        state = self.plan.get(section, "ok")
        if state == "unavailable":
            return SectionResult(self.service, section, SectionState.UNAVAILABLE, reason=self.reason)
        if state == "not_linked":
            return SectionResult(self.service, section, SectionState.NOT_LINKED, reason="unmapped")
        if state == "empty":
            return SectionResult.of(self.service, section, ())
        svc = self.service
        base = (OFFERED[svc].index(section) * 10) if (self.distinct and section in OFFERED[svc]) else 0
        items = []
        for n in range(1, self.count + 1):
            i = upstream_id(svc, base + n)
            kw = {}
            if section == "continue":
                kw = dict(progress_fraction=0.4, position_seconds=400, duration_seconds=1000,
                          active=f"2026-10-2{n}T10:00:00Z")
            elif section == "shelves":
                kw = dict(shelf=SHELVES[n % 4])
            elif section in ("released", "week", "for_you"):
                kw = dict(released=f"2026-10-{20 + n:02d}", active=f"2026-10-2{n}T10:00:00Z")
            elif section == "next_up":
                kw = dict(shelf="next")
            items.append(MediaItem(id=f"{svc.value}:{i}", service=svc, kind=KIND[svc],
                                   title=f"Synthetic {svc.value} {section} {n}", handoff_url=build_handoff_url(svc, i),
                                   artwork=ArtworkRef(f"{svc.value}/primary/{i}", "Cover"), **kw))
        return SectionResult.of(svc, section, tuple(items))

    def _continue_items(self, user, limit):
        return self._result("continue")

    def _recent_items(self, user, limit):
        return self._result("recent")

    def _next_up_items(self, user, limit):
        return self._result("next_up")

    def _shelves_items(self, user, limit):
        return self._result("shelves")

    def _released_items(self, user, limit):
        return self._result("released")

    def _for_you_items(self, user, limit):
        return self._result("for_you")

    def _week_items(self, user, limit):
        return self._result("week")

    def _search(self, user, query, limit):
        return self._result("search")

    def _item(self, user, item_id):
        return self._result("item")


def adapters_for(plans, **kw):
    """One PlanAdapter per library from {Service: {section: state}} (missing library: all ok)."""
    return [PlanAdapter(s, (plans or {}).get(s), **kw) for s in SERVICES]
