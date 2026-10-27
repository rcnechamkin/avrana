# Home: a library is unavailable (operator escalation, AVR-385)

Status: written 2026-10-27 from the code and the offline tests. Home 2.0 is **not deployed**; nothing here
has been run on host `avrana`. Every step that touches the host is the owner's (`AGENTS.md`): observe first,
change one thing, verify.

## What members see, and what keeps working

Home asks each library separately, with its own timeout and circuit breaker (HOME-APP.md section 3,
ADAPTER-CONTRACT). When one library fails:

- Members who may use it see an amber notice on Home, "Movies and TV are unavailable right now.", and
  that library's place in the places bar is struck through and links to Help. Library and Search show the
  same warning for that library only.
- Every other library, Help, Account and the native apps keep working. Nobody else's data is shown.
- Members whose page was loaded in the last 30 seconds (Continue) or 2 minutes (Recently added) keep
  seeing their cached list until it expires (contract.cache_ttl). The outage appears for them after that.
- When the library answers again, Home recovers by itself: after a cool-off of about a minute the next
  request tries it, and on success the notice goes. No restart. (Rehearsed in CI on every Home change:
  `beta/rehearse_degraded.py`, AVR-388 part A.)

Members who are not entitled to that library see nothing at all.

## 1. Look (read-only)

1. **Which library, in Home's view.** On the host, from inside the Home container (the detail view answers
   only a loopback peer with no identity header; members get 404):

   ```
   docker exec <home container> python3 -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8096/readyz').read().decode())"
   ```

   `libraries` is `degraded` when any adapter is `failing` or `cooling_off`. Per adapter: `state`,
   `consecutive_failures`, `last_error_class`, `retry_in_seconds`. No member data is in it. `unknown` means
   no member has loaded a page since Home started.
2. **The library itself.** `scripts/services-health.sh` (the existing host check). If it says the library
   is down, the problem is the library, not Home.
3. **Home's log.** `docker logs --since 15m <home container>`: one JSON line per request with `route`
   (a template, never a raw path), `status`, `duration_ms`, `service`, `section`, `state`, `reason`,
   `error_class`. It never holds a username, title, id, address or key, so it can be shared for diagnosis.

## 2. Read the error class

| `last_error_class` / log `error_class` | Usually means | Next |
|---|---|---|
| `UpstreamTimeout` | the library is slow (load, transcoding, a scan) | wait one cool-off; if it persists, look at the library's own load |
| `UpstreamUnreachable` | the library's container is stopped, restarting, or its network changed | step 3, start the library |
| `UpstreamHTTPError` (5xx) | the library is up but failing internally | the library's own logs and runbook |
| `UpstreamAuthError` (401/403) | Home's service key or token was revoked or rotated | owner: replace the key in Home's secret file (`docs/SECRETS.md`), then restart Home (approval) |
| `UpstreamMalformed`, `UpstreamMisbehaved`, `UpstreamTooLarge` | the library answered something Home will not trust (an upgrade changed the API, or a wrong-user answer) | do not "fix" Home live; check the library's version against the pins in CONTINUE-AND-HANDOFF.md and open an issue |
| `cooling_off` with no new failures | the breaker is waiting out its cool-off (about 60 s) | nothing; it retries by itself |

A member who reports "not set up" (`not_linked`) is not an outage: their account name does not match. Run
`services/avrana-home/tools/check_member_links.py <username>` (owner-run read) and follow its FIX line.

## 3. Fix the library, not Home

Restart or repair the library by its own runbook (`docs/OPERATIONS.md`). Home needs nothing:
reload Home a minute later and the notice is gone. Do not restart Home to clear a library outage; it only
drops every member's cache and costs one slow page each.

## 4. Escalate

- **Home itself fails** (the page answers 5xx for more than a minute, or `/healthz` stops answering):
  that is not a library outage. Roll back by the cut-over switch (HOME-APP.md section 9,
  `docs/runbooks/home-rollback-rehearsal.md` part D): the per-service hostnames and native apps keep
  working throughout.
- **A member sees another member's item, or a library they are not in:** stop. Roll back at once and keep
  the logs; it is a security incident, not an outage.
- **The same library fails repeatedly with `UpstreamMalformed`:** an upstream upgrade. Pin back or hold the
  upgrade; record it against AVR-504's version table.

## 5. After

Note the time, the library, the error class and how long it lasted in the dated findings file, and tell
members only if it lasted long enough for them to notice (the notice on Home already told those affected).
