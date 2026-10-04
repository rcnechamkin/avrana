# BookStack archive

BookStack was the Avrana wiki from August to September 2026. It is being retired: its API token was lost
in the 2026-09-20 incident, and on 2026-10-03 the owner decided to preserve its content and stop running
it rather than repair it.

- `INDEX.md`: every page, its classification and where its content went.
- `raw/<book>/<id>-<slug>.md`: each page as authored, with its metadata as front matter. These are
  **not authoritative**; several describe things that are no longer true.
- `structure.json`: shelves, books, chapters and page order.
- `revisions.tsv`: metadata for all 350 page revisions (bodies are not copied).

Extraction on 2026-10-04 used the database dump and uploads archive from backup run
`2026-10-04T09-33-09Z`, loaded into a disposable MariaDB container with no network. The production
BookStack containers, database, volumes and credentials were not touched.

Not archived here: user accounts, password hashes, API tokens, sessions, activity logs, revision bodies,
and one user avatar image. They remain in the SQL dump and uploads archive inside every backup run for as
long as the `bookstack` backup component exists.

The production `bookstack` and `bookstack-mariadb` containers are still running. Retiring them (and
removing the `bookstack` component from the backup, the required-artifact list, the restore map and the
40-container baseline) needs the owner's approval.
