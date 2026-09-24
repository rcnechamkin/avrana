"""Async HTTP client for the private Libation companion.

The browser never talks to the companion; only this server-side client does. The bearer
token is held server-side (loaded from a mounted file). Every call targets a specific
`profile_id`, which is how per-account isolation is enforced end to end.

All companion errors are caught and re-raised as CompanionError with a redacted message so
raw Libation/Amazon errors (which may embed URLs or tokens) never surface to users or logs.
"""
from __future__ import annotations

from typing import Any

import httpx

from .security import redact


class CompanionError(Exception):
    """A sanitized companion failure. `.user_message` is safe to show end users."""

    def __init__(self, user_message: str, diagnostic: str = ""):
        super().__init__(user_message)
        self.user_message = user_message
        self.diagnostic = redact(diagnostic)


class CompanionClient:
    def __init__(self, base_url: str, token: str, timeout: float):
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._timeout = timeout

    async def _request(self, method: str, path: str, **kw: Any) -> dict:
        url = f"{self._base}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(method, url, headers=self._headers, **kw)
        except httpx.HTTPError as exc:
            # Never include the URL/body verbatim.
            raise CompanionError(
                "Avrana cannot reach the import right now. Please try again shortly.",
                diagnostic=f"{type(exc).__name__}",
            ) from None
        if resp.status_code >= 400:
            raise CompanionError(
                _friendly_status(resp.status_code),
                diagnostic=f"companion {resp.status_code}: {redact(resp.text)[:200]}",
            )
        if resp.content:
            try:
                return resp.json()
            except ValueError:
                return {}
        return {}

    # --- contract ----------------------------------------------------------------------
    async def health(self) -> dict:
        return await self._request("GET", "/health")

    async def auth_start(self, profile_id: str, email: str, locale: str) -> dict:
        return await self._request(
            "POST", "/v1/auth/start",
            json={"profile": profile_id, "account": email, "locale": locale},
        )

    async def auth_complete(self, profile_id: str, companion_session: str, response_url: str) -> dict:
        # response_url is forwarded and then forgotten. Do not log it here or anywhere.
        return await self._request(
            "POST", "/v1/auth/complete",
            json={"profile": profile_id, "sessionId": companion_session, "responseUrl": response_url},
        )

    async def library(self, profile_id: str) -> dict:
        return await self._request("GET", f"/v1/library?profile={profile_id}")

    async def present(self) -> set[str] | None:
        """ASINs the shared Avrana library already holds (library-wide, not per-profile).

        Returns None, NOT an empty set, when the companion could not answer. The caller
        uses this to reconcile books recorded as imported, and an empty set means "the
        library is empty", which would reset every imported book to available and re-download
        the entire library. Absence of an answer must never be read as absence of files.

        A failure here is otherwise harmless: the companion refuses an overwriting download
        regardless, so this only affects whether the UI can say 'already in Avrana' up front.
        """
        try:
            resp = await self._request("GET", "/v1/present")
        except CompanionError:
            return None
        return {str(a).strip().upper() for a in resp.get("asins", []) if a}

    async def scan(self, profile_id: str) -> dict:
        return await self._request("POST", "/v1/sync", json={"profile": profile_id})

    async def backup(self, profile_id: str, asin: str) -> dict:
        return await self._request("POST", f"/v1/backups/{asin}", json={"profile": profile_id})

    async def job(self, profile_id: str, companion_job: str) -> dict:
        return await self._request("GET", f"/v1/jobs/{companion_job}?profile={profile_id}")

    async def revoke(self, profile_id: str) -> dict:
        """Idempotent: removes the profile's stored Audible authorization and state."""
        return await self._request("POST", "/v1/revoke", json={"profile": profile_id})


def _friendly_status(code: int) -> str:
    if code in (401, 403):
        return "Avrana could not authorize the import. Please contact an administrator."
    if code == 404:
        return "That book could not be found."
    if code == 409:
        return "The import is busy with another book. Please try again shortly."
    if code == 429:
        return "Too many requests just now. Please wait a moment and try again."
    return ("Something went wrong with the import. Please try again. "
            "If it keeps happening, contact an administrator.")
