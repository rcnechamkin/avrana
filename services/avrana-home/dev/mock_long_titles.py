#!/usr/bin/env python3
"""Long-title overlay for the loopback mocks. SYNTHETIC, INVENTED TITLES ONLY. Development and review use.

Real catalogues have long titles: a film with a subtitle and an edition, an audiobook with its series in the
title, an episode with a long name in a series with a long name. The repository's fixtures are short
("Synthetic Film Two"), so a narrow card never shows the wrapping problem. `apply(mocks)` renames items in
the mocks' ANSWERS (the fixture files and the adapter tests' fakes are untouched) and adds one in-progress
episode to the synthetic member-b's Continue, so the static export and a dev run look like a real shelf.

Every title is invented and keeps the word "Synthetic", so the export's prepared search still finds it.
No title here is, or is taken from, any real library.
"""
from __future__ import annotations

import copy

# fixture title (as served) -> invented long title. Plain text only: no quote, ampersand or angle bracket,
# so one replacement is valid in JSON and in OPDS XML alike.
RENAME = {
    "Synthetic Film Two": "Synthetic Film Two: The Long Way Round to the Far Lighthouse (Extended Edition)",
    "Synthetic Film Four": "Synthetic Film Four, Part Two: Return of the Very Patient Cartographer",
    "Synthetic Audiobook Four": "Synthetic Audiobook Four: The Lantern Keepers, Book Three of the Northern Harbour Chronicles",
    "Synthetic Author": "Synthetic Author Name and Another Invented Co-Author",
    "Synthetic Saga #1": "Synthetic Saga of the Unhurried Archipelago, Book 1",
    "Synthetic Teen One": "Synthetic Teen One: Volume 12, The Clocktower Summer Special",
    "Synthetic Book Three": "Synthetic Book Three: A Field Guide to Imaginary Rivers and the People Who Map Them",
}
# One in-progress episode for member-b (Jellyfin resume): a long series name and a long episode name.
EXTRA_RESUME = {
    "member_b": [{
        "Id": "bbbb0000000000000000000000000e10",
        "Name": "Synthetic Episode: The One Where Everyone Finally Reads the Instructions",
        "Type": "Episode",
        "SeriesName": "Synthetic Series With a Remarkably Long Name",
        "ParentIndexNumber": 3,
        "IndexNumber": 10,
        "RunTimeTicks": 26400000000,
        "UserData": {"PlaybackPositionTicks": 9000000000, "PlayedPercentage": 34.0, "Played": False,
                     "ItemId": "bbbb0000000000000000000000000e10"},
        "ImageTags": {"Primary": "synthtagbe10"},
    }],
}


def _rename_bytes(body: bytes) -> bytes:
    for old, new in RENAME.items():
        for a, b in (('"', '"'), (">", "<")):
            body = body.replace(f"{a}{old}{b}".encode(), f"{a}{new}{b}".encode())
    return body


def _rename_obj(obj):
    if isinstance(obj, dict):
        return {k: _rename_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rename_obj(v) for v in obj]
    if isinstance(obj, str):
        return RENAME.get(obj, obj)
    return obj


def _jellyfin(mock) -> None:
    plain = mock._per_user

    def per_user(kind, name):
        doc = copy.deepcopy(plain(kind, name))
        if kind == "resume" and name in EXTRA_RESUME and isinstance(doc, dict):
            doc["Items"] = list(EXTRA_RESUME[name]) + list(doc.get("Items", []))
            doc["TotalRecordCount"] = len(doc["Items"])
        return _rename_obj(doc)
    mock._per_user = per_user


def _fake_backed(mock) -> None:
    plain = mock.fake.handle

    def handle(method, path, query):
        status, body, ctype = plain(method, path, query)
        return status, (_rename_bytes(body) if isinstance(body, bytes) else body), ctype
    mock.fake.handle = handle


def apply(mocks) -> None:
    """Apply the overlay to built mocks: a dict or iterable of MockJellyfin / MockAudiobookshelf-family."""
    for mock in (mocks.values() if isinstance(mocks, dict) else mocks):
        if mock is None:
            continue
        if hasattr(mock, "fake"):
            _fake_backed(mock)
        elif hasattr(mock, "_per_user"):
            _jellyfin(mock)
