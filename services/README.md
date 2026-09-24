# Selected service source

These are reviewed source snapshots, not a production deployment bundle. See [the import manifest](../docs/findings/source-migration.md) for origins and deliberate transformations.

- `avrana-portal`: standard-library role-aware front door; requires trusted Authentik proxy headers in production.
- `avrana-kindle-connector`: service source plus offline validation tests. Running it can update CWA and Audiobookshelf; do not start it for a migration test. Its default sender is a non-deliverable placeholder.
- `avrana-imax-verify`: frame classification and webhook source. Only synthetic classification tests are approved here; server execution can write results and tag Radarr.
- `libation-status`: read-only status service source. Its SQLite settings are application behavior, not a safe method for opening forensic originals.
- `calibre-web-automated`: build-time patch and integration test source; no image build, container startup or production upgrade occurred.
- `avrana-audible-connector/connector`: application source, schema definitions, templates, stylesheet and dependencies; see the [28-file Audible addendum](../docs/findings/audible-source-migration.md). Companion, Dockerfile, deployment and tests are deferred. Do not import/run the app as a migration check: startup can initialize state.

No service `.env`, Compose deployment, database, profile, result history, image cache, media file or credential is included. The historical Dockerfiles are not a claim that all images are digest-pinned or currently buildable. Review before deployment.
