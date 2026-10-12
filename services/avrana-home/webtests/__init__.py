"""Test package for the Avrana home WEB application (Tier A and Tier B).

Unlike the adapter tests (`tests/`, which forbid every socket), these tests may talk to
127.0.0.1 only: the mock upstream and a real uvicorn server on ephemeral loopback ports. Any
other destination, and any name lookup that is not loopback, fails the run loudly.

Tier A (standard library only) tests run anywhere. Tier B (FastAPI) test modules are skipped
with an explicit reason when the framework is absent, and this package prints one unmistakable
line so a skip cannot be mistaken for a pass.
"""
import importlib.util
import socket

FRAMEWORK_MISSING = any(importlib.util.find_spec(m) is None
                        for m in ("fastapi", "starlette", "uvicorn", "jinja2", "httpx"))
SKIP_REASON = "avrana-home web suite: fastapi not installed (run with the pinned requirements)"
if FRAMEWORK_MISSING:
    print("SKIP " + SKIP_REASON, flush=True)

_LOOPBACK = ("127.0.0.1", "::1", "localhost")
_real_connect, _real_connect_ex = socket.socket.connect, socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo
_real_bind = socket.socket.bind


def _check(address):
    host = address[0] if isinstance(address, tuple) and address else None
    if host not in _LOOPBACK:
        raise RuntimeError("avrana-home web tests may only connect to loopback")


def _connect(self, address):
    _check(address)
    return _real_connect(self, address)


def _connect_ex(self, address):
    _check(address)
    return _real_connect_ex(self, address)


def _getaddrinfo(host, *args, **kwargs):
    if host not in _LOOPBACK and host is not None:
        raise RuntimeError("avrana-home web tests may only resolve loopback names")
    return _real_getaddrinfo(host, *args, **kwargs)


def _bind(self, address):
    _check(address)                  # nothing may listen on a non-loopback interface
    return _real_bind(self, address)


def _no_name_lookup(*args, **kwargs):
    raise RuntimeError("avrana-home web tests do not resolve host names (no DNS)")


socket.socket.bind = _bind
socket.gethostbyname = socket.gethostbyname_ex = socket.gethostbyaddr = socket.getfqdn = _no_name_lookup
socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = _getaddrinfo
