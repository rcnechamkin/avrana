"""Avrana Libation Companion: per-profile adapter over LibationCli.

Runs INSIDE the rmcrackan/libation image (which ships LibationCli). Exposes the small HTTP
contract the connector depends on. Every operation targets one Libation profile directory
(`--libationFiles /profiles/<profile>`), which is the isolation primitive: each connected
Audible account has a physically separate Libation state DB and AccountsSettings.json.

Libation serializes operations, so a single global lock guards all CLI invocations.

Bearer token is read from COMPANION_TOKEN_FILE (mode 0600, mounted read-only).

VERIFICATION NOTE: the LibationCli verbs/flags used here were confirmed against
`LibationCli help` (v13.7.7). The live Audible login handshake and the exact
`export --json` schema are NOT exercised in CI (no test Audible account, by policy). The
mock-companion is used for automated tests. Field mapping in `_normalize_export` is
defensive and documented; confirm against a real export before first production use.
"""
from __future__ import annotations

import asyncio
import json
import os
import pty
import re
import shutil
import sqlite3
import termios
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

PROFILES_ROOT = Path(os.environ.get("PROFILES_ROOT", "/profiles"))
BOOKS_DIR = os.environ.get("LIBATION_BOOKS_DIR", "/data")
# Staging dir; MUST be on the same filesystem as BOOKS_DIR so the finished-book move is an
# atomic same-fs rename (ABS never sees a half-written file) and big downloads don't fill
# the container root disk.
INPROGRESS_DIR = os.environ.get("LIBATION_IN_PROGRESS_DIR", "/inprogress")
CLI = os.environ.get("LIBATION_CLI", "LibationCli")
TOKEN_FILE = os.environ.get("COMPANION_TOKEN_FILE", "/control/token")
AUTH_TTL = int(os.environ.get("AUTH_SESSION_TIMEOUT_MINUTES", "10")) * 60

_TOKEN = ""
if os.path.isfile(TOKEN_FILE):
    _TOKEN = Path(TOKEN_FILE).read_text(encoding="utf-8").strip()

# Libation serializes; one CLI operation at a time across ALL profiles.
_CLI_LOCK = asyncio.Lock()

# sessionId -> {proc, profile, created}. Live subprocess handles, NOT persistable; a restart
# drops in-flight logins and the user simply re-initiates the (short, interactive) login.
_LOGIN_SESSIONS: dict[str, dict] = {}
# jobId -> {status, asin, error, profile}. Backed by SQLite (see below) so a companion restart
# doesn't strand the connector polling a job id that no longer exists in memory.
_JOBS: dict[str, dict] = {}

# Persist jobs so restarts are recoverable. Lives at the PROFILES_ROOT root (a dotfile, so it
# can never be mistaken for a profile dir, since _ID_RE rejects the leading dot, and `revoke`,
# which only rmtrees PROFILES_ROOT/<valid-id>, never touches it).
JOBS_DB = os.environ.get("COMPANION_JOBS_DB", str(PROFILES_ROOT / ".companion-jobs.db"))


def _jobs_db() -> sqlite3.Connection:
    conn = sqlite3.connect(JOBS_DB, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_jobs() -> None:
    """Create the job store, then reconcile after a possible crash/restart: any job left
    'running' cannot actually be running: its LibationCli subprocess was a child of the old
    process and died with it, so mark it failed/interrupted. That turns a would-be forever
    'running' (the connector polls until it hears otherwise) into a clean, retryable failure.
    Also prunes old terminal jobs so the table stays small."""
    PROFILES_ROOT.mkdir(parents=True, exist_ok=True)
    conn = _jobs_db()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS jobs ("
            " id TEXT PRIMARY KEY, kind TEXT, profile TEXT, asin TEXT,"
            " status TEXT, error TEXT, updated_at TEXT DEFAULT (datetime('now')))"
        )
        conn.execute(
            "UPDATE jobs SET status='failed', error='interrupted by restart', "
            "updated_at=datetime('now') WHERE status='running'"
        )
        conn.execute(
            "DELETE FROM jobs WHERE status IN ('succeeded','failed','skipped') "
            "AND updated_at < datetime('now','-7 days')"
        )
        _JOBS.clear()
        for r in conn.execute("SELECT * FROM jobs"):
            _JOBS[r["id"]] = {"id": r["id"], "kind": r["kind"], "profile": r["profile"],
                              "asin": r["asin"], "status": r["status"], "error": r["error"]}
    finally:
        conn.close()


def _save_job(jid: str) -> None:
    """Persist the current in-memory state of one job (upsert). Best-effort: a persistence
    hiccup must never crash an import."""
    j = _JOBS.get(jid)
    if not j:
        return
    try:
        conn = _jobs_db()
        try:
            conn.execute(
                "INSERT INTO jobs(id, kind, profile, asin, status, error, updated_at) "
                "VALUES (?,?,?,?,?,?,datetime('now')) "
                "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, profile=excluded.profile, "
                "asin=excluded.asin, status=excluded.status, error=excluded.error, "
                "updated_at=datetime('now')",
                (jid, j.get("kind"), j.get("profile"), j.get("asin"), j.get("status"), j.get("error")),
            )
        finally:
            conn.close()
    except sqlite3.Error:
        pass


def _set_job_status(jid: str, status: str, error: str | None = None) -> None:
    """Update a job's terminal state and persist it in one step."""
    j = _JOBS.get(jid)
    if j is None:
        return
    j["status"] = status
    j["error"] = error
    _save_job(jid)


@app.on_event("startup")
async def _load_persisted_jobs() -> None:
    # Runs when the container starts serving, NOT on bare `import companion` (so unit tests
    # that load this module to exercise pure functions don't need a writable /profiles).
    try:
        _init_jobs()
    except OSError:
        # A non-writable jobs path must not stop the companion from serving; it just loses
        # restart-recovery. In the real container /profiles is always writable.
        pass

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
_URL_RE = re.compile(r"https?://\S+")
# Amazon image id as it appears in Libation's export (e.g. "81XXDqZMCzL"). Constrained so a
# hostile value can never escape the URL template we interpolate it into.
_PICTURE_ID_RE = re.compile(r"^[A-Za-z0-9%_+-]{5,40}$")
# Libation's folder template tags finished books with the ASIN in brackets:
#   <Books>/<Author>/<Title [ASIN]>/...
# That tag is how we detect a title the shared library already has.
_ASIN_TAG_RE = re.compile(r"\[([A-Z0-9]{10})\]")

_DEFAULT_SETTINGS = {
    "AllowLibationFixup": True, "AudiobookshelfEnabled": False, "BadBook": "Ignore",
    "DecryptToLossy": False, "DownloadCoverArt": True, "FileDownloadQuality": "High",
    "FileTemplate": "<title> [<id>]", "FolderTemplate": "<first author>/<title> [<id>]",
    "LogLevel": "Information", "MoveMoovToBeginning": True, "OverwriteExisting": False,
    "Request_xHE_AAC": False, "SplitFilesByChapter": False,
    "TokenStorageMethod": "Plaintext", "UseWidevine": False,
}


def _auth(authorization: str | None) -> None:
    if not _TOKEN:
        raise HTTPException(500, "companion token not configured")
    if authorization != f"Bearer {_TOKEN}":
        raise HTTPException(401, "unauthorized")


def _profile_dir(profile: str) -> Path:
    if not _ID_RE.match(profile or ""):
        raise HTTPException(400, "invalid profile id")
    d = PROFILES_ROOT / profile
    d.mkdir(parents=True, exist_ok=True)
    settings = d / "Settings.json"
    if not settings.exists():
        settings.write_text(json.dumps(_DEFAULT_SETTINGS, indent=2) + "\n", encoding="utf-8")
        settings.chmod(0o600)
    return d


async def _run_cli(profile: str, *args: str, timeout: float) -> tuple[int, str, str]:
    """Run LibationCli against one profile under the global lock."""
    pdir = _profile_dir(profile)
    cmd = [CLI, *args, "--libationFiles", str(pdir)]
    async with _CLI_LOCK:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise HTTPException(504, "libation operation timed out")
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


@app.get("/health")
async def health():
    return {"status": "ok", "libation": "present", "busy": _CLI_LOCK.locked()}


@app.post("/v1/auth/start")
async def auth_start(request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization)
    body = await request.json()
    profile = body["profile"]
    email = str(body["account"]).strip()
    locale = str(body["locale"]).strip()
    pdir = _profile_dir(profile)

    # Libation refuses interactive login when stdin is a pipe. Give it a real pseudo-terminal,
    # disable echo so the response URL cannot be reflected, and retain it across both calls.
    master_fd, slave_fd = pty.openpty()
    attrs = termios.tcgetattr(slave_fd)
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
    proc = await asyncio.create_subprocess_exec(
        CLI, "login-external", "-a", email, "-l", locale, "--libationFiles", str(pdir),
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
    )
    os.close(slave_fd)
    login_url = ""
    captured = ""
    try:
        for _ in range(80):
            chunk = await asyncio.wait_for(asyncio.to_thread(os.read, master_fd, 4096), timeout=15)
            if not chunk:
                break
            captured += chunk.decode(errors="replace")
            m = _URL_RE.search(captured)
            if m:
                login_url = m.group(0).strip()
                break
    except (asyncio.TimeoutError, OSError):
        proc.kill()
        os.close(master_fd)
        raise HTTPException(504, "libation did not return a login url")
    if not login_url:
        proc.kill()
        os.close(master_fd)
        raise HTTPException(502, "no login url from libation")

    sid = uuid.uuid4().hex
    _LOGIN_SESSIONS[sid] = {"proc": proc, "pty": master_fd, "profile": profile,
                            "created": asyncio.get_event_loop().time()}
    _reap_sessions()
    return {"status": "waiting_for_browser", "sessionId": sid, "loginUrl": login_url}


@app.post("/v1/auth/complete", status_code=202)
async def auth_complete(request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization)
    body = await request.json()
    sid = body["sessionId"]
    response_url = str(body["responseUrl"])  # NEVER logged
    sess = _LOGIN_SESSIONS.pop(sid, None)
    if not sess or sess["profile"] != body.get("profile"):
        raise HTTPException(404, "unknown or mismatched session")
    proc = sess["proc"]
    master_fd = sess["pty"]
    try:
        os.write(master_fd, (response_url + "\n").encode())
        rc = await asyncio.wait_for(proc.wait(), timeout=60)
    except Exception:
        try:
            proc.kill()
        finally:
            os.close(master_fd)
            del response_url
        raise HTTPException(502, "login could not be completed")
    os.close(master_fd)
    del response_url
    if rc != 0:
        raise HTTPException(502, "audible rejected the login")
    return {"status": "connected"}


@app.post("/v1/sync", status_code=202)
async def sync(request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization)
    body = await request.json()
    profile = body["profile"]
    rc, _out, err = await _run_cli(profile, "scan", timeout=float(os.environ.get("CLI_SYNC_TIMEOUT", "1800")))
    jid = uuid.uuid4().hex
    _JOBS[jid] = {"id": jid, "kind": "scan", "profile": profile,
                  "status": "succeeded" if rc == 0 else "failed",
                  "error": None if rc == 0 else "scan failed"}
    _save_job(jid)
    return {"id": jid, "status": _JOBS[jid]["status"]}


@app.get("/v1/library")
async def library(profile: str, authorization: str | None = Header(default=None)):
    _auth(authorization)
    pdir = _profile_dir(profile)
    export_path = pdir / "export.json"
    rc, _out, _err = await _run_cli(
        profile, "export", "-j", "-p", str(export_path),
        timeout=float(os.environ.get("CLI_SHORT_TIMEOUT", "120")),
    )
    if rc != 0 or not export_path.is_file():
        raise HTTPException(502, "could not read library")
    try:
        raw = json.loads(export_path.read_text(encoding="utf-8"))
    except ValueError:
        raise HTTPException(502, "unreadable library export")
    finally:
        export_path.unlink(missing_ok=True)
    return {"items": _normalize_export(raw)}


def _present_asins() -> set[str]:
    """ASINs the shared Avrana library already holds, read from Libation's `[ASIN]` folder tag.

    This is the ground truth the connector's own DB cannot have: the library predates the
    connector (193 tagged folders as of 2026-08-14, all written by the admin Libation
    instance), and each connected account gets a *fresh* Libation profile DB that knows
    nothing about them. Without this check, a contributor selecting a book Avrana already
    owns would make Libation write to the exact same `<Author>/<Title [ASIN]>` path and
    clobber the existing media.

    Depth is bounded at 3 (real layout is <Author>/<Title [ASIN]>) so this stays a cheap
    directory listing rather than a full walk of a 7 TB array.
    """
    found: set[str] = set()
    root = Path(BOOKS_DIR)
    if not root.is_dir():
        return found
    for depth in (1, 2, 3):
        try:
            for p in root.glob("/".join(["*"] * depth)):
                m = _ASIN_TAG_RE.search(p.name)
                if m:
                    found.add(m.group(1).upper())
        except OSError:
            break
    return found


@app.get("/v1/present")
async def present(authorization: str | None = Header(default=None)):
    """ASINs already in the shared library. Library-wide fact, not per-profile: the
    connector uses it to show books as 'already in Avrana' instead of letting a user queue
    an import that the backup guard would refuse anyway."""
    _auth(authorization)
    return {"asins": sorted(_present_asins())}


@app.post("/v1/backups/{asin}", status_code=202)
async def backup(asin: str, request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization)
    if not _ASIN_RE.match(asin):
        raise HTTPException(400, "invalid asin")
    body = await request.json()
    profile = body["profile"]
    jid = uuid.uuid4().hex
    _JOBS[jid] = {"id": jid, "kind": "backup", "asin": asin, "profile": profile, "status": "running", "error": None}
    _save_job(jid)  # persist BEFORE the task starts, so a crash mid-download is recoverable
    asyncio.create_task(_run_backup(jid, profile, asin))
    return {"id": jid, "status": "running"}


async def _run_backup(jid: str, profile: str, asin: str) -> None:
    try:
        # Refuse to touch a title the shared library already has. `liberate` without -f skips
        # books this *profile's* DB records as downloaded, but a fresh profile has no such
        # record for the 193 books the admin instance imported, so the filesystem is the
        # only authority here. Checked immediately before the download, not at queue time,
        # so a concurrent import of the same ASIN still can't race into an overwrite.
        if asin in _present_asins():
            _set_job_status(jid, "skipped", "already in library")
            return
        # Pin output (Books) and staging (InProgress) explicitly. LibationCli, invoked
        # directly (not via the image's entrypoint), reads these from Settings.json unless
        # overridden, so override explicitly to guarantee books land in the shared ABS library and
        # staging happens on the same filesystem for an atomic move.
        rc, _out, err = await _run_cli(
            profile, "liberate", "-i", asin,
            "-o", f"Books={BOOKS_DIR}", "-o", f"InProgress={INPROGRESS_DIR}",
            timeout=float(os.environ.get("CLI_BACKUP_TIMEOUT", "21600")),
        )
        if rc != 0:
            _set_job_status(jid, "failed", "download failed")
            return
        # rc == 0 is NOT proof a book was produced. Observed live 2026-08-14: LibationCli
        # exited 0 for B076H97WQK having created the destination folder and then removed it,
        # leaving nothing on disk, and the connector recorded a phantom 'imported' book that no
        # rescan would ever correct. Confirm the ASIN-tagged output actually exists before
        # calling it a success, so a silent no-op stays retryable instead of becoming a lie.
        if asin not in _present_asins():
            _set_job_status(jid, "failed", "download produced no output")
            return
        _set_job_status(jid, "succeeded", None)
    except Exception:
        _set_job_status(jid, "failed", "download error")


@app.get("/v1/jobs/{job_id}")
async def job(job_id: str, profile: str, authorization: str | None = Header(default=None)):
    _auth(authorization)
    j = _JOBS.get(job_id)
    if not j or j.get("profile") != profile:
        raise HTTPException(404, "no such job")
    return j


@app.post("/v1/revoke")
async def revoke(request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization)
    body = await request.json()
    profile = body["profile"]
    if not _ID_RE.match(profile or ""):
        raise HTTPException(400, "invalid profile id")
    # Idempotent: remove the profile's Libation state (auth tokens, DB). A revoked profile
    # cannot be scanned again. This is what makes one-time mode truly one-time.
    target = PROFILES_ROOT / profile
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    # Drop any in-flight sessions for this profile.
    for sid in [s for s, v in _LOGIN_SESSIONS.items() if v["profile"] == profile]:
        try:
            _LOGIN_SESSIONS[sid]["proc"].kill()
            os.close(_LOGIN_SESSIONS[sid]["pty"])
        except Exception:
            pass
        _LOGIN_SESSIONS.pop(sid, None)
    # Forget this profile's jobs, in memory and on disk. A revoked account leaves no trace.
    for jid in [j for j, v in _JOBS.items() if v.get("profile") == profile]:
        _JOBS.pop(jid, None)
    try:
        conn = _jobs_db()
        try:
            conn.execute("DELETE FROM jobs WHERE profile=?", (profile,))
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    return {"status": "revoked"}


def _reap_sessions() -> None:
    now = asyncio.get_event_loop().time()
    for sid, v in list(_LOGIN_SESSIONS.items()):
        if now - v["created"] > AUTH_TTL:
            try:
                v["proc"].kill()
                os.close(v["pty"])
            except Exception:
                pass
            _LOGIN_SESSIONS.pop(sid, None)


def _cover_url(r: dict) -> str | None:
    """Build a cover URL from Libation's picture *id*.

    The export carries Amazon image ids (`PictureId` = thumb, `PictureLarge` = full), NOT
    URLs, e.g. "81XXDqZMCzL". They resolve under Amazon's media host; `_SL500_` caps the
    long edge at 500px so the picker doesn't pull full-resolution art.
    """
    pid = str(r.get("PictureLarge") or r.get("PictureId") or r.get("coverUrl") or "").strip()
    if not pid:
        return None
    if pid.startswith("http://") or pid.startswith("https://"):
        return pid
    if not _PICTURE_ID_RE.match(pid):
        return None
    return f"https://m.media-amazon.com/images/I/{pid}._SL500_.jpg"


def _normalize_export(raw) -> list[dict]:
    """Map Libation's export --json into the connector's item shape.

    SCHEMA VERIFIED 2026-08-14 against a real `LibationCli export -j` (v13.7.7, 211 records
    from the admin instance's populated library. No test Audible account was needed, the
    export is a local read of Libation's own DB). Relevant top-level keys, all flat:

        AudibleProductId  str   the ASIN (also non-B-prefixed ids, e.g. "0593291018")
        Title/Subtitle    str
        AuthorNames       str   comma-joined; NOT "Authors"
        NarratorNames     str   comma-joined; NOT "Narrators"
        LengthInMinutes   int
        PictureId         str   Amazon image id, not a URL (see _cover_url)
        PictureLarge      str   larger Amazon image id
        IsAudiblePlus     bool  THE ownership discriminator
        ContentType       str   "Product" | "Episode", same for owned AND Plus titles
        AbsentFromLastScan bool no longer returned by the account's library scan
        HasPdf            bool
        BookStatus        str   "Liberated" | "NotLiberated"

    OWNERSHIP, the bug this replaces: the previous mapping derived Plus from ContentType
    containing "ayce"/"plus". Real ContentType is "Product" for owned *and* Plus titles, so
    every Plus title was classified `isPurchased: True`. In this library that mislabelled 22
    of 211 titles as purchases; downloading one fails at licensing without an active Plus
    membership. `IsAudiblePlus` is the authoritative flag and is used directly here.

    `AbsentFromLastScan` additionally means the title is no longer in the account at all (in
    real data all 17 such records are Plus titles that aged out of the catalogue), so it is
    treated as non-purchasable too. Unknown/unclassifiable records stay non-purchased: the
    contract is that only a clearly owned purchase can ever be queued.
    """
    records = raw if isinstance(raw, list) else raw.get("books") or raw.get("items") or []
    out: list[dict] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        asin = str(r.get("AudibleProductId") or r.get("Asin") or r.get("asin") or "").strip().upper()
        if not _ASIN_RE.match(asin):
            continue
        title = r.get("Title") or r.get("title")
        authors = r.get("AuthorNames") or r.get("Authors") or r.get("Author") or r.get("author")
        narrators = (r.get("NarratorNames") or r.get("Narrators") or r.get("Narrator")
                     or r.get("narrator"))
        length = r.get("LengthInMinutes") or r.get("runtimeMinutes")
        content_type = str(r.get("ContentType") or r.get("contentType") or "").lower()
        # Primary flag, plus legacy/defensive fallbacks for other Libation versions.
        is_plus = bool(
            r.get("IsAudiblePlus")
            or r.get("IsAyce")
            or "ayce" in content_type
            or "plus" in content_type
        )
        absent = bool(r.get("AbsentFromLastScan"))
        owned = bool(r.get("IsOwned", True)) and not is_plus and not absent
        out.append({
            "asin": asin, "title": title, "author": authors, "narrator": narrators,
            "runtimeMinutes": length, "coverUrl": _cover_url(r),
            "hasPdf": bool(r.get("HasPdf")),
            "isPurchased": owned, "isPlus": is_plus,
            "purchaseStatus": "purchased" if owned else ("plus" if is_plus else "unavailable"),
        })
    return out
