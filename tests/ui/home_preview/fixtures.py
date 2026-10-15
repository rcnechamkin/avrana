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

# Who is looking (AVR-478). The invented member's libraries decide which places, tabs and items exist at
# all: a library the member cannot use is never named, struck through or counted. "out" is the page a
# request without a verified identity would get: no member content, a way to sign in, and Help.
VIEWERS = {
    "member": {"label": "Every library", "name": "Ada Lovelace", "held": {"video", "audio", "books", "comics"}},
    "books": {"label": "Books only", "name": "Ada Lovelace", "held": {"books"}},
    "none": {"label": "No library yet", "name": "Ada Lovelace", "held": set()},
    "out": {"label": "Signed out", "name": None, "held": set()},
}
# The account menu: short, and only places that exist. No email, groups or technical data (AVR-478).
ACCOUNT_MENU = [("Account and security", "Account and security"), ("Help", "Help"), ("Sign out", "Sign out")]

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
# The bar of places under the wordmark: (label, the library whose service it needs or None).
PLACES = [("Watch", "video"), ("Listen", "audio"), ("Read", "books"), ("Request", None), ("Help", None)]
LIBRARY_NAMES = {"video": "Movies and TV", "audio": "Audiobooks", "books": "Books", "comics": "Comics"}
CONTINUE_MOST = 4       # Home's Continue row, whatever library each item is from
NEW_MOST = 4            # Home's "New this week" row; the rest is on /new
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


def _lower(name: str) -> str:
    """A library's name inside a sentence: "audiobooks", "movies and TV"."""
    return name[0].lower() + name[1:]


def _state(state: str, held=frozenset(LIBRARY_NAMES)):
    """One preview state: each library's status (ok, slow, gone, or absent when the member cannot use
    it), the notice, and what there is. An absent library is never said to be down."""
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
        if "video" in held:
            notice = f"{GONE['video']} Everything else works."
    elif state == "unavailable":
        status = dict.fromkeys(status, "gone")
        if held:
            notice = "The libraries are offline this evening for maintenance. Help and your account still work."
    for key in status:
        if key not in held:
            status[key] = "absent"
    return status, notice, watching, listening, recent


def _nav(status: dict) -> list[tuple[str, str | None, bool]]:
    """The bar of places. Read needs books or comics; Request and Help need no library. A place for a
    library the member cannot use is left out altogether, not struck through."""
    read = [status[k] for k in ("books", "comics") if status[k] != "absent"]
    held = {"video": status["video"] != "absent", "audio": status["audio"] != "absent", "books": bool(read)}
    up = {"video": status["video"] != "gone", "audio": status["audio"] != "gone",
          "books": any(s != "gone" for s in read)}
    return [(label, key, True if key is None else up[key]) for label, key in PLACES if key is None or held[key]]


def viewer(who: str) -> dict:
    """The identity part of every page: the name for the account menu (never an email) and initial."""
    v = VIEWERS[who]
    name = v["name"]
    return {"who": who, "signed_in": name is not None, "member_name": name,
            "initial": name[0].upper() if name else "", "account_menu": ACCOUNT_MENU if name else []}


def _new(shelf: dict, slug: str, title: str, line: str, all_tab: bool) -> dict:
    # under "All" the second line says which library; under a library's own tab, the item's own line
    return {"slug": slug, "title": title, "line": shelf["name"] if all_tab else line, "shape": shelf["shape"]}


def page(state: str, tab: str = "all", who: str = "member") -> dict:
    """What Home shows in one preview state: the places, one Continue row, one bounded New row."""
    status, notice, watching, listening, recent = _state(state, VIEWERS[who]["held"])
    mine = [v for v in status.values() if v != "absent"]
    all_gone = bool(mine) and all(v == "gone" for v in mine)
    # Continue: video and audio mixed, the most recent of each first, never more than CONTINUE_MOST.
    mixed = []
    for i in range(max(len(watching), len(listening))):
        if i < len(watching) and status["video"] == "ok":
            mixed.append(dict(watching[i], shape="still", verb="watched", line=watching[i]["left"]))
        if i < len(listening) and status["audio"] == "ok":
            mixed.append(dict(listening[i], shape="square", verb="heard", line=listening[i]["left"].split(", ")[-1]))
    slow = [SLOW[key] for key in ("video", "audio") if status[key] == "slow"]
    # New this week: a tab for each library whose service answers at all; "All" is the newest of each.
    shelves = [shelf for shelf in recent if status[shelf["key"]] not in ("gone", "absent")]
    tabs = [("all", "All")] + [(shelf["key"], shelf["name"]) for shelf in shelves]
    if tab not in dict(tabs):
        tab = "all"
    said, wait, items = "", False, []
    if tab == "all":
        items = [_new(shelf, *shelf["items"][0], True) for shelf in shelves if status[shelf["key"]] == "ok" and shelf["items"]]
        waiting = [shelf for shelf in shelves if status[shelf["key"]] == "slow"]
        if waiting:
            said, wait = SLOW[waiting[0]["key"]], True
        elif not items:
            said = "Nothing new this week."
        more = "Everything new this week"
    else:
        shelf = next(shelf for shelf in shelves if shelf["key"] == tab)
        if status[tab] == "slow":
            said, wait = SLOW[tab], True
        elif not shelf["items"]:
            said = f"Nothing new in {_lower(shelf['name'])} this week."
        else:
            items = [_new(shelf, *item, False) for item in shelf["items"][:NEW_MOST]]
        more = f"Everything new in {_lower(shelf['name'])}"
    # Continue holds video and audio only, so it is shown only to a member who can use one of them.
    resumable = any(status[k] != "absent" for k in ("video", "audio"))
    return {**viewer(who), "no_library": not mine, "resumable": resumable,
            "status": status, "notice": notice, "all_gone": all_gone, "nav": _nav(status) if VIEWERS[who]["name"] else [("Help", None, True)],
            "continue_items": mixed[:CONTINUE_MOST], "continue_slow": slow,
            "new_tabs": tabs, "new_tab": tab, "new_items": items[:NEW_MOST], "new_said": said, "new_wait": wait,
            "new_more": more}


def new_page(state: str, lib: str = "", who: str = "member") -> dict:
    """The New page: everything new in one library at a time. No "All" here: this is the long list."""
    status, notice, _, _, recent = _state(state, VIEWERS[who]["held"])
    mine = [key for key, v in status.items() if v != "absent"]
    shelves = [shelf for shelf in recent if status[shelf["key"]] not in ("gone", "absent")]
    tabs = [(shelf["key"], shelf["name"]) for shelf in shelves]
    base = {**viewer(who), "no_library": not mine,
            "status": status, "notice": notice, "nav": _nav(status) if VIEWERS[who]["name"] else [("Help", None, True)], "tabs": tabs, "lib": "", "items": [],
            "said": "", "wait": False, "all": ""}
    if not mine:
        return base
    if not shelves:
        names = [_lower(LIBRARY_NAMES[key]) for key in mine]  # every library name is plural
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        return dict(base, said=listed[0].upper() + listed[1:] + " are unavailable right now.")
    shelf = next((shelf for shelf in shelves if shelf["key"] == lib), shelves[0])
    base.update(lib=shelf["key"], all=shelf["all"])
    if status[shelf["key"]] == "slow":
        return dict(base, said=SLOW[shelf["key"]], wait=True)
    if not shelf["items"]:
        return dict(base, said="Nothing new here this week.")
    return dict(base, items=[_new(shelf, *item, False) for item in shelf["items"]])


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


# ---- Search and title pages (AVR-426) ------------------------------------------------------------
# Which library each title lives in, and what the title page says about it. The descriptions are
# one plain sentence each, written for the preview; a title the library describes no further has none.
ABOUT = {
    "nosferatu": "A clerk travels to a castle in the mountains and brings something back with him.",
    "metropolis": "A city of workers below and owners above, and the machine between them.",
    "the-general": "A train driver chases his stolen engine across the lines.",
    "moby-dick": "A sailor joins a whaling ship whose captain hunts one white whale.",
    "dracula": "Letters and diaries tell of a count who moves from Transylvania to England.",
    "walden": "Two years in a cabin by a pond, and what living simply taught.",
    "little-nemo": "A boy dreams his way into Slumberland, one Sunday page at a time.",
}
# The word a member reads on the one action of a title page, by library (never a claim that it plays).
ACTION = {"video": "Watch in Movies and TV", "audio": "Listen in Audiobooks", "books": "Read in Books",
          "comics": "Read in Comics"}
RESUME = {"video": "Resume in Movies and TV", "audio": "Resume in Audiobooks"}
KIND = {"video": "Film", "audio": "Audiobook", "books": "Book", "comics": "Comic"}
QUERY_MOST = 100        # characters of a search kept; the rest is ignored, never echoed


def _catalogue() -> dict[str, dict]:
    """Every fixture title once: its library, artwork shape, lines and, if it has one, progress."""
    out = {}
    for shelf in RECENT:
        for slug, title, line in shelf["items"]:
            out[slug] = {"slug": slug, "title": title, "line": line, "lib": shelf["key"], "shape": shelf["shape"]}
    for key, shape, items in (("video", "poster", CONTINUE_WATCHING), ("audio", "square", CONTINUE_LISTENING)):
        for i in items:
            out.setdefault(i["slug"], {"slug": i["slug"], "title": i["title"], "line": i["line"], "lib": key, "shape": shape})
            out[i["slug"]].update(left=i["left"], done=i["done"])
    return out


CATALOGUE = _catalogue()


def _listed(keys) -> str:
    names = [_lower(LIBRARY_NAMES[key]) for key in keys]  # every library name is plural
    text = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return text[0].upper() + text[1:]


def _fold(text: str) -> str:
    return " ".join("".join(c for c in text.casefold() if c.isalnum() or c.isspace()).split())


def search_page(state: str, query: str = "", who: str = "member") -> dict:
    """Search across the libraries this member can use, and only those. A library the member cannot
    use is never searched, so "no match" reads the same whether a title is there or nowhere. A library
    that is down or slow is said once, by name, beside what the others found."""
    status, notice, *_ = _state(state, VIEWERS[who]["held"])
    query = " ".join(query.split())[:QUERY_MOST]
    mine = [key for key, v in status.items() if v != "absent"]
    base = {**viewer(who), "no_library": not mine, "status": status, "notice": notice,
            "nav": _nav(status) if VIEWERS[who]["name"] else [("Help", None, True)],
            "query": query, "groups": [], "said": [], "wait": False, "none_found": False, "all_gone": False}
    if not mine:
        return base
    gone = [key for key in mine if status[key] == "gone"]
    slow = [key for key in mine if status[key] == "slow"]
    if len(gone) == len(mine):
        return dict(base, all_gone=True, said=[f"{_listed(mine)} are unavailable right now, so nothing can be searched. "
                                               "Try again later, or read Help."])
    said = []
    if gone:
        said.append(f"{_listed(gone)} could not be searched: unavailable right now.")
    if slow:
        said.append(f"{_listed(slow)} are taking longer than usual, so nothing from them is shown yet.")
    if not query:
        return dict(base, said=said, wait=bool(slow))
    words = _fold(query).split()
    groups = []
    for key in ("video", "audio", "books", "comics"):
        if status[key] != "ok":
            continue
        hits = [dict(t, where=LIBRARY_NAMES[key]) for t in CATALOGUE.values()
                if t["lib"] == key and words and all(w in _fold(t["title"] + " " + t["line"]) for w in words)]
        if hits:
            groups.append({"key": key, "name": LIBRARY_NAMES[key], "items": sorted(hits, key=lambda t: t["title"])})
    return dict(base, groups=groups, said=said, wait=bool(slow), none_found=not groups)


def title_page(state: str, slug: str, who: str = "member") -> dict | None:
    """One title. None (a 404) when the title does not exist for this member: unknown, or in a library
    the member cannot use. When its library is down or slow the page says so and offers no action."""
    t = CATALOGUE.get(slug)
    held = VIEWERS[who]["held"]
    if t is None or t["lib"] not in held:
        return None
    status, notice, *_ = _state(state, held)
    lib = t["lib"]
    base = {**viewer(who), "no_library": False, "status": status, "notice": notice, "nav": _nav(status),
            "lib_name": LIBRARY_NAMES[lib], "item": None, "said": "", "wait": False}
    if status[lib] == "gone":
        return dict(base, said=f"{GONE[lib]} This title will be here when they are back.")
    if status[lib] == "slow":
        return dict(base, said=SLOW[lib], wait=True)
    resume = "done" in t and state != "empty"
    item = dict(t, kind=KIND[lib], about=ABOUT.get(slug, ""),
                action=RESUME[lib] if resume else ACTION[lib],
                progress=(t["left"] if resume else ""), done=(t["done"] if resume else None),
                verb="watched" if lib == "video" else "heard")
    return dict(base, item=item)
