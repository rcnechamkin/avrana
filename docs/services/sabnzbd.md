# SABnzbd: 8082 (LAN, bare-metal)

> Promoted from the BookStack wiki on 2026-10-04 (page 26, "SABnzbd", last edited 2026-08-28) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/services/26-sabnzbd.md).

Usenet downloader (`sabnzbd.service`, not a container). Writes completed downloads to `/mnt/avrana_media/incoming`. Container paths in Shelfmark/*arr must match these host paths exactly (identity mounts) so imports are same-mount renames with no Remote Path Mapping.
