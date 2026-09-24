# Avrana CWA patch source

Imported from live source on 2026-09-23 without executing it. The Dockerfile targets CWA v4.0.6. This is a development snapshot, not permission to build or upgrade production.

The patch modifies five upstream files through exact-match substitutions:

- Mail/helper/convert code separates MIME attachment display names from physical library filenames.
- User management adds local-password fallback for existing local accounts in LDAP mode. Its behavior depends on account state; the source comments' assertion about LDAP accounts is not an independently verified security guarantee.
- `scripts/cwa_db.py` adds write/close helpers expected by upstream callers.

The older live README primarily described attachment naming and omitted later database-helper changes. It was not copied as an authoritative upgrade runbook. Imported source comments retain historical descriptions; inspect the actual `EDITS` mapping for scope.

The imported integration tests require the upstream `cps` package. They were not run against production or a new container during migration. Local syntax review does not establish compatibility with a future upstream release. A later build must use an isolated workspace and reviewed version, then validate all substitutions and service behavior before any deployment approval.
