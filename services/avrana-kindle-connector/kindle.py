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
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CWA_DB = os.environ.get("CWA_DB", "/cwa/app.db")
ABS_URL = os.environ.get("ABS_URL", "http://10.0.0.218:13378")
ABS_KEY = os.environ.get("ABS_API_KEY", "")
REQUIRED_GROUP = os.environ.get("REQUIRED_GROUP", "avrana-books")
# Only decides whether the page may link to Audiobookshelf. It never gates access and never decides what is written.
AUDIOBOOKS_GROUP = os.environ.get("AUDIOBOOKS_GROUP", "avrana-audiobooks")
SENDER = os.environ.get("SENDER_ADDRESS", "cody@avrana.net")

USERNAME_HEADER = "X-authentik-username"
EMAIL_HEADER = "X-authentik-email"
GROUPS_HEADER = "X-authentik-groups"

# Amazon's Personal Document Settings page shows BOTH the @kindle.com addresses and the approved
# sender list, which is exactly the two things a person needs from Amazon.
AMAZON_PDOC = "https://www.amazon.com/hz/mycd/myx#/home/settings/pdoc"

# Deliberately strict. A typo here means books silently vanish: Amazon drops mail addressed to a
# non-existent @kindle.com without telling anyone.
# re.A: without it, Unicode case folding makes U+212A (Kelvin sign) match "k" and U+0131 match "i".
KINDLE_RE = re.compile(r"^[A-Za-z0-9._%+-]+@kindle\.com\Z", re.I | re.A)

MAX_BODY = 16384       # bytes; the only field is one address
MAX_ADDRESS = 254      # RFC 5321 path limit; Kindle addresses are far shorter

_abs_lock = threading.Lock()


def load_aliases(raw: str) -> dict[str, str]:
    """Parse KINDLE_USERNAME_ALIASES: comma- or space-separated `authentik_username=library_username`.

    The ONLY way a login whose Authentik username differs from its library username (the admin is
    `akadmin` in Authentik and `Cody` in the libraries) is matched. Set by the owner, empty by
    default, never derived from request data. Exact match on the Authentik username; the target is
    then looked up in both libraries like any other username. Malformed entries are ignored; a map
    that is ambiguous (a target that is also a source, two sources sharing a target, one source
    given two targets) is refused whole. Only counts are logged, never names.
    """
    pairs, bad, conflict = {}, 0, False
    for tok in re.split(r"[,\s]+", raw or ""):
        if not tok:
            continue
        src, sep, dst = tok.partition("=")
        if not sep or not src or not dst or "=" in dst:
            bad += 1
        elif src in pairs and pairs[src] != dst:
            conflict = True
        else:
            pairs[src] = dst
    targets = [t.lower() for t in pairs.values()]
    if conflict or len(set(targets)) != len(targets) or any(t in {k.lower() for k in pairs} for t in targets):
        print(f"kindle: username alias map refused ({len(pairs)} usable entries); no aliases in effect",
              file=sys.stderr)
        return {}
    if bad:
        print(f"kindle: ignored {bad} malformed username alias entries", file=sys.stderr)
    return pairs


ALIASES = load_aliases(os.environ.get("KINDLE_USERNAME_ALIASES", ""))


def library_name(username: str):
    """The name to look up in Calibre-Web and Audiobookshelf for this Authentik username, or None.

    None (fail closed) when the username is the target of an alias but is not that alias's source:
    otherwise a second Authentik user literally named like the aliased library account would share
    it. The e-mail header plays no part in resolution - it is user-editable and not unique.
    """
    if username in ALIASES:
        return ALIASES[username]
    if username.lower() in {t.lower() for t in ALIASES.values()}:
        return None
    return username


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


def _pick(rows, name_of, wanted: str):
    """Resolve `wanted` to ONE row. Returns (row_or_None, any_candidate).

    The match is case-insensitive (Authentik and the libraries do not agree on case) but exact case
    wins, and two candidates that cannot be told apart resolve to nobody rather than to whichever
    was listed first - the first match is not necessarily the right person.
    """
    folded = [r for r in rows if name_of(r).lower() == wanted.lower()]
    exact = [r for r in folded if name_of(r) == wanted]
    if len(exact) == 1:
        return exact[0], True
    if exact:
        return None, True
    return (folded[0] if len(folded) == 1 else None), bool(folded)


def cwa_find(username: str):
    """Calibre-Web accounts are LDAP-provisioned, so the username matches Authentik (see
    KINDLE_USERNAME_ALIASES for the exceptions). The username is the only join key."""
    if not username:
        return None
    con = sqlite3.connect(f"file:{CWA_DB}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT id, name, kindle_mail FROM user WHERE lower(name)=lower(?) ORDER BY id",
                           (username,)).fetchall()
        return _pick(rows, lambda r: r[1] or "", username)[0]
    finally:
        con.close()


def cwa_set(user_id: int, address: str | None):
    con = sqlite3.connect(CWA_DB, timeout=15)
    try:
        with con:
            con.execute("UPDATE user SET kindle_mail=? WHERE id=?", (address, user_id))
    finally:
        con.close()


def abs_find(username: str):
    """Same rule as cwa_find: the username decides, nothing else."""
    if not username:
        return None
    users = abs_call("/api/users").get("users", [])
    return _pick(users, lambda u: u.get("username") or "", username)[0]


def abs_devices():
    return abs_call("/api/emails/settings").get("settings", {}).get("ereaderDevices", []) or []


def abs_set(abs_user, address: str | None, label: str):
    """Replace this user's device entry, leaving everyone else's untouched."""
    with _abs_lock:
        # Drop only what is this user's: scoped to exactly them, or an unscoped leftover that carries
        # their label. A device scoped to someone else is never touched, even if its name collides.
        devices = [d for d in abs_devices()
                   if not (d.get("users") == [abs_user["id"]] or (d.get("name") == label and not d.get("users")))]
        if address:
            if any(d.get("name") == label for d in devices):
                label = f"{label} #{abs_user['id']}"  # keep names unique without touching the other device
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
# Tokens are the names and values in docs/design/DESIGN.md. Interactive edges use --rule-control (4.1:1 on
# --ink, WCAG 1.4.11); --rule-quiet is for dividers only. Every interactive element shows the same
# two-ring focus mark on :focus-visible, kept apart from the hover inversion. tests/test_a11y.py
# computes contrast, focus and target size from this sheet.
STYLE = """
  :root{color-scheme:dark;--ink:#000000;--paper:#ffffff;--ash:#9a9a9a;--rule-quiet:#474747;
        --rule-control:#6e6e6e;--rule-strong:#999999;--ok:#8fe3a6;--err:#ff8b8b;
        --ring:0 0 0 2px #000000,0 0 0 4px #ffffff}
  *{box-sizing:border-box}html,body{margin:0;padding:0}
  body{background:var(--ink);color:var(--paper);
    font-family:"Times New Roman",Times,"Liberation Serif",Tinos,"Noto Serif",serif;
    min-height:100vh;display:flex;justify-content:center;-webkit-font-smoothing:antialiased}
  main{width:100%;max-width:640px;padding:10vh 24px 8vh;display:flex;flex-direction:column;gap:36px}
  header{text-align:center;display:flex;flex-direction:column;gap:14px;align-items:center}
  h1{margin:0;font-weight:400;font-size:clamp(2rem,7vw,3rem);letter-spacing:.28em;text-indent:.28em;line-height:1;
    overflow-wrap:anywhere}
  h1 a{color:inherit;text-decoration:none}
  .rule{width:64px;height:1px;background:var(--rule-strong)}
  h2{margin:0;font-weight:400;font-size:1rem;letter-spacing:.22em;text-transform:uppercase;color:var(--ash)}
  section{display:flex;flex-direction:column;gap:14px}
  p{margin:0;line-height:1.55}p.note{color:var(--ash);font-size:.97rem}
  p.hint{margin-top:8px}
  label{display:block;margin-bottom:8px}
  input[type=email]{width:100%;min-height:48px;padding:12px 14px;background:transparent;color:var(--paper);
    border:1px solid var(--rule-control);border-radius:0;font:inherit}
  input[type=email]::placeholder{color:var(--ash);opacity:1}
  input[type=email]:focus{border-color:var(--paper)}
  button{font:inherit;min-height:44px;padding:12px 20px;border-radius:0;cursor:pointer;letter-spacing:.06em;
    background:var(--paper);color:var(--ink);border:1px solid var(--paper);transition:background .16s,color .16s}
  button:hover,button:focus-visible{background:transparent;color:var(--paper)}
  button.ghost{background:transparent;color:var(--paper);border-color:var(--rule-control)}
  button.ghost:hover,button.ghost:focus-visible{background:var(--paper);color:var(--ink)}
  a:focus-visible,button:focus-visible,input:focus-visible{box-shadow:var(--ring);outline:2px solid transparent}
  .row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
  .actions{margin-top:14px}
  a{color:var(--paper)}
  a.plain{display:inline-flex;align-items:center;min-height:44px;text-decoration:underline;
    text-decoration-color:var(--rule-strong);text-decoration-thickness:1px;text-underline-offset:2px}
  a.plain:hover{text-decoration-color:var(--paper)}
  dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:10px 24px;align-items:baseline}
  dt{color:var(--ash);font-size:.92rem}
  dd{margin:0;overflow-wrap:anywhere}
  .banner{border:1px solid var(--rule-quiet);padding:12px 16px}
  .banner.err{border-color:var(--err);color:var(--err)}
  .banner.ok{border-color:var(--ok);color:var(--ok)}
  ol{margin:0;padding-left:1.3rem;color:var(--ash)}ol li{margin:.45rem 0}
  footer{display:flex;justify-content:center;gap:0 24px;flex-wrap:wrap}
  @media(max-width:560px){main{padding:8vh 20px 6vh;gap:28px}dl{grid-template-columns:1fr;gap:2px}
    dd{margin-bottom:12px}dd:last-child{margin-bottom:0}}
  @media(prefers-reduced-motion:reduce){button{transition:none}}
"""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="robots" content="noindex, nofollow">
<title>Kindle · Avrana</title><style>{style}</style></head><body><main>
<header><h1><a href="https://avrana.net">AVRANA</a></h1><div class="rule"></div></header>
{banner}
<section>
  <h2>Your Kindle address</h2>
  {current}
  <form method="post" action="/save">
    <div>
      <label for="address">Send-to-Kindle address</label>
      <input type="email" id="address" name="address" placeholder="yourname_abc123@kindle.com"
             value="{value}" autocomplete="off" inputmode="email" autocapitalize="none" spellcheck="false"
             aria-describedby="{describedby}"{invalid} required>
    </div>
    <p class="note hint" id="address-hint">It must end in <strong>@kindle.com</strong>. Amazon discards books sent to an
      address that does not exist, without telling anyone, so this is checked before saving.</p>
    <div class="row actions">
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
  {audiobooks}<a class="plain" href="https://avrana.net">Back to Avrana</a>
</footer>
</main></body></html>
"""

AUDIOBOOKSHELF_LINK = '<a class="plain" href="https://listen.avrana.net">Audiobookshelf</a>\n  '


def render(current_cwa, current_abs, value="", banner=None, can_remove=False, invalid=False, audiobooks=False):
    """`invalid`: the value in the field was just rejected (aria-invalid, tied to the banner).
    `audiobooks`: the member also holds AUDIOBOOKS_GROUP, so the Audiobookshelf link may be shown. This
    changes only what is shown; which libraries get written is decided by the accounts found."""
    rows = []
    rows.append(f"<dt>Calibre-Web</dt><dd>{html.escape(current_cwa or 'not set')}</dd>")
    rows.append(f"<dt>Audiobookshelf</dt><dd>{html.escape(current_abs or 'not set')}</dd>")
    cur = f'<dl>{"".join(rows)}</dl>'
    b, describedby = "", "address-hint"
    if banner:
        kind, msg = banner
        role = "alert" if kind == "err" else "status"
        b = f'<div class="banner {kind}" id="notice" role="{role}">{html.escape(msg)}</div>'
        if invalid:
            describedby = "notice address-hint"
    rm = ('<button class="ghost" type="submit" formaction="/remove" formnovalidate>Remove</button>'
          if can_remove else "")
    return PAGE.format(style=STYLE, banner=b, current=cur, value=html.escape(value),
                       remove=rm, amazon=AMAZON_PDOC, sender=html.escape(SENDER),
                       describedby=describedby, invalid=' aria-invalid="true"' if invalid else "",
                       audiobooks=AUDIOBOOKSHELF_LINK if audiobooks else "")


# The 404 is its own minimal document, not a cut-down PAGE: PAGE's <title> says "Kindle", which would
# tell a non-member what lives here. The title is the portal's, character for character.
NOT_FOUND = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="robots" content="noindex, nofollow">
<title>Not found · Avrana</title><style>{style}</style></head><body><main>
<header><h1><a href="https://avrana.net">AVRANA</a></h1><div class="rule"></div></header>
<section><p class="note">That page does not exist.</p></section>
<footer><a class="plain" href="https://avrana.net">Back to Avrana</a></footer>
</main></body></html>
"""


def render_not_found():
    """The 404 for everyone who is not a member (and for every unknown route): nothing about Kindle,
    Amazon, the libraries or the sender address. 404 rather than 403 so that the existence of this
    tool is not disclosed (audit finding A5, same rule as the portal)."""
    return NOT_FOUND.format(style=STYLE)


# ---------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    server_version = "avrana-kindle/1"
    # HTTP/1.0 (the stdlib default): every response closes the connection. Replies that are sent
    # without reading the request body (404, 400, 413) rely on that; do not switch to keep-alive.
    protocol_version = "HTTP/1.0"
    # Per-connection socket timeout: a client that trickles or stalls cannot pin a thread.
    timeout = 15

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

    def _member(self):
        """Library username of a permitted member, or None. Anything else is a 404.

        Fails closed: each identity header may appear at most once (a repeated line means something
        other than the outpost wrote it, and which copy wins is not worth guessing), and a member
        with no username has no usable identity - without it the lookups would fall back to e-mail
        alone, which resolves to whoever owns that address.
        """
        for name in (USERNAME_HEADER, EMAIL_HEADER, GROUPS_HEADER):
            if len(self.headers.get_all(name) or []) > 1:
                return None
        username, _email, groups = self._identity()
        if REQUIRED_GROUP not in groups or not username:
            return None
        return library_name(username)

    def _audiobooks(self):
        """True when the member also holds the audiobooks group (display only, see AUDIOBOOKS_GROUP)."""
        return AUDIOBOOKS_GROUP in self._identity()[2]

    def _state(self, username):
        cwa = cwa_find(username)
        absu = abs_find(username)
        cwa_val = (cwa[2] if cwa else None) or None
        abs_val = None
        if absu:
            for d in abs_devices():
                if d.get("users") == [absu["id"]]:
                    abs_val = d.get("email")
                    break
        return cwa, absu, cwa_val, abs_val

    def _read_state(self, username):
        """State, or None when a library cannot be read (the caller answers 503, nothing written)."""
        try:
            return self._state(username)
        except Exception:
            return None

    def _unavailable(self):
        return self._send(503, "temporarily unavailable", "text/plain; charset=utf-8")

    def _refresh(self, username, before, failed):
        """Re-read state after a write. If a write already failed and the read does too (the library
        that failed is probably down), answer from whatever can still be read, falling back to the
        pre-write state, rather than dropping the connection after the other library was already
        changed. Returns None only when nothing failed and the read does (the caller answers 503)."""
        state = self._read_state(username)
        if state is not None:
            return state
        if not failed:
            return None
        try:
            cwa = cwa_find(username)
        except Exception:
            return before
        return cwa, before[1], (cwa[2] if cwa else None) or None, before[3]

    def do_GET(self):
        route = self.path.split("?", 1)[0].rstrip("/") or "/"
        if route == "/healthz":
            return self._send(200, "ok", "text/plain; charset=utf-8")
        username = self._member()
        if username is None:
            return self._send(404, render_not_found())
        state = self._read_state(username)
        if state is None:
            return self._unavailable()
        cwa, absu, cwa_val, abs_val = state
        banner = None
        if not cwa and not absu:
            banner = ("err", "No Calibre-Web or Audiobookshelf account found for this login.")
        return self._send(200, render(cwa_val, abs_val, cwa_val or abs_val or "",
                                      banner, bool(cwa_val or abs_val), audiobooks=self._audiobooks()))

    def do_POST(self):
        route = self.path.split("?", 1)[0].rstrip("/") or "/"
        username = self._member()
        if username is None or route not in ("/save", "/remove"):
            return self._send(404, render_not_found())

        # The form is one short field. Refuse anything else up front: a negative length makes
        # rfile.read() wait for EOF and a huge one waits for bytes that never come, each pinning a
        # server thread; a non-numeric one used to raise and drop the connection.
        raw_len = (self.headers.get("Content-Length") or "0").strip()
        if not re.fullmatch(r"[0-9]{1,12}", raw_len):
            return self._send(400, "bad request", "text/plain; charset=utf-8")
        length = int(raw_len)
        if length > MAX_BODY:
            return self._send(413, "request too large", "text/plain; charset=utf-8")
        try:
            data = self.rfile.read(length)
        except OSError:  # includes the socket timeout: the client stalled or trickled the body
            return self._send(408, "request timeout", "text/plain; charset=utf-8")
        form = urllib.parse.parse_qs(data.decode("utf-8", "replace"))
        address = (form.get("address", [""])[0] or "").strip()

        state = self._read_state(username)
        if state is None:
            return self._unavailable()
        cwa, absu, cwa_val, abs_val = state

        before = (cwa, absu, cwa_val, abs_val)

        if route == "/remove":
            written, failed = [], []
            if cwa:
                try:
                    cwa_set(cwa[0], None); written.append("Calibre-Web")
                except Exception:
                    failed.append("Calibre-Web")
            if absu:
                try:
                    abs_set(absu, None, f"Kindle ({username})"); written.append("Audiobookshelf")
                except Exception:
                    failed.append("Audiobookshelf")
            state = self._refresh(username, before, failed)
            if state is None:
                return self._unavailable()
            cwa, absu, cwa_val, abs_val = state
            if failed:
                msg = ("err", "Removed from " + (" and ".join(written) or "nothing") +
                       "; failed for " + " and ".join(failed) + ".")
            elif written:
                msg = ("ok", "Removed from " + " and ".join(written) + ".")
            else:
                msg = ("err", "Nothing to remove.")
            return self._send(200, render(cwa_val, abs_val, "", msg, bool(cwa_val or abs_val),
                                          audiobooks=self._audiobooks()))

        if len(address) > MAX_ADDRESS or not KINDLE_RE.match(address):
            return self._send(200, render(cwa_val, abs_val, address,
                                          ("err", "That is not a @kindle.com address."),
                                          bool(cwa_val or abs_val), invalid=True,
                                          audiobooks=self._audiobooks()))

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

        state = self._refresh(username, before, failed)
        if state is None:
            return self._unavailable()
        cwa, absu, cwa_val, abs_val = state
        if failed:
            msg = ("err", "Saved to " + (" and ".join(written) or "nothing") +
                   "; failed for " + " and ".join(failed) + ".")
        elif written:
            msg = ("ok", "Saved to " + " and ".join(written) +
                   ". Remember to approve " + SENDER + " on Amazon.")
        else:
            msg = ("err", "No library account found for this login.")
        return self._send(200, render(cwa_val, abs_val, address, msg, bool(cwa_val or abs_val),
                                      audiobooks=self._audiobooks()))

    do_HEAD = do_GET

    def log_message(self, *a):
        pass  # no per-request identity in logs


def main():
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8096"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
