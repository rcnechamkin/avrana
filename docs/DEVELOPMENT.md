# Development workflow

How to change this repository and prove the change locally, with no access to the production host.
Production boundaries are in [AGENTS.md](../AGENTS.md); deployment is in [DEPLOYMENT.md](DEPLOYMENT.md).
Nothing in this file touches `avrana` (the host), the Cloudflare tunnel, Backblaze or any live service.

## Prerequisites

- Python 3.12 (`python3` on Linux and macOS, `python` on Windows). Standard library only: there is no
  `requirements.txt`, no virtualenv and nothing to install.
- Git 2.30 or later. On Windows use Git for Windows; write files with LF endings
  (`git config core.autocrlf false`) and mark scripts executable with
  `git update-index --chmod=+x <path>`, because NTFS does not carry the mode.
- A text editor. Nothing else: no Docker, no network, no credentials.

## Run everything

```sh
python3 -B tests/run_offline.py
```

Exit 0 means every offline suite passed. Output includes lines starting `FAIL` from the backup tooling
tests, which assert that bad input is rejected; the exit code is what counts. It takes a few seconds.
`-B` keeps `__pycache__` out of the tree.

What it runs, in order (`tests/run_offline.py` is the source of truth):

| Step | Covers |
|---|---|
| `unittest discover` over `tests/` for `test_*.py` | content gate (`scripts/review_git_content.py`), Audible schema, the CI workflow checks |
| `services/avrana-imax-verify/tests/test_classify.py` | IMAX classification on synthetic cases |
| `services/avrana-kindle-connector/tests/test_kindle.py` | address and group logic; the live-gating checks that call `curl(` are skipped by design |
| `unittest discover` over `services/backups/tests/` | restore test, completeness gate, off-host tooling, with fake rclone and zstd |

## Run one suite

```sh
python3 -B -m unittest discover -s tests -p "test_review_git_content.py" -v
python3 -B -m unittest discover -s tests -p "test_ci_workflow.py" -v
python3 -B -m unittest discover -s services/backups/tests -p "test_restore_tooling.py" -v
python3 -B -m unittest discover -s services/avrana-imax-verify/tests -p "test_server.py" -v
python3 -B services/avrana-imax-verify/tests/test_classify.py
```

One test: add `-k name` to a `unittest discover` command.

Not run by `run_offline.py` today (a gap, not a design): `services/avrana-imax-verify/tests/test_server.py`
(standard library, passes; run it with the command above), `scripts/test_epub_audiobook_matcher.py` and
`scripts/test-storage-log-check.py` (standard library), the Audible connector tests under
`services/avrana-audible-connector/connector/tests/` (need `pytest` and `fastapi`), and
`services/calibre-web-automated/tests/` (needs the patched image). **Do not run
`scripts/test_offboard.py` as a local check**: it invokes `/home/cody/avrana/scripts/offboard.py`, a host path.

## Fixtures: synthetic only

- Invent data. Names, e-mail addresses, titles, paths, IDs and tokens in a fixture must be obviously
  fake (`member-a`, `example.org`, `test-token-not-real`) or built in the test from `tempfile` and
  `sqlite3 :memory:`.
- Never copy into the repository, a fixture, a test, an issue or a chat with an external AI model: production
  media files or file names, API keys, OIDC secrets, session cookies, invitation tokens, rclone or SMTP
  settings, account or member data, e-mail addresses, Kindle addresses, playback or reading history,
  request history, Authentik events, database files, backup runs, logs.
- Recorded API responses (for later adapter contract tests) are rewritten by hand to synthetic values
  before they are committed. A recording of a real member's data is not a fixture.
- Passwords in fixtures must be nonsense strings that cannot be mistaken for a real one; the content gate
  fails on credential-shaped assignments, which is also a prompt to look again.
- Importing a service module is allowed; running it against `/home/cody/...` or any live URL is not.
  Use temporary directories and monkeypatch the root and network helpers, as the existing suites do.

## Add a suite so `run_offline.py` picks it up

Two routes, in this order of preference:

1. **A file under `tests/` named `test_*.py`.** It is discovered with no other change. Load the code under
   test by path, as `tests/test_review_git_content.py` does, or by inserting its directory on `sys.path` as
   `services/avrana-imax-verify/tests/test_server.py` does. Use `unittest`, `tempfile`, in-memory SQLite.
2. **A suite next to a service** (`services/<name>/tests/`). `run_offline.py` lists service suites
   explicitly, so a new one is not run until a line is added there. That file is owned by the
   change that introduces the suite: add the `subprocess.run([sys.executable, '-B', ...])` line in the same
   pull request and show the new suite in the run's output.

Rules for any suite: standard library, no network, no Docker, no reading outside the repository and
temporary directories, no dependence on the current directory, no wall-clock sleeps beyond a second or two,
deterministic under any time zone and locale, and a clear failure message that never prints a secret.
Behaviour that Linux has and Windows does not (symlinks, `fcntl`, file modes) is guarded with
`unittest.skipUnless`, as in `test_server.py`.

## Commit gates

```sh
git status
git diff
python3 -B tests/run_offline.py
git add <exact paths>
git diff --cached --check
python3 -B scripts/review_git_content.py --staged
```

Stage exact paths, never `git add -A` or `git add .`. The content gate reads the staged blobs, rejects
credential patterns, databases, archives, media and oversized files, and reports "0 blocked files" when
clean; it does not replace reading your own diff for personal data. Commit locally; push and open a pull
request only when the owner has asked. No force push. End agent-authored commits with the
`Co-Authored-By` line the session gives you.

After D-8 is approved and the workflow is merged, `.github/workflows/offline-tests.yml` runs
`tests/run_offline.py` (twice, the second time with networking removed) and the content gate on every pull
request. It has no secrets and no deployment step, and `tests/test_ci_workflow.py` keeps it that way. CI is
a second opinion; the local run before you commit is still the gate.

Known CI gap (AVR-386): the runner has no PyYAML and D-8 allows no `pip`, so the G1 compose-declaration
tests skip in CI (12 on `main`, more with the bypass-path suite). `run_offline.py` prints a WARN when that
happens; with `AVRANA_REQUIRE_YAML=1` it fails instead. Closing the gap is an owner decision: amend D-8 to
install one hash-pinned PyYAML wheel and set that variable in the workflow, or accept the skip and keep
running the suite locally with PyYAML before merging G1 changes.

## One worktree per issue

Keep `main` clean and give each issue its own checkout next to it:

```sh
git worktree add ../avrana.wt-avr-352 -b avr-352-portal-authz-suite main
cd ../avrana.wt-avr-352
```

- Directory `../avrana.wt-<issue>`, branch `avr-<number>-<short-slug>` from current `main`. Operations work
  that is not a numbered issue uses a short word (`avrana.wt-ops`).
- Work, test and commit inside that directory only. Two agents never share a worktree or a branch.
- A branch carries one reviewable change. Rebase onto `main` before review if `main` moved.
- Remove it when merged: `git worktree remove ../avrana.wt-avr-352`, then `git branch -d avr-352-portal-authz-suite`.
- `git worktree list` shows what exists. Never run Git inside the production tree
  (`/home/cody/avrana` is not a checkout).

## What is deliberately not runnable locally

| Not run here | Why | Where it is done instead |
|---|---|---|
| Anything that needs the host: `scripts/services-health.sh`, `scripts/drift-check.py`, `deploy/storage/boot-verify.sh`, `deploy/docker/verify-baseline.sh`, `deploy/ufw/verify-firewall.sh` | They read production state | The owner or an approved session on `avrana` |
| `docker compose config`, `up`, image builds | Needs Docker and the real `.env` files; compose changes need owner approval to apply | Dry-run on the host (`DEPLOYMENT.md`) |
| Authentik blueprint application and flows | Needs the running worker and database | Owner, after deploying the file |
| `restore-test.py` against a real backup run, `--boot-*` boot tests | Needs a run directory (contains secrets), zstd, Docker | Weekly timer on the host; `docs/runbooks/m0-offhost-backup-restore.md` |
| Off-host upload, B2, rclone | Live account and credentials | The nightly timer; the owner |
| Sending e-mail, SMTP2GO | Live credential | `docs/runbooks/m0-smtp2go-email.md` |
| Live gating checks in the Kindle tests | They call containers over HTTP | Skipped by `run_offline.py` |
| systemd units, ufw, fstab, mounts | Host state | `deploy/` files are reviewed as text only |
| Browser, accessibility and screenshot checks | Planned under `tests/ui/` (Sprint 1, S1-5) as development tools; not in the repository yet | Run locally once the harness lands, against fixture renders, never production |

If a change cannot be proved locally, say so in the pull request, list the owner-run verification and the
rollback, and leave deployment to the owner.
