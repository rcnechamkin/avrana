# 2026-09-20: most of /home/cody deleted

Summary written 2026-10-04 from the October assessment. The detailed recovery record is
[`../findings/2026-09-20-recovery.md`](../findings/2026-09-20-recovery.md); the evidence is on the host
under `/mnt/avrana_media/recovery-20260920/` (`INCIDENT-REPORT.md`, `RECOVERY-LEDGER.md`).

## What happened

An AI agent session, driven from the laptop over SSH as `cody`, was trying to find the BookStack API
token. It searched the home directory for a file containing the variable name and **sourced the first
match as a shell script**:

```
f=$(grep -rlI "BOOKSTACK_TOKEN_SECRET" ~/ /opt ... | head -1); set -a; . "$f"
```

The first match was not an environment file. It was an agent transcript (a JSON-lines log) that
contained the string. Executing it as shell ran fragments of text recorded in that log, and most of
`/home/cody` was deleted, including the production tree, application state on the root disk and
`~/.ssh/authorized_keys`. The media array, Docker's data-root and the nightly backups were on the other
disk and survived.

## Recovery

Services were rebuilt from the nightly backup taken a few hours earlier (kept since as the golden backup
`2026-09-20T09-34-23Z`, pinned with `.keep`), from an LVM snapshot of the root volume taken after the
deletion, and from the GitHub copy of `Kern-Ecosystem` (commit `adbc4b5`). Work continued until
2026-09-28.

Not recovered: Jellyfin artwork (excluded from the backup at the time), documentation that existed only
in the working tree, the BookStack API token.

## Causes

1. The agent ran as the owner of everything, with no boundary between it and production.
2. A credential was hunted for by searching the disk, and a file found by search was executed.
3. Nothing that mattered was off the host, and the Git copy was two days old.

## Controls since

| Control | State (2026-10-04) |
|---|---|
| Never search for credentials; never `source` a found file | Written into `AGENTS.md` and `docs/SECRETS.md` |
| Backup covers artwork, tunnel credentials, units, host service state | Done (24 components, completeness gate) |
| Failed or partial backups cannot rotate out good ones | Done |
| Health and backup failures alert by e-mail | Code done; delivery waits for the SMTP credential |
| Off-host encrypted backup | Batch 2 |
| Canonical Git repository that matches production | Batch 2 (this repository) |
| SSH key-only | Done 2026-10-04 |
| Separate low-privilege account for agents | Approved, not implemented |
