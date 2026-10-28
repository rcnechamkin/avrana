"""Which outside identifiers are already in a library: the catalogue-id index (read-only).

Status: proposed, not deployed. The file is written on the host by tools/build_catalogue_index.py (docs/design/
API-CAPS-AND-MATCHING.md section 2) and mounted read-only; Home never writes it. It holds catalogue identifiers
only: `"hardcover:123" -> "45"` (a Calibre book id), `"isbn:978…"`, `"asin:…"`, `"comicvine:…"`, plus folded
title keys for a LIKELY tier that is shown as a hint, never as owned.

An index hit says a file exists; it never says a member may open it. Callers show "Already in <library>" only for
a library the member holds (and, for a per-member library, after the adapter's own permission-checked lookup).

Re-read at most every RECHECK_SECONDS when the file changes. Missing, oversized or malformed: an empty index (no
claims at all), logged with a fixed reason. `title_key` and `isbn13` must agree with the builder's copies
(webtests/test_owned_index.py checks it).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

from ..contract import Service, valid_upstream_id

RECHECK_SECONDS = 60.0
MAX_BYTES = 8 * 1024 * 1024
KINDS = {"ebook": Service.CALIBRE_WEB, "audiobook": Service.AUDIOBOOKSHELF, "comic": Service.KOMGA}
KEY = re.compile(r"(?:hardcover:[0-9]{1,12}|isbn:97[89][0-9]{10}|asin:[0-9A-Z]{10}|comicvine:[0-9]{1,10}"
                 r"|t:[a-z0-9 ]{2,200}\|[a-z0-9]{1,60})")
log = logging.getLogger("avrana.home")


def isbn13(raw) -> Optional[str]:
    digits = re.sub(r"[^0-9Xx]", "", str(raw or "")).upper()
    if len(digits) == 10 and digits[:9].isdigit():
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(digits))
        if total % 11:
            return None
        digits = "978" + digits[:9]
        return digits + str((10 - sum((3 if i % 2 else 1) * int(c) for i, c in enumerate(digits)) % 10) % 10)
    if len(digits) == 13 and digits.isdigit():
        check = (10 - sum((3 if i % 2 else 1) * int(c) for i, c in enumerate(digits[:12])) % 10) % 10
        return digits if check == int(digits[12]) else None
    return None


_ARTICLES = re.compile(r"^(?:the|a|an) ")


def title_key(title, author) -> Optional[str]:
    def fold(text):
        text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
        return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())
    main = fold(re.split(r"[:(\[]", str(title or ""), 1)[0])
    main = _ARTICLES.sub("", main)
    first_author = re.split(r"[,;&]| and ", str(author or ""), 1)[0]
    surname = fold(first_author).split(" ")[-1] if fold(first_author) else ""
    if len(main) < 2 or not surname:
        return None
    return f"t:{main}|{surname}"


class OwnedIndex:
    def __init__(self, path: Optional[Path], clock: Callable[[], float] = time.monotonic):
        self.path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._checked = float("-inf")
        self._stamp: Optional[tuple] = None
        self._data: Dict[str, Dict[str, str]] = {}

    def exact(self, kind: str, keys: Iterable[str]) -> Optional[str]:
        """The upstream id of the first key found for this kind, or None."""
        table = self._tables().get(kind, {})
        return next((table[k] for k in keys if k in table), None)

    def likely(self, kind: str, key: Optional[str]) -> Optional[str]:
        return self._tables().get(kind + "_likely", {}).get(key) if key else None

    def _tables(self) -> Dict[str, Dict[str, str]]:
        if self.path is None:
            return {}
        with self._lock:
            now = self._clock()
            if now - self._checked < RECHECK_SECONDS:
                return self._data
            self._checked = now
            try:
                st = os.stat(self.path)
                stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
                if stamp == self._stamp:
                    return self._data
                self._stamp = stamp
                if st.st_size > MAX_BYTES:
                    return self._fail("oversized")
                with open(self.path, "rb") as fh:
                    raw = json.loads(fh.read(MAX_BYTES + 1).decode("utf-8"))
            except FileNotFoundError:
                self._stamp, self._data = None, {}
                return self._data
            except (OSError, ValueError, UnicodeDecodeError, RecursionError):
                return self._fail("invalid")
            self._data = _validated(raw)
            if not any(self._data.values()):
                return self._fail("empty")
            return self._data

    def _fail(self, reason: str) -> Dict[str, Dict[str, str]]:
        log.info(json.dumps({"event": "owned_index", "reason": reason}))
        self._data = {}
        return self._data


def _validated(raw) -> Dict[str, Dict[str, str]]:
    """Only well-formed keys whose value is a valid id for that library survive; anything else is dropped."""
    if not isinstance(raw, dict) or raw.get("version") != 1:
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for kind, service in KINDS.items():
        for table in (kind, kind + "_likely"):
            entries = raw.get(table)
            if not isinstance(entries, dict):
                continue
            out[table] = {k: v for k, v in entries.items()
                          if isinstance(k, str) and isinstance(v, str) and KEY.fullmatch(k)
                          and _valid(service, v)}
    return out


def _valid(service: Service, upstream_id: str) -> bool:
    if service is Service.KOMGA:            # the comic table holds SERIES ids (same alphabet as book ids)
        return bool(re.fullmatch(r"[0-9A-Z]{13}", upstream_id))
    return valid_upstream_id(service, upstream_id)
