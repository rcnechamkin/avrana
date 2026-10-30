# Komga member keys: minted where the password lives (S-01)

Decision: docs/DECISIONS.md, "Komga member keys are minted where the password lives". This replaces Home making
keys with a Komga admin key (`provision.py`, which reset the member's Komga password and so broke the OPDS password
the enrollment set on purpose). Enrollment owns the member's Komga credential; Home only consumes keys and never
holds or changes a member's password.

How a member's own Komga key reaches `state/komga_member_keys` now:

| Way | Who has the password | What happens | Code |
|---|---|---|---|
| Enrollment | Authentik, inside the flow | Policy `avrana-komga-key-mint` (login stage, after `avrana-komga-create`) signs in to Komga AS the new member, makes the key `avrana-home`, PUTs it to Home's intake. Never fails enrollment. | `services/authentik/blueprints/avrana-enrollment.yaml` |
| Connect comics | The member, once | Me -> Comics -> Connect comics: the member types their Avrana password; Home signs in to Komga as them, makes the key, files it and forgets the password. Five tries per 15 minutes. | `services/avrana-home/avrana_home/komga_keys.py`, `app/comics.py` |
| Owner tool (legacy) | Temporary admin key | `tools/komga_member_keys.py`: still resets the password. Do not use for new keys; see "Phase 4". | `services/avrana-home/tools/komga_member_keys.py` |

Every key is checked with Komga before it is filed (`GET /api/v2/users/me` with the key) and filed under the email of
the Komga account it opens. A member removes Home's access on Me -> Comics -> Disconnect (revoked in Komga with the
key itself, then dropped); `scripts/offboard.py` does the same for a leaving member.

## The Komga API this relies on

Read from Komga's source (master, 2026-10-30: `UserController.kt`, `SecurityConfiguration.kt`, `ApiKeyDto.kt`); the
deployed image is pinned by digest only (`services/komga/docker-compose.yml`), and earlier notes call it 1.25. NOT
tested against the live server.

- `POST /api/v2/users/me/api-keys {"comment"}` makes a key for the SIGNED-IN account only and is the only answer
  that shows the key. There is no admin route that makes a key for another user. Sign-in is HTTP Basic with the
  account's email (case-insensitive) and Komga password, or an `X-API-Key`.
- `GET /api/v2/users/me/api-keys` lists the account's keys with the key masked (`******`), so Home keeps each key's
  Komga id in `state/komga_member_keys.ids` to revoke it precisely. Without an id it deletes every `avrana-home` key
  of the account.
- `DELETE /api/v2/users/me/api-keys/{id}` (204; 404 when not this account's) works with an API key: the security
  configuration authenticates `X-API-Key` on all of `/api/**` with no per-route exception. So a stored key can
  revoke itself; Disconnect and offboarding use that and need no admin credential.

## Owner apply steps

Nothing here is applied by an agent. Each step is a production change that needs your approval for that change
(`AGENTS.md`). Never print the token; type it at a hidden prompt.

### 1. Home: the intake and Me -> Comics (one Home deploy)

On avrana, in `/home/cody/avrana/services/avrana-home`:

1. Make the shared token once (32+ random characters) into `secrets/home_key_intake_token` (mode 0600), the same
   way as the other secrets. The same value goes into Authentik in step 2.
2. Find the subnet of the network Home shares with authentik-server alone:
   `docker network inspect authentik_home_beta --format '{{(index .IPAM.Config 0).Subnet}}'`.
3. In `docker-compose.beta-live.yml` uncomment `HOME_KEY_INTAKE_TOKEN_FILE`, `HOME_INTERNAL_CIDR` (set to that
   subnet) and `HOME_KOMGA_CONNECT=on`, add `home_key_intake_token` to the `secrets:` line in use and uncomment its
   entry at the bottom. `KOMGA_MEMBER_KEYS_FILE` must stay on (live has it on; the repo file has it commented).
   Home refuses to start if the token is under 32 characters, the subnet is not private, or the keys file is off.
4. Deploy as usual (`docs/runbooks/home-beta-live.md`: dry-run, keep the old image, recreate, check health).
5. Check: Me shows a "Comics" row for a Comics member. The intake answers nothing to the outside: a PUT from
   anywhere but the subnet, or through the outpost (it adds `X-authentik-*` / `X-Forwarded-*`), is the plain 501.

### 2. Authentik: the enrollment stage (by hand, into the LIVE blueprint)

The repo blueprint is not what runs (drift in PR #167: live has an LDAP switch and admin memberships the repo
lacks). Do NOT copy the repo file over the live one. Import only the new policy and its one binding:

1. Put the token from step 1 into authentik-server's environment as `AVRANA_HOME_KEY_INTAKE_TOKEN` (and the
   worker's, so a blueprint re-apply sees the same environment), in the `.env` the Authentik compose already reads
   for `AVRANA_KOMGA_ADMIN_PASSWORD`. Recreating authentik-server needs your approval; sign-in is briefly down.
   The policy reads the variable when it runs; the token is never written into the expression.
2. In the LIVE `avrana-enrollment.yaml`, confirm the login stage binding has `id: binding-user-login` and that
   `avrana-komga-create` is bound to it (`grep -n "binding-user-login\|policy-komga-create" <live file>`). If the
   ids differ, use the admin-UI route in step 4 instead.
3. Copy two entries from the repo file into the live file, unchanged: the `policy-komga-key-mint` expression policy
   (section "Komga member key: minted while the password is still in the flow") and the policy binding at the end
   of the file (`policy: !KeyOf policy-komga-key-mint`, `order: 2`). Nothing else changes. Authentik re-applies the
   mounted blueprint on change; check Admin -> Customization -> Blueprints shows it "successful".
4. Admin-UI route (if step 2 did not match): Customization -> Policies -> Create -> Expression Policy, name
   `avrana-komga-key-mint`, execution logging on, paste the expression from the repo file. Then Flows ->
   `avrana-invite` -> Stage Bindings -> the login stage (order 40) -> Bind existing policy -> `avrana-komga-key-mint`,
   order 2. Note that a later re-apply of the live blueprint does not remove a UI-made object.

### 3. Test with ONE throwaway invitation

1. Before: `docker exec avrana-home-beta python3 -m avrana_home.member_keys count` (one number).
2. Create one invitation for the `avrana-invite` flow with `avrana_groups` including `avrana-comics` (and
   `avrana-users`), for a throwaway address you control. Enrol through it.
3. After: the same `count` is one higher. Home's log has one `komga_key_intake` line with `state` `filed` and
   `reason` `enrollment` (and a short `ref`, never an identity). Authentik's log (the policy's execution log) has
   `komga-key-mint: key filed in Home`.
4. Sign in as the throwaway member: Home's Me -> Comics says Connected. An OPDS client still signs in with the
   password chosen at enrollment (nothing changed it).
5. Offboard the throwaway member (`docs/runbooks/offboarding.md`): the dry run says it would revoke the Komga key;
   `--apply` revokes it and the count drops back.

If the count did not move: the policy log says why (`not set`, `sign-in ... failed`, `Home did not file the key` with a
status: 401 = token mismatch, 501 = wrong network or the request went through the outpost, 422 = Komga refused the
key, 503 = Komga or the keys file unavailable). Enrollment itself has succeeded either way.

Rollback: delete the policy binding (Flows -> `avrana-invite` -> login stage -> the `avrana-komga-key-mint` binding)
and the policy, and remove the two entries from the live file. Removing them from the file alone does not delete
the objects in Authentik. Home's side can stay: without enrollment calls the intake is idle. To turn Home's side
off, comment the three lines again and redeploy.

### 4. Members who have no key yet ("Connect comics" migration)

- With step 1 on, a Comics member without a key sees Me -> Comics -> "Not connected" and the Connect form. They type
  their Avrana password once. Tell members the copy's caveat: if they changed their Avrana password after joining,
  Komga still has the one they joined with (credential replication, not SSO).
- Members whose key the old provisioning made already have a key and see Connected; nothing to do. Their Komga
  password, though, was reset to a value nobody knows, so their OPDS apps no longer sign in. That is the S-01 damage
  and needs a separate owner decision (a Komga password the member sets in Komga's own UI, signed in through
  Avrana) before telling them.
- Members listed in `state/komga_member_keys.reset_failed` have neither a key nor a known Komga password: Connect
  comics will say the password didn't work. Same owner decision as above; after it, they connect themselves.
- Coverage check without any admin key: `count` above against the number of Comics members in Authentik.

## Phase 4: removing the key factory

On this branch the old admin-key provisioning is behind `HOME_KOMGA_LEGACY_PROVISION=on` (default off; settings refuse
`KOMGA_ADMIN_TOKEN` without it). After step 3 has worked live, delete in a follow-up:

- `KomgaKeyCreator`, `KOMGA_TRIGGER`, `KOMGA_OIDC_ROLES` and the Komga branch of `build_provisioner` in
  `services/avrana-home/avrana_home/provision.py`; the `provisioning` flag and `NO_MEMBER_KEY` trigger in
  `adapters/komga.py`; `reset_failed` / `mark_reset_failed` / `usable` in `member_keys.py` (only the legacy path reads
  them); `komga_admin_token`, `komga_legacy_provision` and the `komga` choice of `HOME_PROVISION_ACCOUNTS` in
  `app/settings.py`; the `HomeMakesKeys` tests in `tests/test_komga_member_reading.py`.
- The `komga_admin_token` secret entry (commented) in `docker-compose.beta-live.yml`, and `secrets/komga_admin_token`
  on the host; revoke that admin key in Komga (Account settings -> API keys).
- The password-resetting parts of `tools/komga_member_keys.py` (`--member`, `--all`); keep `--list` and `--remove`,
  or retire the tool for `member_keys count` and `offboard.py`.
- The "Automatic: Home makes the key" section of `docs/runbooks/komga-member-keys.md`.
