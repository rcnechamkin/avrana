# OliveTin authorization group: proposal (AVR-498)

**Status: proposal only. Nothing in this document is applied.** No configuration, blueprint, Authentik object
or container was changed, and no live system, `.env` file or secret was read in writing it. Every live step is
marked **[OWNER APPROVAL]** and needs its own explicit approval. This follows the owner decision of 2026-10-15
in `docs/DECISIONS.md` ("OliveTin: a dedicated, unambiguous authorisation group, not username lists:
compatibility, group mapping and migration are verified before any live change is proposed"). Background on
the JWT identity work is in [D3-outpost-identity-proof.md](D3-outpost-identity-proof.md) and
[D3-adoption-and-olivetin-plan.md](D3-adoption-and-olivetin-plan.md).

## 1. What exists today (from the repository)

| Where | What it does |
|---|---|
| `services/olivetin/config/config.yaml` | `authHttpHeaderUsername: X-authentik-username`, `authHttpHeaderUsergroup: X-authentik-groups`, `authHttpHeaderUsergroupSep: "\|"`. `defaultPermissions` all `false` (view, exec, logs, kill). One ACL, `avrana-admins`, with `matchUsergroups: ["authentik Admins"]` **and** `matchUserNames: [akadmin]`, granting view, exec, logs and kill. Every action carries `acls: [avrana-admins]`. |
| `services/authentik/blueprints/avrana-olivetin.yaml` | Outer gate: a policy binding on the `avrana-olivetin` application for the group `authentik Admins`. Proxy provider with `access_token_validity: hours=8`. |
| `services/olivetin/tests/test-olivetin.sh` | Checks default-deny keys, that an ACL matches a usergroup, and that every action carries the ACL. It does not check `matchUserNames`. |
| `tests/test_network_isolation.py` | Pins that olivetin sits on the private `authentik_olivetin` network. Unrelated to authorisation. |
| `docs/findings/2026-10-06-authentik-blueprint-audit.md` (item 10) | Records that the `authentik Admins` group is, live only, a child of every `avrana-*` group, and is not in any blueprint. |
| `docs/services/avrana-portal.md` | The portal's Operations tile is gated on `authentik Admins`. |

## 2. Problems with the current arrangement

1. **A username list.** `matchUserNames: [akadmin]` grants a specific account, outside any group. The comment
   says it is there so "access survives a group rename". That is a standing individual exception, it can
   drift from Authentik's membership, and it is not visible in Authentik.
2. **The group is not dedicated.** `authentik Admins` is Authentik's own administration group. Being allowed to
   administer the identity provider and being allowed to restart containers, run backups and read host logs are
   the same grant. Anyone ever added to it for an Authentik reason also gets host operations.
3. **The name is ambiguous in other tokenisers.** `authentik Admins` contains a space. Today it works only
   because the header path declares `|` as the separator. The JWT path of OliveTin 3000.19.0 is reported (PoC
   evidence E9, from OliveTin's source, not re-verified here) to join a groups claim with spaces, which would
   split it into `authentik` and `Admins`. A group name should survive every consumer unchanged.
4. **Inherited membership.** Because `authentik Admins` is a child of every `avrana-*` group, group inheritance
   makes its members members of all library groups too. The OliveTin grant should not depend on that structure.
5. **Two gates with the same single name.** The outer Authentik binding and the inner OliveTin ACL both use
   `authentik Admins`, so changing one without the other either locks everyone out or leaves a mismatch.

## 3. Proposal: one dedicated group, `avrana-ops`

- **Name:** `avrana-ops`. Rule for every Avrana group name, already enforced for tokens by the verifier in
  `services/avrana-home/avrana_home/outpost_jwt.py` and for headers by `principal.py`: lower-case
  `[a-z0-9-]`, no spaces, no `|`, no `,`, no edge whitespace.
- **Purpose:** the only grant for the OliveTin console (and, if later wanted, the portal's Operations tile).
  It means "may run host operations through OliveTin" and nothing else.
- **Membership:** explicit users only (initially the owner). Not nested under any `avrana-*` group and not a
  parent of any group. It does not inherit from, or grant, `authentik Admins`, and the reverse.
- **No username lists** anywhere in OliveTin's ACL after migration (`matchUserNames` removed).
- **MFA:** enrolment for members of `avrana-ops` is recommended before step 7 below (audit item P4); that is a
  separate decision and not part of this proposal.

## 4. How OliveTin consumes it

OliveTin evaluates ACLs from the identity its auth chain produces. Two options, in order of adoption:

**A. Header path (today's mechanism, no OliveTin change except the ACL).** Keep
`authHttpHeaderUsername`, `authHttpHeaderUsergroup` and separator `|`. The ACL becomes:

```yaml
accessControlLists:
  - name: avrana-admins          # name kept so every action's `acls:` line is untouched
    matchUsergroups:
      - "avrana-ops"
    permissions: {view: true, exec: true, logs: true, kill: true}
```

The ACL name is deliberately kept: all actions reference `avrana-admins`, and `test-olivetin.sh` counts
`acls: [avrana-admins]` lines, so no action and no existing check needs editing.

**B. JWT path (after the D-3 decision for OliveTin).** `authJwtHeader: X-authentik-jwt`, `authJwtHmacSecret`
(owner-entered into `services/olivetin/.env` on the host; the repository only has `.env.example`),
`authJwtAud` (the provider's client id), `authJwtClaimUsername: preferred_username`,
`authJwtClaimUserGroup: groups`, and the header options **removed** (the PoC reports that trusted headers are
checked first and would shadow the token). A group without a space is exactly what makes B safe:
`avrana-ops` is unchanged by a space-join. **Unverified:** the option names and ordering come from the PoC's
reading of OliveTin 3000.19.0 and must be confirmed against the pinned image's source or a local fixture run
(section 6, check 1) before this is proposed live.

## 5. Group mapping

| Concept | Before | After |
|---|---|---|
| Authentik group allowed to open `ops.avrana.net` (outer gate, `avrana-olivetin.yaml`) | `authentik Admins` | `avrana-ops` |
| OliveTin ACL `avrana-admins` matches | group `authentik Admins` and username `akadmin` | group `avrana-ops` only |
| Portal Operations tile (`docs/services/avrana-portal.md`) | `authentik Admins` | `avrana-ops` (separate portal change, optional) |
| Owner account | listed by name and by Admins membership | member of `avrana-ops` |
| Other `authentik Admins` members | implicitly allowed | not allowed unless added to `avrana-ops` |

Effect to state to the owner: anyone relying on `authentik Admins` membership alone loses console access when
the final step lands. The step 1 inventory below lists who that is before anything is removed.

## 6. Compatibility checks (all offline, none run in this PR)

1. Read the pinned OliveTin release's source (digest named in `services/olivetin/docker-compose.yml`) and
   record, with file and line: the auth-chain order, how the header groups value is split, how a JWT groups
   array is joined, and whether `matchUsergroups` compares exact strings.
2. In a local, fixture-only container with a synthetic secret and the proposed config, test: a member of
   `avrana-ops` (sees and runs actions), a member of `authentik Admins` only (sees nothing), a user in neither,
   a user with both, an absent group header, a duplicated group header, and for option B a forged and an
   expired token. Expected: only `avrana-ops` members are served.
3. Extend `services/olivetin/tests/test-olivetin.sh` or add a stdlib test that fails if the committed config has
   `matchUserNames`, any group name containing whitespace, `|` or `,`, a missing `acls:` on any action, or a
   non-empty `defaultPermissions`. (Today's script would pass with `akadmin` still listed.)
4. Add a blueprint check that the binding on `avrana-olivetin` names `avrana-ops`, and that no blueprint binds
   OliveTin to a group with a space.

## 7. Migration steps

Each live step stops and is verified before the next. Offline PRs are reviewed and merged first.

0. Offline PR: checks of section 6 (3) and (4) added, passing against today's config. No behaviour change.
1. **[OWNER APPROVAL]** Read-only inventory in the Authentik admin UI of who is in `authentik Admins`, and
   confirm which of them need host operations. Record names in the owner's notes, not in the repository.
2. Offline PR: ACL `avrana-admins` matches **both** `avrana-ops` and the old entries (union), blueprint binding
   lists **both** groups. Safe resting state: nobody loses access.
3. **[OWNER APPROVAL]** Create the Authentik group `avrana-ops` (no parents, no children) and add the owner.
4. **[OWNER APPROVAL]** Apply the blueprint change and deploy the union OliveTin config (container restart, run
   by the owner). Verify the owner reaches the console and can run the harmless `health_report` action.
5. **[OWNER APPROVAL]** Prove the new path alone: on a staging copy or by temporarily testing with a second,
   non-admin test account in `avrana-ops` only, confirm it is served, and a test account in `authentik Admins`
   only is not (after step 6 is staged, not applied).
6. Offline PR: remove `authentik Admins` and `akadmin` from the ACL, and `authentik Admins` from the
   binding. **[OWNER APPROVAL]** to deploy it (restart).
7. Optional, later and separately approved: option B (JWT) for OliveTin, after the verified-identity work is
   accepted. **[OWNER APPROVAL]**

## 8. Rollback

- Every config change is a Git revert of the one PR plus an owner-run restart. **[OWNER APPROVAL]** for each
  restart.
- From the union state (after step 2) rollback is not needed for access: both grants work.
- If step 6 locks the owner out: the owner restores the previous `config.yaml` and blueprint from Git and
  restarts OliveTin; Authentik's own admin UI is unaffected because `authentik Admins` is untouched
  throughout. The group `avrana-ops` can stay; it grants nothing without the ACL.
- If a mistaken member is in `avrana-ops`, removing them in Authentik takes effect at their next token or
  session refresh (session lifetime 8 hours, `avrana-olivetin.yaml`); to cut a session sooner the owner ends
  it in the Authentik admin UI **[OWNER APPROVAL]**.

## 9. Owner decisions needed

1. Approve the name `avrana-ops` and the "explicit members only, no nesting" rule.
2. Decide whether the portal's Operations tile moves to `avrana-ops` in the same change.
3. Decide whether `akadmin` stays as a break-glass username entry (not recommended: it is the individual
   exception this proposal removes) or access is recovered through Git revert and restart only.
4. MFA for `avrana-ops` before step 6 (audit item P4).
