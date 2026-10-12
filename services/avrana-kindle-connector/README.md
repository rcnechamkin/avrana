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

**The username is the only join key.** Calibre-Web accounts are LDAP-provisioned and Audiobookshelf
users are created to match, so the Authentik username (`X-authentik-username`) is looked up in both
libraries. The e-mail header plays **no part** in resolving an account: it is user-editable in
Authentik and not unique, and an earlier e-mail fallback let a member with an account in only one
library act as whoever owned that e-mail in the other.

The rule, identical in both libraries:

1. Match is case-insensitive, exact case wins, and two accounts that cannot be told apart (same name,
   or differing only by case with no exact match) resolve to **nobody**, never to whichever is listed
   first.
2. No username means no identity (see below).
3. If neither account is found the page says so plainly rather than pretending it saved.

### Members whose names differ: `KINDLE_USERNAME_ALIASES`

The one real mismatch (`scripts/offboard.py`: there is no single join key across these systems) is
the admin, `akadmin` in Authentik and `Cody` in the libraries. The owner covers such cases explicitly
with an environment variable, empty by default:

```
KINDLE_USERNAME_ALIASES=akadmin=Cody            # authentik_username=library_username
KINDLE_USERNAME_ALIASES="akadmin=Cody a=b,c=d"  # comma- or space-separated pairs
```

- One entry applies to **both** libraries: the only known case is one name used everywhere. A member
  whose two library usernames differ from each other should have one of them renamed instead.
- The source is an exact match on the Authentik username; no chaining, no case folding, nothing
  derived from request data.
- The target name then belongs to that source alone: any other login whose username equals it (any
  case) gets the 404, so two Authentik users can never share one library account.
- Malformed entries are ignored. An ambiguous map (a target that is also a source, two sources with
  one target, one source with two targets) is refused whole, so a typo fails closed. The one log line
  carries counts only, never names.
- It is commented out in `docker-compose.yml`. Changing it needs the container recreated.

### Before deploying: owner checklist (read-only)

Members whose Authentik username does not exactly match (ignoring case) their Calibre-Web and
Audiobookshelf usernames will see "No ... account found" until an alias is set. Nothing writes to
either library while you check.

1. Authentik admin, Directory, Users: note each member of `avrana-books` and their username.
2. Calibre-Web admin, Users list: compare names. Do not open `app.db` by hand; its WAL files are
   live.
3. Audiobookshelf, Settings, Users: compare names.
4. Anyone who differs gets either a rename in the library, or one `authentik=library` entry in
   `KINDLE_USERNAME_ALIASES` (only when both libraries use the same differing name).
5. Two library accounts that differ only by case (e.g. `Sam` and `sam`) now resolve to nobody; rename
   one.
6. Check that no Authentik user is named like an alias target (that user would get the 404).

## Not a member: 404, never 403

A request that is not an `avrana-books` member gets a plain **404 "That page does not exist."**
as its own minimal document titled "Not found · Avrana" (the portal's wording), with nothing about
Kindle, Amazon, the libraries or the sender address (audit finding A5). That covers: no headers,
empty or wrong groups, a group name that merely contains `avrana-books`, **no username**, and a
repeated `X-authentik-username`, `-email` or `-groups` line. Unknown POST routes also 404 for
members, before the body is read. `/healthz` is the only route that needs no identity.

Other limits: a POST body over 16 KiB gets 413, a non-numeric or negative `Content-Length` 400, a
body that stalls for 15 s 408, and an address over 254 characters or containing non-ASCII look-alikes
(Kelvin sign for `k`, dotless `i`) is rejected like any non-`@kindle.com` address. If Calibre-Web or
Audiobookshelf cannot be read the page answers a plain 503 and writes nothing. The server speaks
HTTP/1.0 so every reply closes the connection; the early replies depend on that.

Device label collisions: Audiobookshelf's global array may already hold a device named
`Kindle (<username>)` scoped to someone else. It is left untouched and the new device is labelled
`Kindle (<username>) #<audiobookshelf id>`. Audiobookshelf's own name-uniqueness rules are unverified
offline.

Known and left for an owner decision: a group whose name contains `,` is split by `parse_groups`
and could count as `avrana-books` (needs an admin-created group; `expectedFailure` test in
`tests/test_authz.py`).

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
