# Avrana home

Status: **not built into an image, not deployed, synthetic data only.** No production Dockerfile, no
production compose file, no hostname; nothing here is wired into `services/avrana-portal`, which stays
deployed and untouched. The one exception is the LAN-only OWNER PREVIEW (owner decision 2026-10-15:
`Dockerfile.preview`, `docker-compose.preview.yml`, `preview/`), which the owner runs by hand on `avrana`
for his own libraries behind one password; see
[`docs/runbooks/home-owner-preview.md`](../../docs/runbooks/home-owner-preview.md). It is not a member path. Gates G1 (network isolation) and G2 (authorization suites) have not passed in
production, so nothing in this directory may read real member data. Real upstream adapters are
disabled unless five explicit settings are present (see `docs/design/HOME-APP.md`, section 7).

Part of [Avrana Media 2.0](../../docs/design/MEDIA-2.0.md). Read these first:

- [`docs/design/HOME-APP.md`](../../docs/design/HOME-APP.md): the application, its identity rules,
  every difference from the current portal, configuration, degradation, cut-over and rollback, and
  the section for the design team.
- [`docs/design/ADAPTER-CONTRACT.md`](../../docs/design/ADAPTER-CONTRACT.md): the adapter layer.
- `avrana_home/principal.py`: member identity from trusted edge headers only, fail closed.
- `avrana_home/contract.py`: adapter base class, result types, states, hand-off URL builder.
- `avrana_home/resilience.py`: timeouts, circuit cool-off, transport interface, safe logging.
- `avrana_home/cache.py`: disposable in-memory TTL cache, member-partitioned by API shape.
- `avrana_home/aggregate.py`: independent sections, health summary.
- `avrana_home/adapters/`: one module per upstream (Jellyfin, Audiobookshelf, Komga, Calibre-Web).

## Layout

| Path | What |
|---|---|
| `avrana_home/principal.py`, `contract.py`, `resilience.py`, `cache.py`, `aggregate.py`, `adapters/` | The adapter layer (standard library only; import-only) |
| `avrana_home/app/` | The web application: `create_app(settings)` (FastAPI + Jinja, server-rendered, no JavaScript) |
| `avrana_home/app/templates/` | Jinja templates and the one stylesheet |
| `dev/` | `mock_jellyfin.py`, `dev_identity.py`, `run_dev.py`: development only, never part of an image |
| `tests/` | The 137 adapter tests (no sockets allowed) and `run_web_tests.py` |
| `webtests/` | Web application tests, Tier A and Tier B (loopback sockets only) |
| `requirements.txt` | Direct pins for the web application (plain `uvicorn`, no `[standard]`) |
| `requirements.lock` | Every pin with sha256 hashes for Linux x86_64 / CPython 3.12 (UNTESTED on Linux) |
| `dev/README-DEMO.md` | Commands, synthetic identities and states for the UI/UX team |

## Run it locally (development only)

```
python -m venv .venv-media && .venv-media/Scripts/pip install -r services/avrana-home/requirements.txt
.venv-media/Scripts/python services/avrana-home/dev/run_dev.py --dev-identity
```

One command starts the mock Jellyfin (`127.0.0.1:18096`, synthetic fixtures) and the app
(`127.0.0.1:8096`) with `HOME_SECTIONS=on` through the real transport. Open
`http://127.0.0.1:8096/_dev/identity` and pick a synthetic member; every page shows a
"DEVELOPMENT IDENTITY" banner. Switch the mock's failure mode with
`curl -X POST http://127.0.0.1:18096/__mock/mode/down` (`ok`, `slow`, `down`, `500`, `malformed`,
`wrong-user`). `run_dev.py` refuses to start without `--dev-identity`, on a non-loopback bind, or
with any non-mock upstream.

## Run the tests

From the repository root.

```
# Tier A: system Python, standard library only. Runs the whole repository's offline suite. The web
# suite's FastAPI modules are SKIPPED with the line
#   SKIP avrana-home web suite: fastapi not installed (run with the pinned requirements)
python -B tests/run_offline.py

# Tier A + B: the interpreter that has the pinned requirements. Runs the adapter tests and the
# web suite and prints `adapter tests: ran=N ...` and `web tests: ran=N skipped=0 failed=0`.
# With AVRANA_REQUIRE_DEPS=1 (the CI command) a missing dependency (exit 2) or any skipped test
# (exit 3; one POSIX-only adapter test may skip on Windows) is a failure.
python -m pip install --require-hashes --only-binary=:all: -r services/avrana-home/requirements.lock
AVRANA_REQUIRE_DEPS=1 python -B services/avrana-home/tests/run_web_tests.py

# Just the web tests, either interpreter (Tier B modules skip without the framework):
python -B -m unittest discover -s services/avrana-home/webtests -t services/avrana-home -p "test_*.py"
```

The web tests open loopback sockets only (the mock upstream, and a real uvicorn server on an
ephemeral port for the header and wire tests); any other destination, any non-loopback bind and
any name resolution fails the run, so they work in a namespace with only loopback and no DNS
(guards tested; a real empty network namespace was not available on the Windows build machine). Run suites
one at a time. If you see loopback connection errors check `netstat -an | grep -c TIME_WAIT`: a
very high count means another process is running socket-heavy suites; wait and rerun.

## Configuration (summary)

Environment variables, read once at start; an invalid or incomplete value stops the process.
`HOME_SECTIONS` (default `off`), `HOME_UPSTREAM_MODE` (`mock` default, loopback only), the real-mode
group `HOME_GATES_VERIFIED=yes` + `JELLYFIN_BASE_URL` + `JELLYFIN_API_KEY_FILE`, `HOME_TIMEOUT`,
`HOME_SECTION_LIMIT`, `HOME_HEALTH_DETAIL` (`loopback` or `off`), `HOME_HOST`/`HOME_PORT`,
`LOG_LEVEL`. Full table with failure behaviour: HOME-APP.md section 7. Secrets only via the
environment or a file the environment names, as `docs/SECRETS.md` describes; never logged.

## Serving it (not done; for when an image exists)

`python -m avrana_home.app.serve` (it sets `--http h11`, no access log, no proxy-header rewriting).
If you run uvicorn directly use `--http h11 --no-access-log` and **never** `--proxy-headers`
or `--forwarded-allow-ips='*'` (the loopback-only `/readyz` trusts the real TCP peer). A future
Dockerfile should follow the Audible connector's (digest-pinned `python:3.12-slim`, non-root,
`pip install --require-hashes -r requirements.lock`, read-only filesystem, Authentik private network only, no
published port).

## Recovery and rollback

Stateless apart from a disposable in-memory SQLite cache (`:memory:`, no file setting; closed on shutdown; `MemberCache.purge_member` is the offboarding hook and is deliberately wired to nothing yet). Recover by rebuilding from Git and restoring
the environment file from 1Password. Cut-over and rollback are a proxy-provider upstream switch
between the new app and the still-deployed portal (MEDIA-2.0 section 5); see HOME-APP.md section 9.
