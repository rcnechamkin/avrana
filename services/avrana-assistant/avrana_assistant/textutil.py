"""Tokenisation shared by retrieval and the grounding check."""
from __future__ import annotations

import re

STOPWORDS = frozenset("""
a an the and or but if then else of to in on at by for with from into onto up out as is are was were be been
being am do does did doing done have has had having it its this that these those there here i me my mine we
our you your yours he she they them their what which who whom whose when where why how can could would should
will shall may might must not no yes so than too very just also about over under again more most some any
all each other such only own same s t don doesn didn isn aren wasn weren won wouldn couldn shouldn cant
please hi hello hey thanks thank help need want like get got use using used see tell know make let give show
anything something someone thing things way able try trying tried still really im ive id ill
""".split())

_SYNONYMS = {
    "film": "movie", "films": "movie", "movies": "movie", "telly": "tv", "television": "tv",
    "forgot": "forgot", "forgotten": "forgot", "forget": "forgot", "lost": "forgot",
    "e-mail": "email", "iphone": "iphone", "ipad": "iphone", "ios": "iphone", "apple": "apple",
    "firestick": "fire", "kindle": "kindle", "audiobook": "audiobook", "audiobooks": "audiobook",
    "ebook": "ebook", "ebooks": "ebook", "manga": "comic", "comics": "comic", "comic": "comic",
    "signin": "sign", "login": "sign", "log": "sign", "signing": "sign", "signed": "sign",
    "reset": "reset", "resetting": "reset", "recover": "reset", "recovery": "reset",
    "down": "down", "outage": "down", "offline": "down", "broken": "down",
    "contact": "contact", "reach": "contact", "message": "contact", "email": "email",
    "install": "install", "download": "install", "downloading": "install",
    "visible": "see", "missing": "missing", "hidden": "missing",
    "request": "request", "requesting": "request", "requests": "request", "ask": "request",
    "listen": "listen", "listening": "listen", "audio": "audiobook",
}

_WORD = re.compile(r"[a-z0-9][a-z0-9'\-]*")


def stem(w: str) -> str:
    w = w.replace("'", "")
    if w in _SYNONYMS:
        return _SYNONYMS[w]
    if len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    elif len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    return _SYNONYMS.get(w, w)


def tokens(text: str) -> list[str]:
    """Lower-cased, stop-word-free, lightly stemmed terms."""
    out = []
    for raw in _WORD.findall(text.lower()):
        base = raw.replace("'", "")
        if base in STOPWORDS or raw in STOPWORDS:
            continue
        out.append(stem(raw))
    return out
