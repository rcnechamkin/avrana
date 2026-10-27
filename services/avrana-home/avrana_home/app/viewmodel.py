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
import re
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import quote

from ..contract import (HANDOFF_BASE, MAX_SUMMARY, MIN_QUERY, REQUIRED_GROUP, Service, clean_query,
                        valid_upstream_id)
from .artwork import src_for

SERVICE_LABEL = {"jellyfin": "Movies and TV", "audiobookshelf": "Audiobooks",
                 "komga": "Comics", "calibre-web": "Books"}
CONTINUE_HEADING = {"jellyfin": "Continue watching", "audiobookshelf": "Continue listening",
                    "komga": "Continue reading", "calibre-web": "Continue reading"}
# Member language for what a thing is (CardVM.kind_label). Never an upstream product name.
KIND_LABEL = {"movie": "Movie", "episode": "Episode", "series": "Series", "audiobook": "Audiobook",
              "comic": "Comic", "ebook": "Book"}
_VERB = {"movie": "watched", "episode": "watched", "series": "watched", "audiobook": "listened",
         "comic": "read", "ebook": "read"}
_HANDOFF_PREFIX = "https://"
# A Home card's hand-off is rendered only when it starts with one of the contract's FIXED hosts followed by
# "/", so the host can never be anything else (str.startswith takes the tuple). An upstream-supplied URL never
# gets here (contract.build_handoff_url); this is the second, independent check at the point of rendering.
HANDOFF_ALLOWED = tuple(base + "/" for base in HANDOFF_BASE.values())
# Longest position or duration believed (1,000 hours). Anything larger is treated as unknown, never shown.
MAX_PLAUSIBLE_SECONDS = 1000 * 3600


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
    pos, dur, pct = _seconds(progress.get("position_seconds")), _seconds(progress.get("duration_seconds")), \
        progress.get("percent")
    if pos is not None and dur is not None and dur > 0:
        left = dur - pos
        if left <= 0:
            return "finished"
        if left < 60:
            return "less than a minute left"
        return _duration_words(left) + " left"
    if _is_int(pct) and 0 <= pct <= 100:
        if pct == 0:
            return "just started"            # a rounded-down sliver is not "0 percent"
        if pct == 100:
            return "nearly finished"         # finished items never reach Continue (continue_state)
        return f"{pct} percent {_VERB.get(kind, 'done')}"
    if pos is not None and pos > 0:
        return (_duration_words(pos) + " in") if pos >= 60 else "just started"
    return None


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _seconds(v) -> Optional[int]:
    """A whole number of seconds the page may believe, else None (missing, negative, huge, not an int)."""
    return v if _is_int(v) and 0 <= v <= MAX_PLAUSIBLE_SECONDS else None


def continue_state(progress) -> Tuple[bool, bool]:
    """(finished, resumable) for one Continue item, from the contract's progress object only.

    finished: the upstream's own numbers say nothing is left (position at or past the duration, or a
    fraction of 1 with no seconds). Finished items are left out of Continue, never shown as "finished".
    resumable: the upstream gave THIS member a saved position (whole seconds > 0, believable). Only then is
    the action "Resume"; a percent alone, a zero position or no progress at all is "Open". Nothing here
    claims that playback will start: the hand-off opens the upstream app at the item."""
    if not isinstance(progress, dict):
        return False, False
    pos, dur = _seconds(progress.get("position_seconds")), _seconds(progress.get("duration_seconds"))
    frac = progress.get("fraction")
    if pos is not None and dur is not None and dur > 0:
        if pos >= dur:
            return True, False
    elif isinstance(frac, (int, float)) and not isinstance(frac, bool) and frac == frac and frac >= 1:
        return True, False
    return False, pos is not None and pos > 0


@dataclass(frozen=True)
class ItemVM:
    title: str
    href: str
    kind: str
    detail: Optional[str]          # series and subtitle, joined
    progress: Optional[str]
    image: Optional[str] = None    # same-origin /art/... URL, only when the contract gave a valid ref
    creator: Optional[str] = None  # author or creator, display text
    year: Optional[int] = None
    service: str = ""              # which library (contract service value); for the member-language label
    resumable: bool = False        # the upstream gave this member a saved position (continue_state)
    finished: bool = False         # the upstream's numbers say nothing is left: never shown in Continue


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
    if not isinstance(href, str) or not href.startswith(HANDOFF_ALLOWED):
        return None
    # An episode leads with its marker ("S3 E10 · Series"): a one-line clamp then cuts the series, never the
    # episode number. Everything else keeps series first.
    parts = (it.get("subtitle"), it.get("series")) if it.get("kind") == "episode" else (it.get("series"), it.get("subtitle"))
    detail = " · ".join(_plain(x) for x in parts if x) or None
    finished, resumable = continue_state(it.get("progress"))
    service = it.get("service") if it.get("service") in SERVICE_LABEL else ""
    return ItemVM(_plain(it.get("title") or "") or "Untitled", href, str(it.get("kind", "")), detail,
                  progress_words(it.get("kind", ""), it.get("progress")), _image(it.get("artwork")),
                  service=service, resumable=resumable, finished=finished)


def build_sections(view: dict) -> Tuple[SectionVM, ...]:
    out = []
    for raw in view.get("sections", ()):
        service, section, state = raw.get("service"), raw.get("section"), raw.get("state")
        if state in (None, "not_permitted", "empty") or service not in SERVICE_LABEL:
            continue                                   # absence, never a hint
        label = SERVICE_LABEL[service]
        heading = _heading(service, section)
        if state == "ok":
            items = [vm for vm in (_item_vm(it) for it in raw.get("items", ()))
                     if vm is not None and not (section == "continue" and vm.finished)]
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
# The account disclosure links only to pages that exist in this shell. Help is not repeated here: it is the last
# place in the places bar on every shell page.
ACCOUNT_MENU = (("Account and security", "/account"),)


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
    # Shared contract for the Home 2.0 sprint (card markup and Continue semantics are built on these):
    kind_label: Optional[str] = None   # "Movie", "Episode", "Audiobook", ... in member language
    action: str = "Open"               # the one visible verb: "Resume" only for a trustworthy saved position
    action_label: Optional[str] = None # accessible name for the action when the verb alone is ambiguous


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
    all_down: bool = False               # nothing answers: a calm page, not an error (no per-library lines)
    all_unset: bool = False              # every library is not set up yet: one block with the next step
    setup_href: Optional[str] = None     # "What to do": a library is not set up for this member


@dataclass(frozen=True)
class ShellVM:
    """What the masthead needs on every shell page (Home, Search, Account, Help, help topics), so the places
    bar, Search, Help and the account menu are the same everywhere."""
    member_name: str
    initial: str
    places: Tuple[PlaceVM, ...]
    can_search: bool                      # only a member with a searchable library is offered Search
    current: str                          # home | search | account | help | help-topic


@dataclass(frozen=True)
class AccessVM:
    """Account's "Your access" on shell pages, in Home's member language, each name once."""
    libraries: Tuple[str, ...]
    requests: Tuple[str, ...]
    other: Tuple[object, ...]        # catalogue text (Trusted) for the remaining services, or member language


# The catalogue's direct library routes, named as Home names them (never the portal's "Watch" or "Movies &amp; TV").
ACCOUNT_LIBRARY = {"watch": "jellyfin", "listen": "audiobookshelf", "comics": "komga", "books": "calibre-web"}
ACCOUNT_OTHER = {"kindle": "Send to Kindle"}
# The interstitial's advice in the shell's member language. The app is still named: it is what the member installs,
# and the help topic's steps name it too. Sections off keeps the portal's own sentence (parity).
INTERSTITIAL_SHELL = {"watch": "For the most stable playback, use the Jellyfin app on your device. "
                               "Help has the steps for each device."}


def account_access(services, groups) -> AccessVM:
    """`services`: (route path, catalogue label) for each catalogue service this member may open (already group
    filtered). A request service is named by the libraries it fills for THIS member (REQUEST_FOR and the library's
    own group), so a books-only member never reads "Audiobooks". Nothing here can add a service."""
    paths = [p for p, _l in services]
    libraries = [SERVICE_LABEL[ACCOUNT_LIBRARY[p]] for p in paths if p in ACCOUNT_LIBRARY]
    requests = []
    for s in SERVICE_ORDER:
        path = REQUEST_FOR[s][0]
        if path in paths and REQUIRED_GROUP[Service(s)] in groups and SERVICE_LABEL[s] not in requests:
            requests.append(SERVICE_LABEL[s])
    fills = {REQUEST_FOR[s][0] for s in SERVICE_ORDER}
    other = [ACCOUNT_OTHER.get(p, label) for p, label in services if p not in ACCOUNT_LIBRARY and p not in fills]
    dedupe = lambda xs: tuple(dict.fromkeys(xs))   # noqa: E731
    return AccessVM(dedupe(libraries), dedupe(requests), dedupe(other))


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


SETUP_HELP = "/help/trouble#not-set-up"
STALE_NOTE = " Anything shown from them may be out of date."


def service_notice(service: str, state: str) -> Optional[str]:
    label = SERVICE_LABEL.get(service)
    if label is None:
        return None
    if state == "unavailable":
        return f"{label} are unavailable right now."
    if state == "not_linked":
        return f"{label} are not set up for your account yet."
    return None


def library_down(secs) -> bool:
    """One rule for "this library is unavailable", shared by the notice and the places bar (HOME-APP.md section 5):
    ANY of its sections said unavailable. During an outage a section may still answer from the cache for up to
    two minutes; the library is still not answering, so the place is struck and the notice says that what is
    shown may be out of date, rather than a notice that contradicts a live-looking place."""
    return any(sec["state"] == "unavailable" for sec in secs)


def build_places(tiles, view: dict) -> Tuple[PlaceVM, ...]:
    """The member's own places, in the catalogue's order. A place whose libraries are all down (`library_down`)
    stays, marked not up (Read stays up while one of its two libraries answers); a library the member cannot use
    is not in `tiles`, so it is absent."""
    held = _sections_by_service(view)
    out = []
    for path, label, _desc in tiles:
        services = [s for s in _PLACE_SERVICES.get(path, ()) if s in held]
        down = bool(services) and all(library_down(held[s]) for s in services)
        out.append(PlaceVM("/" + path, label, not down))
    return tuple(out)


def _round_robin(lists, limit: int):
    out, i = [], 0
    while len(out) < limit and any(i < len(x) for x in lists):
        out.extend(x[i] for x in lists if i < len(x))
        i += 1
    return out[:limit]


def action_of(it: ItemVM, in_continue: bool) -> Tuple[str, str]:
    """(verb, accessible text for the verb) for a card's one action. "Resume" only in Continue and only for a
    saved position the upstream gave this member; everything else is "Open".

    The card is one link whose name is read in order: title, secondary line, progress, then this text in place
    of the visible verb (Lane A's `card` macro). So it is short and verb-first and does not repeat the title or
    the progress already read; it adds where the item opens, in member language ("Movies and TV", never an
    upstream product). It never claims that playback starts: the library opens at the item."""
    verb = "Resume" if (in_continue and it.resumable) else "Open"
    library = SERVICE_LABEL.get(it.service)
    return verb, (f"{verb} in {library}" if library else verb)


def _cards(items, line_of, progress: bool = False) -> Tuple[CardVM, ...]:
    out = []
    for it in items:
        verb, name = action_of(it, progress)
        out.append(CardVM(it.title, it.href, SHAPE.get(it.kind, "poster"), line_of(it), it.image,
                          it.progress if progress else None, kind_label=KIND_LABEL.get(it.kind),
                          action=verb, action_label=name))
    return tuple(out)


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

    notices, retry, unset = [], False, False
    for service in SERVICE_ORDER:
        secs = held.get(service, ())
        if library_down(secs):
            stale = any(sec["state"] == "ok" for sec in secs)
            notices.append(service_notice(service, "unavailable") + (STALE_NOTE if stale else ""))
            retry = True
        elif any(sec["state"] == "not_linked" for sec in secs):
            notices.append(service_notice(service, "not_linked"))
            unset = True
    retry_href = ("/" + (f"?new={new_tab}" if new_tab in SERVICE_LABEL else "")) if retry else None
    setup_href = SETUP_HELP if unset else None
    all_secs = [sec for secs in held.values() for sec in secs]
    if all_secs and not any(sec["state"] in ("ok", "empty") for sec in all_secs):
        # Nothing answers. Never an error page. Everything down: one calm block with one combined line. Everything
        # not set up: one block with the next step. A mix: the lines, Try again and the next step.
        all_down = all(sec["state"] == "unavailable" for sec in all_secs)
        all_unset = all(sec["state"] == "not_linked" for sec in all_secs)
        if all_down:     # one combined line inside the calm block, never a line per library
            down = [SERVICE_LABEL[s] for s in SERVICE_ORDER if s in held]
            notices = [f"{down[0]} are unavailable right now." if len(down) == 1
                       else "None of your libraries is answering right now."]
        return HomeVM(**base, no_library=False, notices=tuple(notices), show_continue=False,
                      continue_items=(), continue_said=None, show_new=False, new_tabs=(),
                      new_items=(), new_said=None, retry_href=retry_href,
                      all_down=all_down, all_unset=all_unset, setup_href=setup_href)

    def items_of(section: str, service: str):
        out = []
        for sec in held.get(service, ()):
            if sec["section"] == section and sec["state"] == "ok":
                out.extend(vm for vm in (_item_vm(it) for it in sec.get("items", ()))
                           if vm is not None and not (section == "continue" and vm.finished))
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
                  retry_href=retry_href, setup_href=setup_href)


# ---- search page (AVR-383) --------------------------------------------------------------------------------
SEARCH_MAX_SHOWN = 100          # characters of the typed term put back in the box
# Plain guidance only. Its one promise, the minimum length, is contract.MIN_QUERY. The wildcard and escape
# characters clean_query turns into spaces are not listed to members: a test checks that none of them makes a
# term unusable while letters remain, so there is nothing a member has to avoid.
SEARCH_HINT = f"At least {MIN_QUERY} characters."
SEARCH_IDLE_HINT = "Searches the libraries on your account. " + SEARCH_HINT
SEARCH_MIN_HINT = SEARCH_HINT


# ---- results and title pages (AVR-383/384) ----------------------------------------------------------------
MEDIUM = {"movie": "Movie", "episode": "Episode", "series": "Series", "audiobook": "Audiobook",
          "comic": "Comic", "ebook": "Book"}
ACTION = {"movie": "Watch", "episode": "Watch", "series": "Watch", "audiobook": "Listen", "comic": "Read",
          "ebook": "Read"}
# Which request service (a catalogue route path) fills which library, and the noun a member reads for it. The
# catalogue gates each request service on the same group as the library it fills (portal.py SERVICES).
REQUEST_FOR = {"jellyfin": ("requests", "a film or show"), "audiobookshelf": ("requestabook", "an audiobook"),
               "calibre-web": ("requestabook", "a book"), "komga": ("requestacomic", "a comic")}
# Request services with a DOCUMENTED search address that takes the term (Seerr/Jellyseerr web route
# `/search?query=`, UNVERIFIED live). Every other request service gets its home through our own route.
REQUEST_SEARCH = {"requests": "/search?query="}
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")
TITLE_PREFIX = "/title/"


def handoff_ok(href, service: str) -> bool:
    """A hand-off link only on THAT service's own fixed host (contract.HANDOFF_BASE), never any other https URL."""
    try:
        base = HANDOFF_BASE[Service(service)]
    except (ValueError, KeyError):
        return False
    return isinstance(href, str) and href.startswith(base + "/")


def _year_of(value) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and 1000 <= value <= 2200 else None


def _detail_of(it: dict, creator: Optional[str], year: Optional[int]) -> Optional[str]:
    """Series and subtitle, without repeating the creator or the year (adapters put either in `subtitle` too)."""
    seen = {x for x in (creator, str(year) if year else None) if x}
    parts = [_plain(x) for x in (it.get("series"), it.get("subtitle")) if x]
    return " · ".join(p for p in parts if p and p not in seen) or None


def split_item_id(item_id) -> Optional[Tuple[str, str]]:
    """("jellyfin", "<upstream id>") from a contract item id, only when both parts are valid; else None."""
    if not isinstance(item_id, str) or ":" not in item_id:
        return None
    service, upstream = item_id.split(":", 1)
    try:
        svc = Service(service)
    except ValueError:
        return None
    return (service, upstream) if valid_upstream_id(svc, upstream) else None


def title_href(service: str, upstream_id: str, term: Optional[str] = None) -> str:
    """The title page of one item. Only validated parts go in; the search term (already `clean_query`ed) is the
    one thing carried, percent-encoded, so Back to search can return to the same search."""
    href = f"{TITLE_PREFIX}{service}/{upstream_id}"
    return href + ("?q=" + quote(term, safe="") if term else "")


def search_href(term: Optional[str]) -> str:
    return "/search" + ("?q=" + quote(term, safe="") if term else "")


@dataclass(frozen=True)
class ResultVM:
    title: str
    href: str                    # the ONE action: the title page, or (no title page) the upstream hand-off
    medium: str                  # Movie, Series, Episode, Audiobook, Book, Comic
    line: Optional[str]          # medium · creator · year · series/episode, for the eye
    shape: str
    image: Optional[str]
    opens: Optional[str] = None  # library name when the link leaves Avrana (no title page for that library)


@dataclass(frozen=True)
class SearchGroupVM:
    service: str
    label: str
    state: str                    # ok | empty | unavailable | not_linked
    items: Tuple[ResultVM, ...] = ()
    message: Optional[str] = None
    retry: bool = False           # "Try again" re-runs this same search


@dataclass(frozen=True)
class RequestVM:
    href: str
    label: str                    # "Ask for a film or show"
    leaves: bool                  # True: the link goes to the request website with the term (the page says so)


@dataclass(frozen=True)
class SearchVM:
    mode: str                     # no_library | idle | invalid | results
    term: str = ""                # bounded, printable; the template autoescapes it
    message: Optional[str] = None
    hint: Optional[str] = SEARCH_HINT
    groups: Tuple[SearchGroupVM, ...] = ()
    found: int = 0
    outcome: Optional[str] = None  # the results heading: "3 results" / "No results" / "Not searched"; never the term
    can_search: bool = True
    # found | none (every library answered, nothing matched) | partial_none (some answered, none matched, some
    # could not answer) | unsearchable (no library could answer: never "no matches") | not_set_up
    result_state: Optional[str] = None
    retry_href: Optional[str] = None
    requests: Tuple[RequestVM, ...] = ()


def _result_vm(it: dict, service: str, label: str, term: Optional[str], title_services) -> Optional[ResultVM]:
    handoff = it.get("handoff_url")
    if not handoff_ok(handoff, service):
        return None
    kind = str(it.get("kind", ""))
    title = _plain(it.get("title") or "") or "Untitled"
    creator = _plain(it.get("creator") or "") or None
    year = _year_of(it.get("year"))
    medium = MEDIUM.get(kind, "")
    line = " · ".join(x for x in (medium, creator, str(year) if year else None,
                                    _detail_of(it, creator, year)) if x) or None
    parts = split_item_id(it.get("id"))
    if parts is not None and parts[0] == service and service in title_services:
        href, opens = title_href(parts[0], parts[1], term), None
    else:
        href, opens = handoff, label
    return ResultVM(title, href, medium, line, SHAPE.get(kind, "poster"), _image(it.get("artwork")), opens)


def request_options(empty_services, term: Optional[str], request_hosts) -> Tuple[RequestVM, ...]:
    """"Request this title" for each library that answered with no match, ONLY where the member's catalogue holds
    the request service that fills it (`request_hosts`: request path -> host, already group-filtered by the
    caller). Seerr gets the term through its documented search address (allowlisted host, percent-encoded); the
    others get their own home through our route. Nothing is ever submitted."""
    by_href: dict = {}
    for service in empty_services:
        path, noun = REQUEST_FOR.get(service, (None, None))
        host = (request_hosts or {}).get(path)
        if not path or not isinstance(host, str) or not _HOST.fullmatch(host):
            continue
        if path in REQUEST_SEARCH and term:
            href, leaves = f"https://{host}{REQUEST_SEARCH[path]}{quote(term, safe='')}", True
        else:
            href, leaves = "/" + path, False
        nouns = by_href.setdefault(href, (leaves, []))[1]
        if noun not in nouns:
            nouns.append(noun)
    return tuple(RequestVM(href, "Ask for " + " or ".join(nouns), leaves)
                 for href, (leaves, nouns) in by_href.items())


def _names(labels) -> str:
    labels = list(labels)
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


def build_search(view: dict, raw_term: Optional[str], *, title_services=frozenset(),
                 request_hosts=None) -> SearchVM:
    """`view` is `SearchResults.search_view()`; `raw_term` the bounded text from the address (or None).
    Libraries the member cannot use are not in `view`, and nothing here can name them.

    `title_services`: libraries whose results link to a title page (the adapter offers a permission-checked item
    lookup); every other result links straight to its library. `request_hosts`: the request services this member's
    catalogue holds (path -> host), for the empty-results fallback. Unavailable is never reported as empty."""
    term = _plain(raw_term or "", SEARCH_MAX_SHOWN)
    if not view.get("entitled") or (view.get("status") == "ok" and not view.get("groups") and raw_term is not None):
        return SearchVM("no_library", message="Search is not available on your account yet.")
    if raw_term is None:
        return SearchVM("idle", hint=SEARCH_IDLE_HINT)
    if view.get("status") != "ok":
        return SearchVM("invalid", term=term, message="That search term cannot be used.", hint=SEARCH_MIN_HINT)
    clean = clean_query(raw_term)
    groups, found, empty = [], 0, []
    for raw in view.get("groups", ()):
        service, state = raw.get("service"), raw.get("state")
        if service not in SERVICE_LABEL or state in (None, "not_permitted"):
            continue
        label = SERVICE_LABEL[service]
        if state == "ok":
            items = [vm for vm in (_result_vm(it, service, label, clean, title_services)
                                   for it in raw.get("items", ())) if vm is not None]
            state = "ok" if items else "empty"
            if items:
                found += len(items)
                groups.append(SearchGroupVM(service, label, "ok", tuple(items)))
        if state == "empty":
            empty.append(service)
            groups.append(SearchGroupVM(service, label, "empty", message=f"No matches in {label}."))
        elif state == "unavailable":
            groups.append(SearchGroupVM(service, label, "unavailable",
                                        message=f"The {label} library could not be searched right now.", retry=True))
        elif state == "not_linked":
            groups.append(SearchGroupVM(service, label, "not_linked",
                                        message=f"The {label} library is not set up for your account yet."))
    down = [g.label for g in groups if g.state == "unavailable"]
    retry = search_href(clean) if down else None
    base = dict(term=term, groups=tuple(groups), retry_href=retry)
    if found:
        return SearchVM("results", message=f"{found} found.", found=found, result_state="found",
                        outcome=f"{found} result" + ("" if found == 1 else "s"), **base)
    if not empty:
        # Nobody answered. Unavailable is not empty: never "no matches", never a request offer.
        if down:
            unlinked = [g.label for g in groups if g.state == "not_linked"]
            if len(groups) == 1:
                msg = f"The {down[0]} library could not be searched right now."
            elif unlinked:
                msg = (f"{_names(down)} could not be searched right now, and {_names(unlinked)} "
                       f"{'is' if len(unlinked) == 1 else 'are'} not set up for your account yet.")
            else:
                msg = "Your libraries could not be searched right now."
            return SearchVM("results", message=msg + " This usually passes within a minute.",
                            result_state="unsearchable", outcome="Not searched", **base)
        return SearchVM("results", message="Search is not set up for your account yet.",
                        result_state="not_set_up", outcome="Not searched", **base)
    reqs = request_options(empty, clean, request_hosts)
    if down:
        msg = (f"No matches in {_names(SERVICE_LABEL[s] for s in empty)}. "
               f"{_names(down)} could not be searched right now, so it may still be there.")
        return SearchVM("results", message=msg, result_state="partial_none", outcome="No results", requests=reqs,
                        **base)
    return SearchVM("results", message="Nothing found. Check the spelling or try fewer words.",
                    result_state="none", outcome="No results", requests=reqs, **base)


@dataclass(frozen=True)
class TitleVM:
    state: str                         # ok | unavailable | not_linked
    library: str
    title: str = ""
    medium: str = ""
    line: Optional[str] = None         # creator · year
    detail: Optional[str] = None       # series · episode
    shape: str = "poster"
    image: Optional[str] = None
    kicker: str = ""                   # "Episode · Movies and TV"; the medium only when the library name lacks it
    progress: Optional[str] = None     # in words, whenever the upstream gave this member progress (not finished)
    summary: Optional[str] = None      # synopsis, plain text from the adapter (R2-C); the template autoescapes it
    action: Optional[str] = None       # Resume | Open | Watch | Listen | Read: opens the item, never "playing"
    action_href: Optional[str] = None
    action_label: Optional[str] = None
    back_href: Optional[str] = None    # Back to search: only from a valid search term
    retry_href: Optional[str] = None
    message: Optional[str] = None


def kicker_of(medium: str, library: str) -> str:
    """"Episode · Movies and TV", but only "Movies and TV" for a movie: the medium is left out when the library's
    own name already says it (Movie/Movies, Audiobook/Audiobooks, Book/Books, Comic/Comics)."""
    if not medium or (medium.lower() + "s") in library.lower().split():
        return library
    return f"{medium} · {library}"


def build_title(section: dict, service: str, upstream_id: str, raw_term: Optional[str]) -> Optional[TitleVM]:
    """`section` is the adapter's `item(...)` result as `SectionResult.to_dict()`. None means the standard 404
    (not permitted, unknown, hidden, malformed, or anything this function does not recognise): the caller cannot
    tell those apart and neither can the member. Unavailable and not-set-up say nothing about the title."""
    label = SERVICE_LABEL.get(service)
    state = section.get("state") if isinstance(section, dict) else None
    if label is None or state in (None, "not_permitted", "empty"):
        return None
    term = clean_query(raw_term) if raw_term is not None else None
    back = search_href(term) if term else None
    if state == "unavailable":
        return TitleVM("unavailable", label, back_href=back, retry_href=title_href(service, upstream_id, term),
                       message=f"The {label} library is unavailable right now. This usually passes within a minute.")
    if state == "not_linked":
        return TitleVM("not_linked", label, back_href=back,
                       message=f"The {label} library is not set up for your account yet.")
    if state != "ok":
        return None
    want = f"{service}:{upstream_id}"
    it = next((x for x in section.get("items", ()) if isinstance(x, dict) and x.get("id") == want), None)
    if it is None:
        return None
    href = it.get("handoff_url")
    if not handoff_ok(href, service):
        return None
    kind = str(it.get("kind", ""))
    title = _plain(it.get("title") or "") or "Untitled"
    creator = _plain(it.get("creator") or "") or None
    year = _year_of(it.get("year"))
    medium = MEDIUM.get(kind, "")
    # The same rule as a Continue card (continue_state): Resume only for a saved position in whole seconds.
    # Progress the upstream reports without one (a fraction, no position) shows in words with the neutral
    # "Open", exactly as Continue shows it; with no progress at all the verb says what the item is for.
    finished, resume = continue_state(it.get("progress"))
    progress = None if finished else progress_words(kind, it.get("progress"))
    if resume:
        action = "Resume"
    elif progress:
        action = "Open"
    else:
        action = ACTION.get(kind, "Open")
    return TitleVM("ok", label, title=title, medium=medium, kicker=kicker_of(medium, label),
                   line=" · ".join(x for x in (creator, str(year) if year else None) if x) or None,
                   detail=_detail_of(it, creator, year), shape=SHAPE.get(kind, "poster"),
                   image=_image(it.get("artwork")), progress=progress,
                   summary=_plain(it.get("summary") or "", MAX_SUMMARY + 1) or None, action=action, action_href=href,
                   action_label=f"{action} {title} in {label}", back_href=back)
