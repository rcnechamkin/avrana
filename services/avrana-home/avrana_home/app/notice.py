"""Operator outage notices (AVR-365): one short banner the owner sets from OliveTin, never from Home.

How it flows. The OliveTin action "Member notice on Home" (services/olivetin, admin ACL only, fixed choices) writes
one small JSON file, `{"id": "<notice id>", "set": "<UTC time>"}`, or removes it to clear. Home reads that file
read-only (`HOME_NOTICE_FILE`; unset = no notices, the default) and shows the matching banner on shell pages.

What the file can and cannot do. It carries an ID and a time, nothing else that reaches a page: the words come from
NOTICES below, in member language, so a file cannot put text, markup, a link, a container name or a health detail on a
member's screen. An unknown ID, malformed JSON, a file over MAX_BYTES or an unreadable file is "no notice" (and one
fixed log reason, never the content). Home has no route that writes the file: the only writer is the OliveTin action.

Scope. A notice about one library (`service`) is shown only to members whose own catalogue tiles open that library
(the places-bar rule: a library a member cannot use is never named). A notice with no service is shown to everyone.

Dismissal. Home reads no cookie and the page script stores nothing (test_route_layer_source, test_web_pwa), so a
notice cannot be hidden for good by a member. The banner is a <details> element: "Hide details" folds it to its one-line
heading on that page, with JS off too. Clearing is the owner's job and needs no member action. Remembering a hide
across pages would need a cookie: an owner decision, not taken here.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .logsafe import app_log, log_event

MAX_BYTES = 512
RECHECK_SECONDS = 5.0                         # stat at most this often; a set or clear shows within this time


@dataclass(frozen=True)
class Notice:
    id: str
    service: Optional[str]                    # adapter service value ("jellyfin"), or None for every member
    heading: str
    body: str


# The only words a notice can show. IDs match services/olivetin/scripts/home-notice.sh and the action's choices
# (tests check all three agree). Plain language: what is affected, what still works, what to do. No app names
# where a member-language name exists, no container or health internals, no promise of a time.
NOTICES = {n.id: n for n in (
    Notice("video-unavailable", "jellyfin", "Movies and TV are down right now",
           "We know, and we're working on it. Your place is saved. Try again later."),
    Notice("audiobooks-unavailable", "audiobookshelf", "Audiobooks are down right now",
           "We know, and we're working on it. Your place is saved. Try again later."),
    Notice("comics-unavailable", "komga", "Comics are down right now",
           "We know, and we're working on it. Your place is saved. Try again later."),
    Notice("books-unavailable", "calibre-web", "Books are down right now",
           "We know, and we're working on it. Try again later."),
    Notice("requests-unavailable", None, "Requests are paused right now",
           "Everything else works. Try your request again later."),
    Notice("slow", None, "Things may be slow right now",
           "Everything still works, but pages and playback may take longer than usual."),
    Notice("maintenance", None, "Maintenance in progress",
           "Some libraries may stop for a few minutes. Your place is saved."),
)}


@dataclass(frozen=True)
class ActiveNotice:
    notice: Notice
    revision: str                             # changes whenever the owner sets a notice again


def revision_of(notice_id: str, set_at: str) -> str:
    return hashlib.sha256(f"{notice_id}\n{set_at}".encode("utf-8")).hexdigest()[:16]


def parse(raw: bytes) -> Optional[ActiveNotice]:
    """The notice a file's bytes name, or None. Never raises on bad input."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > MAX_BYTES:
        return None
    try:
        doc = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    notice_id, set_at = doc.get("id"), doc.get("set")
    if not isinstance(notice_id, str) or not isinstance(set_at, str) or len(set_at) > 64:
        return None
    notice = NOTICES.get(notice_id)
    if notice is None:
        return None
    return ActiveNotice(notice, revision_of(notice_id, set_at))


class NoticeBoard:
    """Reads the operator's notice file. Thread-safe enough for its use: the worst race re-reads the file twice."""

    def __init__(self, path: Optional[Path], clock: Callable[[], float] = time.monotonic):
        self.path = path
        self._clock = clock
        self._checked = float("-inf")
        self._stamp: Optional[tuple] = None
        self._current: Optional[ActiveNotice] = None

    def current(self) -> Optional[ActiveNotice]:
        if self.path is None:
            return None
        now = self._clock()
        if now - self._checked < RECHECK_SECONDS:
            return self._current
        self._checked = now
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            self._stamp, self._current = None, None          # cleared
            return None
        except OSError:
            return self._fail("unreadable")
        stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
        if stamp == self._stamp:
            return self._current
        if st.st_size > MAX_BYTES:
            self._stamp = stamp
            return self._fail("oversized")
        try:
            with open(self.path, "rb") as fh:
                raw = fh.read(MAX_BYTES + 1)
        except FileNotFoundError:
            self._stamp, self._current = None, None
            return None
        except OSError:
            return self._fail("unreadable")
        self._stamp = stamp
        self._current = parse(raw)
        if self._current is None:
            return self._fail("invalid")
        return self._current

    def _fail(self, reason: str) -> None:
        self._current = None
        log_event(app_log, logging.WARNING, "notice_file", reason=reason)
        return None


def visible_notice(active: Optional[ActiveNotice], member_services) -> Optional[ActiveNotice]:
    """The notice this member sees: one for every member, or one about a library their own tiles open."""
    if active is None:
        return None
    if active.notice.service is not None and active.notice.service not in member_services:
        return None
    return active
