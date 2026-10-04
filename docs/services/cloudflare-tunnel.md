# Cloudflare and External Access

> Promoted from the BookStack wiki on 2026-10-04 (page 7, "Cloudflare and External Access", last edited 2026-08-29) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/infrastructure/07-cloudflare-and-external-access.md).

Public reach is via **Cloudflare Tunnel**, not port-forwarding. Tunnel `avrana` (id `1f77ba21-71ca-4360-8861-28b0a5a30f6f`), systemd `cloudflared-avrana.service`, config `~/.cloudflared/config.yml`.

- **Publicly tunneled:** Jellyfin (`watch.avrana.net`), Seerr (`request.avrana.net`), Komga (`read.avrana.net`), Audiobookshelf (`listen.avrana.net`), Authentik (`auth.avrana.net`), **Calibre-Web (`books.avrana.net`, added 2026-08-14)**, **Audible Connector (`contribute.avrana.net`, added 2026-08-14)**, the **Avrana Portal
(`avrana.net`, live 2026-08-16)**. *(The Health API was removed from this list on 2026-08-28 — see below.)*
- **Adding a hostname:** edit `config.yml` ingress (before the catch-all 404) → `cloudflared tunnel route dns 1f77ba21-71ca-4360-8861-28b0a5a30f6f <host>` → **`sudo systemctl restart cloudflared-avrana.service`** (needs the operator's password). The DNS route step creates the CNAME; the restart activates the new ingress.
- **Tunnel ownership:** system units own the main `avrana` and `comics` tunnels. The `health` tunnel is **gone** (retired 2026-08-28). The duplicate *user* comics connector is disabled.
- `comics.avrana.media` still runs a connector and is still **NXDOMAIN**. `health.avrana.media` no longer has a connector at all — its user unit and `config-health.yml` were removed on 2026-08-28 (audit **H1 closed**; see *Services → Health API*). The tunnel **object** `health-avrana` (`9c28d270-c64b-4fb9-8004-333e1af654fe`) still exists account-side with no connector and no DNS; delete it with `cloudflared tunnel delete health-avrana` when convenient.
- ~~Two stale failed system units keep their enabled flags~~ — **done 2026-08-28.** Both were disabled and reset-failed by `deploy/systemd/cleanup-obsolete-units.sh`; the commands below are kept only for history:

```bash
sudo systemctl disable cloudflared-comics.service cloudflared-health.service
sudo systemctl reset-failed cloudflared-comics.service cloudflared-health.service
```

> Do not run duplicate *user* and *system* connectors unless replica operation is explicitly intended.

> ⚠️ **Scheme matters for OIDC.** Cloudflare here does **not** force `http`→`https` (verified 2026-08-13). Audiobookshelf builds its OIDC `redirect_uri` from the request scheme, so mobile clients must use `https://listen.avrana.net` or Authentik returns "Redirect URI Error". Enabling Cloudflare **"Always Use HTTPS"** would prevent this. See *Authentik & SSO*.

> ⚠️ **Cloudflare edge-caches static assets; page HTML it does not.** Behind the
> tunnel, HTML comes back `cf-cache-status: DYNAMIC`, but assets under paths like `/static/*.css`
> are cached at the edge for ~4 h. A redeploy can therefore look like it silently did nothing while
> the origin is already correct. This bit the Audible Connector restyle on 2026-08-16: the edge
> served the old stylesheet (`HIT`, `age 3959`) while `localhost:8092` served the new one.
> **There is no Cloudflare API token on this host, so a cache purge is not available.** The fix is
> to make the asset URL content-addressed; the connector appends a short content hash
> (`?v=<sha256[:12]>`, `main.py:_asset_version()`). **Always verify a front-end change on the
> public hostname, not just on the LAN.**
>
> Whether a service is affected depends on the **origin's `Cache-Control`**, not on whether its
> asset paths look versioned. Audiobookshelf and Komga ship content-hashed bundles and are immune.
> **Calibre-Web is also fine** despite unhashed `/static/css/*` paths, because its origin sends
> `Cache-Control: no-cache`, so the edge revalidates every request (`REVALIDATED`) instead of
> serving a stale copy. The connector's origin sent no `Cache-Control` at all, which is why it was
> hard-cached.


> **Two hostnames added 2026-08-17**, both live after the tunnel restar: **`ops.avrana.net`**
> (OliveTin, gated by `authentik Admins`) and **`kindle.avrana.net`** (Kindle connector, gated by
> `avrana-books`). Both sit behind the Authentik embedded outpost and publish no host port.
> Verified serving: each returns 302 to Authentik sign-in rather than the catch-all 404.
>
> The tunnel restart is now a **button** in OliveTin rather than a manual step. It uses a
> root-level `systemd.path` unit that hardcodes the service name and takes no arguments, so the
> capability granted is exactly "restart the tunnel" and cannot widen. See *OliveTin*.

> **Public login surfaces:** `books.avrana.net` (Calibre-Web) shows a public username/password form (LDAP → Authentik); its default admin password was rotated before exposure. `contribute.avrana.net` (Audible Connector) is OIDC-gated to `library-contributors`. All other tunneled apps gate via Authentik OIDC or their own auth.
