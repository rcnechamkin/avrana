"""The "If something doesn't open" help topic (Home 2.0, AVR-479). Pure functions, standard library only.

Served at `/help/trouble` only when the Home shell is on (HOME_SECTIONS=on and a verified member); with the shell
off the path is unknown, exactly as on today's portal, so portal parity is unchanged.

What it may say is limited to what Avrana Home actually does and what the repository records about each library:
  * a Home card opens the library's own website at the item (contract.HANDOFF_BASE); Avrana never starts
    playback, never opens a phone or TV app at the item, and never moves progress between libraries;
  * how each library signs a member in is the portal's HELP table, taken from the live configuration
    (services/avrana-portal/portal.py): Movies and TV and Books by Avrana username and password, Audiobooks and
    Comics by an Avrana sign-in button;
  * device behaviour that has not been tried on a real device is worded as "may", never as a promise
    (docs/design/CONTINUE-AND-HANDOFF.md lists the physical tests the owner still has to run).

Only libraries the member can use are ever named: every library line is gated on the same Authentik group as
the library itself (contract.REQUIRED_GROUP). All text is plain; the template autoescapes it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from ..contract import REQUIRED_GROUP, Service

SLUG = "trouble"
ROUTE = "/help/" + SLUG
TITLE = "If something doesn't open"
SUMMARY = "Sign-in, missing items and getting back"
WHO = "the person who invited you"

# (service, library label, place path, how that library signs a member in). Labels are Home's member language
# (viewmodel.SERVICE_LABEL); sign-in wording is the portal HELP table's.
_LIBRARIES = (
    (Service.JELLYFIN, "Movies and TV", "/watch", "your Avrana username and password"),
    (Service.AUDIOBOOKSHELF, "Audiobooks", "/listen", "the Avrana sign-in button"),
    (Service.KOMGA, "Comics", "/comics", "the Avrana sign-in button"),
    (Service.CALIBRE_WEB, "Books", "/books", "your Avrana username and password"),
)


@dataclass(frozen=True)
class TroubleSection:
    anchor: str                              # fragment id, fixed text
    heading: str
    paragraphs: Tuple[str, ...]
    items: Tuple[str, ...] = ()              # a list, one line per library the member can use
    links: Tuple[Tuple[str, str], ...] = ()  # (text, same-origin path)


@dataclass(frozen=True)
class TroubleVM:
    title: str
    sections: Tuple[TroubleSection, ...]


def _held(groups):
    return [(svc, label, place, sign_in) for svc, label, place, sign_in in _LIBRARIES
            if REQUIRED_GROUP[svc] in groups]


def build_trouble(groups) -> TroubleVM:
    held = _held(groups)
    sign_in = tuple(f"{label}: sign in with {how}." for _s, label, _p, how in held)
    places = tuple((f"Open {label}", place) for _s, label, place, _h in held)
    no_progress = [label.lower() for svc, label, _p, _h in held if svc in (Service.KOMGA, Service.CALIBRE_WEB)]
    open_only = (f"{' and '.join(no_progress).capitalize()} always say Open." if no_progress else "")
    sections = [
        TroubleSection("what", "What happens when you choose an item", (
            "Avrana opens the library's own website at that item. It does not start anything for you: "
            "start it in the library.",
            ("Resume means the library saved where you stopped. Open means there is no saved place Avrana "
             "can trust, so the library opens at the item's page. " + open_only).strip(),
            "Progress belongs to each library. Avrana shows it and does not copy it between libraries.",
        )),
        TroubleSection("sign-in", "If you are asked to sign in", (
            "Each library is a separate website with its own sign-in. It may remember you, or ask again "
            "if you have not used it for a while or signed in on another device.",
            "After signing in, the library may show its start page instead of the item. Come back to Avrana "
            "and choose the item again.",
        ), items=sign_in),
        TroubleSection("app", "If it opens in the browser instead of the app", (
            "Avrana's links open the library's website. They cannot open a phone or TV app at the item.",
            "iPhone and iPad: the item opens in Safari. If you added Avrana to your Home Screen, it may open "
            "in its own window; close that window to come back.",
            "Android: the item opens in your browser.",
            "Television and other apps: Avrana's links do not reach them. Find the item by name in the app.",
        ), links=(("Apps and setup", "/help"),)),
        TroubleSection("missing", "If the item is missing or cannot be found", (
            "It may have been removed, renamed or moved in the library. Home can take up to two minutes to "
            "catch up; reload it then.",
            f"If it stays missing, ask {WHO}.",
        )),
        TroubleSection("unavailable", "If a library says it is unavailable", (
            "Avrana could not reach that library just now. Your other libraries keep working. This usually "
            "passes within a minute: choose Try again on Home.",
            "You can still try opening the library itself from its place at the top of the page.",
            f"If it keeps happening, tell {WHO}.",
        ), links=places),
        TroubleSection("not-set-up", "If a library says it is not set up for your account", (
            "Your account in that library is not linked to your Avrana account yet. There is nothing to "
            f"change on your side: ask {WHO} to link it.",
        )),
        TroubleSection("back", "Getting back to Avrana", (
            "Use your browser's back button, or choose AVRANA at the top of any Avrana page.",
            "If the library opened in a separate window or tab, close it. If you opened Avrana from your Home "
            "Screen, you can also open it again from its icon.",
        ), links=(("Back to home", "/"),)),
    ]
    if not held:
        # A member with no library: nothing above is about anything they have. Say only what is true.
        sections = [TroubleSection("none", "Nothing is set up yet", (
            f"No library is shared with this account yet. Ask {WHO}.",
        ), links=(("Back to home", "/"),))]
    return TroubleVM(TITLE, tuple(sections))
