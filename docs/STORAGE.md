# Storage

> **Update 2026-10-04.** Verified: Docker's data-root is `/mnt/avrana_media/docker` (on the USB array, not
> the SSD). The LVM recovery snapshot no longer exists. The array is 34% used, the root volume 49%.
> `comics_merged` is a read-only mergerfs union of `comics` and `comics_omnibus/library`. Backups are under
> `/mnt/avrana_media/.backups/` (mode 700); `/mnt/avrana_media/recovery-20260920` is mode 750. The 15-minute
> health check now verifies that the array is mounted, has the expected UUID, is writable and has no
> kernel storage errors.

Historical inventory observed 2026-09-23 using block-device and container mount metadata.

Update, 2026-09-28: the 20 GiB root recovery snapshot filled and became invalid. The owner archived and hash-verified its complete COW allocation and saved VG metadata, then removed only that snapshot. The active 58.09 GiB root volume remains read-write. The snapshot mount in the historical table below is no longer an available recovery source. Storage checks pass; private archived evidence is documented in [the recovery follow-up](findings/2026-09-27-recovery-followup.md).

| Path/device | Role |
|---|---|
| `/` | ext4 root LV, approximately 58.1 GiB, on the approximately 119 GiB `sda` SSD |
| `/mnt/avrana_media` | ext4 media array on `sdb1`, approximately 7.3 TiB |
| `/mnt/root-recovery-snap` | Read-only LVM recovery snapshot; post-deletion evidence |
| `/home/cody/avrana/services` | Live service definitions mixed with secrets and persistent state |
| `/home/cody/docker/jellyfin/config` | Current Jellyfin config, database and metadata |
| `/home/cody/docker/jellyfin/cache` | Current Jellyfin cache |
| `/mnt/avrana_media/.backups/avrana` | Local stack backups; secrets and databases, never Git |
| `/mnt/avrana_media/recovery-20260920` | Preserved recovery workspace, never a deployment target |

Media subtrees: `movies/`, `tv/`, `audiobooks/`, `incoming/`, `books/` (transient inbox), and `calibre-library/` (durable ebook library). The latter distinction comes from BookStack page 3 and the ebook pipeline; do not treat the inbox as a backup of Calibre. `/mnt/media` is documented as a stale root-filesystem directory, not the array; do not use it as a fallback.

Historical incident/recovery documentation records Docker's data-root at `/mnt/avrana_media/docker`. This was not freshly verified in the final documentation review. The recorded dependency explains why an unavailable array can affect the container estate as well as media libraries; never assume Docker state is isolated on the root SSD.

Archived ebook-pipeline page 32 (August 2026) describes CWA deleting inbox copies after import into the durable Calibre library. It also records acquisition false matches when a short title matched part of a different, longer title. Treat inbox files as transient and validate title/author/edition identity rather than assuming a successful download is the requested book. This workflow was not exercised during migration.

Jellyfin maps `movies` → `/data/movies` and `tv` → `/data/tv`, both read-only. Its Movies library also retains `/mnt` in options XML although no `/mnt` bind exists. This discrepancy needs a separate reviewed correction; changing it may change item identities/library membership, so it was not edited during artwork diagnosis.

Historical USB enumeration and mount failures caused empty-library incidents. Ordering alone does not guarantee a mount eventually starts after a device timeout. Never change fstab, mount units, LVM snapshots or Docker mounts during documentation work. Do not infer free space or snapshot capacity from older wiki values.
