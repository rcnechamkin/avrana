#!/usr/bin/env python3
"""Avrana Kindle Connector - set your Send-to-Kindle address once, in both libraries.

Adding a @kindle.com address means editing it in TWO places (Calibre-Web and Audiobookshelf),
in two different admin UIs, and getting the Amazon side right as well. This does the two library
sides automatically and points at the exact Amazon page for the part that cannot be automated.

IT SITS BEHIND AUTHENTIK'S EMBEDDED PROXY OUTPOST, like the portal: no host port is published,
the outpost authenticates and injects X-authentik-* headers, and it strips any the client tried
to send. Access is gated on `avrana-books` - the group that has ebooks at all.

THE TWO LIBRARIES STORE THIS COMPLETELY DIFFERENTLY, which is most of the work here:

  Calibre-Web  user.kindle_mail, a per-user column, comma-separated for multiple addresses.
               Written straight to app.db: it is plaintext (unlike mail_password_e) and
               Calibre-Web reloads the user row per request, so the change is picked up live.

  Audiobookshelf  a single GLOBAL ereaderDevices array, updated by full-array PATCH. A device is
               scoped to one person with availabilityOption "specificUsers" + their user id, so
               nobody sees anybody else's Kindle. NOTE: ABS silently coerces that back to
               "adminOrUp" if the users list is empty - verified against 2.36.0 - so an unscoped
               write would quietly expose the address to every admin.

  Because that array is global and written whole, two people saving at once would clobber each
  other. Every write re-reads the array immediately before modifying it, under a process lock.
"""
from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CWA_DB = os.environ.get("CWA_DB", "/cwa/app.db")
ABS_URL = os.environ.get("ABS_URL", "http://10.0.0.218:13378")
ABS_KEY = os.environ.get("ABS_API_KEY", "")
REQUIRED_GROUP = os.environ.get("REQUIRED_GROUP", "avrana-books")
SENDER = os.environ.get("SENDER_ADDRESS", "cody@avrana.net")

USERNAME_HEADER = "X-authentik-username"
EMAIL_HEADER = "X-authentik-email"
GROUPS_HEADER = "X-authentik-groups"

# Amazon's Personal Document Settings page shows BOTH the @kindle.com addresses and the approved
# sender list, which is exactly the two things a person needs from Amazon.
AMAZON_PDOC = "https://www.amazon.com/hz/mycd/myx#/home/settings/pdoc"

# Deliberately strict. A typo here means books silently vanish: Amazon drops mail addressed to a
# non-existent @kindle.com without telling anyone.
KINDLE_RE = re.compile(r"^[A-Za-z0-9._%+-]+@kindle\.com$", re.I)

_abs_lock = threading.Lock()


# ---------------------------------------------------------------- helpers
def parse_groups(raw: str) -> set[str]:
    for sep in ("|", ","):
        raw = raw.replace(sep, "\n")
    return {g.strip() for g in raw.split("\n") if g.strip()}


def abs_call(path: str, method: str = "GET", body=None):
    req = urllib.request.Request(
        f"{ABS_URL}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {ABS_KEY}", "Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=20).read()
    return json.loads(raw) if raw else {}


def cwa_find(username: str, email: str):
    """Calibre-Web accounts are LDAP-provisioned, so the username matches Authentik; email is a
    fallback for anyone created before that."""
    con = sqlite3.connect(f"file:{CWA_DB}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT id, name, kindle_mail FROM user WHERE lower(name)=lower(?)",
                          (username,)).fetchone()
        if row is None and email:
            row = con.execute("SELECT id, name, kindle_mail FROM user WHERE lower(email)=lower(?)",
                              (email,)).fetchone()
        return row
    finally:
        con.close()


def cwa_set(user_id: int, address: str | None):
    con = sqlite3.connect(CWA_DB, timeout=15)
    try:
        with con:
            con.execute("UPDATE user SET kindle_mail=? WHERE id=?", (address, user_id))
    finally:
        con.close()


def abs_find(username: str, email: str):
    for u in abs_call("/api/users").get("users", []):
        if u["username"].lower() == username.lower():
            return u
        if email and (u.get("email") or "").lower() == email.lower():
            return u
    return None


def abs_devices():
    return abs_call("/api/emails/settings").get("settings", {}).get("ereaderDevices", []) or []


def abs_set(abs_user, address: str | None, label: str):
    """Replace this user's device entry, leaving everyone else's untouched."""
    with _abs_lock:
        devices = [d for d in abs_devices()
                   if not (d.get("users") == [abs_user["id"]] or d.get("name") == label)]
        if address:
            devices.append({
                "name": label,
                "email": address,
                # Without a non-empty users list ABS downgrades this to adminOrUp.
                "availabilityOption": "specificUsers",
                "users": [abs_user["id"]],
            })
        abs_call("/api/emails/settings", "PATCH", {"ereaderDevices": devices})
    return devices


# ---------------------------------------------------------------- view
STYLE = """
  :root{--bg:#000;--fg:#fff;--dim:#9a9a9a;--line:rgba(255,255,255,.28);--strong:rgba(255,255,255,.6);
        --err:#ff8b8b;--ok:#8fe3a6;}
  *{box-sizing:border-box}html,body{margin:0;padding:0}
  body{background:var(--bg);color:var(--fg);font-family:"Times New Roman",Times,serif;
    min-height:100vh;display:flex;justify-content:center;-webkit-font-smoothing:antialiased}
  main{width:100%;max-width:640px;padding:10vh 24px 8vh;display:flex;flex-direction:column;gap:36px}
  header{text-align:center;display:flex;flex-direction:column;gap:14px;align-items:center}
  h1{margin:0;font-weight:400;font-size:clamp(2rem,7vw,3rem);letter-spacing:.28em;text-indent:.28em;line-height:1}
  h1 a{color:inherit;text-decoration:none}
  .rule{width:64px;height:1px;background:var(--strong)}
  h2{margin:0;font-weight:400;font-size:1rem;letter-spacing:.22em;text-transform:uppercase;color:var(--dim)}
  section{display:flex;flex-direction:column;gap:14px}
  p{margin:0;line-height:1.55}p.note{color:var(--dim);font-size:.97rem}
  input[type=email]{width:100%;padding:12px 14px;background:transparent;color:var(--fg);
    border:1px solid var(--line);border-radius:0;font:inherit}
  input[type=email]:focus{outline:none;border-color:var(--fg)}
  button{font:inherit;padding:12px 20px;border-radius:0;cursor:pointer;letter-spacing:.06em;
    background:var(--fg);color:var(--bg);border:1px solid var(--fg);transition:background .16s,color .16s}
  button:hover,button:focus-visible{background:transparent;color:var(--fg);outline:none}
  button.ghost{background:transparent;color:var(--fg);border-color:var(--line)}
  button.ghost:hover{background:var(--fg);color:var(--bg)}
  .row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
  a{color:var(--fg)}
  a.plain{text-decoration:none;border-bottom:1px solid var(--strong);padding-bottom:2px}
  a.plain:hover{border-color:var(--fg)}
  dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:10px 24px;align-items:baseline}
  dt{color:var(--dim);font-size:.85rem;letter-spacing:.08em;text-transform:uppercase}
  dd{margin:0;overflow-wrap:anywhere}
  .banner{border:1px solid var(--line);padding:12px 16px}
  .banner.err{border-color:var(--err);color:var(--err)}
  .banner.ok{border-color:var(--ok);color:var(--ok)}
  ol{margin:0;padding-left:1.3rem;color:var(--dim)}ol li{margin:.45rem 0}
  footer{display:flex;justify-content:center;gap:24px;flex-wrap:wrap}
  @media(max-width:560px){main{padding:8vh 20px 6vh;gap:28px}dl{grid-template-columns:1fr;gap:2px}}
"""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Kindle · Avrana</title><style>{style}</style></head><body><main>
<header><h1><a href="https://avrana.net">AVRANA</a></h1><div class="rule"></div></header>
{banner}
<section>
  <h2>Your Kindle address</h2>
  {current}
  <form method="post" action="/save">
    <div class="row">
      <input type="email" name="address" placeholder="yourname_abc123@kindle.com"
             value="{value}" aria-label="Send-to-Kindle address" required>
    </div>
    <p class="note">It must end in <strong>@kindle.com</strong>. Amazon discards books sent to an
      address that does not exist, without telling anyone, so this is checked before saving.</p>
    <div class="row" style="margin-top:14px">
      <button type="submit">Save to both libraries</button>
      {remove}
    </div>
  </form>
</section>
<section>
  <h2>The Amazon half</h2>
  <p class="note">Amazon will not accept books from an address it does not recognise, and that
    part cannot be automated. On the page below you can do both things at once:</p>
  <ol>
    <li>Copy your <strong>Send-to-Kindle e-mail</strong> (it ends in @kindle.com) and paste it above.</li>
    <li>Under <strong>Approved Personal Document E-mail List</strong>, add
        <strong>{sender}</strong>. Without this, books are silently dropped.</li>
  </ol>
  <p><a class="plain" href="{amazon}" target="_blank" rel="noopener noreferrer">
     Open Amazon Personal Document Settings</a></p>
</section>
<footer>
  <a class="plain" href="https://books.avrana.net">Calibre&#8209;Web</a>
  <a class="plain" href="https://listen.avrana.net">Audiobookshelf</a>
  <a class="plain" href="https://avrana.net">Back to Avrana</a>
</footer>
</main></body></html>
"""


def render(current_cwa, current_abs, value="", banner=None, can_remove=False):
    rows = []
    rows.append(f"<dt>Calibre-Web</dt><dd>{html.escape(current_cwa or 'not set')}</dd>")
    rows.append(f"<dt>Audiobookshelf</dt><dd>{html.escape(current_abs or 'not set')}</dd>")
    cur = f'<dl>{"".join(rows)}</dl>'
    b = ""
    if banner:
        kind, msg = banner
        b = f'<div class="banner {kind}">{html.escape(msg)}</div>'
    rm = ('<button class="ghost" type="submit" formaction="/remove" formnovalidate>Remove</button>'
          if can_remove else "")
    return PAGE.format(style=STYLE, banner=b, current=cur, value=html.escape(value),
                       remove=rm, amazon=AMAZON_PDOC, sender=html.escape(SENDER))


def render_denied():
    return PAGE.format(
        style=STYLE, banner='<div class="banner">This is for Avrana ebook members.</div>',
        current="", value="", remove="", amazon=AMAZON_PDOC, sender=html.escape(SENDER))


# ---------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    server_version = "avrana-kindle/1"

    def _send(self, code, body, ctype="text/html; charset=utf-8", location=None):
        data = body.encode()
        self.send_response(code)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _hdr(self, n):
        return (self.headers.get(n) or "").strip()

    def _identity(self):
        return self._hdr(USERNAME_HEADER), self._hdr(EMAIL_HEADER), parse_groups(self._hdr(GROUPS_HEADER))

    def _state(self, username, email):
        cwa = cwa_find(username, email)
        absu = abs_find(username, email)
        cwa_val = (cwa[2] if cwa else None) or None
        abs_val = None
        if absu:
            for d in abs_devices():
                if d.get("users") == [absu["id"]]:
                    abs_val = d.get("email")
                    break
        return cwa, absu, cwa_val, abs_val

    def do_GET(self):
        route = self.path.split("?", 1)[0].rstrip("/") or "/"
        if route == "/healthz":
            return self._send(200, "ok", "text/plain; charset=utf-8")
        username, email, groups = self._identity()
        if REQUIRED_GROUP not in groups:
            return self._send(403, render_denied())
        cwa, absu, cwa_val, abs_val = self._state(username, email)
        banner = None
        if not cwa and not absu:
            banner = ("err", "No Calibre-Web or Audiobookshelf account found for this login.")
        return self._send(200, render(cwa_val, abs_val, cwa_val or abs_val or "",
                                      banner, bool(cwa_val or abs_val)))

    def do_POST(self):
        route = self.path.split("?", 1)[0].rstrip("/") or "/"
        username, email, groups = self._identity()
        if REQUIRED_GROUP not in groups:
            return self._send(403, render_denied())

        length = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        address = (form.get("address", [""])[0] or "").strip()

        cwa, absu, cwa_val, abs_val = self._state(username, email)

        if route == "/remove":
            written = []
            if cwa:
                cwa_set(cwa[0], None); written.append("Calibre-Web")
            if absu:
                abs_set(absu, None, f"Kindle ({username})"); written.append("Audiobookshelf")
            cwa, absu, cwa_val, abs_val = self._state(username, email)
            return self._send(200, render(cwa_val, abs_val, "",
                                          ("ok", "Removed from " + " and ".join(written) + ".") if written
                                          else ("err", "Nothing to remove."), False))

        if route != "/save":
            return self._send(404, render_denied())

        if not KINDLE_RE.match(address):
            return self._send(200, render(cwa_val, abs_val, address,
                                          ("err", "That is not a @kindle.com address."),
                                          bool(cwa_val or abs_val)))

        written, failed = [], []
        if cwa:
            try:
                cwa_set(cwa[0], address); written.append("Calibre-Web")
            except Exception:
                failed.append("Calibre-Web")
        if absu:
            try:
                abs_set(absu, address, f"Kindle ({username})"); written.append("Audiobookshelf")
            except Exception:
                failed.append("Audiobookshelf")

        cwa, absu, cwa_val, abs_val = self._state(username, email)
        if failed:
            msg = ("err", "Saved to " + (" and ".join(written) or "nothing") +
                   "; failed for " + " and ".join(failed) + ".")
        elif written:
            msg = ("ok", "Saved to " + " and ".join(written) +
                   ". Remember to approve " + SENDER + " on Amazon.")
        else:
            msg = ("err", "No library account found for this login.")
        return self._send(200, render(cwa_val, abs_val, address, msg, bool(cwa_val or abs_val)))

    do_HEAD = do_GET

    def log_message(self, *a):
        pass  # no per-request identity in logs


def main():
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8096"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
