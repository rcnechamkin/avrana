"""Server entry point: `python -m avrana_home.app.serve`.

Reads the environment (settings.py), configures structured logging, and runs uvicorn with the
flags this application depends on:

  * http="h11": one HTTP implementation, so header handling is the one the tests exercise.
  * access_log=False and no uvicorn access logger: the raw request target (with its query string)
    is never logged.
  * proxy_headers=False: the peer address is the real TCP peer. The loopback-only /readyz view
    relies on it; a --forwarded-allow-ips="*" setting would let a client claim to be 127.0.0.1.
  * Bind address from HOME_HOST (default 127.0.0.1). NOT DEPLOYED: no container binds it yet.
"""
import uvicorn

from .logsafe import configure_logging
from .main import create_app
from .settings import Settings


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, http="h11",
                access_log=False, proxy_headers=False, server_header=False, log_config=None)


if __name__ == "__main__":
    main()
