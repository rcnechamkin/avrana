"""Small, valid, SYNTHETIC cover images for the dev mocks. Standard library only (zlib, struct).

The mocks used to answer a cover request with a PNG magic number followed by filler bytes. That passes the
adapters' magic-number check, so the browser received bytes it could not decode and drew its broken-image icon over
every card. These are real PNGs, generated in memory (nothing binary is committed), in each kind's natural shape,
so a review of the dev stack shows the real layout:

    poster 2:3 (movie, series), still 16:9 (episode), square (audiobook), comic 13:20, book 2:3

Each image is a flat colour derived from the request path, with a lighter inner rule, so neighbouring cards differ.
"""
from __future__ import annotations

import hashlib
import struct
import zlib

SHAPES = {"poster": (120, 180), "still": (192, 108), "square": (160, 160), "comic": (130, 200), "book": (120, 180)}
_CACHE: dict = {}


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png(width: int, height: int, rgb, inner) -> bytes:
    """A truecolour 8-bit PNG: `rgb` ground with a 2px `inner` rule inset by about 8 percent."""
    ix, iy = max(2, width // 12), max(2, height // 12)
    ground, rule = bytes(rgb), bytes(inner)
    rows = []
    for y in range(height):
        on_h = y in (iy, iy + 1, height - iy - 2, height - iy - 1)
        inside_y = iy <= y < height - iy
        row = bytearray(b"\x00")                       # filter type 0 for each scanline
        for x in range(width):
            on_v = x in (ix, ix + 1, width - ix - 2, width - ix - 1)
            inside_x = ix <= x < width - ix
            row += rule if ((on_h and inside_x) or (on_v and inside_y)) else ground
        rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + _chunk(b"IEND", b""))


def cover(shape: str, seed: str) -> bytes:
    """A synthetic cover for `shape` (see SHAPES; unknown shapes are posters), coloured by `seed`. Cached."""
    w, h = SHAPES.get(shape, SHAPES["poster"])
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    key = (w, h, digest[:3])
    if key not in _CACHE:
        base = tuple(40 + b % 90 for b in digest[:3])          # muted, so white text beside it stays the focus
        _CACHE[key] = png(w, h, base, tuple(min(255, c + 90) for c in base))
    return _CACHE[key]


# Jellyfin item Type -> shape (as the Home view-model's SHAPE table does for the contract's kinds).
JELLYFIN_SHAPE = {"Movie": "poster", "Series": "poster", "Episode": "still", "Season": "poster"}
