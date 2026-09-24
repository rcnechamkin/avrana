"""Runtime configuration, read once from the environment.

No secrets are hard-coded. The companion bearer token is read from a file (mounted
read-only), never from an environment variable, so it cannot leak via `docker inspect`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _read_secret_file(path: str | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class Settings:
    # Companion (private network only; never published)
    companion_base_url: str
    companion_token: str
    companion_timeout_seconds: float

    # Identity / authorization
    required_group: str
    # auth_mode: "oidc" (default, matches ABS/Komga on this host) | "header" (behind an
    # Authentik proxy outpost) | "dev" (tests).
    auth_mode: str
    # OIDC (Authentik). client_secret comes from a file, never an env var.
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    public_base_url: str
    # Header names injected by an Authentik proxy outpost (auth_mode="header").
    hdr_sub: str
    hdr_username: str
    hdr_email: str
    hdr_groups: str
    # Dev/test escape hatch: trust a static identity. Never set in production.
    dev_identity: str

    # Persistence
    db_path: str

    # Cookies / CSRF signing
    secret_key: str
    cookie_secure: bool

    # Behaviour
    session_ttl_seconds: int
    rate_limit_window_seconds: int
    rate_limit_max: int
    scan_interval_hours: int
    brand_name: str

    @staticmethod
    def load() -> "Settings":
        secret = _read_secret_file(os.environ.get("SECRET_KEY_FILE")) or os.environ.get(
            "SECRET_KEY", ""
        )
        if not secret:
            # A missing signing key must fail closed, not silently use a static default.
            raise RuntimeError("SECRET_KEY_FILE or SECRET_KEY must be set")
        token = _read_secret_file(os.environ.get("COMPANION_TOKEN_FILE"))
        oidc_secret = _read_secret_file(os.environ.get("OIDC_CLIENT_SECRET_FILE")) or os.environ.get(
            "OIDC_CLIENT_SECRET", ""
        )
        return Settings(
            companion_base_url=os.environ.get(
                "COMPANION_BASE_URL", "http://companion:8080"
            ).rstrip("/"),
            companion_token=token,
            companion_timeout_seconds=float(os.environ.get("COMPANION_TIMEOUT", "30")),
            required_group=os.environ.get("REQUIRED_GROUP", "library-contributors"),
            auth_mode=os.environ.get("AUTH_MODE", "oidc").lower(),
            oidc_issuer=os.environ.get("OIDC_ISSUER", "").rstrip("/"),
            oidc_client_id=os.environ.get("OIDC_CLIENT_ID", ""),
            oidc_client_secret=oidc_secret,
            public_base_url=os.environ.get("PUBLIC_BASE_URL", "").rstrip("/"),
            hdr_sub=os.environ.get("HDR_SUB", "x-authentik-uid"),
            hdr_username=os.environ.get("HDR_USERNAME", "x-authentik-username"),
            hdr_email=os.environ.get("HDR_EMAIL", "x-authentik-email"),
            hdr_groups=os.environ.get("HDR_GROUPS", "x-authentik-groups"),
            dev_identity=os.environ.get("DEV_IDENTITY", ""),
            db_path=os.environ.get("DB_PATH", "/data/connector.db"),
            secret_key=secret,
            cookie_secure=os.environ.get("COOKIE_SECURE", "true").lower() != "false",
            session_ttl_seconds=int(os.environ.get("SESSION_TTL", "1800")),
            rate_limit_window_seconds=int(os.environ.get("RATE_LIMIT_WINDOW", "300")),
            rate_limit_max=int(os.environ.get("RATE_LIMIT_MAX", "20")),
            scan_interval_hours=int(os.environ.get("SCAN_INTERVAL_HOURS", "24")),
            brand_name=os.environ.get("BRAND_NAME", "Avrana"),
        )
