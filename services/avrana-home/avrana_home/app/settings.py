"""Application settings: read once from a mapping, validated, immutable. Standard library only.

The application refuses to start (SettingsError) on any invalid value rather than run half
configured. Secrets come from the environment or a file named by the environment (see
docs/SECRETS.md) and are never in a repr, a log line or an error message.

Defaults are the SAFE ones: sections off, upstream mode "mock" (loopback only, a fixed fake key).
Real upstreams need `HOME_UPSTREAM_MODE=real` AND `HOME_GATES_VERIFIED=yes` AND an explicit base
URL AND a key. `create_app` never reads the environment itself; `Settings.from_env` does.

OWNER PREVIEW (owner decision 2026-10-15; preview/run_preview.py): a LAN-only preview for the owner's own
libraries. The gates G1/G2 are about forged identity headers reaching the app from sibling containers; the
preview never trusts an inbound identity header (it strips them all and injects the owner's fixed identity
behind a password), so it may run real mode WITHOUT HOME_GATES_VERIFIED, and it must NOT claim it. That path
needs BOTH `HOME_OWNER_PREVIEW=yes` in the environment AND the sealed token `_OWNER_PREVIEW_SEAL`, which only
preview/run_preview.py passes; `from_env` (serve.py) never does, so the normal server still refuses real
mode without the gates. Only in that mode may the per-service member usernames be set
(HOME_JELLYFIN_USERNAME, HOME_AUDIOBOOKSHELF_USERNAME), and they apply only to the owner's principal
(PREVIEW_OWNER_USERNAME).
"""
from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlsplit

MOCK_API_KEY = "mock-api-key-not-real"          # obviously fake; the only key mock mode accepts
DEFAULT_MOCK_JELLYFIN_URL = "http://127.0.0.1:18096"
DEFAULT_CATALOGUE = Path(__file__).resolve().parents[3] / "avrana-portal" / "portal.py"
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
IDENTITY_MODES = ("headers", "jwt_log_only", "jwt_required")   # same strings as principal.IDENTITY_MODES
MIN_JWT_SECRET_BYTES = 32                                      # same floor as outpost_jwt.MIN_HMAC_SECRET

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


class SettingsError(ValueError):
    """Invalid configuration. Messages name variables, never values."""


class _OwnerPreviewSeal:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<owner preview seal>"


# Passed ONLY by preview/run_preview.py (a test pins the one importer). The environment alone cannot
# select the owner preview: HOME_OWNER_PREVIEW=yes without this token is refused.
_OWNER_PREVIEW_SEAL = _OwnerPreviewSeal()
MAX_MEMBER_USERNAME = 150                       # the principal's own limit


DOCKER_HOST_GATEWAY = "host.docker.internal"   # Docker's alias for this same host (extra_hosts: host-gateway)
_SERVICE_NAME = re.compile(r"[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?")


def plain_http_allowed(host: str) -> bool:
    """Whether a plain-http upstream at `host` stays off the LAN: a loopback address, Docker's host-gateway alias,
    or a single-label Docker service/container name (resolved only by Docker's embedded DNS on a shared,
    isolated network). Every IP literal that is not loopback (LAN, Docker bridge or public) and every dotted
    name is another machine, or could be, so it needs https."""
    host = (host or "").strip("[]").lower()
    if not host:
        return False
    if is_loopback_host(host) or host == DOCKER_HOST_GATEWAY:
        return True
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return _SERVICE_NAME.fullmatch(host) is not None


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
    pwa_sw: bool = True                          # HOME_PWA_SW=off: kill switch, /sw.js serves a self-destruct worker
    motion_proposal: bool = False                # HOME_MOTION_PROPOSAL=on: the 600 ms Proposal for page transitions (MK-6)
    catalogue_path: Path = DEFAULT_CATALOGUE
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8096
    identity_mode: str = "headers"               # "headers" | "jwt_log_only" | "jwt_required" (AVR-498)
    jwt_issuer: str = ""
    jwt_audience: str = ""
    jwt_secret: str = field(default="", repr=False)             # HS256 client secret; never shown
    jwt_secret_previous: str = field(default="", repr=False)    # optional, rotation overlap only
    allowed_users: tuple = ()                    # () = no restriction; beta only, jwt_required only

    owner_preview: bool = False                  # the sealed LAN owner preview (module docstring)
    owner_preview_username: str = ""             # the one principal the member-username overrides apply to
    jellyfin_member_username: str = ""           # "" = the principal's username, exactly (the default rule)
    audiobookshelf_member_username: str = ""     # "" = the principal's username, exactly (the default rule)
    # The sealed token, carried only by settings built through the owner-preview path. Constructing Settings
    # directly (or with dataclasses.replace from unsealed settings) cannot switch the preview or a member
    # username override on: __post_init__ refuses (Home 2.0, AVR-375).
    preview_seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        overrides = (self.owner_preview_username, self.jellyfin_member_username,
                     self.audiobookshelf_member_username)
        if (self.owner_preview or any(overrides)) and self.preview_seal is not _OWNER_PREVIEW_SEAL:
            raise SettingsError("the owner preview and member username overrides are set only by the "
                                "sealed preview entrypoint")
        if any(overrides) and not (self.owner_preview and self.owner_preview_username):
            raise SettingsError("member username overrides need the owner preview and PREVIEW_OWNER_USERNAME")

    def __repr__(self) -> str:
        return (f"Settings(home_sections={self.home_sections}, upstream_mode={self.upstream_mode!r}, "
                f"host={self.host!r}, port={self.port}, owner_preview={self.owner_preview}, "
                f"identity_mode={self.identity_mode!r}, <secrets redacted>)")

    @property
    def uses_real_upstream(self) -> bool:
        return self.upstream_mode == "real"

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        return cls.from_mapping(os.environ if env is None else env)

    @classmethod
    def from_mapping(cls, env: Mapping[str, str], *, owner_preview_seal: object = None) -> "Settings":
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
        pwa_sw = boolean("HOME_PWA_SW", True)
        motion_proposal = boolean("HOME_MOTION_PROPOSAL", False)
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

        preview_env = get("HOME_OWNER_PREVIEW").lower() == "yes"
        sealed = owner_preview_seal is _OWNER_PREVIEW_SEAL
        if owner_preview_seal is not None and not sealed:
            problems.append("the owner preview token is not the sealed one")
        if preview_env and not sealed:
            problems.append("HOME_OWNER_PREVIEW is honoured only by the preview entrypoint (preview/run_preview.py)")
        if sealed and not preview_env:
            problems.append("the preview entrypoint needs HOME_OWNER_PREVIEW=yes")
        owner_preview = preview_env and sealed
        owner_name = get("PREVIEW_OWNER_USERNAME")
        jf_member = get("HOME_JELLYFIN_USERNAME")
        abs_member = get("HOME_AUDIOBOOKSHELF_USERNAME")
        if owner_preview:
            if not owner_name:
                problems.append("PREVIEW_OWNER_USERNAME is required in the owner preview")
            for name, value in (("PREVIEW_OWNER_USERNAME", owner_name), ("HOME_JELLYFIN_USERNAME", jf_member),
                                ("HOME_AUDIOBOOKSHELF_USERNAME", abs_member)):
                if value and (len(value) > MAX_MEMBER_USERNAME or not value.isprintable()
                              or any(c.isspace() for c in value)):
                    problems.append(f"{name} is not a usable username")
            if get("HOME_GATES_VERIFIED"):
                problems.append("HOME_GATES_VERIFIED must not be set in the owner preview "
                                "(the preview does not verify G1/G2; it replaces every identity header)")
        else:
            for name, value in (("PREVIEW_OWNER_USERNAME", owner_name), ("HOME_JELLYFIN_USERNAME", jf_member),
                                ("HOME_AUDIOBOOKSHELF_USERNAME", abs_member)):
                if value:
                    problems.append(f"{name} is accepted only in the owner preview")
            owner_name = jf_member = abs_member = ""
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
            if not owner_preview and get("HOME_GATES_VERIFIED").lower() != "yes":
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
        # HTTPS across machines (owner decision 2026-10-27, ABS admin-token review HIGH): in real mode a plain-http
        # upstream must stay on this machine or inside Docker's isolated networking, so a service key never
        # crosses the LAN in clear text. See `plain_http_allowed`.
        if mode == "real":
            for name, value in (("JELLYFIN_BASE_URL", base_url), ("AUDIOBOOKSHELF_BASE_URL", abs_url),
                                ("KOMGA_BASE_URL", komga_url), ("CALIBRE_WEB_BASE_URL", cw_url)):
                if value and urlsplit(value).scheme == "http" and not plain_http_allowed(url_host(value) or ""):
                    problems.append(f"{name} uses plain http to another machine: use https, or a Docker service "
                                    "name on a shared network (HTTPS across machines)")
        if base_url:
            _check_url(base_url, problems, "JELLYFIN_BASE_URL")
        if abs_url:
            _check_url(abs_url, problems, "AUDIOBOOKSHELF_BASE_URL")
        if komga_url:
            _check_url(komga_url, problems, "KOMGA_BASE_URL")
        if cw_url:
            _check_url(cw_url, problems, "CALIBRE_WEB_BASE_URL")

        # Identity mode (AVR-498). The default keeps today's behaviour exactly; an unknown or empty
        # value is an error, never a silent fallback. The JWT modes need the provider's issuer,
        # audience and HS256 client secret (what Authentik proxy providers sign with; the portal
        # takes the same three values as AVRANA_JWT_*). Unused JWT settings in headers mode are an
        # error so nobody believes a token is being checked when it is not.
        id_mode = _identity_mode(env, problems)
        jwt_issuer, jwt_audience = get("HOME_JWT_ISSUER"), get("HOME_JWT_AUDIENCE")
        jwt_secret = _read_key(env, problems, "HOME_JWT_SECRET")
        jwt_previous = _read_key(env, problems, "HOME_JWT_SECRET_PREVIOUS")
        if id_mode == "headers":
            if jwt_issuer or jwt_audience or jwt_secret or jwt_previous:
                problems.append("HOME_JWT_* is set but HOME_IDENTITY_MODE is headers "
                                "(nothing would be verified; choose jwt_log_only or jwt_required)")
        else:
            if not jwt_issuer:
                problems.append("HOME_JWT_ISSUER is required in a JWT identity mode")
            if not jwt_audience:
                problems.append("HOME_JWT_AUDIENCE is required in a JWT identity mode")
            if not jwt_secret:
                problems.append("HOME_JWT_SECRET or HOME_JWT_SECRET_FILE is required in a JWT identity mode")
            for name, value in (("HOME_JWT_SECRET", jwt_secret), ("HOME_JWT_SECRET_PREVIOUS", jwt_previous)):
                if value and len(value.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
                    problems.append(f"{name} must be at least {MIN_JWT_SECRET_BYTES} bytes")
            if jwt_previous and not jwt_secret:
                problems.append("HOME_JWT_SECRET_PREVIOUS needs HOME_JWT_SECRET")

        # The Audiobookshelf token is an ADMIN token (ADAPTER-CONTRACT 11; it reads every member's progress), so a
        # forged username would read another member's listening. Independent ABS admin-token review 2026-10-27
        # (HIGH, owner decision): in real mode it is accepted only with verified identity (jwt_required). The
        # sealed owner preview is exempt: it strips every inbound identity header and serves only the owner.
        if mode == "real" and abs_url and id_mode != "jwt_required" and not sealed:
            problems.append("AUDIOBOOKSHELF_TOKEN is an admin token: real mode needs HOME_IDENTITY_MODE=jwt_required")

        # Beta allowlist (AVR-373): a second lock behind the Authentik application binding. It only
        # means something when the username comes from a verified token, so any other mode refuses it.
        allowed = _allowed_users(env, problems)
        if allowed and id_mode != "jwt_required":
            problems.append("HOME_ALLOWED_USERS needs HOME_IDENTITY_MODE=jwt_required")

        if problems:
            raise SettingsError("invalid configuration: " + "; ".join(problems))
        return cls(home_sections=sections, upstream_mode=mode, jellyfin_base_url=base_url,
                   jellyfin_api_key=key, audiobookshelf_base_url=abs_url,
                   audiobookshelf_token=abs_token, komga_base_url=komga_url,
                   komga_token=komga_token, komga_owner_confirms=komga_confirms,
                   calibre_web_base_url=cw_url,
                   calibre_web_credential=cw_cred, calibre_web_owner_confirms=cw_confirms, timeout=timeout, section_limit=limit,
                   health_detail=detail, pwa_sw=pwa_sw, motion_proposal=motion_proposal, catalogue_path=catalogue, log_level=level,
                   host=host, port=port, owner_preview=owner_preview, owner_preview_username=owner_name,
                   jellyfin_member_username=jf_member, audiobookshelf_member_username=abs_member,
                   preview_seal=_OWNER_PREVIEW_SEAL if owner_preview else None,
                   identity_mode=id_mode, jwt_issuer=jwt_issuer, jwt_audience=jwt_audience,
                   jwt_secret=jwt_secret, jwt_secret_previous=jwt_previous, allowed_users=allowed)


def is_sealed_preview(settings: object) -> bool:
    """True only for Settings built through the sealed owner-preview path. Used by main.py before it hands a member
    username override to an adapter, so an override can never come from unsealed settings."""
    return (isinstance(settings, Settings) and settings.owner_preview is True
            and settings.preview_seal is _OWNER_PREVIEW_SEAL)


def _allowed_users(env: Mapping[str, str], problems: list) -> tuple:
    """Absent -> no restriction. Present -> a comma-separated list of exact usernames; an empty list
    or a malformed entry is an error, never a silent "everyone"."""
    if "HOME_ALLOWED_USERS" not in env:
        return ()
    names = [n.strip() for n in str(env["HOME_ALLOWED_USERS"]).split(",")]
    if not names or any(not n or len(n) > 150 or not n.isascii() or not n.isprintable()
                        or any(c.isspace() for c in n) for n in names):
        problems.append("HOME_ALLOWED_USERS must be a comma-separated list of usernames")
        return ()
    return tuple(sorted(set(names)))


def _identity_mode(env: Mapping[str, str], problems: list) -> str:
    """Absent -> headers. Present but empty, unknown or differently cased -> an error."""
    if "HOME_IDENTITY_MODE" not in env:
        return "headers"
    raw = str(env["HOME_IDENTITY_MODE"]).strip()
    if raw not in IDENTITY_MODES:
        problems.append("HOME_IDENTITY_MODE must be headers, jwt_log_only or jwt_required")
        return "headers"
    return raw


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
