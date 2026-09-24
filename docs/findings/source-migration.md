# Source migration manifest

Initial 13-file import into the empty Avrana repository, 2026-09-23. Each path below was individually selected and inspected; no directory was copied recursively. Full source/import SHA-256 fingerprints are in [source-migration.json](source-migration.json). The subsequent [Audible addendum](audible-source-migration.md) records 28 additional application files and its separate hash manifest, bringing the selected import to 41 files. Original live files remain unchanged.

| Imported file | Treatment |
|---|---|
| `services/avrana-portal/portal.py` | Replaced personal sender address with explicit non-deliverable placeholder; configure before deployment |
| `services/avrana-portal/Dockerfile` | Byte-identical source import |
| `services/avrana-kindle-connector/kindle.py` | Replaced personal sender address with explicit non-deliverable placeholder; configure before deployment |
| `services/avrana-kindle-connector/Dockerfile` | Byte-identical source import |
| `services/avrana-kindle-connector/tests/test_kindle.py` | Removed live Docker/HTTP tests and replaced personal Kindle fixture with synthetic address |
| `services/avrana-imax-verify/imax_verify.py` | Byte-identical source import |
| `services/avrana-imax-verify/server.py` | Byte-identical source import |
| `services/avrana-imax-verify/Dockerfile` | Byte-identical source import |
| `services/avrana-imax-verify/tests/test_classify.py` | Byte-identical source import |
| `services/libation-status/status.py` | Byte-identical source import |
| `services/calibre-web-automated/avrana-patch/apply_avrana_patches.py` | Byte-identical source import |
| `services/calibre-web-automated/Dockerfile` | Byte-identical source import |
| `services/calibre-web-automated/tests/test_attachment_filename.py` | Byte-identical source import |

## Runtime and validation boundaries

Imported source can perform operational writes when explicitly run (Kindle updates CWA/ABS; IMAX can tag Radarr; CWA patch modifies image-build files). Importing it is not authorization to start it against production. Dockerfiles were reviewed as build source but no image build/run occurred. CWA tests need the upstream package and were not run against a live container. Kindle tests were deliberately reduced to offline cases. IMAX classification tests use synthetic distributions and never decode media.

The portal and Kindle source now contain a non-deliverable sender placeholder. They must not be deployed unchanged without reviewed configuration. CWA patch source includes later authentication/database-helper changes that its older README did not fully describe; a new local README explains scope without copying its restart instructions.

## Deferred source and excluded material

The recovered Kern-Ecosystem reference at adbc4b5 is preserved separately. No wholesale history import was made because tracked history includes personal records and binaries. Root Kern/filing-cabinet code, OliveTin restart actions, live Compose/environment/blueprint configuration, and backup/restore scripts require their own review before a later import. Audible application source was subsequently imported in the linked addendum; its companion components, deployment definition, Dockerfile, credential-generation tooling and tests remain deferred. Their relationships and configuration locations are documented now; deferral does not imply deletion or deployment change. The two live-changed files (root requirements and backup script) remain untouched.

Excluded: entire BookStack production subtree; databases/WAL/SHM; uploads; backups; logs; metadata/cache/media; private records; certificates/keys; user/session data; third-party runtime checkouts; generated files; symlinks; repair/rollback/cleanup scripts. The Komga compose symlink was not followed. No book/media title inventory or raw logs were committed.
