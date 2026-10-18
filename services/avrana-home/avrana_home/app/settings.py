"""Application settings: read once from a mapping, validated, immutable. Standard library only.

The application refuses to start (SettingsError) on any invalid value rather than run half
configured. Secrets come from the environment or a file named by the environment (see
docs/SECRETS.md) and are never in a repr, a log line or an error message.

Defaults are the SAFE ones: sections off, upstream mode "mock" (loopback only, a fixed fake key).
Real upstreams need `HOME_UPSTREAM_MODE=real` AND `HOME_GATES_VERIFIED=yes` AND an explicit base
URL AND a key. `create_app` never reads the environment itself; `Settings.from_env` does.
"""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlsplit

MOCK_API_KEY = "mock-api-key-not-real"          # obviously fake; the only key mock mode accepts
DEFAULT_MOCK_JELLYFIN_URL = "http://127.0.0.1:18096"
DEFAULT_CATALOGUE = Path(__file__).resolve().parents[3] / "avrana-portal" / "portal.py"
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


class SettingsError(ValueError):
    """Invalid configuration. Messages name variables, never values."""


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def url_host(url: str) -> Optional[str]:
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


@dataclass(frozen=True)
class Settings:
    home_sections: bool = False
    upstream_mode: str = "mock"                  # "mock" | "real"
    jellyfin_base_url: str = DEFAULT_MOCK_JELLYFIN_URL
    jellyfin_api_key: str = field(default=MOCK_API_KEY, repr=False)
    audiobookshelf_base_url: str = ""            # "" = the Audiobookshelf adapter is not built
    audiobookshelf_token: str = field(default="", repr=False)
    komga_base_url: str = ""                     # "" = the Komga adapter is not built
    komga_token: str = field(default="", repr=False)    # a REGULAR (non-admin) account's API key; never an admin key
    komga_owner_confirms: bool = False           # the owner's statement that no member is restricted
    calibre_web_base_url: str = ""               # "" = the Calibre-Web adapter is not built
    calibre_web_credential: str = field(default="", repr=False)    # "user:password" of the viewer account
    calibre_web_owner_confirms: bool = False     # the owner's statement that no member is restricted
    timeout: float = 2.0
    section_limit: int = 12
    health_detail: str = "loopback"              # "loopback" | "off"
    catalogue_path: Path = DEFAULT_CATALOGUE
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8096

    def __repr__(self) -> str:
        return (f"Settings(home_sections={self.home_sections}, upstream_mode={self.upstream_mode!r}, "
                f"host={self.host!r}, port={self.port}, <secrets redacted>)")

    @property
    def uses_real_upstream(self) -> bool:
        return self.upstream_mode == "real"

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        return cls.from_mapping(os.environ if env is None else env)

    @classmethod
    def from_mapping(cls, env: Mapping[str, str]) -> "Settings":
        problems = []

        def get(name: str, default: str = "") -> str:
            value = env.get(name)
            return default if value is None else str(value).strip()

        def boolean(name: str, default: bool) -> bool:
            raw = get(name).lower()
            if name not in env or raw == "":
                return default
            if raw in _TRUE:
                return True
            if raw in _FALSE:
                return False
            problems.append(f"{name} must be on or off")
            return default

        def number(name: str, default, cast, lo, hi):
            if name not in env or get(name) == "":
                return default
            try:
                value = cast(get(name))
            except ValueError:
                problems.append(f"{name} must be a number")
                return default
            if not lo <= value <= hi:
                problems.append(f"{name} must be between {lo} and {hi}")
                return default
            return value

        sections = boolean("HOME_SECTIONS", False)
        mode = get("HOME_UPSTREAM_MODE", "mock").lower()
        if mode not in ("mock", "real"):
            problems.append("HOME_UPSTREAM_MODE must be mock or real")
            mode = "mock"
        detail = get("HOME_HEALTH_DETAIL", "loopback").lower()
        if detail not in ("loopback", "off"):
            problems.append("HOME_HEALTH_DETAIL must be loopback or off")
            detail = "loopback"
        level = get("LOG_LEVEL", "INFO").upper()
        if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            problems.append("LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR")
            level = "INFO"
        timeout = number("HOME_TIMEOUT", 2.0, float, 0.1, 10.0)
        limit = number("HOME_SECTION_LIMIT", 12, int, 1, 50)
        port = number("HOME_PORT", 8096, int, 1, 65535)
        host = get("HOME_HOST", "127.0.0.1")
        if not host or any(c.isspace() for c in host):
            problems.append("HOME_HOST is not a host name or address")
            host = "127.0.0.1"
        catalogue = Path(get("HOME_CATALOGUE_PATH")) if get("HOME_CATALOGUE_PATH") else DEFAULT_CATALOGUE
        if not catalogue.is_file():
            problems.append("HOME_CATALOGUE_PATH does not name a file (the portal tables)")

        base_url = get("JELLYFIN_BASE_URL")
        key = _read_key(env, problems)
        abs_url = get("AUDIOBOOKSHELF_BASE_URL")
        abs_token = _read_key(env, problems, "AUDIOBOOKSHELF_TOKEN")
        komga_url = get("KOMGA_BASE_URL")
        komga_token = _read_key(env, problems, "KOMGA_TOKEN")
        komga_confirms = boolean("KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS", False)
        cw_url = get("CALIBRE_WEB_BASE_URL")
        cw_cred = _read_key(env, problems, "CALIBRE_WEB_CREDENTIAL")
        cw_confirms = boolean("CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS", False)
        if mode == "mock":
            base_url = base_url or DEFAULT_MOCK_JELLYFIN_URL
            if not is_loopback_host(url_host(base_url) or ""):
                problems.append("JELLYFIN_BASE_URL must be a loopback address in mock mode")
            if key:
                problems.append("a Jellyfin API key is set but HOME_UPSTREAM_MODE is mock "
                                "(mock mode never sends a real key; unset it or choose real)")
            key = MOCK_API_KEY
            if abs_token:
                problems.append("an Audiobookshelf token is set but HOME_UPSTREAM_MODE is mock "
                                "(mock mode never sends a real token; unset it or choose real)")
            if abs_url and not is_loopback_host(url_host(abs_url) or ""):
                problems.append("AUDIOBOOKSHELF_BASE_URL must be a loopback address in mock mode")
            abs_token = MOCK_API_KEY if abs_url else ""
            if komga_token:
                problems.append("a Komga token is set but HOME_UPSTREAM_MODE is mock "
                                "(mock mode never sends a real token; unset it or choose real)")
            if komga_url and not is_loopback_host(url_host(komga_url) or ""):
                problems.append("KOMGA_BASE_URL must be a loopback address in mock mode")
            komga_token = MOCK_API_KEY if komga_url else ""
            komga_confirms = False               # a real-mode statement; mock mode passes its own constant
            if cw_cred:
                problems.append("a Calibre-Web credential is set but HOME_UPSTREAM_MODE is mock "
                                "(mock mode never sends a real credential; unset it or choose real)")
            if cw_url and not is_loopback_host(url_host(cw_url) or ""):
                problems.append("CALIBRE_WEB_BASE_URL must be a loopback address in mock mode")
            cw_cred = "viewer:" + MOCK_API_KEY if cw_url else ""
            cw_confirms = False                  # a real-mode statement; mock mode passes its own constant
        else:
            if get("HOME_GATES_VERIFIED").lower() != "yes":
                problems.append("HOME_UPSTREAM_MODE=real needs HOME_GATES_VERIFIED=yes "
                                "(gates G1 and G2 verified in production)")
            if not base_url:
                problems.append("JELLYFIN_BASE_URL is required in real mode")
            if not key:
                problems.append("JELLYFIN_API_KEY or JELLYFIN_API_KEY_FILE is required in real mode")
            if komga_url or komga_token:
                # ADAPTER-CONTRACT 12.2 (owner decision 2026-10-15): a SHARED regular-account view, no admin
                # key; refused unless the owner states, deliberately, that no member has a Komga restriction.
                if not komga_confirms:
                    problems.append("Komga is a shared view and cannot be configured in real mode "
                                    "without KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=yes "
                                    "(ADAPTER-CONTRACT 12.2)")
                if not komga_url or not komga_token:
                    problems.append("KOMGA_BASE_URL and KOMGA_TOKEN (or _FILE) must be set together")
            elif komga_confirms:
                problems.append("KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS is set but Komga is not configured")
            if cw_url or cw_cred:
                # ADAPTER-CONTRACT 13.2: a SHARED view; refused unless the owner states, deliberately, that
                # no member has a Calibre-Web restriction (default off). HOME_GATES_VERIFIED applies above.
                if not cw_confirms:
                    problems.append("Calibre-Web is a shared view and cannot be configured in real mode "
                                    "without CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=yes "
                                    "(ADAPTER-CONTRACT 13.2)")
                if not cw_url or ":" not in cw_cred:
                    problems.append("CALIBRE_WEB_BASE_URL and CALIBRE_WEB_CREDENTIAL (user:password, or "
                                    "_FILE) must be set together")
            elif cw_confirms:
                problems.append("CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS is set but Calibre-Web "
                                "is not configured")
            if bool(abs_url) != bool(abs_token):
                problems.append("AUDIOBOOKSHELF_BASE_URL and AUDIOBOOKSHELF_TOKEN (or _FILE) must be "
                                "set together, or both left unset")
        if base_url:
            _check_url(base_url, problems, "JELLYFIN_BASE_URL")
        if abs_url:
            _check_url(abs_url, problems, "AUDIOBOOKSHELF_BASE_URL")
        if komga_url:
            _check_url(komga_url, problems, "KOMGA_BASE_URL")
        if cw_url:
            _check_url(cw_url, problems, "CALIBRE_WEB_BASE_URL")

        if problems:
            raise SettingsError("invalid configuration: " + "; ".join(problems))
        return cls(home_sections=sections, upstream_mode=mode, jellyfin_base_url=base_url,
                   jellyfin_api_key=key, audiobookshelf_base_url=abs_url,
                   audiobookshelf_token=abs_token, komga_base_url=komga_url,
                   komga_token=komga_token, komga_owner_confirms=komga_confirms,
                   calibre_web_base_url=cw_url,
                   calibre_web_credential=cw_cred, calibre_web_owner_confirms=cw_confirms, timeout=timeout, section_limit=limit,
                   health_detail=detail, catalogue_path=catalogue, log_level=level,
                   host=host, port=port)


def _check_url(url: str, problems: list, name: str = "JELLYFIN_BASE_URL") -> None:
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018  (validates the port)
    except ValueError:
        problems.append(f"{name} is not a valid URL")
        return
    if parts.scheme not in ("http", "https") or not parts.hostname:
        problems.append(f"{name} must be an http(s) URL")
    elif parts.username or parts.password or parts.query or parts.fragment or url.endswith("/"):
        problems.append(f"{name} must have no credentials, query, fragment or trailing slash")


def _read_key(env: Mapping[str, str], problems: list, name: str = "JELLYFIN_API_KEY") -> str:
    path = (env.get(name + "_FILE") or "").strip()
    direct = (env.get(name) or "").strip()
    if path and direct:
        problems.append(f"set only one of {name} and {name}_FILE")
        return ""
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            problems.append(f"{name}_FILE cannot be read")
            return ""
    return direct
