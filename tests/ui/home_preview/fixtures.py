"""Fixture data for the member home preview.

Everything here is invented for the preview: one member, titles that are in the public domain,
and covers drawn as plain SVG by this file. Nothing is read from a library, a service or a disk,
and no title here says anything about what the real libraries hold.
"""
from __future__ import annotations

import hashlib
import html

STATES = {
    "healthy": "Healthy",
    "slow": "Loading",
    "empty": "Empty",
    "degraded": "One service down",
    "unavailable": "Libraries unavailable",
}

# shape -> (width, height) of the drawn cover. Each library keeps the shape its own app uses.
SHAPES = {"still": (320, 180), "poster": (200, 300), "square": (300, 300), "book": (200, 300), "comic": (195, 300)}

CONTINUE_WATCHING = [
    {"slug": "nosferatu", "title": "Nosferatu", "line": "Film, 1922", "left": "38 min left", "done": 60, "opens": "Movies and TV"},
    {"slug": "les-vampires", "title": "Les Vampires", "line": "Episode 3, The Red Codebook", "left": "12 min left", "done": 70, "opens": "Movies and TV"},
    {"slug": "the-general", "title": "The General", "line": "Film, 1926", "left": "1 h 5 min left", "done": 15, "opens": "Movies and TV"},
]
CONTINUE_LISTENING = [
    {"slug": "moby-dick", "title": "Moby-Dick", "line": "Herman Melville", "left": "Chapter 41 of 135, 14 h left", "done": 30, "opens": "Audiobooks"},
    {"slug": "middlemarch", "title": "Middlemarch", "line": "George Eliot", "left": "5 h 20 min left", "done": 82, "opens": "Audiobooks"},
]
RECENT = [
    {"key": "video", "name": "Movies and TV", "shape": "poster", "all": "All movies and TV", "items": [
        ("metropolis", "Metropolis", "1927"), ("the-kid", "The Kid", "1921"), ("sherlock-jr", "Sherlock Jr.", "1924"),
        ("safety-last", "Safety Last!", "1923"), ("caligari", "The Cabinet of Dr. Caligari", "1920"),
        ("potemkin", "Battleship Potemkin", "1925")]},
    {"key": "audio", "name": "Audiobooks", "shape": "square", "all": "All audiobooks", "items": [
        ("dracula", "Dracula", "Bram Stoker"), ("frankenstein", "Frankenstein", "Mary Shelley"),
        ("pride-and-prejudice", "Pride and Prejudice", "Jane Austen"), ("the-odyssey", "The Odyssey", "Homer"),
        ("great-expectations", "Great Expectations", "Charles Dickens")]},
    {"key": "books", "name": "Books", "shape": "book", "all": "All books", "items": [
        ("walden", "Walden", "Henry David Thoreau"), ("jane-eyre", "Jane Eyre", "Charlotte Brontë"),
        ("leaves-of-grass", "Leaves of Grass", "Walt Whitman"), ("the-time-machine", "The Time Machine", "H. G. Wells"),
        ("emma", "Emma", "Jane Austen"), ("the-awakening", "The Awakening", "Kate Chopin")]},
    {"key": "comics", "name": "Comics", "shape": "comic", "all": "All comics", "items": [
        ("little-nemo", "Little Nemo in Slumberland", "1905"), ("krazy-kat", "Krazy Kat", "1913"),
        ("yellow-kid", "The Yellow Kid", "1895"), ("mutt-and-jeff", "Mutt and Jeff", "1907"),
        ("gasoline-alley", "Gasoline Alley", "1918")]},
]
TILES = [
    ("Watch", "Movies & TV", "video"), ("Listen", "Audiobooks", "audio"), ("Read", "Comics & ebooks", "books"),
    ("Request", "Ask for something that’s missing", "requests"), ("Help", "Apps & setup guides", "help"),
]
# The sentence a member reads when a library's service does not answer (MEDIA-2.0, degradation).
GONE = {"video": "Movies and TV are unavailable right now.", "audio": "Audiobooks are unavailable right now.",
        "books": "Books are unavailable right now.", "comics": "Comics are unavailable right now."}
SLOW = {"video": "Movies and TV are taking longer than usual.", "audio": "Audiobooks are taking longer than usual.",
        "books": "Books are taking longer than usual.", "comics": "Comics are taking longer than usual."}


def _titles() -> dict[str, tuple[str, str]]:
    known = {i["slug"]: (i["title"], i["line"]) for i in CONTINUE_WATCHING + CONTINUE_LISTENING}
    for shelf in RECENT:
        for slug, title, line in shelf["items"]:
            known[slug] = (title, line)
    return known


TITLES = _titles()


def page(state: str) -> dict:
    """What the home page shows in one preview state. `status` per library: ok, slow, gone, none."""
    status = {"video": "ok", "audio": "ok", "books": "ok", "comics": "ok"}
    notice = None
    watching, listening = CONTINUE_WATCHING, CONTINUE_LISTENING
    recent = RECENT
    if state == "slow":
        status["audio"] = "slow"
    elif state == "empty":
        watching, listening = [], []
        recent = [dict(shelf, items=[]) if shelf["key"] == "audio" else shelf for shelf in RECENT]
    elif state == "degraded":
        status["video"] = "gone"
    elif state == "unavailable":
        status = dict.fromkeys(status, "gone")
        notice = "The libraries are offline this evening for maintenance."
    return {"status": status, "notice": notice, "watching": watching, "listening": listening, "recent": recent,
            "all_gone": all(v == "gone" for v in status.values()),
            "tiles": [t for t in TILES if t[2] in ("help", "requests") or status.get(t[2]) != "gone"]}


def _lines(text: str, width: int) -> list[str]:
    out, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return out + [line]


def cover(shape: str, slug: str) -> str | None:
    """A drawn stand-in for artwork: a quiet tinted field, a frame, the title in the house serif.

    Real artwork comes from each library and is full colour; the tint is here so the preview can
    show how colour sits on the black page. No image file, no photograph, nothing generated.
    """
    if shape not in SHAPES or slug not in TITLES:
        return None
    w, h = SHAPES[shape]
    title, line = TITLES[slug]
    hue = int(hashlib.sha256(slug.encode()).hexdigest()[:4], 16) % 360
    size = 30 if shape == "still" else 26
    rows = _lines(title, 14 if shape == "still" else 11)
    top = h / 2 - (len(rows) - 1) * size * 0.6
    text = "".join(f'<text x="{w / 2}" y="{top + i * size * 1.2:.0f}" font-size="{size}">{html.escape(row)}</text>'
                   for i, row in enumerate(rows))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{html.escape(title)}">'
            f'<rect width="{w}" height="{h}" fill="hsl({hue} 24% 20%)"/>'
            f'<rect x="10" y="10" width="{w - 20}" height="{h - 20}" fill="none" stroke="#fff" stroke-opacity=".45"/>'
            f'<g fill="#fff" text-anchor="middle" font-family="\'Times New Roman\',Times,\'Liberation Serif\',serif" '
            f'letter-spacing="1">{text}'
            f'<text x="{w / 2}" y="{h - 26}" font-size="13" fill-opacity=".7">{html.escape(line)}</text></g></svg>')
