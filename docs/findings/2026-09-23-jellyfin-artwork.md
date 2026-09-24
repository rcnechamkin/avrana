# Jellyfin / Wholphin missing artwork

Investigation date: 2026-09-23 America/Los_Angeles. Production inspection and HTTP checks were read-only. No refresh, database mutation, asset copy, restart, permission change or media write was performed. Independent reviewers resumed after a temporary usage interruption and corroborated the database/file comparison. See [repair review](jellyfin-repair-review.md) for the remaining live-write gate.

## Conclusion and confidence

The failure is server-side: the September deletion removed metadata assets, and the backup function explicitly excludes `metadata`. Restoring configuration and the newer database recovered media/catalog state without the corresponding image files. This is a confirmed coverage gap, not evidence of a Wholphin-only cache problem.

Both preserved databases still contain movie/TV image records. In the current copy, Movie, Series and Season image records are absent; Episode image records declined from 512 to one. A likely subsequent step is Jellyfin removing missing image references during validation. The exact removal event/time was not traced. Jellyfin 10.11.11's [ValidateImages implementation](https://github.com/jellyfin/jellyfin/blob/v10.11.11/MediaBrowser.Controller/Entities/BaseItem.cs) removes references to absent local files, which is consistent with the observed transition but does not alone prove this deployment's call sequence.

## Current observations

- Container `jellyfin` is healthy; application reports 10.11.11; `GET /health` returns 200. The container has one recorded restart, not zero.
- `/config` maps to `/home/cody/docker/jellyfin/config`; `/cache` maps to its sibling `cache`. Movie/TV binds map to `/data/movies` and `/data/tv` and are read-only.
- Metadata directory: 10 images, 5,643,807 bytes; four person images and six library images. Existing images are owned by UID/GID 1000 with mode 0644. No observed permission failure explains the missing files.
- Movies XML retains both `/mnt` and `/data/movies`; `/mnt` is not mounted. This is a separate unresolved configuration discrepancy, not sufficient evidence to explain the metadata loss.
- Recent library options list TMDb image providers, with additional providers for movies/episodes. Provider configuration is not absent. No provider-authenticated fetch test was performed; absence of observed download failures is not proof the providers currently work.
- Chapter extraction and trickplay extraction are disabled in inspected library options. The current DB has 3,326 chapters, zero chapter image paths and zero trickplay records. Scrubbing previews are a separate configuration/history question; do not promise a poster refresh will create them.
- All 59 movies have TMDb and IMDb provider IDs and are not metadata-locked in the captured DB. An independent reviewer found all 584 tested movie/series/episode media paths present, with movie/series overview and serialized metadata retained.
- A bounded last-24-hour log check found six SQLite Error 5 messages at 2026-09-23 10:45Z (locking/active statements), plus missing-image errors. These are a separate contention concern; they are not the September Error 14 failure or proof of corruption. A provider download was not exercised.

## Database and filesystem comparison

Only disposable working copies were opened with SQLite. A fresh live DB+WAL capture had identical hashes before/after byte copying, and copied hashes matched. Full `PRAGMA integrity_check` returned `ok`. Golden archive members and rescued DB files were separately copied into private temporary directories; both also returned `ok`. Originals were never opened by SQLite.

| Measure | Morning archive DB | Rescued DB | Current captured DB |
|---|---:|---:|---:|
| Image records | 3,768 | 3,768 | 2,848 |
| Movie image records | 236 | 236 | 0 |
| Series image records | 46 | 46 | 0 |
| Season image records | 30 | 30 | 0 |
| Episode image records | 512 | 512 | 1 |
| Person image records | 2,832 | 2,832 | 2,836 |

All 2,848 current image paths are under `/config`. Sixteen referenced files exist; 2,832 are missing, all person-image rows. The surviving files include collection/data images outside `metadata`, explaining why the total is greater than the ten metadata images. Current catalog includes 59 movies, 12 series and 513 episodes; catalog presence does not imply artwork presence.

Live capture fingerprints (not reusable expectations after normal server activity):

```text
DB  a3e82a3fcc80a77b4e3a39a65e1c4298a1801c347d40edf07030422a4453c4e2
WAL c7d2cf321dd197325a93576b0d2a3aeba6a546b9419197694c9172ce3e9d805a
```

Anonymous read-only image endpoint samples returned 404 for one movie, one series and one person, while an existing box-set image returned 200 image/jpeg. This confirms differing server responses without relying on a Wholphin cache. Physical Wholphin validation remains with the user. Historical container logs include missing `/config/metadata/library/...` images after recovery; those old errors are not reported as current database corruption.

## Recovery sources

The golden `jellyfin/jellyfin-config.tar.zst` has no metadata members. The live backup script's Jellyfin function excludes that directory explicitly. The recovery `jellyfin/` directory contains rescued DB material, not the missing image tree.

The read-only snapshot has a legacy tree at `/mnt/root-recovery-snap/home/cody/jellyfin/docker/config/metadata`: 1,246 files, 421,370,725 bytes (1,176 JPG, 68 PNG, 2 SVG). Its location differs from current production. Of current missing references, **865 person images match exact relative paths there**, totaling 197,522,735 bytes independently checked. Comparing the preserved pre-recovery DB also finds 12 genre and 10 studio images (887 total matches, 204,349,157 bytes); those 22 extra assets lack current references. **Zero movie, series, season or episode image paths from that DB match this tree.** An older alternate archive was reported to contain 29 images; it was not established as a matching source for the current posters.

Independent comparison found identical image-path sets in the morning and rescued copies. The current copy has removed 925 paths and added five, producing the net reduction of 920. Restoring old database rows wholesale would discard newer application state and is not a repair proposal.

Do not copy all snapshot images by filename guess or restore the old DB. The snapshot postdates deletion and contains an older installation's state. Exact path matches make a limited portrait recovery candidate, not a complete metadata restore. Independent comparison, regular-file checks, JPEG-header checks and SHA-256 hashing of the 865 candidates completed. Full image decoding, identity/currentness checks, fresh no-clobber destination checks and approval remain required before a live copy.

## Repair decision — not executed

No observed permissions/path correction is sufficient to restore the missing posters. The available exact-match assets would restore only part of the portraits. The most useful next action is an **operator-approved one-movie missing-image regeneration pilot**, preserving the recovered DB and existing artwork.

Before the pilot: obtain a current consistent backup outside Git, capture item metadata/provider IDs and image list, preserve affected image files and hashes, verify DB-copy integrity, confirm the item is not locked, and define rollback with the operator. A refresh changes application state; it cannot be advertised as a reversible file-only operation. If rollback requires database restoration, stop and seek specific approval rather than restoring automatically.

Proposed API action, documentation only, against one operator-selected movie ID:

```text
POST /Items/<approved-movie-id>/Refresh?metadataRefreshMode=None&imageRefreshMode=FullRefresh&replaceAllMetadata=false&replaceAllImages=false&regenerateTrickplay=false
```

The version-matched [ItemRefreshController](https://github.com/jellyfin/jellyfin/blob/v10.11.11/Jellyfin.Api/Controllers/ItemRefreshController.cs) supports these parameters and requires elevated application authorization. This endpoint queues one item; it has no recursive parameter in this version. Credentials must stay outside Git and process arguments. Inspect provider failures and compare item state afterward; do not silently broaden scope if it fails.

Validate image HTTP response, dimensions and client rendering, preserve media checksums for the selected item if practical, and verify no media write occurred. Broad refresh, SQL mutation, database replacement, root operations, metadata deletion and service stops remain unapproved. Portrait recovery and backup coverage improvements need their own scoped plans.
