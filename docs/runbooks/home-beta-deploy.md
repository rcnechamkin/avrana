# Deploy the Avrana Media beta (AVR-373 phase 1): real sign-in, synthetic data

Status: prepared 2026-10-27; **superseded by `home-beta-live.md`: the beta has run on live data since 2026-10-29 (revision 2cb228f)**. The owner runs each step on host `avrana` with an explicit yes
at the time (`AGENTS.md`); an agent never does. About 30 to 45 minutes. `docs/design/BETA-CHECKLIST.md` is the
"why" behind each step; this page is the "how", in order, with the check and the undo for each.

What you get: `https://media-beta.avrana.net` (change the name in steps 3 and 4 if you prefer another), behind
Authentik sign-in, open to `akadmin` only, showing Avrana Media with **synthetic** libraries. It cannot read a
real library or real member data: the container refuses any real-library setting at start (exit 2) and runs its
own fake Jellyfin, Audiobookshelf, Komga and Calibre-Web on its own loopback.

What it does not touch: the portal at `avrana.net`, its provider and policy, every library, every member account,
the owner preview. No host port is published.

Prerequisites: #99 and #100 merged (security locks, concurrency), the repository checkout on the host at that
commit, and the hostname decided.

## 1. Build the image (no live effect)

```sh
cd /home/cody/avrana/services/avrana-home
docker build -f Dockerfile.beta --build-context portal=../avrana-portal -t avrana-home-beta:local .
docker run --rm -e HOME_IDENTITY_MODE=headers avrana-home-beta:local; echo "exit=$?"     # exit=2 (refused)
```

**Undo:** `docker image rm avrana-home-beta:local`.

## 2. The private network to the outpost

One network shared by the beta container and `authentik-server` only (the G1 pattern). `docker network connect`
attaches a running container **without restarting it**, so sign-in is not interrupted.

```sh
docker network create --subnet 10.220.32.0/24 authentik_home_beta
docker network connect authentik_home_beta authentik-server
docker network inspect authentik_home_beta --format '{{range .Containers}}{{.Name}} {{end}}'   # authentik-server
```

`services/authentik/docker-compose.yml` declares this network for the `server` service, so it survives a recreate
of `authentik-server`, and the network must exist before that project starts. `HOME_INTERNAL_CIDR` depends on this
subnet. If the link is ever lost, signed-in members get a 502 while a signed-out probe still gets the outpost's 302;
the connect command above repairs it without a restart.

**Undo:** remove the network from that compose file first, then
`docker network disconnect authentik_home_beta authentik-server && docker network rm authentik_home_beta`.

## 3. Authentik: provider, application, group (Authentik UI)

1. Copy `services/avrana-home/beta/authentik-home-beta.yaml` into the worker's blueprints directory, then in the
   admin UI: **Customization → Blueprints → Create**, pick the file, **Apply**. It creates the group
   `avrana-beta` (akadmin only), the proxy provider `avrana-home-beta-proxy` (external host
   `https://media-beta.avrana.net`, internal `http://avrana-home-beta:8096`) and the application
   "Avrana Media (beta)" bound to that group only. For another hostname, set `AVRANA_HOME_BETA_EXTERNAL_HOST`
   in `services/authentik/blueprints.env` first.
2. **Applications → Outposts → authentik Embedded Outpost → Edit**: add `avrana-home-beta-proxy` to the selected
   applications. Save.
3. **Providers → avrana-home-beta-proxy**: note the **Client ID** and the **issuer** (OpenID Configuration
   Issuer). Keep the page open for the **Client Secret** in step 4; do not paste it anywhere else.
4. Optional, for smoke test 2: a test user `beta-outsider` in no groups (you create it; an agent does not).

**Undo:** delete the application, the provider and the group `avrana-beta`, remove the blueprint, and remove
the provider from the outpost.

## 4. Settings and secret on the host

```sh
cd /home/cody/avrana/services/avrana-home
cp beta.env.example beta.env && chmod 600 beta.env      # fill HOME_JWT_ISSUER and HOME_JWT_AUDIENCE (step 3.3)
mkdir -p secrets && chmod 700 secrets
read -rs -p "beta client secret: " s && printf '%s' "$s" > secrets/home_jwt_secret && unset s && chmod 600 secrets/home_jwt_secret; echo
```

The secret is the provider's Client Secret (at least 32 bytes; Authentik's default is longer). It never goes in
`beta.env`, Git, a ticket or a chat.

**Undo:** `rm beta.env secrets/home_jwt_secret`.

## 5. Start the container

```sh
docker compose -p avrana-home-beta -f docker-compose.beta.yml config --quiet && echo config-ok
docker compose -p avrana-home-beta -f docker-compose.beta.yml up -d --dry-run      # one container, nothing else
docker compose -p avrana-home-beta -f docker-compose.beta.yml up -d
docker inspect --format '{{.State.Health.Status}}' avrana-home-beta                 # healthy after ~30 s
docker port avrana-home-beta                                                        # (empty: no host port)
docker logs --tail 20 avrana-home-beta                                              # no "refused"
```

Smoke inside the container (synthetic tokens signed with the same secret; checks forged headers and forged
tokens get 404):

```sh
docker exec -e BETA_URL=http://127.0.0.1:8096 avrana-home-beta python3 -B beta/smoke.py   # 7/7 passed
```

**Undo:** `docker compose -p avrana-home-beta -f docker-compose.beta.yml down` (removes only this container; the
external network stays).

## 6. The hostname (cloudflared)

In the live `/etc/cloudflared/config.yml` (whatever path `cloudflared-avrana.service` uses), add **before** the
catch-all, with the same `service:` target the `avrana.net` entry uses (the Authentik outpost):

```yaml
  - hostname: media-beta.avrana.net
    service: <same target as the avrana.net line>
```

```sh
cloudflared tunnel ingress validate --config <that file>
cloudflared tunnel route dns cloudflared-avrana media-beta.avrana.net
sudo systemctl reload cloudflared-avrana.service
```

**Undo:** remove the two lines, reload, and delete the DNS record in the Cloudflare dashboard.

## 7. Check it (BETA-CHECKLIST section 5)

1. Private window, `https://media-beta.avrana.net/`: Authentik sign-in, never Home.
2. `beta-outsider` signs in: Authentik refuses.
3. `akadmin` signs in: Avrana Media with the synthetic libraries; Me shows `akadmin`.
4. On the iPhone: the same as 3 (then the device pass, `docs/design/M3-DEVICE-REVIEW.md` Step C).

Stop and undo in reverse order (6, 5, 4, 3, 2) if 1 or 2 fails, or if anything shows a real title or a real
member.

## Rollback, all of it

`6 → 5 → 4 → 3 → 2 → 1` undo lines above. The portal, the libraries and every member are untouched throughout.

## Live data instead

Owner decision 2026-10-27: the personal beta runs on live data. Use [`home-beta-live.md`](home-beta-live.md), which
reuses steps 2, 3 and 6 above and replaces 1, 4 and 5.
