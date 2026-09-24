# Optional one-way publishing design

Status: designed, not implemented or activated. No BookStack writes, token creation or permission changes were performed. Existing safe API credentials were not established. This is independent of the offline wiki inventory used in the migration.

BookStack provides a REST API documented at an instance's `/api/docs`; API access requires the corresponding role permission. The [official API reference](https://demo.bookstackapp.com/api/docs) documents page reads, creation and updates. Before implementation, verify the deployed instance's supported fields without changing its configuration.

## Contract

- Source: reviewed Markdown at an explicitly selected clean Git commit. Target: dedicated, explicitly mapped BookStack pages. Existing archive pages stay outside the mapping by default.
- Execution: an operator invokes `publish --plan` first, reviews a content diff and target list, then separately approves `publish --apply <plan>`. No hooks, scheduled job, install-time side effect or Git dependency.
- A versioned mapping assigns a stable document key, Git path, page ID and expected parent. Renames preserve the key/page ID. Duplicate keys/IDs, path traversal, symlinks, missing files and wrong parents fail closed.
- Credentials are supplied by a private external file or environment, never a command-line value, log, plan artifact or repository file. Keep TLS verification on, restrict the configured origin, and reject cross-origin redirects so authorization cannot leak.
- GET only in planning. Fetch each mapped page; compare canonical Markdown plus title/parent against the desired state. No changes means no request in apply mode. Do not match solely by title.
- The plan binds commit hash, source hashes, remote IDs, remote content fingerprints and expected timestamps. Re-read immediately before apply; abort on drift. This detects most concurrent changes but does not claim atomic compare-and-swap if the API lacks it. Avoid concurrent editors during a publish window.
- Apply validates the plan schema and allowed fields, recomputes desired content from the bound commit, and verifies the configured origin and mapping; it does not execute arbitrary URLs or payloads supplied by a plan. Serialize publisher runs for each target. Remote human edits still require the drift checks above.
- PUT only explicitly approved changed fields. Preserve unrelated permissions/tags unless included in the reviewed plan. Read back each successful update and verify content. HTML-only archive pages require explicit conversion review, not an implicit overwrite.
- Preserve the pre-update values of every changed field in a private rollback artifact before writing. Plans and rollback artifacts may contain private wiki content: store them outside Git with restricted access and redact them from routine logs.
- Creation is separate and opt-in. Record returned IDs durably outside normal Git operations; on uncertain POST outcome, stop and reconcile instead of blindly retrying and duplicating pages.
- Never DELETE, never access the database, never recreate infrastructure, never change credentials to make publishing work. Removing a source file produces a report-only orphan warning.
- Bounded timeouts/backoff; no blind retries of uncertain writes. A failed publish reports per-page outcomes and stops. It cannot block or change `git pull`, `git push`, commits or local documentation use.

## Local validation before activation

Use mocks for unchanged/update/create plans, remote edit conflicts, duplicate mapping, unsafe path, wrong parent, HTML-only source, authentication failure, timeout, rate limit, redirect refusal, tampered plans and uncertain create outcome. Assert that dry-run never sends a write, that no delete operation exists, and that a second plan after verified apply contains no changes, including server formatting normalization. Keep fixture pages synthetic and credentials absent.

An eventual disposable-page test still requires a confirmed safe credential and operator-approved scope. No such live test was attempted. Rollback is a separately reviewed update from preserved prior content, never database restoration or automatic deletion.
