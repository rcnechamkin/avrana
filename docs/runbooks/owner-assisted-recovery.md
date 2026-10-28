# Owner-assisted account recovery

Draft, 2026-10-27, for Media 2.0 decision AS-06. **The exact proof of identity is an owner decision**; the steps below
are the minimum the supplement asks for. Use this only when a member has lost both their email access and every
sign-in method. A member who still has their email uses "Forgot password?" on the sign-in page.

## Before doing anything

1. The request must reach you, or be confirmed by you, through a channel you **already** use with that person (their
   known phone number, in person, an existing chat). Never act on a message from a new address or number alone, and
   never accept "I changed my email" as proof.
2. Confirm on that channel that they asked. If anything doesn't match, stop.

## Restore access

Prefer Authentik's admin interface over the database:

1. Admin → Directory → Users → the member.
2. If their email is wrong and they've proven who they are, correct it there.
3. Create a **recovery link** for them (Authentik builds it from the brand's recovery flow, `avrana-recovery`). Check
   that this action exists in the deployed version before relying on it.
4. Send the link over the same established channel. It is a credential: no screenshots, no shared docs, no support
   notes containing it.
5. If they lost their passkey or authenticator too, delete the lost device under the user's MFA Devices **and** delete
   their sessions (a lost phone keeps working until both are gone; `docs/services/authentik-sessions-passkeys.md`).
6. Ask them to sign in, then add a new passkey or authenticator from Me → Account & Security.

Their **TV and Movies (Jellyfin)** password is a separate copy and doesn't change with any of this. Reset it in the
Jellyfin dashboard if they need it.

## Record it

Write one line in your own log: date, member, what you checked to confirm it was them, what you changed. Tell the
member, through the established channel, what was changed.

## Don't

- Don't activate or edit users with SQL when the admin interface can do it.
- Don't email a recovery link to an address you just changed on someone's say-so.
- Don't keep a copy of a recovery link or code anywhere.
