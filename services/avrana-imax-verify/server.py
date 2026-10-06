#!/usr/bin/env python3
"""Radarr post-import webhook -> IMAX framing verification.

Radarr is not modified. It gets a stock Webhook connection pointed here; ffmpeg, the
expectations store and the results all live in this service.

SCOPE. Only imports that matched the IMAX selection logic are verified. Everything else is
acknowledged and dropped, so this never becomes a library-wide scanner.

DELIBERATELY PASSIVE. A FAIL is tagged, logged and optionally notified. Nothing is deleted,
blocklisted or re-searched.
"""
from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import imax_verify as iv

PORT = int(os.environ.get("PORT", "8099"))
SAMPLES = int(os.environ.get("IMAX_SAMPLES", str(iv.DEFAULT_SAMPLES)))
WORKERS = 1                                   # one job at a time, always

RADARR_URL = os.environ.get("RADARR_URL", "").rstrip("/")
RADARR_KEY = os.environ.get("RADARR_API_KEY", "")
TAGS = {"PASS": "imax-verified", "FAIL": "imax-failed", "UNKNOWN": "imax-unknown"}

# Defer while Jellyfin is transcoding. Playback matters more than verification, and this box
# cannot do both. Empty JELLYFIN_URL disables the check rather than failing closed.
JELLYFIN_URL = os.environ.get("JELLYFIN_URL", "").rstrip("/")
JELLYFIN_KEY = os.environ.get("JELLYFIN_API_KEY", "")
DEFER_POLL_S = int(os.environ.get("IMAX_DEFER_POLL_S", "60"))
DEFER_MAX_S = int(os.environ.get("IMAX_DEFER_MAX_S", "10800"))   # give up deferring after 3h

# Pluggable FAIL notification. A command template; {json} is replaced with the result path.
# Avrana has no notification platform of its own, so nothing is built here beyond the hook.
NOTIFY_CMD = os.environ.get("IMAX_NOTIFY_CMD", "")

# Only files under this root are ever probed (forensic audit N2: the webhook body named the path
# and nothing checked it). Radarr reports container paths, and the compose file mounts the movies
# tree at the same path, so a legitimate import is always under here.
ALLOWED_ROOT = Path(os.environ.get("IMAX_ALLOWED_ROOT", "/data/movies"))

# Webhook authentication. Radarr's webhook connection carries a username and password as HTTP
# Basic auth. IMAX_WEBHOOK_AUTH: "required" rejects a POST without the right credentials;
# "warn" (the roll-out mode) accepts it but logs a warning; "off" checks nothing.
WEBHOOK_AUTH = os.environ.get("IMAX_WEBHOOK_AUTH", "warn").lower()
WEBHOOK_USER = os.environ.get("IMAX_WEBHOOK_USER", "radarr")
WEBHOOK_PASSWORD = os.environ.get("IMAX_WEBHOOK_PASSWORD", "")

JOBS: "queue.Queue[dict]" = queue.Queue()
RESULTS = Path(os.environ.get("IMAX_RESULTS", "/config/results"))
LOG = RESULTS / "verifications.log"
HISTORY = RESULTS / "history.jsonl"


def allowed_path(path: str) -> Path | None:
    """The resolved file if it lies under ALLOWED_ROOT and exists, else None.

    Resolving follows symlinks, so a link inside the library that points outside is refused too."""
    try:
        root = ALLOWED_ROOT.resolve()
        candidate = Path(path).resolve()
    except (OSError, RuntimeError):
        return None
    if root != candidate and root not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


def authorized(header: str | None) -> bool:
    """True when the Authorization header carries the configured Basic credentials."""
    import base64
    import hmac
    if not WEBHOOK_PASSWORD:
        return False
    if not header or not header.startswith("Basic "):
        return False
    try:
        user, _, password = base64.b64decode(header[6:].strip()).decode().partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(user, WEBHOOK_USER) and hmac.compare_digest(password, WEBHOOK_PASSWORD)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    print(line, flush=True)
    try:
        RESULTS.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- IMAX selection gate
def matched_imax(payload: dict) -> tuple[bool, str]:
    """Did this import match the IMAX/IMAX Enhanced selection logic?

    Prefer Radarr's own custom-format decision; fall back to the release name only if Radarr
    sent no format information.
    """
    mf = payload.get("movieFile") or {}
    seen = []
    for src in (mf.get("customFormats"), payload.get("customFormats"),
                (payload.get("release") or {}).get("customFormats")):
        for cf in (src or []):
            seen.append(cf.get("name") if isinstance(cf, dict) else str(cf))
    if seen:
        hit = [n for n in seen if n and "imax" in n.lower()]
        return bool(hit), f"custom format {hit}" if hit else f"no IMAX in {seen}"
    name = " ".join(str(x) for x in (mf.get("sceneName"), mf.get("relativePath"),
                                     mf.get("releaseGroup")) if x)
    return ("imax" in name.lower()), "release name" if "imax" in name.lower() else "no IMAX marker"


# ---------------------------------------------------------------- Jellyfin deferral
def jellyfin_busy() -> bool:
    if not (JELLYFIN_URL and JELLYFIN_KEY):
        return False
    try:
        req = urllib.request.Request(f"{JELLYFIN_URL}/Sessions",
                                     headers={"X-MediaBrowser-Token": JELLYFIN_KEY})
        for s in json.load(urllib.request.urlopen(req, timeout=10)):
            if not s.get("NowPlayingItem"):
                continue
            ti = s.get("TranscodingInfo") or {}
            if ti and not (ti.get("IsVideoDirect") and ti.get("IsAudioDirect")):
                return True
    except Exception:
        return False          # never let a Jellyfin hiccup stall verification forever
    return False


def wait_for_quiet() -> None:
    waited = 0
    while jellyfin_busy() and waited < DEFER_MAX_S:
        if waited == 0:
            log("  deferring: Jellyfin is transcoding")
        time.sleep(DEFER_POLL_S)
        waited += DEFER_POLL_S
    if waited:
        log(f"  resuming after {waited}s of deferral")


# ---------------------------------------------------------------- Radarr tagging
def _radarr(path: str, method: str = "GET", body=None):
    req = urllib.request.Request(f"{RADARR_URL}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Api-Key": RADARR_KEY,
                                          "Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=30).read()
    return json.loads(raw) if raw else {}


def tag_movie(movie_id: int | None, verdict: str) -> str:
    """Put the verdict on the movie as a Radarr tag, clearing the other two."""
    if not (RADARR_URL and RADARR_KEY and movie_id):
        return "skipped (radarr not configured)"
    try:
        want = TAGS[verdict]
        existing = {t["label"]: t["id"] for t in _radarr("/api/v3/tag")}
        for label in TAGS.values():
            if label not in existing:
                existing[label] = _radarr("/api/v3/tag", "POST", {"label": label})["id"]
        movie = _radarr(f"/api/v3/movie/{movie_id}")
        ours = {existing[l] for l in TAGS.values()}
        tags = [t for t in movie.get("tags", []) if t not in ours] + [existing[want]]
        movie["tags"] = tags
        _radarr(f"/api/v3/movie/{movie_id}", "PUT", movie)
        return f"tagged {want}"
    except Exception as e:
        return f"tagging failed: {type(e).__name__}"


def notify_fail(result_path: Path, res: dict) -> None:
    """FAIL only. Routine PASS is never notified."""
    if not NOTIFY_CMD:
        return
    cmd = NOTIFY_CMD.replace("{json}", str(result_path)) \
                    .replace("{title}", str(res.get("title"))) \
                    .replace("{reason}", str(res.get("reason")))
    try:
        subprocess.run(shlex.split(cmd), timeout=60, capture_output=True)
        log("  FAIL notification dispatched")
    except Exception as e:
        log(f"  FAIL notification failed: {type(e).__name__}")


def append_history(res: dict) -> None:
    a = res.get("analysis") or {}
    row = {
        "checked_at": res.get("checked_at"),
        "tmdb_id": res.get("tmdb_id"),
        "movie_id": res.get("movie_id"),
        "title": res.get("title"),
        "file": res.get("file"),
        "verdict": res.get("verdict"),
        "reason": res.get("reason"),
        "claimed_imax": res.get("claimed_imax"),
        "expected": (res.get("expectation") or {}).get("expected_ratio"),
        "presentation": res.get("presentation"),
        "expanded_share": res.get("expanded_share"),
        "scope_share": res.get("scope_share"),
        "distribution": [{"ar": d["ar"], "share": d["share"],
                          "approx_runtime_s": d["approx_runtime_s"]}
                         for d in (a.get("distribution") or [])],
        "usable_samples": a.get("usable_samples"),
        "requested_samples": a.get("requested_samples"),
        "elapsed_s": res.get("elapsed_s"),
    }
    try:
        RESULTS.mkdir(parents=True, exist_ok=True)
        with HISTORY.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


def worker() -> None:
    while True:
        job = JOBS.get()
        try:
            wait_for_quiet()
            res = iv.verify(job["path"], job.get("tmdb"), samples=SAMPLES,
                            title=job.get("title"), claimed_imax=job.get("claimed"))
            res["movie_id"] = job.get("movie_id")
            out = iv.write_result(res)
            append_history(res)
            tagged = tag_movie(job.get("movie_id"), res["verdict"])
            log(f"{res['verdict']} tmdb={res.get('tmdb_id')} '{res.get('title')}' "
                f"-> {res.get('reason')} [{out.name}, {res['elapsed_s']}s, {tagged}]")
            if res["verdict"] == "FAIL":
                notify_fail(out, res)
        except iv.ProbeError as e:
            log(f"ERROR probe failed for {job['path']}: {e}")
        except Exception as e:
            log(f"ERROR {type(e).__name__} verifying {job['path']}: {e}")
        finally:
            JOBS.task_done()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):                                # noqa: N802
        if self.path.startswith("/health"):
            return self._send(200, {"status": "ok", "queued": JOBS.qsize(),
                                    "jellyfin_busy": jellyfin_busy()})
        if self.path.startswith("/history"):
            rows = []
            if HISTORY.exists():
                for line in HISTORY.read_text().splitlines()[-200:]:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return self._send(200, {"count": len(rows), "history": rows})
        if self.path.startswith("/results"):
            out = []
            for f in sorted(RESULTS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
                try:
                    r = json.loads(f.read_text())
                    out.append({"tmdb_id": r.get("tmdb_id"), "title": r.get("title"),
                                "verdict": r.get("verdict"), "reason": r.get("reason"),
                                "checked_at": r.get("checked_at")})
                except Exception:
                    continue
            return self._send(200, {"count": len(out), "results": out})
        return self._send(404, {"error": "not found"})

    def do_POST(self):                               # noqa: N802
        if WEBHOOK_AUTH != "off" and not authorized(self.headers.get("Authorization")):
            if WEBHOOK_AUTH == "required":
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="avrana-imax-verify"')
                self.end_headers()
                log(f"rejected unauthenticated POST from {self.client_address[0]}")
                return
            log(f"WARN unauthenticated POST from {self.client_address[0]} accepted (IMAX_WEBHOOK_AUTH=warn)")
        n = min(int(self.headers.get("Content-Length") or 0), 1 << 20)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._send(400, {"error": "invalid json"})

        ev = payload.get("eventType")
        if ev == "Test":
            log("received Radarr webhook test")
            return self._send(200, {"status": "ok", "message": "avrana-imax-verify reachable"})
        if ev not in ("Download", "MovieFileImported"):
            return self._send(200, {"status": "ignored", "eventType": ev})

        movie = payload.get("movie") or {}
        mf = payload.get("movieFile") or {}
        folder, rel = movie.get("folderPath") or "", mf.get("relativePath") or ""
        path = mf.get("path") or (str(Path(folder) / rel) if folder and rel else None)
        if not path:
            return self._send(200, {"status": "ignored", "reason": "no file path"})
        if allowed_path(path) is None:
            log(f"ignored '{movie.get('title')}': path is not a file under {ALLOWED_ROOT}")
            return self._send(200, {"status": "ignored", "reason": "path outside the movie library"})
        path = str(allowed_path(path))

        is_imax, why = matched_imax(payload)
        if not is_imax:
            log(f"skipped '{movie.get('title')}': not an IMAX selection ({why})")
            return self._send(200, {"status": "skipped", "reason": why})

        JOBS.put({"path": path, "tmdb": movie.get("tmdbId"), "movie_id": movie.get("id"),
                  "title": movie.get("title"), "claimed": True})
        log(f"queued {ev}: '{movie.get('title')}' tmdb={movie.get('tmdbId')} via {why}")
        return self._send(200, {"status": "queued", "queued": JOBS.qsize()})

    def log_message(self, *a):
        return


def main() -> None:
    for _ in range(WORKERS):
        threading.Thread(target=worker, daemon=True).start()
    log(f"avrana-imax-verify on :{PORT} samples={SAMPLES} threads={iv.FFMPEG_THREADS} "
        f"radarr={'yes' if RADARR_URL else 'no'} jellyfin_defer={'yes' if JELLYFIN_URL else 'no'} "
        f"notify={'yes' if NOTIFY_CMD else 'no'} root={ALLOWED_ROOT} webhook_auth={WEBHOOK_AUTH}")
    if WEBHOOK_AUTH != "off" and not WEBHOOK_PASSWORD:
        log("WARN IMAX_WEBHOOK_PASSWORD is empty: every POST is unauthenticated")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
