"""Liveness/readiness + a dashboard status summary. `/healthz` is unauthenticated (for
container/proxy checks) and reveals nothing sensitive. `/readyz` also checks the companion is
reachable. `/status/summary` exposes aggregate counts for the Homepage widget."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db import connect

router = APIRouter()


@router.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    companion = request.app.state.companion
    try:
        await companion.health()
        companion_ok = True
    except Exception:
        companion_ok = False
    code = 200 if companion_ok else 503
    return JSONResponse({"status": "ok" if companion_ok else "degraded", "companion": companion_ok}, status_code=code)


@router.get("/status/summary")
async def status_summary(request: Request) -> JSONResponse:
    """Aggregate operational counts for the Homepage dashboard. Deliberately unauthenticated
    like /healthz and deliberately NON-SENSITIVE: only integer counts, never a title, ASIN,
    email, or which account owns what. It answers two questions at a glance: how many books
    are still on their way in, and how many Audible accounts are currently connected."""
    conn = connect(request.app.state.settings.db_path)
    try:
        # Connected accounts (a 'disconnected' once-mode connection is not counted).
        profiles = conn.execute(
            "SELECT COUNT(*) c FROM connection WHERE state='connected'"
        ).fetchone()["c"]
        # Book pipeline, by lifecycle stage.
        rows = conn.execute("SELECT status, COUNT(*) c FROM book GROUP BY status").fetchall()
        by = {r["status"]: r["c"] for r in rows}
    finally:
        conn.close()

    downloading = by.get("importing", 0)                    # actively downloading now
    queued = by.get("selected", 0) + by.get("queued", 0)    # accepted, waiting to start
    pending = queued + downloading                          # "still need to download"
    imported = by.get("imported", 0)
    failed = by.get("failed", 0)

    if pending:
        state = "importing" if downloading else "queued"
    elif failed:
        state = "attention"
    else:
        state = "idle"

    return JSONResponse({
        "profiles": profiles,
        "pending": pending,
        "downloading": downloading,
        "imported": imported,
        "failed": failed,
        "state": state,
    })
