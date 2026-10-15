# Recording Jellyfin responses for the API-contract gate (AVR-376)

**Proposed procedure, not yet approved or run.** No recording exists today: the contract in
`services/avrana-home/contracts/jellyfin.json` is written from Jellyfin's public API shapes and is checked only
against synthetic fixtures (local evidence). A recording proves that a real server of the pinned version sends
the same response shape. It never needs real values, and none are kept.

Only the owner captures. An agent prepares commands, runs the offline sanitiser and reviews the output; it
never holds a Jellyfin token, contacts the server or sees a raw response.

## Choose a source (owner decision)

| Option | Member data touched | Production touched | Recommended |
|---|---|---|---|
| **A. Throwaway local Jellyfin** at the pinned digest (`services/media/docker-compose.yml`, 10.11.11), on a workstation, with a few public-domain files and one test user | None | None | **Yes** |
| B. Production, signed in as a dedicated non-member probe user that can see one small library | None if the library holds no member-specific state | Creating the user and its token is a production change: separate approval | Only if A cannot reproduce a shape |
| C. Production, as a real member | Yes | Yes | **No** |

With A, play part of one item as the test user first, so `/UserItems/Resume` returns something.

## Capture (owner, option A)

1. Start the throwaway server at the pinned digest, bound to `127.0.0.1` only, with its own empty config
   directory. Create one admin and one test user and add a public-domain library.
2. Put the test user's token in an environment variable in your own shell. Never put it in a file in the
   repository, a command line that is logged, or a message to an agent.
3. Capture the four routes the adapter uses, into a directory **outside** the repository, for example
   `~/jf-capture/`:

   ```sh
   H="Authorization: MediaBrowser Token=\"$JF_TOKEN\""   # header only; token stays in the shell
   B=http://127.0.0.1:8096
   curl -sf -H "$H" "$B/Users"                                           > ~/jf-capture/users.raw.json
   curl -sf -H "$H" "$B/UserItems/Resume?userId=$JF_USER&limit=3&enableUserData=true&enableImageTypes=Primary" > ~/jf-capture/resume.raw.json
   curl -sf -H "$H" "$B/Items/Latest?userId=$JF_USER&limit=3&enableUserData=true&enableImageTypes=Primary"    > ~/jf-capture/latest.raw.json
   curl -sf -H "$H" "$B/Items?userId=$JF_USER&ids=$JF_ITEM&enableUserData=true&enableImageTypes=Primary"      > ~/jf-capture/items.raw.json
   ```

   Use the same query keys the adapter sends (`avrana_home/adapters/jellyfin.py`, `ALLOWED_ROUTES`).

## Sanitise (offline, anyone)

From `services/avrana-home`, one recording per route:

```sh
python -m avrana_home.recording_sanitiser --route resume --server-version 10.11.11 \
    ~/jf-capture/resume.raw.json tests/fixtures/jellyfin/recorded/resume-10.11.11.json
```

The sanitiser keeps only declared fields and replaces every value with a synthetic value of the type the
server actually sent. It lists the names (never the values) of undeclared fields, cuts lists to three
entries, and refuses to write anything if any raw string of four or more characters would survive. It never
overwrites an existing recording.

## Review and commit

1. Read each recording in full. Every value must start with `synthetic-` or be a small number or boolean.
2. Read `_undeclared_fields`. A field the adapter should use is a contract change, made in its own pull request.
3. Run `python scripts/review_git_content.py --staged` and `python -B tests/run_offline.py`. The contract gate
   picks recordings up automatically, and a type mismatch fails it.
4. Delete `~/jf-capture/` and the throwaway server, and revoke the test user's token (option B: delete the
   probe user, a production change covered by its approval).

Evidence label: a committed recording is **local** evidence that the pinned version's shape matches. It says
nothing about production configuration and is not evidence that any member's data is handled correctly.

## Rollback

A recording is one JSON file. Deleting it returns the gate to synthetic fixtures only.
