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
                                    progress_words(it.get("kind", ""), it.get("progress"))))
            if items:
                out.append(SectionVM(service, section, heading, "ok", tuple(items)))
        elif state == "unavailable":
            out.append(SectionVM(service, section, heading, state,
                                 message=f"{label} are unavailable right now."))
        elif state == "not_linked":
            out.append(SectionVM(service, section, heading, state,
                                 message=f"{label} are not set up for your account yet."))
    return tuple(out)
