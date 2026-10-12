# Avrana Kindle Connector

Set your Send-to-Kindle address **once** and have it written into both Calibre-Web and
Audiobookshelf, instead of editing two admin UIs by hand.

**https://kindle.avrana.net** — also reachable from the portal: **Read → Kindle**.

## Topology

Same shape as the portal: cloudflared → Authentik's embedded proxy outpost (gated by
**`avrana-books`**) → this container. It publishes **no host port**, so the outpost cannot be
bypassed, and the outpost strips client-supplied `X-authentik-*` headers before setting its own.

The app **also** checks `avrana-books` from the header itself, so the Authentik gate is not a
single point of failure. Stdlib Python only, digest-pinned base, non-root, read-only rootfs,
`cap_drop: ALL`, `no-new-privileges`.

## The two libraries store this completely differently

That difference is most of the work:

| | Calibre-Web | Audiobookshelf |
|---|---|---|
| Where | `user.kindle_mail` column | global `ereaderDevices` array |
| Scope | genuinely per-user | one shared list |
| Written via | direct SQLite | `PATCH /api/emails/settings` |

**Audiobookshelf needs care.** Devices live in one global array, so a device is scoped to a single
person with `availabilityOption: specificUsers` and their user id. **ABS silently coerces that
back to `adminOrUp` if the users list is empty** (verified on 2.36.0) — an unscoped write would
quietly expose someone's Kindle address to every admin. Because the array is global and written
whole, every write re-reads it immediately beforehand under a process lock, so two people saving
at once cannot clobber each other.

**Calibre-Web is written directly to `app.db`** — `kindle_mail` is plaintext (unlike
`mail_password_e`) and Calibre-Web reloads the user row per request, so the change takes effect
live. The column is comma-separated, so multiple addresses are valid.

### Why one directory is mounted, not the database files

The DB is in **WAL** mode, so SQLite needs `app.db`, `app.db-wal` and `app.db-shm`. Those three
live in **`config/appdb/`**, and that whole directory is what gets mounted at `/cwa`.

It is deliberately *not* the `config/` directory itself, because that also contains **`.key`** --
the Fernet key that decrypts CWA's stored SMTP password. This container has no business reading
it, and it cannot: `/cwa` contains exactly the three database files.

CWA still finds the DB at its own hardcoded `/config/app.db`, via a **relative** symlink
`config/app.db -> appdb/app.db`. SQLite resolves the link and creates `-wal`/`-shm` next to the
**target**, so both containers share one directory. The link must stay relative -- an absolute
host path would not resolve inside either container.

> **Do not go back to mounting the three files individually.** That was the original design and it
> caused two CWA outages on 2026-08-29. SQLite *deletes* `-wal` and `-shm` on every clean close, so
> after any clean CWA shutdown those two bind-mount sources were missing -- and Docker creates a
> missing bind source as an empty **directory**. CWA then died on the next start with
> `sqlite3.OperationalError: unable to open database file`, and the connector itself would not
> start either, because its rootfs mountpoints had been baked as directories
> (`error mounting ... not a directory`). Mounting the directory removes the fault class outright:
> Docker never has to create anything, and SQLite manages its own sidecars.

## Address validation

Deliberately strict: the address must match `…@kindle.com`. Amazon **silently discards** mail sent
to a non-existent Send-to-Kindle address, so a typo means books vanish with no error anywhere.
Rejected: other domains, `@free.kindle.com`, look-alikes such as `me@kindle.com.evil.com`,
comma-injected second recipients, and header-injection shapes.

## The Amazon half

Cannot be automated, so the app links straight to **Personal Document Settings**, where both
required things live on one page:

1. Copy the **Send-to-Kindle e-mail** (ends in `@kindle.com`).
2. Add **cody@avrana.net** under **Approved Personal Document E-mail List** — without this Amazon
   drops the book even though SMTP2GO reports success.

## Identity matching

Calibre-Web accounts are LDAP-provisioned so the username matches Authentik, with email as a
fallback; Audiobookshelf uses the same rule. This mirrors `scripts/offboard.py`, which exists
because **there is no single join key across these systems** — Jellyfin stores no email at all, and
the admin is `akadmin` in Authentik but `Cody` elsewhere.

The rule, identical in both libraries:

1. The username decides. Match is case-insensitive, exact case wins, and two accounts that differ
   only by case resolve to **nobody** rather than to whichever is listed first.
2. Email is used only when no account has that username, and only when **exactly one** account
   has that email.
3. No username means no identity (see below). Email is never used alone.

If neither account is found the page says so plainly rather than pretending it saved.

## Not a member: 404, never 403

A request that is not an `avrana-books` member gets a plain **404 "That page does not exist."**
built from the page's own shell, with nothing about Kindle, Amazon or the sender address (audit
finding A5, same rule as the portal). That covers: no headers, empty or wrong groups, a group name
that merely contains `avrana-books`, **no username**, and a repeated `X-authentik-username`,
`-email` or `-groups` line. Unknown POST routes also 404 for members, before the body is read.
`/healthz` is the only route that needs no identity.

POST bodies over 16 KiB get 413, a non-numeric or negative `Content-Length` gets 400, and an address
over 254 characters is rejected like any other non-`@kindle.com` address.

Known and deliberately left alone (owner decision): the e-mail fallback still lets a login with an
unmatched username act as the one account that owns its e-mail; a group whose name contains `,` is
split by `parse_groups` and could count as `avrana-books`; a different user's Audiobookshelf device
that happens to carry the label `Kindle (<username>)` is replaced on save. Each has an
`expectedFailure` test in `tests/test_authz.py`.

## Tests

`tests/test_authz.py` (G2) is offline and standard library only. It drives the real `Handler` over a
loopback server with a temporary Calibre-Web SQLite file and an in-memory Audiobookshelf fake, all
synthetic data. It covers denied, permitted and malformed identities for every route, isolation
between three members (full before/after state, the PATCH body preserving everyone else's entries
byte for byte, every device written as `specificUsers` with exactly the caller's id), and failures
mid-write. Run it with the rest of the offline suite:

```bash
python3 tests/run_offline.py
```

`tests/test_kindle.py` holds the original pure-logic tests plus live gating checks that need the
running containers; `run_offline.py` runs only the former.

## Operating

```bash
cd services/avrana-kindle-connector
cp .env.example .env    # ABS_API_KEY
docker compose -p avrana-kindle-connector up -d --build
python3 tests/run_offline.py   # from the repository root
```

Verified end to end: CWA write lands in `app.db`; ABS write creates a device scoped to exactly
that user; `/remove` clears both; a non-Kindle address is rejected without touching either store;
a user without `avrana-books` gets a 404, and so does a request with no headers at all.

## Rollback

```bash
docker compose -p avrana-kindle-connector down
```

Nothing else depends on it. It stores no state of its own — everything it writes lives in
Calibre-Web and Audiobookshelf, and `/remove` undoes it. To remove entirely, also delete the
`kindle.avrana.net` ingress entry, the Authentik application `avrana-kindle`, and the Kindle entry
from the Read chooser in `services/avrana-portal/portal.py`.
