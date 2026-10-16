"""Run by test_slowdrip.py in a SUBPROCESS (the test process has the network guard installed; this one does
not). Talks only to a throw-away server on 127.0.0.1 inside this process. Prints one JSON line."""
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from avrana_home.adapters.jellyfin import JellyfinAdapter  # noqa: E402
from avrana_home.aggregate import gather  # noqa: E402
from avrana_home.principal import principal_from_headers  # noqa: E402
from avrana_home.resilience import UpstreamError, UrllibTransport  # noqa: E402

DEADLINE = 0.6
HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100000\r\n\r\n"


def serve(mode, stop):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    srv.settimeout(0.2)

    def handle(conn):
        try:
            conn.settimeout(5)
            conn.recv(65536)
            if mode == "silent":
                stop.wait(10)
                return
            data = HEAD if mode == "body" else b"HTTP/1.1 200 OK\r\nX-Slow: " + b"a" * 1000
            sent = 0
            if mode == "body":
                conn.sendall(HEAD)
            while not stop.is_set():
                conn.sendall(b"x" if mode == "body" else b"a")
                time.sleep(0.2)
        except OSError:
            pass
        finally:
            conn.close()

    def loop():
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            threading.Thread(target=handle, args=(conn,), daemon=True).start()
        srv.close()
    threading.Thread(target=loop, daemon=True).start()
    return srv.getsockname()[1]


def main():
    out = {}
    principal = principal_from_headers({"X-authentik-username": "member-a",
                                        "X-authentik-groups": "avrana-videos"})
    for mode in ("body", "header", "silent"):
        stop = threading.Event()
        port = serve(mode, stop)
        t = UrllibTransport(f"http://127.0.0.1:{port}", {})
        start = time.monotonic()
        try:
            t.request("GET", "/x", None, DEADLINE, 1 << 20)
            err = None
        except UpstreamError as exc:
            err = type(exc).__name__
        direct = (err, time.monotonic() - start)

        adapter = JellyfinAdapter(UrllibTransport(f"http://127.0.0.1:{port}", {}), timeout=DEADLINE,
                                  request_timeout=DEADLINE)
        start = time.monotonic()
        home = gather(principal, [adapter], sections=("recent",))
        res = home.sections[0]
        via = (res.state.value, res.reason, time.monotonic() - start)
        out[mode] = {"direct": direct, "gather": via, "in_flight": adapter.in_flight,
                     "by_member": dict(adapter._by_member), "breaker": adapter.health().state}
        stop.set()
    print(json.dumps(out))


main()
