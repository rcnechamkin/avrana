# Recovery follow-up, 2026-09-27

Current status, 2026-09-28 04:24Z: operational recovery validated; storage preflight, Docker baseline and service health all pass. The invalid snapshot was archived and retired by the owner. See the closure section below for scope and remaining qualifications.

This follow-up was authorized by the owner to repair recovery defects and stop on uncertain or unsafe conditions. Development remains separate from production. No Git push was performed.

## Completed repairs

- Calibre-Web Automated: restored original LDAP settings, LDAP login mode, and default role 258 (viewer and download). Existing user rows were preserved.
- A user login initially still failed with an LDAP service-account error. Investigation found that recovery had restored the original encryption key under the backup name cwa.key while the application reads .key. The keys differed. The original key was restored to .key, and original SMTP settings were restored to keep encrypted configuration consistent.
- Preserved LDAP and SMTP credentials authenticated successfully from the Calibre container. No mail was sent. The owner confirmed that Web-Calibre login now works.
- Komga: reconstructed application.yml using its existing Authentik provider credentials, a fixed public callback, stable sub identifier, and automatic account creation. The archived runbook records that account creation was enabled before recovery.
- Komga's Authentik provider previously used the default email scope, which always reported email_verified=false. It now uses the existing verified-email mapping that reads each user's preserved email_verified attribute. No user was marked verified by this operation. The Komga blueprint was updated to preserve the mapping selection.
- Komga's API now advertises the Avrana provider. The public sign-in endpoint returns a redirect to Authentik with the correct callback. The owner confirmed that Komga login now works.
- The backup script now captures Komga application.yml with mode 0600 and includes Jellyfin metadata images. These restore-critical files were previously omitted. Shell syntax validation passed.

## Preservation and validation

Private checkpoints and rollback material are stored outside Git under /mnt/avrana_media/.backups/recovery-followup-20260927T235413Z. They include stopped-state Calibre and Komga database files, both Calibre encryption keys, a pre-change Authentik logical dump, the original Komga blueprint, and the original backup script.

Calibre and Komga database integrity checks passed. Calibre's four existing user rows and OAuth configuration rows were unchanged. Komga's six user rows, 15 role rows, and library-sharing rows were unchanged before user testing.

A fresh bind-mount audit compared device/inode identities for 86 mounts and found no stale mounts among those checked. Beszel could not be checked using the container stat command because the image lacks it. Do not treat that omission as a successful comparison.

A full checkpoint was started through transient user systemd unit avrana-recovery-checkpoint-20260927, at low scheduling priority, into the follow-up directory's final-backup subtree. This separate destination avoids pruning prior backup runs. The checkpoint completed successfully: 24 components, 219 MB, zero failed components. Every manifest file verified. The captured Komga configuration and Calibre active key match deployed bytes, and the Jellyfin archive includes metadata assets.

## Unsafe remainder

The kernel marks the LVM root recovery snapshot invalid and records I/O errors for dm-3. The dm-3 name identifies ubuntu--vg-root--recovery--snap. The current media array is mounted read-write, and the examined errors do not establish active array failure.

The invalid snapshot was not mounted, repaired, removed, or used as a restore source. The boot-verification and health units still report failure; those signals were not cleared to make the system appear recovered.

At the end of the first repair pass, Jellyfin artwork remained incomplete. The later online continuation below uses provider downloads rather than the invalid snapshot. Its newer database was not replaced. Full recovery still cannot be declared complete while the snapshot fault remains unresolved.

## Online continuation under the no-shutdown constraint

The owner subsequently prohibited service shutdowns and a device shutdown. This continuation has not stopped or restarted applications, Docker, mounts, or the device. It starts only read-only diagnostic units and isolated image-repair/backup jobs.

The storage classifier now distinguishes the exact dm-device read errors of the invalid recovery snapshot from active-array errors. The array remains mounted read-write with no ext4 errors recorded. Unclassified disk, root-volume, USB, and ext4 errors still fail verification. Nine boundary fixtures passed. The overall health check explicitly fails on the invalid snapshot; no failed-unit state was cleared.

The baseline checker now reads the preserved Mylar authentication mode and checks SABnzbd using its recovered API key, including rejection of an invalid key. Mylar's authentication=0 matches preserved recovery configuration; that access policy was not changed. The SABnzbd owner GUI password was not reset or guessed. The current storage preflight and Docker baseline pass. Overall boot validation still fails because of the snapshot alarm and its failed health unit.

A second Authentik comparison against the pre-change logical checkpoint confirms all 18 user records, 10 groups, 82 memberships, role memberships, four roles, 128 model-permission associations, six object-permission associations and five passkeys remain intact. Login/update timestamps were excluded; permission association surrogate row IDs were excluded because blueprint reconciliation can recreate equivalent associations. No effective permission difference was found.

Jellyfin artwork is being repaired through its supported remote-image download API, without a metadata refresh, SQL mutation, database replacement or media write. Candidate images must come from the item's TheMovieDb provider on image.tmdb.org. Image bytes are decoded before and after saving. Each item is compared immediately before writing and after; only image fields may change. Episode media size and modification time are checked on their read-only media binding. Any unexpected exception halts the batch.

Private per-item before/after ledgers, candidate URLs, results, original image associations and a consistent pre-pilot working database checkpoint are in the private follow-up directory's jellyfin-online subtree, outside Git. The download API implementation was reviewed in Jellyfin v10.11.11 RemoteImageController.cs and ImageSaver.cs. No recovery snapshot data was used.

Completed first artwork passes: 100 primary posters and 71 movie/series backgrounds restored and verified. Two seasons had no provider image and were left unchanged. The larger episode/portrait pass restores only missing episode images and portraits with preserved image references whose files are absent; it does not invent portraits for people who never had one. Final counts and checkpoint results are recorded below after the batch completes.

The continued backup repair uses the existing online SQLite backup helper for Jellyfin, excludes live DB/WAL/SHM members, and inserts the consistent database at the original restore path in the config archive. Artwork remains included. A temporary fixture archive verified the replacement and absence of live sidecars. Shell syntax passed; tar or compression failures now fail this component. The full backup source was retained in development after privacy review.

## Final online artwork results

The image jobs completed successfully with zero verification failures: 100 posters, 71 movie/series backgrounds, 442 episode thumbnails and 2,830 portraits. Two seasons, 70 episodes and two people had no provider candidate and were left untouched; one portrait file was already present and was preserved. This is not a guarantee of restored custom artwork choices: unavailable images and original custom selections cannot be reconstructed from the invalid snapshot.

A private, consistent post-artwork database copy was saved. Its users (14), permissions (46,584), preferences (25,233), display preferences (10), item display preferences (1,863) and custom item display preferences (17) match the pre-pilot checkpoint byte-for-byte at the row level. The supported image-only operations preserved non-image item fields and the checked read-only media files.

The final full online checkpoint completed successfully through avrana-online-final-checkpoint-20260927 at low priority, with a CPU cap, under the separate online-final-backup directory. This run uses the corrected consistent Jellyfin database capture. No applications were shut down or restarted during this continuation. Jellyfin, Calibre and Komga start timestamps are unchanged from before the online continuation.

The final checkpoint is online-final-backup/2026-09-28T00-55-40Z under the private follow-up directory: 24 successful components, zero failures, 1011 MB, all 107 manifest entries verified. The Jellyfin archive has exactly one consistent database, no live DB/WAL/SHM entries, and 3,453 artwork files. Its database passed integrity_check on a disposable copy; accounts, permissions, preferences and watch state match the post-artwork checkpoint. All 145 watch-state rows also match the pre-pilot checkpoint.

Final live diagnostics: storage preflight PASS, Docker baseline PASS, service health FAIL because the invalid recovery snapshot remains visible and services-health.service remains failed. No snapshot operation, mount change, application shutdown or device shutdown was attempted. Complete recovery is not claimed. Git changes remain uncommitted and unpushed.

## September 28 online verification and operator handoff

The owner authorized further online recovery and requested notification when sudo is required. Application/service shutdowns and device shutdown remain prohibited.

All 18 standalone SQLite artifacts from the 24-component checkpoint were copied into a new private restore-validation directory and passed full integrity checks. Calibre's backed-up key decrypted both preserved LDAP and SMTP ciphertexts offline using only the cryptography library; no service initialization or network credential use occurred.

Authentik's logical dump restored successfully with error-stop and a single transaction into the existing PostgreSQL 16.15 image, in a disposable container with network=none, no published ports, no production mounts, a read-only root filesystem, non-root UID 70, dropped capabilities and memory/CPU limits. All 215 public tables restored and every dumped COPY row matched a re-dump. Counts include 18 users, 82 memberships, 128 model-permission associations, six object-permission associations and five passkeys. The test container was disposed; no production PostgreSQL operation other than version/image/role-name inspection occurred.

BookStack's existing logical dump restored into an isolated MariaDB 11.8.8 process under non-root UID 101, with network=none, no ports/production mounts, read-only root filesystem, private tmpfs storage and limits. The test setup needed corrections for the image's /config volume, temporary-directory defaults and current entity schema. After correction, all 41 tables restored and all dumped INSERT rows matched. Its backed-up BOOKSTACK_APP_KEY matches the running container's APP_KEY. The generated application-file key differs, so the running environment remains essential restore material. No production BookStack database query, initialization, reconfiguration or restart occurred. Full application-stack disaster restoration has not been simulated by these database tests.

All eight Authentik OIDC providers passed public discovery, configured signing behavior and an authorization request using their registered HTTPS callback. The three proxy providers intentionally have no asymmetric signing key and empty JWKS; this matches their preserved symmetric-signing configuration. These checks do not replace a human browser login through each application's code exchange and profile association. Web-Calibre and Komga already have owner-confirmed successful logins; additional login checks were requested.

The owner supplied sudo lvs/dmsetup reports: root-recovery-snap is a 20 GiB classic snapshot at 100% with Invalid status; ubuntu-lv is active/open at 58.09 GiB. The snapshot is not mounted. Owner-supplied SMART reports show SSD overall-health PASSED, no logged errors, no reallocated/uncorrectable/CRC errors. The media drive has zero reallocated/pending/offline-uncorrectable/CRC counts and no logged errors; its USB bridge does not provide complete overall-health status, so its reported pass is attribute-based.

A guarded, owner-operated sudo script was prepared outside Git in restore-validation-20260928/retire-invalid-snapshot.sh. It checks boot/device UUIDs, root mount identity and writability, the snapshot's exact name/origin/size/Invalid status, zero opens and no mount; archives all 20 GiB of COW bytes; verifies original and archived hashes; saves LVM metadata; then requires the operator to type REMOVE_INVALID_SNAPSHOT before removing only that snapshot. Its syntax passed. This is an explicit exception to evidence preservation, with verified retained COW data and metadata. It does not deactivate the origin or stop services. It has not been reported complete.

A monitoring candidate and boundary fixtures were prepared privately, not deployed. They can distinguish exact, captured same-boot historical snapshot errors after verified retirement, while retaining failures for reactivation, different root/boot identities, newly reused dm device errors, new invalid-snapshot events and unrelated storage failures. The current alarm remains in place pending the operator action.

A final read-only privileged inspection was prepared as restore-validation-20260928/final-root-verify.py. It compares host/container bind device-inode identities using /proc process roots, including containers without stat; checks descendants for deleted-open persistent state files; and records current LVM and mount reports privately. It requires the owner to run sudo and has not yet been executed. It does not change mounts, volumes, services or credentials.

The owner subsequently confirmed successful normal sign-in to all five additional applications: Audiobookshelf, Shelfarr, Omnibus, Audible contribution and Kindle. Together with the earlier Web-Calibre and Komga confirmations, all seven requested application login tests passed and opened the existing profile or authorized page. These confirmations cover the owner account, not every individual user account.

## Recovery closure after owner-operated snapshot retirement

The owner explicitly confirmed REMOVE_INVALID_SNAPSHOT after the guarded script preserved and verified all 20 GiB of snapshot COW bytes and LVM metadata. At 2026-09-28T04:21:03Z the script removed only ubuntu-vg/root-recovery-snap. The private COW archive and before/after VG metadata remain preserved. The active ubuntu-vg/ubuntu-lv remains 58.09 GiB and mounted read-write. This does not recover any data that was already absent from the invalid snapshot.

The owner then ran the read-only root inspection. Its saved report verifies all 40 containers, all 88 bind mounts, zero stale mounts, zero unverified mounts and zero deleted-open persistent state files. This closes the earlier Beszel inspection omission. All inspected services are running, with no unhealthy or starting health status.

After independently checking the receipt, device UUIDs, root state, full mount audit and archive presence, the retirement-aware storage checker was deployed. It acknowledges only eight exact pre-retirement kernel lines for this boot and the unchanged origin UUID, and only while both snapshot and COW mappings are absent. It still fails on new/unidentified storage errors, new invalid-snapshot events, reactivation or inconsistent receipt data. Boundary fixtures passed. Historical logs were not deleted.

Both services-health.service and avrana-boot-verify.service were rerun together and completed successfully at 2026-09-28T04:24:23Z. Storage preflight PASS, Docker baseline PASS, service health PASS; BOOT VALIDATION CLEAN. There are no failed user units, and the validation reported no failed system units. No reset-failed was used to hide a fault. No production service or device shutdown/restart occurred during this continuation.

Operational recovery is complete on the checked scope: preserved identity/permissions, seven owner-confirmed application login paths, provider/callback configuration, consistent tested database backups, restored artwork, persistent mount/state verification and current storage/service health. At operational closure, the artwork qualification was 74 unavailable provider images/original custom selections. The later alternate-provider pass below reduced missing images to two portraits. Other qualifications remain USB-limited media SMART overall status and untested full-machine/off-host disaster restoration. These are not active faults repaired by clearing an alarm. Development changes remain uncommitted and unpushed.


## Alternate-provider artwork follow-up

The owner explicitly requested continuing the remaining artwork checks. Jellyfin's available remote-image providers were inspected for all 74 gaps. Exact item-level provider candidates restored both remaining season posters and all 70 missing episode thumbnails, using TheTVDB for 71 items and TheMovieDb for one. OMDb episode candidates were not used where they appeared to be series artwork.

The 72 image-only operations completed with zero failures. Sources and served images decoded successfully; item records changed only image fields, and checked episode media sizes/timestamps remained unchanged. A second served-image pass verified all 72 tags and images. A fresh private consistent database copy passed integrity_check; all 14 users, 46,584 permissions, 25,233 preferences and 145 watch-state rows match the checkpoint immediately before this pass.

Two portraits remain unavailable: Ingrid Tesch and Laurie Craig. Neither configured provider returned a portrait; their exact referenced files are also absent from the preserved legacy directory. A Wikidata lookup by preserved TMDB person IDs supplied no image. No speculative name match or paid stock image was imported. This preserves identity accuracy and does not reconstruct unavailable original custom selections.

The follow-up evidence and image ledger remain private under jellyfin-online/alternate-source-audit in the recovery directory. The separate full online backup completed at low scheduling priority with a CPU cap: artwork-final-backup/2026-09-28T04-56-58Z, 24 components, zero failures, 1013 MB. All 107 manifest entries verified. The Jellyfin archive contains 3,525 artwork files and exactly one consistent database without live WAL/SHM; its disposable database copy passes integrity_check and matches preserved accounts, permissions, preferences and watch state. Storage, Docker baseline and service health were revalidated successfully after the image pass. No application or device shutdown/restart was performed.
