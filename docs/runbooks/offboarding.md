# Runbook: removing a member (offboarding)

Status: **DRAFT for owner review** (AVR-361 S1-6, executed under AVR-366). Written from the repository only.
Nothing in this runbook was run. Every step marked **UNGROUNDED** has no procedure in the repository and
must be worked out, then written down here, during the rehearsal on a disposable account.

Audience: the owner, at a terminal on the production host. Agents do not run any of this
(`AGENTS.md`, `docs/SECURITY.md:17`: do not execute offboarding tooling merely to test it).

## Packet

1. **Approval requested.** Do you approve: (a) running `scripts/offboard.py <username> --apply` against one
   named member, which disables that member's Jellyfin and Audiobookshelf accounts and sets their Authentik
   user inactive; (b) only if that member asked for data removal, running it again with `--purge`, which
   deletes the Jellyfin, Seerr, Audiobookshelf and Authentik users and cannot be undone; (c) restarting the
   `authentik-ldap` outpost container; (d) deleting accounts by hand in Komga, the ebook library, Shelfarr
   and Omnibus, and deleting the member's `profiles/<profile_id>` directory of the Audible connector on the
   host (a bind-mounted directory, irreversible)? Answer yes or no for each lettered action.
2. **Why it is needed and what it unblocks.** Deleting the Authentik user does not end access: Jellyfin keeps
   its own copy of the password and other services keep local accounts. Without this procedure a former
   member keeps working logins. It unblocks honouring a member's request to step away or to have data
   removed (AVR-366, decision D-17).
3. **Blast radius and downtime.** One member's accounts across Authentik, Jellyfin, Seerr, Audiobookshelf,
   and by hand Komga, the ebook library, Shelfarr, Omnibus and the Audible connector profile. The
   `authentik-ldap` restart briefly interrupts ebook library sign-ins for every member. A wrong match
   (the tool matches by username, e-mail or display name) would act on the wrong person; the dry run
   exists to catch that. No library or media folder is touched.
4. **Preconditions.** Your approval for each lettered action; the request came from the member or you
   decided; the username matches `[A-Za-z0-9._-]+` and is not a protected account; the dry run output was
   read and each match is the right person; the member's e-mail address noted privately; a disposable
   account rehearsal done once (section "Rehearsal"); a quiet hour for the outpost restart.
5. **Verification.** The tool's own PASS lines are not enough (section "Verify"). Read-only checks in each
   service's admin UI, a second `--audit` with counts compared, and an independent look at the Authentik
   user list. Nothing is believed that the Verify checklist did not confirm.
6. **Rollback.** Deactivation is reversible: set the user active again in Authentik, clear "Disable this
   user" in Jellyfin, set the user active in Audiobookshelf (section "Reversing a deactivation"). There is
   no rollback for a purge, for a manual account deletion or for deleting a connector profile directory:
   a purge cannot be undone, and backups are not edited, so only an old backup copy holds the data.
7. **Evidence to record.** In a private ledger outside Git: an opaque reference, the date, the outcome,
   the approval reference, PASS, FAIL or manual-step-done per system, and which steps were not applicable.
   In the repository only anything that completes an UNGROUNDED line. No usernames, names, e-mail
   addresses, tool output or screenshots (section "Evidence to record").
8. **Unverified assumptions that the procedure checks first.** That the audit and dry run output match the
   live services (read them before acting); whether a deactivated Authentik user's existing sessions are
   rejected (U-2); whether an open Seerr session survives a disabled Jellyfin account (U-20); whether
   Komga can disable an account (U-17); what a Seerr deletion removes (U-18); that `verify()` reports
   Authentik truthfully (it can report PASS when the lookup itself failed, see "Verify").

## Principles

1. Deleting the Authentik user is **not** offboarding. Jellyfin keeps its own copy of the password and
   keeps working; Seerr rides on the Jellyfin account; Komga keeps a copy of the password; the ebook
   library and audiobook library keep local rows. Sources: `scripts/offboard.py:5-10`,
   `docs/services/jellyfin.md:25-31`, `docs/onboarding/admin-onboarding.md:52-56`, `docs/services/komga.md:19-31`.
2. **Deactivate first, delete only when asked.** Deactivation is reversible and keeps history. Deletion
   is irreversible. The tool's default is deactivation (`scripts/offboard.py:23`).
3. **Dry run first, every time.** The tool is a dry run unless `--apply` is given
   (`scripts/offboard.py:22, 289-290`).
4. **Never delete media or shared data.** Deleting a media-server user removes the user and their
   progress only (`docs/onboarding/admin-onboarding.md:68-69`). Nothing in this runbook touches a library
   folder, a Calibre library, the audiobook folder or a Docker volume. **One exception, stated
   explicitly:** Step 4 item 6 deletes the member's `profiles/<profile_id>` directory of the Audible
   connector. That directory is a bind mount on the host (`./profiles:/profiles` in
   `services/avrana-audible-connector/docker-compose.yml`), not a named Docker volume. Deleting it is a
   production change that needs the owner's specific approval and is irreversible.
5. **Observe, change one thing, verify** (`AGENTS.md`). No SQL against Jellyfin. No ad-hoc database edits
   on any member-facing service.
6. No member data in Git, chat or evidence. Use an opaque reference (section "Evidence").

## Two outcomes

| | Deactivation ("step away") | Data removal ("remove my data") |
|---|---|---|
| Tool flags | `--apply` only | `--apply --purge` |
| Reversible | Yes for Jellyfin, Audiobookshelf and Authentik. Seerr is left as it is | **No** |
| History kept | Yes | No, for the systems the tool covers; manual steps below cover the rest |
| Backups | Unchanged | **Unchanged**: backups are not edited and age out (section "What is retained") |
| Wording to the member | `docs/member/house-rules-and-privacy.md`, "Leaving Avrana" | Same, plus decision D-17 |

A member who asks to be removed gets deactivation first, unless they explicitly ask for data removal.
Deactivation can be upgraded to removal later; the reverse is impossible.

## Before you start

- [ ] The request came from the member, or the owner decided, and you know which outcome applies.
- [ ] Approval: AVR-366 says no live user account is deleted without specific owner approval. Record the
      approval in your private ledger (not in Git).
- [ ] The account is not protected: the tool refuses `akadmin`, `cody`, `ldap-cwa` and `root`, in any
      letter case, with any flags (`scripts/offboard.py:47-48, 240-242`).
- [ ] **Member self-service first, if the member is cooperating and still signed in.** After the account
      is deactivated the member can no longer reach these, so this order matters:
  - Audible connector: the member presses Disconnect, which deletes their stored Audible sign-in
    details and records (`services/avrana-audible-connector/README.md:138-144`).
  - Kindle address: the member presses Remove on the Kindle setup page, which clears both libraries
    (`services/avrana-kindle-connector/README.md:245-246`).
- [ ] Note the member's e-mail address privately from the Authentik admin UI (Directory, Users). The
      dry run prints the username and name but not the e-mail address, and Komga and the audiobook
      library match on e-mail (`scripts/offboard.py:124-127`, `docs/services/komga.md:25-27`).
      Do not copy it into the evidence.
- [ ] The username matches `[A-Za-z0-9._-]+` and nothing else. Refuse any other username until the
      script is fixed. Where the tool pastes the username unescaped: line 101 (the lookup, which runs on
      the typed username on every invocation including a dry run, inside a shell command and a SQL
      string) and line 204 (the deactivation `UPDATE`, using the stored username). The purge path
      (lines 194-199) quotes the username with `{u!r}` and `shlex.quote`, so it is not the unsafe one.
      Sources: `scripts/offboard.py:99-102, 203-204`, compare `:194-199`.

## Step 1. Audit (read-only)

```
python3 /home/cody/avrana/scripts/offboard.py --audit
```

Lists accounts in Authentik, Jellyfin, Audiobookshelf and Seerr and flags names with no Authentik match
(`scripts/offboard.py:295-340`). It reads live services with credentials it loads itself from host
files (`scripts/offboard.py:38-40`), so it runs on the host, not on a laptop. An unmatched name is not
proof of an orphan: Jellyfin stores no e-mail, and the admin has different usernames in different systems.
It does not list Komga, Calibre-Web, Shelfarr, Omnibus or the Audible connector.

## Step 2. Dry run (read-only on the services)

```
python3 /home/cody/avrana/scripts/offboard.py <username>
```

Prints the matched account in each system and exactly what would happen. Check:

- Each match is the right person. Jellyfin matches by username only. Audiobookshelf matches by e-mail
  or username. Seerr matches by display name, username or e-mail (`scripts/offboard.py:109-139`).
  A fuzzy match is never acted on silently, but you must read the list.
- If only the Authentik account matched, the tool says so. Check the audit before believing it
  (`scripts/offboard.py:265-266`).
- Read the two notes the tool prints: Komga and Calibre-Web are **not** handled
  (`scripts/offboard.py:142-147`).
- Do not paste the output anywhere. It contains the member's username and name.

## Step 3. Deactivate (reversible)

```
python3 /home/cody/avrana/scripts/offboard.py <username> --apply
```

It asks you to type the username to confirm; `--yes` skips that prompt, so do not use `--yes`
(`scripts/offboard.py:268-272`). The order is fixed in the code and is deliberate: Jellyfin first,
because it is the account that still works after Authentik is gone; then Seerr; then Audiobookshelf;
then Authentik last, because identity resolution depends on it (`scripts/offboard.py:274-283`).

| System | What `--apply` does | Reversible | Source |
|---|---|---|---|
| Jellyfin | Sets `IsDisabled` on the user's policy | Yes: clear the flag in the Jellyfin dashboard | `scripts/offboard.py:159-162`; `docs/onboarding/admin-onboarding.md:100-103` |
| Seerr | Nothing. Seerr has no disable; the tool prints "left" | n/a | `scripts/offboard.py:177-183` |
| Audiobookshelf | Sets `isActive` to false. Refuses the root user | Yes | `scripts/offboard.py:165-174` |
| Home (comics key) | Revokes the member's own Komga key that Home holds (in Komga, as the member, with that key; no admin credential) and drops it from `state/komga_member_keys`. The dry run only says whether one is held. Komga unreachable: nothing is revoked and Home's entry is KEPT; re-run the tool when Komga is back, or the member deletes the `avrana-home` key under their own Komga account (an admin cannot manage another user's keys in Komga) | No (a new one needs Connect comics or a new enrollment) | `scripts/offboard.py:367-401`; `docs/runbooks/komga-key-lifecycle.md` |
| Authentik | Sets `is_active` to false through SQL | Yes | `scripts/offboard.py:203-205` |

The tool then verifies (section "Verify").

**Seerr session warning (REASONED, unverified, U-20).** The tool leaves Seerr alone on deactivation. Seerr
signs in with Jellyfin credentials and keeps its own session, so an already open Seerr session may keep
working after the Jellyfin account is disabled. Nothing in the repository shows either outcome. Check, in the
Seerr admin UI (read-only): whether the member's user is still listed and what it can do. If the member's
request access must end at once, deletion in Seerr is the only action the tool offers (Step 5), and that is
irreversible; decide per case with the owner.

## Step 4. Manual steps the tool does not do

Do these in order. Each is marked with how well the repository supports it.

1. **Calibre-Web (ebook library): cut the cached sign-in.** The library validates passwords through the
   directory service in cached mode, so a removal can lag. To cut access at once, disable the user in
   Authentik (done in Step 3) **and restart the `authentik-ldap` outpost**. Source:
   `docs/services/calibre-web-automated.md:81-87`. Restarting a container needs the owner's
   approval for that change (`AGENTS.md`); it briefly interrupts ebook sign-ins only.
   Grounded.
2. **Calibre-Web: the local row.** No user API exists; LDAP users lose access once Authentik is
   disabled but the row remains. Remove it in the library's own admin user list if full removal was
   requested (`scripts/offboard.py:145-147`; `docs/onboarding/admin-onboarding.md:66`).
   The row holds the member's Kindle address. **UNGROUNDED**: exact clicks. **Irreversible.**
3. **Komga (comics).** The tool cannot act: no working admin credential on the host. Delete the account
   in Komga's own UI (Users) (`scripts/offboard.py:142-144`; `docs/onboarding/admin-onboarding.md:66`).
   A member who enrolled before 2026-08-17 may have no replicated account (`docs/services/komga.md:52`).
   Grounded for the location, **UNGROUNDED** for the clicks. **Irreversible** when deleted. Do this
   step only for removal; a deactivated Authentik account already blocks the sign-in button, but the
   Komga copy of the password still works for catalog apps until the Komga account is removed or
   disabled. Decide per case. **UNVERIFIED U-17**: whether Komga offers a disable.
4. **Kindle address in the audiobook library (only if the member could not remove it themselves).**
   It lives in one shared device list, scoped to the user. Removing another person's entry by hand is
   not documented. **UNGROUNDED.** Do not clear the whole list: it is global and written as a whole
   (`services/avrana-kindle-connector/README.md:22-30`).
5. **Request services: Shelfarr (books) and Omnibus (comics).** Both keep their own users. The repo has
   no removal procedure for either. **UNGROUNDED.** Omnibus has per-user flags `canRequest` and
   `canDownload` (`docs/services/omnibus.md:67`); using them as a soft block is not documented as an
   offboarding step. Shelfarr has local accounts and is described as not yet in service
   (`docs/services/shelfarr.md:12-13`), which contradicts the portal; see the stale-statements list.
6. **Audible connector (only if the member could not disconnect themselves).** Admin removal is to
   delete `profiles/<profile_id>` and the matching `connection` row (`services/avrana-audible-connector/README.md:144`).
   How to find the `profile_id` is not documented. **UNGROUNDED**. This is the one place the runbook
   deletes a directory on the host (Principle 4): a production change that needs specific owner approval
   for this member, and it is **irreversible**. The profile folder holds live Audible sign-in
   tokens (`services/avrana-audible-connector/README.md:150-152`).
7. **Authentik sessions and passkeys.** Deactivation does not by itself document ending existing
   sessions. In the Authentik admin UI, Directory, Users, the user, **Sessions**: delete the rows. Also
   delete the user's passkey under **MFA Devices** if the device may be lost or stolen
   (`docs/services/authentik-sessions-passkeys.md:120-130`). **UNVERIFIED U-2**: whether a deactivated
   user's existing sessions are rejected. Do this step regardless; it is reversible only in the sense
   that the member signs in again.
8. **Tracearr history.** The repo documents no per-user deletion. Do not edit its database by hand.
   **UNGROUNDED.** Decide under D-17 whether removal requests cover it.
9. **Abandoned or pre-created records.** If the member was only partly invited, a disabled Jellyfin
   account may exist without the video group (`docs/onboarding/admin-onboarding.md:83-103`), and an
   inactive Authentik user may exist from an unfinished enrollment
   (`docs/services/authentik.md:141-164`). The tool matches Jellyfin by username, so it finds the first.
   Grounded.


## Step 4b. Media Home: the name stays bound to the former member

Media Home binds each Authentik username to the Authentik user that holds it (RC1 finding S1,
`services/avrana-home/avrana_home/identity_bindings.py`). After offboarding, **leave the binding in place**: if anyone
is later given the same username, Home treats them as signed out instead of showing them the former member's
libraries, requests or profile. Purge the member's Home profile now:

```sh
docker exec avrana-home-beta python3 -m avrana_home.memberstore purge <username>
```

The name is not reused: deactivating keeps the Authentik user, and Step 5 retires the name in Authentik before it
deletes the user, so enrollment refuses it. Releasing a name for deliberate reuse has its own checked procedure:
[identity-bindings.md](identity-bindings.md) section 3. Grounded (tests: `services/avrana-home/webtests/test_web_identity_bindings.py`,
`services/avrana-home/tests/test_identity_bindings.py`, `tests/test_enrollment_username_available.py`, `tests/test_offboard_retire.py`).

## Step 5. Data removal (only when asked; irreversible)

Only after Step 3 and Step 4 have been done and verified for a deactivation, and only with specific
owner approval for the removal of this member:

```
python3 /home/cody/avrana/scripts/offboard.py <username> --apply --purge
```

| System | What `--purge` deletes | Source |
|---|---|---|
| Jellyfin | The user and their progress | `scripts/offboard.py:156-158` |
| Seerr | The Seerr user | `scripts/offboard.py:180-182` |
| Audiobookshelf | The user | `scripts/offboard.py:170-172` |
| Authentik | The user, through Django so that dependent rows go with it. A failure prints "FAILED ... check by hand" | `scripts/offboard.py:189-202` |

Home keeps a little per member when its member store is on (`HOME_MEMBER_STORE`): the photo and display name the
member set on their profile page, their Customize settings and whether they hid the setup suggestion. `offboard.py` does not touch it; remove it with Home's own command, in the running Home
container (it prints only the username and a verdict; exit 0 done or nothing there, 1 not written, 2 refused):

```
docker exec avrana-home-beta python3 -m avrana_home.memberstore purge <username>
```

**UNVERIFIED U-18**: whether deleting a Seerr user also deletes their request records, and whether
Jellyfin's activity log keeps entries naming the deleted user.

Then repeat Step 4 for every manual item the member's data touched.

## Verify

What the tool prints after `--apply` (`scripts/offboard.py:209-223`):

- Jellyfin: PASS if the user is disabled, or the lookup returns 404 or 400 (gone). Any other HTTP status is
  FAIL; a network error is not caught and ends the tool with a traceback.
- Authentik: PASS if the user is inactive or no longer exists.

**Do not believe the Authentik PASS on its own.** `verify()` reads Authentik through `authentik_user()`,
which runs `docker exec ... psql` and returns only standard output; the exit code and standard error are
discarded (`scripts/offboard.py:75-76, 98-106`). If that command fails for any reason (container not running,
wrong container name, database error), the lookup returns nothing and `verify()` prints
`PASS  authentik/<user> no longer exists` even though nothing was checked (`scripts/offboard.py:218-220`).
Always confirm in the Authentik admin UI (Directory, Users) that the user is inactive (deactivation) or
absent (removal) before accepting that line.

What the tool does **not** check, although its header says it "verifies that the account can no longer
authenticate" (`scripts/offboard.py:26`): it does not try to sign in, it does not look at Audiobookshelf or
Seerr, and it does not look at any manual-step service.

What `--audit` shows (`scripts/offboard.py:295-340`), so that the checks below use it correctly:

- Authentik: each user with `active=True` or `active=False`. This is the only place the audit prints an
  active flag.
- Jellyfin, Audiobookshelf, Seerr: each name with `name-match`, `email-match` or `UNMATCHED`. **It prints no
  disabled or active flag for any of them.** A deactivated Jellyfin or Audiobookshelf account is still listed,
  and still matched while the Authentik user exists, so the audit cannot confirm a deactivation there.
- After an Authentik purge, the surviving accounts of that member (a Seerr user after a deactivation, or
  anything the tool missed) appear as `UNMATCHED`, because their Authentik counterpart is gone. An
  `UNMATCHED` entry after a removal therefore means "still exists", not "orphaned and safe".

Checks, in order. All are read-only. Do not copy names; record counts and PASS or FAIL only.

- [ ] Run `--audit` before the change and again after. Authentik: the user is `active=False`
      (deactivation) or absent (removal). Jellyfin, Audiobookshelf, Seerr: after a removal the counts are
      each one lower, and no entry is newly `UNMATCHED`. After a deactivation the counts are unchanged:
      the audit says nothing more, so use the admin checks below.
- [ ] Authentik admin UI, Directory, Users: the user is inactive (deactivation) or absent (removal). For a
      deactivation, open the user and check that the Sessions list is empty (Step 4 item 7).
- [ ] Jellyfin dashboard, Users: the member's user shows as disabled (deactivation) or is absent
      (removal).
- [ ] Audiobookshelf, Settings, Users: the user is inactive (deactivation) or absent (removal).
- [ ] Seerr, Users: after a deactivation the user is still listed (the tool leaves it) and the Seerr session
      warning in Step 3 applies; after a removal the user is absent.
- [ ] Ebook library: the member's sign-in fails after the LDAP outpost restart (only the owner can test
      this, with a disposable account during the rehearsal, never with the member's password).
- [ ] Komga, Shelfarr, Omnibus, Audible connector, Kindle address: the manual step you performed is
      recorded as done or as "not applicable, never signed in".
- [ ] The libraries are unchanged: item counts as before (`docs/onboarding/admin-onboarding.md:68-69`).

## What is retained, and for how long

| Where | What stays | For how long | Source |
|---|---|---|---|
| Local backup runs | A copy of every service database as of each run, including this member's records | Newest 7 complete runs; a run containing a `.keep` file is never pruned | `services/backups/README.md:31-33` |
| Local golden backup | Everything as of 2026-09-20 | Kept deliberately, not pruned | `docs/BACKUPS.md:12` |
| Off-host daily copies (encrypted) | Same | About 90 days, then 30 days hidden, if the bucket rule is set | `services/backups/OFFHOST.md:28-37` |
| Off-host pinned copies | Same | Until removed by hand | `services/backups/OFFHOST.md:28-37` |
| Service logs | Entries naming the member, if any | Rotated by size; no time limit documented | compose `logging` options; **UNVERIFIED U-14** |
| Request history, Tracearr history | Not documented | Not documented | **UNVERIFIED** U-5 to U-8 |

Backups are never edited to remove one member. The off-host uploader has no delete or overwrite
operation and its markers are never rewritten (`services/backups/OFFHOST.md:18-20`,
`docs/DECISIONS.md:33`). A "remove my data" request is therefore honoured in the live systems, and the
member is told that backup copies age out (decision D-17).

## Honouring a "remove my data" request

1. Confirm with the member that this means irreversible deletion, not stepping away.
2. Do Steps 1 to 4 (deactivation) and verify.
3. With specific owner approval, do Step 5 and the manual deletions.
4. Run `--audit` and the Verify checklist again.
5. Tell the member what was removed and what remains (backups until they expire; any item marked
   UNGROUNDED that could not be removed). Say nothing that the Verify checklist did not confirm.

## Reversing a deactivation

Possible only if nothing was purged: in Authentik set the user active (admin UI), in Jellyfin clear
"Disable this user" in the dashboard, and in Audiobookshelf set the user active. Deactivation of Seerr
is not applicable. A restored member's sessions were deleted in Step 4, so they sign in again.
Source: `docs/onboarding/admin-onboarding.md:100-103`; `scripts/offboard.py:159-174, 203-205`.

## Evidence to record (no personal data)

Keep a private ledger outside Git. If anything is recorded in the repository, use only:

- An opaque reference (for example `OFF-YYYYMMDD-n`), the date, and the outcome (deactivation or removal).
- The approval reference (issue or message id, not content).
- Tool exit code and, per system, PASS, FAIL or "manual step done".
- Which manual steps were not applicable.
- Anything that was UNGROUNDED, so this runbook can be completed.

Never record: usernames, names, e-mail addresses, Kindle addresses, tool output, screenshots of admin
pages. `docs/SECURITY.md:13` and `AGENTS.md` rules apply. Run
`python3 scripts/review_git_content.py --staged` before any commit.

## What the existing tooling does not cover

- Komga, Calibre-Web, Shelfarr, Omnibus: no action (Komga and Calibre-Web print a note; the other two
  are not mentioned at all in `scripts/offboard.py`).
- The Kindle address stored in two libraries, the Audible connector profile and records, and Tracearr history.
- Authentik sessions, passkeys and tokens (the tool only flips `is_active`).
- Verification of Audiobookshelf, Seerr, sign-in failure, and a trustworthy Authentik lookup (a failed
  lookup prints PASS).
- Any check that the matched account is the right person beyond the printed list.
- Tests: `scripts/test_offboard.py` is outside `tests/`, hard-codes the host path and its
  `test_audit_*` cases call live services. Do not run it from a laptop or as part of the offline suite.

## Rehearsal (AVR-366)

Before the first real use, run Steps 1 to 5 once with a disposable account (the repository's earlier
rehearsal used an account named `zz-offboard-test`, `scripts/test_offboard.py:1-7`), with the owner's
explicit approval, and complete every UNGROUNDED line above from what actually works.

## Usernames are never reused (owner decision 2026-10-27)

Home links a member to their Jellyfin and Audiobookshelf accounts by username alone (no stable id,
`docs/design/IDENTITY-MAPPING.md` section 5.6). So:

1. Deactivate the Authentik user; never delete it and create a new person under the same name.
2. Keep the member's Jellyfin and Audiobookshelf accounts disabled (Step 3 above), never renamed back.
   `services/avrana-home/tools/check_member_links.py <username>` should then report `disabled` for both.
3. Before inviting someone, check the name was never used: Authentik shows deactivated users in Directory → Users.

## Sources

`scripts/offboard.py`; `scripts/test_offboard.py`; `AGENTS.md`; `docs/SECURITY.md`;
`docs/onboarding/admin-onboarding.md`; `docs/services/jellyfin.md`, `komga.md`,
`calibre-web-automated.md`, `authentik.md`, `authentik-sessions-passkeys.md`, `omnibus.md`, `shelfarr.md`,
`tracearr.md`; `services/avrana-kindle-connector/README.md`; `services/avrana-audible-connector/README.md`;
`services/backups/README.md`; `services/backups/OFFHOST.md`; `docs/BACKUPS.md`; `docs/DECISIONS.md`;
`docs/member/DECISIONS-NEEDED.md` (U and D identifiers).
