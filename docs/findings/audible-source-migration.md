# Audible source migration

Recorded 2026-09-23. This is a development-only source snapshot, not a deployment or runtime verification. Production files were read and left unchanged.

The [file-level manifest](audible-source-migration.json) lists 28 individually selected files, exact source paths, and SHA-256 hashes before and after migration. It includes the connector application, schema migration definitions, templates, stylesheet, and dependency declaration. The email-shaped UI placeholder in `app/templates/connect.html` was replaced with `reader@example.invalid`; other files are byte-identical to their source.

Review used text decoding, Python AST parsing, credential-pattern and sensitive-assignment checks, and checks for personal identifiers and production filesystem paths. The two flagged cookie constants name cookies rather than contain credentials. These checks are heuristic and do not establish vulnerability-free code.

No application was imported or executed. No SQL migration ran. No dependencies were installed. The application can write its database or contact external services when run; inclusion here does not authorize execution.

Dockerfile, deployment configuration, companion components, credential-generation scripts, existing tests, personal fixtures, runtime data, and historical service documentation remain deferred. Tests were not imported because their shared fixture creates the application and requires a separate complete isolation review. This snapshot is not a self-contained deployment.
