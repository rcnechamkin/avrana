# G1 independent review: identity-header bypass paths (AVR-345)

**Status: review of staged code only. G1 is NOT applied and NOT production-ready.** Nothing here was run
against the host. Reviewed `main` at `2264321` (PR #6 merged as staged code, PR #4 portal suite, PR #5 Kindle,
PR #9 Media 2.0 principal). Reviewer: an agent that did not write PR #6. Pinned images resolved by digest:
Authentik `ghcr.io/goauthentik/server@sha256:ed120caf…` = **2026.5.6** (registry manifest match, 2026-10-14);
source read at tag `version/2026.5.6` (commit `0c67ea4`), not executed.

## Scope

The three header-trusting backends (`avrana-portal`, `avrana-kindle-connector`, `olivetin`), the
embedded outpost in `authentik-server`, the staged private networks, the drift guard
(`scripts/check-network-isolation.py` + `services-health.sh` hook), the cloudflared ingress, the proxy
provider blueprints, and the Media 2.0 principal parser (`services/avrana-home/avrana_home/principal.py`).

## Current vs staged

| | Deployed (per repo history, unverified on host) | Staged on `main` |
|---|---|---|
| Backends' network | `authentik_frontend`, shared with `authentik-worker`, `authentik-ldap` | own `authentik_<name>`, shared with `authentik-server` only |
| Forged header from a sibling | **possible** (worker/ldap, or anything attached to `authentik_frontend`) | blocked for bridge siblings |
| Host namespace (Jellyfin, HA, Beszel agent, host shell) | can reach backends | **still can** (residual, D-3) |
| Drift guard | absent | WARN before sign-off, FAIL after |

```
cloudflared (host) ──► localhost:9000 ─┐            LAN ──► 10.0.0.218:9000 ─┐
                                       ▼                                     ▼
                         authentik-server (embedded outpost; sets X-authentik-*)
              ┌──────────────┬─────────────────┬──────────────────┬─────────────────┐
     authentik_frontend  authentik_portal  authentik_kindle  authentik_olivetin  authentik_backend
     worker, ldap        avrana-portal     kindle-connector  olivetin            postgresql
```

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| F1 | A container with `network_mode: container:<authentik-server or backend>` shares that namespace, never appears in `docker network inspect`, and passes the drift guard while reaching all three private networks. | High if present | No such service in the repo. Static guard added; read-only host check added to the runbook (Verify). |
| F2 | A sibling that answers to a backend's DNS name (alias, `hostname`, `container_name`) on a network the outpost shares could receive authenticated, header-carrying requests. | Medium | None found. Static guard added. |
| F3 | Every layer assumes the outpost **overwrites** client-sent `X-authentik-*` headers. Source for 2026.5.6 supports it: in proxy mode every authenticated request goes through `addHeaders`, which `Set`s username, groups, email, name, uid, jwt and meta headers and deletes every underscore-variant header (`internal/outpost/proxyv2/application/mode_common.go`, `mode_proxy.go`). Source reading is not host proof. | High until verified on the host | Only runbook check **E2** (authenticated, owner-run) is host evidence. E1 proves only that unauthenticated requests are redirected. |
| F4 | `authentik-server` publishes 9000 on `10.0.0.218` (LAN) as well as loopback: a LAN path to the outpost that skips Cloudflare. It still authenticates; it is only as safe as F3. | Low | Pinned to explicit addresses by test; covered by check E (`lan` rows). |
| F5 | Proxy providers must stay `mode: proxy` with no `skip_path_regex` (forward-auth modes need another proxy to strip headers; skipped paths forward unauthenticated requests). | Medium if changed | Correct today; pinned by test. |
| F6 | Header-name variants (`X_authentik_groups`, `HTTP_X_AUTHENTIK_*`, `Remote-User`, `X-Forwarded-User`, trailing characters, space before colon) grant nothing in portal, Kindle or the principal parser, because Python's stdlib does not fold them. A future WSGI/ASGI server for Media 2.0 **would** fold `_` into `-`. | Medium for M3 | Pinned by tests (incl. the stdlib assumption) so a server change fails CI. |
| F7 | Host namespace and host root reach every bridge IP; ufw is off. G1 does not address it. | Residual | Unchanged: D-3 shared-secret header remains the only fix; owner decision. |
| F9 | `intercept_header_auth` is absent from the blueprints and defaults to **true** (`authentik/providers/proxy/models.py`): the outpost accepts `Authorization: Bearer`/Basic credentials and verifies them against Authentik. That is an extra authentication path, not a forgery path. | Low | Recommend setting it to `false` explicitly in the three blueprints during the approved AVR-356 change; not changed here. |
| F10 | The outpost copies `ak_proxy.user_attributes.additionalHeaders` **over** its own identity headers, and the default `ak_proxy` mapping fills `user_attributes` from the user's group attributes. An attribute named `additionalHeaders` on a user or group (an admin edit, or a prompt writing `attributes.*`) could set `X-authentik-groups` for that user. | High if present | None in the blueprints today. Guard test added. Host check: owner confirms in the admin UI that no user or group attribute contains `additionalHeaders`. |
| F8 | `services/avrana-kindle-connector/tests/test_kindle.py` live tests probe via `authentik_frontend`; they will stop working after apply. | Info | Already noted in the runbook; excluded from offline CI. |

Limits: the static tests cover compose files in `services/` and `deploy/` only; a container started by hand (`docker run`) or from an unversioned compose file on the host is covered only by the runbook's host checks.

No defect was found in `check-network-isolation.py`'s decision logic: it inspects every network on the
host (not only the five named), fails closed on odd shapes, and the pre-apply WARN is intentional. Existing
coverage for forged/duplicate/CRLF/near-miss headers in PR #4 and PR #5 was confirmed sufficient.

## New deterministic tests

`tests/test_g1_bypass_paths.py`, 24 tests, offline, in `run_offline.py` discovery and CI. Mutation check:
7 of 7 hand mutants killed (namespace borrow, provider mode, `0.0.0.0` publish, direct ingress, DNS alias,
underscore header folding, attribute-writing prompt). Independent review: CHANGES REQUESTED (check E
pass criterion, fail-open namespace grep, weak test name); all three fixed in this PR.

## Owner approval packet (AVR-356, decision D-2)

Nothing below is authorised by this review. Each item needs the owner's separate approval.

1. **Read-only, before any approval** (agent may prepare commands, owner runs on host):
   address-pool headroom; network/container record; namespace-sharing check (Verify, must report a non-zero
   inspected count); check E1 (unauthenticated, no credential); F10 attribute check in the admin UI. Any surprise: stop.
2. **Approve or decline**: the two pre-apply WARN behaviours (missing docker data and inspect failure warn
   before sign-off); the maintenance window; rollback material staged and SHA-256 recorded.
3. **Apply** strictly per `docs/runbooks/g1-network-isolation.md`, one service at a time, health timer stopped.
4. **Validate**: Verify section, forgery checks A–C, E1 and E2 (E2 is the only F3 evidence), namespace check, health script, drift
   check. A failed control voids the result.
5. **Sign off** only after all pass: marker file, timer restarted, evidence recorded in `docs/DECISIONS.md`
   (D-2) and on AVR-356. Until then G1 is not applied.
6. **Rollback**: Branch 1 (apps not recreated) or Branch 2 (apps recreated) as in the runbook; remove the
   marker first; triggers listed under Stop conditions, now including F1 and check E.

## Blockers to closing AVR-345

- Host evidence for F1/F3 (owner-run, read-only) — required before claiming the boundary holds.
- D-3 decision for the host-namespace residual (F7), or an explicit owner risk exception.
- AVR-356 apply and post-apply evidence; M3 member-data access stays blocked until then.
