# G1 independent review: identity-header bypass paths (AVR-345)

**Status: review of staged code only. G1 is NOT applied and NOT production-ready.** Nothing here was run
against the host. Reviewed `main` at `2264321` (PR #6 merged as staged code, PR #4 portal suite, PR #5 Kindle,
PR #9 Media 2.0 principal). Reviewer: an agent that did not write PR #6.

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
| F3 | Every layer assumes the pinned outpost **overwrites** client-sent `X-authentik-*` headers (comments in the compose files and `kindle.py` assert it). Not proven anywhere for this image digest. | High until verified | Owner check E added to the runbook (unauthenticated + member-session forged-header test). |
| F4 | `authentik-server` publishes 9000 on `10.0.0.218` (LAN) as well as loopback: a LAN path to the outpost that skips Cloudflare. It still authenticates; it is only as safe as F3. | Low | Pinned to explicit addresses by test; covered by check E (`lan` rows). |
| F5 | Proxy providers must stay `mode: proxy` with no `skip_path_regex` (forward-auth modes need another proxy to strip headers; skipped paths forward unauthenticated requests). | Medium if changed | Correct today; pinned by test. |
| F6 | Header-name variants (`X_authentik_groups`, `HTTP_X_AUTHENTIK_*`, `Remote-User`, `X-Forwarded-User`, trailing characters, space before colon) grant nothing in portal, Kindle or the principal parser, because Python's stdlib does not fold them. A future WSGI/ASGI server for Media 2.0 **would** fold `_` into `-`. | Medium for M3 | Pinned by tests (incl. the stdlib assumption) so a server change fails CI. |
| F7 | Host namespace and host root reach every bridge IP; ufw is off. G1 does not address it. | Residual | Unchanged: D-3 shared-secret header remains the only fix; owner decision. |
| F8 | `services/avrana-kindle-connector/tests/test_kindle.py` live tests probe via `authentik_frontend`; they will stop working after apply. | Info | Already noted in the runbook; excluded from offline CI. |

No defect was found in `check-network-isolation.py`'s decision logic: it inspects every network on the
host (not only the five named), fails closed on odd shapes, and the pre-apply WARN is intentional. Existing
coverage for forged/duplicate/CRLF/near-miss headers in PR #4 and PR #5 was confirmed sufficient.

## New deterministic tests

`tests/test_g1_bypass_paths.py`, 23 tests, offline, in `run_offline.py` discovery and CI. Mutation check:
6 of 6 hand mutants killed (namespace borrow, provider mode, `0.0.0.0` publish, direct ingress, DNS alias,
underscore header folding).

## Owner approval packet (AVR-356, decision D-2)

Nothing below is authorised by this review. Each item needs the owner's separate approval.

1. **Read-only, before any approval** (agent may prepare commands, owner runs on host):
   address-pool headroom; network/container record; namespace-sharing check (Verify); check E part 1
   (unauthenticated forged headers, no credential). Any surprise: stop.
2. **Approve or decline**: the two pre-apply WARN behaviours (missing docker data and inspect failure warn
   before sign-off); the maintenance window; rollback material staged and SHA-256 recorded.
3. **Apply** strictly per `docs/runbooks/g1-network-isolation.md`, one service at a time, health timer stopped.
4. **Validate**: Verify section, forgery checks A–C, E (both parts), namespace check, health script, drift
   check. A failed control voids the result.
5. **Sign off** only after all pass: marker file, timer restarted, evidence recorded in `docs/DECISIONS.md`
   (D-2) and on AVR-356. Until then G1 is not applied.
6. **Rollback**: Branch 1 (apps not recreated) or Branch 2 (apps recreated) as in the runbook; remove the
   marker first; triggers listed under Stop conditions, now including F1 and check E.

## Blockers to closing AVR-345

- Host evidence for F1/F3 (owner-run, read-only) — required before claiming the boundary holds.
- D-3 decision for the host-namespace residual (F7), or an explicit owner risk exception.
- AVR-356 apply and post-apply evidence; M3 member-data access stays blocked until then.
