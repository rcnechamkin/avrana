"""Application factory. No import-time side effects; no global holds member data.

`create_app(settings)` loads the catalogue, builds the template environment and (only when
`HOME_SECTIONS` is on) the adapters, then returns a FastAPI app. It reads no environment, opens
no socket and does not configure logging (the server entry points do).

Routing is one catch-all that mirrors the portal exactly (see `routing.py`): the portal answers
every path itself and treats a denied route and an unknown route identically, so the application
does the same. Every request reaches the route through the single identity dependency.
"""
from __future__ import annotations

import base64
import contextlib
import logging
from pathlib import Path
from typing import Optional, Sequence

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..adapters.audiobookshelf import AudiobookshelfAdapter
from ..adapters.jellyfin import JellyfinAdapter
from ..adapters.calibre_web import CalibreWebAdapter
from ..adapters.komga import KomgaAdapter
from ..aggregate import gather, health_summary, search as run_search
from ..contract import MediaAdapter
from ..cache import MemberCache
from ..resilience import SystemClock, UrllibTransport
from . import catalogue as catalogue_mod
from .catalogue import Trusted
from . import artwork as artwork_mod
from . import install as install_mod
from .identity import (IdentityResolver, Viewer, get_viewer, has_identity_headers,
                       new_tab_from_scope, search_term_from_scope)
from .logsafe import app_log, log_event, silence_uvicorn_access
from .middleware import HygieneMiddleware
from . import recovery
from .routing import (AccountFacts, Decision, chooser_intro, decide, normalise_target, not_found, parse_title_route,
                      search_decision, title_decision, trouble_decision)
from .settings import Settings, is_sealed_preview
from .viewmodel import (ACCOUNT_LIBRARY, INTERSTITIAL_SHELL, NO_LIBRARY, REQUEST_FOR, SERVICE_LABEL,
                        account_access, build_home, build_search, build_shell, build_title)

TEMPLATES = Path(__file__).resolve().parent / "templates"
HTML = "text/html; charset=utf-8"
# Pages that wear the shell (masthead with places, Search, Help and the account menu) when sections are on.
SHELL_PAGES = {"/account": "account", "/help": "help", "/help/{slug}": "help-topic",
               "/{chooser}": "place", "/{service}": "place"}


def _trusted(value):
    if not isinstance(value, Trusted):
        raise TypeError("only catalogue text may be rendered unescaped")
    return Markup(value)


def make_environment() -> Environment:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True, auto_reload=False, trim_blocks=True,
                      lstrip_blocks=True, keep_trailing_newline=True)
    env.filters["trusted"] = _trusted
    # The one stylesheet lives in templates/style.css (a copy of the portal's; the parity test
    # fails if the portal's changes, which is the cue to update this file).
    env.globals["stylesheet"] = Markup("\n" + (TEMPLATES / "style.css").read_text(encoding="utf-8"))
    # The Home design's rules (home.css) are added to the page ONLY when the home sections render, so every
    # other page, and Home with sections off, stays byte-identical to the portal (the parity test).
    env.globals["home_stylesheet"] = Markup("\n" + (TEMPLATES / "home.css").read_text(encoding="utf-8"))
    env.globals["no_library_said"] = NO_LIBRARY
    return env


def _member_username(settings: Settings, upstream_name: str):
    """(owner principal username, upstream username) for one adapter's user lookup, or None (the default
    rule). settings.py accepts these values only in the sealed owner preview."""
    if is_sealed_preview(settings) and settings.owner_preview_username and upstream_name:
        return (settings.owner_preview_username, upstream_name)
    return None


def build_adapters(settings: Settings, cache: MemberCache) -> list:
    """Real transports are built ONLY when sections are on. Mock mode (the default) can only
    point at a loopback address with a fixed fake key (see settings.py). All adapters share the
    one per-process cache (in-memory SQLite; there is deliberately no setting for a file path)."""
    if not settings.home_sections:
        return []
    transport = UrllibTransport(settings.jellyfin_base_url,
                                {"Authorization": f'MediaBrowser Token="{settings.jellyfin_api_key}"'})
    adapter = JellyfinAdapter(transport, timeout=settings.timeout, cache=cache,
                              member_username=_member_username(settings, settings.jellyfin_member_username))
    # contract.py:271 does `cache or MemberCache(...)`, and an EMPTY cache is falsy (__len__), so a
    # freshly injected cache is silently replaced. Re-assert the shared one (reported upstream).
    adapter.cache = cache
    adapters = [adapter]
    if settings.audiobookshelf_base_url:          # off unless configured (settings.py validates)
        abs_transport = UrllibTransport(settings.audiobookshelf_base_url,
                                        {"Authorization": f"Bearer {settings.audiobookshelf_token}"})
        abs_adapter = AudiobookshelfAdapter(
            abs_transport, timeout=settings.timeout, cache=cache,
            member_username=_member_username(settings, settings.audiobookshelf_member_username))
        abs_adapter.cache = cache
        adapters.append(abs_adapter)
    if settings.komga_base_url:                   # off unless configured (settings.py validates)
        komga_transport = UrllibTransport(settings.komga_base_url, {"X-API-Key": settings.komga_token})
        # Komga is a SHARED regular-account view (ADAPTER-CONTRACT 12.2, owner decision 2026-10-15), like
        # Calibre-Web below: the adapter refuses to be built without the owner's statement that no member has
        # a Komga restriction. Mock mode (synthetic data) states it itself; real mode takes the value
        # settings.py only accepts when KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=yes.
        komga_confirmed = (settings.upstream_mode == "mock") or settings.komga_owner_confirms
        komga_adapter = KomgaAdapter(komga_transport, timeout=settings.timeout, cache=cache,
                                     owner_confirms_no_member_restrictions=komga_confirmed)
        komga_adapter.cache = cache
        adapters.append(komga_adapter)
    if settings.calibre_web_base_url:             # off unless configured (settings.py validates)
        basic = base64.b64encode(settings.calibre_web_credential.encode("utf-8")).decode("ascii")
        cw_transport = UrllibTransport(settings.calibre_web_base_url, {"Authorization": f"Basic {basic}"})
        # Calibre-Web is a SHARED view (ADAPTER-CONTRACT 13.2): every member with the books group sees what
        # the one viewer account sees. The adapter refuses to be built without the owner's statement that no
        # member has a Calibre-Web restriction. In mock mode (synthetic data, one fake catalogue) there is
        # nothing to restrict, so we state it explicitly; in real mode settings.py only accepts a Calibre-Web
        # URL when CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=yes, and that value is what is passed.
        confirmed = (settings.upstream_mode == "mock") or settings.calibre_web_owner_confirms
        cw_adapter = CalibreWebAdapter(cw_transport, timeout=settings.timeout, cache=cache,
                                       owner_confirms_no_member_restrictions=confirmed)
        cw_adapter.cache = cache
        adapters.append(cw_adapter)
    return adapters


def _is_loopback_peer(request: Request) -> bool:
    client = request.client
    return client is not None and client.host in ("127.0.0.1", "::1")


def create_app(settings: Settings, *, adapters: Optional[Sequence[MediaAdapter]] = None) -> FastAPI:
    """`adapters` lets tests inject fakes; otherwise they are built from `settings`."""
    silence_uvicorn_access()      # whoever serves this app, uvicorn must not log raw query strings
    cat = catalogue_mod.load(settings.catalogue_path)
    env = make_environment()
    # One disposable cache per process, default in-memory database, closed on shutdown. (Offboarding
    # hook for later: MemberCache.purge_member(principal); wired into nothing yet. A file-backed
    # cache is an owner decision, see HOME-APP.md, and has no setting.)
    cache = MemberCache(SystemClock())
    adapter_list = list(adapters) if adapters is not None else build_adapters(settings, cache)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            cache.close()

    app = FastAPI(title="Avrana home", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.cache = cache
    app.router.redirect_slashes = False
    app.state.settings = settings
    app.state.identity = IdentityResolver.from_settings(settings)    # SettingsError = refuse to start
    app.state.catalogue = cat
    app.state.adapters = adapter_list
    app.state.env = env
    # Libraries whose search results link to a title page: those whose adapter offers the permission-checked
    # item lookup (`item`). The others' results link straight to the library.
    title_services = frozenset(a.service.value for a in adapter_list if "item" not in a.not_offered)

    def render(template: str, status: int = 200, **ctx) -> Response:
        body = env.get_template(template).render(**ctx)
        return Response(body, status_code=status, media_type=HTML)

    def respond(decision: Decision, scope=None, **extra) -> Response:
        """The one place a page is rendered. When it wears the shell (which prints the manifest link), the same call
        tells the middleware to allow `manifest-src 'self'`: the tags and the CSP cannot disagree. A shell page
        must pass `scope`; forgetting it is an error, not a silently mismatched CSP."""
        if extra.get("shell") is not None:
            if scope is None:
                raise TypeError("a shell page must pass the request scope to respond()")
            mark_shell(scope, extra["shell"])
        if decision.plain is not None:
            return Response(decision.plain, status_code=decision.status,
                            media_type="text/plain; charset=utf-8")
        if decision.status == 307:
            return Response(b"", status_code=307, headers={"Location": decision.location},
                            media_type=HTML)
        return render(decision.template, decision.status, **dict(decision.context), **extra)

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False,
                   response_model=None)
    async def portal_route(request: Request, viewer: Viewer = Depends(get_viewer)) -> Response:
        raw = request.scope.get("raw_path") or request.scope["path"].encode("latin-1", "replace")
        route = normalise_target(raw.decode("latin-1"))
        scope = request.scope

        if route == "/readyz":
            allowed = (settings.health_detail == "loopback" and _is_loopback_peer(request)
                       and not has_identity_headers(scope))
            if not allowed:
                scope["avrana_route"] = "not_found"
                return respond(not_found())
            scope["avrana_route"] = "/readyz"
            return JSONResponse(health_summary(adapter_list))

        if route == "/home.json" and settings.home_sections:
            if viewer.principal is None:
                scope["avrana_route"] = "not_found"
                return respond(not_found())
            scope["avrana_route"] = "/home.json"
            return JSONResponse(await _gather(viewer))

        if route == "/search" and settings.home_sections:
            if viewer.principal is None:
                scope["avrana_route"] = "not_found"
                return respond(not_found())
            term = search_term_from_scope(scope)          # bounded text; never logged or echoed raw
            result = await run_in_threadpool(run_search, viewer.principal, adapter_list, term,
                                             settings.section_limit)
            for s in result.sections:                     # service, state and a fixed reason only
                log_event(app_log, logging.INFO, "section", service=s.service.value,
                          section=s.section, state=s.state.value, reason=s.reason or "")
            decision = search_decision(build_search(result.search_view(), term, title_services=title_services,
                                                    request_hosts=request_hosts(viewer)))
            scope["avrana_route"] = decision.label
            return respond(decision, scope, shell=shell_for(viewer, "search"))

        if route.startswith("/title/") and settings.home_sections and adapter_list:
            # A title page (AVR-384). Unknown service, malformed id, no principal, no group, unknown or hidden
            # item: the one standard 404, exactly as an unknown route (portal parity, never 403).
            parsed = parse_title_route(route)
            adapter = None
            if parsed is not None and viewer.principal is not None:
                adapter = next((a for a in adapter_list if a.service.value == parsed[0]
                                and "item" not in a.not_offered), None)
            page = None
            if adapter is not None:
                # Always the permission-checked upstream lookup (fresh=True: no cache read or write).
                section = await run_in_threadpool(lambda: adapter.item(viewer.principal, parsed[1], fresh=True))
                log_event(app_log, logging.INFO, "section", service=section.service.value,
                          section=section.section, state=section.state.value, reason=section.reason or "")
                page = build_title(section.to_dict(), parsed[0], parsed[1], search_term_from_scope(scope))
            if page is None:
                scope["avrana_route"] = "not_found"
                return respond(not_found())
            decision = title_decision(page)
            scope["avrana_route"] = decision.label
            return respond(decision, scope, shell=shell_for(viewer, "title"))

        if route.startswith(artwork_mod.PREFIX):
            ref = artwork_mod.ref_from_route(route)
            result = None
            if ref is not None and settings.home_sections and adapter_list:
                result = await run_in_threadpool(artwork_mod.fetch, viewer.principal, adapter_list, ref)
            if result is None:           # unknown service, bad ref, no group, not visible, upstream
                scope["avrana_route"] = "not_found"          # trouble: one and the same 404
                return respond(not_found())
            scope["avrana_route"] = "/art/{ref}"
            return Response(result.data, media_type=result.content_type,
                            headers={"Cache-Control": artwork_mod.CACHE_CONTROL})

        # Installable Home and the approved brand files (install.py, brand.py): only where the shell can render, so
        # with sections off these paths stay the portal's 404. Static bytes, the same for every viewer, so no
        # identity is needed to fetch them.
        asset = install_mod.asset_for(route) if (settings.home_sections and adapter_list) else None
        if asset is not None:
            scope["avrana_route"] = ("/manifest.webmanifest" if route == install_mod.MANIFEST_PATH
                                     else "/brand/{file}" if route.startswith("/brand/") else "/icons/{size}")
            return Response(asset[0], media_type=asset[1])

        p = viewer.principal
        facts = AccountFacts(name=(p.name or "").strip(), username=p.username,
                             email=(p.email or "").strip()) if p is not None else None
        if route == recovery.ROUTE and settings.home_sections and p is not None and adapter_list:
            # "If something doesn't open" exists only with the shell; otherwise the path stays unknown (parity).
            decision = trouble_decision(viewer.groups)
            scope["avrana_route"] = decision.label
            return respond(decision, scope, shell=shell_for(viewer, "help-topic"))
        decision = decide(route, viewer.groups, cat, facts)
        scope["avrana_route"] = decision.label
        extra = {}
        if decision.label == "/" and settings.home_sections and p is not None and adapter_list:
            home = build_home(await _gather(viewer), decision.context["tiles"],
                              new_tab=new_tab_from_scope(scope), limit=settings.section_limit,
                              member_name=(facts.name or facts.username))
            extra["home"] = home
            extra["shell"] = shell_for(viewer, "home", places=home.places)
        elif decision.status == 200 and decision.label in SHELL_PAGES:
            extra["shell"] = shell_for(viewer, SHELL_PAGES[decision.label])
            if decision.label == "/{chooser}" and extra["shell"] is not None:
                extra["intro"] = chooser_intro(decision.context["chooser"].path)
            if decision.label == "/account" and extra["shell"] is not None:
                # Shell only: libraries and requests in Home's language. Sections off keeps the portal's list.
                extra["shell_access"] = account_access(
                    [(s.path, cat.service_copy(s, viewer.groups)[0]) for s in cat.permitted(viewer.groups)],
                    viewer.groups)
            if decision.label == "/{service}" and extra["shell"] is not None:
                path = decision.context["svc"].path
                if path in ACCOUNT_LIBRARY:
                    extra["library"] = SERVICE_LABEL[ACCOUNT_LIBRARY[path]]
                extra["shell_warning"] = INTERSTITIAL_SHELL.get(path)
        return respond(decision, scope, **extra)

    def mark_shell(scope, shell) -> None:
        """Tell the middleware this response is a shell page: only these pages link the manifest and load the brand
        font, so only these get `manifest-src 'self'; font-src 'self'` in their CSP (middleware.py). Every other
        response keeps the CSP unchanged."""
        if shell is not None:
            scope["avrana_shell"] = True

    def request_hosts(viewer: Viewer) -> dict:
        """The request services (catalogue path -> host) this member's groups open, for search's empty-results
        fallback. Static catalogue data only; nothing from the request."""
        out = {}
        for path in {p for p, _noun in REQUEST_FOR.values()}:
            svc = cat.service(path)
            if svc is not None and svc.allows(viewer.groups):
                out[path] = svc.host
        return out

    def shell_for(viewer: Viewer, current: str, places=None):
        """The masthead data (places, Search, Help, account menu) for a shell page, or None where the shell is
        not on (sections off: the pages stay byte-identical to the portal). No upstream call is made here."""
        p = viewer.principal
        if not (settings.home_sections and p is not None and adapter_list):
            return None
        tiles = decide("/", viewer.groups, cat).context["tiles"]
        return build_shell(tiles, current, (p.name or "").strip() or p.username, places=places)

    async def _gather(viewer: Viewer) -> dict:
        """The sections for the verified member, via the adapters' own principal checks and
        bounded timeouts. One failing adapter costs its own section only."""
        result = await run_in_threadpool(gather, viewer.principal, adapter_list,
                                        ("continue", "recent"), settings.section_limit)
        for s in result.sections:
            log_event(app_log, logging.INFO, "section", service=s.service.value,
                      section=s.section, state=s.state.value, reason=s.reason or "")
        return result.member_view()

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        request.scope.setdefault("avrana_route", "error")
        if exc.status_code == 404:
            return respond(not_found())
        return render("error.html", exc.status_code if exc.status_code >= 400 else 500)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        request.scope.setdefault("avrana_route", "error")
        return render("error.html", 422)

    app.add_middleware(HygieneMiddleware, render_error=lambda: env.get_template("error.html")
                       .render().encode("utf-8"))
    log_event(app_log, logging.INFO, "app_created")
    return app
