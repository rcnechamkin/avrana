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
import dataclasses
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
from urllib.parse import urlencode

from ..contract import REQUIRED_GROUP, MediaAdapter, Service, build_handoff_url
from ..cache import MemberCache
from ..member_keys import MemberKeyStore
from ..provision import Provisioner, build_provisioner
from ..quickconnect import OUTCOMES as QC_OUTCOMES, QuickConnect
from ..resilience import SystemClock, UrllibTransport
from . import catalogue as catalogue_mod
from .catalogue import Trusted
from . import artwork as artwork_mod
from . import install as install_mod
from . import notice as notice_mod
from . import pwa as pwa_mod
from . import bookrequests as bookreq_mod
from ..requests.forms import Flash, FormSigner, RequestGuard, SearchCache, SearchLimiter, form_key
from ..requests.owned import OwnedIndex
from ..requests.seerr import MediaState, SeerrRequests
from . import watchrequests as watch_mod
from ..requests.shelfarr import FORMAT_GROUP, ShelfarrRequests, clean_term, member_username
from . import forms as forms_mod
from . import security as security_mod
from .identity import (IdentityResolver, Viewer, get_viewer, has_identity_headers, home_filter_from_scope,
                       if_none_match_from_scope, library_chip_from_scope, library_view_from_scope, new_tab_from_scope,
                       same_origin_form_post, search_term_from_scope, security_state_from_scope, tv_result_from_scope)
from .logsafe import app_log, log_event, silence_uvicorn_access
from .middleware import MAX_FORM_BODY, NOT_IMPLEMENTED_BODY, HygieneMiddleware
from . import recovery
from .routing import (ME_ROUTE, AccountFacts, Decision, chooser_intro, decide, library_decision, me_decision,
                      normalise_target, not_found, parse_title_route, search_decision, title_decision, trouble_decision)
from .settings import Settings, is_sealed_preview
from .viewmodel import (ACCOUNT_LIBRARY, CONTRIBUTE_PATH, INTERSTITIAL_SHELL, LIBRARY_PLACE, NO_LIBRARY, REQUEST_FOR,
                        SERVICE_LABEL, account_access, build_home, build_library, build_me, build_search, build_shell,
                        build_title, extra_sections_for, has_library, library_extra_sections, place_link, title_href)

TEMPLATES = Path(__file__).resolve().parent / "templates"
HTML = "text/html; charset=utf-8"
# Pages that wear the shell (the places bar on Home, the tab bar everywhere) when sections are on.
SHELL_PAGES = {"/account": "account", "/help": "help", "/help/{slug}": "help-topic",
               "/{chooser}": "place", "/{service}": "place"}


def _trusted(value):
    if not isinstance(value, Trusted):
        raise TypeError("only catalogue text may be rendered unescaped")
    return Markup(value)


# MK-6 (AVR-720): the motion Proposal, off by default. Tier 3 page transitions are 200 ms (home.css); with
# HOME_MOTION_PROPOSAL=on this rule is appended to the shell stylesheet (so to shell pages and the offline page, which
# carries it) and they take the 600 ms Proposal token instead, so the owner can compare. Still nothing at all with Reduce Motion. Off, the stylesheet is unchanged.
MOTION_PROPOSAL_CSS = ("  /* Proposal (HOME_MOTION_PROPOSAL=on, default off): page transitions at the 600 ms token. */\n"
                       "  @media (prefers-reduced-motion:no-preference){::view-transition-group(*),::view-transition-old(*),"
                       "::view-transition-new(*){animation-duration:var(--motion-3-proposal);}}\n")


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
    # MK-3 (AVR-717): the page script path (a content hash), the sign-out hop and the kill switch, for shell pages.
    env.globals["page_script"] = pwa_mod.script_path()
    env.globals["shell_signout"] = pwa_mod.SIGNOUT_PATH
    env.globals["pwa_sw_off"] = False
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
        # Members' OWN keys (owner decisions 2026-10-28), for their Continue reading row only; settings.py accepts
        # them only in real mode with signed identity. The store re-reads the file when it changes; Home writes it
        # only when HOME_PROVISION_ACCOUNTS names komga (provision.py). No file: Continue is not offered.
        keys = None
        if settings.komga_member_keys_file:
            keys = MemberKeyStore(settings.komga_member_keys_file, writable="komga" in settings.provision_accounts,
                                  initial=settings.komga_member_keys,
                                  log=lambda **f: log_event(app_log, logging.INFO, "komga_member_keys", **f))
        komga_adapter = KomgaAdapter(
            komga_transport, timeout=settings.timeout, cache=cache,
            owner_confirms_no_member_restrictions=komga_confirmed, member_keys=keys,
            member_transport=(lambda key: UrllibTransport(settings.komga_base_url, {"X-API-Key": key})) if keys else None,
            provisioning="komga" in settings.provision_accounts)
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


def build_book_requests(settings: Settings) -> Optional[ShelfarrRequests]:
    """The Shelfarr request client, or None when HOME_BOOK_REQUESTS is off (settings.py validates the rest)."""
    if not (settings.home_sections and settings.book_requests and settings.shelfarr_base_url):
        return None
    transport = UrllibTransport(settings.shelfarr_base_url, {"Authorization": f"Bearer {settings.shelfarr_token}"})
    return ShelfarrRequests(transport, timeout=settings.timeout)


def build_watch_requests(settings: Settings) -> Optional[SeerrRequests]:
    """The Seerr request client, or None when HOME_WATCH_REQUESTS is off (settings.py validates the rest)."""
    if not (settings.home_sections and settings.watch_requests and settings.seerr_base_url):
        return None
    transport = UrllibTransport(settings.seerr_base_url, {"X-Api-Key": settings.seerr_api_key})
    return SeerrRequests(transport, timeout=settings.timeout)


def build_quick_connect(settings: Settings) -> Optional[QuickConnect]:
    """Embedded Quick Connect (quickconnect.py; owner decision 2026-10-27): built only where the real adapters are, with
    its own transport to the same Jellyfin address and key. Tests inject one, or get none (then /me/tv is the standard
    404 and a POST to it the standard 501)."""
    if not settings.home_sections:
        return None
    transport = UrllibTransport(settings.jellyfin_base_url,
                                {"Authorization": f'MediaBrowser Token="{settings.jellyfin_api_key}"'})
    return QuickConnect(transport, timeout=settings.timeout,
                        member_username=_member_username(settings, settings.jellyfin_member_username))


# "Sign in on a TV" (forms.py, quickconnect.py): the posted fields, and every result the page may be sent back with.
TV_FIELDS = frozenset({"code", "t"})
TV_RESULTS = QC_OUTCOMES + ("expired",)
# The request brokers' signed forms (bookrequests.py, watchrequests.py): exactly these fields, each once.
BOOK_FIELDS = frozenset({"work_id", "book_type", "title", "author", "q", "token"})
WATCH_FIELDS = frozenset({"media_type", "media_id", "title", "q", "token"})


def _is_loopback_peer(request: Request) -> bool:
    client = request.client
    return client is not None and client.host in ("127.0.0.1", "::1")


def create_app(settings: Settings, *, adapters: Optional[Sequence[MediaAdapter]] = None,
               quick_connect: Optional[QuickConnect] = None,
               book_requests: Optional[ShelfarrRequests] = None,
               watch_requests: Optional[SeerrRequests] = None,
               provisioner: Optional[Provisioner] = None) -> FastAPI:
    """`adapters`, `quick_connect`, `book_requests`, `watch_requests` and `provisioner` let tests inject fakes; otherwise
    they are built from `settings`. Each broker exists only when its switch is on (an injected client is ignored
    otherwise)."""
    silence_uvicorn_access()      # whoever serves this app, uvicorn must not log raw query strings
    cat = catalogue_mod.load(settings.catalogue_path)
    env = make_environment()
    env.globals["pwa_sw_off"] = not settings.pwa_sw          # kill switch: the script skips registration
    if settings.motion_proposal:
        env.globals["home_stylesheet"] = env.globals["home_stylesheet"] + Markup(MOTION_PROPOSAL_CSS)
    # The offline page and the worker are built once: static bytes, the same for every viewer (pwa.py).
    offline_html = env.get_template("offline.html").render(offline=True).encode("utf-8")
    worker_js = pwa_mod.worker_bytes(offline_html, enabled=settings.pwa_sw)
    # One disposable cache per process, default in-memory database, closed on shutdown. (Offboarding
    # hook for later: MemberCache.purge_member(principal); wired into nothing yet. A file-backed
    # cache is an owner decision, see HOME-APP.md, and has no setting.)
    cache = MemberCache(SystemClock())
    adapter_list = list(adapters) if adapters is not None else build_adapters(settings, cache)
    notices = notice_mod.NoticeBoard(settings.notice_file)          # AVR-365: read-only; None = no notices
    # Account creation (ACCOUNT-PROVISIONING.md): None unless HOME_PROVISION_ACCOUNTS names a library.
    if provisioner is None and adapters is None:
        komga_keys = next((a.member_keys for a in adapter_list if isinstance(a, KomgaAdapter)), None)
        provisioner = build_provisioner(
            settings, log=lambda **f: log_event(app_log, logging.INFO, "provision", **f), komga_keys=komga_keys)
    broker = None
    if settings.home_sections and settings.book_requests:
        broker = book_requests if book_requests is not None else build_book_requests(settings)
    seerr = None
    if settings.home_sections and settings.watch_requests:
        seerr = watch_requests if watch_requests is not None else build_watch_requests(settings)
    # Forms are signed with a key derived from the JWT client secret when Home has one (open forms survive a
    # restart), else a random per-process key. Guards, the search limiter, caches and outcomes are per process.
    signer, guard = FormSigner(form_key(settings.jwt_secret)), RequestGuard()
    limiter, flash = SearchLimiter(), Flash()
    book_cache = SearchCache(ttl=600.0)           # Shelfarr searched as Home's account: the same for every member
    watch_cache = SearchCache(ttl=120.0)          # Seerr searched AS a member: keyed by that member's Seerr id
    owned_index = OwnedIndex(settings.library_ids_file)             # read-only; None = no "Already in" claims
    # Account & Security: the fixed hand-off table (from the catalogue's account address and the owner-verified flows)
    # and the per-process key for the opaque return state. A bad catalogue address stops startup.
    security_config = security_mod.SecurityConfig.build(cat.account_url, settings.security_flows,
                                                        settings.security_return_origin)
    return_states = security_mod.ReturnStates()
    # "Sign in on a TV": only with the shell on. Injected adapters without an injected Quick Connect mean none.
    qc = quick_connect if quick_connect is not None else (build_quick_connect(settings) if adapters is None else None)
    if not (settings.home_sections and adapter_list):
        qc = None
    form_tokens = forms_mod.FormTokens()
    tv_replays = forms_mod.Replays(keep=frozenset({"approved"}))
    watch = cat.service("watch")
    # Jellyfin's own Quick Connect page (jellyfin-web 10.11 route `quickconnect`), from the catalogue's fixed host.
    tv_handoff = f"https://{watch.host}/web/#/quickconnect" if watch is not None else None


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
    app.state.notices = notices
    app.state.form_tokens = form_tokens            # tests mint a token without loading the page
    # Libraries whose search results link to a title page: those whose adapter offers the permission-checked
    # item lookup (`item`). The others' results link straight to the library.
    title_services = frozenset(a.service.value for a in adapter_list if "item" not in a.not_offered)

    def render(template: str, status: int = 200, **ctx) -> Response:
        body = env.get_template(template).render(**ctx)
        return Response(body, status_code=status, media_type=HTML)

    def respond(decision: Decision, scope=None, **extra) -> Response:
        """The one place a page is rendered. When it wears the shell (which prints the manifest link), the same call
        tells the middleware to allow `manifest-src`, `font-src`, `script-src` and `worker-src` ('self'): the tags and the CSP cannot disagree. A shell page
        must pass `scope`; forgetting it is an error, not a silently mismatched CSP."""
        if extra.get("shell") is not None:
            if scope is None:
                raise TypeError("a shell page must pass the request scope to respond()")
            mark_shell(scope, extra["shell"])
        if decision.plain is not None:
            return Response(decision.plain, status_code=decision.status,
                            media_type="text/plain; charset=utf-8")
        if decision.status in (303, 307):
            return Response(b"", status_code=decision.status, headers={"Location": decision.location},
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
                                                    request_hosts=request_hosts(viewer),
                                                    own_pages=own_pages(viewer)))
            scope["avrana_route"] = decision.label
            # Search's no-results group may offer Contribute (memo section 2), only from the member's own tiles.
            return respond(decision, scope, shell=shell_for(viewer, "search"),
                           contribute=place_link(tiles_for(viewer), CONTRIBUTE_PATH))

        if route == bookreq_mod.PATH and broker is not None:
            # Ask for a book (request broker): a shell page for a member holding Books or Audiobooks; anyone else gets
            # the standard 404, exactly as an unknown route. Shelfarr is searched as Home's service account; nothing
            # is asked for on a GET.
            formats = broker_formats(viewer)
            if not formats:
                scope["avrana_route"] = "not_found"
                return respond(not_found())
            username = broker_user(viewer)
            said, asked, back = flash.take(username, bookreq_mod.PATH) or (None, frozenset(), None)
            term = None if request.method == "HEAD" else (search_term_from_scope(scope) or back)   # HEAD never searches
            state, offers = ("form", ())
            if term is not None:
                state, offers = await cached_search(book_cache, ("books", clean_term(term)), username,
                                                    broker.search, term)
                log_event(app_log, logging.INFO, "book_search", service="shelfarr", state=state)
            owned, maybe = await already_have(viewer, offers, formats) if offers else ({}, {})
            page = bookreq_mod.build_results(state, offers, term, formats, username, signer, owned, maybe, asked)
            if said is not None:
                page = dataclasses.replace(page, notice=said)
            scope["avrana_route"] = bookreq_mod.PATH
            shell = shell_for(viewer, "search")
            mark_shell(scope, shell)
            return render("request_books.html", page=page, shell=shell)

        if route == watch_mod.PATH and seerr is not None:
            # Ask for a film or show (request broker, Seerr): a shell page for a member holding Movies and TV; anyone
            # else gets the standard 404. Searched AS the member's own Seerr user; nothing is asked for on a GET.
            if not watch_allowed(viewer):
                scope["avrana_route"] = "not_found"
                return respond(not_found())
            scope["avrana_route"] = watch_mod.PATH
            shell = shell_for(viewer, "search")
            mark_shell(scope, shell)
            username = broker_user(viewer)
            said, asked, back = flash.take(username, watch_mod.PATH) or (None, frozenset(), None)
            term = None if request.method == "HEAD" else (search_term_from_scope(scope) or back)   # HEAD never searches
            if term is None:
                page = watch_mod.build_results("form", (), None, "", signer)
                return render("request_watch.html", page=dataclasses.replace(page, notice=said), shell=shell)
            linked, seerr_id = await seerr_user(viewer)
            if linked != "ok":
                log_event(app_log, logging.INFO, "watch_search", service="seerr", state=linked)
                page = (watch_mod.not_linked(watch_place(viewer)) if linked == "not_linked" else
                        watch_mod.build_results("unavailable", (), term, "", signer))
                return render("request_watch.html", page=page, shell=shell)
            state, offers = await cached_search(watch_cache, (seerr_id, clean_term(term)), username,
                                                seerr.search, seerr_id, term)
            log_event(app_log, logging.INFO, "watch_search", service="seerr", state=state)
            owned = await watch_owned(viewer, offers) if offers else {}
            page = watch_mod.build_results(state, offers, term, username, signer, owned, asked)
            return render("request_watch.html", page=dataclasses.replace(page, notice=said), shell=shell)

        if route == "/library" and settings.home_sections and adapter_list:
            # The Library page (Concept K MK-5a, AVR-719): a shell page like /search, only with the shell on and for a
            # verified member; otherwise the standard 404, exactly as an unknown route (portal parity). It shows the
            # same sections Home gathers for this member; `?lib=` only chooses a chip among the member's own libraries.
            if viewer.principal is None:
                scope["avrana_route"] = "not_found"
                return respond(not_found())
            tiles = decide("/", viewer.groups, cat).context["tiles"]
            chip = library_chip_from_scope(scope)
            view = (await _gather(viewer, extras=library_extra_sections(chip)) if has_library(tiles)
                    else {"sections": []})
            page = build_library(view, tiles, chip=chip, limit=settings.section_limit,
                                 open_paths=place_paths(viewer), title_services=title_services,
                                 view_mode=library_view_from_scope(scope))
            decision = library_decision(page)
            scope["avrana_route"] = decision.label
            return respond(decision, scope, shell=shell_for(viewer, "library"))

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
            headers = {"Cache-Control": artwork_mod.CACHE_CONTROL, "ETag": artwork_mod.etag_for(result.data)}
            if artwork_mod.not_modified(if_none_match_from_scope(scope), headers["ETag"]):
                return Response(status_code=304, headers=headers)     # checked above like any fetch
            return Response(result.data, media_type=result.content_type, headers=headers)

        # Installable Home and the approved brand files (install.py, brand.py): only where the shell can render, so
        # with sections off these paths stay the portal's 404. Static bytes, the same for every viewer, so no
        # identity is needed to fetch them.
        shell_on = settings.home_sections and bool(adapter_list)
        if shell_on and route in (pwa_mod.SW_PATH, pwa_mod.OFFLINE_PATH, pwa_mod.SIGNOUT_PATH):
            # MK-3 (AVR-717): the worker, its offline page and the sign-out hop. Static, the same for every viewer.
            scope["avrana_route"] = route
            if route == pwa_mod.SW_PATH:
                return Response(worker_js, media_type=pwa_mod.JS_TYPE)       # no Service-Worker-Allowed: scope "/"
            if route == pwa_mod.OFFLINE_PATH:
                return Response(offline_html, media_type=HTML)
            # Clear this site's cache and storage on the device, then on to the outpost's own sign-out (fixed target).
            return Response(b"", status_code=303, media_type=HTML, headers=pwa_mod.signout_headers(cat.signout_url))
        script = pwa_mod.asset_for(route) if shell_on else None
        if script is not None:
            scope["avrana_route"] = "/static/{file}"
            return Response(script[0], media_type=script[1])
        asset = install_mod.asset_for(route) if shell_on else None
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
        if route.startswith(security_mod.PREFIX) and settings.home_sections and p is not None and adapter_list:
            # Me -> Account & Security (security.py). Shell only and a verified member only; any other path under the
            # prefix, or no member, is the standard 404 (parity). The hand-off is a 303 to a fixed Authentik address.
            if route == security_mod.JSON_ROUTE:
                scope["avrana_route"] = route
                return JSONResponse(security_config.summary())
            action = security_mod.action_from_route(route)
            if action is not None:
                scope["avrana_route"] = security_mod.GO_PREFIX + "{action}"
                log_event(app_log, logging.INFO, "security_handoff", reason=action,
                          state=security_config.via(action))
                return Response(b"", status_code=303, media_type=HTML, headers=security_mod.handoff_headers(
                    security_config, return_states, action, p.username))
            result = (return_states.check(security_state_from_scope(scope), p.username)
                      if route == security_mod.BACK_ROUTE else None)
            page = security_mod.build_page(route, security_config, groups=viewer.groups, username=p.username,
                                           signout_href=pwa_mod.SIGNOUT_PATH, result=result)
            if page is None:
                scope["avrana_route"] = "not_found"
                return respond(not_found())
            if result is not None:
                log_event(app_log, logging.INFO, "security_return", state=result.outcome,
                          reason="expired" if result.expired else (result.action or "none"))
            scope["avrana_route"] = route
            return respond(Decision(route, 200, "me_security.html", {"sec": page}), scope,
                           shell=shell_for(viewer, "me"))
        if route == forms_mod.TV_ROUTE and qc is not None and p is not None and tv_member(viewer):
            # "Sign in on a TV" (quickconnect.py). Only for members with TV and Movies; otherwise the standard 404.
            status = await run_in_threadpool(qc.status, p)
            result = tv_result_from_scope(scope)
            scope["avrana_route"] = route
            return respond(Decision(route, 200, "me_tv.html", {"tv": {
                "status": status, "result": result if result in TV_RESULTS else None,
                "token": form_tokens.issue("tv", p.username), "handoff": tv_handoff}}),
                scope, shell=shell_for(viewer, "me"))
        if route == ME_ROUTE and settings.home_sections and p is not None and adapter_list:
            # The Me hub (Concept K, AVR-719) exists only with the shell; otherwise the path stays unknown (parity).
            decision = me_decision(build_me(tiles_for(viewer), p.username, pwa_mod.SIGNOUT_PATH))
            scope["avrana_route"] = decision.label
            return respond(decision, scope, shell=shell_for(viewer, "me"), me_tv=qc is not None and tv_member(viewer))
        decision = decide(route, viewer.groups, cat, facts)
        scope["avrana_route"] = decision.label
        extra = {}
        if decision.label == "/" and settings.home_sections and p is not None and adapter_list:
            focus = home_filter_from_scope(scope)
            home = build_home(await _gather(viewer, extras=extra_sections_for(focus)), decision.context["tiles"],
                              new_tab=new_tab_from_scope(scope), limit=settings.section_limit,
                              member_name=(facts.name or facts.username), title_services=title_services,
                              focus=focus)
            extra["home"] = home
            shell = shell_for(viewer, "home", places=home.places)
            extra["shell"] = dataclasses.replace(shell, filters=home.filters) if shell is not None else None
        elif decision.status == 200 and decision.label in SHELL_PAGES:
            extra["shell"] = shell_for(viewer, SHELL_PAGES[decision.label])
            if decision.label == "/{chooser}" and extra["shell"] is not None:
                extra["intro"] = chooser_intro(decision.context["chooser"].path)
                if decision.context["chooser"].path == "request":
                    # "Add to the library" (frame 17:619): only when the member's own tiles hold Contribute.
                    extra["contribute"] = place_link(tiles_for(viewer), CONTRIBUTE_PATH)
                    # A request service whose broker is on (and that this member may use) opens Home's own ask page.
                    extra["own_pages"] = own_pages(viewer)
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

    @app.post(bookreq_mod.PATH, include_in_schema=False, response_model=None)
    async def ask_for_book(request: Request, viewer: Viewer = Depends(get_viewer)) -> Response:
        """One request for one format of one book, as the verified member. Only reachable when the broker is on (the
        middleware answers 501 to every other POST). Who asks is the principal, never a form field; the fields must
        be the ones this process signed for this member, unexpired."""
        scope = request.scope
        formats = broker_formats(viewer) if broker is not None else ()
        if not formats:
            scope["avrana_route"] = "not_found"
            return respond(not_found())
        scope["avrana_route"] = bookreq_mod.PATH
        shell = shell_for(viewer, "search")
        mark_shell(scope, shell)
        username = broker_user(viewer)
        fields = (await forms_mod.read_form(request, BOOK_FIELDS, MAX_FORM_BODY, exact=True)
                  if same_origin_form_post(scope) else None)
        token = fields.pop("token") if fields is not None else None
        back = clean_term(fields.pop("q")) if fields is not None else None     # navigation only, never signed
        if (fields is None or username is None or fields.get("book_type") not in formats
                or not signer.verify(token, username, fields)):
            log_event(app_log, logging.INFO, "book_request", service="shelfarr", state="refused_form")
            page = bookreq_mod.build_said(None, "expired", {}, None, formats)
            return render("request_books.html", 403, page=page, shell=shell)
        blocked = guard.check(username, fields["work_id"] + "|" + fields["book_type"])
        if blocked == "rate":
            log_event(app_log, logging.INFO, "book_request", service="shelfarr", state=blocked)
            return render("request_books.html", 429, page=bookreq_mod.build_said(None, blocked, fields, None, formats),
                          shell=shell)
        if blocked is not None:                    # a double tap: say so on the page it came from, send nothing
            log_event(app_log, logging.INFO, "book_request", service="shelfarr", state=blocked)
            return see_other(username, bookreq_mod.PATH, bookreq_mod.build_said(None, blocked, fields, None, formats),
                             frozenset({(fields["work_id"], fields["book_type"])}), back)
        outcome = await run_in_threadpool(broker.create, username, fields["work_id"], fields["book_type"],
                                          fields["title"], fields["author"])
        log_event(app_log, logging.INFO, "book_request", service="shelfarr", state=outcome.value,
                  reason=fields["book_type"])
        place = "/requestabook" if cat.service("requestabook") is not None and \
            cat.service("requestabook").allows(viewer.groups) else None
        ok = outcome in (bookreq_mod.Outcome.CREATED, bookreq_mod.Outcome.QUEUED)
        return see_other(username, bookreq_mod.PATH, bookreq_mod.build_said(outcome, None, fields, place, formats),
                         frozenset({(fields["work_id"], fields["book_type"])}) if ok else frozenset(), back)

    @app.post(watch_mod.PATH, include_in_schema=False, response_model=None)
    async def ask_for_watch(request: Request, viewer: Viewer = Depends(get_viewer)) -> Response:
        """One request for one film or show, as the verified member's own Seerr user (never an administrator). The
        same gates as books: switch, group, same origin, exact fields, a token this process signed for this member,
        the guard."""
        scope = request.scope
        if seerr is None or not watch_allowed(viewer):
            scope["avrana_route"] = "not_found"
            return respond(not_found())
        scope["avrana_route"] = watch_mod.PATH
        shell = shell_for(viewer, "search")
        mark_shell(scope, shell)
        username = broker_user(viewer)
        fields = (await forms_mod.read_form(request, WATCH_FIELDS, MAX_FORM_BODY, exact=True)
                  if same_origin_form_post(scope) else None)
        token = fields.pop("token") if fields is not None else None
        back = clean_term(fields.pop("q")) if fields is not None else None     # navigation only, never signed
        if (fields is None or username is None or not signer.verify(token, username, fields)
                or fields["media_type"] not in ("movie", "tv") or not fields["media_id"].isdigit()):
            log_event(app_log, logging.INFO, "watch_request", service="seerr", state="refused_form")
            return render("request_watch.html", 403, page=watch_mod.build_said(None, "expired", {}, None), shell=shell)
        blocked = guard.check(username, "watch|" + fields["media_type"] + "|" + fields["media_id"])
        key = (fields["media_type"], int(fields["media_id"]))
        if blocked == "rate":
            log_event(app_log, logging.INFO, "watch_request", service="seerr", state=blocked)
            return render("request_watch.html", 429, page=watch_mod.build_said(None, blocked, fields, None), shell=shell)
        if blocked is not None:
            log_event(app_log, logging.INFO, "watch_request", service="seerr", state=blocked)
            return see_other(username, watch_mod.PATH, watch_mod.build_said(None, blocked, fields, None),
                             frozenset({key}), back)
        linked, seerr_id = await seerr_user(viewer)
        if linked != "ok":
            outcome = watch_mod.Outcome.NOT_LINKED if linked == "not_linked" else watch_mod.Outcome.UNAVAILABLE
        else:
            outcome = await run_in_threadpool(seerr.create, seerr_id, fields["media_type"], int(fields["media_id"]))
        log_event(app_log, logging.INFO, "watch_request", service="seerr", state=outcome.value,
                  reason=fields["media_type"])
        ok = outcome in (watch_mod.Outcome.CREATED, watch_mod.Outcome.AWAITING, watch_mod.Outcome.DUPLICATE)
        if ok and seerr_id is not None:
            watch_cache.drop((seerr_id, back))     # the next view of that search shows Seerr's new state
        return see_other(username, watch_mod.PATH, watch_mod.build_said(outcome, None, fields, watch_place(viewer)),
                         frozenset({key}) if ok else frozenset(), back)

    def see_other(username: str, path: str, said, asked: frozenset, term: Optional[str]) -> Response:
        """Post-redirect-get: the outcome, the titles just asked for and the search the form came from go into the
        member's one-shot flash, and a 303 goes to the ask page's own fixed path (nothing from the request is ever
        in a Location). The next GET shows the outcome over the same results; a reload never re-sends the form."""
        flash.put(username, path, (said, asked, term))
        return respond(Decision(path, 303, location=path))

    async def cached_search(cache, key, username, search, *args):
        """A cached answer, or one upstream search counted against the member's search allowance ("limited" once it
        is spent). Only "ok" and "empty" are cached; a key whose term is unusable is never cached."""
        hit = cache.get(key) if key[1] is not None else None
        if hit is not None:
            return hit
        if username is None or not limiter.allow(username):
            return "limited", ()
        state, offers = await run_in_threadpool(search, *args)
        if key[1] is not None and state in ("ok", "empty"):
            cache.put(key, (state, offers))
        return state, offers

    def watch_allowed(viewer: Viewer) -> bool:
        return (seerr is not None and viewer.principal is not None and bool(adapter_list)
                and REQUIRED_GROUP[Service.JELLYFIN] in viewer.groups)

    def watch_place(viewer: Viewer) -> Optional[str]:
        svc = cat.service(watch_mod.PLACE.strip("/"))
        return watch_mod.PLACE if svc is not None and svc.allows(viewer.groups) else None

    async def seerr_user(viewer: Viewer):
        """("ok", seerr id) | ("not_linked", None) | ("unavailable", None): the member's Seerr user, found through the
        Jellyfin user Home already maps them to. No Jellyfin adapter, or an unmapped member: not linked."""
        jellyfin = next((a for a in adapter_list if a.service is Service.JELLYFIN), None)
        if jellyfin is None:
            return "not_linked", None
        user = await run_in_threadpool(jellyfin.resolve_user, viewer.principal)
        if user is None:
            return "not_linked", None
        return await run_in_threadpool(seerr.user_for, user.upstream_id)

    async def watch_owned(viewer: Viewer, offers) -> dict:
        """{(media_type, tmdb_id): OwnedVM} for titles Seerr says are in the library AND this member's own
        permission-checked Jellyfin lookup finds (at most OWNED_CHECKS); the link is Home's own title page."""
        out, checks = {}, 0
        jellyfin = next((a for a in adapter_list if a.service is Service.JELLYFIN), None)
        for offer in offers:
            if (jellyfin is None or offer.jellyfin_id is None or checks >= bookreq_mod.OWNED_CHECKS
                    or offer.state not in (MediaState.AVAILABLE, MediaState.PARTIAL)):
                continue
            checks += 1
            section = await run_in_threadpool(jellyfin.item, viewer.principal, offer.jellyfin_id, True)
            if section.state.value == "ok" and section.items:
                out[(offer.media_type, offer.tmdb_id)] = bookreq_mod.OwnedVM(
                    watch_mod.LIBRARY, title_href(Service.JELLYFIN.value, offer.jellyfin_id), False)
        return out

    def own_pages(viewer: Viewer) -> dict:
        """Request path -> Home ask page, for each broker that is on and that this member may use (search fallback)."""
        out = {}
        if broker_formats(viewer):
            out["requestabook"] = bookreq_mod.PATH
        if watch_allowed(viewer):
            out["requests"] = watch_mod.PATH
        return out

    async def already_have(viewer: Viewer, offers, formats):
        """({(work_id, format): OwnedVM}, {(work_id, format): MaybeVM}) for this member, from the catalogue-id index.
        Only the member's own formats are looked at (a library they do not hold is never mentioned). Books is a
        shared view, so holding the group is the permission; Audiobooks is per member, so an exact hit is shown only
        after the adapter's own permission-checked lookup finds the item for this member (at most OWNED_CHECKS).
        A likely match (title and author only) is a hint linking to Home's own search, never a claim."""
        owned, maybe, checks = {}, {}, 0
        by_service = {a.service: a for a in adapter_list}
        for offer in offers:
            for fmt in formats:
                upstream = owned_index.exact(fmt, offer.keys)
                if upstream is not None and fmt == "ebook":
                    owned[(offer.work_id, fmt)] = bookreq_mod.OwnedVM(
                        bookreq_mod.LIBRARY_LABEL[fmt], build_handoff_url(Service.CALIBRE_WEB, upstream), True)
                    continue
                adapter = by_service.get(Service.AUDIOBOOKSHELF)
                if upstream is not None and adapter is not None and checks < bookreq_mod.OWNED_CHECKS:
                    checks += 1
                    section = await run_in_threadpool(adapter.item, viewer.principal, upstream, True)
                    if section.state.value == "ok" and section.items:
                        owned[(offer.work_id, fmt)] = bookreq_mod.OwnedVM(
                            bookreq_mod.LIBRARY_LABEL[fmt], title_href(Service.AUDIOBOOKSHELF.value, upstream), False)
                        continue
                if owned_index.likely(fmt, offer.title_key) is not None:
                    maybe[(offer.work_id, fmt)] = bookreq_mod.MaybeVM(
                        bookreq_mod.LIBRARY_LABEL[fmt], "/search?" + urlencode({"q": offer.title[:100]}))
        return owned, maybe

    def broker_formats(viewer: Viewer) -> tuple:
        """The formats this member may ask for through the broker; () when the broker is off or nobody verified."""
        if broker is None or viewer.principal is None or not adapter_list:
            return ()
        return bookreq_mod.formats_for(viewer.groups)

    def broker_user(viewer: Viewer) -> Optional[str]:
        return member_username(viewer.principal.username) if viewer.principal is not None else None

    def mark_shell(scope, shell) -> None:
        """Tell the middleware this response is a shell page: only these pages link the manifest and load the brand
        font and the page script (base.html), so only these get `SHELL_SOURCES` in their CSP (middleware.py). Every other
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

    def place_paths(viewer: Viewer) -> dict:
        """service -> the member's own place route for that library ("/watch"), only where this member's groups open
        it in the catalogue (the same check as the route itself), for Library's "Open <app>" links. Static catalogue
        data only; nothing from the request."""
        out = {}
        for service, path in LIBRARY_PLACE.items():
            svc = cat.service(path)
            if svc is not None and svc.allows(viewer.groups):
                out[service] = "/" + path
        return out
    def tiles_for(viewer: Viewer):
        """The member's own catalogue tiles (group-filtered, static data; no upstream call)."""
        return decide("/", viewer.groups, cat).context["tiles"]

    def shell_for(viewer: Viewer, current: str, places=None):
        """The shell data (places, tabs, the member's name) for a shell page, or None where the shell is
        not on (sections off: the pages stay byte-identical to the portal). No upstream call is made here."""
        p = viewer.principal
        if not (settings.home_sections and p is not None and adapter_list):
            return None
        shell = build_shell(tiles_for(viewer), current, (p.name or "").strip() or p.username, places=places)
        # The operator notice (AVR-365): fixed words from notice.py, a library notice only for members who open it.
        seen = notice_mod.visible_notice(notices.current(), place_paths(viewer))
        return dataclasses.replace(shell, notice=seen) if seen is not None else shell

    async def _gather(viewer: Viewer, extras: tuple = ()) -> dict:
        """The sections for the verified member, via the adapters' own principal checks and
        bounded timeouts. One failing adapter costs its own section only. `extras` (Up next for Watch, the shelves for
        Listen and the Audiobooks chip, New releases for Comics and Read) are (library, section) pairs, asked of those
        libraries only, AFTER the others: a member holds at most two upstream calls per library at once
        (contract.DEFAULT_MAX_IN_FLIGHT_PER_MEMBER), so a third alongside them would only be refused as busy."""
        result = await run_in_threadpool(gather, viewer.principal, adapter_list, ("continue", "recent"),
                                        settings.section_limit)
        if provisioner is not None and provisioner.candidates(result.sections):
            # A library said "no account with this name": create it once, forget the cached "absent" mapping and
            # read the page again, so the member's first visit already shows that library.
            created = await run_in_threadpool(provisioner.provision, viewer.principal, result.sections)
            if created:
                for a in adapter_list:
                    if a.service in created:
                        a.cache.for_member(viewer.principal).delete(a.service.value, "mapping")
                result = await run_in_threadpool(gather, viewer.principal, adapter_list, ("continue", "recent"),
                                                settings.section_limit)
        sections = list(result.sections)
        view = result.member_view()
        if extras:
            wanted = {service for service, _section in extras}
            more = await run_in_threadpool(gather, viewer.principal,
                                           [a for a in adapter_list if a.service.value in wanted],
                                           tuple(dict.fromkeys(section for _service, section in extras)),
                                           settings.section_limit)
            sections += more.sections
            view["sections"] += more.member_view()["sections"]
        for s in sections:
            log_event(app_log, logging.INFO, "section", service=s.service.value,
                      section=s.section, state=s.state.value, reason=s.reason or "")
        return view

    def tv_member(viewer: Viewer) -> bool:
        return REQUIRED_GROUP[Service.JELLYFIN] in viewer.groups

    if qc is not None:
        @app.post(forms_mod.TV_ROUTE, include_in_schema=False, response_model=None)
        async def tv_approve(request: Request, viewer: Viewer = Depends(get_viewer)) -> Response:
            """Approve a TV's Quick Connect code as this member (quickconnect.py has the guardrails). Every lock in
            forms.py first; the answer is always a 303 back to the page with a fixed result id (post/redirect/get)."""
            scope = request.scope
            p = viewer.principal
            if p is None or not tv_member(viewer):
                # The same 501 as a POST to any other path (middleware.py): nobody without TV and Movies can tell
                # from outside that this path takes a form.
                scope["avrana_route"] = "method_not_supported"
                return Response(NOT_IMPLEMENTED_BODY, status_code=501, media_type="text/html; charset=utf-8")
            scope["avrana_route"] = forms_mod.TV_ROUTE
            if not same_origin_form_post(scope):
                return render("error.html", 403)
            form = await forms_mod.read_form(request, TV_FIELDS)
            if form is None:
                return render("error.html", 400)
            token, code = form.get("t"), form.get("code", "")
            if form_tokens.check(token, "tv", p.username):
                # A double-click or a resent page shares the first post's answer: one approval per form (forms.Replays).
                outcome = await tv_replays.once((p.username, token, code),
                                                lambda: run_in_threadpool(qc.approve, p, code))
            else:
                outcome = "expired"
            log_event(app_log, logging.INFO, "quick_connect", state=outcome)       # never the code or the member
            return Response(b"", status_code=303, media_type=HTML,
                            headers=forms_mod.result_headers(outcome, TV_RESULTS))

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
                       .render().encode("utf-8"),
                       post_paths=frozenset(path for path, on in ((forms_mod.TV_ROUTE, qc is not None),
                                                                   (bookreq_mod.PATH, broker is not None),
                                                                   (watch_mod.PATH, seerr is not None)) if on))
    log_event(app_log, logging.INFO, "app_created")
    return app
