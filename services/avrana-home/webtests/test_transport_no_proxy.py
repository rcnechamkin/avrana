"""Security review 2026-10-27 (MEDIUM): the transport never uses a proxy from the environment.

urllib's default opener reads HTTP_PROXY/HTTPS_PROXY (and the Windows registry). With a plain-http base URL the
upstream's bearer token, the Audiobookshelf one admin-capable, would then be sent to that proxy. The opener is
built with ProxyHandler({}), so the request goes straight to the upstream whatever the environment says.
Loopback only (webtests, Tier A sockets): one listener plays the upstream, another the would-be proxy."""
import os as _os
import socketserver
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from avrana_home.resilience import UrllibTransport


class _Server(ThreadingHTTPServer):
    def server_bind(self):                      # HTTPServer's bind looks up the FQDN; these tests resolve no names
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def _listener(seen):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization")))
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = _Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class NoEnvironmentProxy(unittest.TestCase):
    def setUp(self):
        self.upstream_seen, self.proxy_seen = [], []
        self.upstream = _listener(self.upstream_seen)
        self.proxy = _listener(self.proxy_seen)
        self.addCleanup(self.upstream.shutdown)
        self.addCleanup(self.proxy.shutdown)

    def test_a_proxy_in_the_environment_never_sees_the_request_or_the_token(self):
        proxy = f"http://127.0.0.1:{self.proxy.server_address[1]}"
        env = {"HTTP_PROXY": proxy, "http_proxy": proxy, "HTTPS_PROXY": proxy, "https_proxy": proxy,
               "ALL_PROXY": proxy, "NO_PROXY": "", "no_proxy": ""}
        with mock.patch.dict(_os.environ, env):
            transport = UrllibTransport(f"http://127.0.0.1:{self.upstream.server_address[1]}",
                                        {"Authorization": "Bearer SYNTHETIC-not-a-real-token"})
            transport.request("GET", "/api/me", None, 2.0, 4096)
        self.assertEqual([], self.proxy_seen)
        self.assertEqual([("/api/me", "Bearer SYNTHETIC-not-a-real-token")], self.upstream_seen)


if __name__ == "__main__":
    unittest.main()
