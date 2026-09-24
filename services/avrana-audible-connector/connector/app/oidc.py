"""Authentik OIDC login (Authorization Code + PKCE), implemented directly on httpx to avoid
extra dependencies. Sets the signed session cookie that identity.get_identity consumes.

The code exchange is a server-to-server call to Authentik over TLS; claims (including
`groups`) are read from the userinfo endpoint with the returned access token. State + nonce
are bound in a short-lived signed cookie to prevent CSRF/replay on the callback.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .identity import SESSION_COOKIE, session_serializer

router = APIRouter()
_STATE_COOKIE = "avrana_ac_oidc"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


async def _discovery(request: Request) -> dict:
    cached = getattr(request.app.state, "_oidc_meta", None)
    if cached:
        return cached
    settings = request.app.state.settings
    url = f"{settings.oidc_issuer}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10) as client:
        meta = (await client.get(url)).json()
    request.app.state._oidc_meta = meta
    return meta


def _state_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="avrana-audible-oidc-state")


@router.get("/auth/login")
async def login(request: Request):
    settings = request.app.state.settings
    if settings.auth_mode != "oidc":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "OIDC disabled")
    meta = await _discovery(request)
    verifier = _b64(secrets.token_bytes(48))
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    redirect_uri = f"{settings.public_base_url}/auth/callback"
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = str(httpx.URL(meta["authorization_endpoint"], params=params))
    resp = RedirectResponse(auth_url, status_code=status.HTTP_302_FOUND)
    blob = _state_serializer(settings.secret_key).dumps(
        {"state": state, "nonce": nonce, "verifier": verifier}
    )
    resp.set_cookie(
        _STATE_COOKIE, blob, max_age=600, httponly=True, secure=settings.cookie_secure,
        samesite="lax",
    )
    return resp


@router.get("/auth/callback")
async def callback(request: Request):
    settings = request.app.state.settings
    if settings.auth_mode != "oidc":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "OIDC disabled")
    err = request.query_params.get("error")
    if err:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Login was cancelled or failed")
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    raw = request.cookies.get(_STATE_COOKIE, "")
    try:
        saved = _state_serializer(settings.secret_key).loads(raw, max_age=600)
    except (BadSignature, Exception):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Login session expired; try again")
    if not code or not secrets.compare_digest(state, saved.get("state", "")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid login state")

    meta = await _discovery(request)
    redirect_uri = f"{settings.public_base_url}/auth/callback"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": settings.oidc_client_id,
        "code_verifier": saved["verifier"],
    }
    if settings.oidc_client_secret:
        data["client_secret"] = settings.oidc_client_secret
    async with httpx.AsyncClient(timeout=15) as client:
        tok = await client.post(meta["token_endpoint"], data=data)
        if tok.status_code >= 400:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not complete login")
        access_token = tok.json().get("access_token", "")
        ui = await client.get(
            meta["userinfo_endpoint"], headers={"Authorization": f"Bearer {access_token}"}
        )
    claims = ui.json() if ui.status_code < 400 else {}
    sub = str(claims.get("sub", ""))
    if not sub:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Login did not return an identity")

    ident_data = {
        "sub": sub,
        "username": claims.get("preferred_username") or claims.get("nickname") or sub,
        "email": claims.get("email", ""),
        "groups": claims.get("groups", []),
    }
    session = session_serializer(settings.secret_key).dumps(ident_data)
    resp = RedirectResponse("/contribute/audible", status_code=status.HTTP_302_FOUND)
    resp.delete_cookie(_STATE_COOKIE)
    resp.set_cookie(
        SESSION_COOKIE, session, max_age=settings.session_ttl_seconds, httponly=True,
        secure=settings.cookie_secure, samesite="lax",
    )
    return resp


@router.get("/auth/logout")
async def logout(request: Request):
    resp = RedirectResponse("/contribute/audible", status_code=status.HTTP_302_FOUND)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
