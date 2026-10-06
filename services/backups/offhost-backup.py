#!/usr/bin/env python3
"""Copy verified Avrana backup runs to encrypted off-host storage. Add-only: it never removes.

    offhost-backup.py                 upload every complete local run that is not yet off-host
    offhost-backup.py --pin RUN       also keep RUN in the permanent tier
    offhost-backup.py --list          show what is off-host
    offhost-backup.py --check         test configuration and reachability, upload nothing
    offhost-backup.py --dry-run       show what would be uploaded

Design (docs/OFFHOST.md has the reasoning):

  * Each run is an immutable, timestamped directory. It is uploaded once with `rclone copy
    --immutable`. This script contains no command that removes, overwrites or mirrors, so local
    rotation, a wiped array or an emptied backup tree cannot remove anything off-host.
  * Retention is decided by the storage provider, not by this host: a bucket lifecycle rule
    expires the daily tier; the pinned tier has no rule.
  * A run is uploaded only if it is complete: not named *.partial*, its MANIFEST.txt checksums
    verify, and it satisfies required-artifacts.txt. The newest run must also be the one
    LAST_RUN.json reports as ok.
  * After upload, `rclone cryptcheck` compares every file with the encrypted remote copy and the
    remote file count is compared with the local one; only then is OFFHOST-COMPLETE.json written
    into the remote run. A remote run without that marker is not a recovery set. The marker counts
    regular files only. Symlinks are not uploaded and are reported separately.
  * Names and contents are encrypted client-side by rclone crypt. The provider sees ciphertext.
  * The result is written to OFFHOST_LAST_RUN.json, which services-health.sh already checks, and
    a failure sends an alert e-mail.

Configuration is services/backups/rclone.conf (mode 0600, never in Git), created by
offhost-setup.sh. Exit 0 ok, 1 failure, 3 not configured.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import platform
import re
import stat
import subprocess
import sys
import tempfile

REPO =pathlib.Path(os.environ.get("AVRANA_REPO", "/home/cody/avrana"))
SRC = pathlib.Path(os.environ.get("AVRANA_BACKUP_ROOT", "/mnt/avrana_media/.backups/avrana"))
CONF = pathlib.Path(os.environ.get("AVRANA_RCLONE_CONF", REPO / "services/backups/rclone.conf"))
STATE = pathlib.Path(os.environ.get("AVRANA_OFFHOST_STATE", "/mnt/avrana_media/.backups/OFFHOST_LAST_RUN.json"))
DAILY = os.environ.get("AVRANA_OFFHOST_DAILY", "avrana-offsite-daily:")
PINNED = os.environ.get("AVRANA_OFFHOST_PINNED", "avrana-offsite-pinned:")
IMAGE = os.environ.get("AVRANA_RCLONE_IMAGE",
                       "rclone/rclone@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548")
MARKER = "OFFHOST-COMPLETE.json"
RUN_NAME = re.compile(r"^20\d\d-\d\d-\d\dT\d\d-\d\d-\d\dZ$")


def log(text):
    print(f"{datetime.datetime.now(datetime.timezone.utc):%H:%M:%S} {text}", flush=True)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def month_of(run_name):
    return run_name[:7]


def complete_runs(root):
    return sorted(p for p in root.iterdir() if p.is_dir() and RUN_NAME.match(p.name))


def eligible(run_name, last_run):
    """Name-level rule: never an incomplete run, and the newest run must be the one reported ok."""
    if not RUN_NAME.match(run_name):
        return False
    reported = pathlib.PurePosixPath(str(last_run.get("dest", ""))).name
    if reported == run_name:
        return last_run.get("status") == "ok"
    return True


def rclone(arguments, mounts=(), capture=True, stdin=None):
    """Run rclone from the pinned local image. The source tree is only ever mounted read-only."""
    command = ["docker", "run", "--rm", "--pull", "never", "--user", f"{os.getuid()}:{os.getgid()}",
               "--memory", "1g", "-e", "XDG_CACHE_HOME=/tmp", "-e", "RCLONE_CONFIG=/config/rclone.conf",
               "-v", f"{CONF}:/config/rclone.conf:ro"]
    if stdin is not None:
        command.append("-i")
    for host, inside, mode in mounts:
        command += ["-v", f"{host}:{inside}:{mode}"]
    command += [IMAGE] + list(arguments)
    return subprocess.run(command, capture_output=capture, text=True, input=stdin)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(run):
    """Return (regular_files, total_bytes, symlinks). rclone uploads regular files and skips symlinks.

    The only symlinks in a run are systemd/user/*.wants entries. They are not needed off-host:
    systemd/enabled-user.txt records the same thing and BOOTSTRAP.md enables units explicitly.
    """
    files = size = links = 0
    for base, _, names in os.walk(run):
        for name in names:
            info = os.lstat(os.path.join(base, name))
            if stat.S_ISLNK(info.st_mode):
                links += 1
            elif stat.S_ISREG(info.st_mode):
                files += 1
                size += info.st_size
    return files, size, links


def verify_local(run):
    """Return (ok, detail, (regular_files, total_bytes, symlinks)). Reads only."""
    none = (0, 0, 0)
    manifest = run / "MANIFEST.txt"
    if not manifest.is_file():
        return False, "no MANIFEST.txt", none
    verifier = REPO / "services/backups/verify-required.py"
    listing = REPO / "services/backups/required-artifacts.txt"
    result = subprocess.run([sys.executable, str(verifier), str(run), str(listing)], capture_output=True, text=True)
    if result.returncode != 0:
        first = (result.stdout.strip().splitlines() or ["verifier failed"])[0]
        return False, f"incomplete: {first}", none
    listed = 0
    for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^([0-9a-f]{64})\s+\*?(.+)$", line)
        if not match:
            continue
        listed += 1
        target = run / match.group(2)
        if not target.is_file() or sha256_file(target) != match.group(1):
            return False, f"manifest mismatch: {match.group(2)}", none
    if not listed:
        return False, "empty manifest", none
    return True, "ok", inventory(run)


def describe(counts):
    files, size, links = counts
    skipped = f", {links} symlinks not uploaded" if links else ""
    return f"{files} files, {size / 1e6:.0f} MB{skipped}"


def remote_runs(remote):
    """Run name -> True when its completion marker exists.

    The marker is found by listing the run directory, never by addressing the file: a listing is a
    cheap class C call that keeps working when the account's download cap is exhausted. Any error
    is raised, so "could not check" is never mistaken for "no marker".
    """
    listing = rclone(["lsf", "--dirs-only", remote])
    if listing.returncode != 0:
        if "directory not found" in listing.stderr:
            return {}                                  # nothing uploaded to this tier yet
        raise RuntimeError(f"cannot list {remote}: {listing.stderr.strip()[-200:]}")
    found = {}
    for name in (line.strip().rstrip("/") for line in listing.stdout.splitlines()):
        if RUN_NAME.match(name):
            entries = rclone(["lsf", "--files-only", f"{remote}{name}/"])
            if entries.returncode != 0:
                raise RuntimeError(f"cannot list {remote}{name}: {entries.stderr.strip()[-200:]}")
            found[name] = MARKER in (line.strip() for line in entries.stdout.splitlines())
    return found


def marker_document(name, counts, manifest_sha256):
    """The completion marker. files and bytes describe regular files only, which is what is uploaded."""
    files, size, links = counts
    return {"marker_version": 2, "run": name, "files": files, "bytes": size, "symlinks_skipped": links,
            "manifest_sha256": manifest_sha256, "verified": "rclone cryptcheck --one-way",
            "uploaded_at": now(), "host": platform.node()}


def upload(run, remote, counts):
    name = run.name
    log(f"upload {name} -> {remote}{name} ({describe(counts)})")
    copied = rclone(["copy", f"/data/{name}", f"{remote}{name}", "--immutable", "--transfers", "4",
                     "--retries", "3", "--low-level-retries", "10", "--stats", "60s", "--stats-one-line",
                     "--log-level", "INFO"], mounts=[(SRC, "/data", "ro")], capture=False)
    if copied.returncode != 0:
        raise RuntimeError(f"rclone copy of {name} exited {copied.returncode}")
    checked = rclone(["cryptcheck", f"/data/{name}", f"{remote}{name}", "--one-way"], mounts=[(SRC, "/data", "ro")])
    if checked.returncode != 0:
        raise RuntimeError(f"cryptcheck of {name} failed: {checked.stderr.strip()[-200:]}")
    listed = rclone(["lsf", "-R", "--files-only", f"{remote}{name}"])
    present = len([line for line in listed.stdout.splitlines() if line.strip()]) if listed.returncode == 0 else -1
    if present != counts[0]:
        raise RuntimeError(f"{name}: {counts[0]} regular files locally but {present} on the remote; not marked complete")
    marker = marker_document(name, counts, sha256_file(run / "MANIFEST.txt"))
    with tempfile.TemporaryDirectory() as scratch:
        os.chmod(scratch, 0o755)
        path = pathlib.Path(scratch) / MARKER
        path.write_text(json.dumps(marker, indent=1) + "\n")
        os.chmod(path, 0o644)
        placed = rclone(["copyto", f"/marker/{MARKER}", f"{remote}{name}/{MARKER}", "--immutable"],
                        mounts=[(scratch, "/marker", "ro")])
    if placed.returncode != 0:
        raise RuntimeError(f"could not write the completion marker for {name}: {placed.stderr.strip()[-200:]}")
    log(f"verified and marked complete: {name}")


def emit(status, detail, extra=None):
    document = {"status": status, "detail": detail, "at": now(), "source": str(SRC)}
    document.update(extra or {})
    temporary = STATE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, STATE)


def alert(detail):
    sender = REPO / "scripts/avrana-alert.py"
    if sender.is_file() and not os.environ.get("AVRANA_OFFHOST_NO_ALERT"):
        subprocess.run([sys.executable, str(sender), "--subject", "off-host backup FAILED"],
                       input=f"The off-host backup failed at {now()}.\n\n{detail}\n", text=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pin", metavar="RUN", help="also copy this run to the permanent tier")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not CONF.is_file():
        print(f"off-host backup is not configured ({CONF} absent); see services/backups/OFFHOST.md")
        return 3
    if CONF.stat().st_mode & 0o077:
        print(f"refusing to use {CONF}: it must be mode 0600")
        return 1
    import fcntl                                       # Linux only; kept out of module import for tests
    lock = open(STATE.with_suffix(".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another off-host run is in progress")
        return 1

    if args.list or args.check:
        for label, remote in (("daily", DAILY), ("pinned", PINNED)):
            try:
                runs = remote_runs(remote)
            except RuntimeError as exc:
                print(f"{label}: {exc}")
                return 1
            print(f"{label} tier ({remote}): {len(runs)} runs")
            for name in sorted(runs):
                print(f"  {name}  {'complete' if runs[name] else 'NO COMPLETION MARKER'}")
        return 0

    try:
        if not SRC.is_dir():
            raise RuntimeError(f"backup tree missing: {SRC}")
        last_run = json.loads((SRC / "LAST_RUN.json").read_text()) if (SRC / "LAST_RUN.json").is_file() else {}
        local = [run for run in complete_runs(SRC) if eligible(run.name, last_run)]
        if not local:
            raise RuntimeError("no complete local run to upload")
        newest = complete_runs(SRC)[-1]
        if newest not in local:
            raise RuntimeError(f"newest local run {newest.name} is not reported ok by LAST_RUN.json; nothing promoted")
        remote = remote_runs(DAILY)
        uploaded, skipped = [], []
        for run in reversed(local):                      # newest first, then catch up
            if remote.get(run.name):
                continue
            good, detail, counts = verify_local(run)
            if not good:
                skipped.append(f"{run.name} ({detail})")
                if run == newest:
                    raise RuntimeError(f"newest run {run.name} failed local verification: {detail}")
                continue
            if args.dry_run:
                log(f"would upload {run.name} ({describe(counts)})")
                continue
            upload(run, DAILY, counts)
            uploaded.append(run.name)
        if args.pin:
            target = SRC / args.pin
            good, detail, counts = verify_local(target) if target.is_dir() else (False, "no such run", (0, 0, 0))
            if not good:
                raise RuntimeError(f"cannot pin {args.pin}: {detail}")
            if not remote_runs(PINNED).get(args.pin) and not args.dry_run:
                upload(target, PINNED, counts)
        if args.dry_run:
            return 0
        final = remote_runs(DAILY)
        if not final.get(newest.name):
            raise RuntimeError(f"newest run {newest.name} is not complete on the remote after upload")
        complete = sorted(name for name, done in final.items() if done)
        detail = f"runs={len(complete)} newest={newest.name}"
        for line in skipped:
            log(f"not promoted: {line}")
        log(f"ok: {detail}; uploaded this run: {', '.join(uploaded) or 'none (already off-host)'}")
        emit("ok", detail, {"newest": newest.name, "remote_runs": len(complete), "uploaded": uploaded,
                            "not_promoted": skipped})
        return 0
    except (RuntimeError, OSError, ValueError) as exc:
        log(f"FAIL {exc}")
        emit("failed", str(exc)[:300])
        alert(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
