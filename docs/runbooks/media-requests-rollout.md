# Switch on member requests in Avrana Media (books, films and TV, comics)

Status: prepared 2026-10-28. **Steps 1 and 2 applied 2026-10-29 for Shelfarr and Seerr** (backups in
`/home/cody/backups/requests-rollout-20261029T001304Z`); **Omnibus is back on upstream** after its fork image failed
(see step 2). Steps 3 to 7 not started. Every step changes host `avrana` and needs the owner's yes at
the time (`AGENTS.md`); a yes for one step does not cover the next. Secrets are typed at a hidden prompt, never
pasted into chat, a ticket, Git or a command line.

## Where things stand

- **Live beta** (`media-beta.avrana.net`, one tester in `HOME_ALLOWED_USERS`): main `69ed1aa`, deployed
  2026-10-28 23:22Z from `/tmp/home-live-69ed1aa` (rollback image `avrana-home-live:pre-69ed1aa`). It already has
  My requests, the comics page, the season picker and the New releases / New to Avrana rows; every request switch
  is **off**, so the request pages answer with the standard 404. #134 (Komga auto-keys) is merged, not deployed.
- **Forks**, built by their own CI, public on GHCR (no registry login needed on the host):

  | Service | Now on avrana | Fork image (pin by digest) | Schema change |
  |---|---|---|---|
  | Shelfarr | `pedro-revez-silva/shelfarr:2026.10.19.1` | `ghcr.io/rcnechamkin/shelfarr:avrana-2026.10.19.1-a8cc710@sha256:c0e1e78db13e38d9395815953c6cc7a7397b9d5a3053e8e3b211af9a8f5bc342` | none |
  | Seerr | `seerr-team/seerr` v3.4.1 (`f4768de5…`) | `ghcr.io/rcnechamkin/seerr:avrana-v3.4.1-028543b@sha256:b4ef806ff8de8900109baa12cb36add85c5536283fed10a1b201050b67f2bc32` | none |
  | Omnibus | `hankscafe/omnibus:v1.4.4` | `ghcr.io/rcnechamkin/omnibus:avrana-v1.4.4-6c3ca88@sha256:1e8c0be0b05b94c26f6ae178594b500359654aad8f16fb7a6a4f197b97535631` | one column (`ApiKey.allowOnBehalf`), added by the image's own `prisma db push` at start |
  | Omnibus engine | `hankscafe/omnibus-engine:v1.4.4` | `ghcr.io/rcnechamkin/omnibus-engine:avrana-v1.4.4-6c3ca88@sha256:39da4ecb49e73f3b8392226858492ceebdce1b8531a50fec2d792b9285e65875` | (same database) |

  Each fork is its upstream version plus a scoped "on behalf" key and nothing else; with no such key set up it
  behaves exactly like upstream. That is why step 2 changes nothing a member sees.

## The tester must be a plain member

Every broker refuses to act as an administrator: Home refuses Seerr admins, the Seerr fork's key never acts as
user 1 or anyone with an ADMIN or MANAGE permission, the Omnibus fork never acts for an ADMIN, and Shelfarr names
no admin. If the beta tester is your own admin account, every ask says "can't ask for this". Use a non-admin member
account whose Authentik username equals its Jellyfin and Audiobookshelf username, as `home-beta-live.md` already
asks, and put it in `HOME_ALLOWED_USERS`.

## The order

| Step | What | Member-visible | Undo |
|---|---|---|---|
| 1 | Backups and a record of what runs now | no | n/a |
| 2 | Fork images for Shelfarr, Seerr, Omnibus | no | image line back, `up -d` |
| 3 | Mint the three keys | no | revoke the keys |
| 4 | Home: join the request networks, switch the brokers on | yes, the tester only | switches off, `up -d` |
| 5 | Live check as the tester | yes | cancel what you asked for |
| 6 | Account creation on first ask (optional) | yes | switches off |
| 7 | "Already in your library" index (optional) | yes | unset the file |

Steps 2 to 4 can be one sitting of about an hour. Stop on anything unexpected, write it down, and ask.

## 1. Backups and a record

```sh
ts=$(date -u +%Y%m%dT%H%M%SZ); b=/home/cody/backups/requests-rollout-$ts; mkdir -p "$b" && chmod 700 "$b"
for c in shelfarr seerr omnibus omnibus-engine avrana-home-beta; do
  docker inspect --format '{{.Name}} {{.Config.Image}} {{.Image}} {{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$c"
done | tee "$b/running.txt"
docker inspect seerr --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' | tee "$b/seerr-networks.txt"
docker inspect shelfarr omnibus --format '{{.Name}} {{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' | tee -a "$b/seerr-networks.txt"
```

`running.txt` is the rollback record (image and compose folder of each). Then copy the three apps' data **with
each app stopped for the copy** (a SQLite file copied while written can be torn), using the compose folders it
printed:

```sh
cd <shelfarr folder> && docker compose stop shelfarr && cp -a data "$b/shelfarr-data" && docker compose start shelfarr
cd <omnibus folder>  && docker compose stop omnibus omnibus-engine && cp -a config "$b/omnibus-config" && docker compose start omnibus omnibus-engine
docker stop seerr && cp -a /home/cody/docker/seerr/config "$b/seerr-config" && docker start seerr
du -sh "$b"/*            # sizes only; nothing is printed from inside
```

## 2. Fork images (no behaviour change)

In each compose file (the folders from step 1), change only the `image:` line to the fork's line from the table
above, keeping a comment with the upstream line it replaces. Then, one service at a time:

```sh
docker compose pull <service> && docker compose up -d <service>
docker inspect --format '{{.State.Health.Status}}' <container>     # healthy (Shelfarr can take a minute)
docker logs --tail 30 <container>                                  # no errors; Omnibus logs its db push once
```

For Omnibus do `omnibus` and `omnibus-engine` together (they share the database). For Seerr the service lives in
the media stack's compose file, whose compose **project is named `docker`** (not `media`): always run
`docker compose -p docker -f /home/cody/avrana/services/media/docker-compose.yml ... --no-deps seerr`, or compose
starts a second copy under a new project name. Open each app's own page once and sign in as usual: same data, same settings.

**Applied 2026-10-29:** Shelfarr (healthy, web 200) and Seerr (healthy, reports v3.4.1 commit `028543b`). Omnibus
`6c3ca88` started but every page was a 500 (`PrismaClient is not configured to run in Edge Runtime`): the fork's
middleware imported its on-behalf module, which loads the database client, and Next.js runs middleware where
Prisma cannot load. Unit tests mock the database, so CI passed. Rolled back to upstream within about five minutes
(healthy); the fork is fixed by an import-free gate module plus a test that walks the middleware's imports, and is
retried only after the built app has served pages locally.

**Undo:** put the upstream `image:` line back and `up -d` that service. Omnibus's upstream `db push` drops the one
added column again (it only holds the on-behalf flag). If the data itself looks wrong: stop the app, restore its
folder from `$b`, start it.

## 3. Mint the keys

Each key goes straight into a Home secret file, typed at a hidden prompt:

```sh
cd /home/cody/avrana/services/avrana-home   # where secrets/ already lives
```

- **Shelfarr** (as the Shelfarr admin): Profile → API tokens → token name `avrana-home`, scopes exactly
  `search:read requests:read requests:write requests:on_behalf` (no `requests:admin`: the fork's `on_behalf`
  scope is what lets it name a member, and only a non-admin one). Add `users:write` only if you will do step 6.
  `read -rs -p "Shelfarr token: " s && printf '%s' "$s" > secrets/shelfarr_token && unset s && chmod 600 secrets/shelfarr_token; echo`
- **Seerr**: the fork reads `ON_BEHALF_API_KEY` from its environment (at least 32 characters). Generate it on the
  host so it is never typed or shown:

  ```sh
  umask 077; k=$(openssl rand -hex 32)
  printf 'ON_BEHALF_API_KEY=%s\n' "$k" > /home/cody/docker/seerr/on-behalf.env
  printf '%s' "$k" > secrets/seerr_api_key; unset k; umask 022
  ```

  In the media compose file add `env_file: [/home/cody/docker/seerr/on-behalf.env]` to the `seerr` service, then
  `docker compose up -d seerr` and check it is healthy. The main Seerr API key is unchanged and stays unused by
  Home.
- **Omnibus** (as an Omnibus admin): Admin → Settings → Access & Security → API keys → new key named
  `avrana-home`, tick **Allow requests on behalf of members**. Copy it once:
  `read -rs -p "Omnibus key: " s && printf '%s' "$s" > secrets/omnibus_api_key && unset s && chmod 600 secrets/omnibus_api_key; echo`

Check without printing anything: `for f in shelfarr_token seerr_api_key omnibus_api_key; do test -s secrets/$f && stat -c '%a %n' secrets/$f; done` (three lines, each `600`).

**Undo:** delete the Shelfarr token and the Omnibus key in their pages, remove the `env_file` line and
`on-behalf.env`, `up -d seerr`, and `rm secrets/{shelfarr_token,seerr_api_key,omnibus_api_key}`.

## 4. Home: networks and switches

Deploy main as for every Home change (export from the PC into `/tmp/home-live-<sha>`, link `beta-live.env`,
`secrets/` and `state/` from `~/avrana/services/avrana-home`, build, and run `up -d` **from the export folder** with
`-p avrana-home-beta`; tag the running image first as the rollback, e.g. `docker tag avrana-home-live:local
avrana-home-live:pre-requests`). Use main at or after #136 so CI is green.

In the export's `docker-compose.beta-live.yml`:

1. Re-apply what the live container already has: the Komga member-keys lines (owner enabled them 2026-10-28; the
   repo keeps them commented).
2. Uncomment the block marked `MEMBER REQUESTS` in four places: the nine environment lines (three switches, three
   URLs, three key files), the `networks:` line that adds `shelfarr_default`, `omnibus` and
   `docker_request-backend` (Seerr's; names checked 2026-10-29), those three entries under `networks:` at the
   bottom, and the three secrets (add them to the `secrets:` line in use and uncomment their entries at the
   bottom). Switch and URL go together: Home refuses to start with a URL whose switch is off. To leave one broker
   off, keep its three lines commented.

Joining the networks creates none (the host is at Docker's network limit, so this matters). The Seerr network also
holds Radarr and Sonarr; Home holds no key for them and its request code only calls Seerr's fixed routes.

```sh
docker compose -p avrana-home-beta -f docker-compose.beta-live.yml config --quiet && echo config-ok
docker compose -p avrana-home-beta -f docker-compose.beta-live.yml up -d
docker inspect --format '{{.State.Health.Status}}' avrana-home-beta     # healthy
docker logs --tail 30 avrana-home-beta                                  # no "refusing"
```

A broker that cannot start is a refusal in the log naming its setting; turn that one switch off and start again.

**Undo:** comment the block again and `up -d`; or run the tagged rollback image.

## 5. Live check (as the tester)

On the iPhone or a browser signed in as the tester:

1. Request → Books: search a title you do not have, **Ask for it**, then **See what you have asked for**: it is
   there as Waiting or Searching. **Cancel** it. Its row goes.
2. Request → Movies and TV: search a show, **Choose seasons**, pick one season, ask. Unless the tester has
   auto-approve in Seerr it says it was sent for approval (no download starts). On My requests, cancel it.
3. Request → Comics: search a series, ask. It shows on My requests (comics have no cancel; delete it in Omnibus as
   the admin if it was only a test).
4. Home: New releases and New to Avrana both show; a request page in a second browser signed in as someone else
   is the standard 404.

`docker logs avrana-home-beta 2>&1 | grep -cE 'book_request|watch_request|comic_request|request_cancel'` counts the
asks and cancels; those lines carry a fixed outcome only, never a title or a name. Record the result (pass or fail, times, no titles) in `docs/findings/`.

## 6. Account creation on first ask (optional)

Only for members who have never opened Shelfarr or Seerr. The tester already has both, so this needs a second,
fresh non-admin member to prove it (the same situation as `HOME_PROVISION_ACCOUNTS`).

These two lines go in the same compose block as the switches.

- `HOME_SEERR_PROVISION=on`: runs Seerr's own Import Jellyfin users for that one member on their first watch ask.
  Needs nothing else.
- `HOME_SHELFARR_PROVISION=on`: creates a plain Shelfarr user on the first book ask. Needs `users:write` on the
  Shelfarr token (step 3) and, in Shelfarr's settings, OIDC **link existing users** on, so the member's Authentik
  sign-in joins that account. Shelfarr usernames are `a-z 0-9 _` only; others are never created (see the username
  comparison of 2026-10-28: the recommended Authentik rule `^[a-z][a-z0-9_]{2,31}$` removes the case).

Both try at most once per member per hour and log `account_provision` with a fixed state. **Undo:** `off`, `up -d`.
Accounts already created stay (delete them in each app if unwanted).

## 7. "Already in your library" (optional)

`tools/build_catalogue_index.py` joins the libraries' own catalogue ids (Calibre, Shelfarr's Audiobookshelf mirror,
Omnibus plus Komga) read-only into one file, so a search result can say **Already in Books. Open**.

```sh
t=/tmp/home-live-<sha>/services/avrana-home/tools/build_catalogue_index.py   # the deployed export (~/avrana is older)
python3 "$t" --dry-run                                     # counts per source; nothing written
cd /home/cody/avrana/services/avrana-home && mkdir -p state/index && python3 "$t" --out state/index/library_ids.json
```

Mount it read-only into Home (`./state/index:/var/lib/avrana-home-index:ro`) and set
`HOME_LIBRARY_IDS_FILE=/var/lib/avrana-home-index/library_ids.json`. Refresh it with a user timer every six hours
(an index older than 36 hours makes no claims, so a stopped timer fails safe). **Undo:** unset the variable.

## After it is on

- Commit the applied compose changes (the three image lines, Seerr's `env_file`) so `scripts/drift-check.py` is
  clean, and note the date here.
- Members beyond the tester come with the general Media launch, not with this runbook.
