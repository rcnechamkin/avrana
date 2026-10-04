# Komga: 25600 (Tunnel: comics)

> Promoted from the BookStack wiki on 2026-10-04 (page 18, "Komga, Komf, and Kavita", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Note: Komf and Kavita are not deployed; their sections are history.
> Original: [archive](../../docs/archive/bookstack/raw/services/18-komga-komf-and-kavita.md).

Comics/manga server. Container `komga`. Sees `/mnt/avrana_media` **read-only**. Needs an executable `/tmp` (SQLite JNI).
- **Komf** (:8086, `--profile legacy`): Komga/Kavita metadata fetcher; remapped off 8085 to avoid Complete Series.
- **Kavita** (`--profile legacy`): in-browser reader; now uses the real media disk read-only. Its old compose pointed at the rootfs; **repoint at the array before starting.** Role now narrowed to ebook in-browser reading (CWA handles delivery).


## Avrana credential replication (2026-08-17)

Komga's OIDC covers the **web UI**, but comic reader apps speak **OPDS over HTTP Basic**, and an
account auto-created by signing in with Avrana has no password the member knows. The apps were
therefore unusable for exactly the people SSO was meant to help.

Enrollment now creates the Komga account with the **same email and password** the person chose,
via the `avrana-komga-create` expression policy on the enrollment flow's `user_login` stage
(same mechanism as the Jellyfin policy, `evaluate_on_plan: false` + `re_evaluate_policies: true`
so `plan.context["groups"]` is populated). It fires only for members carrying `avrana-comics`,
and never blocks enrollment if Komga is unreachable.

It handles the ordering problem: `oauth2-account-creation` means an SSO login can create the
account first, and a second create would fail: so the policy looks the account up by email and
sets the password on the existing row instead.

> **This is credential REPLICATION, not SSO**, exactly like Jellyfin. Komga keeps its own copy,
> so a later Authentik password change does **not** propagate.

**Verified 2026-08-17** by driving a real enrollment with a disposable invite: Komga account
created with `FILE_DOWNLOAD` + `PAGE_STREAMING`, local sign-in 200, OPDS catalog 200. All test
artifacts removed.

### The OPDS path, and a trap

**`/opds/v1.2/catalog`** returns 200 (Atom). **`/opds/v2/catalog`** returns 200 (JSON).

> **Bare `/opds/v2` is a 404.** Unauthenticated it returns an OPDS *authentication document*,
> which is just Komga's challenge for any `/opds/**` path and looks convincingly like a real
> endpoint. Probing without credentials cannot tell a real path from a fake one: every
> `/opds/*` answers 401. Always verify with credentials.

### Admin access

Komga's admin API uses **HTTP Basic**, not the API key: the `X-API-Key` header is rejected for
both the REST API and OPDS. The credentials live in `services/komf/config/application.yml`
(`komgaUser` / `komgaPassword`), which is also what the enrollment policy uses: **rotate in both
places and re-apply the enrollment blueprint**.

**Not backfilled:** members who enrolled before this have no Komga account, and their Avrana
password is hashed so it cannot be replicated retroactively.

## Library access: all libraries, read only (decided 2026-08-17)

Every member sees every comic library, by decision. `SHARED_ALL_LIBRARIES=1` is therefore
**intended behaviour, not a gap**: the previous "trim per person" item is closed. The
requirement is instead that nobody but an admin can change anything.

**Verified by attempting every write as a normal account** created exactly the way enrollment
creates them (`FILE_DOWNLOAD`, `PAGE_STREAMING`, implicit `USER`):

| Attempt | Result |
|---|---|
| create / delete a library | **403** |
| trigger a library scan | **403** |
| edit series or book metadata | **403** |
| delete a book or series file | **403** |
| create a collection or read list | **403** |
| change server settings | **403** |
| create another user / list all users | **403** |
| **self-promote to ADMIN** | **403** |
| read libraries, series, OPDS catalog | 200 |
| update own read progress | 204 (correc: their own data) |

Roles were unchanged after the escalation attempt, and all 5 libraries, 8 read lists and 1
collection were intact afterwards. Test accounts removed; Komga is back to its two real users.

> Non-admin is genuinely read-only here, so no per-user library scoping is needed. The only
> thing to protect is **ADMIN**: never grant it through the enrollment policy, which currently
> requests `FILE_DOWNLOAD` + `PAGE_STREAMING` only.
