# Initial repository validation — 2026-09-24

This validates the selective development import, not production deployment or a new recovery checkpoint. Production forensics remain dated September 23. No BookStack/Jellyfin write or refresh was performed during final review.

## Source and documentation review

- Two manifests cover 41 imported files: 13 initial files and 28 Audible application files. Destination hashes match recorded import hashes; original selected source-file hashes were also rechecked and matched the recorded source hashes. No original source was changed.
- Independent source review checked file types, Python parsing, high-signal credential patterns and Dockerfile `COPY` inputs. All referenced build-copy inputs exist. No application container was built or started.
- Documentation reviewers checked onboarding, source hierarchy, recovery chronology, wiki inventory and the pilot plan. Corrected stale Audible deferral/counts, the overbroad TV-artwork claim, completed-versus-pending review status, historical Docker storage dependency, and wording that could imply optional publishing was committed work.
- Added archival ebook acquisition/matching caveats without importing media records or treating historical behavior as a newly tested workflow.
- Relative Markdown links resolve. The initial inventory has all 72 export-time wiki pages. Raw wiki bodies, authentication tables, databases and attachments remain outside Git.

## Offline checks

From the checkout:

```sh
python3 -B tests/run_offline.py
```

Passed: five staged-content-gate unit tests, two Audible schema tests using SQLite `:memory:` only, 16 synthetic IMAX classification cases, and four offline Kindle checks (27 total). No live API, credentials, production database, media file or container was used by these tests. Python source was also parsed without importing applications.

The portal authorization suite (`tests/test_portal_authz.py`, 72 tests, one documented `expectedFailure`) serves the real `services/avrana-portal/portal.py` handler on a loopback port inside the test process and checks the route matrix, leaks, malformed and duplicated `X-authentik-groups` headers, fixed redirect targets, `/account` escaping and response headers against synthetic identities in `tests/fixtures/identities.py`. It makes no network call beyond 127.0.0.1 and uses no real member data. The count above predates it.

The original Kindle live tests were omitted and its personal fixture replaced. Audible application/end-to-end tests were not imported because their shared fixture initializes application state; only the isolated in-memory schema invariants are tested here. CWA integration tests require its upstream package and were not executed. These boundaries are deliberate; passing local checks is not deployment validation.

The day-to-day local workflow, fixture rules and how to add a suite are in [DEVELOPMENT.md](DEVELOPMENT.md).

## UI harness (AVR-360)

`python3 -B tests/run_offline.py` also renders every portal and Kindle page offline, from their own code
with synthetic identities, and runs stdlib accessibility, copy and no-leak checks (`tests/test_ui_harness.py`)
plus a design-token drift check (`tests/test_token_drift.py`). Known defects are listed in
`tests/ui/harness/baseline.json`, each with the issue that fixes it; a finding outside that list fails the
run, and the baseline may only shrink.

The browser layer (Chromium, axe-core, Tab order, rendered target sizes, 200% text) is a development tool
for a laptop, not part of the offline suite and never run against production:
`python -B tests/ui/harness/run_ui.py`. It needs Node and a Playwright install kept outside the repository.
What it does not cover (real phones, screen readers, Safari, Firefox, anything behind Authentik) and how to
add pages are in [`tests/ui/README.md`](../tests/ui/README.md).

## Commit gates

Stage exact reviewed paths, then run:

```sh
git diff --cached --check
git diff --cached --name-status
python3 -B scripts/review_git_content.py --staged
```

The content gate reads indexed blobs, not potentially different working copies. It rejects common credential/private-key patterns, forbidden runtime paths, databases, archives, media/image files, binary/non-UTF-8 content, oversized files and non-regular index modes. It allows reviewed schema migration SQL, not arbitrary SQL dumps. Manual review remains necessary for personal data and secrets not recognized by patterns.

The initial staging review is recorded in the coordinator's session and commit. No push, sync hook, deployment or publisher activation is part of validation. The repository is a reviewable source/documentation baseline, not a complete production restore bundle.
