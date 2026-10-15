#!/usr/bin/env python3
"""Serve every registry page from loopback, for the browser layer (check.mjs). Development tool.

    python -B tests/ui/harness/serve.py [--port 0] [--host 127.0.0.1]

Binds only to loopback (it refuses any other host). Prints one line `LISTENING http://127.0.0.1:PORT`
once ready, then serves until stopped:

    /                          an index of every page, with its identity, expected visibility, status
    /manifest.json             the same as JSON (what check.mjs reads)
    /p/<service>/<page>/<id>   the page exactly as the service rendered it (status code preserved)
    /a/<service>/<path>        assets a registry entry declared (Rendered.assets)

Pages are rendered once, offline, from the services' own code with fixture identities. Nothing here
talks to a network or a live service; links on the pages lead nowhere (they are not followed).
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import pages  # noqa: E402


def build(registry):
    """(manifest, bodies): manifest rows for check.mjs, and key -> Rendered for the server."""
    manifest, bodies = [], {}
    for p in registry.pages():
        rendered, why = p.produce()
        row = {"id": p.key, "service": p.service, "page": p.page, "identity": p.identity.id,
               "identityClass": p.identity.klass, "visibility": p.visibility, "tags": list(p.tags),
               "needsJs": p.needs_js, "url": f"/p/{p.key}", "available": rendered is not None}
        if rendered is None:
            row["unavailable"] = why
        else:
            row["status"] = rendered.status
            bodies[p.key] = rendered
        manifest.append(row)
    return manifest, bodies


def make_handler(manifest, bodies):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def _send(self, code, data, ctype="text/html; charset=utf-8", csp=True):
            if isinstance(data, str):
                data = data.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if csp:   # no script anywhere unless a page declares it needs one; no network
                self.send_header("Content-Security-Policy",
                                 "default-src 'none'; style-src 'unsafe-inline' 'self'; img-src data: 'self'; font-src 'self'; base-uri 'none'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                rows = "".join(
                    f'<tr><td><a href="{html.escape(r["url"])}">{html.escape(r["id"])}</a></td>'
                    f'<td>{html.escape(r["visibility"])}</td><td>{r.get("status", "")}</td>'
                    f'<td>{html.escape(r.get("unavailable", ""))}</td></tr>' for r in manifest)
                return self._send(200, "<!doctype html><html lang=en><meta charset=utf-8><title>Harness pages</title>"
                                       "<style>body{font:15px sans-serif;margin:24px}td,th{padding:3px 12px;text-align:left}</style>"
                                       f"<h1>Harness pages ({len(manifest)})</h1><table><tr><th>Page<th>Visibility<th>Status<th>Note</tr>"
                                       f"{rows}</table>")
            if path == "/manifest.json":
                return self._send(200, json.dumps({"pages": manifest}), "application/json", csp=False)
            if path.startswith("/p/"):
                r = bodies.get(path[3:])
                if r is None:
                    return self._send(404, "no such page", "text/plain; charset=utf-8")
                js = next((m["needsJs"] for m in manifest if m["id"] == path[3:]), False)
                body = r.html
                if r.status != 200:
                    pass   # the browser still renders the body; the manifest records the status
                return self._send(200, body, csp=not js)
            if path.startswith("/a/"):
                for r in bodies.values():
                    if path[2:] in r.assets:
                        return self._send(200, r.assets[path[2:]], "application/octet-stream")
            return self._send(404, "not found", "text/plain; charset=utf-8")

        do_HEAD = do_GET

        def log_message(self, *a):
            pass
    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args(argv)
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print("refusing to bind to a non-loopback address", file=sys.stderr)
        return 2
    manifest, bodies = build(pages.build_registry())
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(manifest, bodies))
    print(f"LISTENING http://{a.host}:{srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
