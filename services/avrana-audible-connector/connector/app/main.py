"""Application factory and wiring."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import oidc
from .companion_client import CompanionClient
from .config import Settings
from .db import migrate
from .routes import flow, health
from .security import Csrf, RateLimiter, redact

_APP_DIR = Path(__file__).parent


def _asset_version(path: Path) -> str:
    """Short content hash, appended to the stylesheet URL as `?v=`.

    Cloudflare caches /static/*.css at the edge for four hours, so a restyle stayed invisible on
    contribute.avrana.net long after the container was rebuilt (observed: the edge served the
    previous stylesheet with cf-cache-status HIT while the origin served the new one). The page
    HTML is DYNAMIC and never cached, so giving the stylesheet a content-derived URL means a
    deploy changes the cache key and the new CSS is fetched immediately, with no cache purge and
    no Cloudflare API credentials. Falls back to "dev" if the file cannot be read, which only
    costs the cache-busting, not the page.
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return "dev"


class _RedactingFilter(logging.Filter):
    """Last-line-of-defence: scrub URLs/tokens from every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(str(record.getMessage()))
            record.args = ()
        except Exception:
            pass
        return True


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()

    logging.getLogger().addFilter(_RedactingFilter())

    app = FastAPI(title="Avrana Audible Connector", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.csrf = Csrf(settings.secret_key)
    app.state.rate = RateLimiter(settings.rate_limit_window_seconds, settings.rate_limit_max)
    app.state.companion = CompanionClient(
        settings.companion_base_url, settings.companion_token, settings.companion_timeout_seconds
    )
    templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))
    templates.env.globals["brand"] = settings.brand_name
    templates.env.globals["asset_v"] = _asset_version(_APP_DIR / "static" / "style.css")
    app.state.templates = templates

    migrate(settings.db_path)

    app.mount("/static", StaticFiles(directory=str(_APP_DIR / "static")), name="static")
    app.include_router(health.router)
    app.include_router(oidc.router)
    app.include_router(flow.router)

    @app.exception_handler(HTTPException)
    async def _auth_redirect(request: Request, exc: HTTPException):
        # For unauthenticated HTML GETs under OIDC, send the user to log in instead of a
        # bare 401. Everything else returns the normal error response.
        accepts_html = "text/html" in request.headers.get("accept", "")
        if (
            exc.status_code == 401
            and request.method == "GET"
            and settings.auth_mode == "oidc"
            and accepts_html
            and not request.url.path.startswith("/auth/")
        ):
            return RedirectResponse("/auth/login", status_code=302)
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.on_event("startup")
    async def _start_scheduler() -> None:
        # Disabled under tests (they call scheduler_tick directly).
        if settings.dev_identity and settings.dev_identity.startswith("test:"):
            return
        from .sync import scheduler_loop

        app.state._scheduler = asyncio.create_task(scheduler_loop(app.state))

    return app
