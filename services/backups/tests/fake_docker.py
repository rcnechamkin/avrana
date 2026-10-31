#!/usr/bin/env python3
"""The `docker` of the fixture host (recovery_fixture.py). No Docker, no rclone, no network.

`docker exec` prints a small dump, or a tar of the fixture Home Assistant config. `docker run <rclone image> ...` plays
the rclone verbs offhost-backup.py uses, against a plain directory, and fails on request:
  $FIXTURE_ROOT/fail-rclone holds a verb (copy, cryptcheck, lsf, copyto); that verb exits 1.
  $FIXTURE_ROOT/fail-exec-<container> makes `docker exec` in that container exit 1.
  $FIXTURE_ROOT/hang makes `docker exec` sleep, for the signal test.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(os.environ["FIXTURE_ROOT"])
REMOTE = ROOT / "remote"
VERBS = ("copy", "cryptcheck", "lsf", "copyto")


def remote_path(spec):
    tier, _, rest = spec.partition(":")
    return REMOTE / tier / rest


def run(arguments):
    mounts = {}
    for index, item in enumerate(arguments):
        if item == "-v":
            host, _, tail = arguments[index + 1].replace("\\", "/").rpartition(":")      # strips :ro
            host, _, inside = host.rpartition(":")
            mounts[inside] = host
    start = next(i for i, item in enumerate(arguments) if item in VERBS)
    verb, rest = arguments[start], arguments[start + 1:]
    failing = ROOT / "fail-rclone"
    if failing.exists() and failing.read_text().strip() == verb:
        print(f"fake rclone: {verb} failed password=should-not-reach-mail", file=sys.stderr)
        return 1
    if verb == "lsf":
        spec = rest[-1]
        target = remote_path(spec)
        if not target.is_dir():
            print("directory not found", file=sys.stderr)
            return 3
        if "--dirs-only" in rest:
            print("\n".join(f"{p.name}/" for p in sorted(target.iterdir()) if p.is_dir()))
        elif "-R" in rest:
            print("\n".join(str(p.relative_to(target)) for p in sorted(target.rglob("*")) if p.is_file()))
        else:
            print("\n".join(p.name for p in sorted(target.iterdir()) if p.is_file()))
        return 0
    if verb == "copy":
        source = pathlib.Path(mounts["/data"]) / pathlib.PurePosixPath(rest[0]).name
        shutil.copytree(source, remote_path(rest[1]), symlinks=False, ignore_dangling_symlinks=True, dirs_exist_ok=True)
        return 0
    if verb == "cryptcheck":
        return 0
    if verb == "copyto":
        source = pathlib.Path(mounts["/marker"]) / pathlib.PurePosixPath(rest[0]).name
        shutil.copy(source, remote_path(rest[1]))
        return 0
    return 2


def execute(container, command):
    if (ROOT / f"fail-exec-{container}").exists():
        return 1
    if (ROOT / "hang").exists():
        time.sleep(60)
    if container == "home-assistant":
        if command[0] == "tar":
            return subprocess.run(["tar", "-C", str(ROOT / "ha"), "-cf", "-", "config"]).returncode
        return 0
    sys.stdout.write(f"-- fixture dump of {container}\n")
    return 0


def main():
    arguments = sys.argv[1:]
    if arguments[0] == "info":
        print("/var/lib/docker")
        return 0
    if arguments[0] == "cp":
        shutil.copy(ROOT / "ha-recorder.db", arguments[2])
        return 0
    if arguments[0] == "exec":
        return execute(arguments[1], arguments[2:])
    if arguments[0] == "run":
        return run(arguments[1:])
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
