#!/usr/bin/env python3
"""Compare a checkout of this repository with the deployed tree. Read-only; changes nothing.

    scripts/drift-check.py [--repo DIR] [--live /home/cody/avrana] [--list FILE] [--quiet]

Every tracked file is classified:

  same        byte-identical to the deployed file at the same path
  DIFFERS     deployed file exists and is different            (exit 1)
  MISSING     tracked here, absent in production               (exit 1 unless repo-only)
  repo-only   documentation, tests, templates and host representations that are not deployed
  mapped      deployed under a different path (see MAPPED) and compared there

The file list comes from `git ls-files` in the checkout, or from --list (one path per line) when
the checkout has no .git directory, for example an exported tarball.
"""
import argparse
import hashlib
import pathlib
import subprocess
import sys

# Tracked paths that are deployed somewhere other than <live>/<same path>.
MAPPED = {
    "deploy/host/fstab": "/etc/fstab",
    "deploy/host/sshd_config.d/00-avrana-pubkey-only.conf": "/etc/ssh/sshd_config.d/00-avrana-pubkey-only.conf",
    "deploy/host/systemd/mylar3.service": "/etc/systemd/system/mylar3.service",
    "deploy/host/systemd/sabnzbd.service": "/etc/systemd/system/sabnzbd.service",
    "deploy/host/apt/50unattended-upgrades": "/etc/apt/apt.conf.d/50unattended-upgrades",
    "deploy/host/apt/20auto-upgrades": "/etc/apt/apt.conf.d/20auto-upgrades",
    "deploy/docker/docker-require-array.conf": "/etc/systemd/system/docker.service.d/require-array.conf",
    "deploy/storage/dropins/mylar3-require-array.conf": "/etc/systemd/system/mylar3.service.d/require-array.conf",
    "deploy/storage/dropins/sabnzbd-require-array.conf": "/etc/systemd/system/sabnzbd.service.d/require-array.conf",
}
USER_UNIT_DIR = pathlib.Path.home() / ".config/systemd/user"
# User units are tracked under deploy/ and installed into ~/.config/systemd/user.
USER_UNITS = {
    "deploy/systemd/avrana-backup.service", "deploy/systemd/avrana-backup.timer",
    "deploy/systemd/avrana-backup-trigger.path", "deploy/systemd/avrana-backup-trigger.service",
    "deploy/systemd/services-health.service", "deploy/systemd/services-health.timer",
    "deploy/systemd/omnibus-cache-purge.service", "deploy/systemd/omnibus-cache-purge.timer",
    "deploy/systemd/avrana-offhost.service", "deploy/systemd/avrana-offhost.timer",
    "deploy/systemd/avrana-restore-test.service", "deploy/systemd/avrana-restore-test.timer",
    "deploy/storage/systemd/avrana-boot-verify.service", "deploy/storage/systemd/avrana-boot-verify.timer",
}
# Not deployed anywhere: documentation, tests, templates, representations and repo tooling.
REPO_ONLY_PREFIXES = ("docs/", "tests/", ".git", "deploy/host/", "deploy/ufw/")
REPO_ONLY_SUFFIXES = (".template", ".md", ".env.example")
REPO_ONLY_FILES = {
    ".gitignore", "AGENTS.md", "CLAUDE.md", "README.md", "BOOTSTRAP.md",
    "scripts/review_git_content.py", "scripts/drift-check.py", "scripts/test-storage-log-check.py",
    "deploy/systemd/avrana-cloudflared-restart.path", "deploy/systemd/avrana-cloudflared-restart.service",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked(repo, listing):
    if listing:
        return [line.strip() for line in pathlib.Path(listing).read_text().splitlines() if line.strip()]
    out = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True)
    return out.stdout.split("\n")[:-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=str(pathlib.Path(__file__).resolve().parents[1]))
    parser.add_argument("--live", default="/home/cody/avrana")
    parser.add_argument("--list")
    parser.add_argument("--quiet", action="store_true", help="print only problems and the summary")
    args = parser.parse_args()
    repo, live = pathlib.Path(args.repo), pathlib.Path(args.live)
    counts = {"same": 0, "DIFFERS": 0, "MISSING": 0, "repo-only": 0, "mapped": 0, "unreadable": 0}
    for rel in sorted(tracked(repo, args.list)):
        source = repo / rel
        if rel in MAPPED:
            target, kind = pathlib.Path(MAPPED[rel]), "mapped"
        elif rel in USER_UNITS:
            target, kind = USER_UNIT_DIR / pathlib.Path(rel).name, "mapped"
        else:
            target, kind = live / rel, "same"
        if rel in REPO_ONLY_FILES:
            state = "repo-only"              # never compared (production keeps its own .gitignore)
        else:
            try:
                exists = target.is_file()
                state = (kind if digest(source) == digest(target) else "DIFFERS") if exists else "MISSING"
            except PermissionError:
                state = "unreadable"
        if state == "MISSING" and kind == "same" and (
                rel.startswith(REPO_ONLY_PREFIXES) or rel.endswith(REPO_ONLY_SUFFIXES)):
            state = "repo-only"
        counts[state] += 1
        if state in ("DIFFERS", "MISSING", "unreadable") or not args.quiet:
            shown = f"  ->  {target}" if kind == "mapped" else ""
            print(f"{state:10s} {rel}{shown}")
    print("summary: " + "  ".join(f"{name}={number}" for name, number in counts.items()))
    return 1 if counts["DIFFERS"] or counts["MISSING"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
