# Secrets: where each one lives

No secret value is in this repository. This file lists names and locations so that a rebuild does not
depend on memory. Values are in the deployed files (mode 0600), in every backup run, and where noted in
1Password.

## Only in 1Password (needed before any backup can be opened)

| Secret | Used by |
|---|---|
| Backblaze B2 bucket name, keyID, applicationKey | `services/backups/rclone.conf` (written by `offhost-setup.sh`) |
| rclone crypt password and salt | same file; **without these the off-host backup cannot be decrypted** |
| `cody` login password, SSH private keys | host access |
| SMTP2GO password (user `avrana-mail`) | Authentik e-mail stages, `services/backups/.env.alert`, Calibre-Web |
| Cloudflare account login | only if the tunnel credential must be re-issued |

## In the deployed tree and in every backup run

`stack-config/stack-config.tar.zst` in a backup run contains all of these. Variable names are in each
service's `.env.example`.

| Path under `/home/cody/avrana` | Contents |
|---|---|
| `services/authentik/.env` | Postgres password, `AUTHENTIK_SECRET_KEY`, LDAP outpost token |
| `services/authentik/blueprints/audible-connector.yaml`, `audiobookshelf.yaml`, `komga.yaml`, `omnibus.yaml`, `shelfarr.yaml` | OIDC `client_secret` for each application (`.template` files in Git have the value removed) |
| `services/authentik/blueprints/avrana-enrollment.yaml` | SMTP2GO password; a Jellyfin API key and the Komga admin e-mail and password, both embedded in expression policies that create member accounts |
| `services/authentik/blueprints/avrana-recovery.yaml` | SMTP2GO password |
| `services/avrana-audible-connector/secrets/` | `companion_token`, `oidc_client_secret`, `session_key` (regenerate with `scripts/gen-secrets.sh` only if also updating Authentik) |
| `services/beszel/secrets/` | hub and agent keys |
| `services/homepage/widget-secrets.env` | API keys for the dashboard widgets |
| `services/bookstack/.env` | database passwords, `APP_KEY` (until BookStack is retired) |
| `services/omnibus/.env` | `NEXTAUTH_SECRET` (also the database encryption key), ComicVine key |
| `services/{avrana-imax-verify,avrana-kindle-connector,calibre-web-automated,home-assistant,olivetin,recyclarr,shelfarr,tracearr}/.env` | API keys and tokens named in each `.env.example` |
| `services/backups/.env.alert` | SMTP settings for alert e-mail (0600; refused otherwise) |
| `services/backups/rclone.conf` | B2 key and obscured crypt passwords (0600; refused otherwise) |

## Outside the tree, captured by their own backup component

| Path | Component | Contents |
|---|---|---|
| `/home/cody/.cloudflared/` | `cloudflared` | tunnel credential JSON, `cert.pem`, ingress config |
| `/home/cody/.sabnzbd/sabnzbd.ini` | `sabnzbd` | Usenet server credentials, API key |
| `services/mylar3/config.ini` | `mylar` | API key, download client credentials |
| `/home/cody/docker/{radarr,sonarr,prowlarr}/config.xml` | `arr` | API keys |
| `services/calibre-web-automated/config/.key` | `calibre-web` (stored as `cwa.key`) | encryption key for `app.db` |
| `services/shelfarr/data/.encryption_keys`, `.secret_key_base` | `shelfarr` | database encryption |
| `services/libation/config/libation-master.key`, `AccountsSettings.json` | `libation` | Audible account |
| `services/shelfmark/config/.flask_secret` | `shelfmark` | session signing |
| `services/komga/config/application.yml` | `komga` | OIDC client configuration |
| Application databases | each component | user tables, password hashes, tokens |

## Rules

- Never print, paste or commit a value. Ask the owner to type it at a hidden prompt on the host.
- Never search the disk for a credential and never `source` a file found that way.
- `scripts/review_git_content.py --staged` must pass before every commit.
- Rotating a secret that appears in a blueprint means editing the deployed blueprint file as well as the
  service, or Authentik restores the old value the next time it applies blueprints.
