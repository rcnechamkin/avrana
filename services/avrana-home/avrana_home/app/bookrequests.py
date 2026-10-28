"""The page for asking for a book or an audiobook (`/request/books`): view-model and member wording.

Status: proposed, not deployed. No request input is read here (identity.py reads the term and the form); this module
turns Shelfarr's answers (requests/shelfarr.py) into what the member reads, and decides which format buttons a member
gets: a format only where the upstream says it exists AND the member holds the library group it fills.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from ..requests.forms import FormSigner
from ..requests.shelfarr import FORMAT_GROUP, MAX_TERM, BookOffer, Outcome

PATH = "/request/books"
FORMAT_LABEL = {"ebook": "ebook", "audiobook": "audiobook"}
LIBRARY_LABEL = {"ebook": "Books", "audiobook": "Audiobooks"}
LIMITED = "You have searched a lot in the last few minutes. Try again shortly."
OWNED_CHECKS = 3               # permission-checked Audiobookshelf lookups per page, at most

OUTCOME_COPY = {
    Outcome.CREATED: "Asked for the {fmt} of {title}. It appears in {library} once it arrives. That can take a "
                     "while, and not every request can be filled.",
    Outcome.QUEUED: "Asked for the {fmt} of {title}. It appears in {library} once it arrives. That can take a "
                    "while, and not every request can be filled.",
    Outcome.REFUSED: "The {fmt} of {title} could not be asked for. It may already be asked for, or already be in "
                     "{library}.",
    Outcome.NOT_LINKED: "Requests are not set up for your account yet. Open the request website once to sign in, "
                        "then ask again here.",
    Outcome.UNAVAILABLE: "Requests could not be reached right now. Try again later.",
}
GUARD_COPY = {
    "repeat": "You just asked for the {fmt} of {title}.",
    "rate": "You have asked for a lot in the last hour. Try again later.",
    "expired": "This page has expired. Search again to ask for it.",
}


@dataclass(frozen=True)
class AskVM:
    label: str                     # "Ask for the ebook"
    fields: Tuple[Tuple[str, str], ...]   # hidden inputs, signed
    token: str


@dataclass(frozen=True)
class OwnedVM:
    """A format the member already has: "Already in Books", with the way in."""
    library: str                   # "Books"
    href: str                      # Home's title page, or the library's own page for the book
    leaves: bool                   # True: the link opens the library's website (the page says so)


@dataclass(frozen=True)
class MaybeVM:
    """A LIKELY match (same title and author, no shared id): a hint with a link to Home's own search, never a claim."""
    library: str
    href: str                      # /search?q=<title>


@dataclass(frozen=True)
class OfferVM:
    title: str
    line: str                      # "Frank Herbert · 1965 · Dune Chronicles"
    asks: Tuple[AskVM, ...]
    unavailable: str = ""          # why no button: "Only as an audiobook, which you have no library for"
    owned: Tuple[OwnedVM, ...] = ()
    maybe: Tuple[MaybeVM, ...] = ()
    asked_now: Tuple[str, ...] = ()   # formats asked for on the page this redirect came from ("ebook")


@dataclass(frozen=True)
class RequestPageVM:
    mode: str                      # "form" | "results" | "empty" | "invalid" | "unavailable" | "said"
    term: str = ""
    offers: Tuple[OfferVM, ...] = ()
    message: str = ""
    warn: bool = False
    place_href: Optional[str] = None       # the member's own request place ("/requestabook"), for NOT_LINKED
    outcome: str = ""                      # page title prefix
    formats: Tuple[str, ...] = field(default=())
    notice: Optional["RequestPageVM"] = None   # the outcome of the ask that redirected here (a "said" page)


def formats_for(groups) -> Tuple[str, ...]:
    """The formats this member may ask for: those whose library group they hold."""
    return tuple(f for f in ("ebook", "audiobook") if FORMAT_GROUP[f] in groups)


def _line(offer: BookOffer) -> str:
    return " · ".join(p for p in (offer.author, str(offer.year) if offer.year else "", offer.series) if p)


def _fields(offer: BookOffer, book_type: str) -> dict:
    return {"work_id": offer.work_id, "book_type": book_type, "title": offer.title, "author": offer.author}


def build_results(state: str, offers, term: Optional[str], formats, username: str,
                  signer: FormSigner, owned=None, maybe=None, asked=frozenset()) -> RequestPageVM:
    """`owned` / `maybe`: {(work_id, format): OwnedVM / MaybeVM}, already decided by the caller for THIS member (a
    library the member holds, and a permission-checked lookup where the library is per member). An owned format
    gets no ask button."""
    owned, maybe = owned or {}, maybe or {}
    if state == "limited":
        return RequestPageVM("unavailable", (term or "")[:MAX_TERM], message=LIMITED, warn=True, outcome="Not searched",
                             formats=formats)
    shown = (term or "")[:MAX_TERM]
    if term is None:
        return RequestPageVM("form", formats=formats)
    if state == "invalid":
        return RequestPageVM("invalid", shown, message="Type at least two letters of a title or author.",
                             formats=formats)
    if state == "unavailable":
        return RequestPageVM("unavailable", shown, message=OUTCOME_COPY[Outcome.UNAVAILABLE], warn=True,
                             outcome="Unavailable", formats=formats)
    rows = []
    for offer in offers:
        asks, have, hints, now = [], [], [], []
        for fmt in formats:
            if (offer.work_id, fmt) in asked:
                now.append(FORMAT_LABEL[fmt])
                continue
            if (offer.work_id, fmt) in owned:
                have.append(owned[(offer.work_id, fmt)])
                continue
            if (offer.work_id, fmt) in maybe:
                hints.append(maybe[(offer.work_id, fmt)])
            if fmt in offer.formats:
                fields = _fields(offer, fmt)
                asks.append(AskVM(f"Ask for the {FORMAT_LABEL[fmt]}", tuple(sorted(fields.items())),
                                  signer.sign(username, fields)))
        why = ""
        if not asks and not have and not now:
            if not offer.formats:
                why = "No edition found to ask for."
            else:
                only = " or ".join(FORMAT_LABEL[f] for f in offer.formats)
                why = f"Only as an {only}, which is not one of your libraries."
        rows.append(OfferVM(offer.title, _line(offer), tuple(asks), why, tuple(have), tuple(hints), tuple(now)))
    if not rows:
        return RequestPageVM("empty", shown, message="No book matches that. Check the spelling, or try the author.",
                             outcome="No match", formats=formats)
    return RequestPageVM("results", shown, tuple(rows), outcome=f"{len(rows)} found", formats=formats)


def build_said(outcome: Optional[Outcome], guard: Optional[str], fields: dict, place_href: Optional[str],
               formats) -> RequestPageVM:
    fmt = fields.get("book_type", "")
    words = {"fmt": FORMAT_LABEL.get(fmt, "book"), "title": fields.get("title") or "this book",
             "library": LIBRARY_LABEL.get(fmt, "your library")}
    if guard is not None:
        return RequestPageVM("said", message=GUARD_COPY[guard].format(**words), warn=guard != "repeat",
                             outcome="Not sent", formats=formats)
    ok = outcome in (Outcome.CREATED, Outcome.QUEUED)
    return RequestPageVM("said", message=OUTCOME_COPY[outcome].format(**words), warn=not ok,
                         place_href=place_href if outcome is Outcome.NOT_LINKED else None,
                         outcome="Asked for" if ok else "Not asked for", formats=formats)
