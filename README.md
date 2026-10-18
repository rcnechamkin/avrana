# Avrana

Avrana is a single-host media and home server (`avrana`): Jellyfin, the arr stack,
Audiobookshelf, Calibre-Web, Komga, Authentik single sign-on, Home Assistant and supporting tools, in 22
Docker Compose projects plus three host services, published through a Cloudflare tunnel.

**This repository is the canonical source of truth** for how the host is built and operated (owner
decision, 2026-10-03). It replaces the older `rcnechamkin/Kern-Ecosystem` repository, which is archived,
and the BookStack wiki, which is retired and preserved under `docs/archive/bookstack/`.

If the host disappeared, this repository plus one backup run plus the secrets in 1Password are enough to
rebuild it: **[BOOTSTRAP.md](BOOTSTRAP.md)**.

## Layout

The tree mirrors the deployed layout at `/home/cody/avrana`.

| Path | Contents |
|---|---|
| `BOOTSTRAP.md` | Bare-metal rebuild guide |
| `services/<name>/` | One Compose project each: `docker-compose.yml`, `.env.example` (names only), source and Dockerfile for locally built images |
| `services/authentik/blueprints/` | Authentik configuration as code; secret-bearing blueprints are `.template` files |
| `services/backups/` | Backup, completeness gate, restore test, off-host copy |
| `scripts/` | Health check, alerting, storage checks, content gate, drift check |
| `deploy/` | systemd units, storage and Docker guards, host configuration representations, staged firewall |
| `docs/` | Architecture, operations, services, incidents, audits, the BookStack archive |
| `tests/` | Offline tests (`python3 tests/run_offline.py`) |

Not in Git, by design: secrets, `.env` files, application databases and state, media, backups, recovery
evidence. `docs/SECRETS.md` lists where each secret lives.

## Working on it

Read [AGENTS.md](AGENTS.md) first. In short:

- Change files here, review, commit, then deploy one service at a time ([docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).
- `python3 scripts/review_git_content.py --staged` must pass before every commit.
- `scripts/drift-check.py`, run on the host, shows where production differs from Git.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) is the local workflow: one command for all offline tests, fixture rules, worktrees.
- `docs/provenance/` records where every file in the initial import came from and what was left behind.

## Start here

[Architecture](docs/ARCHITECTURE.md) · [Services](docs/SERVICES.md) · [Operations](docs/OPERATIONS.md) ·
[Storage](docs/STORAGE.md) · [Backups](services/backups/README.md) · [Off-host](services/backups/OFFHOST.md) ·
[Security](docs/SECURITY.md) · [Incidents](docs/incidents/README.md) · [Decisions](docs/DECISIONS.md) ·
[Roadmap](docs/ROADMAP.md)
