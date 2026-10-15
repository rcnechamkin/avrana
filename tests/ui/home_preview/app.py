"""Member home preview (AVR-426, recomposed in AVR-452): a design preview, not a service.

    python -m uvicorn tests.ui.home_preview.app:app --host 127.0.0.1 --port 8200

Server-rendered with FastAPI and Jinja, like the Media 2.0 home is planned to be, and with no
JavaScript at all. It reads fixtures only (fixtures.py): no adapter, no key, no identity header,
no library and no network call. `/before` renders today's portal home from the code in Git, for
comparison. Nothing here is deployed or deployable.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import fixtures

HERE = Path(__file__).resolve().parent
PORTAL = HERE.parents[2] / "services" / "avrana-portal" / "portal.py"
# Every library group and no admin group: the fixture member sees what an ordinary member sees.
FIXTURE_GROUPS = {"avrana-users", "avrana-videos", "avrana-audiobooks", "avrana-books", "avrana-comics"}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


@app.middleware("http")
async def headers(request: Request, call_next):
    response = await call_next(request)
    # No script source at all: the page has to work as plain HTML and CSS.
    # (/before is the portal as it is in Git, and the portal writes its stylesheet into the page.)
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'" if request.url.path == "/before" else
        "default-src 'none'; img-src 'self'; style-src 'self'; base-uri 'none'; form-action 'none'")
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store"
    return response


def _common(state: str, art: str, who: str) -> dict:
    """What every page needs to keep the preview's switches: the state, the viewer and the artwork."""
    if state not in fixtures.STATES or who not in fixtures.VIEWERS:
        raise HTTPException(404)
    q = f"state={state}" + ("" if who == "member" else f"&who={who}")
    return {"state": state, "states": fixtures.STATES, "viewers": fixtures.VIEWERS,
            "art": "mono" if art == "mono" else "colour", "q": q}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, state: str = "healthy", art: str = "colour", new: str = "all", who: str = "member"):
    common = _common(state, art, who)
    return templates.TemplateResponse(request, "home.html", {**common, **fixtures.page(state, new, who)})


@app.get("/new", response_class=HTMLResponse)
def new(request: Request, state: str = "healthy", art: str = "colour", lib: str = "", who: str = "member"):
    """Everything new, one library at a time: browsing has a page of its own, off the home page."""
    common = _common(state, art, who)
    return templates.TemplateResponse(request, "new.html", {**common, **fixtures.new_page(state, lib, who)})


@app.get("/art/{shape}/{slug}.svg")
def art(shape: str, slug: str):
    svg = fixtures.cover(shape, slug)
    if svg is None:
        raise HTTPException(404)
    return Response(svg, media_type="image/svg+xml")


@app.get("/stop", response_class=HTMLResponse)
def stop(request: Request, to: str = ""):
    """Where every link in the preview ends: it says what the product would do, and does nothing."""
    return templates.TemplateResponse(request, "stop.html", {"to": to[:80]})


@app.get("/before", response_class=HTMLResponse)
def before():
    """Today's portal home, rendered by the portal's own code for the same fixture member."""
    spec = importlib.util.spec_from_file_location("avrana_portal_for_preview", PORTAL)
    portal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(portal)
    return HTMLResponse(portal.render_home(set(FIXTURE_GROUPS)))
