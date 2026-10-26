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
                slow_seconds: float = 5.0, start_mock: bool = True, sections: str = "on",
                abs_mock_port: int = 0, komga_mock_port: int = 0,
                calibre_mock_port: int = 0, check=None):
    """Return (mock, asgi_app, settings). Raises DevIdentityRefused BEFORE anything is started.
    `abs_mock_port` > 0 also builds the mock Audiobookshelf (`mock.abs`); off by default.
    `check(settings)` replaces the loopback `check_startup` (run_lan_preview.py passes its LAN check)."""
    from avrana_home.app.main import create_app
    from avrana_home.app.settings import Settings
    from dev.dev_identity import DevIdentityMiddleware, check_startup
    from dev.mock_jellyfin import MockJellyfin

    env = {"HOME_SECTIONS": sections, "HOME_UPSTREAM_MODE": "mock",
           "JELLYFIN_BASE_URL": f"http://127.0.0.1:{mock_port}", "HOME_HOST": host,
           "HOME_PORT": str(app_port), "HOME_TIMEOUT": "2.0"}
    if os.environ.get("HOME_PWA_SW"):                  # the service worker's kill switch (MK-3), for local testing
        env["HOME_PWA_SW"] = os.environ["HOME_PWA_SW"]
    if os.environ.get("HOME_MOTION_PROPOSAL"):         # the 600 ms motion Proposal (MK-6), for local comparison
        env["HOME_MOTION_PROPOSAL"] = os.environ["HOME_MOTION_PROPOSAL"]
    if abs_mock_port:
        env["AUDIOBOOKSHELF_BASE_URL"] = f"http://127.0.0.1:{abs_mock_port}"
    if komga_mock_port:
        env["KOMGA_BASE_URL"] = f"http://127.0.0.1:{komga_mock_port}"
    if calibre_mock_port:
        env["CALIBRE_WEB_BASE_URL"] = f"http://127.0.0.1:{calibre_mock_port}"
    settings = Settings.from_mapping(env)
    if check is None:
        checked = check_startup(enabled=enabled, host=host, settings=settings)   # refuse first
    else:
        checked = check(settings)                                                # refuse first
    mock = MockJellyfin("127.0.0.1", mock_port, mode, slow_seconds)
    mock.abs = None
    if abs_mock_port:
        from dev.mock_audiobookshelf import MockAudiobookshelf
        mock.abs = MockAudiobookshelf("127.0.0.1", abs_mock_port, mode, slow_seconds)
    mock.komga = None
    if komga_mock_port:
        from dev.mock_komga import MockKomga
        mock.komga = MockKomga("127.0.0.1", komga_mock_port, mode, slow_seconds)
    mock.calibre = None
    if calibre_mock_port:
        from dev.mock_calibre_web import MockCalibreWeb
        mock.calibre = MockCalibreWeb("127.0.0.1", calibre_mock_port, mode, slow_seconds)
    if start_mock:
        mock.start()
        for extra in (mock.abs, mock.komga, mock.calibre):
            if extra is not None:
                extra.start()
    return mock, DevIdentityMiddleware(create_app(settings), checked=checked), settings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dev-identity", action="store_true",
                    default=os.environ.get("HOME_DEV_IDENTITY", "").lower() == "on",
                    help="explicitly enable the synthetic development identity shim")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8096)
    ap.add_argument("--mock-port", type=int, default=18096)
    ap.add_argument("--abs-mock-port", type=int, default=0,
                    help="also start the mock Audiobookshelf on this port (default: off)")
    ap.add_argument("--komga-mock-port", type=int, default=0,
                    help="also start the mock Komga on this port (default: off)")
    ap.add_argument("--calibre-mock-port", type=int, default=0,
                    help="also start the mock Calibre-Web on this port (default: off)")
    ap.add_argument("--mode", default="ok")
    ap.add_argument("--slow-seconds", type=float, default=5.0)
    ap.add_argument("--sections", choices=("on", "off"), default="on",
                    help="HOME_SECTIONS for this run (off = today's portal pages only)")
    args = ap.parse_args(argv)

    from dev.dev_identity import DevIdentityRefused
    try:
        mock, app, settings = build_stack(args.host, args.port, args.mock_port, args.dev_identity,
                                          args.mode, args.slow_seconds, sections=args.sections,
                                          abs_mock_port=args.abs_mock_port,
                                          komga_mock_port=args.komga_mock_port,
                                          calibre_mock_port=args.calibre_mock_port)
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
        for extra in (mock.abs, mock.komga, mock.calibre):
            if extra is not None:
                extra.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
