#!/usr/bin/env python3
"""Prove an Avrana backup run can rebuild the server, without touching the run or production.

    restore-test.py [RUN_DIR] [--work DIR] [--boot-abs] [--alert] [--no-state] [--repo DIR]

RUN_DIR defaults to the newest complete run under the backup root (AVRANA_BACKUP_ROOT, or
/mnt/avrana_media/.backups/avrana). Runs named *.partial or *.partial-failed are never chosen.

What it does, in order:

  1. fingerprints the run (every path, size and mtime) so it can prove afterwards that the
     test changed nothing
  2. verifies MANIFEST.txt checksums and, for a run downloaded from off-host storage, checks
     its OFFHOST-COMPLETE.json marker against the manifest and the files actually present
  3. checks the 23 expected components, required-artifacts.txt and restore-map.txt
  4. copies every SQLite database to a scratch directory and runs integrity_check on the COPY
  5. tests every .zst archive, lists every tar, and checks the three SQL dumps are complete
  6. checks rebuild prerequisites: compose files, secrets, tunnel credentials, units, fstab,
     Docker data-root, external networks named in BOOTSTRAP.md, Dockerfiles for built images
  7. optionally (--boot-abs) boots a throwaway Audiobookshelf from the restored copy on
     127.0.0.1:18378 with the library mounted read-only
  8. fingerprints the run again and fails if anything differs

Nothing is ever opened in place inside the run directory except for reading bytes. Nothing is
restored onto production. Exit 0 when every check passes, 1 otherwise, 2 for usage errors.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_ROOT = "/mnt/avrana_media/.backups/avrana"

# Directory in the run -> component name used in LAST_RUN.json and required-artifacts.txt.
COMPONENT_DIRS = {
    "arr": "arr", "audiobookshelf": "audiobookshelf", "authentik": "authentik",
    "avrana-audible-connector": "connector", "beszel": "beszel", "bookstack": "bookstack",
    "calibre-web-automated": "calibre-web", "cloudflared": "cloudflared",
    "home-assistant": "home-assistant", "host-docker": "host-docker", "jellyfin": "jellyfin",
    "kern-data": "kern-data", "komga": "komga", "libation": "libation",
    "mylar": "mylar", "omnibus": "omnibus", "sabnzbd": "sabnzbd", "seerr": "seerr",
    "shelfarr": "shelfarr", "shelfmark": "shelfmark", "stack-config": "stack-config",
    "systemd": "systemd", "tracearr": "tracearr",
}
# Components that older runs may still carry. Tolerated, never required.
RETIRED_DIRS = {"kavita"}                     # retired 2026-10-06, Batch 3
# Tables that must exist and hold at least one row; an empty one means the restore is useless.
SQLITE_TABLES = {
    "arr/radarr/radarr.db": ["QualityProfiles", "Movies"],
    "arr/sonarr/sonarr.db": ["QualityProfiles", "Series"],
    "arr/prowlarr/prowlarr.db": ["Indexers"],
    "audiobookshelf/absdatabase.sqlite": ["libraryItems", "users"],
    "calibre-web-automated/app.db": ["user"],
    "calibre-web-automated/calibre-metadata.db": ["books"],
    "home-assistant/home-assistant_v2.db": ["states"],
}
# Dump -> (first-line marker, completion marker, tables that must be created)
SQL_DUMPS = {
    "authentik/authentik.pgdump.zst": (
        "-- PostgreSQL database dump", "-- PostgreSQL database dump complete",
        [r"CREATE TABLE public\.authentik_core_user ", r"CREATE TABLE public\.authentik_flows_flow "], 100),
    "tracearr/tracearr.pgdump.zst": (
        "-- PostgreSQL database dump", "-- PostgreSQL database dump complete",
        [r"CREATE TABLE public\.libraries ", r"CREATE TABLE public\.users "], 5),
    "bookstack/bookstack.sql.zst": (
        "-- MariaDB dump", "-- Dump completed",
        [r"CREATE TABLE `entities` ", r"CREATE TABLE `users` "], 20),
}
# Members that must be inside an archive for a rebuild to work (beyond required-artifacts.txt).
ARCHIVE_MEMBERS = {
    "home-assistant/ha-config.tar.zst": [
        "config/.storage/auth", "config/.storage/core.config", "config/.storage/core.entity_registry",
        "config/.storage/esphome.encryption_keys", "config/configuration.yaml"],
    "jellyfin/jellyfin-config.tar.zst": ["data/jellyfin.db"],
    "cloudflared/cloudflared-config.tar.zst": ["config.yml", "cert.pem"],
}
SYSTEM_UNITS = ["sabnzbd.service", "mylar3.service", "cloudflared-avrana.service",
                "docker.service.d/require-array.conf", "sabnzbd.service.d/require-array.conf",
                "mylar3.service.d/require-array.conf"]
USER_UNITS = ["avrana-backup.service", "avrana-backup.timer", "services-health.service",
              "services-health.timer", "avrana-boot-verify.service", "avrana-boot-verify.timer"]
ABS_IMAGE = ("ghcr.io/advplyr/audiobookshelf@sha256:"
             "180acad33d69c99ed208676465d8edcb268fa46967735579a7810859885b1a8e")
ABS_NAME, ABS_PORT = "abs-restore-test", "18378"
# Written into every off-host copy of a run by offhost-backup.py. Metadata, not a restore payload.
OFFHOST_MARKER = "OFFHOST-COMPLETE.json"


class Report:
    def __init__(self):
        self.passed, self.failed, self.warned = [], [], []

    def ok(self, text):
        self.passed.append(text)
        print(f"PASS  {text}")

    def fail(self, text):
        self.failed.append(text)
        print(f"FAIL  {text}")

    def warn(self, text):
        self.warned.append(text)
        print(f"WARN  {text}")

    def check(self, condition, good, bad):
        (self.ok if condition else self.fail)(good if condition else bad)
        return bool(condition)


def newest_complete_run(root):
    runs = sorted(p for p in pathlib.Path(root).glob("20*") if p.is_dir() and ".partial" not in p.name)
    return runs[-1] if runs else None


def fingerprint(run):
    """Every entry under the run with its type, size and mtime. atime is deliberately ignored."""
    digest, count = hashlib.sha256(), 0
    for base, dirs, files in os.walk(run):
        dirs.sort()
        for name in sorted(dirs) + sorted(files):
            path = os.path.join(base, name)
            info = os.lstat(path)
            rel = os.path.relpath(path, run)
            digest.update(f"{rel}\0{info.st_mode}\0{info.st_size}\0{info.st_mtime_ns}\n".encode())
            count += 1
    return digest.hexdigest(), count


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_manifest(run, report):
    manifest = run / "MANIFEST.txt"
    if not manifest.is_file():
        report.fail("MANIFEST.txt is missing")
        return
    bad = total = 0
    for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^([0-9a-f]{64})\s+\*?(.+)$", line)
        if not match:
            continue
        total += 1
        target = run / match.group(2)
        if not target.is_file() or sha256_file(target) != match.group(1):
            bad += 1
            report.fail(f"manifest: {match.group(2)} is missing or does not match its checksum")
    if total and not bad:
        report.ok(f"manifest: {total} checksums verified")
    elif not total:
        report.fail("manifest: no checksum lines found")


def check_offhost_marker(run, report):
    """A run downloaded from off-host storage carries a completion marker. Verify it; never skip it."""
    marker = run / OFFHOST_MARKER
    if not marker.is_file():
        return                                         # a local run: nothing to verify
    try:
        document = json.loads(marker.read_text(encoding="utf-8"))
        recorded = document["manifest_sha256"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report.fail(f"off-host marker: {OFFHOST_MARKER} is unreadable or has no manifest hash ({exc})")
        return
    manifest = run / "MANIFEST.txt"
    actual = sha256_file(manifest) if manifest.is_file() else None
    report.check(actual is not None and recorded == actual,
                 "off-host marker: manifest hash matches MANIFEST.txt",
                 "off-host marker: MANIFEST.txt is not the one that was uploaded (hash mismatch)")
    if document.get("run") != run.name:
        report.warn(f"off-host marker: written for run {document.get('run')}, directory is named {run.name}")
    files = size = 0
    for base, _, names in os.walk(run):
        for name in names:
            info = os.lstat(os.path.join(base, name))
            if stat.S_ISREG(info.st_mode) and not (base == str(run) and name == OFFHOST_MARKER):
                files += 1
                size += info.st_size
    counted = (document.get("files"), document.get("bytes"))
    if document.get("marker_version", 1) >= 2:
        report.check(counted == (files, size),
                     f"off-host marker: {files} files and {size} bytes, as recorded at upload",
                     f"off-host marker: recorded {counted[0]} files / {counted[1]} bytes, "
                     f"found {files} / {size}")
    elif counted != (files, size):
        # Markers written before version 2 also counted symlinks, which are never uploaded.
        report.warn(f"off-host marker: version 1 marker records {counted[0]} files, {files} present; "
                    "version 1 counts included symlinks and are not enforced")
    else:
        report.ok(f"off-host marker: {files} files and {size} bytes, as recorded at upload")


def check_components(run, report):
    present = {p.name for p in run.iterdir() if p.is_dir()}
    missing = sorted(set(COMPONENT_DIRS) - present)
    extra = sorted(present - set(COMPONENT_DIRS) - RETIRED_DIRS)
    report.check(not missing, f"components: all {len(COMPONENT_DIRS)} expected directories present",
                 f"components: missing {', '.join(missing)}")
    if extra:
        report.fail(f"components: {', '.join(extra)} present in the run but unknown to this test; "
                    "add them to COMPONENT_DIRS, restore-map.txt and required-artifacts.txt")
    empty = sorted(name for name in present & set(COMPONENT_DIRS) if not any((run / name).rglob("*")))
    report.check(not empty, "components: none is empty", f"components: empty {', '.join(empty)}")


def check_required(run, repo, report):
    verifier = repo / "services/backups/verify-required.py"
    listing = repo / "services/backups/required-artifacts.txt"
    if not (verifier.is_file() and listing.is_file()):
        report.fail("required artifacts: verifier or list not found beside this script")
        return
    result = subprocess.run([sys.executable, str(verifier), str(run), str(listing)],
                            capture_output=True, text=True)
    if result.returncode == 0:
        report.ok("required artifacts: " + (result.stdout.strip().splitlines() or ["ok"])[-1])
    else:
        for line in (result.stdout + result.stderr).strip().splitlines()[:20]:
            report.fail(f"required artifacts: {line}")


def read_restore_map(repo):
    rows = []
    for raw in (repo / "services/backups/restore-map.txt").read_text(encoding="utf-8").splitlines():
        if raw.strip() and not raw.startswith("#"):
            parts = [part.strip() for part in raw.split("|")]
            if len(parts) != 4:
                raise ValueError(f"restore-map.txt: malformed line: {raw}")
            rows.append(parts)
    return rows


def check_restore_map(run, repo, report):
    try:
        rows = read_restore_map(repo)
    except (OSError, ValueError) as exc:
        report.fail(f"restore map: {exc}")
        return
    missing = [artifact for _, artifact, _, _ in rows if not (run / artifact).is_file()]
    for artifact in missing:
        report.fail(f"restore map: {artifact} has a documented restore path but is not in this run")
    mapped = {artifact for _, artifact, _, _ in rows}
    unmapped = []
    for path in sorted(run.rglob("*")):
        rel = path.relative_to(run).as_posix()
        if (path.is_file() and rel not in ("MANIFEST.txt", OFFHOST_MARKER) and rel not in mapped
                and not rel.startswith("systemd/") and rel.split("/")[0] not in RETIRED_DIRS):
            unmapped.append(rel)
    for rel in unmapped:
        report.fail(f"restore map: {rel} is in the backup but has no documented restore path")
    covered = {component for component, _, _, _ in rows}
    uncovered = sorted(set(COMPONENT_DIRS.values()) - covered)
    report.check(not uncovered, "restore map: every component has a documented restore path",
                 f"restore map: no entry for {', '.join(uncovered)}")
    renamed = [(a, d) for _, a, d, method in rows if method == "copy-as"]
    for artifact, destination in renamed:
        report.check((run / artifact).is_file() and (run / artifact).stat().st_size > 0,
                     f"renamed on restore: {artifact} -> {destination}",
                     f"renamed on restore: {artifact} is missing or empty")
    if not missing and not unmapped:
        report.ok(f"restore map: {len(rows)} artifacts present, none undocumented")


def sqlite_check(copy, label, tables, report):
    connection = None
    try:
        connection = sqlite3.connect(str(copy))
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            report.fail(f"sqlite: {label} integrity_check: {result[:120]}")
            return
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not names:
            report.fail(f"sqlite: {label} has no tables")
            return
        counts = []
        for table in tables:
            if table not in names:
                report.fail(f"sqlite: {label} is missing table {table}")
                return
            rows = connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            if rows < 1:
                report.fail(f"sqlite: {label} table {table} is empty")
                return
            counts.append(f"{table}={rows}")
        report.ok(f"sqlite: {label} ok ({', '.join(counts) or str(len(names)) + ' tables'})")
    except sqlite3.Error as exc:
        report.fail(f"sqlite: {label}: {exc}")
    finally:
        if connection is not None:
            connection.close()


def check_sqlite(run, work, report):
    found = 0
    for path in sorted(run.rglob("*")):
        rel = path.relative_to(run).as_posix()
        if not path.is_file() or not re.search(r"\.(db|sqlite|sqlite3)$", rel):
            continue
        with open(path, "rb") as handle:
            if handle.read(16) != b"SQLite format 3\0":
                report.fail(f"sqlite: {rel} is not a SQLite database")
                continue
        found += 1
        copy = work / "sqlite" / rel
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, copy)                      # the original is only ever read
        sqlite_check(copy, rel, SQLITE_TABLES.get(rel, []), report)
    report.check(found >= 18, f"sqlite: {found} databases checked on copies",
                 f"sqlite: only {found} databases found, expected at least 18")


def zstd_stream(path):
    return subprocess.Popen(["zstd", "-dc", str(path)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def check_archives(run, work, report):
    for path in sorted(run.rglob("*.zst")):
        rel = path.relative_to(run).as_posix()
        if subprocess.run(["zstd", "-tq", str(path)], capture_output=True).returncode != 0:
            report.fail(f"archive: {rel} fails zstd -t")
            continue
        if rel.endswith(".tar.zst"):
            stream = zstd_stream(path)
            listing = subprocess.run(["tar", "-tf", "-"], stdin=stream.stdout, capture_output=True, text=True)
            stream.wait()
            members = [m[2:] if m.startswith("./") else m for m in listing.stdout.splitlines()]
            if listing.returncode != 0 or not members:
                report.fail(f"archive: {rel} cannot be listed")
                continue
            wanted = ARCHIVE_MEMBERS.get(rel, [])
            absent = [m for m in wanted if m not in members]
            report.check(not absent, f"archive: {rel} ok ({len(members)} members)",
                         f"archive: {rel} lacks {', '.join(absent)}")
            if rel == "cloudflared/cloudflared-config.tar.zst":
                report.check(any(re.fullmatch(r"[0-9a-f-]{36}\.json", m) for m in members),
                             "archive: tunnel credential file present",
                             "archive: no tunnel credential (<uuid>.json) in the cloudflared archive")
        elif rel in SQL_DUMPS:
            first, last, tables, minimum = SQL_DUMPS[rel]
            stream = zstd_stream(path)
            head, tail, created, seen, number = "", "", 0, set(), 0
            for raw in stream.stdout:
                line = raw.decode("utf-8", errors="replace")
                number += 1
                if number <= 5:
                    head += line                         # the marker is within the first lines
                if line.startswith("CREATE TABLE"):
                    created += 1
                    seen.update(p for p in tables if re.match(p, line))
                if line.startswith("-- ") and line.strip() != "--":
                    tail = line
            stream.wait()
            problems = []
            if first not in head:
                problems.append("not a database dump")
            if last not in tail:
                problems.append("TRUNCATED (no completion marker)")
            if len(seen) != len(tables):
                problems.append("expected tables missing")
            if created < minimum:
                problems.append(f"only {created} tables")
            report.check(not problems, f"dump: {rel} complete ({created} tables)",
                         f"dump: {rel}: {'; '.join(problems)}")
        else:
            report.ok(f"archive: {rel} ok")
    # Jellyfin's database only exists inside its archive; pull out that one member and check it.
    archive = run / "jellyfin/jellyfin-config.tar.zst"
    if archive.is_file():
        target = work / "jellyfin"
        target.mkdir(parents=True, exist_ok=True)
        stream = zstd_stream(archive)
        subprocess.run(["tar", "-C", str(target), "-xf", "-", "data/jellyfin.db"],
                       stdin=stream.stdout, capture_output=True)
        stream.wait()
        extracted = target / "data/jellyfin.db"
        if extracted.is_file():
            sqlite_check(extracted, "jellyfin-config.tar.zst:data/jellyfin.db", [], report)
        else:
            report.fail("sqlite: data/jellyfin.db could not be extracted from the Jellyfin archive")


def tar_members(path):
    stream = zstd_stream(path)
    listing = subprocess.run(["tar", "-tf", "-"], stdin=stream.stdout, capture_output=True, text=True)
    stream.wait()
    return {m[2:] if m.startswith("./") else m for m in listing.stdout.splitlines()}


def check_prerequisites(run, repo, report):
    stack = run / "stack-config/stack-config.tar.zst"
    members = tar_members(stack) if stack.is_file() else set()
    composes = sorted(p.relative_to(repo).as_posix() for p in (repo / "services").glob("*/docker-compose.yml"))
    if composes:
        absent = [c for c in composes if c not in members]
        report.check(not absent, f"prerequisites: all {len(composes)} compose files are in stack-config",
                     f"prerequisites: compose files not in the backup: {', '.join(absent)}")
    else:
        report.warn("prerequisites: no compose files found beside this script; skipped the compose check")
    # Every secret-bearing blueprint that Git only holds as a template must be in the backup.
    templates = sorted((repo / "services/authentik/blueprints").glob("*.yaml.template"))
    for template in templates:
        real = f"services/authentik/blueprints/{template.name[:-len('.template')]}"
        report.check(real in members, f"prerequisites: {real} is in the backup",
                     f"prerequisites: {real} (secret-bearing, not in Git) is NOT in the backup")
    # A compose file that reads an env file needs that file to come back from the backup.
    for compose in composes:
        text = (repo / compose).read_text(encoding="utf-8", errors="replace")
        service = compose.split("/")[1]
        example = repo / "services" / service / ".env.example"
        if example.is_file() and re.search(r"\$\{[A-Z_]+|env_file", text):
            report.check(f"services/{service}/.env" in members,
                         f"prerequisites: services/{service}/.env is in the backup",
                         f"prerequisites: services/{service}/.env is NOT in the backup")
    # Images built on the host need their Dockerfile in Git.
    for compose in composes:
        text = (repo / compose).read_text(encoding="utf-8", errors="replace")
        for context in re.findall(r"^\s*(?:build|context):\s*(\S+)\s*$", text, re.M):
            if context in ("build:", "") or context.startswith("#"):
                continue
            base = (repo / compose).parent / context
            if base.is_dir():
                report.check((base / "Dockerfile").is_file(),
                             f"prerequisites: Dockerfile present for {compose} ({context})",
                             f"prerequisites: {compose} builds from {context} but no Dockerfile is in Git")
    # External networks must be created by hand on a new host; BOOTSTRAP.md has to name each one.
    bootstrap = repo / "BOOTSTRAP.md"
    if bootstrap.is_file():
        guide = bootstrap.read_text(encoding="utf-8", errors="replace")
        external = set()
        for compose in composes:
            text = (repo / compose).read_text(encoding="utf-8", errors="replace")
            external.update(re.findall(r"^  ([A-Za-z0-9_.-]+):\s*\{[^}]*external:\s*true", text, re.M))
            for block in re.finditer(r"^  ([A-Za-z0-9_.-]+):\n((?:    .*\n)+)", text, re.M):
                if re.search(r"^\s+external:\s*true", block.group(2), re.M):
                    named = re.search(r"^\s+name:\s*(\S+)", block.group(2), re.M)
                    external.add(named.group(1) if named else block.group(1))
        unnamed = sorted(n for n in external if n not in guide)
        report.check(not unnamed, f"prerequisites: BOOTSTRAP.md names all {len(external)} external networks",
                     f"prerequisites: external networks missing from BOOTSTRAP.md: {', '.join(unnamed)}")
    else:
        report.warn("prerequisites: BOOTSTRAP.md not found; external-network check skipped")
    system = run / "systemd"
    absent = [u for u in SYSTEM_UNITS if not (system / "system" / u).is_file()]
    absent += [u for u in USER_UNITS if not (system / "user" / u).is_file()]
    report.check(not absent, "prerequisites: required system and user units captured",
                 f"prerequisites: units missing from the backup: {', '.join(absent)}")
    fstab = (system / "fstab").read_text(errors="replace") if (system / "fstab").is_file() else ""
    report.check("/mnt/avrana_media" in fstab and "mergerfs" in fstab,
                 "prerequisites: fstab carries the array and the mergerfs union",
                 "prerequisites: fstab is missing the array or mergerfs line")
    root_file = system / "docker-data-root.txt"
    report.check(root_file.is_file() and root_file.read_text().strip().startswith("/"),
                 "prerequisites: Docker data-root recorded", "prerequisites: Docker data-root not recorded")
    for name in ("enabled-system.txt", "enabled-user.txt"):
        report.check((system / name).is_file() and (system / name).stat().st_size > 0,
                     f"prerequisites: {name} captured", f"prerequisites: {name} missing or empty")


def boot_abs(run, work, report):
    """Start a disposable Audiobookshelf on the restored copy. Never touches the live container."""
    if shutil.which("docker") is None:
        report.warn("abs boot: docker not available; skipped")
        return
    config, metadata = work / "abs/config", work / "abs/metadata"
    config.mkdir(parents=True)
    metadata.mkdir(parents=True)
    shutil.copyfile(run / "audiobookshelf/absdatabase.sqlite", config / "absdatabase.sqlite")
    stream = zstd_stream(run / "audiobookshelf/metadata.tar.zst")
    subprocess.run(["tar", "-C", str(metadata), "-xf", "-"], stdin=stream.stdout, capture_output=True)
    stream.wait()
    subprocess.run(["docker", "rm", "-f", ABS_NAME], capture_output=True)
    started = subprocess.run(
        ["docker", "run", "-d", "--name", ABS_NAME, "--user", "1000:1000", "--pull", "never",
         "-e", "TZ=America/Los_Angeles", "-v", f"{config}:/config", "-v", f"{metadata}:/metadata",
         "-v", "/mnt/avrana_media/audiobooks:/audiobooks:ro",
         "-p", f"127.0.0.1:{ABS_PORT}:80", ABS_IMAGE], capture_output=True, text=True)
    try:
        if started.returncode != 0:
            report.fail(f"abs boot: could not start the throwaway container: {started.stderr.strip()[:160]}")
            return
        import time
        import urllib.request
        status = ""
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{ABS_PORT}/status", timeout=3) as response:
                    status = response.read().decode()
                break
            except OSError:
                time.sleep(2)
        report.check('"isInit":true' in status,
                     "abs boot: throwaway Audiobookshelf started from the restored database (isInit=true)",
                     "abs boot: the throwaway server did not initialise from the restored database")
    finally:
        subprocess.run(["docker", "rm", "-f", ABS_NAME], capture_output=True)


def write_state(root, run, report, started):
    state = {
        "status": "ok" if not report.failed else "failed",
        "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run": run.name, "passed": len(report.passed), "failed": len(report.failed),
        "warnings": len(report.warned), "seconds": int((datetime.datetime.now() - started).total_seconds()),
        "failures": report.failed[:20],
    }
    target = pathlib.Path(root) / "RESTORE_TEST_LAST.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def send_alert(repo, run, report):
    sender = repo / "scripts/avrana-alert.py"
    if not sender.is_file():
        return
    body = f"Restore test FAILED for backup run {run.name}.\n\n" + "\n".join(report.failed[:30]) + "\n"
    subprocess.run([sys.executable, str(sender), "--subject", "restore test FAILED"],
                   input=body, text=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", nargs="?")
    parser.add_argument("--work", help="scratch parent directory (default: the system temp directory)")
    parser.add_argument("--repo", default=str(HERE.parents[1]), help="checkout or deployed tree to check against")
    parser.add_argument("--boot-abs", action="store_true", help="also boot a throwaway Audiobookshelf")
    parser.add_argument("--alert", action="store_true", help="send an alert e-mail when the test fails")
    parser.add_argument("--no-state", action="store_true", help="do not write RESTORE_TEST_LAST.json")
    args = parser.parse_args()

    root = os.environ.get("AVRANA_BACKUP_ROOT", DEFAULT_ROOT)
    run = pathlib.Path(args.run) if args.run else newest_complete_run(root)
    if run is None or not run.is_dir():
        print(f"FAIL  no complete backup run found (looked in {root})")
        return 2
    run, repo = run.resolve(), pathlib.Path(args.repo).resolve()
    if ".partial" in run.name:
        print(f"FAIL  {run.name} is an incomplete run; refusing to test it as a recovery set")
        return 2
    started, report = datetime.datetime.now(), Report()
    print(f"restore-test: {run}")
    before = fingerprint(run)
    work = pathlib.Path(tempfile.mkdtemp(prefix="avrana-restore-test.", dir=args.work))
    os.chmod(work, 0o700)
    try:
        if work.resolve().is_relative_to(run):
            print("FAIL  the scratch directory is inside the run being tested")
            return 2
        check_manifest(run, report)
        check_offhost_marker(run, report)
        check_components(run, report)
        check_required(run, repo, report)
        check_restore_map(run, repo, report)
        check_sqlite(run, work, report)
        check_archives(run, work, report)
        check_prerequisites(run, repo, report)
        if args.boot_abs:
            boot_abs(run, work, report)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    after = fingerprint(run)
    report.check(before == after, f"untouched: the run is unchanged by this test ({before[1]} entries)",
                 "untouched: THE RUN DIRECTORY CHANGED DURING THE TEST")
    print(f"\n{len(report.passed)} passed, {len(report.failed)} failed, {len(report.warned)} warnings")
    if not args.no_state and not args.run:
        write_state(root, run, report, started)
    if report.failed:
        print(f"RESTORE TEST FAILED - {run.name}")
        if args.alert:
            send_alert(repo, run, report)
        return 1
    print(f"RESTORE TEST PASSED - {run.name} is recoverable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
