"""Section view-model for the optional home sections. Pure functions, standard library only.

Input is `HomeSections.member_view()` (the documented JSON contract), so the HTML and the JSON
view can never disagree. Output is plain data for a deliberately plain template: the design team
replaces the template, not this logic.

State rules (docs/design/HOME-APP.md):
  ok            -> the list
  empty         -> nothing at all (the least presumptuous choice; see the owner decision there)
  unavailable   -> one neutral sentence naming only a library the member may use
  not_linked    -> one neutral "not set up yet" sentence
  not_permitted -> never present: `member_view()` omits it, and this module refuses it too
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from .artwork import src_for

SERVICE_LABEL = {"jellyfin": "Movies and TV", "audiobookshelf": "Audiobooks",
                 "komga": "Comics", "calibre-web": "Books"}
CONTINUE_HEADING = {"jellyfin": "Continue watching", "audiobookshelf": "Continue listening",
                    "komga": "Continue reading", "calibre-web": "Continue reading"}
KIND_LABEL = {"movie": "Movie", "episode": "Episode", "series": "Series", "audiobook": "Audiobook",
              "comic": "Comic", "ebook": "Ebook"}
_VERB = {"movie": "watched", "episode": "watched", "series": "watched", "audiobook": "listened",
         "comic": "read", "ebook": "read"}
_HANDOFF_PREFIX = "https://"


def _duration_words(seconds: int) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    hours, rest = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("" if hours == 1 else "s"))
    if rest:
        parts.append(f"{rest} minute" + ("" if rest == 1 else "s"))
    return " ".join(parts)


def progress_words(kind: str, progress: Optional[dict]) -> Optional[str]:
    """Progress as words, never a bare bar or number. None when the upstream did not say."""
    if not isinstance(progress, dict):
        return None
    pos, dur, pct = (progress.get("position_seconds"), progress.get("duration_seconds"),
                     progress.get("percent"))
    ints = lambda v: isinstance(v, int) and not isinstance(v, bool)   # noqa: E731
    if ints(pos) and ints(dur) and dur > 0 and pos >= 0:
        left = dur - pos
        if left <= 0:
            return "finished"
        if left < 60:
            return "less than a minute left"
        return _duration_words(left) + " left"
    if ints(pct) and 0 <= pct <= 100:
        return f"{pct} percent {_VERB.get(kind, 'done')}"
    if ints(pos) and pos > 0:
        return (_duration_words(pos) + " in") if pos >= 60 else "just started"
    return None


@dataclass(frozen=True)
class ItemVM:
    title: str
    href: str
    kind: str
    detail: Optional[str]          # series and subtitle, joined
    progress: Optional[str]
    image: Optional[str] = None    # same-origin /art/... URL, only when the contract gave a valid ref


@dataclass(frozen=True)
class SectionVM:
    service: str
    section: str
    heading: str
    state: str
    items: Tuple[ItemVM, ...] = ()
    message: Optional[str] = None


def _plain(value, limit: int = 200) -> str:
    """Display text from an upstream: printable characters only (no bidi overrides or other
    format/control characters), bounded. HTML escaping is the template's job."""
    return "".join(c for c in str(value) if c.isprintable())[:limit].strip()


def _image(artwork) -> Optional[str]:
    return src_for(artwork.get("ref")) if isinstance(artwork, dict) else None


def _heading(service: str, section: str) -> str:
    label = SERVICE_LABEL.get(service, "Library")
    if section == "continue":
        return CONTINUE_HEADING.get(service, "Continue")
    return f"Recently added to {label}"


def _item_vm(it: dict) -> Optional[ItemVM]:
    """One contract item as display data, or None when it has no https hand-off (never rendered)."""
    href = it.get("handoff_url")
    if not isinstance(href, str) or not href.startswith(_HANDOFF_PREFIX):
        return None
    detail = " · ".join(_plain(x) for x in (it.get("series"), it.get("subtitle")) if x) or None
    return ItemVM(_plain(it.get("title") or "") or "Untitled", href, str(it.get("kind", "")), detail,
                  progress_words(it.get("kind", ""), it.get("progress")), _image(it.get("artwork")))


def build_sections(view: dict) -> Tuple[SectionVM, ...]:
    out = []
    for raw in view.get("sections", ()):
        service, section, state = raw.get("service"), raw.get("section"), raw.get("state")
        if state in (None, "not_permitted", "empty") or service not in SERVICE_LABEL:
            continue                                   # absence, never a hint
        label = SERVICE_LABEL[service]
        heading = _heading(service, section)
        if state == "ok":
            items = [vm for vm in (_item_vm(it) for it in raw.get("items", ())) if vm is not None]
            if items:
                out.append(SectionVM(service, section, heading, "ok", tuple(items)))
        elif state == "unavailable":
            out.append(SectionVM(service, section, heading, state,
                                 message=f"{label} are unavailable right now."))
        elif state == "not_linked":
            out.append(SectionVM(service, section, heading, state,
                                 message=f"{label} are not set up for your account yet."))
    return tuple(out)


# ---- The Home page (AVR-374/452/478): places, Continue, New this week ---------------------------------
# Pure functions over `member_view()` plus the catalogue's tile list. Nothing here calls an adapter.
RAIL_MOST = 4                       # a rail is one bounded row, never more than four things
NEW_ALL = "all"
SERVICE_ORDER = ("jellyfin", "audiobookshelf", "komga", "calibre-web")
# Which tile (route path) is backed by which service(s); a tile not listed is not a library.
_PLACE_SERVICES = {"watch": ("jellyfin",), "listen": ("audiobookshelf",), "comics": ("komga",),
                   "books": ("calibre-web",), "read": ("komga", "calibre-web")}
SHAPE = {"movie": "poster", "series": "poster", "episode": "still", "audiobook": "square",
         "comic": "comic", "ebook": "book"}
NOTHING_IN_PROGRESS = ("Nothing in progress. Whatever you start in a library appears here, "
                       "ready to pick up where you stopped.")
NOTHING_NEW = "Nothing new this week."
NO_LIBRARY = "No library is shared with this account yet. Ask the person who invited you, or read Help."
# The account disclosure links only to pages that exist in this shell.
ACCOUNT_MENU = (("Account", "/account"), ("Help", "/help"))


@dataclass(frozen=True)
class PlaceVM:
    href: str
    label: object          # catalogue text (Trusted): the template renders it with |trusted
    up: bool               # False: kept in place, struck through, ", unavailable" for screen readers


@dataclass(frozen=True)
class CardVM:
    title: str
    href: str
    shape: str
    line: Optional[str]            # the secondary line: series, episode or library, never progress
    image: Optional[str]
    progress: Optional[str] = None  # progress in words ("1 hour left"), its own line


@dataclass(frozen=True)
class HomeVM:
    member_name: str
    initial: str
    places: Tuple[PlaceVM, ...]
    no_library: bool
    notices: Tuple[str, ...]
    show_continue: bool
    continue_items: Tuple[CardVM, ...]
    continue_said: Optional[str]
    show_new: bool
    new_tabs: Tuple[Tuple[str, str, bool], ...]      # (key, label, current)
    new_items: Tuple[CardVM, ...]
    new_said: Optional[str]
    retry_href: Optional[str] = None     # "Try again": the same page, when a library said unavailable
    all_down: bool = False               # nothing answers: a calm page, not an error


@dataclass(frozen=True)
class ShellVM:
    """What the masthead needs on every shell page (Home, Search, Account, Help, help topics), so the places
    bar, Search, Help and the account menu are the same everywhere."""
    member_name: str
    initial: str
    places: Tuple[PlaceVM, ...]
    can_search: bool                      # only a member with a searchable library is offered Search
    current: str                          # home | search | account | help | help-topic


def has_library(tiles) -> bool:
    return any(path in _PLACE_SERVICES for path, _l, _d in tiles)


def build_shell(tiles, current: str, member_name: str = "", places: Optional[Tuple[PlaceVM, ...]] = None) -> ShellVM:
    name = _plain(member_name) or "Member"
    if places is None:       # pages that call no upstream cannot know a library is down: all stay up
        places = build_places(tiles, {"sections": []})
    return ShellVM(name, initial_of(name), places, has_library(tiles), current)


def initial_of(name: str) -> str:
    for c in _plain(name or ""):
        if c.isalnum():
            return c.upper()
    return "A"


def _sections_by_service(view: dict) -> dict:
    out: dict = {}
    for raw in view.get("sections", ()):
        if raw.get("service") in SERVICE_LABEL and raw.get("state") not in (None, "not_permitted"):
            out.setdefault(raw["service"], []).append(raw)
    return out


def service_notice(service: str, state: str) -> Optional[str]:
    label = SERVICE_LABEL.get(service)
    if label is None:
        return None
    if state == "unavailable":
        return f"{label} are unavailable right now."
    if state == "not_linked":
        return f"{label} are not set up for your account yet."
    return None


def build_places(tiles, view: dict) -> Tuple[PlaceVM, ...]:
    """The member's own places, in the catalogue's order. A library whose sections are all unavailable
    stays, marked not up; a library the member cannot use is not in `tiles`, so it is absent."""
    held = _sections_by_service(view)
    out = []
    for path, label, _desc in tiles:
        services = [s for s in _PLACE_SERVICES.get(path, ()) if s in held]
        down = bool(services) and all(sec["state"] == "unavailable" for s in services for sec in held[s])
        out.append(PlaceVM("/" + path, label, not down))
    return tuple(out)


def _round_robin(lists, limit: int):
    out, i = [], 0
    while len(out) < limit and any(i < len(x) for x in lists):
        out.extend(x[i] for x in lists if i < len(x))
        i += 1
    return out[:limit]


def _cards(items, line_of, progress: bool = False) -> Tuple[CardVM, ...]:
    return tuple(CardVM(it.title, it.href, SHAPE.get(it.kind, "poster"), line_of(it), it.image,
                        it.progress if progress else None) for it in items)


def build_home(view: dict, tiles, *, new_tab: Optional[str] = None, limit: int = RAIL_MOST,
               member_name: str = "") -> HomeVM:
    """Home as display data. Retry links point at `/` (the new tab is kept), the same page again."""
    limit = max(1, min(int(limit), RAIL_MOST))
    held = _sections_by_service(view)
    places = build_places(tiles, view)
    has_lib = has_library(tiles)
    name = _plain(member_name) or "Member"
    base = dict(member_name=name, initial=initial_of(name), places=places)
    if not has_lib:
        return HomeVM(**base, no_library=True, notices=(), show_continue=False, continue_items=(),
                      continue_said=None, show_new=False, new_tabs=(), new_items=(), new_said=None)

    notices, seen, retry = [], set(), False
    for service in SERVICE_ORDER:
        for sec in held.get(service, ()):
            msg = service_notice(service, sec["state"])
            if msg and msg not in seen:
                seen.add(msg)
                notices.append(msg)
                retry = retry or any(sec["state"] == "unavailable" for sec in held.get(service, ()))
    retry_href = ("/" + (f"?new={new_tab}" if new_tab in SERVICE_LABEL else "")) if retry else None
    all_secs = [sec for secs in held.values() for sec in secs]
    if all_secs and not any(sec["state"] in ("ok", "empty") for sec in all_secs):
        # Nothing answers: say so once per library and stop. Never an error page.
        return HomeVM(**base, no_library=False, notices=tuple(notices), show_continue=False,
                      continue_items=(), continue_said=None, show_new=False, new_tabs=(),
                      new_items=(), new_said=None, retry_href=retry_href,
                      all_down=all(sec["state"] == "unavailable" for sec in all_secs))

    def items_of(section: str, service: str):
        out = []
        for sec in held.get(service, ()):
            if sec["section"] == section and sec["state"] == "ok":
                out.extend(vm for vm in (_item_vm(it) for it in sec.get("items", ())) if vm is not None)
        return out

    # Continue: one rail merged across services, the most recent of each first.
    cont_services = [s for s in SERVICE_ORDER if any(x["section"] == "continue" for x in held.get(s, ()))]
    cont = _round_robin([items_of("continue", s) for s in cont_services], limit)
    cont_degraded = any(x["state"] in ("unavailable", "not_linked") for s in cont_services
                        for x in held[s] if x["section"] == "continue")
    continue_said = None if (cont or cont_degraded) else NOTHING_IN_PROGRESS

    # New this week: a tab for each library that answers; anything else falls back to All. A member with
    # exactly one library has no use for "All" (it is the same list), so that tab is not offered.
    libs = [(s, SERVICE_LABEL[s]) for s in SERVICE_ORDER
            if any(x["section"] == "recent" and x["state"] in ("ok", "empty") for x in held.get(s, ()))]
    tabs = [(NEW_ALL, "All")] + libs if len(libs) != 1 else list(libs)
    tab = new_tab if isinstance(new_tab, str) and new_tab in {k for k, _ in tabs} else tabs[0][0]
    if tab == NEW_ALL:           # the newest of each library; the second line says which library
        per = [_cards(items_of("recent", s), lambda it, s=s: SERVICE_LABEL[s]) for s in SERVICE_ORDER]
        new = tuple(_round_robin(per, limit))
        new_said = None if (new or notices) else NOTHING_NEW
    else:
        new = _cards(items_of("recent", tab)[:limit], lambda it: it.detail or KIND_LABEL.get(it.kind))
        new_said = None if new else (NOTHING_NEW if len(libs) == 1 else f"Nothing new in {SERVICE_LABEL[tab]} this week.")
    return HomeVM(**base, no_library=False, notices=tuple(notices), show_continue=bool(cont_services),
                  continue_items=_cards(cont, lambda it: it.detail, progress=True),
                  continue_said=continue_said, show_new=True,
                  new_tabs=tuple((k, n, k == tab) for k, n in tabs), new_items=new, new_said=new_said,
                  retry_href=retry_href)


# ---- search page (AVR-383) --------------------------------------------------------------------------------
SEARCH_MAX_SHOWN = 100          # characters of the typed term put back in the box
# What contract.clean_query neutralises into spaces, in the order a member can read it. A test pins this
# list to the contract's own set, so the hint can never promise more or less than the code does.
SEARCH_SPACED = "* % _ ? \\ [ ] { } ( ) | ^ ~ $ \" `"
SEARCH_HINT = f"At least 2 characters. These are treated as spaces: {SEARCH_SPACED}"
SEARCH_IDLE_HINT = "Searches the libraries on your account. " + SEARCH_HINT
SEARCH_MIN_HINT = SEARCH_HINT


@dataclass(frozen=True)
class SearchGroupVM:
    service: str
    label: str
    state: str                    # ok | empty | unavailable | not_linked
    items: Tuple[ItemVM, ...] = ()
    message: Optional[str] = None
    retry: bool = False           # "Try again" re-runs this same search


@dataclass(frozen=True)
class SearchVM:
    mode: str                     # no_library | idle | invalid | results
    term: str = ""                # bounded, printable; the template autoescapes it
    message: Optional[str] = None
    hint: Optional[str] = SEARCH_HINT
    groups: Tuple[SearchGroupVM, ...] = ()
    found: int = 0
    outcome: Optional[str] = None  # the results heading: "3 results" / "No results"; never the term
    can_search: bool = True


def build_search(view: dict, raw_term: Optional[str]) -> SearchVM:
    """`view` is `SearchResults.search_view()`; `raw_term` the bounded text from the address (or None).
    Libraries the member cannot use are not in `view`, and nothing here can name them."""
    term = _plain(raw_term or "", SEARCH_MAX_SHOWN)
    if not view.get("entitled") or (view.get("status") == "ok" and not view.get("groups") and raw_term is not None):
        return SearchVM("no_library", message="Search is not available on your account yet.")
    if raw_term is None:
        return SearchVM("idle", hint=SEARCH_IDLE_HINT)
    if view.get("status") != "ok":
        return SearchVM("invalid", term=term, message="That search term cannot be used.", hint=SEARCH_MIN_HINT)
    groups, found = [], 0
    for raw in view.get("groups", ()):
        service, state = raw.get("service"), raw.get("state")
        if service not in SERVICE_LABEL or state in (None, "not_permitted"):
            continue
        label = SERVICE_LABEL[service]
        if state == "ok":
            items = []
            for it in raw.get("items", ()):
                href = it.get("handoff_url")
                if not isinstance(href, str) or not href.startswith(_HANDOFF_PREFIX):
                    continue
                detail = " · ".join(_plain(x) for x in (it.get("series"), it.get("subtitle")) if x) or None
                items.append(ItemVM(_plain(it.get("title") or "") or "Untitled", href,
                                    KIND_LABEL.get(str(it.get("kind", "")), ""), detail, None,
                                    _image(it.get("artwork"))))
            if items:
                found += len(items)
                groups.append(SearchGroupVM(service, label, "ok", tuple(items)))
            else:
                groups.append(SearchGroupVM(service, label, "empty", message=f"No matches in {label}."))
        elif state == "empty":
            groups.append(SearchGroupVM(service, label, "empty", message=f"No matches in {label}."))
        elif state == "unavailable":
            groups.append(SearchGroupVM(service, label, "unavailable",
                                        message=f"The {label} library is unavailable right now.", retry=True))
        elif state == "not_linked":
            groups.append(SearchGroupVM(service, label, "not_linked",
                                        message=f"The {label} library is not set up for your account yet."))
    if not found:
        down = any(g.state in ("unavailable", "not_linked") for g in groups)
        msg = ("Nothing found in the libraries that could be searched." if down
               else "Nothing found. Check the spelling or try fewer words.")
        return SearchVM("results", term=term, message=msg, groups=tuple(groups), outcome="No results")
    return SearchVM("results", term=term, message=f"{found} found.", groups=tuple(groups), found=found,
                    outcome=f"{found} result" + ("" if found == 1 else "s"))
