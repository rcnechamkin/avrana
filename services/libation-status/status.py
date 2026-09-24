#!/usr/bin/env python3
# Tiny read-only status endpoint for Libation, for the Homepage customapi widget.
# Serves JSON at GET / :
#   {"library":N,"downloaded":N,"pending":N,"percent":N,"state":"Downloading|Idle"}
#
# Data sources (both mounted READ-ONLY):
#   /data/LibationContext.db   -> UserDefinedItem.BookStatus (1=Liberated, 0=not)
#   /inprogress/               -> Libation's on-disk staging; non-empty = active
# No secrets are read (AccountsSettings.json / master key are NOT mounted).
import http.server, socketserver, json, sqlite3, os

DB = "/data/LibationContext.db"
INPROG = "/inprogress"
PORT = 8087

def compute():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=3)
    try:
        cur = con.cursor()
        total = cur.execute("SELECT COUNT(*) FROM UserDefinedItem").fetchone()[0]
        done = cur.execute("SELECT COUNT(*) FROM UserDefinedItem WHERE BookStatus=1").fetchone()[0]
    finally:
        con.close()
    active = False
    for sub in ("DownloadsInProgress", "DecryptInProgress"):
        d = os.path.join(INPROG, sub)
        try:
            if os.path.isdir(d) and any(os.scandir(d)):
                active = True
                break
        except OSError:
            pass
    return {
        "library": total,
        "downloaded": done,
        "pending": total - done,
        "percent": round(done * 100 / total) if total else 0,
        "state": "Downloading" if active else "Idle",
    }

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body = json.dumps(compute()).encode()
        except Exception as e:  # keep returning 200 so the widget shows something
            body = json.dumps({"error": str(e), "state": "Unknown"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        httpd.serve_forever()
