# Owner runbooks

What only the owner can do for Media 2.0 milestone M0, in the order that unblocks the most. Nothing on
this list has been run. Every item needs the owner on the host or in a vendor console; the agent never
holds a secret and never changes production (`AGENTS.md`). Times are estimates for a focused session.

| # | Runbook | Issue | Unblocks | Owner time | Agent can | Only the owner can |
|---|---|---|---|---|---|---|
| 1 | [SMTP2GO rotation and mail proof](m0-smtp2go-email.md) | AVR-346 | Invites, resets, every alert and notification; M1 invite tests; launch | 45 to 60 min | Trace consumers, write snippets, later stage an alert-setup script | Rotate in SMTP2GO, type values, recreate the Authentik worker, run and witness the three e-mail tests |
| 2 | [akadmin MFA, break-glass, proposals P1 to P6](m0-authentik-admin-mfa.md) | AVR-347 | M0 gate; safe administration for everything after | 30 min (enrol and test) plus 30 min decisions | Analyse and draft blueprint edits (P4 on request) | Enrol factors, store codes, decide P1 to P6, deploy, smoke test |
| 3 | [Off-host backup check and restore drill](m0-offhost-backup-restore.md) | AVR-350 | Recovery gate; the safety net for every later change | 30 min (checks) plus 45 min (drill) | Maintain the tooling and tests | Raise the B2 cap, type B2 and crypt values, run the drill |
| 4 | [Seerr CSRF and proxy trust](m0-seerr-csrf-proxy-trust.md) | AVR-348 | M0 prerequisite for the public request path | 45 min with an iPhone | Trace the path, write the matrix | Toggle the settings, run client tests, accept or reject an exception |

Order notes:

- 1 first: it is the longest wait (an inbox) and gates three other things. Run 2's recovery smoke test after it.
- 3 before any production change you approve afterwards (G1 window, P1 to P6, Seerr): know that you can get
  back before you change anything. Do the full download once, late in the UTC day.
- 4 is last because it is the only one that can break a member-facing client; do it when you can test with a phone.
- Items 1 to 3 can be done in one sitting of about three hours. Do not combine 4 with them.

Rules that apply to all four:

- Secrets go from 1Password to a hidden prompt or a vendor form. Never into chat, a ticket, a file in Git, or
  a command line.
- Stop on anything unexpected, record it, and ask. Approval for one runbook does not cover another.
- Evidence is secret-free: timestamps, exit codes, counts, pass or fail. Put it in a dated file under
  `docs/findings/` and a comment on the Linear issue.

Related, owned elsewhere: gate G1 (network isolation) has its own runbook when it lands; the full list of
owner actions is in [the roadmap](../ROADMAP.md) and [the owner scripts](../../deploy/host/owner-scripts/README.md).
