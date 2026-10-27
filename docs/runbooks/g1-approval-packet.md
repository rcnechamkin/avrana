# G1 approval packet (AVR-356, decision D-2)

**Nothing here is approved yet, and G1 is not applied.** This is the exact list of what the owner is asked to
approve, in order, each as its own decision. The procedure is
[`g1-network-isolation.md`](g1-network-isolation.md). The independent review and its findings are in
[`../audits/2026-10-14-g1-independent-review.md`](../audits/2026-10-14-g1-independent-review.md). An agent may
prepare commands and read the output the owner pastes back; it does not run anything on the host.

Evidence is labelled by where it comes from, and only one kind counts for each claim:

| Label | Means | Can show |
|---|---|---|
| **Local** | Offline tests on a development machine | The code and the scripts behave as written |
| **CI** | GitHub Actions on the pull request | The same, reproducibly (the offline workflow runs on every PR since #90 fixed its YAML; it was never billing) |
| **Production** | Read-only output from the host, run by the owner | The real state. Required for every G1 claim |

## Step 1. Read-only preflight (approval: run read-only commands on the host)

On the host, from an export of the reviewed commit:

```sh
scripts/g1-preflight.sh                       # first pass, before rollback material exists: always ends
                                              # with one STOP (rollback material not checked) and exit 1
scripts/g1-preflight.sh --rollback "$B/rollback" --e1   # final pass, the day of the window
```

`--e1` sends six unauthenticated requests with forged headers: three over HTTPS to the public hostnames and
three over plain HTTP to the LAN outpost port (`10.0.0.218:9000`, with each hostname as `Host`). No credential
is sent and nothing changes. Leave it out if even that is not wanted.

| Check | Pass means | A STOP means |
|---|---|---|
| Subnets | `10.220.29-31.0/24` overlap no Docker network and no host route (the networks use explicit subnets, not the address pools; `daemon.json` is information only) | Pick other free `10.220.x.0/24` in the compose file and `G1_SUBNETS`, re-run |
| G1 state | none of the three private networks exists | Investigate before anything else |
| Namespace sharing | non-zero inspected count, no `net=container:` | A G1 bypass exists today: report it, do not apply |
| Containers | `authentik-server` and the three backends running and healthy | Fix that first |
| Local backup | `LAST_RUN.json` status ok and under 26 h old | Wait for a clean run |
| Off-host backup | `OFFHOST_LAST_RUN.json` ok and under 50 h old | Wait for a clean sync |
| Rollback material | five files present, each matching its own line in the `SHA256SUMS` staged with them (this proves the copy is intact, not that it matches production: the staging step does that) | Stage it again (precondition 3) |
| E1 | for all six, `302` to `https://<same host>/outpost.goauthentik.io/start…` or to `https://auth.avrana.net/…` | A backend answered unauthenticated: G1 failure |
| *(manual)* F10 | no user or group attribute named `additionalHeaders` in the Authentik admin UI | An identity-override path exists: report it |

The script exits 0 only with no STOP and no VOID. A VOID (it could not read something) is not a pass.

## Step 2. Decisions before the window (each one separately)

1. **D-2 window:** a quiet weekday evening. SSO is down for about a minute while `authentik-server` is
   recreated, and each app for a few seconds. Members are told beforehand.
2. **The two deliberate pre-apply warnings** in the health hook: before sign-off, docker data that cannot be
   read and a missing Python only WARN. After sign-off they FAIL.
3. **Health timer:** stopped for the window and restarted after sign-off or rollback.
4. **Throwaway probe containers** for forgery check B: each `docker run --rm` on `authentik_frontend` is a
   production change, labelled as such in the runbook.

## Step 3. Apply (approval: the listed **[CHANGES PRODUCTION]** steps, in this window only)

Runbook "Apply" steps 0 to 3, one service at a time, stopping on any stop condition.

## Step 4. Validate (read-only, except check B's throwaway containers)

The runbook's Verify section (including the namespace check), forgery checks A, B and C, E1, and **E2**.
E2 is the owner, signed in as a member, adding forged headers in a browser. It is the only evidence that
the outpost overwrites client headers (review finding F3). After that: the health script and the drift
check. A failed control voids its check.

## Step 5. Sign off (approval: one state file)

Only when step 4 passes completely: create the `g1-applied` marker, restart the timer, record the result in
`docs/DECISIONS.md` (D-2) and on AVR-356 with the production output attached. Until then G1 is **not
applied**, whatever the repository says.

## Rollback (pre-approved as part of step 3's approval, or approve now)

Remove the marker if set, then follow the runbook's Branch 1 (apps not yet recreated) or Branch 2 (apps
recreated), using the staged compose files after checking their SHA-256. Triggers are the runbook's stop
conditions. Expected disruption is the same as the apply. Afterwards Git differs from production until the
owner decides; record that.

## Not covered by G1 (separate decisions)

- The host network namespace: the host, Jellyfin, Home Assistant and Beszel can still reach the backends.
  D-3 (verifying the outpost's signed JWT) is the proposed fix; see `docs/design/D3-outpost-identity-proof.md`
  once that pull request is merged.
- Bearer/Basic authentication at the outpost (review finding F9): no switch closes it in 2026.5.6.
