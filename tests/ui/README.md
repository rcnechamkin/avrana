# UI test harness

Status: **test infrastructure, 2026-10-12 (AVR-360, with a slice of AVR-362)**. Fixture data only.
It never touches a live service, a database, Docker, SSH or the network, and it is never run
against production.

It answers one question for every member-facing page Avrana owns: *does this page still meet the
house style's accessibility, copy and no-leak rules, for every kind of viewer?* It works on `main`
today, where the pages still have the defects listed in the
[web interface audit](../../docs/audits/2026-10-11-web-interface-audit.md), and on the combined tree
later, because it holds each page to a **ratchet**: known defects are listed, new ones fail.

## What runs where

| Layer | What | Needs | Runs |
|---|---|---|---|
| 1. Static | Every registry page is rendered offline from the service's own code and checked: headings, landmarks, names and labels, `target=_blank`, `lang`/viewport/`color-scheme`, `outline:none` without a ring, WCAG contrast computed from the page's own CSS tokens, declared target size, `meta refresh`, script and inline handlers, em/en dashes and first-person words, and **leaks** (a page must not name a service the viewer cannot use) | Python 3.12 standard library | `python -B tests/run_offline.py` (and so CI, if D-8 is approved) via `tests/test_ui_harness.py` |
| 2. Browser | The same pages served from `127.0.0.1`, opened in Chromium at 390x844 and 1280x800 with JavaScript off: axe-core, real Tab order and focus indicator, rendered target sizes and contrast, sideways scroll, and 200% text | Node, Playwright, axe-core (**not in the repository**) | `python -B tests/ui/harness/run_ui.py`, by hand, in a development environment only |
| Token drift | The portal, Kindle and Audible stylesheets must agree on the shared tokens (AVR-362 slice) | Python standard library | `tests/test_token_drift.py` inside `run_offline.py` |

Layer 2 is not part of `run_offline.py` and not a requirement of it: a machine without Node still
gets layer 1 on every run.

## The one command

```sh
python -B tests/ui/harness/run_ui.py            # static + browser, end to end
python -B tests/ui/harness/run_ui.py --no-browser
python -B tests/ui/harness/run_ui.py --only portal/home --strict
```

It renders the registry, runs the static checks, starts `serve.py` on an ephemeral loopback port,
runs `check.mjs`, stops the server, and applies the baseline to both layers. Exit 1: a finding that
is not in the baseline. Exit 2: the browser tooling is missing (it says so; nothing is claimed).
Exit 3: a page failed to load. Screenshots and `report.json` land in `tests/ui/harness/out/`, which
is git-ignored (this repository tracks no binary files).

### Browser tooling (kept outside the repository)

Playwright and axe-core are **not vendored**. `run_ui.py` looks at `$PLAYWRIGHT_FROM`, then at
`.ui-tooling/` next to the repository root (that is, `../.ui-tooling` from a worktree
checkout), for a folder with `node_modules/@playwright/test` and `node_modules/axe-core`. This is
the same variable the home preview's `check.mjs` uses. To create it:

```sh
mkdir .ui-tooling && cd .ui-tooling
printf '{"name":"avrana-ui-tooling","version":"1.0.0","private":true}' > package.json
npm install --save-exact @playwright/test@1.63.0 axe-core@4.14.0
npx playwright install chromium
```

Versions used for the recorded run: `@playwright/test` 1.63.0, `axe-core` 4.14.0, Chromium 153
(Playwright's build), Node 22.22, Python 3.12. axe-core cannot run in a page with scripting disabled
(Chromium crashes), so `check.mjs` runs axe in a second, script-enabled context on the same URL; the
pages carry no script, so the render is identical.

## Layer 1 internals

```
tests/ui/harness/
  pages.py          the declarative page registry (Page, Identity, Rendered, Unavailable)
  adapters.py       portal + Kindle: drive the real Handler in memory with fixture headers
  static_checks.py  the rules; ids are service/page/identity/rule/detail
  css.py dom.py     the small CSS and HTML readers behind the rules (stdlib)
  ratchet.py        baseline.json handling; update_baseline.py is its command line
  serve.py check.mjs run_ui.py     layer 2
  token_drift.py    AVR-362 slice
  baseline.json     known findings, each with the issue that fixes it
  extra/            drop-in registry hooks
```

The adapters detect what a module offers instead of assuming a version. The portal on `main` and on
the authorization branch, and the Kindle connector before and after the 404 change, both render
(Kindle's library back-ends are stood in for by in-memory fakes, so no SQLite file or
Audiobookshelf is needed). A page that cannot be produced on a tree is reported as **unavailable**
and is never a failure.

### Registry coverage

Portal: `home` for no groups, each single group (videos, audiobooks, comics, books, contributors),
admin, and a multi-permission member; each chooser (denied for no groups); help index; every help
topic the module declares (and one denied topic); account; the Watch interstitial; 404.
Kindle: form empty, form with values, no library account, saved, bad address, and the page a
non-member gets.

### Adding pages

Add a module to `tests/ui/harness/extra/` (or list its path in `UI_HARNESS_EXTRA`) that defines
`register(registry)`; copy `extra/_example.py`.

- **Audible connector templates**: render the Jinja templates inside the callable, convert a missing
  `jinja2` into `Unavailable`, and pass the linked `style.css` text as `Rendered.css`.
- **`services/avrana-home`**: render each route with a fixture principal inside the callable
  (for example with `TestClient`), guarded the same way. Set `forbid=` to the tokens the identity
  must never see, and `needs_js=True` only if the page genuinely needs script.

A hook that raises while loading is reported as a failure of `test_registry_builds_and_covers_both_services`.

## The baseline rule

`tests/ui/harness/baseline.json` lists today's known findings (section `static`, and section
`browser` for layer 2), each with the Linear issue that will fix it:

| Issue | Covers |
|---|---|
| AVR-357 | portal accessibility |
| AVR-358 | Kindle accessibility |
| AVR-359 | Audible accessibility |
| AVR-353 | Kindle answers a non-member with a 403 page that names Kindle, Amazon and the libraries |
| AVR-430 | the portal Read tile subtitle that names the other library |

**The baseline may only shrink.**

- A finding that is not in the baseline fails the run (a regression). Fix the page.
- A baseline entry that no longer occurs is printed as stale. When a fix merges, delete its entries:
  `python -B tests/ui/harness/update_baseline.py --write`. With `UI_HARNESS_STRICT_BASELINE=1` (or
  `--strict`) a stale entry fails, which is how the file is brought to empty.
- `--write` never adds an entry. `--write --add-new` exists to create the file and to record debt a
  reviewer has approved; it prints a warning, and review should reject any pull request that grows
  the file: `python -B tests/ui/harness/update_baseline.py --vs origin/main`.
- Finding ids name what and where, never a magnitude, so partly fixing a defect does not create a new id.

`test_negative_*` in `tests/test_ui_harness.py` proves the ratchet bites: it injects a page with
deliberate defects through the registry and requires the run to fail.

## How the other branches plug in

| Branch | What to do when it merges |
|---|---|
| `avr-357-430-portal-a11y`, `avr-358-kindle-a11y` | Run `python -B tests/ui/harness/update_baseline.py --check`; it lists the stale entries. Remove them with `--write` in the same pull request. Aim for an empty section for the service. |
| `avr-352-portal-authz-suite`, `avr-353-kindle-identity-isolation` | Nothing to edit: the adapters detect the new handlers. Kindle's `not-found` page then answers 404 and drops its `leak` and `status` entries from the baseline. |
| `avr-359-audible-a11y` | Add `extra/audible.py` (see the example), then add its findings only if a reviewer agrees; the target is an empty entry list. |
| `avr-374-home-app` | Add `extra/home.py` rendering each page with a fixture principal. |

## Not covered

Real phones and TVs; screen readers (NVDA, VoiceOver, TalkBack); Safari and Firefox (Chromium
only); anything behind Authentik (its flows, brand CSS and library page); the upstream
applications; real fonts (the machine's serif stands in for Times New Roman); text spacing and
reduced-motion settings; text zoom as a browser does it (layer 2 doubles the root font size, which
scales `rem` and `em` text but not text sized in `px`); and what the host actually serves
(headers added by the outpost, the Cloudflare tunnel). Contrast is computed against solid grounds;
text over an image or gradient is skipped. A clean run is evidence about these fixtures, not a
sign-off for deployment.

## Token drift (AVR-362, narrow slice)

`tests/test_token_drift.py` reads the inline `STYLE` strings of the portal and the Kindle connector
(with `ast`, without importing them) and the Audible `style.css`, extracts the shared tokens
(colours, font stack, column width, wordmark size and tracking, button and field padding, focus
ring, and the literal colours each stylesheet repeats), and compares them. The reference is
`docs/design/foundation/tokens.json` (theme `media`) **if that file exists**, which it will once the
design team's PR #3 is merged; otherwise the services are compared with each other. Known
differences are in `tests/ui/harness/token_drift_allowlist.json` with a reason and issue each; a new
divergence fails.

What remains for AVR-362 after PR #3 is approved: decide the single source of truth (a shared
`avrana.css` or generated tokens) and build it; add the sync script and have the portal, Kindle and
Audible read it; converge the wordmark to the two sizes and tracking in `DESIGN.md`; extend the font
stack; define the Control Rule colour (`outline_control`, which no service defines yet); then empty
the allow-list. This slice only guarantees that, until then, the copies cannot drift further
unnoticed.
