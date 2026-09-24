# Jellyfin artwork repair review — 2026-09-23

Status: design review only, reviewed again 2026-09-24. **The production repair gate is not met.** No refresh, restore, authentication extraction, or production write is authorized by this document. All forensic observations below are September 23 evidence, not a fresh preflight for a later repair.

See [the artwork finding](2026-09-23-jellyfin-artwork.md) for primary evidence. This review uses established observations; it does not imply another live scan.

## Evidence and interpretation

- The server health endpoint returns 200, while sampled movie, series, and person image requests return 404; a box-set image returns 200. This supports a server-side artwork problem rather than a general client-cache failure.
- Current working-copy evidence has 59 movies and 12 series with no image references. Movies retain provider identifiers and are not metadata-locked. Their lack of image references differs from missing person image files whose references survive.
- Morning and rescued database working copies retain substantially more image references. Database structural checks do not certify application-level completeness or justify replacing the live database.
- The older snapshot supplies exact relative-path matches for 865 missing person images, but no matches for the saved movie/TV image references examined. These are separate recovery opportunities.
- Six observed SQLite lock errors are contention evidence, not proof of corruption. Existing missing-file messages corroborate missing bytes. Neither observation establishes whether a provider download will succeed.

## Proposed single-movie pilot

This is a proposed API request, not an executable instruction or approved action:

```text
POST /Items/<explicitly-approved-movie-id>/Refresh
  ?metadataRefreshMode=None
  &imageRefreshMode=FullRefresh
  &replaceAllMetadata=false
  &replaceAllImages=false
  &regenerateTrickplay=false
```

The coordinator verified this route against the v10.11.11 controller; no recursive parameter is proposed. The enum/flag names alone are not a guarantee of isolation. Image refresh can create files, change image associations and cache state, contact providers, and queue asynchronous work. An HTTP success response does not prove that the refresh completed successfully.

Prerequisites before requesting approval:

1. Identify one movie by a privately reviewed ID and confirm it still lacks artwork. Record server URL, library, lock state, provider identifiers, descriptive metadata, current image list, filesystem path, and pre-request image HTTP status. Keep personal library details and authentication outside Git.
2. Confirm the running server version, read-only media mounts, absence of conflicting refresh/scan work, and the refresh implementation's behavior for this exact item type and flags, including related-item/provider work. Existing controller verification does not establish all downstream side effects.
3. Establish a fresh application-consistent recoverable checkpoint using a separately reviewed, expressly approved method; verify a disposable copy. The September 23 integrity result and a stable DB/WAL forensic capture are not automatically an operational rollback mechanism. Preserve checkpoint provenance privately.
4. Preserve affected image files/hashes, media size/mtime (checksum if practical), selected-item API responses and a bounded catalog/image-reference baseline. Record UTC start time and an operator-owned ten-minute observation window with no automatic retry. Agree on containment before sending the request.
5. Obtain approval for this exact single-item mutation and its rollback/containment limitations. Use existing credentials outside Git, logs and process arguments; do not regenerate credentials or broaden access. Send once, with exactly the reviewed parameters.

Acceptance requires a decodable image with nonzero dimensions returned for the selected movie, correct new associations/files, unchanged descriptive/provider data, existing images and media, and no unexplained unrelated item changes. Compare the bounded before/after baseline with concurrent activity, inspect provider/SQLite errors, and verify rendering in Wholphin separately. Do not infer success from request acceptance or the health endpoint.

On ambiguity, timeout, new errors or unexpected changes, send no additional mutation and report the evidence. The ten-minute window is an observation limit, not a cancellation of queued work. No retry, scope expansion, SQL edit, file deletion, service restart or database restore is authorized as a fallback.

### Rollback limitation

Restoring a whole pre-pilot database can discard concurrent watch history, user activity, and unrelated changes. Copying old SQLite files into a running service is not an acceptable rollback. Directly deleting new rows is also outside the permitted design. A provider refresh with replacement disabled is not inherently reversible.

Before execution, either demonstrate supported, sufficiently narrow rollback in an isolated test environment or obtain explicit acceptance of the remaining risk and a separately approved recovery procedure. A service stop, database replacement, or filesystem deletion requires its own approval; none is implied here. Until then, the pilot remains blocked.

## Alternative: restore only missing person images

Potential benefit: recover up to 865 already-referenced portraits without asking providers to modify database associations. This does **not** restore movie/series artwork or its lost references.

Before approval, build a private manifest from existing database references and exact candidate relative paths. Verify every source is a readable regular image, validate image type/content, reject symlinks and path escapes, and check dimensions where useful. Exact path equality alone does not prove that an older portrait is current or depicts the intended person.

Any approved implementation must target only absent destination files, avoid overwriting or following symlinks, handle destination races without clobbering files, and use narrowly specified ownership/modes consistent with the service. Do not recursively change permissions or copy the entire metadata directory. Record every created file and directory and its hash in an external private manifest.

Rollback would remove only files demonstrably created by that operation and still matching recorded hashes, with separate approval. Never remove pre-existing files, modified files, or nonempty directories indiscriminately. Concurrent server image creation and any cache effects require consideration even for this file-only option.

## Decision

Preserve current databases and all recovery evidence. Neither a broad refresh nor a database restore is warranted by the evidence. The single-movie pilot offers a focused way to test provider-based artwork recovery, but production execution still needs an approved checkpoint, bounded verification, and an accepted rollback/containment plan. The portrait option is narrower in database impact but remains a production write requiring approval.
