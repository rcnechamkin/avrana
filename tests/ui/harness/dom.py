"""A forgiving HTML tree for the static checks (stdlib html.parser)."""
from __future__ import annotations

import re
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
CLOSES_SAME = {"li", "p", "dt", "dd", "option", "tr", "td", "th"}
INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "summary"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "text", "line")

    def __init__(self, tag, attrs=None, parent=None, text="", line=0):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent
        self.text = text
        self.line = line

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def element_children(self):
        return [c for c in self.children if c.tag != "#text"]

    def iter(self):
        for c in self.children:
            yield c
            if c.tag != "#text":
                yield from c.iter()

    def find_all(self, *tags):
        return [n for n in self.iter() if n.tag in tags]

    def ancestors(self):
        p = self.parent
        while p is not None:
            yield p
            p = p.parent

    def text_content(self):
        if self.tag == "#text":
            return self.text
        return "".join(c.text_content() for c in self.children if c.tag not in ("script", "style"))

    def label(self):
        """A short, stable description of the element for finding ids."""
        cls = ".".join(self.classes)
        return self.tag + ("." + cls if cls else "")


class Document:
    def __init__(self, root: Node):
        self.root = root
        self.by_id = {}
        for n in root.iter():
            i = n.attrs.get("id")
            if i is not None and i not in self.by_id:
                self.by_id[i] = n

    @property
    def html(self):
        for n in self.root.children:
            if n.tag == "html":
                return n
        return None

    def all(self, *tags):
        return self.root.find_all(*tags)

    def style_text(self):
        return "\n".join(n.text_content_raw() if hasattr(n, "text_content_raw") else "".join(c.text for c in n.children)
                         for n in self.all("style"))


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        top = self.stack[-1]
        if tag in CLOSES_SAME and top.tag == tag:
            self.stack.pop()
            top = self.stack[-1]
        node = Node(tag, {k.lower(): (v if v is not None else "") for k, v in attrs}, top, line=self.getpos()[0])
        top.children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data:
            top = self.stack[-1]
            top.children.append(Node("#text", parent=top, text=data, line=self.getpos()[0]))


def parse(html_text: str) -> Document:
    b = _Builder()
    b.feed(html_text)
    b.close()
    return Document(b.root)


# ---------------------------------------------------------------------------------------------
def visible_text(node: Node) -> str:
    """Text a sighted reader would meet: no head, script, style, template or aria-hidden subtree."""
    parts = []

    def walk(n):
        if n.tag == "#text":
            parts.append(n.text)
            return
        if n.tag in ("head", "script", "style", "template", "title", "noscript") or n.attrs.get("hidden") is not None:
            return
        if n.attrs.get("aria-hidden") == "true":
            return
        if n.tag in ("br", "li", "p", "div", "section", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6"):
            parts.append(" ")
        for c in n.children:
            walk(c)
        if n.tag in ("p", "div", "li", "section", "dd", "h1", "h2", "h3", "h4", "h5", "h6"):
            parts.append(" ")
    walk(node)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def accessible_name(node: Node, doc: Document) -> str:
    """Approximate accessible name: aria-labelledby, aria-label, native label, content, title."""
    ref = node.attrs.get("aria-labelledby")
    if ref:
        txt = " ".join(visible_text(doc.by_id[i]) for i in ref.split() if i in doc.by_id)
        if txt.strip():
            return txt.strip()
    al = (node.attrs.get("aria-label") or "").strip()
    if al:
        return al
    if node.tag == "input":
        t = (node.attrs.get("type") or "text").lower()
        if t in ("submit", "button", "reset"):
            return (node.attrs.get("value") or ("Submit" if t == "submit" else "")).strip()
        if t == "image":
            return (node.attrs.get("alt") or "").strip()
    if node.tag in ("input", "select", "textarea"):
        lab = label_for(node, doc)
        if lab:
            return visible_text(lab)
    else:
        parts = []

        def walk(n):
            for c in n.children:
                if c.tag == "#text":
                    parts.append(c.text)
                elif c.tag == "img":
                    parts.append(c.attrs.get("alt") or "")
                elif c.attrs.get("aria-hidden") == "true":
                    continue
                elif c.tag not in ("script", "style"):
                    al2 = (c.attrs.get("aria-label") or "").strip()
                    parts.append(al2) if al2 else walk(c)
        walk(node)
        txt = re.sub(r"\s+", " ", "".join(parts)).strip()
        if txt:
            return txt
    return (node.attrs.get("title") or "").strip()


def label_for(node: Node, doc: Document):
    i = node.attrs.get("id")
    if i:
        for lab in doc.all("label"):
            if lab.attrs.get("for") == i:
                return lab
    for a in node.ancestors():
        if a.tag == "label":
            return a
    return None


def inline_in_text(node: Node) -> bool:
    """WCAG 2.5.8 'inline' exemption, approximated: the link sits in a run of other text."""
    p = node.parent
    if p is None:
        return False
    for c in p.children:
        if c.tag == "#text" and c.text.strip():
            return True
    return False
