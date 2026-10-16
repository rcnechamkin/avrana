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


def build_sections(view: dict) -> Tuple[SectionVM, ...]:
    out = []
    for raw in view.get("sections", ()):
        service, section, state = raw.get("service"), raw.get("section"), raw.get("state")
        if state in (None, "not_permitted", "empty") or service not in SERVICE_LABEL:
            continue                                   # absence, never a hint
        label = SERVICE_LABEL[service]
        heading = _heading(service, section)
        if state == "ok":
            items = []
            for it in raw.get("items", ()):
                href = it.get("handoff_url")
                if not isinstance(href, str) or not href.startswith(_HANDOFF_PREFIX):
                    continue
                detail = " · ".join(_plain(x) for x in (it.get("series"), it.get("subtitle")) if x) or None
                items.append(ItemVM(_plain(it.get("title") or "") or "Untitled", href,
                                    str(it.get("kind", "")), detail,
                                    progress_words(it.get("kind", ""), it.get("progress")),
                                    _image(it.get("artwork"))))
            if items:
                out.append(SectionVM(service, section, heading, "ok", tuple(items)))
        elif state == "unavailable":
            out.append(SectionVM(service, section, heading, state,
                                 message=f"{label} are unavailable right now."))
        elif state == "not_linked":
            out.append(SectionVM(service, section, heading, state,
                                 message=f"{label} are not set up for your account yet."))
    return tuple(out)


# ---- search page (AVR-383) --------------------------------------------------------------------------------
SEARCH_MAX_SHOWN = 100          # characters of the typed term put back in the box
SEARCH_MIN_HINT = "Type at least 2 letters or numbers. Search matches titles, and * ? % are treated as spaces."


@dataclass(frozen=True)
class SearchGroupVM:
    service: str
    label: str
    state: str                    # ok | empty | unavailable | not_linked
    items: Tuple[ItemVM, ...] = ()
    message: Optional[str] = None


@dataclass(frozen=True)
class SearchVM:
    mode: str                     # no_library | idle | invalid | results
    term: str = ""                # bounded, printable; the template autoescapes it
    message: Optional[str] = None
    hint: Optional[str] = None
    groups: Tuple[SearchGroupVM, ...] = ()
    found: int = 0


def build_search(view: dict, raw_term: Optional[str]) -> SearchVM:
    """`view` is `SearchResults.search_view()`; `raw_term` the bounded text from the address (or None).
    Libraries the member cannot use are not in `view`, and nothing here can name them."""
    term = _plain(raw_term or "", SEARCH_MAX_SHOWN)
    if not view.get("entitled") or (view.get("status") == "ok" and not view.get("groups") and raw_term is not None):
        return SearchVM("no_library", message="Search is not available on your account yet.")
    if raw_term is None:
        return SearchVM("idle", hint="Searches the libraries on your account.")
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
                                        message=f"The {label} library is unavailable right now. Try again in a moment."))
        elif state == "not_linked":
            groups.append(SearchGroupVM(service, label, "not_linked",
                                        message=f"The {label} library is not set up for your account yet."))
    if not found:
        down = any(g.state in ("unavailable", "not_linked") for g in groups)
        msg = ("Nothing found in the libraries that could be searched." if down
               else "Nothing found. Check the spelling or try fewer words.")
        return SearchVM("results", term=term, message=msg, groups=tuple(groups))
    return SearchVM("results", term=term, message=f"{found} found.", groups=tuple(groups), found=found)
