"""Corpus loading and a small lexical (BM25) retriever with audience filtering."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import corpus_check
from .guards import detect_injection
from .denylist import has_internal_markers
from .textutil import tokens
from .datatypes import Passage, Principal

ALLOWED_CLASSES = ("public-help", "member-general")


class CorpusError(Exception):
    pass


@dataclass(frozen=True)
class Doc:
    id: str
    title: str
    text: str
    audience: dict
    data_class: str
    review_status: str
    stale: bool = False   # a source file drifted since extraction (computed at load time)


def visible(doc: Doc, principal: Principal) -> bool:
    """Audience filter. Depends only on the Principal, never on message text."""
    kind = doc.audience.get("kind")
    if kind == "public":
        return True
    if not principal.authenticated:
        return False
    if kind == "all_members":
        return True
    if kind == "any_of_groups":
        return bool(set(doc.audience.get("groups", ())) & principal.groups)
    return False


class Corpus:
    """`strict` (the default, for any production-style configuration) fails closed: documents whose
    sources are stale are not retrievable. Tests and the evaluation use strict=False against the pinned
    corpus, where staleness only produces warnings."""

    def __init__(self, docs: list[Doc], strict: bool = True):
        self.strict = strict
        self.docs = {d.id: d for d in docs}
        if len(self.docs) != len(docs):
            raise CorpusError("duplicate document id")

    @classmethod
    def load(cls, *manifest_paths: Path, verify: bool = True, strict: bool = True,
             repo_root: Path | None = None) -> "Corpus":
        docs: list[Doc] = []
        for mp in manifest_paths:
            mp = Path(mp)
            root = Path(repo_root) if repo_root else corpus_check.find_repo_root(mp)
            if strict:
                hard = corpus_check.check_hard(mp, root)
                if hard:
                    raise CorpusError(f"{mp.name}: {len(hard)} manifest problem(s); first: {hard[0]}")
            stale_ids = corpus_check.stale_doc_ids(mp, root)
            manifest = corpus_check.load_manifest(mp)
            for d in manifest["documents"]:
                p = mp.parent / d["path"]
                if verify and d.get("doc_sha256") and corpus_check.sha256_text_file(p) != d["doc_sha256"]:
                    raise CorpusError(f"{d['id']}: changed since review")
                fixture = d.get("review_status") == "synthetic-fixture"
                if d["data_class"] not in ALLOWED_CLASSES and not fixture:
                    raise CorpusError(f"{d['id']}: class {d['data_class']} may not be indexed")
                text = p.read_text(encoding="utf-8")
                # Operator-internal content is never indexed, fixture or not: it would reach prompts.
                if not fixture and has_internal_markers(text):
                    raise CorpusError(f"{d['id']}: operator-internal marker")
                docs.append(Doc(d["id"], d["title"], text, d["audience"], d["data_class"], d["review_status"],
                                d["id"] in stale_ids))
        return cls(docs, strict)

    def get(self, doc_id: str, principal: Principal) -> Doc | None:
        d = self.docs.get(doc_id)
        if d is not None and self.strict and d.stale:
            return None
        return d if d is not None and visible(d, principal) else None

    def lead_text(self, doc_id: str, principal: Principal, paragraphs: int = 2) -> str:
        """First body paragraphs of a visible document (headings and bullets excluded)."""
        d = self.get(doc_id, principal)
        if d is None:
            return ""
        paras = [p.strip() for p in re.split(r"\n\s*\n", d.text) if p.strip() and not p.lstrip().startswith("#")]
        return " ".join(" ".join(p.split()) for p in paras[:paragraphs])


def chunk(doc: Doc, max_chars: int = 900) -> list[str]:
    parts = re.split(r"\n(?=## )", doc.text)
    out: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        while len(part) > max_chars:
            cut = part.rfind("\n", 0, max_chars)
            cut = cut if cut > 200 else max_chars
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            out.append(part)
    return out


@dataclass(frozen=True)
class RetrievalResult:
    passages: tuple
    confidence: float
    matched_any: bool
    quarantined: tuple = ()


class Retriever:
    K1, B = 1.5, 0.75

    def __init__(self, corpus: Corpus):
        self.corpus = corpus

    def search(self, principal: Principal, query: str, k: int = 3, only_doc: str | None = None) -> RetrievalResult:
        chunks: list[tuple[Doc, int, str, Counter]] = []
        quarantined: list[str] = []
        for doc in self.corpus.docs.values():
            if self.corpus.strict and doc.stale:
                continue
            if not visible(doc, principal) or (only_doc is not None and doc.id != only_doc):
                continue
            for i, text in enumerate(chunk(doc)):
                if detect_injection(text):
                    if doc.id not in quarantined:
                        quarantined.append(doc.id)
                    continue
                chunks.append((doc, i, text, Counter(tokens(doc.title + " " + text))))
        q_terms = tokens(query)
        if not chunks or not q_terms:
            return RetrievalResult((), 0.0, False, tuple(quarantined))
        n = len(chunks)
        df = Counter()
        for _d, _i, _t, tf in chunks:
            df.update(tf.keys())
        avgdl = sum(sum(tf.values()) for *_x, tf in chunks) / n

        def idf(term: str) -> float:
            return math.log(1 + (n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))

        scored = []
        for doc, i, text, tf in chunks:
            dl = sum(tf.values())
            s = 0.0
            for t in set(q_terms):
                f = tf.get(t, 0)
                if f:
                    s += idf(t) * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * dl / avgdl))
            scored.append((s, doc.id, i, doc, text, tf))
        scored.sort(key=lambda r: (-r[0], r[1], r[2]))
        top = [r for r in scored[:k] if r[0] > 0]
        if not top:
            return RetrievalResult((), 0.0, False, tuple(quarantined))
        uniq = set(q_terms)
        total = sum(idf(t) for t in uniq)
        matched = sum(idf(t) for t in uniq if t in top[0][5])
        confidence = matched / total if total else 0.0
        if only_doc is not None:
            confidence = 1.0  # the route, not lexical overlap, selected this document
        passages = tuple(Passage(r[3].id, r[3].title, r[4], round(r[0], 4), r[3].data_class, r[2]) for r in top)
        return RetrievalResult(passages, round(confidence, 4), True, tuple(quarantined))
