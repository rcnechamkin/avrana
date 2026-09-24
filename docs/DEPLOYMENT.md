# Development and deployment workflow

The private remote is `https://github.com/rcnechamkin/avrana`. At migration start it had zero size and no branches/commits. The authorized clone was created at `/home/cody/dev/avrana`, on `recovery/docs-source-of-truth`. Default SSH cloning failed host-key verification; HTTPS with the existing `gh` credential helper succeeded without changing SSH configuration.

The recovered `Kern-Ecosystem` checkout is source evidence, not this repository's history: HEAD `adbc4b5`, dated 2026-09-18. The comparison found 252 identical tracked regular files, two changed files (`requirements.txt`, `services/backups/avrana-backup.sh`), 26 recovered-only files and one excluded symlink. BookStack paths were excluded from this comparison. These counts describe that selected comparison, not every live file.

Import only individually reviewed source files. The file-level [initial manifest](findings/source-migration.md) covers 13 files; the [Audible addendum](findings/audible-source-migration.md) covers 28 more. Preserve the two changed sources and do not infer that the older copy is preferable. Root personal/Kern code, production Compose files, secrets-bearing templates and dangerous repair scripts remain deferred unless individually selected later.

Before committing: inspect status and exact diff; run offline tests; stage exact paths; inspect staged names and content; run the staged-content gate; confirm no production changes. A local commit does not deploy or push. Push requires operator approval.

Before a later deployment, select one service, compare its development file with the exact live target, preserve current live files, review restart/migration consequences, define rollback and obtain approval for production actions. Do not run compose from this checkout as a bulk deployment. No deployment automation or hooks are installed.
