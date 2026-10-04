"""The companion persists jobs so a restart is recoverable.

The connector polls `/v1/jobs/<id>` until it hears a terminal status. Before this, the
companion kept jobs only in memory, so a restart (or crash) both lost the id — the connector
would poll a job the companion no longer knew, get 404 forever — and, worse, a download that
was 'running' when the process died looked like it might still be going. Now jobs live in a
small SQLite store and any 'running' job is reconciled to 'failed/interrupted' on startup,
because its LibationCli subprocess died with the old process.

The real companion module is loaded by path (it lives outside the connector package). Its DB
and profiles root are redirected to a temp dir via env.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

COMPANION_PY = Path(__file__).resolve().parents[2] / "companion" / "api" / "companion.py"


def _load_companion(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILES_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("COMPANION_JOBS_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("COMPANION_TOKEN_FILE", str(tmp_path / "no-token"))
    spec = importlib.util.spec_from_file_location("companion_persist_test", COMPANION_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._init_jobs()  # the real trigger is the app startup event; call it directly in tests
    return mod


def test_a_saved_job_round_trips_across_a_restart(tmp_path, monkeypatch):
    c = _load_companion(tmp_path, monkeypatch)
    c._JOBS["job-done"] = {"id": "job-done", "kind": "backup", "profile": "p1",
                           "asin": "B000000AA1", "status": "succeeded", "error": None}
    c._save_job("job-done")

    c._JOBS.clear()          # simulate the process going away
    c._init_jobs()           # ...and coming back
    assert c._JOBS["job-done"]["status"] == "succeeded"
    assert c._JOBS["job-done"]["asin"] == "B000000AA1"


def test_running_job_is_reconciled_to_interrupted_on_restart(tmp_path, monkeypatch):
    c = _load_companion(tmp_path, monkeypatch)
    # A download was in flight when the process died.
    c._JOBS["job-live"] = {"id": "job-live", "kind": "backup", "profile": "p1",
                           "asin": "B000000AA2", "status": "running", "error": None}
    c._save_job("job-live")

    c._JOBS.clear()
    c._init_jobs()           # restart

    j = c._JOBS["job-live"]
    assert j["status"] == "failed", "a 'running' job cannot survive the process that ran it"
    assert "interrupt" in (j["error"] or "").lower()


def test_set_job_status_persists(tmp_path, monkeypatch):
    c = _load_companion(tmp_path, monkeypatch)
    c._JOBS["j"] = {"id": "j", "kind": "backup", "profile": "p", "asin": "B000000AA3",
                    "status": "running", "error": None}
    c._save_job("j")
    c._set_job_status("j", "succeeded", None)

    c._JOBS.clear()
    c._init_jobs()
    assert c._JOBS["j"]["status"] == "succeeded"  # not reverted to interrupted


def test_the_jobs_db_is_not_a_valid_profile_id(tmp_path, monkeypatch):
    """The store is a dotfile at PROFILES_ROOT root; it must never be mistaken for a profile
    (which would let a crafted request read/delete it)."""
    c = _load_companion(tmp_path, monkeypatch)
    assert c._ID_RE.match(".companion-jobs.db") is None
