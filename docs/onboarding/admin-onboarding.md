# Running the onboarding beta (admin)

> Promoted from the BookStack wiki on 2026-10-04 (page 46, "Running the onboarding beta (admin)", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/member-onboarding/46-running-the-onboarding-beta-admin.md).

How to invite one real person and verify the complete workflow works. The member-facing steps live in **Welcome to Avrana**.

## The landing page (done 2026-08-14)
`https://auth.avrana.net` (Authentik's "My applications") **is** the Avrana landing page: it natively shows a user only the apps their groups permit. It was made complete + branded:
- Brand title is **Avrana** (was "authentik").
- All six services are tiles now, each gated by one group:

| Tile | URL | Group | Auth |
|---|---|---|---|
| Audiobooks | listen.avrana.net | `avrana-audiobooks` | OIDC |
| Comics | read.avrana.net | `avrana-comics` | OIDC |
| Books | books.avrana.net | `avrana-books` | LDAP (Avrana username+password) |
| Movies & TV | watch.avrana.net | `avrana-videos` | Jellyfin (replicated password) |
| Requests | request.avrana.net | `avrana-requests` | Jellyfin-backed |
| Contribute | contribute.avrana.net | `library-contributors` | OIDC |

Jellyfin and Seerr are **link-only** apps (no OIDC): the tile + group gating are for *visibility*. Real enforcement stays at each app's own login: a non-video user can't get a Jellyfin account, so can't log in. (Defined in the gitignored `services/authentik/blueprints/avrana-landing.yaml`; captured by the nightly backup's `stack-config`.)

## Group → access cheat sheet
Put an invitee in exactly the groups matching what they should have. `avrana-users` is the baseline. `avrana-requests` should be granted **together with** `avrana-videos` (Seerr login rides on a Jellyfin account).

Personas:
- **Audiobooks-only:** `avrana-users`, `avrana-audiobooks`
- **Video-only:** `avrana-users`, `avrana-videos`, `avrana-requests`
- **Full-media:** all `avrana-*`
- **Library contributor:** add `library-contributors`

## Create a single-use invite (token never leaves Authentik)
In the Authentik admin UI → **Directory → Invitations → Create**:
- Flow: **avrana-invite**
- **Single use: on**, expiry a few days out.
- Custom attributes: carry the groups the flow will assign:
  ```json
  { "avrana_groups": ["avrana-users", "avrana-videos", "avrana-requests"] }
  ```
- Copy the resulting link `https://auth.avrana.net/if/flow/avrana-invite/?itoken=<token>` and send it to the person **directly** (message/email). **Never** paste an active token into chat, docs, git, or a handoff: a leaked one must be revoked (as one was, 2026-08-14).

## Verify the workflow (do this with the invitee, or a throwaway account in a private window)
1. Open the invite → create the account → land on `auth.avrana.net`.
2. **Confirm they see only their tiles** (e.g. a video-only user sees Movies & TV + Requests, not Audiobooks).
3. **Confirm blocked ≠ hidden:** in the same session, open a service they should NOT have (e.g. `listen.avrana.net`): sign-in should be **denied**, not just missing from the list.
4. Log in to each permitted app (see Welcome to Avrana for the per-app method).
5. Requests: first **Sign in with Jellyfin** creates the Seerr account.
6. Contributor only: `contribute.avrana.net` connects Audible.

## Offboarding (VERIFIED 2026-08-15: deleting the Authentik user is NOT enough)

Removing someone requires touching multiple systems. Proven the hard way: a test account deleted
only from Authentik was still **loginable in Jellyfin** afterward, because Jellyfin holds its own
replicated password copy independent of Authentik.

Steps, in order:
1. **Authentik**: Directory → Users → delete (or deactivate). Kills OIDC + LDAP logins + all
   portal tiles immediately.
2. **Jellyfin**: Dashboard → Users → delete the account. *This is the real access revocation for
   video*: skipping it leaves a working login. (Deactivating in Authentik does nothing to it.)
3. **Seerr**: Users → delete (rides on Jellyfin; remove separately).
4. **ABS** (optional, hygiene): Settings → Users → delete. ABS OIDC users have no local password
   so the orphan can't log in, but remove the stale record + listening history if you want.
5. **Komga / Calibre-Web**: only exist if the person ever logged in; delete in-app if so.

Deleting a media-server user removes the **user and their progress only**: never the shared
library/media (verified: ABS item count unchanged after offboarding).

## Offboarding (legacy note)
Remove the person's `avrana-*` groups in Authentik (kills OIDC + LDAP + tile visibility immediately). Then delete their **Jellyfin** account (Jellyfin dashboard → Users) and **Seerr** accoun: those are separate copies that group removal does *not* touch. Optionally deactivate the Authentik user.

## Password reset (until self-service exists)
No email/recovery flow is configured yet, so reset manually: Authentik admin → **Directory → Users →** the user → **Set password**. For Movies & TV, also reset their **Jellyfin** password (separate copy). *Follow-up: configure an SMTP email stage + a recovery flow so members can self-serve (pairs with the CWA Send-to-Kindle SMTP setup).*

## Known onboarding rough edges (fix as the beta surfaces them)
- **Movies & TV password doesn't sync** with Avrana password changes (credential replication, not SSO). Documented for members; only build sync if the beta shows it's a real problem.
- **Self-service password recovery** not available yet (needs SMTP).
- **App tiles have no icons** ye: functional but plain.
- **Komga** grants new SSO users all libraries by defaul: trim per-person only if needed.

## Partial-access invites (grant some apps now, pre-stage others)

Some invites should grant real access to only a subset of apps while getting a Jellyfin
identity ready for later: e.g. "Audiobooks + Contribute now, Movies & TV later." Two custom
attributes work together in the invitation's fixed_data:

```json
{
  "avrana_groups": ["avrana-users", "avrana-audiobooks", "library-contributors"],
  "avrana_precreate_jellyfin": true
}
```

- `avrana_groups` is the ONLY thing that grants real access: only the listed apps become
  usable and visible.
- `avrana_precreate_jellyfin: true` creates the Jellyfin account now but leaves it
  **disabled** (`IsDisabled: true` in Jellyfin's own policy): a real login block, not just a
  hidden tile, verified with a direct `AuthenticateByName` call returning 403. When ready to
  grant Movies & TV, two separate steps are needed: add `avrana-videos` to the user's
  Authentik groups (tile visibility) **and** toggle the account back on in the Jellyfin
  dashboard (Users → the account → uncheck "Disable this user").

**This does NOT work for Komga or Calibre-Web.** Both only create their local account as a
side effect of a successful SSO login (Komga OIDC, CWA LDAP), and that login is gated by the
same group that grants access: so there is no way to pre-create an account for either without
also granting access. If `avrana-comics`/`avrana-books` aren't in `avrana_groups`, no Komga/CWA
account exists yet; the first login after access is later granted creates it automatically,
same as any other user.

## Check that Home links a new member (Home 2.0, AVR-375)
Once Home 2.0 runs, after the invite is accepted, run this where Home's configuration lives:
`python services/avrana-home/tools/check_member_links.py <their Authentik username>`. Every row should say
`ok`; a `FIX` row says in plain words what to rename, create or enable in Jellyfin or Audiobookshelf. The member
never sees or enters an API key. It reads the libraries' user lists with Home's service keys, so on the live host
it is an owner-run step.
