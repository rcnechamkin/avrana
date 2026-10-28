"""The page for asking for a comic series (`/request/comics`): view-model and member wording.

Status: proposed, not deployed. No request input is read here (identity.py and forms.py read the term and the form);
this module turns Omnibus's answers (requests/omnibus.py) into what the member reads. One button per series: Omnibus
asks for every issue of it and keeps watching for new ones. "Already in Comics" only from a shared ComicVine id in the
catalogue-id index (Comics is a shared view, so holding the group is the permission).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from ..contract import HANDOFF_BASE, Service
from ..requests.forms import FormSigner
from ..requests.omnibus import MAX_TERM, ComicOffer, Outcome, SeriesState
from .bookrequests import GUARD_COPY, LIMITED, AskVM, OwnedVM

PATH = "/request/comics"
LIBRARY = "Comics"
PLACE = "/requestacomic"            # the member's own request place (catalogue), for NOT_LINKED

OUTCOME_COPY = {
    Outcome.CREATED: "Asked for {title}. Its issues appear in Comics as they arrive, and new ones follow.",
    Outcome.AWAITING: "Asked for {title}. It waits for approval first; then its issues appear in Comics as they "
                      "arrive.",
    Outcome.REFUSED: "{title} could not be asked for. Your account may not be allowed to ask for comics, or this "
                     "kind of series is switched off.",
    Outcome.NOT_LINKED: "Comic requests are not set up for your account yet. Open the request website once to sign "
                        "in, then ask again here.",
    Outcome.UNAVAILABLE: "Comic requests could not be reached right now. Try again later.",
}
SERIES_COPY = {
    SeriesState.AWAITING: ("Waiting for approval", False),
    SeriesState.COMING: ("On its way", False),
    SeriesState.WAITING_RELEASE: ("Waiting for new issues", False),
    SeriesState.STUCK: ("Stuck", False),
    SeriesState.ARRIVED: ("Arrived", True),
}


@dataclass(frozen=True)
class ComicOfferVM:
    title: str
    line: str                      # "Image · 2012 · 66 issues"
    ask: Optional[AskVM] = None
    owned: Optional[OwnedVM] = None
    note: str = ""


@dataclass(frozen=True)
class ComicPageVM:
    mode: str                      # "form" | "results" | "empty" | "invalid" | "unavailable" | "said"
    term: str = ""
    offers: Tuple[ComicOfferVM, ...] = ()
    message: str = ""
    warn: bool = False
    place_href: Optional[str] = None
    outcome: str = ""
    notice: Optional["ComicPageVM"] = None


def series_href(series_id: str) -> str:
    """Komga's own series page for an index hit (the id was validated by owned.py: 13 upper-case alphanumerics)."""
    return HANDOFF_BASE[Service.KOMGA] + "/series/" + series_id


def _line(offer: ComicOffer) -> str:
    issues = f"{offer.issues} issue{'s' if offer.issues != 1 else ''}" if offer.issues else ""
    return " · ".join(p for p in (offer.publisher, str(offer.year) if offer.year else "", issues) if p)


def fields_for(offer: ComicOffer) -> dict:
    return {"cv_id": str(offer.cv_id), "title": offer.name, "year": str(offer.year or ""),
            "publisher": offer.publisher}


def build_results(state: str, offers, term: Optional[str], username: str, signer: FormSigner, owned=None,
                  asked=frozenset()) -> ComicPageVM:
    """`owned`: {cv_id: OwnedVM} from the catalogue-id index."""
    owned = owned or {}
    shown = (term or "")[:MAX_TERM]
    if term is None:
        return ComicPageVM("form")
    if state == "invalid":
        return ComicPageVM("invalid", shown, message="Type at least two letters of a title.")
    if state == "not_linked":
        return not_linked(PLACE)
    if state == "unavailable":
        return ComicPageVM("unavailable", shown, message=OUTCOME_COPY[Outcome.UNAVAILABLE], warn=True,
                           outcome="Unavailable")
    if state == "limited":
        return ComicPageVM("unavailable", shown, message=LIMITED, warn=True, outcome="Not searched")
    rows = []
    for offer in offers:
        have = owned.get(offer.cv_id)
        fields = fields_for(offer)
        if offer.cv_id in asked:
            rows.append(ComicOfferVM(offer.name, _line(offer), owned=have,
                                     note="Asked for just now. Its issues appear in Comics as they arrive."))
        elif have is not None:
            rows.append(ComicOfferVM(offer.name, _line(offer), owned=have,
                                     ask=AskVM("Ask for missing issues", tuple(sorted(fields.items())),
                                               signer.sign(username, fields))))
        else:
            rows.append(ComicOfferVM(offer.name, _line(offer),
                                     ask=AskVM("Ask for this series", tuple(sorted(fields.items())),
                                               signer.sign(username, fields))))
    if not rows:
        return ComicPageVM("empty", shown, message="Nothing matches that. Check the spelling, or try fewer words.",
                           outcome="No match")
    return ComicPageVM("results", shown, tuple(rows), outcome=f"{len(rows)} found")


def build_said(outcome: Optional[Outcome], guard: Optional[str], fields: dict, place_href: Optional[str]) -> ComicPageVM:
    title = fields.get("title") or "This series"
    if guard is not None:
        text = GUARD_COPY[guard].replace("the {fmt} of ", "").format(title=title, fmt="")
        return ComicPageVM("said", message=text, warn=guard != "repeat", outcome="Not sent")
    ok = outcome in (Outcome.CREATED, Outcome.AWAITING)
    return ComicPageVM("said", message=OUTCOME_COPY[outcome].format(title=title), warn=not ok,
                       place_href=place_href if outcome is Outcome.NOT_LINKED else None,
                       outcome="Asked for" if ok else "Not asked for")


def not_linked(place_href: Optional[str]) -> ComicPageVM:
    return ComicPageVM("said", message=OUTCOME_COPY[Outcome.NOT_LINKED], warn=True, place_href=place_href,
                       outcome="Not set up")
