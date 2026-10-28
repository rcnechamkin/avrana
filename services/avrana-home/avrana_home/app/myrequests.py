"""My requests (`/request/mine`): what the member has asked for, where each request stands, and a way to take one back.

Status: proposed, not deployed. No request input is read here (identity.py and forms.py read the form); this module
turns the brokers' answers (requests/shelfarr.py `mine`, requests/seerr.py `mine`) into what the member reads. Both
lists are the member's OWN: the clients drop every row whose owner is someone else, and nothing here names another
member. One list, newest first, in two groups: still on the way, and done.

Arrived titles link to Home's own pages: a film or show to its title page when this member's own permission-checked
Jellyfin lookup finds it, everything else to Home's search for the title. Nothing links to the request services.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import urlencode

from ..requests.forms import FormSigner
from ..requests.omnibus import SeriesState
from ..requests.seerr import CancelOutcome as WatchCancel, RequestState as WatchState, WatchRequest
from ..requests.shelfarr import BookRequest, CancelOutcome as BookCancel, RequestState as BookState
from .bookrequests import GUARD_COPY, LIBRARY_LABEL, AskVM, OwnedVM

PATH = "/request/mine"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FORMAT_NOUN = {"ebook": "Ebook", "audiobook": "Audiobook"}
KIND = {"movie": "Film", "tv": "Series"}
WATCH_LIBRARY = "Movies and TV"

# status line, longer note, done?  (fixed words only; nothing upstream sends is shown)
BOOK_COPY = {
    BookState.LOOKING: ("Looking for it", "", False),
    BookState.NOT_FOUND: ("Not found yet", "It is looked for again from time to time.", False),
    BookState.WAITING: ("Waiting for the owner", "Only a copy that has to be bought was found.", False),
    BookState.COMING: ("On its way", "", False),
    BookState.ARRIVED: ("Arrived", "", True),
    BookState.STOPPED: ("Stopped", "Cancelled, or it could not be fetched.", True),
}
WATCH_COPY = {
    WatchState.AWAITING: ("Waiting for approval", "", False),
    WatchState.COMING: ("On its way", "", False),
    WatchState.PARTIAL: ("Partly arrived", "Some of it is in Movies and TV; the rest is on its way.", False),
    WatchState.ARRIVED: ("Arrived", "", True),
    WatchState.DECLINED: ("Declined", "", True),
    WatchState.FAILED: ("Could not be fetched", "The owner can see this.", True),
}
CANCEL_COPY = {
    "cancelled": "Cancelled your request for {title}.",
    "not_allowed": "{title} can no longer be cancelled. It may already be on its way.",
    "unavailable": "Requests could not be reached right now. Try again later.",
}
NOT_LINKED = {"watch": "Film and show requests are not set up for your account yet. Open the request website once "
                       "to sign in.",
              "comics": "Comic requests are not set up for your account yet. Open the request website once to sign "
                        "in."}
UNAVAILABLE = {"books": "Book requests could not be reached right now.",
               "watch": "Film and show requests could not be reached right now.",
               "comics": "Comic requests could not be reached right now."}
COMIC_COPY = {
    SeriesState.AWAITING: ("Waiting for approval", "", False),
    SeriesState.COMING: ("On its way", "", False),
    SeriesState.WAITING_RELEASE: ("Waiting for new issues", "The rest are not out yet.", False),
    SeriesState.STUCK: ("Stuck", "The owner can see this.", False),
    SeriesState.ARRIVED: ("Arrived", "", True),
}
LIMITED = "You have looked a lot in the last few minutes. Try again shortly."
NEW_DAYS = 3                       # an arrival this recent is marked New (no state kept: it is about the date only)


@dataclass(frozen=True)
class RowVM:
    title: str
    line: str                      # "Ebook · asked 28 Oct"
    status: str                    # "On its way"
    note: str = ""
    done: bool = False
    tone: str = ""                 # "ok" (arrived) | "warn" (declined, failed) | ""
    open: Optional[OwnedVM] = None
    cancel: Optional[AskVM] = None
    asked_on: str = ""             # sort key, ISO date
    new: bool = False              # arrived in the last NEW_DAYS days
    changed_on: str = ""           # Done is sorted by this (newest arrivals first)


@dataclass(frozen=True)
class SaidVM:
    message: str
    warn: bool = False
    place_href: Optional[str] = None


@dataclass(frozen=True)
class MinePageVM:
    coming: Tuple[RowVM, ...] = ()
    done: Tuple[RowVM, ...] = ()
    problems: Tuple[SaidVM, ...] = ()           # a service that could not be read, or is not set up
    ask_books: Optional[str] = None             # Home's ask pages this member may use
    ask_watch: Optional[str] = None
    ask_comics: Optional[str] = None
    notice: Optional[SaidVM] = None             # the outcome of the cancel that redirected here
    outcome: str = ""                           # page title prefix


def asked_label(iso: str, today: dt.date) -> str:
    try:
        day = dt.date.fromisoformat(iso)
    except ValueError:
        return ""
    if day == today:
        return "asked today"
    text = f"asked {day.day} {MONTHS[day.month - 1]}"
    return text if day.year == today.year else f"{text} {day.year}"


def is_new(iso: str, today: dt.date) -> bool:
    try:
        return 0 <= (today - dt.date.fromisoformat(iso)).days < NEW_DAYS
    except ValueError:
        return False


def _line(noun: str, iso: str, today: dt.date) -> str:
    return " · ".join(p for p in (noun, asked_label(iso, today)) if p)


def search_href(title: str) -> str:
    return "/search?" + urlencode({"q": title[:100]})


def book_rows(rows, username: str, signer: FormSigner, today: dt.date) -> Tuple[RowVM, ...]:
    out = []
    for r in rows:
        status, note, done = BOOK_COPY[r.state]
        if r.told and not done:
            note = " ".join(p for p in (note, "The owner has been told.") if p)
        fields = {"service": "books", "request_id": str(r.request_id), "title": r.title}
        cancel = AskVM("Cancel request", tuple(sorted(fields.items())), signer.sign(username, fields)) \
            if r.cancellable else None
        found = OwnedVM(LIBRARY_LABEL[r.book_type], search_href(r.title), False) if r.state is BookState.ARRIVED \
            else None
        arrived = r.state is BookState.ARRIVED
        out.append(RowVM(r.title, _line(FORMAT_NOUN[r.book_type], r.asked_on, today), status, note, done,
                         "ok" if arrived else "", found, cancel, r.asked_on, arrived and is_new(r.changed_on, today),
                         r.changed_on))
    return tuple(out)


def watch_rows(rows, username: str, signer: FormSigner, today: dt.date, opens=None) -> Tuple[RowVM, ...]:
    """`opens`: {request_id: OwnedVM} for titles this member's own Jellyfin lookup found (decided by the caller)."""
    opens = opens or {}
    out = []
    for r in rows:
        status, note, done = WATCH_COPY[r.state]
        title = r.title or ("A film" if r.media_type == "movie" else "A show")
        if not r.title:
            note = " ".join(p for p in (note, "Reload to see its name.") if p)
        line = _line(" · ".join(p for p in (KIND[r.media_type], str(r.year) if r.year else "") if p), r.asked_on,
                     today)
        fields = {"service": "watch", "request_id": str(r.request_id), "title": title}
        cancel = AskVM("Cancel request", tuple(sorted(fields.items())), signer.sign(username, fields)) \
            if r.cancellable else None
        found = None
        if r.state in (WatchState.ARRIVED, WatchState.PARTIAL):
            found = opens.get(r.request_id) or (OwnedVM(WATCH_LIBRARY, search_href(r.title), False) if r.title
                                                else None)
        tone = "ok" if r.state is WatchState.ARRIVED else ("warn" if r.state in (WatchState.DECLINED,
                                                                                   WatchState.FAILED) else "")
        landed = r.state in (WatchState.ARRIVED, WatchState.PARTIAL)
        out.append(RowVM(title, line, status, note, done, tone, found, cancel, r.asked_on,
                         landed and is_new(r.changed_on, today), r.changed_on))
    return tuple(out)


def comic_rows(rows, today: dt.date) -> Tuple[RowVM, ...]:
    """One row per series (Omnibus asks per issue). No cancel: the fork's key cannot."""
    out = []
    for r in rows:
        status, note, done = COMIC_COPY[r.state]
        if r.state is SeriesState.ARRIVED:
            count = f"All {r.total} issues arrived." if r.total > 1 else ""
        else:
            count = f"{r.arrived} of {r.total} issues arrived." if r.total > 1 and r.arrived else ""
        note = " ".join(p for p in (count, note) if p)
        found = OwnedVM("Comics", search_href(r.name), False) if r.arrived else None
        out.append(RowVM(r.name, _line("Comic series", r.asked_on, today), status, note, done,
                         "ok" if done else ("warn" if r.state is SeriesState.STUCK else ""), found, None, r.asked_on,
                         bool(r.arrived) and is_new(r.changed_on, today), r.changed_on))
    return tuple(out)


def build_page(books=None, watch=None, comics=None, *, ask_books: Optional[str] = None,
               ask_watch: Optional[str] = None, ask_comics: Optional[str] = None, watch_place: Optional[str] = None,
               comics_place: Optional[str] = None) -> MinePageVM:
    """`books` / `watch`: (state, rows) where state is "ok" | "empty" | "unavailable" | "not_linked" | "limited", or
    None when that broker is off or not this member's. Rows are already RowVMs (book_rows / watch_rows)."""
    rows, problems = [], []
    places = {"watch": watch_place, "comics": comics_place}
    for service, part in (("books", books), ("watch", watch), ("comics", comics)):
        if part is None:
            continue
        state, found = part
        if state == "ok":
            rows.extend(found)
        elif state == "not_linked" and service in NOT_LINKED:
            problems.append(SaidVM(NOT_LINKED[service], True, places[service]))
        elif state == "limited":
            if not any(p.message == LIMITED for p in problems):
                problems.append(SaidVM(LIMITED, True))
        elif state == "unavailable":
            problems.append(SaidVM(UNAVAILABLE[service] + " Try again later.", True))
    rows.sort(key=lambda r: r.asked_on, reverse=True)          # stable: each service's own order breaks ties
    coming = tuple(r for r in rows if not r.done)
    done = tuple(sorted((r for r in rows if r.done), key=lambda r: r.changed_on or r.asked_on, reverse=True))
    fresh = sum(1 for r in rows if r.new)
    outcome = (f"{fresh} new" + (f", {len(coming)} on the way" if coming else "")) if fresh else \
        (f"{len(coming)} on the way" if coming else ("Nothing on the way" if rows else ""))
    return MinePageVM(coming, done, tuple(problems), ask_books, ask_watch, ask_comics, outcome=outcome)


def cancel_said(outcome, guard: Optional[str], title: str) -> SaidVM:
    if guard is not None:
        text = {"repeat": "You just did that.", "rate": GUARD_COPY["rate"],
                "expired": "This page had expired, so nothing was cancelled. Here is the latest."}[guard]
        return SaidVM(text, guard != "repeat")
    value = outcome.value if isinstance(outcome, (BookCancel, WatchCancel)) else "unavailable"
    return SaidVM(CANCEL_COPY[value].format(title=title or "That request"), value != "cancelled")
