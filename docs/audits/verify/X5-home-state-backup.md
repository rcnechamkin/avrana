# X5: independent verification of S-04 / S-11 (Home state backup, repo compose volume)

Fix under review: branch `fix/rc2-home-state-backup`, commit `320859f` on `2cb228f` (worktree `avrana.wt-rc2-s04`).
Verifier: an independent agent. It edited nothing in the fix, ran no ssh or Docker, and never ran the backup script.
Scratch work: `C:\Users\cnech\AppData\Local\Temp\claude\C--Users-cnech-Projects\aa646cb8-53b8-47f2-ae01-c8adcaf3826c\scratchpad\verify-x5\`.

## Verdict: ACCEPT, with required follow-ups (R1, R2) before or in the PR

The fix closes both defects on avrana as it is today: Home bindings are on, and the deploy script will not run
without `state/` and a non-empty bindings file. The allowlist, the required-artifacts lines and the compose line are
correct. All suites pass, and both new backup tests fail on the baseline. My earlier claim that "nullglob keeps the
archive correct when `state/` is absent" is **false**; details in finding 1. It cannot fire on avrana now, and a host
with bindings off fails the completeness gate anyway, so I do not block on it.

## 1. Backup allowlist (`services/backups/avrana-backup.sh:460`)

- The new line sits inside the existing `for p in ... ; do` list, between recyclarr and `services/backups`. Paths
  are stored relative to `$REPO`, so archive members are `services/avrana-home/docker-compose.beta-live.yml` and
  `services/avrana-home/state/...`. These match the required-artifacts strings exactly (verify-required.py does an exact
  `parts[3] in members` check).
- **nullglob does NOT protect these two entries.** Both are literal paths with no wildcard, and nullglob only drops
  patterns that contain a wildcard (the script itself says so at `:512`). An absent `state/` or compose file stays in
  `paths`, and GNU tar exits 2 with "Cannot stat". The script runs `set -uo pipefail` (`:20`), so the
  `tar | zstd` pipeline fails and the **whole stack-config component** is recorded `fail stack-config "tar"`, which
  makes the run `.partial-failed`. I reproduced this with GNU tar 1.35 under the same `set -uo pipefail` and the same
  loop: the pipeline returned rc `2 0` and the result was fail, then good once both paths existed. On avrana both exist
  (`deploy-home-beta.sh` exits 4 without `$LIVE/state` and exits 7 without the bindings file), so there is no regression
  there. The same property already applies to `recyclarr/config/state`, `kern_secrets` and others.
- Nothing else is newly swept in. `services/avrana-home/secrets` and `beta-live.env` were already caught by
  `services/*/secrets` and `services/*/*.env`. Home has no `profiles/`. `state/` holds only Home-written files:
  `identity_bindings.json` (0600), `identity_bindings.json.lock` (an empty 0600 flock target, harmless to archive or
  restore; flock state is not in the file), `komga_member_keys` (member API keys; the archive is already chmod 600 and
  secret-dense) and, when switched on, `members.sqlite3`.
- Readability: the container runs as `USER 1000:1000` (Dockerfile.live:22), and the compose comment says `./state`
  is uid 1000, mode 0700. The backup runs as cody. That works if cody is uid 1000, which the runbooks' `--user 1000:1000`
  suggests; I did not verify it on the host.
- Small risks, not blocking. (a) `identity_bindings.py` writes through `mkstemp` + `os.replace` in `state/`. A tar
  that walks the directory during a write can see a vanished temp file and exit 1, which fails stack-config for that
  night (rare: writes happen only on first sign-in or binding changes). (b) When the member store is on,
  `members.sqlite3` is tarred live rather than copied with the SQLite online-backup API. README says "SQLite databases
  are copied with the online backup API", which would then be untrue for this file.

## 2. required-artifacts.txt

- Both new lines use the existing 4-field `component|member|archive|name` form, the same as the neighbouring lines.
  Non-comment requirement lines: 180 at baseline, 182 now.
- Host with bindings **on** (avrana): the file exists (the deploy guard enforces it), so the gate passes.
- Host with bindings **off**, or Home never set up: `identity_bindings.json` is absent. The nightly gate
  (`avrana-backup.sh:616-628`) then fails the stack-config component, every run becomes `<ts>.partial-failed` with an
  alert e-mail, and `offhost-backup.py` will not promote it. This is a **standing requirement that Home bindings are on
  wherever this backup runs**. That is acceptable for avrana but should be stated (R1). If `state/` itself is missing,
  the failure shows up as "tar" rather than "required artifact missing" (finding 1), which is a misleading diagnosis.
- Not requiring `komga_member_keys` is correct: it exists only when Komga provisioning is on.

## 3. Compose (`services/avrana-home/docker-compose.beta-live.yml:99`)

- The new active line is byte-identical to the quoted live line: `    volumes: ["./state:/var/lib/avrana-home:rw"]`
  (4 spaces, double quotes, `:rw`, LF, no CR; file is ASCII). It sits inside the service, before `read_only`.
- `read_only: true` plus a tmpfs `/tmp` plus one rw bind mount is the intended hardening: the root filesystem stays
  read-only and `./state` is the only writable path. That is consistent.
- Active-line diff, baseline to fix, using the deploy script's own `active()` normaliser (extracted verbatim): the
  **only** new active line is `    volumes: "./state:/var/lib/avrana-home:rw"`. The sets of active `- KEY=` environment
  lines are identical (empty diff). No request, provisioning, member-store or Komga-keys switch changed.
- Deploy behaviour. I ran `active()` and `comm -23` from `deploy-home-beta.sh:52-66`:
  - against a simulated live file (baseline plus that volume line active): `new=[]`, so the script proceeds past
    the exit-3 check to export, link, `cp` the LIVE compose over the exported one, build and dry run. The repo copy is
    never used at runtime.
  - against a live file without the line: `new=[    volumes: "./state:/var/lib/avrana-home:rw"]`, so it would exit 3.
    That is correct, and per the orchestrator it does not happen on avrana.
- `tests/test_deploy_home_beta.py` and `tests/test_deploy_home_beta_bindings.py` (6 ran, 0 failed) cover **only the
  REMOTE half** (dry run, apply, plan guard) and the bindings guard. **No test exercises the exit-3 "repo enables
  something new" check**, for `volumes:` or any other line. The simulation above is the only evidence.
- `test_beta_live_static.py` adds a check that the volume line is active whenever bindings are on, and that there is
  exactly one `volumes:` key. That is fine.

## 4. Tests run (worktree root, `.venv-media` Python, `-B`)

| Suite | Result |
|---|---|
| `unittest discover -s services/backups/tests -p "test_*.py"` | 32 ran, OK (1 skipped) |
| `discover -s services/avrana-home/tests -t services/avrana-home -p test_beta_live_static.py` | 11 ran, OK |
| `tests.test_deploy_home_beta tests.test_deploy_home_beta_bindings` | 6 ran, OK |
| `tests.test_home_static_export` | 8 ran, OK |
| `tests.test_ci_workflow` | 14 ran, OK (1 skipped) |

Baseline check (scratch copies of `services/backups`):
- Baseline `avrana-backup.sh` with the fixed list: **both** new tests FAIL (the compose path is not in the matched
  set and not covered by the allowlist).
- Fixed script with the baseline list: `test_required_home_members_are_covered_by_the_allowlist` FAILS (the
  compose file is not required).

Test gap: `test_home_compose_record_and_state_are_collected` builds a tree where `state/` exists. It never covers
the absent-path case from finding 1. The test's glob-based matcher also differs from bash, because Python's `glob`
drops a missing literal path.

## 5. Docs

- `identity-bindings.md` section 4 and `m0-offhost-backup-restore.md` step 6 describe the archive in the present tense
  ("the nightly stack-config archive holds services/avrana-home/state/"). That becomes true only after the live
  `/home/cody/avrana/services/backups/avrana-backup.sh` and `required-artifacts.txt` are synced **and** one nightly
  run has finished (plus one off-host upload for the m0 check). Every run before that lacks these members, and the
  m0 grep would print nothing. Neither runbook says so. **No PR exists yet** (`gh pr list --head
  fix/rc2-home-state-backup`: none). The PR body must say this.
- Other text that is now stale: `restore-map.txt:63` still describes stack-config as "secrets only ... everything
  else comes from Git", but the live Home compose and `state/` do not come from Git. `services/backups/README.md:6`
  still says "180 files and archive members" (now 182).

## Required follow-ups

- **R1 (PR body, required).** State that (a) the backup contains Home state only after the owner syncs the live
  backup script and list on avrana and one nightly run has completed (and been uploaded, for the m0 check); (b) from
  that sync on, every nightly run fails completeness (`.partial-failed`, alert, no off-host promotion) on any host where
  `services/avrana-home/state/identity_bindings.json` is absent; (c) the commit changes the tracked
  `docker-compose.beta-live.yml`, so a `git pull` in `~/avrana`, where that file carries live edits, will refuse to
  merge it. The owner must reconcile that file or sync the backup files another way. I could not check ~/avrana's git
  state without ssh.
- **R2 (docs, required, one sentence each).** Add the "only for runs after the sync" caveat to m0 step 6, and to
  identity-bindings section 4 step 1 (point to an older golden or manual copy if the newest run predates it).

## Recommended (non-blocking)

- Guard the two new literal paths with `[[ -e "$p" ]] || continue` (the `backup_host_docker` pattern), so an absent
  `state/` is reported by the completeness gate as "required artifact missing: identity_bindings.json" rather than as a
  whole-component "tar" failure. Add a test with `state/` absent.
- Update `restore-map.txt:63` (stack-config also carries Home's live compose and `state/`; restore them to
  `services/avrana-home/`) and the README count (182).
- When the member store is switched on, copy `members.sqlite3` with `sqlite_backup` (as other SQLite files are)
  rather than live tar.
- Add a test for the deploy script's local exit-3 check (the `active()` + `comm` logic), including a `volumes:` line.

## Re-check: commit 84846cb (diff 320859f..84846cb)

**Verdict: ACCEPT.** R2 and the absent-path tar failure are fixed. R1 lives in the PR body, which does not exist yet,
so it is still open. One new follow-up, F1, is below.

- **Guard placement.** `[[ -e "$p" || -L "$p" ]] || continue` is the first statement inside the `for p in ...; do`
  loop of `backup_stack_config`, before `paths+=`. A path present on disk always passes `-e`, including every match
  from the `services/*/...` globs (nullglob only yields matches that exist). A dangling symlink is kept through `-L`,
  and tar archives the link itself, so nothing present is dropped. I confirmed this by test:
  `test_present_home_paths_are_listed` passes, and with all paths present the list matches the pre-guard loop.
- **The new tests run the real loop under bash.** They extract the loop from the script and run it against a
  temporary tree. In a scratch copy with only the guard line deleted (checked by diff),
  `test_absent_home_paths_are_skipped_not_passed_to_tar` **fails**: the absent `services/avrana-home/state` and
  compose path are listed, along with `kern_secrets`, `recyclarr/config/state` and the others.
  `test_present_home_paths_are_listed` passes both with and without the guard. That is expected: it protects against
  dropping too much, not against the bug.
- **Suites.** Backups: 34 ran, OK (1 skipped). The 4 StackConfig tests all pass, so the bash-driven ones are not
  skipped here. `tests.test_deploy_home_beta`: 3 ran, OK.
- **Docs.** Both caveats (identity-bindings section 4 step 1, m0 step 6) say only true things: Home state is present
  only in runs made after the live script and list are synced, and after the sync a host without bindings fails
  completeness. The README count is now 182, matching 182 non-comment lines. The restore-map stack-config line now
  names Home's live compose and `state/`, and it still has 4 fields.
- **R1 is still open.** There is no PR yet. Its body must still carry R1(a) to R1(c), including the `git pull` in
  `~/avrana` refusing to merge because the tracked compose file has live edits.
- **F1 (new, small, recommended before merge).** The guard applies to **every** literal entry, not just the two Home
  ones. `kern_secrets` and `services/recyclarr/config/state` have **no** line in `required-artifacts.txt` (0 matches
  each). Before this commit, losing either made the run fail loudly through tar exit 2. Now they would be skipped
  silently, and the run stays `ok`. The other literal entries are covered by the completeness check (.env,
  .gitignore, deploy/, scripts/, olivetin, recyclarr yml files, authentik/blueprints). Fix by either limiting the
  guard to the two Home paths, or adding a `mincount` or `member` requirement for `kern_secrets/` and
  `services/recyclarr/config/state/`.
