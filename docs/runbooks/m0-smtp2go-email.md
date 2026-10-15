# M0: rotate SMTP2GO and prove invite, reset and alert e-mail (AVR-346)

Owner runbook. Nothing here is run by an agent. Every command is run by the owner on `avrana` as `cody`;
every secret is typed at a hidden prompt or pasted from 1Password into the vendor's web form.

## Purpose and what it blocks

Rotate the SMTP2GO password (user `avrana-mail`), update every consumer, and prove three journeys end to
end: an invitation (address verification), a password reset, and an alert. Blocks: invite tests for M1,
every Media 2.0 notification (M4), the launch, and all health, backup and disk alerts (silent today:
`scripts/avrana-alert.py` exits 3 without `services/backups/.env.alert`).

## Preconditions

- SMTP2GO web login and the 1Password entry for `avrana-mail` open.
- No invitation pending: between steps 1 and 3 Authentik cannot send.
- An inbox you control for the test (a `+tag` address works) and a private browser window.
- Owner approval for the one recreate in step 3 (`AGENTS.md`: recreating a container needs it).

## Prepared by the agent, and what only you can do

| Prepared | Only the owner can do |
|---|---|
| Consumer map below, traced from the repo | Rotate the password in SMTP2GO and store it in 1Password |
| `scripts/avrana-alert.py --check` (login test, sends nothing) | Type the value at the hidden prompts |
| Blueprints read the value with `!Env` | Recreate the worker; re-enter the value in Calibre-Web |
| Hidden-prompt snippets below | Run the invite and reset tests, record evidence |

There is **no alert-configuration script in the repo**. `docs/ROADMAP.md`, `deploy/host/owner-scripts/README.md`
and the Sprint 1 plan refer to a "Batch 1 alert-configuration script"; `git grep` finds none, and
`services/backups/` has no `.env.alert.example`. Step 4 is the stand-in. Follow-up for an agent: stage it
as `services/backups/alert-setup.sh` in the style of `offhost-setup.sh`.

## Every consumer of the SMTP2GO credential

| # | Consumer | Where the value lives | Source in repo | After rotation |
|---|---|---|---|---|
| 1 | Authentik invite verification e-mail (`avrana-enrollment-verify-email`) | `services/authentik/blueprints.env`, `AVRANA_SMTP2GO_PASSWORD`; copied by the worker into the stage row | `services/authentik/blueprints/avrana-enrollment.yaml` | Edit file, then `docker compose up -d --no-deps worker` in `services/authentik` |
| 2 | Authentik password reset e-mail (`avrana-recovery-email`) | same variable, same file | `services/authentik/blueprints/avrana-recovery.yaml` | Same recreate covers 1 and 2 |
| 3 | Alert e-mail: `services-health.sh`, `boot-verify.sh`, `avrana-backup.sh`, `offhost-backup.py`, `restore-test.py --alert`, smartd hook (`deploy/host/smartmontools/20avrana-alert`) | `services/backups/.env.alert`, `ALERT_SMTP_PASSWORD` (0600, owned by `cody`) | `scripts/avrana-alert.py` | None. The file is read on every call |
| 4 | Calibre-Web-Automated Send-to-Kindle | CWA `app.db`, encrypted with `.key` (Admin, E-mail server settings) | `docs/services/calibre-web-automated.md` | Re-enter in the admin page, "Save and send test e-mail". No restart |

Not consumers: `avrana-kindle-connector` only writes `kindle_mail` and never touches the SMTP password
(`services/avrana-kindle-connector/README.md`); both Authentik stages set `use_global_settings: false`, and
`services/authentik/docker-compose.yml` has no `AUTHENTIK_EMAIL__*` variable.

Verify on host (read-only), because the repo cannot answer them:

- Which provider CWA actually uses. `docs/services/calibre-web-automated.md` describes Postmark
  (`smtp.postmarkapp.com`); `docs/SECRETS.md` and the Kindle docs say SMTP2GO; the 2026-09-27 recovery note
  says a preserved SMTP credential authenticated. Open Admin, E-mail server settings and read the
  **server name** only. If it is not `mail.smtp2go.com`, row 4 is a different credential: do not rotate it
  here, and correct `docs/SECRETS.md`.
- Any other Authentik e-mail stage on global settings: Admin, Flows and Stages, Stages, filter "Email".
  A stage with "Use global settings" ticked has no sender configured and will not send.
- Whether the old SMTP2GO password stays valid after regeneration (SMTP2GO's page says). The steps assume it does not.

## Steps

1. **Baseline, read-only.**
```sh
cd /home/cody/avrana
ls -l services/backups/.env.alert
python3 scripts/avrana-alert.py --check; echo "rc=$?"
stat -c '%a %U' services/authentik/blueprints.env
```
   Expect: file absent, `rc=3` (or `rc=4`/`5` if a stale file exists), `600 cody`. Record the three results.

2. **Rotate in SMTP2GO.** Sending, SMTP Users, `avrana-mail`, set a new password. Paste it straight into the
   1Password entry. Labels in the vendor UI may differ; only the user name `avrana-mail` is fixed by the repo.

3. **Authentik (rows 1 and 2).** Replaces one line without printing anything.
```sh
cd /home/cody/avrana/services/authentik
install -d -m 700 /mnt/avrana_media/.backups/m0-smtp-$(date -u +%F)/rollback
cp -p blueprints.env /mnt/avrana_media/.backups/m0-smtp-$(date -u +%F)/rollback/blueprints.env
python3 - <<'PY'
import getpass, os, pathlib, sys
path = pathlib.Path("blueprints.env")
value = getpass.getpass("New SMTP2GO password (hidden): ")
if getpass.getpass("Again: ") != value or not value or any(c in value for c in " \t#'\"$\\`"):
    sys.exit("empty, mismatch or unsafe character; nothing changed")
out, hits = [], 0
for line in path.read_text().splitlines():
    if line.startswith("AVRANA_SMTP2GO_PASSWORD="):
        line, hits = "AVRANA_SMTP2GO_PASSWORD=" + value, hits + 1
    out.append(line)
if hits != 1:
    sys.exit("expected exactly one AVRANA_SMTP2GO_PASSWORD line; nothing changed")
tmp = path.with_name(path.name + ".tmp")
with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as handle:
    handle.write("\n".join(out) + "\n")
os.replace(tmp, path)
print("updated 1 line; mode", oct(path.stat().st_mode & 0o777))
PY
docker compose up -d --no-deps --dry-run worker
```
   Expect `updated 1 line; mode 0o600`. The dry run must name only `authentik-worker`. If it names anything
   else, stop. Then `docker compose up -d --no-deps worker`. In the Authentik admin UI, Customization,
   Blueprints: the enrollment and recovery blueprint instances show
   Successful with a fresh "Last applied" time. The old rollback copy holds the retired password; delete the
   `m0-smtp-*` directory once step 8 passes.

4. **Alerts (row 3).** Stand-in for the missing script. The file is parsed, never sourced.
```sh
cd /home/cody/avrana/services/backups
python3 - <<'PY'
import getpass, os, pathlib, sys
host = input("SMTP host [mail.smtp2go.com]: ") or "mail.smtp2go.com"
user = input("SMTP user [avrana-mail]: ") or "avrana-mail"
sender = input("From address [cody@avrana.net]: ") or "cody@avrana.net"
to = input("Alert recipient(s), comma separated: ")
secret = getpass.getpass("SMTP2GO password (hidden): ")
if not (to and secret) or any("\n" in v for v in (host, user, sender, to, secret)):
    sys.exit("missing value or newline; nothing written")
body = (f"ALERT_SMTP_HOST={host}\nALERT_SMTP_PORT=587\nALERT_SMTP_USER={user}\n"
        f"ALERT_SMTP_PASSWORD={secret}\nALERT_FROM={sender}\nALERT_TO={to}\n")
path = pathlib.Path(".env.alert")
with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as handle:
    handle.write(body)
print("wrote", path, oct(path.stat().st_mode & 0o777))
PY
cd /home/cody/avrana
python3 scripts/avrana-alert.py --check; echo "rc=$?"
printf 'M0 alert path test\n' | python3 scripts/avrana-alert.py --subject "M0 SMTP rotation test"; echo "rc=$?"
```
   Expect `alert: settings valid, SMTP login accepted`, `rc=0`, then `alert: sent`, `rc=0`, and the message in
   the inbox with the host name in the subject. If owner script 09 is installed, its own test also uses this path.

5. **Calibre-Web (row 4).** Admin, Basic Configuration, Edit E-mail server settings. Re-enter the password
   from 1Password, "Save and send test e-mail". Expect the test message to arrive. Skip if the server is not
   `mail.smtp2go.com` (see "Verify on host").

6. **Invitation journey.** Follow `docs/onboarding/admin-onboarding.md`, "Create a single-use invite":
   flow `avrana-invite`, single use, expiry one day, attributes `{ "avrana_groups": ["avrana-users"] }` (no
   service groups, so no Jellyfin or Komga account should be provisioned). Send the link to your test inbox.
   In a private window open it, create the account, wait for "Confirm your Avrana email" (sender
   `cody@avrana.net`), click within 30 minutes. Expect the account to become active and land on
   `https://auth.avrana.net`. Note UTC times: invite opened, e-mail received, link clicked.

7. **Reset journey.** Private window, sign-in page, "Forgot password?" (brand recovery flow
   `avrana-recovery`, direct URL `https://auth.avrana.net/if/flow/avrana-recovery/`). Enter the **test
   account**, never `akadmin`. Expect "Reset your Avrana password" within a minute, a working link inside 30
   minutes, a new password accepted, and sign-in with it. A reset does not reach Jellyfin
   (`docs/services/sso-architecture.md`); irrelevant for a test account with no video group.

8. **Clean up the test account.** Dry run first, nothing changes without `--apply`:
```sh
cd /home/cody/avrana && python3 scripts/offboard.py --help
python3 scripts/offboard.py <test-username>
```
   Review what it matched in every system, then decide on `--apply`. Deleting only the Authentik user is not
   offboarding (`docs/onboarding/admin-onboarding.md`).

## Done when

- `avrana-alert.py --check` returns 0 and the test alert arrived.
- A real invitation e-mail arrived, its link activated a new account, and that account signed in.
- A real reset e-mail arrived and the new password worked.
- Both Authentik blueprint instances are Successful after the worker recreate.
- Calibre-Web test e-mail arrived, or the provider mismatch is recorded.
- Evidence recorded, test account removed, rollback directory deleted.

## Rollback and failure handling

- The old password is gone once SMTP2GO regenerates it, so there is no "back". Failures are fixed forward by
  re-entering the new value. A failed or unreachable SMTP2GO makes mail fail visibly (Authentik shows the
  error in Events; the alert script prints `alert: SMTP failure`); nothing else degrades.
- File mistakes: restore `blueprints.env` from the `rollback/` copy, `chmod 600`, recreate the worker again.
  Remove a bad `.env.alert` and alerts return to exit 3 (silent but harmless).
- The worker recreate pauses blueprint application and background tasks for seconds. Sign-in and the Authentik
  server are not restarted. If the worker does not return healthy, `docker compose logs --tail 50 worker`
  (read it, do not paste it anywhere: it can include addresses) and stop.

## Stop conditions

- The dry run names a container other than the worker.
- `--check` fails with an SMTP login error twice in a row: stop retrying (repeated failures can lock the
  SMTP user) and re-check the value in 1Password.
- A prompt or log would print the password, or a file shows mode other than 600.
- The invite link is rejected after a good e-mail. Do not activate by SQL (`docs/services/authentik.md`) without
  deciding to; record it as a failure.

## Evidence (no secrets, no addresses, no tokens)

Write a dated note under `docs/findings/` (for example `2026-10-DD-m0-smtp-rotation.md`) and a short comment
on AVR-346 with: UTC time of each of the four tests, subject lines, SMTP2GO activity log status "delivered"
(not the address), outcome of the baseline in step 1, which provider CWA uses, and the exit codes. After a
pass, correct the stale text: the "no email/recovery flow" lines in `docs/onboarding/admin-onboarding.md` and
`docs/onboarding/welcome.md`, the "gitignored" comment in `avrana-recovery.yaml`, and the Postmark section
of `docs/services/calibre-web-automated.md` if it is wrong.
