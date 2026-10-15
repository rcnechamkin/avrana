"""ASGI entry point for a server: `uvicorn avrana_home.app.asgi:app`.

Importing this module reads the environment and builds the app, so only a server should import it
(tests and tools use `create_app` directly). Invalid configuration raises `SettingsError` and the
process does not start. Preferred entry point: `python -m avrana_home.app.serve`, which also sets
the flags the application depends on (h11, no access log, no proxy-header rewriting). If you run
uvicorn yourself, pass `--http h11 --no-access-log` and do NOT pass `--proxy-headers`.
"""
from .logsafe import configure_logging
from .main import create_app
from .settings import Settings

_settings = Settings.from_env()
configure_logging(_settings.log_level)
app = create_app(_settings)
