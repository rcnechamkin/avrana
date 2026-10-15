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
        if mode == "mock":
            base_url = base_url or DEFAULT_MOCK_JELLYFIN_URL
            if not is_loopback_host(url_host(base_url) or ""):
                problems.append("JELLYFIN_BASE_URL must be a loopback address in mock mode")
            if key:
                problems.append("a Jellyfin API key is set but HOME_UPSTREAM_MODE is mock "
                                "(mock mode never sends a real key; unset it or choose real)")
            key = MOCK_API_KEY
        else:
            if get("HOME_GATES_VERIFIED").lower() != "yes":
                problems.append("HOME_UPSTREAM_MODE=real needs HOME_GATES_VERIFIED=yes "
                                "(gates G1 and G2 verified in production)")
            if not base_url:
                problems.append("JELLYFIN_BASE_URL is required in real mode")
            if not key:
                problems.append("JELLYFIN_API_KEY or JELLYFIN_API_KEY_FILE is required in real mode")
        if base_url:
            _check_url(base_url, problems)

        if problems:
            raise SettingsError("invalid configuration: " + "; ".join(problems))
        return cls(home_sections=sections, upstream_mode=mode, jellyfin_base_url=base_url,
                   jellyfin_api_key=key, timeout=timeout, section_limit=limit,
                   health_detail=detail, catalogue_path=catalogue, log_level=level,
                   host=host, port=port)


def _check_url(url: str, problems: list) -> None:
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018  (validates the port)
    except ValueError:
        problems.append("JELLYFIN_BASE_URL is not a valid URL")
        return
    if parts.scheme not in ("http", "https") or not parts.hostname:
        problems.append("JELLYFIN_BASE_URL must be an http(s) URL")
    elif parts.username or parts.password or parts.query or parts.fragment or url.endswith("/"):
        problems.append("JELLYFIN_BASE_URL must have no credentials, query, fragment or trailing slash")


def _read_key(env: Mapping[str, str], problems: list) -> str:
    path = (env.get("JELLYFIN_API_KEY_FILE") or "").strip()
    direct = (env.get("JELLYFIN_API_KEY") or "").strip()
    if path and direct:
        problems.append("set only one of JELLYFIN_API_KEY and JELLYFIN_API_KEY_FILE")
        return ""
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            problems.append("JELLYFIN_API_KEY_FILE cannot be read")
            return ""
    return direct
