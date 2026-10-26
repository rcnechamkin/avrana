"""Media identity: external identifiers an upstream already holds, validated, and the rule for "the same title".

Status: proposed (R2-B, AVR-747), not deployed. Standard library only. Rules in docs/design/MEDIA-IDENTITY.md.

  * Only identifiers the upstream itself returned are used. Nothing here calls TMDB, TVDB, IMDb, Open Library
    or any other outside service, and nothing is stored beyond the item it came with.
  * Every value is validated against a strict pattern (ISBNs by check digit); anything else is dropped, never
    repaired. ISBN-10 is rewritten as its ISBN-13, the one normalisation that is exact.
  * Work-level schemes (`tmdb`, `imdb`, `tvdb`) identify a movie, a series or an episode, so their keys carry the
    kind: TMDB uses separate number spaces for movies and TV, and an episode is not its series. Edition-level
    schemes (`isbn13`, `asin`) identify one published edition: an ebook and its audiobook never share one.
  * Two items are linked only by an exact key. A key that two different items of one service both carry is
    ambiguous and links nothing. Titles, authors and years never link anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

WORK_SCHEMES = ("tmdb", "imdb", "tvdb")
EDITION_SCHEMES = ("isbn13", "asin")
SCHEMES = WORK_SCHEMES + EDITION_SCHEMES

_NUMERIC_ID = re.compile(r"[1-9][0-9]{0,9}")
_IMDB = re.compile(r"tt[0-9]{7,10}")
_ASIN = re.compile(r"[A-Z0-9]{10}")
_ISBN_SEPARATORS = re.compile(r"[\s-]")
_ISBN10 = re.compile(r"[0-9]{9}[0-9X]")
_ISBN13 = re.compile(r"97[89][0-9]{10}")
MAX_RAW = 32                       # longer input is refused before any pattern runs


def _isbn13_check(first12: str) -> str:
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def isbn13(value: Any) -> Optional[str]:
    """The ISBN-13 for a valid ISBN-10 or ISBN-13 (hyphens and spaces allowed), else None."""
    if not isinstance(value, str) or len(value) > MAX_RAW:
        return None
    digits = _ISBN_SEPARATORS.sub("", value).upper()
    if _ISBN13.fullmatch(digits):
        return digits if _isbn13_check(digits[:12]) == digits[12] else None
    if _ISBN10.fullmatch(digits):
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(digits))
        if total % 11 != 0:
            return None
        body = "978" + digits[:9]
        return body + _isbn13_check(body)
    return None


def _clean(scheme: str, value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value or len(value) > MAX_RAW:
        return None
    value = value.strip()
    if scheme in ("tmdb", "tvdb"):
        return value if _NUMERIC_ID.fullmatch(value) else None
    if scheme == "imdb":
        return value if _IMDB.fullmatch(value) else None
    if scheme == "asin":
        # A valid ISBN-10 given as an ASIN was already moved to isbn13 by external_ids().
        return value if _ASIN.fullmatch(value) else None
    if scheme == "isbn13":
        return isbn13(value)
    return None


def external_ids(pairs: Iterable[Tuple[str, Any]]) -> Tuple[Tuple[str, str], ...]:
    """Validated (scheme, value) pairs, one value per scheme, sorted. A scheme given two different valid values
    is dropped entirely (the upstream contradicts itself; neither is trusted)."""
    seen: Dict[str, Optional[str]] = {}
    for scheme, raw in pairs:
        if scheme == "asin" and isbn13(raw) is not None:
            scheme = "isbn13"                      # an ISBN-10 given as the ASIN (Amazon's book convention)
        if scheme not in SCHEMES:
            continue
        value = _clean(scheme, raw)
        if value is None:
            continue
        if scheme in seen and seen[scheme] != value:
            seen[scheme] = None
        elif scheme not in seen:
            seen[scheme] = value
    return tuple(sorted((s, v) for s, v in seen.items() if v is not None))


# Jellyfin `ProviderIds` keys (MediaBrowser.Model/Entities/MetadataProvider.cs names) -> scheme. Plugins may add
# other keys; they are ignored.
_JELLYFIN_KEYS = {"tmdb": "tmdb", "imdb": "imdb", "tvdb": "tvdb"}


def from_jellyfin(provider_ids: Any) -> Tuple[Tuple[str, str], ...]:
    if not isinstance(provider_ids, Mapping):
        return ()
    pairs = []
    for key, value in list(provider_ids.items())[:64]:
        if isinstance(key, str) and key.lower() in _JELLYFIN_KEYS:
            pairs.append((_JELLYFIN_KEYS[key.lower()], value))
    return external_ids(pairs)


def from_book_metadata(metadata: Any) -> Tuple[Tuple[str, str], ...]:
    """Audiobookshelf `media.metadata` (`isbn`, `asin`) and Komga `metadata` (`isbn`)."""
    if not isinstance(metadata, Mapping):
        return ()
    return external_ids([("isbn13", metadata.get("isbn")), ("asin", metadata.get("asin"))])


def identity_keys(kind: str, ids: Iterable[Tuple[str, str]]) -> Tuple[str, ...]:
    """Link keys for one item: `<kind>:<scheme>:<value>` for work schemes, `<scheme>:<value>` for editions."""
    keys = []
    for scheme, value in ids:
        if scheme in WORK_SCHEMES:
            keys.append(f"{kind}:{scheme}:{value}")
        elif scheme in EDITION_SCHEMES:
            keys.append(f"{scheme}:{value}")
    return tuple(sorted(keys))


@dataclass(frozen=True)
class Linked:
    groups: Tuple[Tuple[str, ...], ...]   # item ids that are the same title, each group of two or more
    ambiguous: Tuple[str, ...]           # keys left unused because one service gave them to several items


def link(items: Iterable[Any]) -> Linked:
    """Group items (anything with `id`, `service`, `kind` and `external_ids`) that share an exact identity key.

    Pure and per call: it only ever sees the items one member's own adapters returned for one page."""
    by_key: Dict[str, List[Any]] = {}
    for item in items:
        kind = getattr(item.kind, "value", item.kind)
        for key in identity_keys(kind, item.external_ids):
            by_key.setdefault(key, []).append(item)
    ambiguous = []
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for key, members in sorted(by_key.items()):
        per_service: Dict[Any, set] = {}
        for m in members:
            per_service.setdefault(m.service, set()).add(m.id)
        if any(len(ids) > 1 for ids in per_service.values()):
            ambiguous.append(key)
            continue
        ids = sorted({m.id for m in members})
        for other in ids[1:]:
            parent[find(other)] = find(ids[0])
    groups: Dict[str, List[str]] = {}
    for item_id in parent:
        groups.setdefault(find(item_id), []).append(item_id)
    return Linked(tuple(sorted(tuple(sorted(g)) for g in groups.values() if len(g) > 1)), tuple(ambiguous))
