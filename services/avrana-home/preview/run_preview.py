#!/usr/bin/env python3
"""The Avrana Home OWNER PREVIEW entrypoint: `python -m preview.run_preview` (Dockerfile.preview).

Owner decision 2026-10-15: Home on host `avrana`, reachable ONLY on the home LAN at its LAN address, behind
ONE password, showing the owner's own real libraries. No Cloudflare tunnel, no DNS name, no Authentik.

Layers, outermost to innermost (gate.py):
  1. PasswordGate: HTTP Basic, one password from PREVIEW_PASSWORD_FILE (>= 16 characters), constant-time
     compare, a per-address failure throttle; nothing else runs before it (a loopback-only /healthz aside).
  2. OwnerIdentity: every inbound identity-like header is stripped, then the owner's fixed identity
     (PREVIEW_OWNER_USERNAME, PREVIEW_OWNER_GROUPS) is added. A client cannot choose who it is.
  3. The unchanged application (`create_app`), with settings built through the SEALED owner-preview path:
     HOME_OWNER_PREVIEW=yes is honoured only here, so real mode runs without claiming HOME_GATES_VERIFIED
     (G1/G2 concern forged identity headers, which layer 2 makes moot). serve.py still refuses real mode
     without the gates. Komga and Calibre-Web still need their owner-confirmation flags.

Uvicorn runs as serve.py runs it: h11, no access log, proxy_headers off (the peer is the real TCP peer),
no server header. The bind is HOME_HOST: a loopback literal, or 0.0.0.0 only inside the preview container
(PREVIEW_IN_CONTAINER=yes, set by Dockerfile.preview); the compose file publishes one LAN address.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping, Optional, Tuple

HOME = Path(__file__).resolve().parents[1]
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))

from avrana_home.app.settings import _OWNER_PREVIEW_SEAL, Settings, SettingsError  # noqa: E402
from preview.gate import (OwnerIdentity, PasswordGate, PreviewRefused, check_preview_startup,  # noqa: E402
                          owner_headers, read_password)


def _groups(raw: str) -> list:
    return [g.strip() for g in raw.replace(",", "|").split("|") if g.strip()]


def build_preview_app(env: Mapping[str, str], *, adapters=None, clock=None) -> Tuple[Settings, object]:
    """(settings, the wrapped ASGI app). Raises PreviewRefused (or SettingsError) BEFORE anything is built.
    `adapters` and `clock` are for tests only."""
    if env.get("PREVIEW_PASSWORD"):
        raise PreviewRefused("set the password in a file (PREVIEW_PASSWORD_FILE), never in the environment")
    password = read_password((env.get("PREVIEW_PASSWORD_FILE") or "").strip())
    settings = Settings.from_mapping(env, owner_preview_seal=_OWNER_PREVIEW_SEAL)
    in_container = (env.get("PREVIEW_IN_CONTAINER") or "").strip().lower() == "yes"
    checked = check_preview_startup(password=password, settings=settings, host=settings.host,
                                    in_container=in_container)
    headers = owner_headers(settings.owner_preview_username, _groups(env.get("PREVIEW_OWNER_GROUPS") or ""))
    from avrana_home.app.main import create_app
    app = create_app(settings, adapters=adapters)
    kw = {} if clock is None else {"clock": clock}
    gated = PasswordGate(OwnerIdentity(app, headers=headers, checked=checked), password=password,
                         checked=checked, **kw)
    return settings, gated


def main(env: Optional[Mapping[str, str]] = None) -> int:
    env = os.environ if env is None else env
    try:
        settings, app = build_preview_app(env)
    except (PreviewRefused, SettingsError) as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    import uvicorn
    from avrana_home.app.logsafe import configure_logging
    configure_logging(settings.log_level)
    uvicorn.run(app, host=settings.host, port=settings.port, http="h11", access_log=False,
                proxy_headers=False, server_header=False, log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
