"""The page for asking for a film or a show (`/request/watch`): view-model and member wording.

Status: proposed, not deployed. No request input is read here (identity.py reads the term and the form); this module
turns Seerr's answers (requests/seerr.py) into what the member reads. One button per title: a film is asked for
whole, a show for every season it lacks. What Seerr already knows is said plainly: in the library (with the way in,
when this member can open it), already asked for (never by whom), or not available to ask for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from ..requests.forms import FormSigner
from ..requests.seerr import MAX_TERM, MediaState, Outcome, WatchOffer
from .bookrequests import GUARD_COPY, AskVM, OwnedVM

PATH = "/request/watch"
LIBRARY = "Movies and TV"
PLACE = "/requests"                 # the member's own request place (catalogue), for NOT_LINKED
KIND = {"movie": "Film", "tv": "Series"}

OUTCOME_COPY = {
    Outcome.CREATED: "Asked for {title}. It appears in Movies and TV once it arrives.",
    Outcome.AWAITING: "Asked for {title}. It waits for approval first, then appears in Movies and TV once it arrives.",
    Outcome.DUPLICATE: "{title} has already been asked for. It appears in Movies and TV once it arrives.",
    Outcome.REFUSED: "{title} could not be asked for. You may have reached your request limit, or there is nothing "
                     "left of it to ask for.",
    Outcome.NOT_LINKED: "Requests are not set up for your account yet. Open the request website once to sign in, then "
                        "ask again here.",
    Outcome.UNAVAILABLE: "Requests could not be reached right now. Try again later.",
}


@dataclass(frozen=True)
class WatchOfferVM:
    title: str
    line: str                      # "Film · 1999"
    ask: Optional[AskVM] = None
    owned: Optional[OwnedVM] = None
    note: str = ""                 # "Already asked for. …" / "Not available to ask for."


@dataclass(frozen=True)
class WatchPageVM:
    mode: str                      # "form" | "results" | "empty" | "invalid" | "unavailable" | "said"
    term: str = ""
    offers: Tuple[WatchOfferVM, ...] = ()
    message: str = ""
    warn: bool = False
    place_href: Optional[str] = None
    outcome: str = ""


def _line(offer: WatchOffer) -> str:
    return " · ".join(p for p in (KIND[offer.media_type], str(offer.year) if offer.year else "") if p)


def fields_for(offer: WatchOffer) -> dict:
    return {"media_type": offer.media_type, "media_id": str(offer.tmdb_id), "title": offer.title}


def build_results(state: str, offers, term: Optional[str], username: str, signer: FormSigner,
                  owned=None) -> WatchPageVM:
    """`owned`: {(media_type, tmdb_id): OwnedVM}, decided by the caller after this member's own permission-checked
    Jellyfin lookup."""
    owned = owned or {}
    shown = (term or "")[:MAX_TERM]
    if term is None:
        return WatchPageVM("form")
    if state == "invalid":
        return WatchPageVM("invalid", shown, message="Type at least two letters of a title.")
    if state == "unavailable":
        return WatchPageVM("unavailable", shown, message=OUTCOME_COPY[Outcome.UNAVAILABLE], warn=True,
                           outcome="Unavailable")
    rows = []
    for offer in offers:
        have = owned.get((offer.media_type, offer.tmdb_id))
        noun = "film" if offer.media_type == "movie" else "show"

        def ask(label):
            fields = fields_for(offer)
            return AskVM(label, tuple(sorted(fields.items())), signer.sign(username, fields))
        if offer.state is MediaState.NONE:
            rows.append(WatchOfferVM(offer.title, _line(offer), ask=ask(f"Ask for this {noun}")))
        elif offer.state is MediaState.PARTIAL:
            rows.append(WatchOfferVM(offer.title, _line(offer), ask=ask("Ask for the missing seasons"), owned=have,
                                     note="" if have else "Some seasons are already in Movies and TV."))
        elif offer.state is MediaState.AVAILABLE:
            rows.append(WatchOfferVM(offer.title, _line(offer), owned=have,
                                     note="" if have else "Already in Movies and TV."))
        elif offer.state is MediaState.ASKED:
            rows.append(WatchOfferVM(offer.title, _line(offer),
                                     note="Already asked for. It appears in Movies and TV once it arrives."))
        else:
            rows.append(WatchOfferVM(offer.title, _line(offer), note="Not available to ask for."))
    if not rows:
        return WatchPageVM("empty", shown, message="Nothing matches that. Check the spelling, or try fewer words.",
                           outcome="No match")
    return WatchPageVM("results", shown, tuple(rows), outcome=f"{len(rows)} found")


def build_said(outcome: Optional[Outcome], guard: Optional[str], fields: dict, place_href: Optional[str]) -> WatchPageVM:
    words = {"title": fields.get("title") or "This title", "fmt": "film" if fields.get("media_type") == "movie"
             else "show"}
    if guard is not None:
        text = GUARD_COPY[guard].replace("the {fmt} of ", "").format(**words)
        return WatchPageVM("said", message=text, warn=guard != "repeat", outcome="Not sent")
    ok = outcome in (Outcome.CREATED, Outcome.AWAITING, Outcome.DUPLICATE)
    return WatchPageVM("said", message=OUTCOME_COPY[outcome].format(**words), warn=not ok,
                       place_href=place_href if outcome is Outcome.NOT_LINKED else None,
                       outcome="Asked for" if ok else "Not asked for")


def not_linked(place_href: Optional[str]) -> WatchPageVM:
    """Shown instead of the search when the member has no Seerr account Home may act as."""
    return WatchPageVM("said", message=OUTCOME_COPY[Outcome.NOT_LINKED], warn=True, place_href=place_href,
                       outcome="Not set up")
