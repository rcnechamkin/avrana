#!/usr/bin/env python3
"""TEMPORARY fixture-only HTTPS preview on ONE home-LAN address, for the owner's iPhone (AVR-585 B1, 2026-10-26).

    python services/avrana-home/dev/run_lan_preview.py --i-understand-lan --host 192.168.1.23 \\
        --cert C:/Users/<you>/avrana-preview/preview.pem --key C:/Users/<you>/avrana-preview/preview-key.pem

Runbook: docs/runbooks/home-fixture-lan-preview.md. Foreground only: it stops on Ctrl+C and exits by itself after
`--minutes` (default 60, at most 240). It installs nothing, writes no file, creates no service or scheduled task.

The stack is run_dev.py's, unchanged: the mock Jellyfin, Audiobookshelf, Komga and Calibre-Web on 127.0.0.1 (never on
the LAN), the application with HOME_SECTIONS=on, and the synthetic development identity switch. In front of it,
outermost, dev/lan_gate.py: a one-time passphrase printed here, then an HttpOnly Secure SameSite=Strict cookie.
Uvicorn runs as serve.py runs it (h11, no access log, proxy_headers off, no server header), with TLS.

It refuses to start (exit 2, nothing bound) unless ALL hold:
  * `--i-understand-lan` is given;
  * `--host` is ONE private IPv4 literal (10/8, 172.16/12, 192.168/16): never 0.0.0.0, ::, a name, link-local,
    public or CGNAT; loopback only with the hidden test flag;
  * `--cert` and `--key` are readable PEM files that load as a pair, and the key is outside every Git working tree;
  * no real upstream configuration is in the environment (JELLYFIN_*, AUDIOBOOKSHELF_*, KOMGA_*, CALIBRE_WEB_*,
    PREVIEW_*, HOME_* other than the two UI switches), and every upstream URL the settings hold is
    one of the mocks started here, in mock mode with the fixed fake key;
  * `--minutes` is 1..240.
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import secrets
import ssl
import sys
import threading
import time
from pathlib import Path
from typing import Mapping, Optional

HOME = Path(__file__).resolve().parents[1]
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))

from dev.dev_identity import DevIdentityRefused, check_lan_bind, check_lan_startup  # noqa: E402

DEFAULT_MINUTES = 60
MAX_MINUTES = 240
DEFAULT_PORT = 8443
MOCK_PORTS = {"jellyfin": 18096, "abs": 13378, "komga": 25600, "calibre": 18083}
ALLOWED_HOME_VARS = frozenset({"HOME_PWA_SW", "HOME_MOTION_PROPOSAL"})
REAL_PREFIXES = ("JELLYFIN_", "AUDIOBOOKSHELF_", "KOMGA_", "CALIBRE_WEB_", "PREVIEW_")
HOSTNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.local$")
SHUTDOWN_GRACE = 5
HARD_STOP_AFTER = 60          # seconds past expiry: if uvicorn has not exited by then, the process is ended


class LanPreviewRefused(DevIdentityRefused):
    """The LAN preview will not start. Messages name settings, never values."""


# ---- startup checks (each refuses before anything is bound) -------------------------------------------------
def check_minutes(minutes: int) -> int:
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= MAX_MINUTES:
        raise LanPreviewRefused(f"--minutes must be 1 to {MAX_MINUTES} (at most 4 hours)")
    return minutes


def check_environment(environ: Mapping[str, str]) -> None:
    """Refuse when anything the application's settings read for an upstream is set, whatever its value. The stack is
    built from an explicit mapping (run_dev.build_stack), so these would be ignored anyway; refusing makes a shell
    that is set up for the real preview fail loudly. Other tools' variables (say ANTHROPIC_BASE_URL) are not ours."""
    for name in environ:
        upper = name.upper()
        if upper.startswith(REAL_PREFIXES) or (upper.startswith("HOME_") and upper not in ALLOWED_HOME_VARS):
            raise LanPreviewRefused(f"refusing: {upper} is set in the environment; the LAN preview is fixture-only "
                                    f"(unset it in this shell)")


def inside_git_tree(path: Path) -> bool:
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            return True
    return False


def check_tls_files(cert: Optional[str], key: Optional[str]) -> tuple:
    """(cert path, key path) as resolved strings, or LanPreviewRefused."""
    if not cert or not key:
        raise LanPreviewRefused("--cert and --key are required (HTTPS only; see the runbook for mkcert)")
    paths = []
    for flag, raw, marker in (("--cert", cert, b"-----BEGIN CERTIFICATE-----"), ("--key", key, b"PRIVATE KEY-----")):
        path = Path(raw).expanduser().resolve()
        try:
            head = path.read_bytes()[:65536] if path.is_file() else None
        except OSError:
            head = None
        if head is None:
            raise LanPreviewRefused(f"{flag} is missing or unreadable")
        if marker not in head:
            raise LanPreviewRefused(f"{flag} is not a PEM file of the expected kind")
        paths.append(path)
    cert_path, key_path = paths
    if inside_git_tree(key_path) or inside_git_tree(key_path.parent):
        raise LanPreviewRefused("--key is inside a Git working tree; keep the key outside every repository")
    try:
        ssl.create_default_context(ssl.Purpose.CLIENT_AUTH).load_cert_chain(str(cert_path), str(key_path))
    except (ssl.SSLError, OSError, ValueError):
        raise LanPreviewRefused("--cert and --key do not load as a matching pair (or the key has a passphrase)") from None
    return str(cert_path), str(key_path)


def check_hostname(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    if not HOSTNAME.match(name):
        raise LanPreviewRefused("--hostname must be one name ending in .local (as in the certificate)")
    return name.lower()


def check_mock_targets(settings, ports: Mapping[str, int]) -> None:
    """Every upstream URL in the settings is http://127.0.0.1:<a mock port started by this process>."""
    from avrana_home.app.settings import MOCK_API_KEY
    from urllib.parse import urlsplit
    if settings.upstream_mode != "mock" or settings.jellyfin_api_key != MOCK_API_KEY:
        raise LanPreviewRefused("the LAN preview runs only against the in-process mocks")
    allowed = {f"http://127.0.0.1:{p}" for p in ports.values()}
    for url in (settings.jellyfin_base_url, settings.audiobookshelf_base_url, settings.komga_base_url,
                settings.calibre_web_base_url):
        if not url:                                   # not configured: no adapter for that library
            continue
        parts = urlsplit(url)
        if f"{parts.scheme}://{parts.netloc}" not in allowed or parts.path not in ("", "/"):
            raise LanPreviewRefused("an upstream URL is not one of this process's loopback mocks")


# ---- assembly --------------------------------------------------------------------------------------------------
def build(host: str, port: int, *, cert: Optional[str], key: Optional[str], acknowledged: bool,
          minutes: int = DEFAULT_MINUTES, hostname: Optional[str] = None, allow_loopback: bool = False,
          environ: Optional[Mapping[str, str]] = None, mode: str = "ok", ports: Optional[Mapping[str, int]] = None,
          start_mock: bool = True, clock=time.monotonic):
    """(mock, gated app, settings, passphrase, expiry seconds). Raises LanPreviewRefused/DevIdentityRefused BEFORE
    any socket is bound or any mock is started."""
    from dev import run_dev
    from dev.lan_gate import LanGate
    if acknowledged is not True:
        raise LanPreviewRefused("the LAN preview needs the explicit --i-understand-lan flag")
    seconds = check_minutes(minutes) * 60
    check_environment(os.environ if environ is None else environ)
    check_lan_bind(host, allow_loopback=allow_loopback)        # again, with the settings, in check() below
    if not 1024 <= port <= 65535:
        raise LanPreviewRefused("--port must be 1024 to 65535")
    check_tls_files(cert, key)
    name = check_hostname(hostname)
    ports = dict(MOCK_PORTS if ports is None else ports)

    def check(settings):
        checked = check_lan_startup(enabled=True, acknowledged=acknowledged, host=host, settings=settings,
                                    allow_loopback=allow_loopback)
        check_mock_targets(settings, ports)
        return checked

    mock, app, settings = run_dev.build_stack(host, port, ports["jellyfin"], True, mode, start_mock=start_mock,
                                              abs_mock_port=ports["abs"], komga_mock_port=ports["komga"],
                                              calibre_mock_port=ports["calibre"], check=check)
    passphrase = secrets.token_urlsafe(15)
    hosts = [f"{host}:{port}"] + ([f"{name}:{port}"] if name else [])
    gated = LanGate(app, passphrase=passphrase, allowed_hosts=hosts, expires_at=clock() + seconds, clock=clock)
    return mock, gated, settings, passphrase, seconds


def stop_mocks(mock) -> None:
    mock.stop()
    for extra in (mock.abs, mock.komga, mock.calibre):
        if extra is not None:
            extra.stop()


def run_server(app, host: str, port: int, seconds: float, *, cert: Optional[str], key: Optional[str],
               hard_stop: bool = True):
    """Serve in the foreground until Ctrl+C or `seconds` pass. Returns the uvicorn.Server (tests read it)."""
    import uvicorn
    tls = {} if cert is None else {"ssl_certfile": cert, "ssl_keyfile": key}
    config = uvicorn.Config(app, host=host, port=port, http="h11", access_log=False, proxy_headers=False,
                            server_header=False, log_config=None, timeout_graceful_shutdown=SHUTDOWN_GRACE, **tls)
    server = uvicorn.Server(config)

    def expire():
        print("LAN preview expired; stopping.", flush=True)
        server.should_exit = True

    timers = [threading.Timer(seconds, expire)]
    if hard_stop:
        timers.append(threading.Timer(seconds + HARD_STOP_AFTER, lambda: os._exit(0)))
    for t in timers:
        t.daemon = True
        t.start()
    try:
        server.run()
    finally:
        for t in timers:
            t.cancel()
    return server


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--i-understand-lan", dest="ack", action="store_true",
                    help="required: serve synthetic fixtures on ONE home-LAN address, temporarily")
    ap.add_argument("--host", required=True, help="this computer's private IPv4 address on the home Wi-Fi")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--cert", help="PEM certificate (mkcert), outside the repository")
    ap.add_argument("--key", help="PEM private key (mkcert), outside every repository")
    ap.add_argument("--hostname", help="optional <name>.local also named in the certificate")
    ap.add_argument("--minutes", type=int, default=DEFAULT_MINUTES, help=f"auto-stop after (1..{MAX_MINUTES})")
    ap.add_argument("--mode", default="ok", help="mock failure mode at start (ok, slow, down, 500, ...)")
    ap.add_argument("--allow-loopback-for-tests", dest="loopback", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        mock, app, _settings, passphrase, seconds = build(
            args.host, args.port, cert=args.cert, key=args.key, acknowledged=args.ack, minutes=args.minutes,
            hostname=args.hostname, allow_loopback=args.loopback, mode=args.mode, start_mock=False)
    except DevIdentityRefused as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("refusing to start: a loopback mock port is already in use (another preview running?)",
              file=sys.stderr)
        return 2
    cert, key = check_tls_files(args.cert, args.key)
    from avrana_home.app.logsafe import configure_logging
    configure_logging("INFO")
    until = (datetime.datetime.now() + datetime.timedelta(seconds=seconds)).strftime("%H:%M")
    names = [f"https://{args.host}:{args.port}/"] + (
        [f"https://{args.hostname.lower()}:{args.port}/"] if args.hostname else [])
    # The passphrase goes to this console only: print(), never the logging system.
    print("AVRANA FIXTURE LAN PREVIEW: SYNTHETIC DATA ONLY, temporary, not a deployment.\n"
          f"  open on the iPhone: {'  or  '.join(names)}\n"
          f"  passphrase:         {passphrase}\n"
          f"  stops by itself at: {until} ({seconds // 60} min)\n"
          "  stop now:           Ctrl+C in this window\n"
          "  members:            /_dev/identity after unlocking", flush=True)
    mock.start()
    for extra in (mock.abs, mock.komga, mock.calibre):
        if extra is not None:
            extra.start()
    try:
        run_server(app, args.host, args.port, seconds, cert=cert, key=key)
    finally:
        stop_mocks(mock)
        print("LAN preview stopped. Nothing is left running.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
