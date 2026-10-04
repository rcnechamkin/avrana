"""Test harness: in-process app with a fake companion and header-based identities so tests
can act as different Authentik users. No real Audible or Libation is ever touched."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # import `app`

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


class FakeCompanion:
    """Mimics CompanionClient with in-memory per-profile state and recorded calls."""

    def __init__(self):
        self.profiles: dict[str, dict] = {}
        self.revoked: list[str] = []
        self.fail_backup_asins: set[str] = set()
        self.fail_backup_all = False
        self.fail_complete = False  # when True, auth_complete raises like a rejected handshake
        self.jobs: dict[str, dict] = {}
        # ASINs the shared library already holds on disk (the real companion reads these
        # from Libation's `[ASIN]` folder tags). Backups for these are skipped, never run.
        self.present_asins: set[str] = set()

    def _p(self, pid):
        return self.profiles.setdefault(pid, {"authed": False, "library": []})

    async def health(self):
        return {"status": "ok"}

    async def auth_start(self, profile_id, email, locale):
        self._p(profile_id)
        return {"sessionId": "cs-" + uuid.uuid4().hex, "loginUrl": "https://amazon.example/signin?x=1"}

    async def auth_complete(self, profile_id, companion_session, response_url):
        assert response_url.startswith("http")
        if self.fail_complete:
            from app.companion_client import CompanionError
            raise CompanionError("Audible could not complete the sign-in.")
        p = self._p(profile_id)
        p["authed"] = True
        p["library"] = [
            {"asin": "B000000AA1", "title": "Owned One", "author": "Auth A",
             "narrator": "Nar", "runtimeMinutes": 600, "isPurchased": True, "purchaseStatus": "purchased"},
            {"asin": "B000000AA2", "title": "Owned Two", "author": "Auth B",
             "runtimeMinutes": 720, "isPurchased": True, "purchaseStatus": "purchased"},
            {"asin": "B000000PL1", "title": "Plus Borrow", "isPlus": True, "purchaseStatus": "plus"},
        ]
        return {"status": "connected"}

    async def library(self, profile_id):
        return {"items": self._p(profile_id)["library"]}

    async def scan(self, profile_id):
        jid = "scan-" + uuid.uuid4().hex
        self.jobs[jid] = {"id": jid, "status": "succeeded"}
        return {"id": jid, "status": "succeeded"}

    async def present(self):
        return set(self.present_asins)

    async def backup(self, profile_id, asin):
        jid = "job-" + uuid.uuid4().hex
        fail = self.fail_backup_all or asin in self.fail_backup_asins
        if asin in self.present_asins:
            status, error = "skipped", "already in library"
        else:
            status, error = ("failed", "mock failure") if fail else ("succeeded", None)
        self.jobs[jid] = {"id": jid, "asin": asin, "status": status, "error": error}
        return {"id": jid, "status": "running"}

    async def job(self, profile_id, companion_job):
        return self.jobs.get(companion_job, {"id": companion_job, "status": "running"})

    async def revoke(self, profile_id):
        self.revoked.append(profile_id)
        self.profiles.pop(profile_id, None)
        return {"status": "revoked"}

    def add_new_purchase(self, profile_id, asin, title="New Buy"):
        self._p(profile_id)["library"].append(
            {"asin": asin, "title": title, "isPurchased": True, "purchaseStatus": "purchased"}
        )


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        companion_base_url="http://companion",
        companion_token="t",
        companion_timeout_seconds=5,
        required_group="library-contributors",
        auth_mode="header",
        oidc_issuer="", oidc_client_id="", oidc_client_secret="", public_base_url="",
        hdr_sub="x-authentik-uid", hdr_username="x-authentik-username",
        hdr_email="x-authentik-email", hdr_groups="x-authentik-groups",
        dev_identity="",
        db_path=str(tmp_path / "t.db"),
        secret_key="test-secret-key-000",
        cookie_secure=False,
        session_ttl_seconds=1800,
        rate_limit_window_seconds=300,
        rate_limit_max=10000,
        scan_interval_hours=24,
        brand_name="Avrana",
    )


@pytest.fixture
def fake() -> FakeCompanion:
    return FakeCompanion()


@pytest.fixture
def app(settings, fake):
    application = create_app(settings)
    application.state.companion = fake
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


def hdr(sub: str, groups: str = "library-contributors") -> dict:
    return {
        "x-authentik-uid": sub, "x-authentik-username": sub,
        "x-authentik-email": f"{sub}@example.invalid", "x-authentik-groups": groups,
        "accept": "text/html",
    }


def csrf(app, sub: str) -> str:
    return app.state.csrf.issue(sub)
