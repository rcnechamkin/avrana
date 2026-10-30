# Komga member keys: Continue reading on Comics

Owner decision 2026-10-28 (docs/DECISIONS.md). Home's comics rows are a shared view read with one regular Komga
account (ADAPTER-CONTRACT 12.2). Continue reading is different: it is each member's own in-progress books, then
their On Deck (the next unread book of a series they have started), and Komga answers those only to the member
themself. Home therefore holds one Komga API key per member, made by `tools/komga_member_keys.py`, and uses it for
that one row and nothing else (two GET routes: `/api/v1/books?read_status=IN_PROGRESS` and `/api/v1/books/ondeck`).

A member without a key sees exactly what they see today: Recently added and New releases, no Continue row.

**Superseded 2026-10-30 (S-01).** Keys are now minted where the password lives: by the enrollment stage and by the
member on Me -> Comics, never with an admin key (docs/runbooks/komga-key-lifecycle.md; docs/DECISIONS.md, "Komga
member keys are minted where the password lives"). The admin-key paths below reset the member's Komga password, which
breaks the OPDS password the enrollment set. Home's automatic path is switched off live and runs only with
`HOME_KOMGA_LEGACY_PROVISION=on`; do not use `--member` / `--all` of the tool for new keys. `--list`, `--remove` and
the file format below still apply.

## Automatic (LEGACY): Home makes the key (owner decision 2026-10-28, "Home does it")

With `komga` in `HOME_PROVISION_ACCOUNTS`, Home makes a member's key the first time they open a page with their
Comics rows and have none (a Continue section answers `no_member_key`). The same page then shows their row. Home
uses its Komga admin key (`secrets/komga_admin_token`) for this and nothing else. The steps are the tool's,
below: find the account by email (or create it with Authentik sign-in defaults), a one-time random password
(one Komga sign-out), the `avrana-home` key, filed in `state/komga_member_keys`. Your own account, the admin
key's, gets its key without a password change; any other admin is never touched. One attempt per member per
hour, at most `HOME_PROVISION_CAP_PER_HOUR` (with Jellyfin and Audiobookshelf creations) in all; every attempt
logs one `provision` event with service `komga` and a fixed reason.

Safety stops (S-02). Home refuses to make keys while the keys file is absent or unreadable (log `provision`,
service `komga`, state `refused`, reason `keys_file_unusable`; no Komga request): an unmounted `state/` would
otherwise look like "nobody has a key" and reset members' passwords. So create the file once, empty, when turning this
on: `echo '{}' > state/komga_member_keys && chmod 600 state/komga_member_keys`. If a key step fails AFTER the
password reset (Komga error, or the file cannot be written), Home logs `provision`, service `komga`, state `failed`,
reason `failed_after_reset`, and never retries that member by itself; find them with
`grep failed_after_reset` in Home's log, and the list is in `state/komga_member_keys.reset_failed`. Repair with
`python3 tools/komga_member_keys.py --member <email> --keys-file state/komga_member_keys` (a key in the file also
ends the block; to let Home try again without a key, delete the member's line from the `.reset_failed` file AND
restart Home, which also holds the block in memory).

Home re-reads the keys file whenever it changes, so neither Home nor the tool needs Home restarted.

Turning it on (owner, once):

1. Create a Komga admin API key named `avrana-home-admin` and put it in `secrets/komga_admin_token` (hidden
   prompt, mode 0600), like the other secrets.
2. `mkdir -m 700 state` next to the compose file (owned by cody, uid 1000), and move any keys file there:
   `mv secrets/komga_member_keys state/`.
3. Add `komga` to `HOME_PROVISION_ACCOUNTS` in `beta-live.env`.
4. Uncomment the Komga lines in `docker-compose.beta-live.yml` (two environment lines, `volumes:`, the second
   `secrets:` line, `komga_admin_token`), dry-run and recreate.

Checking coverage: `python3 tools/komga_member_keys.py --missing` lists non-admin Komga accounts Home holds no
key for (they get one on their next Home visit). Turning it off: drop `komga` from `HOME_PROVISION_ACCOUNTS`;
existing keys keep working.

## What it costs

- Komga makes keys only for the account that is signed in, and members never see their Komga password (Authentik
  sign-in gives them a random one). So the tool sets a fresh random password for each member, signs in as them
  once to make the key, and forgets the password. **That signs the member out of Komga's web app once.** Their
  Authentik sign-in is not affected; they sign in again as usual.
- An account that uses a real local Komga password (not Authentik) would lose that password. The tool never
  touches ADMIN accounts; pass `--skip` for any other local account, such as Home's shared viewer.
- Komga keys cannot be narrowed: a member's key can do whatever that member can do in Komga. Home's code uses it
  only through the two-route allow-list above (`MEMBER_ROUTES`, GET only), and the file is a secret like the
  others (mode 0600, `secrets/`, never in Git).
- Every run needs a Komga **admin** API key. With the tool you type it at a hidden prompt and delete it
  afterwards. With automatic keys on, Home holds one (owner decision 2026-10-28, replacing 2026-10-15's "no
  admin key"), used only by provision.py, never by the read adapters.

## First run (everyone who already has a Komga account)

On avrana, from `/home/cody/avrana/services/avrana-home`:

1. In Komga (read.avrana.net) as the owner: Account settings -> API keys -> create one named `temporary`.
2. Run the tool. It lists each Komga account and asks before changing it; answer `n` for anyone who should be
   left alone.

   ```bash
   python3 tools/komga_member_keys.py --all --skip <Home's shared viewer email>
   ```

3. Check who has a key: `python3 tools/komga_member_keys.py --list` (emails only).
4. Delete the `temporary` key in Komga.
5. Home picks the file up by itself (it re-reads it when it changes). With automatic keys on, the keys file is
   `state/komga_member_keys`: pass `--keys-file state/komga_member_keys`.

## A new member (onboarding), by hand

Not needed with automatic keys on: their first Home visit makes it.

A member gets a Komga account on their first Authentik sign-in to read.avrana.net. To give them Continue reading
from day one, do this when you invite them instead of waiting:

```bash
python3 tools/komga_member_keys.py --member new.member@example.com
```

With no Komga account yet, the tool creates one by email with the same defaults an Authentik first sign-in gives
(download and page streaming, every library, no restriction). Komga finds accounts by email, ignoring case, so
their first Authentik sign-in lands in that account. Then delete the temporary admin key.

If you forget, nothing breaks: they see the shared rows, and you can run `--member` for them later (that later run
signs them out of Komga once).

## Remove or rotate

- Rotate: run `--member <email>` again. Their older `avrana-home` key is deleted and replaced.
- Remove: `--remove <email>` deletes their `avrana-home` key in Komga (one sign-out) and drops it from the file.
  A member removed from Authentik should be removed here too.

## Not verified

The Komga behaviour above is read from the 1.25.0 source, not tested against the live server: account creation
by email linking on first Authentik sign-in, the password reset signing the member out, and the two reading
routes. The first `--member` run on a test account is the check.
