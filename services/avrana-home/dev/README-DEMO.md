# Demo for the UI/UX team

**Synthetic data only. Not deployed. Never deploy anything in this directory.**

> **The development identity shim must never be deployed.** `run_dev.py` refuses to start unless it
> is given the explicit `--dev-identity` flag **and** is bound to a loopback address (`127.0.0.1`
> or `::1`) **and** the upstream is the local mock with the fixed fake key. It lives outside the
> application package, the default app does not know it exists, and every page it serves carries a
> yellow "DEVELOPMENT IDENTITY" banner. There is no Authentik here: the shim stands in for the
> outpost with invented members.

**Page composition and visual design belong to the UI/UX team.** The home-page sections in this app
are an unstyled, semantic placeholder (`avrana_home/app/templates/_sections.html`: `section`, `h2`,
`ul`, `a`, `span`, `p role="status"`, no classes, no images). The app deliberately does **not**
implement a shelf or rail layout, and nothing about the existing pages' look has changed: they
reproduce today's portal. Watch, Request, Help and Account stay in the unchanged navigation block
and footer, which a test asserts is present once, after the sections, for every state (no section
state can remove or reorder it). Replace the placeholder freely; keep the state rules in
`docs/design/HOME-APP.md` section 5.

## Start it

From the repository root, with the interpreter that has the pinned requirements
(`services/avrana-home/requirements.lock` for the exact versions):

```
.venv-media/Scripts/python services/avrana-home/dev/run_dev.py --dev-identity
```

This starts the mock Jellyfin on `127.0.0.1:18096` and the app on `http://127.0.0.1:8096/`,
talking through the real HTTP transport, with `HOME_SECTIONS=on`. Open
`http://127.0.0.1:8096/_dev/identity` and pick a member (a cookie remembers the choice), or send
`X-Dev-Identity: member-a` from a script.

Options: `--port`, `--mock-port`, `--mode <ok|slow|down|500|malformed|wrong-user>`,
`--slow-seconds N` (for `slow`), `--sections <on|off>`.

## Who sees what

| Identity | Libraries | What the home page shows |
|---|---|---|
| `member-a` | Movies and TV only (single library) | Continue watching (3 items, one untitled) and Recently added (3), then the navigation: Watch, Request, Help |
| `member-b` | Movies and TV, books, comics (multi-permission) | Their own different items, plus Read in the navigation; shares one recent title with member-a |
| `member-nolib` | Comics only (no video permission) | **No section at all**: the page is byte-identical to `--sections off`; no mention of Movies and TV |
| `member-c` | Movies and TV group, Jellyfin account disabled (unlinked) | "Movies and TV are not set up for your account yet." in each section |
| `member-d` | Movies and TV group, no Jellyfin account (unlinked) | Same sentence |
| `synthetic-admin` | None; Operations only | Help and the Operations tile; no sections |
| (none selected) | No identity | Help tile only, like a request with no groups today |

## Upstream states

A member's page is cached for 30 seconds (recently added: 120 s), so reload as a member whose cache
is cold, or restart the stack with the failure mode:

- **Upstream down:** `run_dev.py --dev-identity --mode down`, or switch a running mock with
  `curl -X POST http://127.0.0.1:18096/__mock/mode/down`. Each section shows
  "Movies and TV are unavailable right now." (`role="status"`); the navigation is untouched.
- **Slow upstream:** `--mode slow --slow-seconds 5` (longer than the 2 s adapter timeout): the same
  unavailable sentence appears after about the timeout, never a hung page.
- Others: `500`, `malformed`, `wrong-user` (the mock answers with another member's items; the app
  discards them and shows the unavailable sentence), then `ok` to recover. After three consecutive
  failures the adapter cools off for 60 s, so recovery can take up to a minute.

`GET http://127.0.0.1:8096/readyz` (from this machine, with no identity selected) shows the adapter
state: `ok`, `failing`, `cooling_off` or `unknown`.

## Sections on and off

`--sections on` (default) is `HOME_SECTIONS=on`; `--sections off` is the flag-off app, whose pages
are identical to today's portal. In a normal run the setting is the environment variable
`HOME_SECTIONS` (default off).

## The JSON contract

`GET /home.json` (needs a selected identity and `--sections on`) returns the exact data the page is
built from, so templates can bind to it. Schema and one example per state:
[`docs/design/HOME-APP.md`](../../../docs/design/HOME-APP.md) section 5. Progress is given as
fractions and seconds; the page's wording ("1 hour 10 minutes left") comes from
`avrana_home/app/viewmodel.py`. There is no artwork route yet, so `artwork.ref` cannot be fetched.
