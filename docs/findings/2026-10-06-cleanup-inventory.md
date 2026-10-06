# Clean-up inventory, 2026-10-06 (roadmap items 9 and 10)

Read-only survey of the recovery leftovers and the completed-download folder, so the owner can
release them with one decision each. Nothing was deleted. Sizes are `du` on the host.

## Recovery artifacts (roadmap 9)

| Item | Size | What it is | Suggested action |
|---|---|---|---|
| `/home/cody/jellyfin/` (root-owned, July 2025) | 420 MB | an old Jellyfin `docker/config` + `cache` tree from before the current layout; not referenced by any compose file | owner: `sudo rm -rf /home/cody/jellyfin` after a glance |
| `/home/cody/jellyfin-recovery/` | 4 KB | empty directory | remove |
| `/home/cody/recovery-check.py`, `/home/cody/recovery-retire.sh` | 12 KB | September recovery operator scripts (read-only inspection; snapshot retirement) | move into `docs/findings/` next to the recovery report, or delete; they are in the `kern-data`/home backup component either way |
| Docker images `avrana-audible-connector:premaint-20260922`, `avrana-libation-companion:premaint-20260922` | 162 MB + 535 MB | pre-maintenance rollback images from 2026-09-22; the services run on later builds | `docker rmi` both once the owner releases them |
| Dangling volume `authentik_database` | not measured | a named Postgres volume from the old Authentik layout; the live database is `services/authentik/data` (bind mount) and is restore-tested weekly | owner decision: it may hold the pre-recovery database; keep until the next restore test passes once more, then `docker volume rm` |
| Dangling volumes `komf_komf-config`, `tracearr_tracearr_{backups,data,postgres,redis}` | part of 1.0 GB reclaimable | left behind when those stacks moved to bind mounts | `docker volume rm` after the owner confirms nothing in them is wanted |
| 9 anonymous dangling volumes, 14 dangling image layers | see `docker system df` | build leftovers | `docker volume prune` and `docker image prune` (not `-a`) are safe |
| Unused tagged images (10, about 2.3 GB): `crocodilestick/calibre-web-automated:v4.0.6` 1.7 GB, `avrana-libation-companion-mock:local`, `python:3.12-slim`, `recyclarr:7.4.0`, `rclone/rclone:latest`, `curlimages/curl`, `shellcheck`, three `alpine` tags | 2.3 GB | superseded by the pinned digests the compose files use (`rclone/rclone:latest` by the pinned digest in `offhost-backup.py`) | `docker image prune -a` would remove them AND the premaint tags; prefer removing by name |

## Completed downloads in `/mnt/avrana_media/incoming/` (roadmap 10, bug hunt A18)

102 GB in 11 entries, 124 files, 7 entries untouched for more than 30 days. Written by the media
stack (SABnzbd, the *arr importers), Omnibus, Shelfarr and Shelfmark. Whether an item was imported
can only be confirmed in the importing app's history (no API key was used here).

| Entry | Size | Newest file | Note |
|---|---|---|---|
| `movies/Mission.Impossible.The.Final.Reckoning.2025.REPACK.1080p…` | 23.7 GB | 2025-10-11 | a year old; two copies of the same film |
| `movies/Mission.Impossible.The.Final.Reckoning.2025.1080p.Bluray…` | 18.6 GB | 2025-09-28 | |
| `movies/Orumcek Adam Yepyeni Bir Gun [Spider Man Brand New Day] 2026` | 13.6 GB | 2026-10-05 | fresh; probably still being imported |
| `movies/F1.2025.1080p.BluRay.x264-OFT-AsRequested` | 6.9 GB | 2025-10-09 | |
| `movies/Friendship.[2025].720p.WEBRip-LAMA` | 925 MB | 2025-08-29 | |
| `movies/_FAILED_Supergirl.2026…` | 477 MB | 2026-09-03 | failed download |
| `movies/*` (seven more) | ~1 MB each | | empty import leftovers (NFO/sample) |
| `tv/Fallout.S02E07.REPACK.2160p…`, `tv/Fallout.S02E08.REPACK.2160p…` | 17.4 + 18.6 GB | 2026-08-21 | |
| `tv/_FAILED_House of Mouse…` | 1 MB | | failed download |
| `comics/` (70 Ultimate Spider-Man issues) | 3.3 GB | 2026-08-21 | Komga library is on the array; these are the download copies |
| `Timothy Zahn - Thrawn (Unabridged) MP3` | 468 MB | 2026-08-13 | audiobook download copy |
| four ebook folders (Expanse ×2, Antimemetics, Lathe of Heaven) | < 6 MB | | |
| `incomplete/`, `.incomplete/`, `GetComics/` | 20 KB | | empty working folders |

Suggested action: in Radarr and Sonarr, "Activity > Queue" and the history for each title confirm the
import; everything confirmed imported (the two Mission Impossible copies, F1, Friendship, both Fallout
episodes, the comics and the audiobook once in Komga and Audiobookshelf) can be deleted: about 93 GB.
The `_FAILED_` folders can go now. For the future, SABnzbd's "Remove completed downloads after
import" (Radarr/Sonarr: Completed Download Handling > Remove) is the setting that stops A18 recurring;
it is a change to each app's settings, so it stays an owner step.
