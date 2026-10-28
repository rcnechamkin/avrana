"""The page for asking for a film or a show (`/request/watch`): view-model and member wording.

Status: proposed, not deployed. No request input is read here (identity.py reads the term and the form); this module
turns Seerr's answers (requests/seerr.py) into what the member reads. One button per title: a film is asked for
whole, a show for every season it lacks. What Seerr already knows is said plainly: in the library (with the way in,
when this member can open it), already asked for (never by whom), or not available to ask for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import urlencode

from ..requests.forms import FormSigner
from ..requests.seerr import CancelOutcome as WatchCancel, MAX_TERM, MediaState, Outcome, RequestState as WatchState, \
    WatchOffer
from .bookrequests import GUARD_COPY, LIMITED, AskVM, OwnedVM

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
    choose_href: Optional[str] = None   # a show: the season picker


@dataclass(frozen=True)
class WatchPageVM:
    mode: str                      # "form" | "results" | "empty" | "invalid" | "unavailable" | "said"
    term: str = ""
    offers: Tuple[WatchOfferVM, ...] = ()
    message: str = ""
    warn: bool = False
    place_href: Optional[str] = None
    outcome: str = ""
    notice: Optional["WatchPageVM"] = None    # the outcome of the ask that redirected here (a "said" page)
    show: Optional["ShowVM"] = None           # mode "show": the season picker


@dataclass(frozen=True)
class SeasonVM:
    number: int
    label: str                     # "Season 2 · 10 episodes"
    field: Optional[str] = None    # "season_2" when it may be asked for, else None
    note: str = ""                 # "In Movies and TV" / "Already asked for" / "Partly in Movies and TV"


@dataclass(frozen=True)
class ShowVM:
    title: str
    line: str
    seasons: Tuple[SeasonVM, ...]
    ask: Optional[AskVM]           # the signed show fields; None when nothing is left to ask for
    back_href: str                 # the search the member came from


def _line(offer: WatchOffer) -> str:
    return " · ".join(p for p in (KIND[offer.media_type], str(offer.year) if offer.year else "") if p)


def fields_for(offer: WatchOffer) -> dict:
    return {"media_type": offer.media_type, "media_id": str(offer.tmdb_id), "title": offer.title}


def choose_href(tmdb_id: int, term: Optional[str]) -> str:
    query = {"show": str(tmdb_id)}
    if term:
        query["q"] = term[:MAX_TERM]
    return PATH + "?" + urlencode(query)


SEASON_NOTE = {MediaState.AVAILABLE: "In Movies and TV", MediaState.ASKED: "Already asked for",
               MediaState.PARTIAL: "Partly in Movies and TV", MediaState.BLOCKED: "Not available to ask for"}


def build_show(detail, term: Optional[str], username: str, signer: FormSigner) -> WatchPageVM:
    """The season picker for one show: a checkbox for each season that may still be asked for (none, or partly
    there); the rest say why not."""
    seasons = []
    for s in detail.seasons:
        episodes = f"{s.episodes} episode{'s' if s.episodes != 1 else ''}" if s.episodes else ""
        label = " · ".join(p for p in (f"Season {s.number}", episodes) if p)
        open_ = s.state in (MediaState.NONE, MediaState.PARTIAL)
        seasons.append(SeasonVM(s.number, label, f"season_{s.number}" if open_ else None,
                                SEASON_NOTE.get(s.state, "") if s.state is not MediaState.NONE else ""))
    fields = {"media_type": "tv", "media_id": str(detail.tmdb_id), "title": detail.title}
    ask = AskVM("Ask for the chosen seasons", tuple(sorted(fields.items())), signer.sign(username, fields)) \
        if any(s.field for s in seasons) else None
    back = PATH + ("?" + urlencode({"q": term[:MAX_TERM]}) if term else "")
    line = " · ".join(p for p in ("Series", str(detail.year) if detail.year else "") if p)
    show = ShowVM(detail.title, line, tuple(seasons), ask, back)
    return WatchPageVM("show", (term or "")[:MAX_TERM], outcome=detail.title, show=show)


def build_results(state: str, offers, term: Optional[str], username: str, signer: FormSigner,
                  owned=None, asked=frozenset()) -> WatchPageVM:
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
    if state == "limited":
        return WatchPageVM("unavailable", shown, message=LIMITED, warn=True, outcome="Not searched")
    rows = []
    for offer in offers:
        have = owned.get((offer.media_type, offer.tmdb_id))
        noun = "film" if offer.media_type == "movie" else "show"

        def ask(label):
            fields = fields_for(offer)
            return AskVM(label, tuple(sorted(fields.items())), signer.sign(username, fields))
        if (offer.media_type, offer.tmdb_id) in asked:
            rows.append(WatchOfferVM(offer.title, _line(offer), owned=have,
                                     note="Asked for just now. It appears in Movies and TV once it arrives."))
        elif offer.state is MediaState.NONE:
            rows.append(WatchOfferVM(offer.title, _line(offer), ask=ask(f"Ask for this {noun}" if noun == "film"
                                                                         else "Ask for every season"),
                                     choose_href=choose_href(offer.tmdb_id, term) if noun == "show" else None))
        elif offer.state is MediaState.PARTIAL:
            rows.append(WatchOfferVM(offer.title, _line(offer), ask=ask("Ask for the missing seasons"), owned=have,
                                     note="" if have else "Some seasons are already in Movies and TV.",
                                     choose_href=choose_href(offer.tmdb_id, term)))
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
    if guard == "no_season":
        return WatchPageVM("said", message="Choose at least one season to ask for.", warn=True, outcome="Not sent")
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
