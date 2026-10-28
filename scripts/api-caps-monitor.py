#!/usr/bin/env python3
"""Watch the third-party metadata APIs that can hit a real cap, and say when one breaks.

Passive on purpose: it reads what the services already record and spends NO quota of its own. Probing an API to
see whether it is rate limited would use up the very budget being watched.

Sources (all read-only):
  * Container logs since the last run (`docker logs --since`): Seerr (TMDB), Shelfarr and Shelfmark (Hardcover,
    Google Books, Open Library), Calibre-Web Automated (Hardcover), Omnibus and its engine (ComicVine, Metron).
  * Shelfarr's own provider health table, `metadata_provider_statuses` (status, rate_limited_until,
    failure_count), opened with `mode=ro`.
  * Omnibus's `JobLog` rows marked FAILED since the last run, opened with `mode=ro`.

Signals, per provider: `rate` (HTTP 429 or 420, "Too Many Requests", "rate limit", "quota", "velocity"), `auth`
(401 or 403 next to the provider's name: an expired or revoked key) and `down` (5xx, timeouts, provider marked
unhealthy). A bare number is never a signal: log timestamps are full of "429".

Nothing it prints or sends carries a key: matched lines are reduced to provider, service, signal and count, plus
one sample with every URL query and token-looking value replaced. State (last run, open incidents) lives in
~/.local/state/avrana/api-caps.json. A new incident, or one still open after a day, is sent through
scripts/avrana-alert.py; a run with nothing new prints one summary line for the journal.

Usage:
  api-caps-monitor.py                 check, alert on new incidents
  api-caps-monitor.py --dry-run       check and print, send nothing, keep the state unchanged
  api-caps-monitor.py --since 24h     look further back than the last run (first run default: 24h)

Exit: 0 nothing open · 1 an incident is open · 2 a source could not be read (still reports the rest)
"""
import argparse
import contextlib
import datetime as dt
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE = pathlib.Path(os.environ.get("AVRANA_API_CAPS_STATE",
                                    str(pathlib.Path.home() / ".local/state/avrana/api-caps.json")))
SHELFARR_DB = ROOT / "services/shelfarr/data/production.sqlite3"
OMNIBUS_DB = ROOT / "services/omnibus/config/omnibus.db"
ALERT = ROOT / "scripts/avrana-alert.py"
REMIND_AFTER = dt.timedelta(hours=24)

# container -> the providers it talks to (only these are looked for in its log)
CONTAINERS = {
    "seerr": ("tmdb",),
    "shelfarr": ("hardcover", "google_books", "openlibrary"),
    "shelfmark": ("hardcover", "google_books", "openlibrary"),
    "calibre-web-automated": ("hardcover", "google_books"),
    "omnibus": ("comicvine", "metron"),
    "omnibus-engine": ("comicvine", "metron"),
}
PROVIDER_WORDS = {
    "tmdb": r"tmdb|themoviedb",
    "hardcover": r"hardcover",
    "google_books": r"google ?books|googleapis\.com/books",
    "openlibrary": r"open ?library",
    "comicvine": r"comic ?vine|gamespot\.com/api",
    "metron": r"metron",
}
PROVIDER_RE = {p: re.compile(w, re.I) for p, w in PROVIDER_WORDS.items()}
RATE = re.compile(r"(?:status(?: code)?|http|error|code)[^0-9a-z]{0,3}(?:429|420)\b|\b(?:429|420) too many"
                  r"|too many requests|rate[- ]?limit(?:ed|ing)? (?:exceeded|hit|reached)|ratelimit"
                  r"|quota (?:exceeded|reached)|velocity|retry-after", re.I)
AUTH = re.compile(r"(?:status(?: code)?|http|error|code)[^0-9a-z]{0,3}(?:401|403)\b|unauthori[sz]ed|forbidden"
                  r"|invalid (?:api )?(?:key|token)|token (?:expired|revoked)|jwt expired", re.I)
DOWN = re.compile(r"(?:status(?: code)?|http|error|code)[^0-9a-z]{0,3}5\d\d\b|bad gateway|service unavailable"
                  r"|gateway time-?out|timed? ?out|connection (?:refused|reset)", re.I)
# Proactive self-throttling the services do on purpose: informational, never an incident.
SELF_THROTTLE = re.compile(r"Globally throttling|to prevent IP bans", re.I)
FAILURE_WORD = re.compile(r"\b(?:error|fail|failed|failure|warn|warning|exception)\b", re.I)

_QUERY = re.compile(r"\?[^\s\"'<>]*")
_SECRETISH = re.compile(r"(?i)(api[_-]?key|apikey|token|key|secret|password|authorization|bearer)([\"']?\s*[:=]\s*|\s+)"
                        r"[\"']?[^\s\"'&,;]+")
_LONG = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")


def redact(line: str, limit: int = 200) -> str:
    """One log line made safe to mail: no URL query strings, no key- or token-looking values, bounded."""
    line = _QUERY.sub("?<query>", line)
    line = _SECRETISH.sub(lambda m: m.group(1) + "=<redacted>", line)
    line = _LONG.sub("<long>", line)
    return line.strip()[:limit]


def classify(line: str, providers) -> list:
    """[(provider, signal)] for one log line, or [] if it is not about a capped provider breaking."""
    if SELF_THROTTLE.search(line):
        return []
    named = [p for p in providers if PROVIDER_RE[p].search(line)]
    if not named:
        return []
    if RATE.search(line):
        signal = "rate"
    elif AUTH.search(line) and FAILURE_WORD.search(line):
        signal = "auth"
    elif DOWN.search(line) and FAILURE_WORD.search(line):
        signal = "down"
    else:
        return []
    return [(p, signal) for p in named]


def scan_logs(since: dt.datetime, run=subprocess.run):
    """{(provider, signal): {"count", "services", "sample"}} from every listed container, plus unreadable names."""
    found, unreadable = {}, []
    stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    for name, providers in CONTAINERS.items():
        try:
            proc = run(["docker", "logs", "--since", stamp, name], capture_output=True, text=True,
                       errors="replace", timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            unreadable.append(name)
            continue
        if proc.returncode != 0:
            if "No such container" not in (proc.stderr or ""):
                unreadable.append(name)
            continue
        for line in (proc.stdout + proc.stderr).splitlines():
            for key in classify(line, providers):
                entry = found.setdefault(key, {"count": 0, "services": [], "sample": ""})
                entry["count"] += 1
                if name not in entry["services"]:
                    entry["services"].append(name)
                entry["sample"] = entry["sample"] or redact(line)
    return found, unreadable


def _ro(path: pathlib.Path):
    return contextlib.closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5))


def shelfarr_status(path=SHELFARR_DB, now=None):
    """{(provider, signal): entry} from Shelfarr's provider health table; raises sqlite3.Error / OSError."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = {}
    with _ro(path) as db:
        rows = db.execute("SELECT provider, status, rate_limited_until, last_error, failure_count "
                          "FROM metadata_provider_statuses").fetchall()
    for provider, status, until, error, failures in rows:
        provider = (provider or "").lower().replace(" ", "_")
        limited = False
        if until:
            try:
                limited = _parse_time(until) > now
            except ValueError:
                limited = True
        if limited or (status or "").lower() == "rate_limited":
            signal = "rate"
        elif (status or "healthy").lower() not in ("healthy", "unknown"):
            signal = "auth" if error and AUTH.search(error) else "down"
        else:
            continue
        out[(provider, signal)] = {"count": int(failures or 0), "services": ["shelfarr (provider status)"],
                                   "sample": redact(f"status={status} rate_limited_until={until or '-'} "
                                                    f"{error or ''}")}
    return out


def omnibus_jobs(since: dt.datetime, path=OMNIBUS_DB):
    """{(provider, signal): entry} from Omnibus job failures since `since`; raises sqlite3.Error / OSError."""
    out = {}
    with _ro(path) as db:
        rows = db.execute("SELECT jobType, message FROM JobLog WHERE status LIKE 'FAILED%' AND createdAt >= ?",
                          (int(since.timestamp() * 1000),)).fetchall()
    for job, message in rows:
        line = f"{job} FAILED {message or ''}"
        for key in classify(line, ("comicvine", "metron")):
            entry = out.setdefault(key, {"count": 0, "services": ["omnibus (job log)"], "sample": ""})
            entry["count"] += 1
            entry["sample"] = entry["sample"] or redact(line)
    return out


def _parse_time(text: str) -> dt.datetime:
    value = dt.datetime.fromisoformat(str(text).replace("Z", "+00:00").replace(" ", "T", 1))
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def merge(*parts):
    out = {}
    for part in parts:
        for key, entry in part.items():
            cur = out.setdefault(key, {"count": 0, "services": [], "sample": ""})
            cur["count"] += entry["count"]
            cur["services"] += [s for s in entry["services"] if s not in cur["services"]]
            cur["sample"] = cur["sample"] or entry["sample"]
    return out


def decide(found: dict, state: dict, now: dt.datetime):
    """(to_alert, new_state). An incident alerts when it first appears and again every REMIND_AFTER while it lasts;
    one that disappears is closed (and reported as recovered)."""
    open_before = state.get("open", {})
    open_now, alert, recovered = {}, [], []
    for (provider, signal), entry in sorted(found.items()):
        key = f"{provider}:{signal}"
        prev = open_before.get(key)
        since = prev["since"] if prev else now.isoformat()
        last_alert = prev.get("alerted") if prev else None
        due = last_alert is None or now - _parse_time(last_alert) >= REMIND_AFTER
        open_now[key] = {"since": since, "alerted": now.isoformat() if due else last_alert}
        if due:
            alert.append((key, entry, prev is not None))
    for key in open_before:
        if key not in open_now:
            recovered.append(key)
    return alert, recovered, {"last_run": now.isoformat(), "open": open_now}


SIGNAL_WORDS = {"rate": "rate limited", "auth": "refusing the key (expired or revoked?)", "down": "failing"}


def report(alert, recovered) -> str:
    lines = []
    for key, entry, reminder in alert:
        provider, signal = key.split(":")
        lines.append(f"{'STILL ' if reminder else ''}{provider} is {SIGNAL_WORDS[signal]}: {entry['count']} sign(s) "
                     f"in {', '.join(entry['services'])}")
        if entry["sample"]:
            lines.append(f"    sample: {entry['sample']}")
    for key in recovered:
        lines.append(f"recovered: {key}")
    return "\n".join(lines)


def _duration(text: str) -> dt.timedelta:
    m = re.fullmatch(r"(\d+)([hd])", text)
    if not m:
        raise argparse.ArgumentTypeError("use e.g. 24h or 7d")
    return dt.timedelta(hours=int(m[1]) * (24 if m[2] == "d" else 1))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since", type=_duration)
    args = parser.parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    if args.since:
        since = now - args.since
    elif state.get("last_run"):
        since = _parse_time(state["last_run"]) - dt.timedelta(minutes=1)
    else:
        since = now - dt.timedelta(hours=24)

    logs, unreadable = scan_logs(since)
    parts = [logs]
    for label, read in (("shelfarr db", lambda: shelfarr_status()), ("omnibus db", lambda: omnibus_jobs(since))):
        try:
            parts.append(read())
        except (sqlite3.Error, OSError):
            unreadable.append(label)
    found = merge(*parts)
    alert, recovered, new_state = decide(found, state, now)
    text = report(alert, recovered)
    summary = (f"api-caps: {len(new_state['open'])} open ({', '.join(new_state['open']) or 'none'}), "
               f"{len(alert)} to report, {len(recovered)} recovered"
               + (f", unreadable: {', '.join(unreadable)}" if unreadable else ""))
    print(summary)
    if text:
        print(text)
    if args.dry_run:
        return 1 if new_state["open"] else (2 if unreadable else 0)
    if (alert or recovered) and ALERT.exists():
        subject = "API cap: " + ", ".join(k for k, _e, _r in alert) if alert else "API cap: recovered"
        subprocess.run([sys.executable, str(ALERT), "--subject", subject[:120]], input=text + "\n\n" + summary,
                       text=True, timeout=60)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(new_state, indent=1))
    os.replace(tmp, STATE)
    return 1 if new_state["open"] else (2 if unreadable else 0)


if __name__ == "__main__":
    sys.exit(main())
