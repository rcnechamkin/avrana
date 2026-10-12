# M0: Seerr CSRF protection and proxy trust (AVR-348, bug hunt A20)

Owner runbook. The settings are changed in the Seerr web UI by the owner, after a recorded before-test
and with a rollback ready. No agent changes them.

## Purpose and what it blocks

Seerr (`request.avrana.net`) is a public hostname where members sign in with Jellyfin credentials and
create requests that reach Radarr and Sonarr. Two Seerr settings are off today:

- **Enable CSRF Protection**: refuses state-changing calls that do not carry the anti-forgery token the
  web UI sends. Without it a malicious page a signed-in member visits can submit requests in their name.
- **Enable Proxy Support** (trust proxy): lets Seerr use `X-Forwarded-*` headers for the client address and
  scheme. Without it every request appears to come from the tunnel on the host.

Blocks: the M0 gate and the "no broken member requests" acceptance in AVR-348. `docs/ROADMAP.md` lists it
under "Waiting on the owner" (item "Seerr > Settings"). The finding text for A20 is not in the repo
(the bug hunt itself is not tracked); only the roadmap line exists.

## Where Seerr sits (from the repo)

```
member browser / Pocket for Seerr
   -> Cloudflare edge (TLS ends here)
   -> cloudflared on the host   deploy/host/cloudflared/config.yml: request.avrana.net -> http://localhost:5055
   -> seerr container           services/media/docker-compose.yml, port 5055, plain HTTP
```

- One proxy hop that Seerr can see: `cloudflared` on loopback. No nginx, no Authentik proxy or forward auth
  in front of Seerr. Authentik only controls whether the Requests **tile** is visible
  (`docs/services/sso-architecture.md`: Seerr has "no OIDC", local sign-in kept, `localLogin: true`).
  Therefore Seerr trusts **no identity header** today and enabling proxy support must not change that.
- The port is also published on `127.0.0.1:5055` and `10.0.0.218:5055` (LAN). A LAN client can reach Seerr
  without the tunnel and can send its own `X-Forwarded-For`. `deploy/ufw/verify-firewall.sh` expects the LAN
  address to answer. Expect the client address in Seerr's log to be forgeable from the LAN once trust proxy
  is on; that is acceptable only because nothing keys access on it.
- Local callers that use the LAN URL: `scripts/offboard.py` (`SEERR = http://10.0.0.218:5055`, uses the
  Seerr API key to list and `DELETE` users) and the Homepage widget (`HOMEPAGE_VAR_SEERR_KEY`).
- Members who use a native client: the portal help (`services/avrana-portal/portal.py`, topic
  "Requests") recommends **Pocket for Seerr** on iPhone and iPad, server `https://request.avrana.net`;
  Android uses the browser.

## Risks to settle in the test

1. **Native client may break.** CSRF protection makes Seerr require a token cookie and header on writes.
   A browser-based UI handles that; a native app may not. Whether Pocket for Seerr works with it is **not
   knowable from the repo**. The before/after matrix tests it. If it fails, either leave CSRF off and record
   an owner-approved exception, or tell members to use the browser.
2. **API-key callers.** The in-product help for the toggle says external API access may become read-only
   (author's recollection of the upstream wording; read the help text under the toggle on your version).
   If so `offboard.py` deletes against Seerr and any write by key would fail, while Homepage's read-only
   widget keeps working.
3. **Plain-HTTP LAN use.** Anti-forgery cookies may be flagged secure; writes over `http://10.0.0.218:5055`
   could stop working. Public HTTPS is unaffected.
4. **Restart.** The UI may say a restart is required after toggling. That restart is a production change.

## Preconditions

- Owner approval for this change and, if the UI asks, for restarting `seerr` (one container, a few seconds;
  members mid-request see an error).
- A test member account with `avrana-videos` and `avrana-requests` (Seerr rides on Jellyfin), an iPhone with
  Pocket for Seerr, a desktop browser, a private window.
- Quiet time. Nothing in the repo shows a request peak; pick a low-traffic hour.

## Prepared by the agent, and what only you can do

| Prepared | Only the owner can do |
|---|---|
| This runbook, the path and caller trace, the matrix | Change the two toggles |
| A read-only check of the current values (step 1) | Run every client test, including the iPhone |
| Rollback steps | Decide on an exception if the native app fails |

## Steps

1. **Baseline, read-only.** Prints only the three named keys (the file also holds the API key, never
   print it whole). Key names are from upstream; if a key is missing the output shows `None`.
   ```sh
   python3 -c "import json;m=json.load(open('/home/cody/docker/seerr/config/settings.json'))['main'];print({k:m.get(k) for k in ('csrfProtection','trustProxy','localLogin')})"
   curl -s http://127.0.0.1:5055/api/v1/status
   docker inspect seerr --format '{{.State.Health.Status}} {{.Config.Image}}'
   ```
   Expect `csrfProtection` and `trustProxy` false, a JSON status with a version, `healthy`.
   Save a copy for rollback (the file holds a secret; keep mode 600):
   ```sh
   install -d -m 700 /mnt/avrana_media/.backups/m0-seerr-$(date -u +%F)/rollback
   cp -p /home/cody/docker/seerr/config/settings.json /mnt/avrana_media/.backups/m0-seerr-$(date -u +%F)/rollback/
   ```
2. **Before-test** with the matrix below. Fill the "before" column.
3. **Enable proxy support first**, alone. Seerr web UI, Settings, General, "Enable Proxy Support", save.
   If the UI asks to restart, do step 5 now. Re-run the matrix rows 1 to 5.
4. **Enable CSRF protection**, alone, same page. Save. Re-run the whole matrix.
5. **Restart only if the UI says it is required.** From `/home/cody/avrana/services/media`:
   `docker compose --profile media restart seerr` (project `docker`; restart, not recreate). Then
   `docker inspect seerr --format '{{.State.Health.Status}}'` until `healthy` and `scripts/services-health.sh; echo rc=$?`.
6. **Confirm the stored values** with the step 1 command; expect both true.

### Verification matrix

| # | Client and action | Expected before | Expected after | Result |
|---|---|---|---|---|
| 1 | Desktop browser, `https://request.avrana.net`: sign in as test member, search, open a title | works | works | |
| 2 | Same: submit and then cancel a request for one title | works | works | |
| 3 | Private window: sign in with a wrong password, then the right one | error, then works | same | |
| 4 | iPhone Safari: sign in, request, cancel | works | works | |
| 5 | **Pocket for Seerr**: sign in, browse, request, cancel | works | works or documented failure | |
| 6 | Admin session: change and revert a harmless setting (for example a notification toggle) | works | works | |
| 7 | LAN browser `http://10.0.0.218:5055`: sign in, request | works | works or documented failure | |
| 8 | `python3 scripts/offboard.py --audit` (read-only, lists Seerr users) | lists users | lists users | |
| 9 | Homepage tile shows Seerr counts | shows | shows | |
| 10 | Seerr log: a public request shows the member's real address, not the host's | host address | real address | |

Row 10 needs a log read: `docker logs --tail 30 seerr` can contain usernames and addresses, so read it
at the terminal and do not paste it anywhere. If it still shows the host address, trust proxy is not
effective: leave the toggle but record it; do not raise the trust level elsewhere.
A write by API key (`offboard.py --apply`, a delete) is **not** tested here; do not delete a real member to
test. If you need that proof, create a test member first and offboard it with the script's dry run
first (`docs/onboarding/admin-onboarding.md`).

## Done when

- Rows 1 to 4, 6, 8, 9 pass after both toggles.
- Rows 5, 7 and 10 either pass, or the failure is written down with the owner's decision (member
  guidance to use the browser; or CSRF left off as an explicit exception).
- The step 1 command shows the intended values; the container is healthy; `services-health.sh` returns 0.

## Rollback

Same page: switch the toggle(s) off, save, restart only if the UI asked. If the UI itself is unusable:
stop `seerr`, put the saved `settings.json` back (mode 600, owner `cody`), start it:

```sh
cd /home/cody/avrana/services/media
docker compose --profile media stop seerr
cp -p /mnt/avrana_media/.backups/m0-seerr-<date>/rollback/settings.json /home/cody/docker/seerr/config/settings.json
docker compose --profile media start seerr
```

Restoring the file also reverts anything else changed in Seerr since the copy; use it only within the
test window.

## Stop conditions

- Row 1 or 2 fails after a toggle: roll that toggle back at once.
- The container is not healthy two minutes after a restart.
- `docker compose` wants to recreate anything other than `seerr`, or the project name is not `docker`.
- You are about to print `settings.json`, a log with member data, or the API key.

## Evidence (no secrets, no member data)

Dated note under `docs/findings/` and a comment on AVR-348: the filled matrix (client type, pass or fail,
no usernames), the step 1 output before and after (three booleans), Seerr version from `/api/v1/status`,
whether a restart was needed, and any exception with the owner's reason. Update `docs/ROADMAP.md`.

## Cannot be determined from the repo (verify on host)

- Exact label and help text of the toggles, and whether a restart is required, in the deployed version
  (`docs/services/sso-architecture.md` says 3.4.1; the image is pinned by digest in
  `services/media/docker-compose.yml`). Read-only: Settings, General in the UI, or `curl -s http://127.0.0.1:5055/api/v1/status`.
- Whether Pocket for Seerr works with CSRF protection.
- Whether Cloudflare's header set gives Seerr the real client address (row 10).
- Any other caller of the Seerr API: `docker logs seerr` shows API-key calls; look for the path only.
