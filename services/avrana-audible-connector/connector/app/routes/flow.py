"""The consumer onboarding flow. Every route is authenticated (Authentik group gate via
`get_identity`), every state change is CSRF-checked, and every data access is scoped to the
caller's Authentik subject so no user can see or touch another user's catalog."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import audit, catalog, jobs, sync
from ..companion_client import CompanionError
from ..db import connect
from ..identity import Identity, get_identity
from ..repo import (
    auth_session_expired,
    create_auth_session,
    create_connection,
    delete_auth_session,
    delete_connection_cascade,
    get_auth_session_owned,
    get_connection_for_sub,
    get_connection_owned,
    set_connection_state,
    set_sync_mode,
)
from ..security import require_csrf, valid_asin

router = APIRouter()

MARKETPLACES = [
    ("us", "United States"), ("uk", "United Kingdom"), ("canada", "Canada"),
    ("australia", "Australia"), ("germany", "Germany"), ("france", "France"),
    ("italy", "Italy"), ("spain", "Spain"), ("japan", "Japan"), ("india", "India"),
]
VALID_LOCALES = {code for code, _ in MARKETPLACES}


def _db(request: Request):
    return connect(request.app.state.settings.db_path)


def _render(request: Request, template: str, ident: Identity, **ctx) -> HTMLResponse:
    csrf = request.app.state.csrf.issue(ident.sub)
    context = {"csrf_token": csrf, "ident": ident, **ctx}
    return request.app.state.templates.TemplateResponse(request, template, context)


@router.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse("/contribute/audible", status_code=status.HTTP_302_FOUND)


@router.get("/contribute/audible", response_class=HTMLResponse)
async def connect_page(request: Request, ident: Identity = Depends(get_identity)):
    conn = _db(request)
    try:
        existing = get_connection_for_sub(conn, ident.sub)
    finally:
        conn.close()
    if existing and existing["state"] == "connected":
        return RedirectResponse("/contribute/audible/library", status_code=302)
    return _render(request, "connect.html", ident, marketplaces=MARKETPLACES)


@router.post("/contribute/audible/start", response_class=HTMLResponse)
async def start_connect(
    request: Request,
    ident: Identity = Depends(get_identity),
    email: str = Form(...),
    marketplace: str = Form(...),
):
    request.app.state.rate.check("auth_start", ident.sub)
    await require_csrf(request, ident.sub)
    email = email.strip().lower()
    if "@" not in email or len(email) > 254:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a valid email address")
    if marketplace not in VALID_LOCALES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a valid marketplace")

    conn = _db(request)
    try:
        # Reuse or create the user's connection (one active per subject).
        existing = get_connection_for_sub(conn, ident.sub)
        if existing and existing["state"] not in ("disconnected",):
            connection = existing
        else:
            connection = create_connection(conn, ident.sub, email, marketplace)
        audit.record(conn, audit.CONNECTION_STARTED, sub=ident.sub,
                     connection_id=connection["id"], detail=marketplace)
        try:
            resp = await request.app.state.companion.auth_start(
                connection["profile_id"], email, marketplace
            )
        except CompanionError as exc:
            set_connection_state(conn, connection["id"], "error", exc.user_message)
            return _render(request, "connect.html", ident, marketplaces=MARKETPLACES,
                           error=exc.user_message)
        login_url = resp.get("loginUrl", "")
        companion_session = resp.get("sessionId", "")
        sid = create_auth_session(
            conn, ident.sub, connection["id"], companion_session,
            request.app.state.settings.session_ttl_seconds,
        )
    finally:
        conn.close()
    # login_url is an Amazon-hosted URL; it is shown to the user but is not a secret and
    # contains no Avrana/Amazon credentials.
    return _render(request, "paste_redirect.html", ident, login_url=login_url, session_id=sid,
                   email=email)


@router.post("/contribute/audible/complete", response_class=HTMLResponse)
async def complete_connect(
    request: Request,
    ident: Identity = Depends(get_identity),
    session_id: str = Form(...),
    response_url: str = Form(...),
):
    request.app.state.rate.check("auth_complete", ident.sub)
    await require_csrf(request, ident.sub)
    # response_url is the pasted final redirect. It is forwarded to the companion and then
    # discarded. It is NEVER written to the DB, logs, or audit trail.
    if not response_url or not response_url.lower().startswith("http"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Paste the full redirect URL")

    conn = _db(request)
    try:
        sess = get_auth_session_owned(conn, session_id, ident.sub)
        if sess is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
        if auth_session_expired(sess):
            delete_auth_session(conn, session_id)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This login link expired. Start again.")
        connection = get_connection_owned(conn, sess["connection_id"], ident.sub)
        if connection is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
        try:
            await request.app.state.companion.auth_complete(
                connection["profile_id"], sess["companion_session"], response_url
            )
        except CompanionError as exc:
            # The handshake is single-shot: the companion's login process has already exited
            # and this session is now consumed (deleted just below). Re-offering the paste
            # page would bind the form to a dead session, so the user's natural retry would
            # fail with a baffling "Session not found". Send them back to a clean start, which
            # spawns a fresh login process against the same account.
            set_connection_state(conn, connection["id"], "error", exc.user_message)
            return _render(request, "connect.html", ident, marketplaces=MARKETPLACES,
                           prefill_email=connection["audible_email"],
                           error=f"{exc.user_message} Please start again.")
        finally:
            # Consume the one-time session regardless of outcome.
            delete_auth_session(conn, session_id)
            del response_url  # drop the reference promptly

        set_connection_state(conn, connection["id"], "connected")
        audit.record(conn, audit.CONNECTION_COMPLETED, sub=ident.sub, connection_id=connection["id"])
        # Kick off the first metadata-only scan.
        try:
            await sync.run_scan(conn, request.app.state.companion, connection, ident.sub)
        except CompanionError:
            pass  # library page will offer a re-scan
    finally:
        conn.close()
    return RedirectResponse("/contribute/audible/library", status_code=302)


@router.get("/contribute/audible/library", response_class=HTMLResponse)
async def library_page(request: Request, ident: Identity = Depends(get_identity)):
    conn = _db(request)
    try:
        connection = get_connection_for_sub(conn, ident.sub)
        if connection is None or connection["state"] != "connected":
            return RedirectResponse("/contribute/audible", status_code=302)
        from ..repo import books_for_connection

        books = books_for_connection(conn, connection["id"])
    finally:
        conn.close()
    counts = _counts(books)
    return _render(request, "library.html", ident, connection=connection, books=books, counts=counts)


@router.post("/contribute/audible/scan", response_class=HTMLResponse)
async def rescan(request: Request, ident: Identity = Depends(get_identity)):
    await require_csrf(request, ident.sub)
    conn = _db(request)
    try:
        connection = get_connection_for_sub(conn, ident.sub)
        if connection is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No connection")
        try:
            await sync.run_scan(conn, request.app.state.companion, connection, ident.sub)
        except CompanionError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.user_message)
    finally:
        conn.close()
    return RedirectResponse("/contribute/audible/library", status_code=302)


@router.post("/contribute/audible/select", response_class=HTMLResponse)
async def select(
    request: Request,
    ident: Identity = Depends(get_identity),
):
    await require_csrf(request, ident.sub)
    form = await request.form()
    select_all = form.get("select_all") == "1"
    asins = [a for a in form.getlist("asin") if valid_asin(a)]
    conn = _db(request)
    try:
        connection = get_connection_for_sub(conn, ident.sub)
        if connection is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No connection")
        if select_all:
            chosen = catalog.select_all_new(conn, connection["id"])
        else:
            chosen = catalog.select_books(conn, connection["id"], asins)
        already = conn.execute(
            "SELECT COUNT(*) c FROM book WHERE connection_id=? AND status='selected'", (connection["id"],)
        ).fetchone()["c"]
        if not chosen and not already:
            # An empty selection goes no further: in one-time mode it could otherwise end the import
            # before anything was chosen.
            from ..repo import books_for_connection

            books = books_for_connection(conn, connection["id"])
            return _render(request, "library.html", ident, connection=connection, books=books,
                           counts=_counts(books), error="Choose at least one book to import.")
    finally:
        conn.close()
    return RedirectResponse("/contribute/audible/mode", status_code=302)


@router.get("/contribute/audible/mode", response_class=HTMLResponse)
async def mode_page(request: Request, ident: Identity = Depends(get_identity)):
    conn = _db(request)
    try:
        connection = get_connection_for_sub(conn, ident.sub)
        if connection is None or connection["state"] != "connected":
            return RedirectResponse("/contribute/audible", status_code=302)
        selected = conn.execute(
            "SELECT COUNT(*) c FROM book WHERE connection_id=? AND status='selected'",
            (connection["id"],),
        ).fetchone()["c"]
    finally:
        conn.close()
    return _render(request, "mode.html", ident, connection=connection, selected=selected)


@router.post("/contribute/audible/mode", response_class=HTMLResponse)
async def set_mode(
    request: Request,
    ident: Identity = Depends(get_identity),
    mode: str = Form(...),
):
    await require_csrf(request, ident.sub)
    if mode not in ("once", "ask", "auto"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a valid option")
    conn = _db(request)
    try:
        connection = get_connection_for_sub(conn, ident.sub)
        if connection is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No connection")
        cid = connection["id"]
        if mode == "once":
            chosen = conn.execute(
                "SELECT COUNT(*) c FROM book WHERE connection_id=? "
                "AND status IN ('selected','queued','importing')",
                (cid,),
            ).fetchone()["c"]
            if not chosen:
                return _render(request, "mode.html", ident, connection=connection, selected=0,
                               error="Choose at least one book before importing once.")
        set_sync_mode(conn, cid, mode)
        audit.record(conn, audit.SYNC_MODE_CHANGED, sub=ident.sub, connection_id=cid, detail=mode)
        # Queue everything currently selected (idempotent).
        selected = conn.execute(
            "SELECT asin FROM book WHERE connection_id=? AND status='selected'", (cid,)
        ).fetchall()
        for row in selected:
            try:
                jobs.queue_book(conn, cid, ident.sub, row["asin"])
            except ValueError:
                continue
        await jobs.dispatch_queued(conn, request.app.state.companion, connection["profile_id"], cid)
    finally:
        conn.close()
    return RedirectResponse("/contribute/audible/progress", status_code=302)


def _progress_rows(conn, cid):
    return conn.execute(
            "SELECT b.asin, b.title, b.status AS book_status, j.status AS job_status, j.failure "
            "FROM book b LEFT JOIN job j ON j.connection_id=b.connection_id AND j.asin=b.asin "
            "AND j.id=(SELECT id FROM job WHERE connection_id=b.connection_id AND asin=b.asin "
            "ORDER BY created_at DESC LIMIT 1) "
            "WHERE b.connection_id=? AND b.status IN "
            "('selected','queued','importing','imported','failed') ORDER BY b.title",
            (cid,),
        ).fetchall()


@router.get("/contribute/audible/progress", response_class=HTMLResponse)
async def progress_page(request: Request, ident: Identity = Depends(get_identity)):
    """Read only (owner decision, 2026-10-15): loading this page never polls, dispatches, finalises
    or revokes. The scheduler advances imports in the background; Refresh is the POST below."""
    conn = _db(request)
    try:
        connection = get_connection_for_sub(conn, ident.sub)
        if connection is None:
            return RedirectResponse("/contribute/audible", status_code=302)
        rows = _progress_rows(conn, connection["id"])
    finally:
        conn.close()
    return _render(request, "progress.html", ident, connection=connection, rows=rows, revoked=False)


@router.post("/contribute/audible/progress/refresh", response_class=HTMLResponse)
async def progress_refresh(request: Request, ident: Identity = Depends(get_identity)):
    """Check now: poll and dispatch this member's imports and, in one-time mode, finish the import
    (revoke the Audible authorization) once every chosen book is in. CSRF-protected, idempotent."""
    await require_csrf(request, ident.sub)
    conn = _db(request)
    try:
        connection = get_connection_for_sub(conn, ident.sub)
        if connection is None:
            return RedirectResponse("/contribute/audible", status_code=303)
        cid = connection["id"]
        await jobs.dispatch_queued(conn, request.app.state.companion, connection["profile_id"], cid)
        await jobs.poll_jobs(conn, request.app.state.companion, connection["profile_id"], cid, ident.sub)
        connection = get_connection_for_sub(conn, ident.sub)
        revoked = False
        if connection is not None:
            revoked = await sync.finalize_once_mode(conn, request.app.state.companion, connection, ident.sub)
        if not revoked:
            return RedirectResponse("/contribute/audible/progress", status_code=303)
        # The connection is gone after revoking, so the result is said here, once.
        rows = _progress_rows(conn, cid)
    finally:
        conn.close()
    return _render(request, "progress.html", ident, connection=None, rows=rows, revoked=True)


@router.post("/contribute/audible/retry", response_class=HTMLResponse)
async def retry(request: Request, ident: Identity = Depends(get_identity), asin: str = Form(...)):
    await require_csrf(request, ident.sub)
    if not valid_asin(asin):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid book id")
    conn = _db(request)
    try:
        connection = get_connection_for_sub(conn, ident.sub)
        if connection is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No connection")
        jobs.retry_failed(conn, connection["id"], asin)
        await jobs.dispatch_queued(conn, request.app.state.companion, connection["profile_id"], connection["id"])
    finally:
        conn.close()
    return RedirectResponse("/contribute/audible/progress", status_code=302)


# Where Cancel on the confirmation page goes back to. Only these two pages offer Disconnect; anything
# else in `from` falls back to the progress page, so the parameter can never point off the connector.
_DISCONNECT_RETURN = {"mode": "/contribute/audible/mode", "progress": "/contribute/audible/progress"}


@router.get("/contribute/audible/disconnect", response_class=HTMLResponse)
async def disconnect_confirm(request: Request, ident: Identity = Depends(get_identity)):
    """The JS-free confirmation (owner decision, 2026-10-15). Read only: it shows what disconnecting
    does and offers the CSRF-protected POST below. Loading it never revokes, deletes or records."""
    conn = _db(request)
    try:
        connection = get_connection_for_sub(conn, ident.sub)
    finally:
        conn.close()
    if connection is None:
        return RedirectResponse("/contribute/audible", status_code=302)
    back = _DISCONNECT_RETURN.get(request.query_params.get("from", ""), _DISCONNECT_RETURN["progress"])
    return _render(request, "disconnect_confirm.html", ident, cancel_href=back)


@router.post("/contribute/audible/disconnect", response_class=HTMLResponse)
async def disconnect(request: Request, ident: Identity = Depends(get_identity)):
    await require_csrf(request, ident.sub)
    conn = _db(request)
    try:
        connection = get_connection_for_sub(conn, ident.sub)
        if connection is None:
            return RedirectResponse("/contribute/audible", status_code=302)
        revoked = True
        try:
            await request.app.state.companion.revoke(connection["profile_id"])
        except CompanionError:
            revoked = False  # best-effort; we still forget it locally, and the page says so
        audit.record(conn, audit.ACCOUNT_DISCONNECTED, sub=ident.sub,
                     connection_id=connection["id"],
                     detail="user disconnect" if revoked else "user disconnect; companion revoke failed")
        delete_connection_cascade(conn, connection["id"])
    finally:
        conn.close()
    return _render(request, "disconnected.html", ident, revoked=revoked)


def _counts(books) -> dict:
    c = {"purchased": 0, "already": 0, "plus": 0, "imported": 0, "selected": 0, "review": 0, "pending": 0}
    for b in books:
        if b["eligibility"] == "purchased":
            c["purchased"] += 1
        if b["eligibility"] == "plus":
            c["plus"] += 1
        if b["status"] in c:
            c[b["status"]] += 1
    return c
