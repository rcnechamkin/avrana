# Run the Avrana Media beta on live data (AVR-771)

Status: prepared 2026-10-27, **nothing applied**. Owner decision 2026-10-27: the personal beta uses live data
instead of synthetic. Every step on host `avrana` needs the owner's yes at the time (`AGENTS.md`).

What you get: `https://media-beta.avrana.net` behind Authentik, open to one tester, showing that tester's own
Jellyfin and Audiobookshelf (Continue, Recently added, search, title pages, hand-offs), read-only, plus comics
(Komga) and ebooks (Calibre-Web) since 2026-10-27. Those two are shared views (ADAPTER-CONTRACT 12.2, 13.2): one
regular Komga account's API key and one Calibre-Web viewer account, allowed because the owner confirmed on
2026-10-15 that no member is restricted in either (`docs/DECISIONS.md`). See "Comics and ebooks" below.

What it does not touch: the portal at `avrana.net`, every library's data and settings, every other member, the
owner preview. No host port is published. The app only reads.

## Why this is allowed now

`settings.py` refuses real mode unless `HOME_GATES_VERIFIED=yes`, meaning gates G1 and G2 hold in production
(`docs/design/MEDIA-2.0.md` section 4). G1 was applied and signed off on 2026-10-27, owner check E2 included
(`docs/DECISIONS.md`). G2 is the offline authorization and isolation suites that run on every PR. Home trusts
only the outpost's signed token (`jwt_required`), never a plain header, and the Audiobookshelf admin token is
refused in any other mode.

## Choose the tester first

Home matches a member to their library accounts by **exact username** (case-sensitive), with no mapping table
(`docs/DECISIONS.md`, no username reuse). So the tester's Authentik username must equal their Jellyfin
username and their Audiobookshelf username. If `akadmin` is not your Jellyfin name, use (or create) a
non-admin member account whose name matches; that is also what AVR-771 asks for. A mismatch is safe: Home
shows "not set up" for that library, never someone else's.

## 1. Authentik, network and hostname (from the synthetic runbook)

Do `docs/runbooks/home-beta-deploy.md` steps **2** (private network `authentik_home_beta`), **3** (blueprint:
group `avrana-beta`, provider `avrana-home-beta-proxy`, application, outpost) and **6** (cloudflared hostname).
Skip its steps 1, 4 and 5 (the synthetic image and settings). Then, in the Authentik admin UI, add the tester
to the group `avrana-beta` if it is not `akadmin`.

## 2. Settings and secrets on the host

```sh
cd /home/cody/avrana/services/avrana-home
cp beta-live.env.example beta-live.env && chmod 600 beta-live.env   # issuer, audience, the tester's username
mkdir -p secrets && chmod 700 secrets
read -rs -p "beta client secret: " s && printf '%s' "$s" > secrets/home_jwt_secret && unset s && chmod 600 secrets/home_jwt_secret; echo
read -rs -p "Jellyfin API key: " s && printf '%s' "$s" > secrets/jellyfin_api_key && unset s && chmod 600 secrets/jellyfin_api_key; echo
read -rs -p "Audiobookshelf token: " s && printf '%s' "$s" > secrets/audiobookshelf_token && unset s && chmod 600 secrets/audiobookshelf_token; echo
```

- Client secret: the `avrana-home-beta-proxy` provider's (Authentik, provider page).
- Jellyfin: Dashboard → API Keys → a new key named `avrana-home-beta`. Home only reads with it.
- Audiobookshelf: an API token from an admin account (Settings → API Keys, or the admin's token). It is
  admin-capable; Home uses it read-only and only with verified identity.

None of these go in `beta-live.env`, Git, a ticket or a chat. **Undo:** `rm beta-live.env secrets/*`, and revoke
the Jellyfin key and the Audiobookshelf token in their admin pages.

## 3. Build and start

```sh
docker compose -p avrana-home-beta -f docker-compose.beta-live.yml build   # avrana has no buildx; compose builds it
docker compose -p avrana-home-beta -f docker-compose.beta-live.yml config --quiet && echo config-ok
docker compose -p avrana-home-beta -f docker-compose.beta-live.yml up -d --dry-run   # one container, no network created
docker compose -p avrana-home-beta -f docker-compose.beta-live.yml up -d
docker inspect --format '{{.State.Health.Status}}' avrana-home-beta                  # healthy after ~30 s
docker port avrana-home-beta                                                         # (empty: no host port)
docker logs --tail 20 avrana-home-beta                                               # no "refusing"
docker inspect avrana-home-beta --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'
# exactly: audiobookshelf_default authentik_home_beta calibre-web-automated_default komga_default
```

If the synthetic beta is running, stop it first (`docker compose -p avrana-home-beta -f docker-compose.beta.yml
down`): the two use the same container name. **Undo:** `docker compose -p avrana-home-beta -f
docker-compose.beta-live.yml down` (removes only this container; the external networks stay).

## Comics and ebooks (added 2026-10-27)

The compose file reads two more secret files, `secrets/komga_token` (a REGULAR, non-admin Komga account's API key,
never an admin key) and `secrets/calibre_web_credential` (`user:password` of the Calibre-Web viewer account). Both
already exist in `~/avrana/services/avrana-home/secrets/` from the owner preview (checked 2026-10-27 by name and
mode only, contents not read); the export deploy links that folder. Create them only if they are missing, with the
same `read -rs` lines as step 2. It also joins `komga_default` and `calibre-web-automated_default`, the two
libraries' own compose networks (both exist; checked read-only 2026-10-27).

A member sees comics only with the Authentik group `avrana-comics` and ebooks only with `avrana-books`. Add the
tester to those groups in the Authentik admin UI if they should see them. Without a group, the library is simply
absent, never an error.

If either upstream refuses the account, Home shows that library as unavailable and everything else as usual.
**Undo:** redeploy the previous image, or remove the six `KOMGA_`/`CALIBRE_WEB_` lines, the two networks and the
two secrets from the compose file and run `up -d` again.

## 4. Check it

1. Private window, `https://media-beta.avrana.net/`: Authentik sign-in, never Home.
2. An account outside `avrana-beta` (for example `beta-outsider`): Authentik refuses.
3. An account inside `avrana-beta` but not in `HOME_ALLOWED_USERS`, if you have one: Home treats it as having
   no identity (`identity.py`, "not_allowed"): no library content, no username on Me.
4. The tester: Home with their own Continue and Recently added; Me shows their username; a title opens and its
   hand-off goes to Jellyfin or Audiobookshelf. With the groups: Read shows a Comics row and a Books row, and the
   Library's Comics and Books chips list them.
5. Degraded: no library is stopped for this check (that would be a production change). Library-down
   behaviour is rehearsed in CI (`beta/rehearse_degraded.py`, `.github/workflows/beta-image.yml`).
6. On the iPhone: the same as 4, then AVR-585 (Safari, Add to Home Screen, VoiceOver, text size, reduced motion,
   offline).

Stop and undo (3, 2, then step 1's undo lines in reverse) if 1, 2 or 3 fails, or if anything shows another
member's item.

## Rollback, all of it

Step 3 undo, step 2 undo (revoke the key and token), then `home-beta-deploy.md` undo lines for 6, 3 and 2. The
portal, the libraries and every member are untouched throughout.
