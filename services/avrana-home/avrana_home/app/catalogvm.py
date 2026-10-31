"""The Library as a complete catalogue (handoff 02 and 06): display data for `library_catalog.html`, behind
HOME_LIBRARY_CATALOG. Pure functions, standard library only: nothing here calls an adapter, and everything from the
address (`?lib=`, `?group=`, `?view=`, `?page=`) is matched against fixed lists or this member's own libraries and is
never echoed. A library the member cannot use is never named, in the menu, a card, a count or a link.

Overview: one directory card per library, with the truthful count and up to three covers. Catalogue: the switcher, the
groupings the library can really page, one bounded page and plain Previous and Next links, so everything works with
no script at all."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple
from urllib.parse import urlencode

from .viewmodel import (KIND_LABEL, LIBRARY_LIST_CLASS, LIBRARY_VIEW_ALIAS, LIBRARY_VIEWS, SERVICE_LABEL,
                        SERVICE_ORDER, SETUP_HELP, CardVM, _cards, _item_vm, asks_heading_of, service_notice)

COVERS = 3                               # on an Overview card, decorative
CATALOG_VIEW_DEFAULT = "grid"            # one page of a catalogue is a wall of covers; "shelves" has no meaning here
# (service, group) -> what one entity is called, one and many. A count always says what it counts.
_NOUN = {("jellyfin", "movies"): ("movie", "movies"), ("jellyfin", "series"): ("show", "shows"),
         ("audiobookshelf", "titles"): ("audiobook", "audiobooks"), ("komga", "series"): ("series", "series"),
         ("calibre-web", "titles"): ("book", "books")}
GROUP_LABEL = {"movies": "Movies", "series": "TV shows", "titles": "Titles"}
NOTHING_YET = "Nothing in this library yet."
NOT_ANSWERING = "This library isn't answering right now."
PAST_THE_END = "There is nothing on this page."
HIDDEN_PAGE = "Nothing on this page is available to your account. There is more on the next page."
# Why Comics is not linked -> what the member can do about it, on Me -> Comics (the words of that page).
COMICS_STEP = {"no_member_key": ("Connect comics", "Comics isn't connected to your account yet."),
               "member_key_refused": ("Reconnect comics", "Comics needs reconnecting to your account.")}


@dataclass(frozen=True)
class CategoryVM:
    key: str
    label: str
    href: str
    state: str                            # ok | empty | unavailable | not_linked
    count: Optional[str] = None           # "83 series": only when it is exact for this member
    note: Optional[str] = None            # the words a card shows in place of a count, for a state
    covers: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SwitchVM:
    label: str
    href: str
    current: bool


@dataclass(frozen=True)
class LibraryCatalogVM:
    no_library: bool = False
    chosen: Optional[str] = None          # the library shown, None on the Overview
    chosen_label: Optional[str] = None
    menu: Tuple[SwitchVM, ...] = ()       # Overview and this member's own libraries, nothing else
    categories: Tuple[CategoryVM, ...] = ()
    groups: Tuple[Tuple[str, str, bool, str], ...] = ()    # (key, label, current, href), for tab_nav
    state: str = "ok"
    message: Optional[str] = None
    setup_label: Optional[str] = None     # the link's own words, when it says what it does
    setup_href: Optional[str] = None
    retry_href: Optional[str] = None
    count: Optional[str] = None
    items: Tuple[CardVM, ...] = ()
    page: int = 1
    prev_href: Optional[str] = None
    next_href: Optional[str] = None
    view: str = CATALOG_VIEW_DEFAULT
    view_label: str = "Grid"
    views: Tuple[Tuple[str, str, str, bool], ...] = ()     # (key, label, href, current): the layout menu
    list_class: str = LIBRARY_LIST_CLASS[CATALOG_VIEW_DEFAULT]
    asks: Tuple[Tuple[str, object, object], ...] = ()      # (href, label, description): catalogue text (Trusted)
    asks_heading: str = "Requests"


def clean_view(raw: Optional[str]) -> str:
    """The layout from the address: an old link's name still works; Shelves or anything else is the default."""
    view = LIBRARY_VIEW_ALIAS.get(raw, raw) if isinstance(raw, str) else None
    return view if view in LIBRARY_LIST_CLASS else CATALOG_VIEW_DEFAULT


def clean_page(raw: Optional[str]) -> int:
    """`?page=`, at most five ASCII digits, from 1; anything else is the first page."""
    if isinstance(raw, str) and raw.isascii() and raw.isdigit() and len(raw) <= 5 and int(raw) >= 1:
        return int(raw)
    return 1


def clean_group(raw: Optional[str], groups: Sequence[str]) -> str:
    return raw if raw in groups else groups[0]


def catalog_href(service: str, groups: Sequence[str], group: Optional[str] = None, view: str = CATALOG_VIEW_DEFAULT,
                 page: int = 1) -> str:
    """The one builder of a catalogue address: only allowed keys, each from a fixed list or a number, defaults left out."""
    query = [("lib", service)]
    if group and group != groups[0]:
        query.append(("group", group))
    if view != CATALOG_VIEW_DEFAULT:
        query.append(("view", view))
    if page > 1:
        query.append(("page", str(page)))
    return "/library?" + urlencode(query)


def count_words(service: str, group: str, total: Optional[int]) -> Optional[str]:
    if total is None or (service, group) not in _NOUN:
        return None
    one, many = _NOUN[(service, group)]
    return f"{total:,} {one if total == 1 else many}"


def _menu(mine: Sequence[Tuple[str, Tuple[str, ...]]], chosen: Optional[str]) -> Tuple[SwitchVM, ...]:
    return (SwitchVM("Overview", "/library", chosen is None),) + tuple(
        SwitchVM(SERVICE_LABEL[s], catalog_href(s, groups), s == chosen) for s, groups in mine)


def _ordered(mine):
    return sorted(mine, key=lambda pair: SERVICE_ORDER.index(pair[0]))


def _comics_step(service: str, res: dict, connect_href: Optional[str]):
    """(link words, sentence), when this member can fix an unlinked Comics themselves: only with the Me -> Comics page
    open to them, and only for a reason that page fixes. Anything else keeps the neutral words and the Help link."""
    return COMICS_STEP.get(res.get("reason")) if service == "komga" and connect_href else None


def build_overview(mine, results, *, asks=(), connect_href: Optional[str] = None) -> LibraryCatalogVM:
    """`mine`: (service, groups) for each library this member may use; `results`: {service: that library's first
    page as a SectionResult dict plus its `total`}. A library that did not answer is said so, never counted as nothing."""
    mine = _ordered(mine)
    cards, down = [], False
    for service, groups in mine:
        res = results[service]
        state, label = res["state"], SERVICE_LABEL[service]
        vms = [vm for vm in (_item_vm(it) for it in res.get("items", ())) if vm is not None]
        note = {"unavailable": "Not answering right now", "not_linked": "Not set up yet",
                "empty": "Nothing here yet"}.get(state)
        down = down or state == "unavailable"
        step = _comics_step(service, res, connect_href) if state == "not_linked" else None
        note = step[0] if step else note
        cards.append(CategoryVM(service, label, connect_href if step else catalog_href(service, groups), state,
                                count_words(service, groups[0], res.get("total")) if state == "ok" else None,
                                note, tuple(vm.image for vm in vms if vm.image)[:COVERS]))
    return LibraryCatalogVM(menu=_menu(mine, None), categories=tuple(cards), retry_href="/library" if down else None,
                            asks=tuple(asks), asks_heading=asks_heading_of(asks))


def build_catalog(mine, service: str, group: str, res: dict, *, page: int, view: str,
                  title_services=frozenset(), asks=(), connect_href: Optional[str] = None) -> LibraryCatalogVM:
    """One page of one library. `res`: its SectionResult as a dict plus `total` and `has_next`."""
    mine = _ordered(mine)
    groups = dict(mine)[service]
    label = SERVICE_LABEL[service]

    def href(g=group, v=view, n=1):
        return catalog_href(service, groups, g, v, n)
    state = res["state"]
    vms = [vm for vm in (_item_vm(it) for it in res.get("items", ())) if vm is not None]
    items = _cards(vms, lambda it: it.detail or KIND_LABEL.get(it.kind), title_services=title_services)
    has_next = bool(res.get("has_next")) and state == "ok"
    message = setup = setup_label = retry = None
    if state == "unavailable":
        message, retry = NOT_ANSWERING, href(n=page)
    elif state == "not_linked":
        message, setup = service_notice(service, "not_linked"), SETUP_HELP
        step = _comics_step(service, res, connect_href)
        if step:
            setup_label, message, setup = step[0], step[1], connect_href
    elif state == "empty":
        message = PAST_THE_END if page > 1 else NOTHING_YET
    elif not items and has_next:
        message = HIDDEN_PAGE
    return LibraryCatalogVM(
        chosen=service, chosen_label=label, menu=_menu(mine, service),
        groups=tuple((g, GROUP_LABEL[g], g == group, href(g=g)) for g in groups) if len(groups) > 1 else (),
        state=state, message=message, setup_href=setup, setup_label=setup_label, retry_href=retry,
        count=count_words(service, group, res.get("total")) if state == "ok" else None,
        items=items, page=page,
        prev_href=href(n=page - 1) if page > 1 and state in ("ok", "empty") else None,
        next_href=href(n=page + 1) if has_next else None,
        view=view, view_label=dict(LIBRARY_VIEWS)[view],
        views=tuple((k, name, href(v=k, n=page), k == view) for k, name in LIBRARY_VIEWS if k in LIBRARY_LIST_CLASS),
        list_class=LIBRARY_LIST_CLASS[view], asks=tuple(asks), asks_heading=asks_heading_of(asks))
