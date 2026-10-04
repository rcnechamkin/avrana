# Service deployment & hardening checklist

Run through this **before** calling a new service done. It exists because the 2026-08-28 audit
found the same four gaps repeatedly, and every one of them came from a service being *deployed*
rather than *finished*:

- Beszel, Home Assistant and Tracearr ran for days with **no committed compose file**.
- Home Assistant and Tracearr ran with **no backup of their actual state**.
- The four services added after the 2026-08-13 hardening pass all run as **root**, because
  hardening was a one-time project rather than a gate.
- 13 systemd units failed silently for a month because **nothing checked**.

Hardening is a gate, not an event. A service that fails any REQUIRED line is not deployed yet.

---

## 1. Git tracking — REQUIRED

- [ ] `services/<name>/docker-compose.yml` is **committed**, not merely present.
      `.gitignore` ignores `services/*/*` but re-includes `docker-compose.yml`; the file being
      untracked means nobody ever ran `git add`.
- [ ] Verify: `git ls-files services/<name>/` returns the compose file.
- [ ] No secret values in the compose. Use `${VAR}` interpolation, `env_file:`, or
      `/run/secrets/` paths. Verify with
      `grep -nEi '(PASSWORD|SECRET|TOKEN|KEY)[A-Z_]*[:=][[:space:]]*[^$\{[:space:]]' <file>`.
- [ ] Secrets live in a gitignored `.env`, mode **600**.

## 2. Backups — REQUIRED

- [ ] Decide what the **irreplaceable** state is. It is almost never the whole directory.
- [ ] Add a `backup_<name>()` to `services/backups/avrana-backup.sh`, reporting through
      `good`/`fail` — **not** a bare `return`. (`backup_omnibus` used an *undefined* `warn` and a
      return value nobody read, so a broken omnibus backup still reported `status: ok`.)
- [ ] Add it to the run block.
- [ ] Pick the right method:
      - **SQLite** → the online `.backup` API, never `cp`. WAL-mode files tear under a raw copy.
      - **Postgres** → `pg_dump` in-container. Check *which* container: Tracearr's "supervised"
        image runs Postgres inside the app container, not a separate one.
      - **Config dirs** → if the app runs as root, files may be root-owned `0600` and a
        host-side tar as `cody` **silently omits them while still producing a plausible
        archive**. Home Assistant's `.storage/auth` and ESPHome pairing keys were exactly this.
        Archive from **inside the container**.
      - **Caches** (redis, thumbnails, transcodes) → exclude; they regenerate.
- [ ] Add an assertion to `services/backups/restore-test.sh`. A component with no verification
      is a hypothesis. Assert on *content* (a table exists, a key file is in the archive), not
      just that a file is non-empty.
- [ ] Verify end-to-end against a throwaway root — this does **not** touch production:
      ```bash
      AVRANA_BACKUP_ROOT=/mnt/avrana_media/.backups/_test bash services/backups/avrana-backup.sh
      bash services/backups/restore-test.sh /mnt/avrana_media/.backups/_test/<run>
      ```

## 3. Health monitoring — REQUIRED

- [ ] Add `check_url <name> <health-endpoint>` to `scripts/services-health.sh`.
- [ ] Prefer a real health endpoint over the root path; a 200 from `/` can mean a login page.
- [ ] If it adds a systemd unit, confirm it does **not** appear in
      `scripts/known-failed-units.txt` — that file is for acknowledged debt, not new services.

## 4. Image pinning — REQUIRED

- [ ] Pin by **digest**: `image: repo/name:tag@sha256:...`. Never `:latest`.
- [ ] Locally built images are the only exception (you cannot digest-pin what you built).
- [ ] Verify with `docker inspect <c> --format '{{.Config.Image}}'` — `docker ps` shows the run
      reference, not the resolved digest, and reading it there has produced false findings before.

## 5. Least privilege — REQUIRED unless documented

- [ ] `user: "1000:1000"` unless the image genuinely needs root.
- [ ] `security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]`, add back only what is needed.
- [ ] `read_only: true` where compatible, with explicit writable paths.
- [ ] `mem_limit`, `cpus`, `pids_limit` set to the workload.
- [ ] tmpfs `nosuid,nodev` and `noexec` unless the app needs exec (Komga's SQLite JNI,
      Shelfmark's Chromium, CWA's Calibre conversions all legitimately need exec).
- [ ] **Any exception gets a comment in the compose saying why**, or the next audit will "fix"
      it and break the service.
- [ ] **Never mount the array root** (`/mnt/avrana_media`) into a new service. It exposes
      `.backups` — Authentik's `pg_dump`, the BookStack `APP_KEY`, the tunnel credentials. Mount
      the specific subtree, read-only where possible.
      *The `*arr` whole-array mount + tmpfs shadow is a deliberate exception: `link()` returns
      `EXDEV` across separate bind mounts, so narrowing it would silently downgrade every import
      to a full copy. Do not copy that pattern into new services, and do not "simplify" it.*

## 6. Network binding — REQUIRED

- [ ] Publish to `10.0.0.218:<port>`, never `0.0.0.0`. Binding all interfaces exposes the
      service on `virbr0` and every Docker bridge too.
- [ ] Check the port is free against the *live host*, not just the wiki:
      `ss -tulpn | grep :<port>`.
- [ ] LAN-only by default. Tunnel exposure is a separate, deliberate decision — and if it is
      tunneled it must sit behind Authentik (native OIDC, or the embedded proxy outpost with no
      published host port).
- [ ] Minimise new Docker networks. **Docker is near pool exhaustion** — see
      `deploy/docker/README.md`; one remaining default slot overlaps libvirt's `virbr0`.

## 7. Restart & startup behaviour — REQUIRED

- [ ] `restart: unless-stopped`.
- [ ] A real `healthcheck:` with a `start_period` long enough for first boot.
- [ ] If it depends on a host mount, confirm the ordering survives a reboot:
      `systemctl show docker.service -p After | tr ' ' '\n' | grep <mount>`.
- [ ] **Do not add a duplicate unit for something that already has one.** The host carries a
      system *and* a user unit for mylar3; the user one pointed at a stale venv and would have
      started a second instance against the same database and port.
- [ ] If it is a host service rather than a container, its unit is now captured by
      `backup_systemd` — but it still belongs in `deploy/systemd/` in Git.

## 8. Documentation — REQUIRED

- [ ] A page under BookStack → **Services**, covering: what it is, its URL and port, exposure,
      dependencies, backup/restore, and how to start/stop/check it.
- [ ] Update **Infrastructure → Service and Port Map**.
- [ ] Record deliberate exceptions and workarounds *with the reason*. The reason is the part
      that decays; the workaround is usually self-evident.
- [ ] If it supersedes something, say so **and remove the predecessor** — the audit's largest
      debt category was replacements whose predecessor was left enabled and failing.

---

## Post-deployment verification (one block)

```bash
git ls-files services/<name>/                                   # compose is tracked
docker inspect <name> --format '{{.Config.Image}}'              # digest-pinned
docker inspect <name> --format 'user={{.Config.User}} ro={{.HostConfig.ReadonlyRootfs}}'
docker inspect <name> --format '{{range $p,$b := .NetworkSettings.Ports}}{{$p}}->{{$b}}{{end}}'
bash scripts/services-health.sh | grep <name>                   # monitored
AVRANA_BACKUP_ROOT=/mnt/avrana_media/.backups/_test bash services/backups/avrana-backup.sh
bash services/backups/restore-test.sh /mnt/avrana_media/.backups/_test/<run>
```
