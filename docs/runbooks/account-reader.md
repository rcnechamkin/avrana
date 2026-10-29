# Runbook: give Home the scoped account reader

Lets Media Home show a member's own sign-in methods and signed-in browsers on Avrana's pages, and sign out one of those
browsers, without ever sending the member to Authentik (owner decision 2026-10-28; design:
`docs/design/ME-ACCOUNT-SECURITY.md`). **Owner-run.** Each production step needs the owner's approval for that step
(`AGENTS.md`). Until this is done Home works without it: the pages say what they can't show.

## What the reader can and can't do

- Can: list users (to find the member's id), list every member's devices (names, kinds, dates) and sign-in sessions
  (browser, approximate place, last active), and delete a sign-in session.
- Can't: change a password, a user, a group or a device; read backup codes (the backup-code device permission is
  deliberately **not** granted, because it can read the codes themselves).
- Home's own allow-list (`avrana_home/accountreader.py`) is narrower still: four requests, the delete only for a session
  found in that member's own fresh list.
- If the token leaks: an attacker can see who is signed in where and sign people out. No account takeover.

## Steps

1. **Apply the blueprint** `services/authentik/blueprints/avrana-account.yaml` (with the rest of that branch). It
   creates the service account `avrana-home-reader` and the role `Avrana Home reader`, bound through the group
   `avrana-home-reader`. Check: Admin → Directory → Users shows `avrana-home-reader` (type: service account).
2. **Grant the role its permissions**, by hand, because blueprints can't assign global permissions on 2026.5.6
   (verify; if `permissions:` on a role entry works there, move this into the blueprint). Admin → Directory → Roles →
   *Avrana Home reader* → Assign permissions, exactly these:
   - `authentik_core | user | Can view user`
   - `authentik_core | authenticated session | Can view authenticated session`
   - `authentik_core | authenticated session | Can delete authenticated session`
   - `authentik_stages_authenticator_webauthn | WebAuthn Device | Can view WebAuthn Device`
   - `authentik_stages_authenticator_totp | TOTP Device | Can view TOTP Device`
   Nothing else. **Not** the static (backup code) device permission.
3. **Make the token.** Admin → Directory → Tokens and App passwords → Create: identifier `avrana-home-reader`, user
   `avrana-home-reader`, intent **API**, untick *Expiring* (or set a year and diary the rotation). Copy the key once.
4. **Store it on the host** at a hidden prompt, never in the shell history or chat:
   ```bash
   read -rs -p "reader token: " T && printf '%s' "$T" > /home/cody/avrana/services/avrana-home/secrets/account-reader-token && unset T
   ```
   then `chmod 600` that file. Mount it read-only into the Home container.
5. **Configure Home** (beta env file): `HOME_ACCOUNT_READER_URL=https://auth.avrana.net` and
   `HOME_ACCOUNT_READER_TOKEN_FILE=/run/secrets/account-reader-token`. Real mode already runs
   `HOME_IDENTITY_MODE=jwt_required`, which the reader needs. A plain-http URL is accepted only for a Docker service name
   on a shared network.
6. **Check the API shapes once, before members see it** (the code follows the documented API, not a 2026.5.6 read).
   From the host, with the token in a variable read at a hidden prompt:
   ```bash
   curl -s -H "Authorization: Bearer $T" "https://auth.avrana.net/api/v3/core/users/?username=<test member>" | head -c 400
   curl -s -H "Authorization: Bearer $T" "https://auth.avrana.net/api/v3/authenticators/admin/all/?user=<pk>" | head -c 400
   curl -s -H "Authorization: Bearer $T" "https://auth.avrana.net/api/v3/core/authenticated_sessions/?user__username=<test member>" | head -c 600
   ```
   Expect JSON with `results`; users carry `pk`, `username`, `is_active` (and ideally `password_change_date`); devices
   carry `name`, `meta_model_name`, `created`, `last_used`, and **no** `token_set`; sessions carry `uuid`,
   `user_agent`, `last_used`. Any difference: stop and report it.
7. **Recreate Home** (dry-run first), sign in as a test member and open Me → Account & Security → Sign-in protection
   and Where you're signed in. Sign out a second browser from the list and confirm it has to sign in again.

## Rollback

Unset the two `HOME_ACCOUNT_READER_*` settings and recreate Home (the pages fall back to "ask the person who invited
you"), then delete the token in Authentik. Removing the blueprint entries deletes the service account and role.
