# First-Run and Default-Credential Checklist

> Promoted from the BookStack wiki on 2026-10-04 (page 37, "First-Run and Default-Credential Checklist", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/runbook/37-first-run-and-default-credential-checklist.md).

When standing up a service:
- Change any default admin password **immediately** (CWA, BookStack, etc.).
- Bind the published port to `10.0.0.218`, not `0.0.0.0`.
- Confirm the container is `healthy` and hits its `siteMonitor` endpoint.
- Add a Homepage tile (dedicated read-only creds for any widget).
- If it stores unique state, ensure a backup path exists **before** editing that state.
