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

from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

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
