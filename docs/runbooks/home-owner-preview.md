# Avrana Home owner preview (LAN only)

Owner decision, 2026-10-15: run Avrana Home on `avrana`, reachable only on the home LAN at
`http://10.0.0.218:8197`, behind one password, showing the owner's own real libraries. No Cloudflare
tunnel, no DNS name, no Authentik. The owner runs every step below. Nothing here has been run, and no
image has been built: Docker was not available where this was written.

Files (branch `feat/lan-demo`, `services/avrana-home/`): `Dockerfile.preview`, `docker-compose.preview.yml`,
`.dockerignore`, `preview.env.example`, `preview/` (entrypoint and password gate).

## What it does

- Every request needs the password (HTTP Basic; any username). Without it the answer is 401 and the
  application never runs. The one exception is `/healthz` from inside the container (the health check).
- After 10 wrong passwords in 60 seconds from one address, that address gets 429 for 60 seconds.
- Every identity header a client sends is removed. The owner's identity (`PREVIEW_OWNER_USERNAME`,
  `PREVIEW_OWNER_GROUPS`) is added in its place, so nobody can choose who they are.
- The owner's account names differ per service. `HOME_JELLYFIN_USERNAME` (for example `Cody`) and
  `HOME_AUDIOBOOKSHELF_USERNAME` (for example `akadmin`) are used for the account lookup and nothing else.
  The match is exact and case-sensitive.
- Real mode runs without `HOME_GATES_VERIFIED`. The gates (G1, G2) protect against forged identity
  headers from sibling containers. The preview ignores every inbound identity header, so it does not
  claim the gates, and the normal `serve.py` still refuses real mode without them.

## Trade-offs (read before starting)

- **Plain HTTP on the LAN.** The password and every page cross the Wi-Fi unencrypted. Any device on
  the LAN that can see the traffic can capture the password.
- **Anyone on the LAN with the password sees the owner's libraries**, including what is in progress.
  There is one password and one identity.
- **The Audiobookshelf token is admin-capable** (an open gate in the adapter contract). The Jellyfin API
  key is server-wide too. If this container were compromised, those keys would reach everything in
  those services. The adapters only make read-only GET calls on an allow-list, but the keys themselves
  can do more.
- **No Authentik sign-in is tested.** This preview proves nothing about the member path through
  Authentik, the outpost or the gates.
- **The failure throttle may be shared.** With Docker's userland proxy, every LAN client can appear to
  come from the same bridge address. Ten wrong tries by anyone then lock everyone out for 60 seconds.
- Komga and Calibre-Web are shared views (one regular account each). Owner decision: no member
  restrictions.
- `restart: "no"`: the preview does not come back by itself after a reboot.

## Before you start: check these

1. You have this branch's files on the host in a checkout OUTSIDE the production tree, for example
   `~/preview/avrana`. Do not use `/home/cody/avrana`, and do not initialise Git inside it.
2. `id -u` prints `1000`. The container runs as 1000:1000 and must be able to read the secret files.
   If it prints something else, stop and ask.
3. `docker compose version` shows 2.17 or later. The build uses `additional_contexts`.
4. Port 8197 is free on the LAN address: `ss -ltn | grep -w 8197` prints nothing.
5. Komga: `ss -ltn | grep -w 25600`. If it shows only `127.0.0.1:25600`, the preview container cannot
   reach Komga. Leave the three Komga lines commented out in `preview.env` and decide later. Do not
   change Komga's bind for this preview.

## 1. Secret files (hidden prompts, mode 0600)

Run these one at a time in `services/avrana-home`. Values are typed at a hidden prompt and never echoed.

```sh
cd ~/preview/avrana/services/avrana-home
umask 077
install -d -m 0700 secrets
read -rs -p 'Preview password (at least 16 characters): ' v; echo; printf '%s\n' "$v" > secrets/preview_password; unset v
read -rs -p 'Jellyfin API key: ' v; echo; printf '%s\n' "$v" > secrets/jellyfin_api_key; unset v
read -rs -p 'Audiobookshelf token: ' v; echo; printf '%s\n' "$v" > secrets/audiobookshelf_token; unset v
read -rs -p 'Calibre-Web viewer user:password: ' v; echo; printf '%s\n' "$v" > secrets/calibre_web_credential; unset v
```

Komga: only if step 5 above showed Komga is reachable. Use the regular (non-admin) account's key:

```sh
read -rs -p 'Komga regular-account API key: ' v; echo; printf '%s\n' "$v" > secrets/komga_token; unset v
```

Every file named in the compose file must exist. For a service you leave out, create an empty file.
Then check the modes and the password length without printing anything secret:

```sh
[ -e secrets/komga_token ] || : > secrets/komga_token
chmod 600 secrets/*
stat -c '%a %U %n' secrets/*                          # every line: 600 cody ...
[ "$(tr -d '\n' < secrets/preview_password | wc -m)" -ge 16 ] && echo password-long-enough
```

## 2. Non-secret settings

```sh
cp preview.env.example preview.env
chmod 600 preview.env
```

Edit `preview.env` and replace every `<...>` placeholder:

- `PREVIEW_OWNER_USERNAME` is your Authentik username (`akadmin`).
- `HOME_JELLYFIN_USERNAME=Cody` and `HOME_AUDIOBOOKSHELF_USERNAME=akadmin`.
- `CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=yes` is your statement that no member has a
  Calibre-Web restriction. To leave Calibre-Web out, delete its three lines instead.
- Keep the Komga lines commented out unless step 5 showed Komga is reachable. If it is, set
  `KOMGA_BASE_URL` to that address and `KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=yes`.
- Do not add `HOME_GATES_VERIFIED`. The preview refuses to start with it.

The base URLs come from `deploy/host/cloudflared/config.yml`: Jellyfin is on the host network (:8096),
Audiobookshelf is `10.0.0.218:13378` and Calibre-Web is `10.0.0.218:8083`.

## 3. Build and start

```sh
docker compose -p avrana-home-preview -f docker-compose.preview.yml config --quiet && echo config-ok
docker compose -p avrana-home-preview -f docker-compose.preview.yml build
docker compose -p avrana-home-preview -f docker-compose.preview.yml up -d --dry-run
docker compose -p avrana-home-preview -f docker-compose.preview.yml up -d
```

`config` prints the resolved file, so use `--quiet`: it would otherwise show values from `preview.env`.
The dry run should create one network (`avrana-home-preview`) and one container
(`avrana-home-preview`), and touch nothing else. If it shows anything else, stop.

## 4. Check it

```sh
docker inspect --format '{{.State.Health.Status}}' avrana-home-preview      # healthy (after about 30 s)
docker compose -p avrana-home-preview -f docker-compose.preview.yml logs --tail 50
docker port avrana-home-preview                                             # 8096/tcp -> 10.0.0.218:8197 only
curl -s -o /dev/null -w '%{http_code}\n' http://10.0.0.218:8197/            # 401
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8197/             # 000 (nothing listens there)
```

The logs must not contain `refusing to start`. They never contain the password.

Check that the upstreams can be reached from inside the container (no key is sent):

```sh
for u in http://10.0.0.218:8096 http://10.0.0.218:13378 http://10.0.0.218:8083; do
  docker exec avrana-home-preview python3 -c "import sys,urllib.request,urllib.error
try: print(sys.argv[1], urllib.request.urlopen(sys.argv[1], timeout=3).status)
except urllib.error.HTTPError as e: print(sys.argv[1], e.code)
except Exception as e: print(sys.argv[1], 'UNREACHABLE', type(e).__name__)" "$u"
done
```

Any HTTP status means reachable. `UNREACHABLE` means a firewall or bind problem. The section then shows
"unavailable"; do not open the firewall for this preview without deciding it separately.

## 5. Open it on the iPhone

On the home Wi-Fi, open `http://10.0.0.218:8197`. Safari asks for a user name and password. The user
name can be anything; the password is the one from step 1. You should see your own Watch, Listen,
Comics and Books sections. If a section says it is not set up, the username for that service does not
match exactly (check case).

## 5a. Confirm it is LAN only

- The deployed cloudflared configuration has no hostname for this service and nothing on port 8197:
  `grep -n -e 8197 -e preview <deployed cloudflared config>` prints nothing. (The repository copy,
  `deploy/host/cloudflared/config.yml`, has none; a test checks it.)
- The router has no port forward for 8197, and UPnP has not opened one.
- With the iPhone on mobile data (Wi-Fi off), `http://<public address>:8197` must not load.

## Rollback

```sh
cd ~/preview/avrana/services/avrana-home
docker compose -p avrana-home-preview -f docker-compose.preview.yml down
docker image rm avrana-home-preview:local
shred -u secrets/preview_password secrets/jellyfin_api_key secrets/audiobookshelf_token \
  secrets/komga_token secrets/calibre_web_credential
rm -f preview.env
```

`down` removes the container and its network only. Then revoke any key or token you created only for
the preview, in Jellyfin, Audiobookshelf, Komga and Calibre-Web.

## Evidence to record

In a dated file under `docs/findings/`, with no secrets: the image ID, the health status, the
`docker port` line, the 401 and 000 results, which sections showed data on the iPhone, and the
mobile-data check. Note anything unexpected.
