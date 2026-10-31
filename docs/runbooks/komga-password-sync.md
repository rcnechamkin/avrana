# Komga password sync on reset: no member ever needs an obsolete password

Audit and decision: docs/audits/2026-10-30-komga-auth-cleanup-audit.md. Companion of
docs/runbooks/komga-key-lifecycle.md (enrollment mint, Connect comics, offboarding), which stays valid.

What changes: the policy `avrana-komga-password-sync` (services/authentik/blueprints/avrana-recovery.yaml) runs on the
recovery flow's write stage. With the new password still in the flow it (1) sets the member's Komga password to the
same value, creating the Komga account if there is none, with the Komga admin API key, then (2) signs in to Komga as
the member, replaces the `avrana-home` key and files it in Home (intake `source=recovery`). It never fails the reset.
The same policy is bound, by name, in the not-yet-applied `avrana-account.yaml` password flow, so a future self-service
password change behaves the same.

Home accepts the new source (komga_keys.py) and the Me -> Comics copy asks for the CURRENT Avrana password and sends a
member whose password keeps failing to the reset.

## Owner apply steps

Nothing here is applied by an agent (AGENTS.md). Never print a secret; type it at a hidden prompt.

### 1. Home first (one deploy)

Deploy main with this change as usual (`scripts/deploy-home-beta.sh`; docs/runbooks/home-beta-live.md). No new setting.
Check: `docker exec avrana-home-beta python3 -c "from avrana_home.komga_keys import SOURCES; print(SOURCES)"` prints
`recovery` among the sources. Until this is live, the Authentik policy's PUT is answered 400 and the policy deletes
the key it just made (the password sync still happens), so do step 2 after step 1.

### 2. Authentik

1. The policy reads `AVRANA_KOMGA_ADMIN_API_KEY` from the authentik-SERVER environment at run time, exactly like
   `AVRANA_HOME_KEY_INTAKE_TOKEN` (S-01). The key already exists in `services/authentik/blueprints.env` (worker only,
   used by `avrana-komga-create` at apply time). Add the SAME value to `/home/cody/avrana/services/authentik/.env`
   (hidden prompt), then recreate authentik-server and the worker (`docker compose up -d`; sign-in is down for the
   restart; the authentik_home_beta network is declared in compose since #185, check the dry run shows it). Location
   recorded in docs/SECRETS.md.
2. In the LIVE `avrana-recovery.yaml` (`/home/cody/avrana/services/authentik/blueprints/`), the write stage binding is
   `target: !KeyOf flow-recovery, order: 40` with `re_evaluate_policies: false`. Give it `id: recovery-binding-write`
   and set `re_evaluate_policies: true` (the repo file shows the exact lines). Without this the policy only runs at plan
   time, before the password exists, and does nothing.
3. Copy two entries from the repo file into the live file, unchanged: the `policy-komga-password-sync` expression policy
   and the policy binding (`target: !KeyOf recovery-binding-write`, order 0). Authentik re-applies the mounted blueprint
   on change; Admin -> Customization -> Blueprints must show it "successful".
4. Admin-UI route instead of 2 and 3: Flows -> `avrana-recovery` -> Stage Bindings -> the write stage (order 40) ->
   Edit -> "Re-evaluate policies" on. Customization -> Policies -> Create -> Expression Policy, name
   `avrana-komga-password-sync`, execution logging on, paste the expression from the repo file. Back on the write
   binding: Bind existing policy -> `avrana-komga-password-sync`, order 0, timeout 60.

### 3. Komga: hide the obsolete login form (recommended)

Komga -> Server settings -> UI, section OAuth2: tick "Hide login fields if OAuth2 is enabled". Members then see only
"Sign in with Authentik" at read.avrana.net. "Automatic OAuth2 login" (needs the first) starts that login by itself; it
opens a popup, which Safari and the iPhone may block when nothing was clicked, so turn it on only if the phone pass
below is fine with it. Both are instant to undo. Komga's own admin (the owner) can still sign in with the form at
`/login?error=` or by unticking.

## Test matrix (one afternoon, throwaway members where possible)

Before: `docker exec avrana-home-beta python3 -m avrana_home.member_keys count` (K).

| # | Case | Steps | Expect |
|---|---|---|---|
| T1 | Fresh enrollment | Invite a throwaway with `avrana-comics`; enrol; sign in to avrana.net | Home Me -> Comics: Connected (count K+1); read.avrana.net: one click "Sign in with Authentik" (none with auto login) and in; an OPDS app signs in with the enrollment password. Unchanged by this PR; confirms the baseline. |
| T2 | Password reset, existing member with a key | "Forgot password?" for the throwaway; set a new password | authentik-server log: `komga-password-sync: Komga password now matches Avrana` then `key filed in Home`; Home log one `komga_key_intake` `state=filed reason=recovery`; count still K+1 (replaced, not added); Me -> Comics Connected; OPDS app signs in with the NEW password and not the old; the member's OTHER Komga keys (if any) still listed under Komga Account settings -> API keys; reading progress unchanged. |
| T3 | Reset for a member with NO Komga account | A throwaway created directly in Authentik with `avrana-comics` (no enrollment), then reset | log `Komga account created`; Komga Users shows it with FILE_DOWNLOAD + PAGE_STREAMING; Me -> Comics Connected. |
| T4 | Reset for a member NOT in `avrana-comics` | reset for such an account | no Komga call, no log line beyond the policy's normal pass; nothing in Komga. |
| T5 | Reconnect by hand | Me -> Comics -> Disconnect, then Connect with the CURRENT password | Connected; the copy never mentions the enrollment password; a wrong password says to reset. |
| T6 | Komga down during a reset | stop komga for one reset of the throwaway | the reset itself succeeds (new Avrana password works); log `komga-password-sync: failed error=ConnectionError`; afterwards T5 or another reset heals it. |
| T7 | Offboarding | `scripts/offboard.py` dry run, then `--apply` for the throwaway | revokes the key, count back to K; Komga account handled as the offboarding runbook says. |
| T8 | iPhone PWA and Safari | From the avrana.net PWA open a comic; from Safari open read.avrana.net | PWA: at most ONE Avrana sign-in in the in-app browser, then Komga; Safari: provider button works; with auto login on, note whether the popup was blocked (then leave auto login off); after the first login, a second deep link from Home lands on the book (7-day session). |
| T9 | Existing damaged members | one member from `state/komga_member_keys.reset_failed` resets their password | Connected; OPDS works with the new password. Then the `reset_failed` note for them can go. |

If the count does not move in T2/T3: the policy log says why (`not set` = the key or token is not in
`services/authentik/.env` or the server was not recreated; `could not list Komga accounts` with 401 = wrong admin key;
`Home did not file the key` 400 = Home not yet deployed with this change, 401 = token mismatch, 501 = network/outpost
path; the new key is deleted again in all those cases). A member is never blocked: the Avrana reset has succeeded
either way.

## Rollback

Authentik: delete the policy binding (Flows -> `avrana-recovery` -> write stage -> `avrana-komga-password-sync`) and
the policy, remove the two entries from the live file and set the write binding's `re_evaluate_policies` back to
false. Removing entries from the file alone does not delete objects in Authentik. `AVRANA_KOMGA_ADMIN_API_KEY` may stay
in `.env` or be removed with one more recreate. Home: nothing to roll back for the Authentik side (an unused source);
to restore the previous copy redeploy the previous export (`docs/runbooks/home-beta-live.md`). Komga: untick the two
UI settings.

## What this does not do (deferred on purpose)

- Universal SSO / Connected Apps UI; a "Connect via Avrana" flow that would remove Home's password form entirely
  (audit section 5, option c) is the natural next step if Connect comics is still used after beta.
- Destination preservation across Komga's OAuth2 login (upstream limit; 7-day session makes it rare).
- Jellyfin and Calibre-Web: already LDAP against Authentik, no copy to sync. Audiobookshelf: OIDC.
