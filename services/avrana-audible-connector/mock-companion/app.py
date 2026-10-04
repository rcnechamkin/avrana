"""Mock Libation companion: implements the connector's companion contract with fake data.

Used by the test suite and for credential-free UI walkthroughs. It is deliberately NOT a
real Audible client: no Amazon calls, no downloads. It keeps per-profile state in memory so
isolation behaviour can be exercised end to end.

Bearer token is read from COMPANION_TOKEN_FILE (same contract as the real companion).
"""
from __future__ import annotations

import os
import time
import uuid

from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_TOKEN = ""
_tf = os.environ.get("COMPANION_TOKEN_FILE")
if _tf and os.path.isfile(_tf):
    _TOKEN = open(_tf, encoding="utf-8").read().strip()

# profile_id -> {"authed": bool, "library": [items], "jobs": {id: {...}}}
STATE: dict[str, dict] = {}


def _sample_library() -> list[dict]:
    return [
        {"asin": "B0000000P1", "title": "The Long Way", "author": "A. Writer",
         "narrator": "N. Reader", "runtimeMinutes": 610, "coverUrl": "",
         "isPurchased": True, "purchaseStatus": "purchased"},
        {"asin": "B0000000P2", "title": "Deep Field", "author": "B. Scribe",
         "narrator": "M. Voice", "runtimeMinutes": 725, "isPurchased": True,
         "purchaseStatus": "purchased"},
        {"asin": "B0000000X1", "title": "Borrowed Tale", "author": "C. Author",
         "runtimeMinutes": 300, "isPlus": True, "purchaseStatus": "plus"},
    ]


def _auth(authorization: str | None) -> None:
    if not _TOKEN:
        return  # no token configured (dev)
    if authorization != f"Bearer {_TOKEN}":
        raise HTTPException(401, "bad token")


def _profile(state_key: str) -> dict:
    return STATE.setdefault(state_key, {"authed": False, "library": [], "jobs": {}})


@app.get("/health")
async def health():
    return {"status": "ok", "libation": "mock", "busy": False}


@app.post("/v1/auth/start")
async def auth_start(request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization)
    body = await request.json()
    pid = body["profile"]
    _profile(pid)
    return {"status": "waiting_for_browser", "sessionId": uuid.uuid4().hex,
            "loginUrl": "https://www.amazon.com/ap/signin?mock=1",
            "expiresAt": time.time() + 600}


@app.post("/v1/auth/complete", status_code=202)
async def auth_complete(request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization)
    body = await request.json()
    pid = body["profile"]
    # A real companion would validate the pasted responseUrl with Libation. The mock
    # accepts anything that looks like a URL and marks the profile authed with a library.
    if not str(body.get("responseUrl", "")).startswith("http"):
        raise HTTPException(400, "bad response url")
    p = _profile(pid)
    p["authed"] = True
    p["library"] = _sample_library()
    return {"status": "connected"}


@app.get("/v1/library")
async def library(profile: str, authorization: str | None = Header(default=None)):
    _auth(authorization)
    p = _profile(profile)
    if not p["authed"]:
        raise HTTPException(409, "not authed")
    return {"items": p["library"], "totalItems": len(p["library"])}


@app.get("/v1/present")
async def present(authorization: str | None = Header(default=None)):
    """ASINs the shared library already holds. The real companion reads Libation's `[ASIN]`
    folder tags off disk; set MOCK_PRESENT_ASINS (comma-separated) to exercise the
    'already in Avrana' path in the credential-free walkthrough."""
    _auth(authorization)
    raw = os.environ.get("MOCK_PRESENT_ASINS", "")
    return {"asins": [a.strip().upper() for a in raw.split(",") if a.strip()]}


@app.post("/v1/sync", status_code=202)
async def sync(request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization)
    body = await request.json()
    pid = body["profile"]
    jid = uuid.uuid4().hex
    _profile(pid)["jobs"][jid] = {"id": jid, "kind": "scan", "status": "succeeded"}
    return {"id": jid, "status": "succeeded"}


@app.post("/v1/backups/{asin}", status_code=202)
async def backup(asin: str, request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization)
    body = await request.json()
    pid = body["profile"]
    jid = uuid.uuid4().hex
    # Mock: succeed immediately. Set MOCK_FAIL_ASIN to force a failure for retry tests.
    present = {a.strip().upper() for a in os.environ.get("MOCK_PRESENT_ASINS", "").split(",") if a.strip()}
    if asin.upper() in present:
        status = "skipped"  # mirrors the real companion's refusal to overwrite existing media
    elif asin == os.environ.get("MOCK_FAIL_ASIN"):
        status = "failed"
    else:
        status = "succeeded"
    _profile(pid)["jobs"][jid] = {"id": jid, "kind": "backup", "asin": asin, "status": status,
                                  "error": "mock failure" if status == "failed" else None}
    return {"id": jid, "status": "running"}


@app.get("/v1/jobs/{job_id}")
async def job(job_id: str, profile: str, authorization: str | None = Header(default=None)):
    _auth(authorization)
    p = _profile(profile)
    j = p["jobs"].get(job_id)
    if not j:
        raise HTTPException(404, "no job")
    return j


@app.post("/v1/revoke")
async def revoke(request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization)
    body = await request.json()
    pid = body["profile"]
    STATE.pop(pid, None)  # idempotent
    return {"status": "revoked"}
