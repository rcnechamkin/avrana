# Komga viewer key: replace Home's admin key (AVR-782)

Owner runbook. Home's everyday `secrets/komga_token` is reported to be `avrana-home-api`, a key on the owner's Komga
ADMIN account (the AVR-784 notes). Komga keys have no scope, so that key can do anything the admin can. This moves Home
to a key on a regular account, then revokes the old key. Member keys, passwords and reading progress do not change.

Status at the time of writing: **nothing here has been run.** Whether the key is ADMIN was never read directly; step 1
reads it. Komga behaviour below is from the 1.25.0 source (`UserController.kt`, `UserDto.kt`, `KomgaUser.kt`,
`SecurityConfiguration.kt`, `BookController.kt`), not tested against the live server.

## What the viewer needs

| Need | Answer (Komga 1.25.0) |
|---|---|
| Account | A regular account, used by Home alone. `ADMIN` must be off. |
| Libraries | **All libraries** (`sharedAllLibraries`, the default for a new account). A smaller share silently hides comics from every member's Recently added, New releases, Search and title pages. |
| Roles | **None.** Home reads the book list, one book, one series, a thumbnail and `/api/v2/users/me`; each is open to any signed-in account. `PAGE_STREAMING` and `FILE_DOWNLOAD` guard reading and download routes Home's allow-list never calls. Komga shows `USER` on every account. That is expected. |
| Restrictions | No age or label restrictions, or the same comics go missing. |
| On Deck | Not the viewer's job. On Deck and Continue use each member's own key. The shared route table has no `ondeck`. |
| Key | Only the account itself can make one (`POST /api/v2/users/me/api-keys`), so sign in as the viewer. An admin cannot mint it for them. |

Effect on Home with a viewer key: none visible. Admin accounts see every library by rule; the viewer sees them only by
the `All libraries` setting, which is why step 4 compares the two.

## Order

The guard (branch `fix/rc3-komga-viewer-guard`) refuses an ADMIN key in real mode. Swap the key **first**, on the running
revision, then deploy the guard, and revoke last. Each step below can be undone by the previous one, until step 7.

If the guard goes first with the admin key still in place: Comics, including Continue, show as unavailable until the
swap. Home itself, the other libraries and `/healthz` stay up, and the log says `error=SharedKeyIsAdmin`.

## 1. Preflight (read only)

```sh
cd ~/avrana/services/avrana-home
docker exec avrana-home-beta python3 -c "import json,os,urllib.request as u; k=open('/run/secrets/komga_token').read().strip(); r=u.urlopen(u.Request(os.environ['KOMGA_BASE_URL']+'/api/v2/users/me',headers={'X-API-Key':k}),timeout=5); print(r.status, sorted(json.load(r)['roles']))"
```

`200 [... 'ADMIN' ...]` confirms AVR-782. If `ADMIN` is absent, stop: the premise is wrong, and revoking would be a
needless outage; the guard can deploy alone.

Check nothing else holds the same key. Compare hashes, never values:

```sh
tr -d '\n' < secrets/komga_token | sha256sum | cut -c1-12
grep -h '^HOMEPAGE_VAR_KOMGA_KEY=' ~/avrana/services/homepage/widget-secrets.env | cut -d= -f2- | tr -d '\n' | sha256sum | cut -c1-12
```

The Homepage widget (`deploy/homepage/config/services.yaml`) reads `HOMEPAGE_VAR_KOMGA_KEY`. If the two prints match, give
it a viewer key too before step 7, or its widget breaks on revocation. Komga's key list shows comments only, so any other
copy of the key is unknown to this runbook; check your own notes.
Back up the secret: `cp -p secrets/komga_token secrets/komga_token.pre-viewer`.

## 2. Create the viewer (Komga web UI)

1. As admin: Server settings, Users, add a user. Pick an address no member uses and that is not routable to anyone, with a
   long generated password kept in 1Password. Untick every role. Leave libraries on All. No restrictions.
2. Sign out, then sign in **with that address and password** on the local form (a private window keeps the admin session).
   If the local form is hidden, that is `webui.oauth2.hide_login`; turn it off for this step.
3. Account settings, API keys, new key, comment `avrana-home-viewer`. Komga shows it once. Copy it into 1Password.

**Undo:** delete the user as admin. Nothing depends on it yet.

## 3. Install it on the running revision

No code changes here, so this proves the key before the guard exists. A short Home recreate; Authentik sessions survive.

```sh
cd ~/avrana/services/avrana-home
read -rs -p 'Komga viewer API key: ' v; echo; printf '%s' "$v" > secrets/komga_token.new; unset v
chmod 600 secrets/komga_token.new
mv secrets/komga_token.new secrets/komga_token
dir=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' avrana-home-beta)
cd "$dir" && docker compose -p avrana-home-beta -f docker-compose.beta-live.yml up -d --no-build --force-recreate avrana-home-beta
```

Use `--no-build`, with the project name, from the running export; a bare `up` from `~/avrana` targets the wrong project.
Run the deploy script's dry-run check first if the export was not the last thing deployed.

**Undo:** `cp -p ~/avrana/services/avrana-home/secrets/komga_token.pre-viewer ~/avrana/services/avrana-home/secrets/komga_token`
and the same `up` line.

## 4. Verify the key

```sh
docker exec avrana-home-beta python3 -c "import json,os,urllib.request as u; k=open('/run/secrets/komga_token').read().strip(); r=u.urlopen(u.Request(os.environ['KOMGA_BASE_URL']+'/api/v2/users/me',headers={'X-API-Key':k}),timeout=5); d=json.load(r); print(r.status, sorted(d['roles']), d['sharedAllLibraries'], len(d['sharedLibrariesIds']))"
```

Expect `200 ['USER'] True 0`. As a signed-in member with `avrana-comics`: Comics rows, a cover, a title page and a Search
hit. Compare a recent title seen in Komga as admin with what Home shows.

## 5. Deploy the guard

After review and merge: `scripts/deploy-home-beta.sh`, then `--apply`, as usual (docs/runbooks/home-beta-deploy.md).
The deploy recreates Home only.

## 6. Verify the guard

```sh
docker logs --since 10m avrana-home-beta 2>&1 | grep -c SharedKeyIsAdmin      # 0
```

Load Home as a comics member. Comics show. The check runs at the first Komga mapping after start, not at start, so a count
of 0 before any member page proves nothing. Load a page first.

**Undo:** the rollback the deploy printed. The viewer key works with either revision.

## 7. Revoke the old key

Wait until a normal day of use has passed with no `adapter_failure service=komga`. Then, signed in to Komga **as the owner
admin**: Account settings, API keys, delete `avrana-home-api`. Delete that one only. `authentik-enrollment` is a different
key and enrollment needs it; a key on the owner's list may also be the owner's own member key.

Verify: a signed-in page still shows Comics, the old key gets 401 (paste it from 1Password at a hidden prompt, do not put
it in a command line), then enroll nothing and change nothing else. Remove `secrets/komga_token.pre-viewer` with `shred -u`.

**Undo:** none. A revoked key cannot return. If something unexpected relied on it, give that thing its own new key.

## Rotation

Same as steps 2 (key only) and 3. There is no overlap to manage: Home holds one key and reads it at start.
