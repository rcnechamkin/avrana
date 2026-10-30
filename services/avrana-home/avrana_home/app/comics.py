"""Me -> Comics (S-01; docs/runbooks/komga-key-lifecycle.md): whether Home holds the member's own Komga key, and the
member's two controls over it. Pure functions; main.py reads the form (forms.py) and calls komga_keys.

  * Disconnect: revokes the key in Komga as the member (with the key itself) and drops it from the keys file. If Komga
    can't be reached the key is still dropped here, and the page says how to remove it in Komga.
  * Connect comics (only with no key): the member's password, once, in the POST body only. Home signs in to Komga as
    them, makes the `avrana-home` key, files it and forgets the password (komga_keys.KomgaKeyClient.mint). Rate-limited
    per member.

Only for members who hold the Comics group (avrana-comics), only with HOME_KOMGA_CONNECT=on; otherwise the path is the
standard 404 (GET) and 501 (POST), like every unknown route.
"""
from __future__ import annotations

from typing import Dict

ROUTE = "/me/comics"
FIELDS = frozenset({"t", "do", "password"})
CONNECT_WINDOW = 15 * 60
CONNECT_TRIES = 5
RESULTS = ("connected", "disconnected", "disconnected_here", "not_connected", "already_connected", "wrong_password",
           "no_password", "komga_unavailable", "busy", "unavailable", "expired")


def result_headers(outcome: str, allowed) -> Dict[str, str]:
    """The 303 back to the page after a post (post/redirect/get). `outcome` is a fixed id from `allowed`."""
    if outcome not in allowed:
        raise ValueError("not an outcome")
    return {"Location": f"{ROUTE}?r={outcome}"}
