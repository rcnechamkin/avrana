# Komga member keys: Continue reading on Comics

Owner decision 2026-10-28 (docs/DECISIONS.md). Home's comics rows are a shared view read with one regular Komga
account (ADAPTER-CONTRACT 12.2). Continue reading is different: it is each member's own in-progress books, then
their On Deck (the next unread book of a series they have started), and Komga answers those only to the member
themself. Home therefore holds one Komga API key per member, made by `tools/komga_member_keys.py`, and uses it for
that one row and nothing else (two GET routes: `/api/v1/books?read_status=IN_PROGRESS` and `/api/v1/books/ondeck`).

A member without a key sees exactly what they see today: Recently added and New releases, no Continue row.

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
- Every run needs a Komga **admin** API key. Home never holds it: you create it, type it at the tool's hidden
  prompt, and delete it afterwards. Owner decision 2026-10-15 (no standing admin key) still holds.

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
5. Turn it on in Home, once: uncomment the two `komga_member_keys` lines in `docker-compose.beta-live.yml` (the
   environment line and the `secrets:` entries), then dry-run and recreate as in home-beta-live.md, step 3.

## A new member (onboarding)

A member gets a Komga account on their first Authentik sign-in to read.avrana.net. To give them Continue reading
from day one, do this when you invite them instead of waiting:

```bash
python3 tools/komga_member_keys.py --member new.member@example.com
```

With no Komga account yet, the tool creates one by email with the same defaults an Authentik first sign-in gives
(download and page streaming, every library, no restriction). Komga finds accounts by email, ignoring case, so
their first Authentik sign-in lands in that account. Then delete the temporary admin key and recreate Home (it
reads the file only at start-up).

If you forget, nothing breaks: they see the shared rows, and you can run `--member` for them later (that later run
signs them out of Komga once).

## Remove or rotate

- Rotate: run `--member <email>` again. Their older `avrana-home` key is deleted and replaced.
- Remove: `--remove <email>` deletes their `avrana-home` key in Komga (one sign-out) and drops it from the file.
  Recreate Home afterwards. A member removed from Authentik should be removed here too.

## Not verified

The Komga behaviour above is read from the 1.25.0 source, not tested against the live server: account creation
by email linking on first Authentik sign-in, the password reset signing the member out, and the two reading
routes. The first `--member` run on a test account is the check.
