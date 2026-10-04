# Libation

> Promoted from the BookStack wiki on 2026-10-04 (page 17, "Libation", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/services/17-libation.md).

Audible downloader/decrypter → writes to `/mnt/avrana_media/audiobooks`. Container `libation`. **No web UI**: all interaction is `LibationCli` via `docker exec`. Runs a **scan+liberate loop every 12h**.
- **Two Audible accounts** on one instance (shared DB dedups by **ASIN**). As of 2026-08-13 both `cnechamkin@` and `liammmurph95@` are added and scanned; **196/212 liberated**. Folders carry an `[ASIN]` suffix (relevant to the epub↔audiobook matcher).
- **~15-17 Audible-Plus titles cannot download** without an active membership (expected "content license denied").
- **OOM fix (2026-08-13):** `InProgress` staged to `/tmp`, a **RAM-backed tmpfs** under `mem_limit` 2g, so large books (e.g. *A Storm of Swords*) filled RAM and the memcg **OOM-killed** liberate (exit 137). Fixed by bind-mounting `/mnt/avrana_media/.libation-inprogress` → `/tmp` (disk) and raising `mem_limit` to 4g. Protects the native loop too.
- **Manual liberate gotcha:** `docker exec` does NOT inherit the compose env, so a manual run needs `docker exec libation LibationCli liberate --libationFiles /config -o Books=/data -o InProgress=/tmp` (else "Books directory is not set"). Simples: `docker restart libation`.
- **Progress widget:** the `libation-status` container (:8087, digest-pinned read-only python) serves library/downloaded/pending/state JSON, feeding a Homepage **customapi** widget under *Automation*.
