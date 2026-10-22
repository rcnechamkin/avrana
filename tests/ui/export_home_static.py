#!/usr/bin/env python3
"""Static export of the integrated Home for a real-device (iPhone) review. SYNTHETIC DATA ONLY.

    "$TEMP/audvenv/Scripts/python.exe" tests/ui/export_home_static.py --out <folder>

It renders the REAL Home (the app's own templates and view model) in this process, against the
loopback mock services (Jellyfin, Audiobookshelf, Komga, Calibre-Web), for synthetic members and
these states: normal, one library unavailable, one section unavailable (the library still answers in part),
all unavailable, a library not set up for the member, no library, signed out, and the New tabs. Besides Home
it follows the shell's own links: Search, title pages (at most one per library per member and state),
Account, Help and its topics, "If something doesn't open", Read, Request and the Watch interstitial. Titles are lengthened by the invented long-title overlay (dev/mock_long_titles.py) so narrow cards
show real-world wrapping; `--short-titles` serves the fixtures' own short titles. It then writes plain files: HTML, one shared stylesheet per page kind, and generated SVG
placeholders for the artwork. Serve the folder from the PC's LAN address:

    python -m http.server 8480 --bind <LAN-IP> --directory <folder>

Nothing here binds a network port, forges an identity over a network, or reaches a real service:
the synthetic identity headers are handed to the in-process app and never leave it. The production
artwork route is untouched; only the exported copy gets generated placeholders. Pages that would
leave Home (a real service, sign-in, sign-out) become a stub page that says so.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import re
import shutil
import socket
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

REPO = Path(__file__).resolve().parents[2]
HOME = REPO / "services" / "avrana-home"
sys.path.insert(0, str(HOME))

USER, GROUPS, NAME = "X-authentik-username", "X-authentik-groups", "X-authentik-name"
PEER = ("203.0.113.7", 50000)
MEMBERS = {   # synthetic, the same groups as dev/dev_identity.py
    "member-a": ("Member A", "avrana-users|avrana-videos|avrana-audiobooks"),
    "member-b": ("Member B", "avrana-users|avrana-videos|avrana-audiobooks|avrana-books|avrana-comics"),
}
NO_LIBRARY = ("member-none", ("Member None", "avrana-users"))
# member-c: Movies and TV permitted, but the synthetic Jellyfin account is disabled, so it is "not set up yet".
EXTRA = {"member-c": ("Member C", "avrana-users|avrana-videos")}
MOCK_KEYS = ("jellyfin", "abs", "komga", "calibre")
# scenario: (title, members, which mocks misbehave: "key" is down, "key:mode" is that mock mode)
SCENARIOS = {
    "normal": ("Normal", tuple(MEMBERS), ()),
    "one-down": ("One library unavailable (Movies and TV)", tuple(MEMBERS), ("jellyfin",)),
    "one-section-down": ("One section unavailable (Movies and TV Continue; New still answers)", ("member-a",),
                         ("jellyfin:wrong-user",)),
    "all-down": ("All libraries unavailable", tuple(MEMBERS), MOCK_KEYS),
    "not-linked": ("Not set up (Movies and TV not linked to the account)", ("member-c",), ()),
    "no-library": ("No library", ("member-none",), ()),
    "signed-out": ("Signed out", ("signed-out",), ()),
}
# The search pages worth reviewing (term in the address -> file name): results, no match, an invalid term.
SEARCH_SEEDS = {"/search": "search", "/search?q=Synthetic": "search-results",
                "/search?q=zzqxnothingzz": "search-no-match", "/search?q=%2A%2A": "search-invalid"}
# Member-a's own film: a title page in every state (ok, unavailable, not set up for member-c; 404 is skipped).
TITLE_SEEDS = ("/title/jellyfin/aaaa0000000000000000000000000001",)
TITLE = re.compile(r"^/title/([a-z-]+)/[A-Za-z0-9_-]+(?:\?q=[A-Za-z0-9%]+)?$")
CRAWL = re.compile(r"^/(?:\?new=[a-z-]+)?$|^/(?:account|help|read|request|watch)$|^/help/[a-z0-9-]+$"
                   r"|^/search(?:\?q=[A-Za-z0-9%]+)?$|" + TITLE.pattern[1:])
ACTION = re.compile(r'(<form [^>]*action=")(/search)(")')
HREF = re.compile(r'(\bhref=")([^"]*)(")')
SRC_ART = re.compile(r'(<li class="w-([a-z]+)">(?:<a class="card"[^>]*>\s*)?<span class="frame"><span class="ph"'
                     r'[^>]*>[^<]*</span><img class="art" src=")(/art/[^"]*)(")')
STYLE = re.compile(r"<style>(.*?)</style>", re.S)
PLAIN = ("<style>html{background:#000;color:#fff}body{font:18px/1.5 system-ui}a{color:#9ecbff}</style>")
BANNER = ('<div class="review-note" role="note"><a href="{up}index.html">Review index</a> &middot; '
          'Static export, synthetic data. Search shows prepared pages only; links that leave Home are not live.</div>')
NOTE_CSS = (".review-note{font:14px/1.4 system-ui,sans-serif;padding:8px 16px;background:#fff3b0;"
            "color:#111;text-align:center}.review-note a{color:#111;font-weight:600;"
            "display:inline-block;min-height:24px}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Peer:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope, client=PEER)
        await self.app(scope, receive, send)


def slug_of(key: str) -> str:
    if key in SEARCH_SEEDS:
        return SEARCH_SEEDS[key]
    path, _, query = key.partition("?")
    name = "home" if path == "/" else path.strip("/").replace("/", "-")
    if path.startswith("/title/"):                 # title pages: one file per item, the search term dropped
        return re.sub(r"[^A-Za-z0-9-]", "-", name)
    return f"{name}-{query.replace('new=', 'new-')}" if query else name


def placeholder(ref: str, shape: str, title: str) -> str:
    hue = int(hashlib.sha256(ref.encode()).hexdigest()[:4], 16) % 360
    w, h = {"square": (200, 200), "still": (320, 180)}.get(shape, (200, 300))
    letter = html.escape((title.strip()[:1] or "A").upper())
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'<rect width="{w}" height="{h}" fill="hsl({hue},45%,32%)"/>'
            f'<rect x="{w*0.08}" y="{h*0.08}" width="{w*0.84}" height="{h*0.84}" fill="none" '
            f'stroke="hsl({hue},60%,75%)" stroke-width="3"/>'
            f'<text x="{w/2}" y="{h/2+h*0.12}" font-family="sans-serif" font-size="{min(w,h)*0.45}" '
            f'text-anchor="middle" fill="hsl({hue},60%,90%)">{letter}</text></svg>\n')


class Exporter:
    def __init__(self, out: Path, long_titles: bool = True):
        self.out = out
        self.long_titles = long_titles
        self.css: dict[str, str] = {}
        self.art: dict[str, str] = {}

    def start_stack(self):
        from dev import run_dev
        mock, _shim, settings = run_dev.build_stack(
            "127.0.0.1", free_port(), free_port(), True, abs_mock_port=free_port(),
            komga_mock_port=free_port(), calibre_mock_port=free_port())
        mocks = dict(zip(MOCK_KEYS, (mock, mock.abs, mock.komga, mock.calibre)))
        if self.long_titles:      # invented long titles (dev/mock_long_titles.py): real shelves wrap
            from dev import mock_long_titles
            mock_long_titles.apply(mocks)
        return mocks, settings

    def client(self, settings):
        from fastapi.testclient import TestClient
        from avrana_home.app.main import create_app
        return TestClient(Peer(create_app(settings)), base_url="http://portal.test",
                          follow_redirects=False, raise_server_exceptions=False)

    def headers(self, who):
        if who == "signed-out":
            return {}
        name, groups = MEMBERS.get(who) or EXTRA.get(who) or NO_LIBRARY[1]
        return {USER: who, GROUPS: groups, NAME: name}

    def export_scenario(self, key, title, members, down):
        mocks, settings = self.start_stack()
        written = []
        try:
            modes = dict(d.split(":", 1) if ":" in d else (d, "down") for d in down)
            for k, m in mocks.items():
                m.set_mode(modes.get(k, "ok"))
            for who in members:
                c = self.client(settings)
                hdr = self.headers(who)
                pages: dict[str, str] = {}
                titled: set = set()            # at most one title page per library: enough for axe and focus
                queue = ["/", *SEARCH_SEEDS, *TITLE_SEEDS]
                while queue:
                    k = queue.pop(0)
                    if k in pages or not CRAWL.match(k):
                        continue
                    t = TITLE.match(k)
                    if t and (t.group(1) in titled or any(slug_of(p) == slug_of(k) for p in pages)):
                        continue
                    r = c.get(k, headers=hdr)
                    ok = r.status_code == 200 or (t and r.status_code == 503)    # an unavailable title is a page
                    if not ok or "text/html" not in r.headers.get("content-type", ""):
                        continue
                    if t:
                        titled.add(t.group(1))
                    pages[k] = r.text
                    for _a, href, _b in HREF.findall(r.text):
                        if href.startswith("/") and not href.startswith("//"):
                            queue.append(href.split("#")[0])
                    if key != "normal":   # help topics are the same in every state: export them once
                        queue = [q for q in queue if not q.startswith("/help/") or q.startswith("/help/trouble")]
                d = self.out / who / key
                d.mkdir(parents=True, exist_ok=True)
                for k, text in pages.items():
                    (d / f"{slug_of(k)}.html").write_bytes(self.rewrite(text, pages).encode("utf-8"))
                    written.append(f"{who}/{key}/{slug_of(k)}.html")
        finally:
            for m in mocks.values():
                m.stop()
        return written

    def rewrite(self, text: str, pages: dict) -> str:
        def art(m):
            pre, shape, src, post = m.groups()
            title = re.search(r'<span class="t">(.*?)</span>', text[m.end():], re.S)
            name = hashlib.sha256(src.encode()).hexdigest()[:12] + ".svg"
            self.art[name] = placeholder(src, shape, html.unescape(title.group(1)) if title else "A")
            return f"{pre}../../art/{name}{post}"
        text = SRC_ART.sub(art, text)
        text = re.sub(r'(<img class="art" src=")/art/[^"]*(")', r"\1../../art/missing.svg\2", text)

        def link(m):
            pre, href, post = m.groups()
            if href.startswith("#"):
                return m.group(0)
            if href.startswith("/brand/"):                    # the approved brand files, copied by finish()
                return f"{pre}../..{href}{post}"
            if href.startswith("/") and not href.startswith("//"):
                base, _, frag = href.partition("#")
                if base in pages or (TITLE.match(base) and slug_of(base) in {slug_of(p) for p in pages}):
                    return f'{pre}{slug_of(base)}.html{"#" + frag if frag else ""}{post}'
            return f'{pre}../../not-in-export.html{post}'
        text = HREF.sub(link, text)
        text = text.replace('src="/brand/', 'src="../../brand/')
        text = ACTION.sub(r"\g<1>../../not-in-export.html\g<3>", text)     # the search form is not live here
        def sheet(m):
            body = m.group(1).replace('url("/brand/', 'url("../brand/')
            name = "style-" + hashlib.sha256(body.encode()).hexdigest()[:8] + ".css"
            self.css[name] = body
            return f'<link rel="stylesheet" href="../../assets/{name}">'
        text = STYLE.sub(sheet, text)
        text = text.replace("</head>", f"<style>{NOTE_CSS}</style></head>", 1)
        return text.replace("<body>", "<body>\n" + BANNER.format(up="../../"), 1)

    def finish(self, written):
        assets, art = self.out / "assets", self.out / "art"
        assets.mkdir(exist_ok=True)
        art.mkdir(exist_ok=True)
        for n, body in self.css.items():
            (assets / n).write_bytes(body.encode("utf-8"))
        for n, body in self.art.items():
            (art / n).write_bytes(body.encode("utf-8"))
        (art / "missing.svg").write_bytes(placeholder("missing", "poster", "A").encode())
        from avrana_home.app import brand                     # the shell's approved brand files (AVR-584)
        (self.out / "brand").mkdir(exist_ok=True)
        for route in brand.ROUTES:
            (self.out / route.lstrip("/")).write_bytes(brand.asset_for(route)[0])
        stub_note = ('<p><a href="index.html">Back to the review index</a></p>')
        (self.out / "not-in-export.html").write_bytes((
            '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width, initial-scale=1"><meta name="color-scheme" content="dark">'
            '<title>Not in this export</title>' + PLAIN + '</head><body style="padding:24px">'
            '<main><h1>Not in this export</h1><p>This link leaves Home for a real service, sign-in or '
            'sign-out, or it is the search box, which has no server behind it here. The review export is static '
            'and has no live services. Open the prepared search pages from the review index.</p>' + stub_note +
            '</main></body></html>\n').encode())
        rows = []
        for key, (title, members, _d) in SCENARIOS.items():
            for who in members:
                label = {"signed-out": "Signed out"}.get(who, who)
                links = sorted(w for w in written if w.startswith(f"{who}/{key}/"))
                items = " ".join(f'<a href="{quote(w)}">{html.escape(Path(w).stem)}</a>' for w in links)
                rows.append(f"<li><strong>{html.escape(title)}</strong> &middot; {html.escape(label)}"
                            f"<br>{items}</li>")
        (self.out / "index.html").write_bytes((
            '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width, initial-scale=1"><meta name="color-scheme" content="dark">'
            '<title>Avrana Home review</title>' + PLAIN + '<style>body{margin:0;padding:16px}'
            'li{margin:0 0 16px}a{display:inline-block;min-height:44px;line-height:44px;margin-right:12px}'
            '</style></head><body><main><h1>Avrana Home: device review</h1>'
            '<p>Static export. Synthetic data only. Start with <em>home</em> in each row.</p><ul>'
            + "\n".join(rows) + '</ul></main></body></html>\n').encode())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="folder to write (emptied first if it holds an earlier export)")
    ap.add_argument("--short-titles", action="store_true",
                    help="serve the fixtures' short titles as they are (default: the invented long-title overlay)")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    if out.exists():
        if any(out.iterdir()) and not (out / "not-in-export.html").is_file():
            print(f"refusing: {out} is not empty and is not an earlier export", file=sys.stderr)
            return 2
        for child in out.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)
    ex = Exporter(out, long_titles=not args.short_titles)
    written = []
    for key, (title, members, down) in SCENARIOS.items():
        written += ex.export_scenario(key, title, members, down)
    ex.finish(written)
    print(f"wrote {len(written)} pages to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
