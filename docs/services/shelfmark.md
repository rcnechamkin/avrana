# Shelfmark: 8084 (LAN)

> Promoted from the BookStack wiki on 2026-10-04 (page 16, "Shelfmark", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/services/16-shelfmark.md).

Manual book/audiobook search + request frontend (not a library manager). Container `shelfmark`, pinned `1.3.6`, runs `user: "1000:1000"`.
- Routes **Prowlarr → SABnzbd (usenet) → Shelfmark import**. Direct Download is off.
- **Mounts (scoped, not the whole array):** `incoming` + `audiobooks` + `books`. Narrowing to `incoming` alone breaks post-processing → imports fail "path not accessible".
- `downloads.json`: `DESTINATION_AUDIOBOOK=/mnt/avrana_media/audiobooks` + `FILE_ORGANIZATION_AUDIOBOOK=organize`. **`AA_CONTENT_TYPE_ROUTING` is a red herring** for the Prowlarr path.
- SAB cleanup via `PROWLARR_USENET_ACTION=move`; don't add SAB-side auto-delete (races the importer).
- **Metadata:** Hardcover provider wired in; the `HARDCOVER_API_KEY` field auto-strips a `Bearer ` prefix.
