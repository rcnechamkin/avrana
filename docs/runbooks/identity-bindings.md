# Media Home identity bindings (RC1 finding S1)

Status: **deployed (seeded bindings file on in the live member beta since 2026-10-29, #166, revision 2cb228f).** Code: `services/avrana-home/avrana_home/identity_bindings.py`. Owner-run only;
the agent never runs these against production.

## Why

Home finds a member's Jellyfin and Audiobookshelf accounts, Shelfarr and Omnibus requests, member-store profile and
cache by their Authentik **username**. Authentik keeps a username unique only among the users that exist now. If a
member is deleted and someone else is later given the same name (an invitation, or an administrator's rename), that
person would see the former member's libraries, progress, requests and profile.

Home therefore binds each username to the Authentik user that holds it: `username -> sha256(sub)`, where `sub` is
Authentik's `hashed_user_id` (`User.uid`, the same for one Authentik user for ever and different for a recreated
one). A token whose `sub` does not match is treated as signed out.

## Rules

- **Usernames are never reused** while anything of the former member survives anywhere. Offboarding retires the name
  (`scripts/offboard.py`: deactivating keeps the Authentik user; `--purge` adds the name to the Authentik group
  `avrana-retired-usernames`, which the enrollment policy refuses, before it deletes the user).
- **Never create or rename an Authentik user to a retired name by hand.** The admin UI bypasses the enrollment
  policy. Check the group's `usernames` attribute and `identity_bindings list` first.
- **Home never creates, reseeds or repairs the file.** No file, an unreadable file, or a file that lost a binding
  Home had seen (without a release record) refuses every member until the owner fixes it. That is deliberate: a
  silently recreated file would let the next person to sign in with a former member's name claim it.

## 1. First deployment (migration of existing members)

Do this **before** the Home deploy that turns `HOME_IDENTITY_BINDINGS_FILE` on. Every step is read-only for Authentik
and the libraries; only `./state/identity_bindings.json` is written.

1. Make the seed from Authentik (one line of JSON: every user's name and the sha256 of its `sub`; the raw `sub` never
   leaves Authentik; refuses if a Home proxy provider is not on `hashed_user_id`):

   ```sh
   cd ~/avrana/services/avrana-home
   docker exec -i authentik-server ak shell < ~/avrana/scripts/identity-bindings-seed.py \
     | grep '^AVRANA-SEED ' | cut -c13- > state/identity_seed.json
   ```

2. Initialise the file from the seed with the NEW image (so the module exists), and reserve every Jellyfin and
   Audiobookshelf account name that has no Authentik user (a former member's kept account, a local-only account):

   ```sh
   docker compose -p avrana-home-beta -f docker-compose.beta-live.yml run --rm --no-deps avrana-home-beta \
     python3 -m avrana_home.identity_bindings init --seed /var/lib/avrana-home/identity_seed.json --reserve-upstream
   docker compose -p avrana-home-beta -f docker-compose.beta-live.yml run --rm --no-deps avrana-home-beta \
     python3 -m avrana_home.identity_bindings count
   rm state/identity_seed.json
   ```

   Expect `N bound, M reserved` with N = the Authentik user count and M = the upstream accounts with no Authentik user
   (on 2026-10-29: 23 Authentik users; 3 Jellyfin accounts without one). A name in the list that should belong to a
   current member means that member's Authentik username differs from their library account: fix the mapping, do not
   release.

3. Deploy Home (docs/runbooks/home-beta-deploy.md). Sign in as yourself and as a non-admin tester: both see their own
   Home. `docker logs avrana-home-beta | grep identity_jwt` shows no `bindings_unavailable`.

Rollback: the previous image ignores the file. Keep the file; it is needed again on the next forward deploy.

## 2. Day to day

Nothing. A member who joins after the seed is bound at their first sign-in. A name that differs from a bound or
reserved one only in letter case or Unicode form is refused (`identity_jwt reason=name_reserved`).

Log reasons (`identity_jwt reason=`): `identity_changed` (a different Authentik user under a bound name: expected
after a recreate, otherwise investigate), `name_reserved`, `no_subject` (a token without `sub`: provider
misconfigured), `bindings_unavailable` (the file is missing, unreadable or shrank: section 4).

## 3. Releasing a name (only for deliberate reuse)

Only with the owner's approval, after offboarding is complete:

1. `scripts/offboard.py <username> --apply --purge` has deleted the Jellyfin and Audiobookshelf accounts (Seerr
   follows Jellyfin). The release refuses while either still has an account under the name in any letter case.
2. The member store row is purged: `docker exec avrana-home-beta python3 -m avrana_home.memberstore purge <username>`.
   The release refuses while a row remains.
3. By hand, in each admin UI: the Shelfarr, Omnibus, Calibre-Web and Komga accounts of the former member are deleted
   (no API can check these; this is what `--other-apps-cleared` states).
4. Remove the name from the `usernames` attribute of the Authentik group `avrana-retired-usernames`.
5. Release:

   ```sh
   docker exec avrana-home-beta python3 -m avrana_home.identity_bindings release <username> --other-apps-cleared
   ```

   The next Authentik user with that name is bound at their first sign-in. The release is recorded in the file.

An upstream that cannot be asked is not a pass: the release refuses and changes nothing.

## 4. Recovery: the file is missing, unreadable or shrank

Everyone is signed out of Home until this is done. Do not hand-write the file.

1. Restore `./state/identity_bindings.json` from the latest backup of `./state`: the nightly `stack-config` archive
   holds `services/avrana-home/state/` (the file, its `.lock`, and `komga_member_keys` / `members.sqlite3` when on),
   and the restore verifier requires the bindings file (docs/runbooks/m0-offhost-backup-restore.md).
   Caveat: only runs made after the live backup script and required list are synced on avrana contain Home state;
   after the sync a host without the bindings file fails the completeness check by design.
2. Make a fresh seed (section 1, step 1) and merge it: `init --seed ... --reserve-upstream`. Merging only ADDS names;
   if a name in the file is bound to a different Authentik user than the seed says, `init` refuses and writes
   nothing, and lists the names. That means a username was given to a different person since the backup: decide per
   name, with the offboarding record, before going on.
3. `docker restart avrana-home-beta` (Home remembers the bindings it had seen and refuses a file that lost one until
   it restarts).

If no backup exists, section 1 from a fresh seed rebuilds it; members who joined since are bound again at their next
sign-in (they are Authentik users, so the seed already covers them).

## Evidence

Tests: `services/avrana-home/tests/test_identity_bindings.py` (seeded binding, fail closed on a missing, deleted,
malformed or shrunk file, letter-case twins, reserved names, release preflight, several processes binding and
claiming at once), `services/avrana-home/webtests/test_web_identity_bindings.py` (the same through Home's pages),
`tests/test_enrollment_username_available.py` (enrollment refuses Jellyfin names, retired names and twins of existing
users), `tests/test_offboard_retire.py` (`--purge` retires before it deletes). The enrollment policy against a real
Authentik: `.github/workflows/enrollment-policy.yml`.
