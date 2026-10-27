# Home rollback and degraded-library rehearsal (AVR-388)

Status: prepared 2026-10-27, **nothing in it has been run on the host**. Part A runs in CI on every change; parts B
to D are the owner's, each needs its own yes at the time, and an agent never runs them (`AGENTS.md`). The design
is MEDIA-2.0.md section 5 ("Recovery and rollback"): Home is stateless, cut-over and rollback are one upstream
switch on an Authentik proxy provider, and the previous portal container stays deployed for two weeks.

Order: A (proof without the host) → B (beta container on the host) → C (one real library degraded, off-peak) →
D (provider round-trip on the **beta** hostname). The production round-trip itself belongs to AVR-389's cut-over
window, after D has passed once.

## Stop criteria (all parts)

Stop, put things back with the part's own "Undo", and record what happened if any of these occurs:

- the portal at `avrana.net` stops answering, or a member reports a problem;
- any per-service hostname (watch, listen, read, books) stops answering;
- a page shows another member's item, or a library the viewer is not in;
- Home answers 5xx for more than one minute, or the page itself (not one section) fails;
- anything happens that the step does not describe.

## A. Degraded library, mocks only (CI, no approval needed)

`.github/workflows/beta-image.yml` builds `Dockerfile.beta`, runs it, and inside the container runs
`beta/rehearse_degraded.py`: the Jellyfin **mock** goes down; within about 30 s Jellyfin's Continue reads
"unavailable" while Audiobookshelf, Komga and Calibre-Web stay ok and the page answers 200 (Recently added keeps
its cached items for up to 120 s, by design); the mock comes back and Jellyfin recovers by itself, no restart.
Local run (2026-10-27, Windows, loopback): degraded at 30.5 s, recovered 2 s after the mock returned.

## B. The same rehearsal on the host, in the beta container **[OWNER APPROVAL]**

Needs the beta image built on the host (BETA-CHECKLIST section 0) and nothing published: the container talks to
nobody but its own loopback mocks.

```
docker build -f services/avrana-home/Dockerfile.beta --build-context portal=services/avrana-portal -t avrana-home-beta:local services/avrana-home
export HOME_JWT_ISSUER=https://auth.example.test/application/o/rehearsal/ HOME_JWT_AUDIENCE=rehearsal HOME_JWT_SECRET="$(openssl rand -hex 32)"
docker run -d --name beta-rehearsal --network none -e HOME_IDENTITY_MODE=jwt_required -e HOME_JWT_ISSUER -e HOME_JWT_AUDIENCE -e HOME_JWT_SECRET avrana-home-beta:local
docker exec beta-rehearsal python3 -B beta/rehearse_degraded.py
```

Pass: the last line is `PASS: recovered by itself`. **Undo:** `docker rm -f beta-rehearsal` (nothing else changed;
the key was throwaway and only in that shell).

## C. One real library degraded, off-peak **[OWNER APPROVAL]**

This is physical test P11 (CONTINUE-AND-HANDOFF.md section 6) against the **owner preview** (LAN, the owner's own
data; `docs/runbooks/home-owner-preview.md`), never against members. Pick Audiobookshelf: its outage costs the
least, and the native apps keep their downloads.

1. Note the time. Open the owner preview Home on a phone and a laptop; both show Audiobooks.
2. `docker stop audiobookshelf` on the host.
3. Within about 30 s, reload: "Audiobooks are unavailable right now.", Listen struck through and linking to the
   help section; Movies and TV, Comics and Books unchanged; `scripts/services-health.sh` reports Audiobookshelf
   down and nothing else.
4. `docker start audiobookshelf`. Wait for its own health check, then reload Home (a cool-off of about a minute
   may delay it): Audiobooks are back without restarting Home.

**Undo:** `docker start audiobookshelf` (step 4 is the undo). If it does not come back healthy within five
minutes, follow the service's own recovery in OPERATIONS.md; Home needs nothing.

## D. Provider round-trip on the beta hostname **[OWNER APPROVAL]**

Proves the switch mechanics on a hostname no member uses. Preconditions: BETA-CHECKLIST sections 1 to 5 done
and passed (the beta hostname, its own Authentik proxy provider, the beta container on the outpost's network).

1. Record the beta provider's current **internal host** (the beta container) in the dated findings file.
2. In the Authentik UI, set the beta provider's internal host to the **portal** container's address (the value
   the `avrana-portal` provider uses). Save. Within a minute, signed in as `akadmin`, `https://<beta-host>/`
   shows the current portal. Time it.
3. Set it back to the beta container. Within a minute the beta Home is back; smoke test 3 of BETA-CHECKLIST
   section 5 passes again. Time it.
4. Repeat steps 2 and 3 once more if either took longer than two minutes or showed an error page.

**Undo:** set the internal host to the value recorded in step 1. The production `avrana-portal` provider is never
edited in this part.

## Record (dated file under `docs/findings/`, and a comment on AVR-388)

| Part | Date and time | Result (pass/fail) | Durations | Notes (no secrets, no member names) |
|---|---|---|---|---|
| A | 2026-10-27 05:38 UTC, [run 40456490943](https://github.com/rcnechamkin/avrana/actions/runs/40456490943) (main after #92) | pass | degraded at 30.2 s, recovered 2.0 s after the mock returned | smoke 7/7; also runs on every Home change |
| B | | | | |
| C | | | outage seen after, recovered after | what Help and the health script showed |
| D | | | switch to portal, switch back | |

Done when A to D have passed once and the record is linked from AVR-388. The production round-trip and the
two-week retention of the previous portal container are part of AVR-389.
