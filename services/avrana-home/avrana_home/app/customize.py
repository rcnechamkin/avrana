"""Customize (Media 2.0 HOME-01/02) and the device-setup card (ME-02): the posted fields, their checks, the editor's
display data and the 303s. Pure functions; main.py reads the form (forms.py) and the record (memberstore.py).

  * One Home per account (HOME-02, owner 2026-10-28): the place Home starts on, the places shown, the order of its three
    sections. No device or browser override exists. A save is checked against the member's OWN places (the catalogue
    after the access filter), names the version it was drawn from, and replaces the record as a whole or not at all.
  * Hiding a place is presentation only: it never closes a library, and the copy never calls it a restriction.
  * The setup card's "hide" is presentation only too: it records no device, no guide progress and calls nothing
    upstream. Setup stays one row away under Devices, and the card can be shown again.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ..memberstore import HOME_ALL, HOME_PLACES, HOME_SHELVES

ROUTE = "/me/home"
SETUP_ROUTE = "/me/setup"
SETUP_CARD = 1              # the card's version; a member who hid this version doesn't see it again
SHOWN = "show_"
FIELDS = frozenset({"t", "v", "start", "from", "o1", "o2", "o3"} | {SHOWN + k for k in HOME_PLACES})
SETUP_FIELDS = frozenset({"t", "do"})
RESULTS = ("saved", "conflict", "start_hidden", "none_shown", "invalid", "unavailable", "expired")
SETUP_RESULTS = ("setup_hidden", "setup_shown", "setup_unsaved", "expired")
SHELF_LABELS = {"continue": "Continue", "released": "New Releases", "new": "New to Avrana"}


@dataclass(frozen=True)
class PlaceRow:
    key: str                 # the catalogue place path ("watch")
    label: object            # the catalogue's text (Trusted)
    shown: bool


@dataclass(frozen=True)
class EditorVM:
    places: Tuple[PlaceRow, ...]       # empty for a member with fewer than two places (nothing to choose)
    start: str                         # "all" or one of `places`
    shelves: Tuple[Tuple[str, str], ...]   # (key, label) in the saved order
    version: int


def editor(prefs, places) -> EditorVM:
    """The form's starting values: the saved record as it applies to the member's places now (effective_home's
    rules), or Home's defaults. `places` are the member's library places (key, label) in catalogue order."""
    keys = [k for k, _l in places]
    hidden = {h for h in prefs.hidden if h in keys}
    if hidden >= set(keys):
        hidden = set()
    start = prefs.start if prefs.start in keys and prefs.start not in hidden else HOME_ALL
    order = prefs.order if sorted(prefs.order) == sorted(HOME_SHELVES) else HOME_SHELVES
    rows = tuple(PlaceRow(k, label, k not in hidden) for k, label in places) if len(places) > 1 else ()
    return EditorVM(rows, start if rows else HOME_ALL, tuple((k, SHELF_LABELS[k]) for k in order), prefs.version)


def parse(form: Dict[str, str], keys) -> Tuple[Optional[str], str, Tuple[str, ...], Tuple[str, ...]]:
    """(problem, start, hidden, order) from a posted editor. `problem` is None for a good form, else a result id.
    `keys` are the member's own library places: a field for any other place is refused, never ignored."""
    keys = [k for k in keys if k in HOME_PLACES]
    shown_fields = {f[len(SHOWN):] for f in form if f.startswith(SHOWN)}
    if not shown_fields <= set(keys) or any(form[SHOWN + k] != "on" for k in shown_fields):
        return "invalid", HOME_ALL, (), HOME_SHELVES
    order = tuple(form.get(f"o{i}", "") for i in (1, 2, 3))
    if sorted(order) != sorted(HOME_SHELVES):
        return "invalid", HOME_ALL, (), HOME_SHELVES
    start = form.get("start", HOME_ALL)
    if len(keys) < 2:                      # nothing to choose: Home is the one place
        return None, HOME_ALL, (), order
    if start != HOME_ALL and start not in keys:
        return "invalid", HOME_ALL, (), HOME_SHELVES
    hidden = tuple(k for k in keys if k not in shown_fields)
    if len(hidden) == len(keys):
        return "none_shown", HOME_ALL, (), HOME_SHELVES
    if start in hidden:
        return "start_hidden", HOME_ALL, (), HOME_SHELVES
    return None, start, hidden, order


def result_headers(outcome: str, allowed, back_home: bool) -> Dict[str, str]:
    """The 303 after a save (post/redirect/get). Saved from Home's Customize: back to Home, which shows the result.
    Otherwise the editor again with a fixed result id. `outcome` is a fixed id from `allowed`."""
    if outcome not in allowed:
        raise ValueError("not an outcome")
    if outcome == "saved" and back_home:
        return {"Location": "/"}
    return {"Location": f"{ROUTE}?r={outcome}" + ("&from=home" if back_home else "")}


def setup_result_headers(outcome: str, allowed) -> Dict[str, str]:
    """The 303 back to Me after hiding or showing the setup suggestion. `outcome` is a fixed id from `allowed`."""
    if outcome not in allowed:
        raise ValueError("not an outcome")
    return {"Location": f"/me?r={outcome}"}
