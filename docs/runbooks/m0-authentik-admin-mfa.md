# M0: akadmin MFA, break-glass test and proposals P1 to P6 (AVR-347)

Owner runbook. No agent applies Authentik configuration (AVR-347). Source of the findings:
`docs/findings/2026-10-06-authentik-blueprint-audit.md`.

## Purpose and what it blocks

`akadmin` is the only superuser and has no second factor: the MFA validate stage is
`not_configured_action: skip`, so a password alone signs the administrator in on a public hostname
(audit finding 1, high). This runbook enrols MFA, makes sure you cannot lock yourself out, and records
a decision on each of the six hardening proposals. Blocks: the M0 gate, and every change that needs an
administrator session you trust (G1, Media 2.0 provisioning).

## Preconditions

- 1Password open; a phone or key for the passkey, and a second device or authenticator app.
- A way back in if the new factor fails (step 3 exists to prove one before you depend on it).
- No other admin work in progress. Nothing here needs a container restart.

## Prepared by the agent, and what only you can do

| Prepared | Only the owner can do |
|---|---|
| This runbook; the audit; proposals P1, P2, P3, P5, P6 as blueprint edits on a branch | Enrol the factor and store recovery codes |
| Analysis of each proposal against current `main` (below) | Decide accept or reject for each |
| Rollback notes | Merge, deploy files, test sign-in and recovery |
| P4 is **not drafted** (needs your decision) | Any change in the admin UI |

## Part 1. Enrol MFA for akadmin

1. Sign in as `akadmin` at `https://auth.avrana.net`. User settings (top right), MFA Devices.
   (The audit says: account page, "Configure" under MFA. Labels depend on the Authentik version, 2026.5.6.)
2. Enrol two factors, on two different carriers: a passkey (stage `avrana-enrollment-passkey` provides
   the Configure button) and an authenticator app (TOTP). A synced passkey and a phone-bound TOTP survive
   losing either device.
3. Add static recovery codes (Static tokens). Paste the codes into the 1Password `akadmin` entry at once.
   Codes are single use. Do not photograph or e-mail them.
4. Sign out. Sign in again in a private window with password plus each factor in turn. Expect the MFA
   prompt every time (the "remember device" cookie is inert in this version, see
   `avrana-session-tuning.yaml`).

Verify on host (read-only), because the repo does not declare the MFA validate stage (it is Authentik's
default, `default-authentication-mfa-validation`): in Admin, Flows and Stages, Stages, open it and confirm
`Not configured action` is Skip (so enrolling is what turns MFA on) and that device classes include
TOTP, WebAuthn and Static. If Static is missing the recovery codes will not be accepted.

## Part 2. Break-glass test

Goal: prove you can get back in without the factor you enrolled, before you need to.

| Path | How to test | Cost |
|---|---|---|
| Recovery codes | Private window, sign in, use one code when asked for a second factor | Burns one code; tick it off in 1Password |
| Second factor | Sign in using TOTP, then again using the passkey | None |
| Server-side recovery key | Read-only: `docker exec authentik-server ak --help` and confirm `create_recovery_key` is listed. Write the command line into the 1Password entry: `docker exec -it authentik-server ak create_recovery_key <days> akadmin` | Do **not** run it as a drill: it creates a live sign-in link for the administrator |
| Host database | `docs/services/authentik.md`, "Admin recovery procedures" (SQL via `authentik-postgresql`). That covers re-activating a user; it does not remove an MFA device | Not a drill |

Why the command line is only recorded: the repo does not document `ak create_recovery_key` (it is an
upstream Authentik management command); confirm it on your instance with `--help` before relying on it.

## Part 3. Sign-in and recovery smoke test

- Sign in as `akadmin` with MFA (done above).
- Open `https://auth.avrana.net/if/flow/avrana-recovery/` in a private window and request a reset for a
  **test member**, not `akadmin`. The e-mail half needs `docs/runbooks/m0-smtp2go-email.md` first. Without
  it, expect the page to accept the request and no message to arrive.
- Confirm a reset does not bypass MFA: a user with a device still gets the MFA prompt after the new password.

## Part 4. Proposals P1 to P6

Branch: `origin/batch5-authentik-proposals`, one commit `6e88234` on top of `d79d117` (already in `main`).
Inspected read-only. `git merge-tree --write-tree main origin/batch5-authentik-proposals` reports no
conflicts, and `services/authentik/` is unchanged on `main` since the branch point, so every hunk applies
as written. Seven blueprint files change, 101 insertions and 9 deletions, no secret in any hunk. The branch
has not been merged or deployed. **Staged is not deployed.**

| # | Change | File(s) | Applies to main | What you must decide |
|---|---|---|---|---|
| P1 | Reputation policy `avrana-login-reputation` (IP and username, threshold -5) bound to the identification stage binding of `default-authentication-flow` | `avrana-session-tuning.yaml` | Yes | Accept the lockout trade-offs below, then apply last |
| P2 | Password policy `avrana-password-policy` (12 characters, HaveIBeenPwned, zxcvbn 3) on the enrollment, recovery and password-change prompts | `avrana-enrollment.yaml`, `avrana-recovery.yaml` | Yes | Accept the outbound breach lookup and stricter passwords for members |
| P3 | Declare live bindings: Seerr also requires `avrana-videos`; Shelfarr requires `avrana-books` and `avrana-audiobooks` | `avrana-landing.yaml`, `shelfarr.yaml` | Yes | Compare with the live bindings first; then accept (no behaviour change intended) |
| P4 | Require MFA for superusers | none | Not drafted | Choose: enrolment alone (Part 1 already satisfies finding 1) or ask for a draft |
| P5 | Remove plain-HTTP LAN redirect URIs from Komga, Omnibus, Shelfarr | `komga.yaml`, `omnibus.yaml`, `shelfarr.yaml` | Yes | Does anyone sign in to these through a `10.0.0.218` address? |
| P6 | Recovery user-write stage `user_creation_mode: never_create` | `avrana-recovery.yaml` | Yes | Accept (recovery should never create users) |

File coupling: P2 and P6 share `avrana-recovery.yaml`; P3 and P5 share `shelfarr.yaml`. Accepting one
of a pair means deploying an edited copy of the file, not the branch version.

Agent analysis for your decision (from the diff and the audit; not tested on the host):

- **P1 can lock you out of your own admin account.** `akadmin` is the only superuser; five failed attempts
  by anyone can push its username score to the threshold for up to 24 hours, and clearing a score is done in
  the admin UI you cannot reach. Either create a second administrator first, or write down the server-side
  way to delete the reputation entry (verify an `ak shell` path on your instance). A named member can also be
  locked out deliberately. If Authentik sees every request as coming from the tunnel or proxy address, the IP
  score is shared by everyone and a handful of failures anywhere would block all sign-ins. **Verify on host**
  before applying: Events, a "Login failed" entry, `client_ip` must be a real remote address, and the
  server's trusted proxy setting must cover the proxy hop. The compose file sets no
  `AUTHENTIK_LISTEN__TRUSTED_PROXY_CIDRS`, so this rests on Authentik's default.
- **P1 also assumes the identification binding has order 10** in `default-authentication-flow`; the
  blueprint finds it by that number. Verify the order in the flow's Stage Bindings tab.
- **P2** replaces nothing existing, but `avrana-recovery.yaml` references a policy that
  `avrana-enrollment.yaml` creates. If the worker applies recovery first it retries on the next pass; check
  both instances end Successful. The breach check sends a hash prefix to the HaveIBeenPwned service, so it
  needs outbound access from the Authentik containers; a failed lookup behaviour is not stated in the repo.
- **P3** only matters if the live objects differ from the audit inventory
  (`batch5-20261006/authentik-inventory.txt` on the host). If a binding differs, the blueprint overwrites it.
- **P5** is safe if the three services' own configs use the public hostnames (the audit says none reference
  the LAN URIs). Reversible by adding the entries back.
- **P6** is a one-line safe tightening.

Suggested order if you accept them: Part 1 and 2 first, then P6, P3, P2, P5, and P1 last and only after the
two checks above.

### Applying an accepted proposal (owner, per `docs/DEPLOYMENT.md`)

1. Merge the branch (or an edited copy) to `main`. Do not merge it as-is if you rejected any proposal.
2. On the host: `scripts/drift-check.py --quiet` from a checkout of the commit.
3. Save the live file under `/mnt/avrana_media/.backups/batch<N>-<date>/rollback/` with its SHA-256.
4. Copy only the accepted blueprint files into `services/authentik/blueprints/`, mode 644. The worker applies
   within minutes; a worker recreate is not required for blueprint files.
5. Admin, Customization, Blueprints: the changed instances are Successful.
6. Test: an invitation enrollment (weak password refused under P2), a password reset, a normal sign-in.
7. Run `drift-check.py` again; record the result.

Rollback: restore the saved file. Objects created by P1 and P2 are not deleted by a blueprint revert: delete
`avrana-login-reputation` and `avrana-password-policy` (and their bindings) in Admin, Customization, Policies.

## Done when

- `akadmin` has at least two enrolled factors and static codes in 1Password; a private-window sign-in
  needed a second factor.
- One recovery code used and ticked off, or the second factor tested twice.
- `ak create_recovery_key` confirmed present and recorded in 1Password.
- Each of P1 to P6 recorded as accepted, rejected or deferred, with the reason, in `docs/DECISIONS.md` or a
  dated file in `docs/findings/`, and the roadmap line updated.
- For every accepted proposal: deployed, instances Successful, smoke tests passed, rollback file kept.

## Stop conditions

- The second factor is rejected at the private-window sign-in: stay signed in on the original session, do not
  sign out, fix enrolment first.
- You are down to your last unused recovery code.
- Any blueprint instance shows an error after deployment: restore the saved file and stop.
- P1 only: `client_ip` in Events is not a real remote address.

## Evidence (no secrets)

Record: date, device types enrolled (not the codes), which break-glass tests passed, the decision table for
P1 to P6 with reasons, the Blueprints page showing Successful (screenshot without tokens), drift-check
result. File: a dated note under `docs/findings/` and a comment on AVR-347.
