"""Test helpers: principals built the only legal way, and a configurable fake adapter.

All data here is synthetic. No test in this package opens a network socket.
"""
import threading

from avrana_home.contract import (ArtworkResult, ArtworkRef, Kind, MappingFailed, MediaAdapter,
                                  MediaItem, SectionResult, SectionState, Service,
                                  UpstreamUser, build_handoff_url)
from avrana_home.principal import principal_from_headers
from avrana_home.resilience import UpstreamTimeout

GROUP_FOR = {Service.JELLYFIN: "avrana-videos", Service.AUDIOBOOKSHELF: "avrana-audiobooks",
             Service.KOMGA: "avrana-comics", Service.CALIBRE_WEB: "avrana-books"}
ID_FOR = {Service.JELLYFIN: "0" * 31, Service.AUDIOBOOKSHELF: "li_syntheticid",
          Service.KOMGA: "SynthId", Service.CALIBRE_WEB: "1"}


def make_principal(username="member-a", groups=("avrana-videos",)):
    return principal_from_headers({"X-authentik-username": username,
                                   "X-authentik-groups": "|".join(groups)})


def item_id(service, n):
    base = ID_FOR[service]
    if service is Service.JELLYFIN:
        return base + str(n)
    if service is Service.CALIBRE_WEB:
        return str(n)
    return base + str(n)


class FakeAdapter(MediaAdapter):
    """Maps usernames to upstream ids, returns that member's items, counts upstream calls."""

    def __init__(self, service, users, clock, mode="ok", **kw):
        self.service = service
        super().__init__(clock=clock, **kw)
        self.users = users              # username -> upstream user id
        self.mode = mode                # ok | timeout | boom | block
        self.calls = 0
        self.release = threading.Event()
        self.block_users = None         # None: "block" mode blocks everyone; else only these names
        self.block_ops = None           # None: every operation; else only these ("resolve", "items", "artwork")
        self.started = threading.Semaphore(0)
        self.work_exc = None            # raised by every non-mapping operation (after the call is counted)

    def _enter(self, op="items", username=None):
        self.calls += 1
        if self.work_exc is not None and op != "resolve":
            raise self.work_exc
        if self.mode == "timeout":
            raise UpstreamTimeout()
        if self.mode == "boom":
            raise RuntimeError("synthetic adapter bug")
        if self.mode == "block" and (self.block_users is None or username in self.block_users)                 and (self.block_ops is None or op in self.block_ops):
            self.started.release()
            self.release.wait(5)

    def _name_of(self, user):
        return next((n for n, uid in self.users.items() if uid == user.upstream_id), None)

    def _resolve_user(self, principal):
        self._enter("resolve", principal.username)
        uid = self.users.get(principal.username)
        if uid is None:
            raise MappingFailed("unmapped")
        return UpstreamUser(self.service, uid)

    def _items(self, user, section):
        self._enter("items", self._name_of(user))
        n = int(user.upstream_id)
        it = MediaItem(id=f"{self.service.value}:{item_id(self.service, n)}", service=self.service,
                       kind=Kind.MOVIE, title=f"Synthetic Title {n}",
                       handoff_url=build_handoff_url(self.service, item_id(self.service, n)),
                       artwork=ArtworkRef(f"{self.service.value}/primary/{item_id(self.service, n)}",
                                          f"Poster for Synthetic Title {n}"))
        return SectionResult.of(self.service, section, (it,))

    def _continue_items(self, user, limit):
        return self._items(user, "continue")

    def _recent_items(self, user, limit):
        return self._items(user, "recent")

    def _fetch_artwork(self, user, ref):
        self._enter("artwork", self._name_of(user))
        return ArtworkResult(SectionState.OK, "image/png", b"synthetic")
