---
bookstack_page_id: 37
title: "First-Run and Default-Credential Checklist"
shelf: "Avrana Homelab"
book: "Runbook"
chapter: ""
created: 2026-08-13 21:28:54
updated: 2026-08-21 00:15:50
last_editor: "Cody"
revisions: 3
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/security/first-run-checklist.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified PROMOTE; current information is in `docs/security/first-run-checklist.md`.

# First-Run and Default-Credential Checklist
# First-Run and Default-Credential Checklist
When standing up a service:
- Change any default admin password **immediately** (CWA, BookStack, etc.).
- Bind the published port to `10.0.0.218`, not `0.0.0.0`.
- Confirm the container is `healthy` and hits its `siteMonitor` endpoint.
- Add a Homepage tile (dedicated read-only creds for any widget).
- If it stores unique state, ensure a backup path exists **before** editing that state.
