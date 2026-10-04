---
bookstack_page_id: 69
title: "Security audit, 2026-08-20"
shelf: "Avrana Homelab"
book: "Runbook"
chapter: ""
created: 2026-08-20 16:43:38
updated: 2026-08-29 04:24:50
last_editor: "Cody"
revisions: 6
tags: ["type=audit", "status=action required"]
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-29; exported 2026-10-04. Classified ARCHIVE. Dated security audit; superseded by the Phase 1 and Phase 2 reports.

# Security audit, 2026-08-20
# Security audit, 2026-08-20

Top-down audit from the public Internet inward. The live host and deployed configuration were
treated as authoritative; the repo and this wiki were supporting context only. Every claim below
was verified by request or by reading live configuration, not inferred from documentation.

> **MANUAL ACTIONS ARE IN THE NEXT SECTION.** Two Critical findings are still open and can only be
> closed by Cody. Everything else in this page is either already fixed or is context.

## Verification gaps, stated up front

- ~~**ufw rules could not be read**~~ — **RESOLVED 2026-08-28, and the answer is the bad one.**
  `/etc/ufw/ufw.conf` contains **`ENABLED=no`**, while `ufw.service` reports `active (enabled)`.
  That combination means the unit starts and then installs **no rules**: the "active" status is
  misleading. So ufw is **not** filtering the LAN, and C1 and C2 do **not** drop to Medium — they
  stand at Critical with no mitigating control. *Caveat: the live nftables ruleset itself still
  could not be read (no passwordless sudo), so this rests on `ufw.conf` plus the unit state, not
  on `ufw status verbose` output. Run that to confirm.*
- No scan was performed from an external host or a second LAN device.
- No image CVE scanning: trivy, grype, gitleaks and semgrep are not installed and permission to
  install was not sought.
- Authentik user enumeration was blocked by tooling policy, so privilege review used group
  membership counts and Jellyfin's user list instead.
- **One read-only violation:** probing the health API required a POST, which created
  `filing_cabinet/health/raw_exports/HealthAutoExport_2026-08-19_23-36.json` (31 bytes) and one
  line in `logs/health_requests.log`. It overwrote nothing. Both were left in place rather than
  modified further. Safe to delete.

---

## MANUAL ACTIONS REQUIRED

Ordered by risk reduction. Items 1 and 2 are what stand between any device on the LAN and root on
this host.

### 1. Check the firewall first  — DONE 2026-08-28: `ufw.conf` says `ENABLED=no`; ufw is not filtering
```
sudo ufw status verbose
```
Five seconds, and it may reclassify the two Critical findings below. Everything marked Critical
assumes the LAN can reach these ports, which could not be disproved.

### 2. SABnzbd: set a username and password  (Critical, C1)
Web UI is fully open: `curl http://10.0.0.218:8082/config/` returns **200** with no credentials.
**Port corrected 2026-08-28: SABnzbd moved 8080 → 8082** so UniFi OS Server could take 8080.
Re-verified still open on the new port.
`sabnzbd.ini` has `username = ""`, which disables the login entirely.

```
SABnzbd -> Config -> General -> set username and password
```
**The API key is unaffected, so Radarr and Sonarr keep working.** SABnzbd runs as the host user
`cody` (not in a container), and its post-processing scripts execute as that user.

*Not done by the assistan: credential-setting operations are refused by tooling policy, and
editing `sabnzbd.ini` directly is the same action by another route.*

### 3. mylar3: enable authentication  (Critical, C2)
`authentication = 0`, `http_host = 0.0.0.0`. `curl http://10.0.0.218:8090/config` returns **200**.
Runs as `cody` from `services/mylar3/.venv`.

```
edit services/mylar3/config.ini -> authentication = 1, set http_username / http_password
sudo systemctl restart mylar3
```
**Do not bind it to loopback.** `mylar3.service` is a system unit (needs sudo) and
Homepage's widget reaches it over the LAN address, so rebinding breaks the dashboard.

### 4. Restart Jellyfin to activate the proxy fix
`KnownProxies` has been set to `127.0.0.1` and written to `network.xml`, but **Jellyfin only reads
network configuration at startup**. Until it restarts, every client still appears as `127.0.0.1`.
There were zero active streams when the change was made.

### 5. Off-host backups  (High, H3)
Needs a B2 or R2 key. `services/backups/offhost-sync.sh` is written and waiting. See
[Stack backups](http://10.0.0.218:6875/books/runbook/page/roadmap-and-open-work).

### 6. Reboot, and apply the outstanding security update
`/var/run/reboot-required` is present. One security update pending. `unattended-upgrades` is
active, so this is a restart, not a neglected patch queue.

### 7. Remove the dead nginx site
`/etc/nginx/sites-enabled/homeassistant` proxies `haos.local` to `192.168.122.108:8123`, a libvirt
VM that no longer runs. It returns 502 and is the only enabled site, so nginx on `0.0.0.0:80` is
currently inert. Delete the file and reload.

### 8. Stop Plex
Still listening on `*:32400`, still pending the authorization recorded on the roadmap.

### Decisions, not tasks

- **`cody` is in `docker`, `lxd` and `libvirt`.** Each is independently root-equivalent, and each
  converts any code execution as `cody` into full host compromise. Removing them breaks most of
  the operational tooling in this stack. Architectural call.
- ~~**Health API on `0.0.0.0:8240`.**~~ **Decided and done, 2026-08-28: retired entirely.** The
  premise above was wrong — there was no phone export left to break. The last genuine POST was
  **2025-09-18**, and the endpoint's parser had been missing since a rename, so every POST after
  that returned `{"status": "error"}` regardless. See *Services → Health API*.
- **Komga's plaintext OIDC redirect** can be removed from Authentik in seconds, but it breaks SSO
  login for anyone using `http://10.0.0.218:25600` rather than `read.avrana.net`.
- **Jellyfin API key hardcoded** at `services/authentik/blueprints/avrana-enrollment.yaml:183`.
  Rotating means changing Jellyfin and the blueprint together, then re-applying.

---

## Already remediated, 2026-08-20

| Finding | Change | Evidence |
|---|---|---|
| **H2** Radarr accepted unauthenticated administration from the LAN | `AuthenticationRequired: DisabledForLocalAddresses -> Enabled` | unauth UI `200 -> 302 /login`; API with key still `200`; Recyclarr and Seerr unaffected |
| **M2** Jellyfin saw every client as `127.0.0.1` | `KnownProxies: [] -> ["127.0.0.1"]` | written to `network.xml`; **pending restart** |

Lockout risk was checked before enabling Radarr auth: `radarr.db` holds the account `rcnechamkin`
with a password set. Originals are in
`/mnt/avrana_media/.backups/sec-remediation-20260820T071153Z/`.

Radarr was the only one of the three misconfigured. Sonarr (`401`) and Prowlarr (`302`) were
already correct, which made this a slip rather than a policy.

---

## Findings

### Critical

**C1. SABnzbd: unauthenticated admin UI, host user, all interfaces.** **CLOSED 2026-08-28.**
A username and password are now set (`avrana-admin`, credentials in
`services/bare-metal-auth.env`, mode 600). Anonymous `/`, `/config/`, `/config/switches/`
and `/config/general/` all 303 to `/login/`; the form login succeeds and reaches
`/config/switches/`. Applied through SABnzbd's own `mode=set_config` API, which takes
effect live — no root, no restart. **`api_key` and `nzb_key` are byte-identical**
afterwards, so Radarr, Sonarr, Prowlarr, Shelfmark and Homepage were unaffected; all five
were re-tested and pass. Note the port is **8082**, not 8080 as written below.
Historical text follows.

~~`0.0.0.0:8080`, runs as
`cody`, who holds three root-equivalent groups. Any LAN device reaches `/config/` with no
credentials, sets a post-processing script, and executes code as `cody`. `inet_exposure = 0`
limits Internet exposure only and does nothing on the LAN. **Open.**

**C2. mylar3: authentication disabled.** **CLOSED 2026-08-28.** `authentication = 2`
(forms login) with a username and password set. Mode **2** was chosen over mode 1
deliberately: both exempt `/api`, but mode 1 puts HTTP basic auth in front of every page
while mode 2 gives a real session login. `encrypt_passwords = False`, so
`check_credentials` compares plaintext and the ini edit is deterministic. Restarted via
Mylar's own `cmd=restart` API, which `os.execv`s in place — same MainPID, `NRestarts` 0,
no root needed. Anonymous `/`, `/home`, `/config`, `/history` and `/manage` now 303 to
`/auth/login` leaking no app content; the API answers with the key and returns 460
without it or with a wrong one. Homepage (the only API consumer) verified with `getIndex`
from inside the container. Credentials in `services/bare-metal-auth.env`.

### High

**H1. Health API: unauthenticated write plus subprocess execution.** **CLOSED 2026-08-28 —
retired, not patched.** `api/health.py` served an unauthenticated `POST /api/health` on
`0.0.0.0:8240` as `cody`, writing caller-supplied JSON to disk and spawning
`subprocess.run(["python3","-m","filing_cabinet.health.parse_health_export"])`. Re-confirmed live
before removal: an anonymous POST from the host returned HTTP 200 and wrote a file.

The 2026-08-20 note that "every available fix breaks the phone's health export" was mistaken.
The last genuine POST was **2025-09-18** (`logs/health_requests.log`); the only later entry is a
`127.0.0.1` probe from the audit itself. And the parser named in the subprocess call **does not
exist** — the file on disk is `parsers/parse_healt_export.py`, misspelt — so the code-execution
leg was already dead and every POST for ~14 months returned `{"status": "error"}` after writing
its file. Nothing consumed the endpoint, and `health.avrana.media` is NXDOMAIN.

`health_api.service` and `cloudflared-health.service` (both *user* units) are disabled and their
unit files moved to backup; `~/.cloudflared/config-health.yml` is removed; `api/health.py` is now
an importable stub with no `router` and no `app`, so `api/start_api.py`'s
`from api import health` still behaves exactly as before and the endpoint cannot come back by
accident. `SECRET_KEY = "letmein"` is gone. Verified: connection refused on 8240, no connector
process, 40/40 containers up. Rollback under `/home/cody/backups/health-api-retire-<stamp>/`.
**Residual:** the `health-avrana` tunnel object still exists account-side (no connector, no DNS),
and `watch-health.service` still watches the dead drop directory — both need the operator.

**H2. Radarr unauthenticated from LAN.** **Fixed.**

**H3. Backups unencrypted, co-located, destroyable by the same account.** 762 MB at mode 775 on
`/dev/sdb1`, the same disk as the media. No encryption artifacts, no off-host copy, no timer. Only
`olivetin` mounts them, correctly read-only. Every host-compromise path ends with delete access to
the only copy. **The one finding with no recovery path. Open.**

**H4. `cody` in `docker`, `lxd`, `libvirt`.** Not independently exploitable. It is the amplifier
that turns C1, C2 and H1 from service compromise into host compromise. **Open, architectural.**

**H5. Home Assistant runs as root on the host network.** Caps `CHOWN, SETUID, SETGID, DAC_OVERRIDE,
FOWNER, KILL, NET_RAW`, `0.0.0.0:8123`, image not digest-pinned, newest addition to the stack. Host
networking means a compromise reaches every loopback-bound service: Authentik `:9000`, Komga
`:25600`, Seerr `:5055`, connector `:8092`, none of which expect hostile callers on `127.0.0.1`.
**Mitigating and verified:** it mounts only its own config directory. No Docker socket, no host
paths, so there is no direct escape. **Open.**

### Medium

| # | Finding | Evidence |
|---|---|---|
| M1 | Komga OAuth redirect over plaintext HTTP | `strict:http://10.0.0.218:25600/login/oauth2/code/authentik` |
| M2 | Jellyfin saw all clients as `127.0.0.1` | **Fixed, pending restart** |
| M3 | Live Jellyfin API key and OIDC secrets in Authentik blueprints | `avrana-enrollment.yaml:183` plus 3 more files. Correctly gitignored, therefore unversioned |
| M4 | Unmanaged nginx on `0.0.0.0:80` with a dead upstream | `proxy_pass http://192.168.122.108:8123` returns 502 |
| M5 | Reboot pending, 1 security update outstanding | `/var/run/reboot-required` |
| M6 | Plex still on `*:32400` | Awaiting retirement authorization |
| M7 | `whisper-flask` on `0.0.0.0:5005` as `cody` | Undocumented; Flask server posture unverified |

### Low

`avrana-imax-verify` `/results` and `/history` unauthenticated on the LAN (film titles only).
Homepage dashboard unauthenticated on `10.0.0.218:3000`, disclosing the service inventory. Two
failed `cloudflared` units retain enabled flags. BookStack, MariaDB and Shelfmark on version tags
rather than digests.

---

## False alarms, and things that are correct

**Do not "fix" these.** Each looks alarming and is adequately controlled.

- **Docker socket proxies are properly constrained.** All three mount `docker.sock` as `:ro`, which
  does **not** restrict API operations, but the environment does: `EXEC=0`, `POST=0`, `VOLUMES=0`,
  `IMAGES=0`, `NETWORKS=0`, `SYSTEM=0`, and no host port binding. `olivetin-docker-restart` has
  `POST=1` but `CONTAINERS=0` and `EXEC=0`. **Compromising Homepage or OliveTin does not yield
  container escape.** This is the best-designed control in the stack.
- **World-readable `.env` files are contained.** Eight files at 664, but `/home/cody` is 750, so no
  other local user can traverse in.
- **Git history holds no real secrets.** The three pattern matches are empty template values
  (`SPOTIFY_TOKEN=`, `GOODREADS_API_KEY=`, `FITBIT_CLIENT_SECRET=`). No `.env` is tracked today.
- **Image pinning is good.** 23 of 32 containers are digest-pinned; the 9 that are not are locally
  built. An earlier pass reported this as a finding and was wrong: `docker ps` shows the run
  reference, not the resolved digest. Use `docker inspect --format '{{.Config.Image}}'`.
- **Authentik authorization is sound.** Every OAuth redirect URI uses `strict` matching, no
  wildcards. `skip_path_regex` is empty on all three proxy providers, so there are no
  unauthenticated bypass paths. Enrollment requires an invite
  (`continue_flow_without_invitation=False`).
- **The portal, kindle connector and OliveTin publish no host ports.** The embedded outpost cannot
  be bypassed, which is what makes the portal's trust of `X-authentik-*` headers safe.
- **No member can escalate through Jellyfin.** Only `Cody` holds `IsAdministrator` across 10
  accounts.
- **`comics.avrana.media` and `health.avrana.media` are NXDOMAIN.** Both tunnels run, neither
  resolves.

---

## Actual external attack surface

Ten hostnames, one tunnel, no inbound port forwarding, `404` catch-all for anything else.

| Hostname | Backend | Auth boundary |
|---|---|---|
| avrana.net | portal :8095 | Authentik outpost, `avrana-users` |
| ops.avrana.net | olivetin :1337 | Authentik outpost, `authentik Admins` |
| kindle.avrana.net | kindle connector :8096 | Authentik outpost, `avrana-books` |
| auth.avrana.net | Authentik :9000 | Authentik itself |
| contribute.avrana.net | connector :8092 | OIDC in-app |
| watch.avrana.net | Jellyfin :8096 | **Jellyfin only** |
| read.avrana.net | Komga :25600 | Komga only |
| listen.avrana.net | ABS :13378 | ABS only |
| request.avrana.net | Seerr :5055 | Seerr only |
| books.avrana.net | CWA :8083 | CWA via LDAP outpost |

## Attack chains

**A. LAN to root, the most plausible.** Guest phone or IoT device compromise, then
`10.0.0.218:8080` SABnzbd with no credentials, then a post-processing script, then code execution
as `cody`, then the `docker` group, then root, then the backups are deleted. Every step verified
except the ufw question. mylar3 `:8090` is the identical chain.

**B. Internet to member.** `watch.avrana.net`, Jellyfin credential stuffing. Rate limiting was
ineffective because all clients appeared as `127.0.0.1`; the `KnownProxies` fix addresses this once
Jellyfin restarts. Ends at a non-admin media account.

**C. Lateral through Home Assistant.** Integration compromise, root in a host-network container,
reaching every loopback-bound service. Still needs credentials at each, and HA cannot escape to the
host directly.

## Summary

The Internet-facing perimeter is well buil: Cloudflare Tunnel with no inbound ports, strict OIDC
redirects, invite-only enrollment, a `404` catch-all, and three services correctly behind the
outpost with no published ports.

The risk is almost entirely on the LAN, and it comes from the services that were never
containerised. The discipline applied to Docker was not applied to the systemd units beside it.
The single unrecoverable risk is backups.
