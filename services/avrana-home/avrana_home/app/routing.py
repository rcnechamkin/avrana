"""Portal-parity routing decisions. Pure functions, standard library only.

`decide` reproduces the decision logic of `services/avrana-portal/portal.py::Handler.do_GET`
for GET and HEAD, in the same order, from the same tables (via the catalogue seam):

  /healthz  ->  200 (no identity looked at)
  /  /account  /help  /help/<slug>  ->  pages (help topics gated on their group)
  choosers (/read /request)          ->  sub-page of the permitted members, else 404
  service paths                      ->  307 to a FIXED table target, the watch interstitial (200),
                                         or 404 when the group is missing
  anything else                      ->  404 (the same body as a denied route)

Nothing here reads a request: it takes the path text and the viewer's groups. Redirect targets
come from the catalogue's fixed table. A denied route and an unknown route return the identical
`not_found` decision, so a withheld service is indistinguishable from one that never existed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

from ..contract import Service, valid_upstream_id
from . import recovery
from .catalogue import Catalogue, Trusted

NOT_FOUND_LABEL = "not_found"


@dataclass(frozen=True)
class Decision:
    label: str                          # route TEMPLATE for logs, never the raw path
    status: int
    template: str = ""
    context: Mapping = field(default_factory=dict)
    location: Optional[str] = None
    plain: Optional[str] = None         # text/plain body (healthz)


@dataclass(frozen=True)
class AccountFacts:
    """What /account may print: from the verified principal only."""
    name: str = ""
    username: str = ""
    email: str = ""


def normalise_target(raw_target: str) -> str:
    """The portal's route normalisation, byte for byte: Python 3.12's http.server first collapses
    leading slashes, then the portal drops the query and fragment and trailing slashes. The path
    is NOT percent-decoded and is case-sensitive."""
    target = raw_target
    if target.startswith("//"):
        target = "/" + target.lstrip("/")
    return target.split("?", 1)[0].split("#", 1)[0].rstrip("/") or "/"


def not_found() -> Decision:
    return Decision(NOT_FOUND_LABEL, 404, "not_found.html")


def search_decision(page) -> Decision:
    """The decision for GET /search once the route layer has a verified member (the route itself is gated on
    HOME_SECTIONS in main.py, so with sections off the path is unknown and `decide` answers 404). `page` is the
    view-model; the label is the route template, never the typed term."""
    return Decision("/search", 200, "search.html", {"page": page})


TITLE_LABEL = "/title/{service}/{id}"
_TITLE = re.compile(r"/title/([a-z][a-z-]{1,23})/([A-Za-z0-9_-]{1,64})")


def parse_title_route(route: str) -> Optional[Tuple[str, str]]:
    """(service, upstream id) from a normalised route `/title/<service>/<id>`, or None. The route is NOT
    percent-decoded (normalise_target), so `%2f`, `..`, NUL or CRLF can never become a separator or reach an
    adapter; the id must also match the contract's own pattern for that service (`valid_upstream_id`)."""
    m = _TITLE.fullmatch(route)
    if m is None:
        return None
    try:
        service = Service(m.group(1))
    except ValueError:
        return None
    return (service.value, m.group(2)) if valid_upstream_id(service, m.group(2)) else None


def title_decision(page) -> Decision:
    """A title page (AVR-384). `page` is a TitleVM; unavailable is a calm 503, everything else 200. A title the
    member may not see is never a decision here: the caller answers `not_found()` (portal parity, never 403)."""
    return Decision(TITLE_LABEL, 503 if page.state == "unavailable" else 200, "title.html", {"page": page})


# What a chooser page says above its places, shown only with the Home shell (HOME_SECTIONS on). Plain text, no
# library named: the tiles below already show only the places this member can use (AVR-430).
CHOOSER_INTRO = {
    "read": ("Each place below opens a separate library website with its own sign-in.",),
    "request": ("Ask for something that is missing from a library. Each place below opens a separate request "
                "website, where you sign in and search for the title.",
                "Asking does not add it straight away, and not every request can be filled."),
}


def chooser_intro(path: str):
    return CHOOSER_INTRO.get(path, ())


ME_ROUTE = "/me"


def me_decision(page) -> Decision:
    """GET /me, the Me hub (Concept K, AVR-719), once the route layer knows the shell is on and there is a verified
    member (main.py); otherwise the path is unknown and `decide` answers 404, as the portal does. `page` is a MeVM."""
    return Decision(ME_ROUTE, 200, "me.html", {"me": page})


def trouble_decision(groups) -> Decision:
    """GET /help/trouble once the route layer knows the shell is on (main.py); otherwise the path is unknown
    and `decide` answers 404, as the portal does. The content names only libraries this member can use."""
    return Decision("/help/trouble", 200, "help_trouble.html", {"trouble": recovery.build_trouble(groups)})


def decide(route: str, groups, cat: Catalogue, facts: Optional[AccountFacts] = None) -> Decision:
    if route == "/healthz":
        return Decision("/healthz", 200, plain="ok")

    if route == "/":
        tiles = []
        for path in cat.home_order:
            ch = cat.chooser(path)
            if ch:
                if cat.chooser_members(ch, groups):
                    tiles.append((ch.path, ch.label, cat.chooser_subtitle(ch, groups)))
                continue
            if path == "help":
                tiles.append(("help", Trusted("Help"), Trusted("Apps &amp; setup guides")))
                continue
            svc = cat.service(path)
            if svc and svc.allows(groups):
                label, desc = cat.service_copy(svc, groups)
                tiles.append((svc.path, label, desc))
        return Decision("/", 200, "home.html", {"tiles": tiles})

    if route == "/account":
        facts = facts or AccountFacts()
        rows = []
        if facts.name:
            rows.append(("Name", facts.name))
        if facts.username:
            rows.append(("Username", facts.username))
        if facts.email:
            rows.append(("Email", facts.email))
        if not rows:
            rows.append(("Signed in", "yes"))
        mine = [cat.service_copy(s, groups)[0] for s in cat.permitted(groups)]
        return Decision("/account", 200, "account.html", {
            "facts": rows, "access": mine, "account_url": cat.account_url,
            "signout_url": cat.signout_url})

    if route == "/help":
        tiles = [(f"help/{t.slug}", t.label, Trusted("Apps and setup")) for t in cat.help_permitted(groups)]
        return Decision("/help", 200, "help_index.html", {"tiles": tiles})

    if route.startswith("/help/"):
        topic = cat.help_by_slug(route[len("/help/"):])
        if topic is None or topic.group not in groups:
            return not_found()
        return Decision("/help/{slug}", 200, "help_topic.html", {"topic": topic})

    slug = cat.aliases.get(route[1:], route[1:])

    ch = cat.chooser(slug)
    if ch:
        members = cat.chooser_members(ch, groups)
        if not members:
            return not_found()
        tiles = [(m.path, *cat.service_copy(m, groups)) for m in members]
        return Decision("/{chooser}", 200, "chooser.html", {"chooser": ch, "tiles": tiles})

    svc = cat.service(slug)
    if svc is not None and svc.allows(groups):
        warn = cat.interstitials.get(svc.path)
        if warn:
            return Decision("/{service}", 200, "interstitial.html", {
                "svc": svc, "warning": warn[0], "help_path": warn[1]})
        return Decision("/{service}", 307, location=cat.redirect_target(svc))

    return not_found()
