---
bookstack_page_id: 29
title: "Health API: 8240 — RETIRED"
shelf: "Avrana Homelab"
book: "Services"
chapter: "Platform"
created: 2026-08-13 21:28:51
updated: 2026-08-29 04:04:01
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: STALE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-29; exported 2026-10-04. Classified STALE. The health API was retired on 2026-08-28.

# Health API: 8240 — RETIRED
# Health API: 8240 — RETIRED 2026-08-28

> **This service no longer exists.** Nothing listens on 8240, and the
> `health.avrana.media` tunnel connector is gone. Audit finding **H1 is closed.**

## What it was
A `uvicorn` process (`health_api.service`, a **user** unit) serving an
**unauthenticated** `POST /api/health` on **`0.0.0.0:8240`** as `cody`. It wrote
caller-supplied JSON straight into `filing_cabinet/health/raw_exports/` and then
shelled out to a parser. An iOS *Health Auto Export* shortcut was the only client.
A second user unit, `cloudflared-health.service`, published it as
`health.avrana.media`.

It was **not** related to `scripts/services-health.sh` / `services-health.timer`,
despite what this page previously claimed. That pair is the stack health monitor
and never touched port 8240. The earlier wording conflated the two.

## Why it was retired
- Last genuine phone POST: **2025-09-18**. The only newer line in
  `logs/health_requests.log` is a `127.0.0.1` probe from the 2026-08-20 audit.
- Its parser, `filing_cabinet.health.parse_health_export`, **does not exist** — the
  file on disk is `parsers/parse_healt_export.py` (misspelt). Every POST after that
  rename returned `{"status": "error"}` and only wrote a file. The endpoint's stated
  purpose had been broken for ~14 months.
- `parse_health_export.timer` was retired in the 2026-08-28 pass.
- **No consumer.** `services-health.sh`, Homepage and Home Assistant never
  referenced `:8240` or `health.avrana.media`. The `/api/health` URLs in those
  configs are Shelfmark's and Beszel's own endpoints.
- `health.avrana.media` is **NXDOMAIN** — the tunnel published nothing.

## What was removed
| Thing | Kind | State |
|---|---|---|
| `health_api.service` | user unit | disabled, unit file moved to backup |
| `cloudflared-health.service` | user unit | disabled, unit file moved to backup |
| `~/.cloudflared/config-health.yml` | tunnel ingress | moved to backup |
| `cloudflared-health.service` | **system** unit | already disabled by the 2026-08-28 systemd cleanup |
| `api/health.py` | source | replaced by an importable stub (see below) |

`api/health.py` was **not deleted**: `api/start_api.py` still does
`from api import health`. The stub exports no `router` and no `app` — exactly what
the original exported — so import behaviour is unchanged and the endpoint cannot be
revived by accident. The hardcoded `SECRET_KEY = "letmein"` went with it; it only
ever guarded a log-viewing `GET`, never the `POST`.

## Rollback
Everything is preserved under `/home/cody/backups/health-api-retire-<stamp>/`
(unit files, the ingress yml, the original `api/health.py`, the request log), and
the retirement is one commit. The tunnel's **credentials json is deliberately still
in `~/.cloudflared`** so `cloudflared tunnel delete health-avrana` remains possible.

```bash
# script + rollback instructions
/home/cody/avrana/deploy/systemd/retire-health-api.sh
```

## Still open
- **`watch-health.service`** (a **system** unit, still `enabled` and running) keeps an
  `inotifywait` on the now-dead `raw_exports` drop. Harmless — nothing writes there
  any more — but it is a stale startup mechanism. Removal needs interactive sudo:

```bash
sudo systemctl disable --now watch-health.service
```

- The Cloudflare **tunnel object** `health-avrana` (id `9c28d270-c64b-4fb9-8004-333e1af654fe`)
  still exists account-side with no connector and no DNS record. Deleting it is an
  outward-facing change and is left to the operator:

```bash
cloudflared tunnel delete health-avrana
```
