# Member home preview

Status: **design preview (2026-10-11, AVR-426; recomposed the same day in AVR-452 after the
owner's review). Fixture data only. Not a service, not deployed, and not the Media 2.0
application.**

A browsable proposal for the member home in [Media 2.0](../../../docs/design/MEDIA-2.0.md), in
the house style of [DESIGN.md](../../../docs/design/DESIGN.md). The places a member came for are
first: Watch, Listen, Read, Request and Help in one bar under the wordmark. Under it are one
Continue row and one bounded "New this week" row; everything new, by library, is on `/new`. It is server-rendered with FastAPI and Jinja, as the
home is planned to be, and sends no JavaScript (its Content-Security-Policy allows no script).

What is real: the HTML, the stylesheet, the layouts at phone and desktop width, the five states.
What is invented: the member, every title (all public-domain works), the progress figures and the
covers, which `fixtures.py` draws as plain SVG. It has no adapter, key, identity header or network
call, and every link ends at a note that says what the product would do.

## Open it

From the repository root, with Python 3.12:

```sh
python -m venv .venv
.venv/bin/pip install fastapi==0.115.6 uvicorn==0.34.0 jinja2==3.1.5 httpx==0.28.1   # Windows: .venv\Scripts\pip
.venv/bin/python -m uvicorn tests.ui.home_preview.app:app --host 127.0.0.1 --port 8200
```

Then open <http://127.0.0.1:8200/>. The bar at the top (not part of the design) switches state:

| Link | Shows |
|---|---|
| Healthy | the bar, four things to continue, four new things |
| Loading | one service slower than the two-second budget: a sentence and "Try again"; what did answer is shown |
| Empty | nothing in progress; one library with nothing new (its tab says so) |
| One service down | "Movies and TV are unavailable right now", said once; Watch is struck through; everything else works |
| Libraries unavailable | the operator notice; Request, Help and Account |
| Artwork: colour / grey | the open question of how library artwork sits on the black page |
| Today's home | `/before`: the portal home as it is in Git, rendered by `portal.py` itself |

## Check it

```sh
python tests/run_offline.py                       # includes tests/test_home_preview.py (skipped without FastAPI)
PLAYWRIGHT_FROM=<a folder with @playwright/test> node tests/ui/home_preview/check.mjs http://127.0.0.1:8200 tests/ui/home_preview/screens
```

The second command is optional and needs Node and Playwright, which this repository does not
install. It writes screenshots to `tests/ui/home_preview/screens/` (ignored by Git: this repository tracks
no binary files) and checks, in Chromium with
JavaScript switched off: no sideways page scroll, one `h1` and no skipped heading level, 44px
targets, 4.5:1 text, an `alt` on every image, a visible focus ring at every Tab stop, rails that
scroll inside themselves on a phone and not on a wide screen, and no sideways scroll at 200% text.
At 360 by 640 it also checks that the five places end within the first 260px of the design, that
no row holds more than four things and that the home page is no taller than two screens.
