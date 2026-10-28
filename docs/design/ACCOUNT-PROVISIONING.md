# Home creates missing library accounts

Status: BUILT, NOT ENABLED. Owner answered section 6 on 2026-10-28 ("Go with your recommendations"). Code:
`avrana_home/provision.py`, wired in `app/main.py` (`_gather`); contract: ADAPTER-CONTRACT 15. Off until
`HOME_PROVISION_ACCOUNTS` names a library; section 5's live proof is still to do. Owner direction 2026-10-28: "Yes it should" (Home should create a member's
library accounts so nobody has to visit each library first). This document says how, what it will never do,
and the choices left for the owner (section 6).

## 1. The gap today

Home matches a signed-in member to the library account with the **same username** (IDENTITY-MAPPING 1). Every
library already creates that account by itself, but only on the member's first sign-in **to that library**
(read-only audit of avrana, 2026-10-28):

| Library | Account appears when | Today's Home result before that |
|---|---|---|
| Jellyfin | first sign-in to Jellyfin (LDAP plugin, `CreateUsersFromLdap=true`, group `avrana-videos`) | "not set up yet" (`NOT_LINKED`, `unmapped`) |
| Audiobookshelf | first "Sign in with Avrana" (OIDC auto-register, matches an existing account by email) | same |
| Komga, Calibre-Web | not needed by Home: shared view (ADAPTER-CONTRACT 12.2, 13.2) | works from the first visit |

On 2026-10-28 one member with `avrana-videos` had no Jellyfin account and six members with
`avrana-audiobooks` had no Audiobookshelf account, so Home showed them nothing from those libraries.

## 2. Proposal: create the account on the member's first Home visit

When a Jellyfin or Audiobookshelf section comes back `NOT_LINKED` with reason `unmapped`
(exactly zero accounts with that name, so never `ambiguous`, `disabled` or a case mismatch), and the member
holds the library's group, Home creates the account once and re-reads the section.

The created account is the **same account the library would have created on the member's first sign-in**,
so the member's later direct sign-in lands in it instead of making a second one:

* **Jellyfin:** `POST /Users/New` with the member's username. Then `POST /Users/{id}/Policy` sets the
  authentication provider to the LDAP plugin (`Jellyfin.Plugin.LDAP_Auth.LdapAuthenticationProviderPlugin`),
  not administrator, and all libraries (the plugin's own `EnableAllFolders=true`). The member signs in to
  Jellyfin with their Avrana password, exactly as before. No local password is ever set.
* **Audiobookshelf:** `POST /api/users` with the member's username and email (from the verified token),
  type `user` and the default user permissions. A random password is generated, used for the request, and
  discarded, so it is never stored or logged. ABS's "match existing by email" then links the member's first
  "Sign in with Avrana" to this account.

### What it never does

* Never changes, renames, enables or deletes an existing account; never touches Komga or Calibre-Web.
* Never creates an administrator or grants more than the library's own first-sign-in default.
* Never creates for a member without the library's group, for a name that exists in any letter case, or for
  a principal that is not from a verified token (`HOME_IDENTITY_MODE=jwt_required` only).
* At most one attempt per member and library per hour, a per-member lock, and a global cap (for example
  10 creations per hour); past the cap it stops and logs, and the member keeps the "not set up yet" sentence.
* Logs one fixed event per attempt (`provisioned`, `refused:<reason>`, `failed:<reason>`) through logsafe:
  never a password, token or upstream id.
* Off by default (`HOME_PROVISION_ACCOUNTS=off`); the owner turns it on per library.

## 3. Why on the Home visit (and not a background sync)

| | First Home visit (proposed) | Background sync from Authentik groups |
|---|---|---|
| New secret | none: the Jellyfin key and ABS token Home already holds can create users | an Authentik API token with user and group read |
| Covers someone who never opens Home | no (they still get an account on their first library sign-in) | yes |
| Moving parts | one hook where `NOT_LINKED` is already decided | a scheduler, Authentik pagination, removal rules |
| Identity source | the verified token Home already trusts | a second identity source to keep consistent |

The sync can come later without undoing anything here.

## 4. Where it lives

A separate `avrana_home/provision.py` holds the two create calls. The read adapters stay read-only, and their
guarded transports keep refusing every non-GET. It is called from one place, after the section gather, only
for `unmapped`. This changes Home from read-only to "read-only plus account creation", so the
ADAPTER-CONTRACT read-only clause gets an amendment naming exactly these two writes.

## 5. Proof before it goes live

* **Offline:** fakes for both create APIs. Tests cover every refusal in "What it never does", the cap, the
  lock, idempotence (two tabs at once create one account), and logs carrying no secrets.
* **Parity:** read-only, compare the policy of a Jellyfin account the LDAP plugin created (e.g. Tyler's) with
  the one Home would create, field by field. Done 2026-10-28 across all 15 accounts (counts only): LDAP-made
  accounts differ from Jellyfin's defaults only in `AuthenticationProviderId` and `PasswordResetProviderId` (both
  the plugin), which provision.py sets; it also pins non-admin, all libraries, no deletion, no remote control. For ABS, confirm on the live 2.36.0 that an email-matched OIDC
  sign-in links to a pre-created account (unverified until tested).
* **One real member:** the owner turns it on for Jellyfin, a member without an account opens Home, the account
  appears, and that member then signs in to Jellyfin directly and lands in the same account.

## 6. Owner choices (answered 2026-10-28: all as recommended)

| # | Question | Recommendation (chosen) |
|---|---|---|
| P1 | Trigger: first Home visit, or a background sync too? | Home visit now, sync later if wanted |
| P2 | Jellyfin library access for created accounts | All libraries (what the LDAP plugin gives today) |
| P3 | Audiobookshelf library access and permissions | ABS defaults for a new user (what OIDC auto-register gives today) |
| P4 | Who: everyone with the group, or only the beta's allowed users first? | Beta allowed users first, then everyone |
| P5 | Global cap per hour | 10 |
