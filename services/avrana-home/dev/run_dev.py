#!/usr/bin/env python3
"""ONE command: the mock Jellyfin plus the Avrana home app, on 127.0.0.1, for local development.

    python services/avrana-home/dev/run_dev.py --dev-identity
    (use the venv with the pinned requirements: fastapi, uvicorn, jinja2)

What it does: starts `mock_jellyfin` (synthetic fixtures only), then the app with
HOME_SECTIONS=on talking to the mock through the REAL `UrllibTransport`, behind the development
identity shim (dev_identity.py). Open http://127.0.0.1:8096/_dev/identity to choose a synthetic
member; every page carries a "DEVELOPMENT IDENTITY" banner. Switch the mock's failure mode with
`curl -X POST http://127.0.0.1:18096/__mock/mode/down` (ok, slow, down, 500, malformed, wrong-user).

It refuses to start unless `--dev-identity` (or HOME_DEV_IDENTITY=on) is given, the bind address
is a loopback literal, and the upstream is the mock (see dev_identity.check_startup). It reads no
real configuration, no secrets and no production address.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))


def build_stack(host: str, app_port: int, mock_port: int, enabled: bool, mode: str = "ok",
                slow_seconds: float = 5.0, start_mock: bool = True, sections: str = "on"):
    """Return (mock, asgi_app, settings). Raises DevIdentityRefused BEFORE anything is started."""
    from avrana_home.app.main import create_app
    from avrana_home.app.settings import Settings
    from dev.dev_identity import DevIdentityMiddleware, check_startup
    from dev.mock_jellyfin import MockJellyfin

    settings = Settings.from_mapping({
        "HOME_SECTIONS": sections, "HOME_UPSTREAM_MODE": "mock",
        "JELLYFIN_BASE_URL": f"http://127.0.0.1:{mock_port}", "HOME_HOST": host,
        "HOME_PORT": str(app_port), "HOME_TIMEOUT": "2.0"})
    checked = check_startup(enabled=enabled, host=host, settings=settings)   # refuse first
    mock = MockJellyfin("127.0.0.1", mock_port, mode, slow_seconds)
    if start_mock:
        mock.start()
    return mock, DevIdentityMiddleware(create_app(settings), checked=checked), settings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dev-identity", action="store_true",
                    default=os.environ.get("HOME_DEV_IDENTITY", "").lower() == "on",
                    help="explicitly enable the synthetic development identity shim")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8096)
    ap.add_argument("--mock-port", type=int, default=18096)
    ap.add_argument("--mode", default="ok")
    ap.add_argument("--slow-seconds", type=float, default=5.0)
    ap.add_argument("--sections", choices=("on", "off"), default="on",
                    help="HOME_SECTIONS for this run (off = today's portal pages only)")
    args = ap.parse_args(argv)

    from dev.dev_identity import DevIdentityRefused
    try:
        mock, app, settings = build_stack(args.host, args.port, args.mock_port, args.dev_identity,
                                          args.mode, args.slow_seconds, sections=args.sections)
    except DevIdentityRefused as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    import uvicorn
    from avrana_home.app.logsafe import configure_logging
    configure_logging("INFO")
    print(f"mock Jellyfin: {mock.url} (mode {mock.mode})\n"
          f"app:           http://{args.host}:{args.port}/   identity switcher: /_dev/identity\n"
          f"SYNTHETIC DATA ONLY. Ctrl+C to stop.", flush=True)
    try:
        uvicorn.run(app, host=args.host, port=args.port, http="h11", access_log=False,
                    proxy_headers=False, server_header=False, log_config=None)
    finally:
        mock.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
