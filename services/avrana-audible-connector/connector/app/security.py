"""CSRF, rate limiting, redaction, and path/identifier sanitization."""
from __future__ import annotations

import hmac
import re
import time
from hashlib import sha256

from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

# --- Redaction -------------------------------------------------------------------------
# The pasted final redirect URL and any bearer token must never reach logs, traces, or
# exception messages. These patterns scrub the obvious carriers.
_REDACT_PATTERNS = [
    re.compile(r"https?://[^\s\"']*(?:openid|oauth|signin|ap/|authorize|code=|access_token=)[^\s\"']*", re.I),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"),
    re.compile(r"(?i)(response_?url[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"),
    re.compile(r"(?i)(token[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9._\-]{8,}"),
]


def redact(text: str | None) -> str:
    if not text:
        return ""
    out = str(text)
    for pat in _REDACT_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) if m.groups() else "") + "[REDACTED]", out)
    return out


# --- CSRF ------------------------------------------------------------------------------
class Csrf:
    """Signed double-submit token bound to the Authentik subject."""

    def __init__(self, secret_key: str):
        self._s = URLSafeTimedSerializer(secret_key, salt="avrana-audible-csrf")

    def issue(self, sub: str) -> str:
        return self._s.dumps({"sub": sub})

    def verify(self, token: str, sub: str, max_age: int = 3600) -> bool:
        try:
            data = self._s.loads(token, max_age=max_age)
        except BadSignature:
            return False
        except Exception:
            return False
        return hmac.compare_digest(str(data.get("sub", "")), sub)


async def require_csrf(request: Request, sub: str) -> None:
    csrf: Csrf = request.app.state.csrf
    token = request.headers.get("x-csrf-token", "")
    if not token:
        form = await request.form()
        token = str(form.get("csrf_token", ""))
    if not csrf.verify(token, sub):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid or missing CSRF token")


# --- Rate limiting ---------------------------------------------------------------------
class RateLimiter:
    """Fixed-window in-memory limiter, keyed by (bucket, subject). Adequate for a single
    connector replica; move to the DB if horizontally scaled."""

    def __init__(self, window_seconds: int, max_hits: int):
        self.window = window_seconds
        self.max = max_hits
        self._hits: dict[str, list[float]] = {}

    def check(self, bucket: str, sub: str) -> None:
        key = f"{bucket}:{sub}"
        now = time.time()
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        if len(hits) >= self.max:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, slow down"
            )
        hits.append(now)
        self._hits[key] = hits


# --- Path / identifier sanitization ----------------------------------------------------
_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def valid_asin(asin: str) -> bool:
    return bool(_ASIN_RE.match(asin or ""))


def valid_id(value: str) -> bool:
    return bool(_ID_RE.match(value or ""))


def safe_component(value: str) -> str:
    """A defensive path-component sanitizer. Output paths are never built from titles;
    this exists as a second line of defence for any value that reaches the filesystem."""
    digest = sha256((value or "").encode("utf-8")).hexdigest()[:16]
    # Dots are excluded so the result can never be "." / ".." or embed a traversal.
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", (value or ""))[:40]
    return f"{cleaned or 'x'}-{digest}"
