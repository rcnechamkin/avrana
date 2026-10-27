#!/usr/bin/env python3
"""Fixture-only beta entry point (AVR-373 phase 1): `python -m beta.run_beta`, the CMD of Dockerfile.beta.

Real Authentik sign-in, synthetic data. The app verifies the outpost's signed token (HOME_IDENTITY_MODE
jwt_required or jwt_log_only; plain headers are refused here) and reads ONLY the four loopback mocks this
process starts (Jellyfin, Audiobookshelf, Komga, Calibre-Web, from tests/fixtures). It never reaches a real
library: every upstream variable, real mode, HOME_GATES_VERIFIED and the development identity shim are
refused before anything binds. Server flags are serve.py's (h11, no access log, no proxy headers).

Refusals exit 2 with the reason; nothing is started. See docs/design/BETA-CHECKLIST.md section 4.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOME_DIR = Path(__file__).resolve().parents[1]
if str(HOME_DIR) not in sys.path:
    sys.path.insert(0, str(HOME_DIR))

JWT_MODES = ("jwt_required", "jwt_log_only")
# The mocks' loopback ports inside the container; never published.
MOCK_PORTS = {"JELLYFIN": 18096, "AUDIOBOOKSHELF": 18113, "KOMGA": 18125, "CALIBRE_WEB": 18183}
# The only settings the beta takes from its environment; everything else is fixed below.
PASSTHROUGH = ("HOME_IDENTITY_MODE", "HOME_JWT_ISSUER", "HOME_JWT_AUDIENCE", "HOME_JWT_SECRET",
               "HOME_JWT_SECRET_FILE", "HOME_JWT_SECRET_PREVIOUS", "HOME_JWT_SECRET_PREVIOUS_FILE",
               "HOME_ALLOWED_USERS", "HOME_HOST", "HOME_PORT", "HOME_LOG_LEVEL", "HOME_HEALTH_DETAIL",
               "HOME_CATALOGUE_PATH", "HOME_PWA_SW", "HOME_SECTIONS")
REFUSED_PREFIXES = ("JELLYFIN_", "AUDIOBOOKSHELF_", "KOMGA_", "CALIBRE_WEB_", "PREVIEW_", "HOME_DEV_")


class BetaRefused(Exception):
    pass


def build_env(environ, ports=None) -> dict:
    """The app's settings mapping for the beta, or BetaRefused naming every problem."""
    problems = []
    for name in sorted(environ):
        if name.startswith(REFUSED_PREFIXES):
            problems.append(f"{name} is set: the beta reads only its own loopback mocks")
        elif name.startswith("HOME_") and name not in PASSTHROUGH:
            problems.append(f"{name} is not a beta setting")
    mode = (environ.get("HOME_IDENTITY_MODE") or "").strip().lower()
    if mode not in JWT_MODES:
        problems.append("HOME_IDENTITY_MODE must be jwt_required or jwt_log_only "
                        "(plain identity headers are never trusted on the beta)")
    if problems:
        raise BetaRefused("; ".join(problems))
    env = {name: environ[name] for name in PASSTHROUGH if name in environ}
    env.setdefault("HOME_SECTIONS", "on")
    env["HOME_UPSTREAM_MODE"] = "mock"
    env["HOME_TIMEOUT"] = "2.0"
    for service, port in (ports or MOCK_PORTS).items():
        env[f"{service}_BASE_URL"] = f"http://127.0.0.1:{port}"
    return env


def build(environ, *, start: bool = True, ports=None):
    """(asgi_app, settings, mocks). Validates everything before any mock starts."""
    from avrana_home.app.main import create_app
    from avrana_home.app.settings import Settings, SettingsError

    ports = dict(ports or MOCK_PORTS)
    env = build_env(environ, ports)
    try:
        settings = Settings.from_mapping(env)
    except SettingsError as exc:
        raise BetaRefused(str(exc)) from None
    from dev.mock_audiobookshelf import MockAudiobookshelf
    from dev.mock_calibre_web import MockCalibreWeb
    from dev.mock_jellyfin import MockJellyfin
    from dev.mock_komga import MockKomga

    mocks = [MockJellyfin("127.0.0.1", ports["JELLYFIN"], "ok", 5.0),
             MockAudiobookshelf("127.0.0.1", ports["AUDIOBOOKSHELF"], "ok", 5.0),
             MockKomga("127.0.0.1", ports["KOMGA"], "ok", 5.0),
             MockCalibreWeb("127.0.0.1", ports["CALIBRE_WEB"], "ok", 5.0)]
    if start:
        for mock in mocks:
            mock.start()
    return create_app(settings), settings, mocks


def main() -> int:
    try:
        app, settings, mocks = build(os.environ)
    except BetaRefused as exc:
        print(f"refusing to start the beta: {exc}", file=sys.stderr)
        return 2
    import uvicorn
    from avrana_home.app.logsafe import configure_logging

    configure_logging(settings.log_level)
    print(f"Avrana Home beta (fixture-only, {settings.identity_mode}) on {settings.host}:{settings.port}; "
          "synthetic data from loopback mocks only.", flush=True)
    try:
        uvicorn.run(app, host=settings.host, port=settings.port, http="h11", access_log=False,
                    proxy_headers=False, server_header=False, log_config=None)
    finally:
        for mock in mocks:
            mock.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
