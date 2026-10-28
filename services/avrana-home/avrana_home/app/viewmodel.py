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
_MINUTES_KINDS = frozenset({"movie", "episode", "series"})   # time left in total minutes (_duration_words)
_HANDOFF_PREFIX = "https://"
# A Home card's hand-off is rendered only when it starts with one of the contract's FIXED hosts followed by
# "/", so the host can never be anything else (str.startswith takes the tuple). An upstream-supplied URL never
# gets here (contract.build_handoff_url); this is the second, independent check at the point of rendering.
HANDOFF_ALLOWED = tuple(base + "/" for base in HANDOFF_BASE.values())
# Longest position or duration believed (1,000 hours). Anything larger is treated as unknown, never shown.
MAX_PLAUSIBLE_SECONDS = 1000 * 3600


def _duration_words(seconds: int, kind: str = "") -> str:
    minutes = max(1, math.ceil(seconds / 60))
    if kind in _MINUTES_KINDS:
        # Owner review 2026-10-27: a film or an episode reads in total minutes ("70 minutes left"), shorter and the
        # way a player shows it. Long listens and reads keep hours ("7 hours 43 minutes left").
        return f"{minutes} minute" + ("" if minutes == 1 else "s")
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
        return _duration_words(left, kind) + " left"
    if _is_int(pct) and 0 <= pct <= 100:
        if pct == 0:
            return "just started"            # a rounded-down sliver is not "0 percent"
        if pct == 100:
            return "nearly finished"         # finished items never reach Continue (continue_state)
        return f"{pct} percent {_VERB.get(kind, 'done')}"
    if pos is not None and pos > 0:
        return (_duration_words(pos, kind) + " in") if pos >= 60 else "just started"
    return None


def progress_fraction(progress: Optional[dict]) -> Optional[float]:
    """How far along, 0 to 1, for the 3px progress rule beside the words (never instead of them). The same
    believable numbers as `progress_words`: whole seconds first, then a whole percent, then a fraction. None when
    the upstream gave nothing usable, so no rule is drawn rather than a guessed one."""
    if not isinstance(progress, dict):
        return None
    pos, dur = _seconds(progress.get("position_seconds")), _seconds(progress.get("duration_seconds"))
    if pos is not None and dur is not None and dur > 0:
        return min(1.0, pos / dur)
    pct = progress.get("percent")
    if _is_int(pct) and 0 <= pct <= 100:
        return pct / 100
    frac = progress.get("fraction")
    if isinstance(frac, (int, float)) and not isinstance(frac, bool) and math.isfinite(frac) and 0 <= frac <= 1:
        return float(frac)
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
    item_id: Optional[str] = None  # the contract id ("jellyfin:<id>"), for the hero's Details link only
    fraction: Optional[float] = None  # 0 to 1, for the progress rule beside the words (progress_fraction)
    backdrop: Optional[str] = None # same-origin /art/... URL of a wide backdrop, for the hero only
    shelf: Optional[str] = None    # a "shelves" item's shelf (SHELF_ROWS key); never upstream text


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
    item_id = it.get("id") if isinstance(it.get("id"), str) else None
    return ItemVM(_plain(it.get("title") or "") or "Untitled", href, str(it.get("kind", "")), detail,
                  progress_words(it.get("kind", ""), it.get("progress")), _image(it.get("artwork")),
                  service=service, resumable=resumable, finished=finished, item_id=item_id,
                  fraction=progress_fraction(it.get("progress")), backdrop=_image(it.get("backdrop")),
                  shelf=it.get("shelf") if it.get("shelf") in dict(SHELF_ROWS) else None)


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


# ---- The Home page (AVR-374/452/478; Concept K AVR-718): places, the hero, Continue, Recently added ------
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
# "Recently added", never "this week": the upstream lists are not date-bounded (memo section 4, wording fix).
NOTHING_NEW = "Nothing recently added."
NO_LIBRARY = "No library is shared with this account yet. Ask the person who invited you, or read Help."


@dataclass(frozen=True)
class PlaceVM:
    href: str
    label: object          # catalogue text (Trusted): the template renders it with |trusted
    up: bool               # False: kept in place, struck through, ", unavailable" for screen readers


@dataclass(frozen=True)
class FilterVM:
    """One of Home's filters (owner decision 2026-10-27): All, or one library place (Watch, Listen, Read). It narrows
    Home to that place's libraries; the place itself (its own site) stays one tap away on the filtered Home."""
    key: str               # "all" or the catalogue place path ("watch"); never anything from the address
    label: object          # "All", or the catalogue text (Trusted): the template renders it with |trusted
    href: str              # "/" or "/?for=<place>"
    current: bool
    up: bool = True        # False: the place's libraries are all down (struck, ", unavailable" for screen readers)


@dataclass(frozen=True)
class RowVM:
    """A titled rail of cards on a filtered Home (Watch: Up next, Movies, TV shows)."""
    key: str               # the heading id suffix: "next", "movies", "shows"
    heading: str
    items: Tuple["CardVM", ...]
    said: Optional[str] = None
    tall: bool = True      # posters (a tall rail), or False for episode stills


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
    bar: Optional[int] = None          # Continue only: the progress rule's length in 5% steps (0 to 100), beside
                                       # the words, never instead of them; None draws no rule


# The hero's one hand-off (memo sections 4 and 6). It names the app that opens, because that is where the member
# lands (an installed Home opens it in a separate view), and it never claims playback: "Resume" only for a saved
# position this member has in Movies and TV; the other libraries say what the member does there.
HERO_APP = {"jellyfin": "Jellyfin", "audiobookshelf": "Audiobookshelf", "komga": "Komga", "calibre-web": "Calibre-Web"}
HERO_VERB = {"jellyfin": "Open", "audiobookshelf": "Listen", "komga": "Read", "calibre-web": "Open"}


@dataclass(frozen=True)
class HeroVM:
    """Home's hero (Concept K, AVR-718): the member's own next thing. `state` is "continue" (the first Continue item,
    eyebrow in the Media yellow: it is the member's own state) or "recent" (nothing in progress: the first Recently
    added item, eyebrow in Stone: a list is not the member's state). Built only from this member's sections."""
    state: str
    title: str
    shape: str
    image: Optional[str]               # same-origin /art/... only (the gateway re-checks it per member)
    meta: Optional[str]                # "1 hour 10 minutes left · Movies and TV"
    action: str                        # "Resume in Jellyfin": visible text of the one primary hand-off
    action_href: str                   # the item's https hand-off on its library's fixed host
    details_href: Optional[str] = None  # the title page, only for a library that has one (permission-checked)
    backdrop: Optional[str] = None     # a wide 16:9 /art/... backdrop; when present the hero leads with it


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
    hero: Optional[HeroVM] = None        # Concept K hero (AVR-718); None on every state with nothing of the member's
    filters: Tuple[FilterVM, ...] = ()   # All, Watch, Listen, Read: only when the member has two places or more
    focus: Optional[str] = None          # the chosen place ("watch"), None for All
    rows: Tuple[RowVM, ...] = ()         # Watch: Up next, Movies, TV shows (in place of Recently added)
    focus_open: Optional[Tuple[object, str]] = None   # (place label, "/watch"): the chosen place's own site


@dataclass(frozen=True)
class ShellVM:
    """What the shell needs on every shell page (Home, Search, Account, Help, help topics, places, titles): the
    places bar on Home, and the tab bar (Home, Library, Search, Me) everywhere."""
    member_name: str
    initial: str
    places: Tuple[PlaceVM, ...]
    can_search: bool                      # only a member with a library is offered Library and Search
    current: str                          # home | library | search | me | account | help | help-topic | place | title
    notice: Optional[object] = None       # the operator notice this member sees (notice.ActiveNotice), AVR-365
    filters: Tuple["FilterVM", ...] = ()  # Home only: the filters that take the places bar's row (HomeVM.filters)


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


# ---- The Me hub (Concept K, AVR-719) -----------------------------------------------------------------------
# Catalogue places the Me hub and the Request page may link to, each only when it is in THIS member's own tiles
# (the catalogue's group gate, the same one the place's route uses: a member without it gets the standard 404).
OPERATIONS_PATH = "ops"
CONTRIBUTE_PATH = "contribute"


@dataclass(frozen=True)
class PlaceLinkVM:
    href: str              # our own route ("/ops", "/contribute"), which hands off to the place's fixed host
    label: object          # catalogue text (Trusted): the template renders it with |trusted
    desc: object


def place_link(tiles, path: str) -> Optional[PlaceLinkVM]:
    """The member's own tile for `path`, or None. `tiles` is the catalogue's group-filtered list (decide("/")), so
    nothing here can offer a place the member cannot open."""
    return next((PlaceLinkVM("/" + p, label, desc) for p, label, desc in tiles if p == path), None)


@dataclass(frozen=True)
class MeVM:
    """The Me hub: who is signed in and the member's own way to Account, Help and (admins) Operations. From the
    verified principal and the member's catalogue tiles only; nothing here calls an adapter."""
    username: str                       # "Signed in as <username>"
    operations: Optional[PlaceLinkVM]   # only when the catalogue's Operations gate admits this member
    signout_href: str                   # where Sign out goes: MK-3's /signout hop (D10)

    @property
    def admin(self) -> bool:
        """The ADMIN tag: exactly the catalogue gate that offers Operations (never a second role source)."""
        return self.operations is not None


def build_me(tiles, username: str, signout_href: str) -> MeVM:
    return MeVM(_plain(username or ""), place_link(tiles, OPERATIONS_PATH), signout_href)


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
    shown may be out of date, rather than a notice that contradicts a live-looking place. Up next (Watch) and the
    shelves (Listen) are left out: when one alone fails, its rows are simply not shown and the library still answers."""
    return any(sec["state"] == "unavailable" for sec in secs if sec.get("section") not in ("next_up", "shelves"))


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


HOME_ALL = "all"
WATCH_ROWS = (("movies", "Movies", ("movie",)), ("shows", "TV shows", ("series", "episode")))
NOTHING_UP_NEXT = "Nothing up next. The next episode of a show you are watching appears here."


# The Audiobooks shelves (owner decision 2026-10-27), in this order after Recently added. Keys are the adapter's.
SHELF_ROWS = (("new", "New releases"), ("classics", "Classics"), ("short", "Short listens"),
              ("epic", "Epic listens"))
_EXTRA_FOR = {"jellyfin": "next_up", "audiobookshelf": "shelves", "komga": "shelves"}
# Libraries whose Recently added gives way to Recently released when nothing was added in the last two months
# (owner decisions 2026-10-27 Audiobookshelf, 2026-10-28 Komga).
RELEASED_FALLBACK = ("audiobookshelf", "komga")


def extra_sections_for(raw_focus) -> Tuple[Tuple[str, str], ...]:
    """The (library, section) pairs a Home filter needs beyond Continue and Recently added (Watch: Up next; Listen:
    the shelves; Comics and Read: Komga's New releases), so the caller gathers them too, from that library only.
    It only decides what to ask for; `build_home` still checks the member's own places."""
    services = _PLACE_SERVICES.get(raw_focus, ()) if isinstance(raw_focus, str) else ()
    return tuple((s, _EXTRA_FOR[s]) for s in services if s in _EXTRA_FOR)


def library_extra_sections(raw_chip) -> Tuple[Tuple[str, str], ...]:
    """The extra (library, section) pairs a Library chip needs: the Audiobooks shelves when that library is chosen."""
    return (("audiobookshelf", "shelves"),) if raw_chip == "audiobookshelf" else ()


def shelf_rows(shelved, limit: int, title_services, rows_of=SHELF_ROWS) -> list:
    """One RowVM per non-empty shelf, in SHELF_ROWS order."""
    out = []
    for key, heading in rows_of:
        cards = _cards([it for it in shelved if it.shelf == key][:limit],
                       lambda it: it.detail or KIND_LABEL.get(it.kind), title_services=title_services)
        if cards:
            out.append(RowVM(key, heading, cards))
    return out


def build_filters(places, focus: Optional[str]):
    """Home's filters and the chosen place. One per library place the member has, in the catalogue's order, after All;
    none at all for a member with fewer than two (one place is the same list as All). An unknown or foreign `focus`
    falls back to All and is never echoed."""
    libs = [p for p in places if p.href[1:] in _PLACE_SERVICES]
    if len(libs) < 2:
        return (), None
    keys = {p.href[1:] for p in libs}
    chosen = focus if isinstance(focus, str) and focus in keys else None
    out = [FilterVM(HOME_ALL, "All", "/", chosen is None)]
    out.extend(FilterVM(p.href[1:], p.label, "/?for=" + p.href[1:], p.href[1:] == chosen, p.up) for p in libs)
    return tuple(out), chosen


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
    upstream product). The Home hero is the one exception: its button names the app that opens (HERO_APP), as
    the approved design shows. It never claims that playback starts: the library opens at the item."""
    verb = "Resume" if (in_continue and it.resumable) else "Open"
    library = SERVICE_LABEL.get(it.service)
    return verb, (f"{verb} in {library}" if library else verb)


def _bar(it: ItemVM) -> Optional[int]:
    """The progress rule in 5% steps, only beside progress words (a rule never stands alone)."""
    if it.fraction is None or not it.progress:
        return None
    return max(0, min(100, int(round(it.fraction * 20)) * 5))


def _details_href(it: ItemVM, title_services) -> Optional[str]:
    """The item's title page, where its library offers the permission-checked item lookup and the id is valid."""
    parts = split_item_id(it.item_id)
    if parts is None or parts[0] != it.service or it.service not in title_services:
        return None
    return title_href(parts[0], parts[1])


def _cards(items, line_of, progress: bool = False, title_services=frozenset()) -> Tuple[CardVM, ...]:
    """Continue cards (`progress`) open the item where it plays. Any other card opens the item's title page when its
    library has one (the page script shows it as a sheet over this page; owner decision 2026-10-27), else the item
    in its own library as before."""
    out = []
    for it in items:
        verb, name = action_of(it, progress)
        href = (None if progress else _details_href(it, title_services)) or it.href
        out.append(CardVM(it.title, href, SHAPE.get(it.kind, "poster"), line_of(it), it.image,
                          it.progress if progress else None, kind_label=KIND_LABEL.get(it.kind),
                          action=verb, action_label=name, bar=_bar(it) if progress else None))
    return tuple(out)


def hero_of(it: ItemVM, state: str, title_services=frozenset()) -> Optional[HeroVM]:
    """The hero for one of THIS member's items (already filtered by `_item_vm`: https hand-off on a fixed host).
    Continue: progress in words, then the library. Recently added: the series or episode line (or what it is),
    then the library. Details links to the title page only where that library offers the permission-checked
    item lookup and the id is valid; otherwise there is no Details at all, never a dead link."""
    if it.service not in HERO_APP or not handoff_ok(it.href, it.service):
        return None
    library = SERVICE_LABEL[it.service]
    kind = KIND_LABEL.get(it.kind)
    if state == "continue":
        meta = " · ".join(x for x in (it.progress or it.detail, library) if x)
    elif it.detail:
        meta = f"{it.detail} · {library}"
    else:
        meta = kicker_of(kind or "", library)      # "Episode · Movies and TV", but "Movies and TV" for a movie
    verb = "Resume" if (state == "continue" and it.service == "jellyfin" and it.resumable) else HERO_VERB[it.service]
    details = _details_href(it, title_services)
    return HeroVM(state, it.title, SHAPE.get(it.kind, "poster"), it.image, meta or None,
                  f"{verb} in {HERO_APP[it.service]}", it.href, details, it.backdrop)


def build_home(view: dict, tiles, *, new_tab: Optional[str] = None, limit: int = RAIL_MOST,
               member_name: str = "", title_services=frozenset(), focus: Optional[str] = None) -> HomeVM:
    """Home as display data. Retry links point at `/` (the new tab is kept), the same page again.
    `title_services`: libraries with a title page (main.py's set), for the hero's Details link and the Recently added
    cards (which open the title page; Continue cards open the item where it plays)."""
    limit = max(1, min(int(limit), RAIL_MOST))
    held = _sections_by_service(view)
    places = build_places(tiles, view)
    filters, focus = build_filters(places, focus)
    focus_open = None
    if focus is not None:      # Home for one place: only its libraries' sections, and its own site one tap away
        held = {s: v for s, v in held.items() if s in _PLACE_SERVICES[focus]}
        focus_open = next(((p.label, p.href) for p in places if p.href == "/" + focus and p.up), None)
    has_lib = has_library(tiles)
    name = _plain(member_name) or "Member"
    base = dict(member_name=name, initial=initial_of(name), places=places, filters=filters, focus=focus,
                focus_open=focus_open)
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
    keep = ([f"for={focus}"] if focus else []) + ([f"new={new_tab}"] if new_tab in SERVICE_LABEL else [])
    retry_href = ("/" + ("?" + "&".join(keep) if keep else "")) if retry else None
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

    # Recently added: a tab for each library that answers; anything else falls back to All. A member with
    # exactly one library has no use for "All" (it is the same list), so that tab is not offered.
    libs = [(s, SERVICE_LABEL[s]) for s in SERVICE_ORDER
            if any(x["section"] == "recent" and x["state"] in ("ok", "empty") for x in held.get(s, ()))]
    tabs = [(NEW_ALL, "All")] + libs if len(libs) != 1 else list(libs)
    tab = new_tab if isinstance(new_tab, str) and new_tab in {k for k, _ in tabs} else tabs[0][0]
    if tab == NEW_ALL:           # the newest of each library; the second line says which library
        per = [_cards(items_of("recent", s), lambda it, s=s: SERVICE_LABEL[s], title_services=title_services)
               for s in SERVICE_ORDER]
        new = tuple(_round_robin(per, limit))
        new_said = None if (new or notices) else NOTHING_NEW
    else:
        new = _cards(items_of("recent", tab)[:limit], lambda it: it.detail or KIND_LABEL.get(it.kind),
                     title_services=title_services)
        new_said = None if new else (NOTHING_NEW if len(libs) == 1 else f"Nothing recently added in {SERVICE_LABEL[tab]}.")

    # Watch (owner decision 2026-10-27): Up next, then Recently added split into Movies and TV shows, in place of the
    # one Recently added rail. Up next leaves out what Continue already shows.
    rows = ()
    if focus is not None and _PLACE_SERVICES[focus] == ("jellyfin",) and "jellyfin" in held:
        shown = {it.item_id for it in cont}
        built = []
        if any(x["section"] == "next_up" and x["state"] in ("ok", "empty") for x in held["jellyfin"]):
            nxt = [it for it in items_of("next_up", "jellyfin") if it.item_id not in shown][:limit]
            built.append(RowVM("next", "Up next", _cards(nxt, lambda it: it.detail, title_services=title_services),
                               None if nxt else NOTHING_UP_NEXT, tall=False))
        recent = items_of("recent", "jellyfin")
        for key, heading, kinds in WATCH_ROWS:
            cards = _cards([it for it in recent if it.kind in kinds][:limit],
                           lambda it: it.detail or KIND_LABEL.get(it.kind), title_services=title_services)
            if cards:
                built.append(RowVM(key, heading, cards))
        rows = tuple(built)
    elif focus is not None:
        # Listen (owner decision 2026-10-27): Recently added, then the library's shelves, so the page leads with what
        # the library holds. Read (two libraries): one row per library. A single row keeps the plain section.
        services = [s for s in _PLACE_SERVICES[focus] if s in held]
        built, released_only = [], False
        if len(services) > 1:
            for s in services:
                cards = _cards(items_of("recent", s)[:limit], lambda it: it.detail or KIND_LABEL.get(it.kind),
                               title_services=title_services)
                if not cards and s in RELEASED_FALLBACK:      # nothing new in two months: the newest releases
                    released = shelf_rows(items_of("shelves", s), limit, title_services,
                                          (("new", f"Recently released {SERVICE_LABEL[s].lower()}"),))
                    built += [RowVM(s.replace("-", ""), r.heading, r.items) for r in released]
                    released_only = released_only or bool(released)
                elif cards:
                    built.append(RowVM(s.replace("-", ""), SERVICE_LABEL[s], cards))
        elif services:
            s = services[0]
            cards = _cards(items_of("recent", s)[:limit], lambda it: it.detail or KIND_LABEL.get(it.kind),
                           title_services=title_services)
            shelved = items_of("shelves", s)
            if cards or s not in RELEASED_FALLBACK:
                built.append(RowVM("new", "Recently added", cards, None if cards else NOTHING_NEW))
                built += shelf_rows(shelved, limit, title_services)
            else:
                # Nothing added in the last two months (owner decision 2026-10-27): the row says Recently released and
                # shows the newest releases instead of old additions; New releases is then that row.
                released = shelf_rows(shelved, limit, title_services, (("new", "Recently released"),))
                built += [RowVM("new", r.heading, r.items) for r in released]
                built += shelf_rows(shelved, limit, title_services, SHELF_ROWS[1:])
                released_only = bool(released)
        # One row alone is the plain Recently added section, unless it is Recently released (it must keep its name).
        rows = tuple(built) if len(built) > 1 or released_only else ()

    # The hero (memo section 4, Actual states only): the member's own next thing. H1: the first Continue item that
    # is not from a library said to be down (a stale card stays in its rail, but is never the one big promise).
    # H0, nothing in progress: the first Recently added item, newest of each library in library order, whichever
    # tab is chosen (the hero does not jump when the member changes tab). Nothing at all: no hero.
    def up(it):
        return not library_down(held.get(it.service, ()))
    first_cont = next((it for it in cont if up(it)), None)
    if first_cont is not None:
        hero = hero_of(first_cont, "continue", title_services)
    else:
        recent = _round_robin([[it for it in items_of("recent", s) if up(it)] for s in SERVICE_ORDER], 1)
        hero = hero_of(recent[0], "recent", title_services) if recent else None
    return HomeVM(**base, no_library=False, notices=tuple(notices), show_continue=bool(cont_services),
                  continue_items=_cards(cont, lambda it: it.detail, progress=True),
                  continue_said=continue_said, show_new=not rows, rows=rows,
                  new_tabs=tuple((k, n, k == tab) for k, n in tabs), new_items=new, new_said=new_said,
                  retry_href=retry_href, setup_href=setup_href, hero=hero)


# ---- The Library page (Concept K MK-5a, AVR-719): chips, one shelf per library, the Request group ------------
# Pure functions over the same `member_view()` Home renders (Continue and Recently added, this member only) plus the
# catalogue's tile list. Nothing here calls an adapter or builds a URL from upstream data: shelf items are Home's own
# Recently added cards, the "Open <app>" links are the member's own place routes (the catalogue's group-gated paths,
# passed in by the caller), and the Request group links the existing place pages.
LIBRARY_ALL = "all"
# Each library's own place route (the catalogue path Home's places bar and Account already use for it). The caller
# keeps only those this member's groups open, so a link is never offered that would be the standard 404.
LIBRARY_PLACE = {s: p for p, s in ACCOUNT_LIBRARY.items()}
LIBRARY_ASKS = ("request", "contribute")         # the catalogue's request-side places, in Home's order


@dataclass(frozen=True)
class LibraryChipVM:
    key: str                      # "all" or a service value; never anything from the address
    label: str                    # "All", or the library in member language
    href: str
    current: bool
    down: bool = False            # the library said unavailable: struck, ", unavailable" for screen readers


@dataclass(frozen=True)
class ShelfVM:
    service: str
    label: str                    # member language ("Movies and TV")
    state: str                    # ok | empty | not_linked (a down library is a warning, never a shelf)
    items: Tuple[CardVM, ...] = ()
    message: Optional[str] = None
    open_href: Optional[str] = None   # the member's own place route for this library, or None (no link)
    open_app: Optional[str] = None    # "Jellyfin": the app that place opens (HERO_APP)
    rows: Tuple[RowVM, ...] = ()      # one library chosen: its rows (Movies and TV shows; Recently added and shelves)


@dataclass(frozen=True)
class LibraryVM:
    no_library: bool
    chips: Tuple[LibraryChipVM, ...] = ()
    chosen: str = "all"
    chosen_label: Optional[str] = None     # the chosen library in member language (None for All)
    warnings: Tuple[str, ...] = ()         # Home's own unavailable sentences, one per down library (or one combined)
    retry_href: Optional[str] = None       # "Try again": this same page, the chosen chip kept
    shelves: Tuple[ShelfVM, ...] = ()
    said: Optional[str] = None             # the honest empty state ("Nothing recently added.")
    setup_href: Optional[str] = None       # "What to do next": a library is not set up for this member
    asks: Tuple[Tuple[str, object, object], ...] = ()   # (href, label, description): catalogue text (Trusted)
    asks_heading: str = "Requests"         # "Request or contribute" when both rows are there; contributing is no request
    view: str = "large"                    # the layout (LIBRARY_VIEWS); never anything from the address
    views: Tuple[Tuple[str, str, str, bool], ...] = ()   # (key, label, href, current): the layout switcher
    view_label: str = "Shelves"            # the chosen layout's name, on the layout button
    list_class: str = "rail"               # the class every list of cards on this page takes (LIBRARY_LIST_CLASS)


def asks_heading_of(asks) -> str:
    paths = {href for href, _l, _d in asks}
    if "/contribute" in paths:
        return "Request or contribute" if "/request" in paths else "Contribute"
    return "Requests"


# The Library's layouts (owner decisions 2026-10-27; reworked the same day): Shelves (rows that scroll sideways,
# the default; a page with one row shows it as a grid), Grid (large covers), Compact (a dense wall of small covers)
# and List (a small cover beside its words). A text-only list was dropped: covers are how people find media. Chosen
# with `?view=`; the chosen library chip is kept, and the reverse. The first names stay readable as aliases.
LIBRARY_VIEWS = (("shelves", "Shelves"), ("grid", "Grid"), ("compact", "Compact"), ("list", "List"))
LIBRARY_VIEW_DEFAULT = "shelves"
LIBRARY_VIEW_ALIAS = {"large": "grid", "small": "compact", "details": "list"}
# The class each layout gives a list of cards (the page script mirrors this when it switches in place).
LIBRARY_LIST_CLASS = {"grid": "lib-grid", "compact": "lib-grid lib-v-compact", "list": "lib-grid lib-v-list"}


def list_class_of(layout: str, shelves) -> str:
    """Shelves are rows that scroll sideways, except that a page with only one row shows it as a grid."""
    if layout != "shelves":
        return LIBRARY_LIST_CLASS[layout]
    lists = sum(len(sh.rows) or 1 for sh in shelves if sh.items)
    return "rail" if lists > 1 else "lib-grid"


def library_href(key: str, view: str = LIBRARY_VIEW_DEFAULT) -> str:
    query = ([] if key == LIBRARY_ALL else [f"lib={key}"]) + ([] if view == LIBRARY_VIEW_DEFAULT else [f"view={view}"])
    return "/library" + ("?" + "&".join(query) if query else "")


def build_library(view: dict, tiles, *, chip: Optional[str] = None, limit: int = RAIL_MOST,
                  open_paths=None, title_services=frozenset(), view_mode: Optional[str] = None) -> LibraryVM:
    """The Library page as display data. `chip` is the bounded `?lib=` text (identity.library_chip_from_scope): it is
    matched against THIS member's own libraries only and is never echoed; anything else is All. `open_paths`:
    service -> the member's own place route (already group-filtered by the caller). A library is named only when
    this member's sections hold it (`member_view()` omits a library the member cannot use)."""
    limit = max(1, min(int(limit), RAIL_MOST))
    view_mode = LIBRARY_VIEW_ALIAS.get(view_mode, view_mode) if isinstance(view_mode, str) else None
    layout = view_mode if view_mode in dict(LIBRARY_VIEWS) else LIBRARY_VIEW_DEFAULT
    asks = tuple(("/" + path, label, desc) for path, label, desc in tiles if path in LIBRARY_ASKS)
    if not has_library(tiles):
        return LibraryVM(no_library=True, asks=asks, asks_heading=asks_heading_of(asks))
    held = _sections_by_service(view)
    mine = [s for s in SERVICE_ORDER if s in held]
    down = {s for s in mine if library_down(held[s])}
    chosen = chip if isinstance(chip, str) and chip in mine else LIBRARY_ALL
    chips = (LibraryChipVM(LIBRARY_ALL, "All", library_href(LIBRARY_ALL, layout), chosen == LIBRARY_ALL),) + tuple(
        LibraryChipVM(s, SERVICE_LABEL[s], library_href(s, layout), chosen == s, s in down) for s in mine)
    views = tuple((k, label, library_href(chosen, k), k == layout) for k, label in LIBRARY_VIEWS)
    shown = mine if chosen == LIBRARY_ALL else [chosen]
    paths = open_paths or {}

    def recent_of(service: str):
        out = []
        for sec in held.get(service, ()):
            if sec["section"] == "recent" and sec["state"] == "ok":
                out.extend(vm for vm in (_item_vm(it) for it in sec.get("items", ())) if vm is not None)
        return out

    warnings, shelves, unset = [], [], False
    for s in shown:
        label = SERVICE_LABEL[s]
        if s in down:                          # a section said unavailable: Home's sentence, none of its items
            warnings.append(service_notice(s, "unavailable"))
            continue
        open_href = paths.get(s) if paths.get(s) == "/" + LIBRARY_PLACE[s] else None
        if any(sec["state"] == "not_linked" for sec in held[s]):
            unset = True
            shelves.append(ShelfVM(s, label, "not_linked", message=service_notice(s, "not_linked")))
            continue
        cards = _cards(recent_of(s)[:limit], lambda it: it.detail or KIND_LABEL.get(it.kind),
                       title_services=title_services)
        app = HERO_APP[s] if open_href else None
        rows = ()
        if chosen != LIBRARY_ALL:              # one library: its own rows, where it has more than one
            recent = recent_of(s)
            if s == "jellyfin":
                built = [RowVM(key, heading, _cards([it for it in recent if it.kind in kinds][:limit],
                                                    lambda it: it.detail or KIND_LABEL.get(it.kind),
                                                    title_services=title_services))
                         for key, heading, kinds in WATCH_ROWS]
                built = [r for r in built if r.items]
            else:
                built = [RowVM("new", "Recently added", cards)] if cards else []
                shelved = [vm for sec in held[s] if sec["section"] == "shelves" and sec["state"] == "ok"
                           for vm in (_item_vm(it) for it in sec.get("items", ())) if vm is not None]
                built += shelf_rows(shelved, limit, title_services)
            rows = tuple(built) if len(built) > 1 else ()
        if cards:
            shelves.append(ShelfVM(s, label, "ok", cards, open_href=open_href, open_app=app, rows=rows))
        else:
            shelves.append(ShelfVM(s, label, "empty", message=f"Nothing recently added in {label}.",
                                   open_href=open_href, open_app=app))
    if chosen == LIBRARY_ALL and len(warnings) > 1 and len(warnings) == len(mine):
        warnings = ["None of your libraries is answering right now."]   # Home's combined line (all down)
    said = None
    if chosen == LIBRARY_ALL and shelves and all(sh.state == "empty" for sh in shelves) and not warnings:
        said = NOTHING_NEW                     # nothing anywhere: one honest line, not a column of empty shelves
    return LibraryVM(no_library=False, chips=chips, chosen=chosen,
                     chosen_label=None if chosen == LIBRARY_ALL else SERVICE_LABEL[chosen],
                     warnings=tuple(warnings), retry_href=library_href(chosen, layout) if warnings else None,
                     shelves=tuple(shelves), said=said, setup_href=SETUP_HELP if unset else None, asks=asks,
                     asks_heading=asks_heading_of(asks), view=layout, views=views,
                     view_label=dict(LIBRARY_VIEWS)[layout], list_class=list_class_of(layout, shelves))


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
    path: str = ""                # the catalogue request path ("requests", ...): picks the row's decorative icon


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
        nouns = by_href.setdefault(href, (leaves, [], path))[1]
        if noun not in nouns:
            nouns.append(noun)
    return tuple(RequestVM(href, "Ask for " + " or ".join(nouns), leaves, path)
                 for href, (leaves, nouns, path) in by_href.items())


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
    backdrop: Optional[str] = None     # the wide Jellyfin backdrop over the top of the page (owner review 2026-10-27)
    kicker: str = ""                   # "Episode · Movies and TV"; the medium only when the library name lacks it
    progress: Optional[str] = None     # in words, whenever the upstream gave this member progress (not finished)
    bar: Optional[int] = None          # the 3px Cream rule beside the progress words, in 5% steps (as on Continue)
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
    fraction = progress_fraction(it.get("progress")) if progress else None
    bar = max(0, min(100, int(round(fraction * 20)) * 5)) if fraction is not None else None
    if resume:
        action = "Resume"
    elif progress:
        action = "Open"
    else:
        action = ACTION.get(kind, "Open")
    return TitleVM("ok", label, title=title, medium=medium, kicker=kicker_of(medium, label),
                   line=" · ".join(x for x in (creator, str(year) if year else None) if x) or None,
                   detail=_detail_of(it, creator, year), shape=SHAPE.get(kind, "poster"),
                   image=_image(it.get("artwork")), backdrop=_image(it.get("backdrop")), progress=progress, bar=bar,
                   summary=_plain(it.get("summary") or "", MAX_SUMMARY + 1) or None, action=action, action_href=href,
                   action_label=f"{action} {title} in {label}", back_href=back)
