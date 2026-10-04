# Audiobook Pipeline

> Promoted from the BookStack wiki on 2026-10-04 (page 31, "Audiobook Pipeline", last edited 2026-08-13) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/pipelines/31-audiobook-pipeline.md).

**Shelfmark → SABnzbd → Audiobookshelf.**
1. Shelfmark searches via Prowlarr, sends the grab to SABnzbd (usenet, :8080).
2. SAB writes to `/mnt/avrana_media/incoming`.
3. Shelfmark imports → `DESTINATION_AUDIOBOOK=/mnt/avrana_media/audiobooks`, `FILE_ORGANIZATION_AUDIOBOOK=organize`.
4. `PROWLARR_USENET_ACTION=move` cleans up the SAB job after a successful import.
5. Audiobookshelf serves from `/audiobooks`.

Also fed by **Libation** (Audible) writing to `/audiobooks` directly.
Verified: audiobooks land correctly in ABS.
