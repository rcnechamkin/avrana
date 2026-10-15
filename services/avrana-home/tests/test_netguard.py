"""The test network guard: every way to open a socket or resolve a name fails the run."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests import _netguard  # noqa: E402,F401  (installs the guard; also when this file is run directly)

import socket  # noqa: E402
import unittest  # noqa: E402

import _socket  # noqa: E402


class NetGuardTests(unittest.TestCase):
    def blocked(self, fn, *args):
        with self.assertRaises(RuntimeError) as cm:
            fn(*args)
        self.assertIn("network access is forbidden", str(cm.exception))

    def test_connections_and_name_lookups_are_blocked(self):
        self.blocked(socket.create_connection, ("127.0.0.1", 9))
        self.blocked(socket.getaddrinfo, "example.invalid", 80)
        self.blocked(socket.gethostbyname, "example.invalid")
        self.blocked(socket.gethostbyname_ex, "example.invalid")
        self.blocked(socket.gethostbyaddr, "127.0.0.1")

    def test_creating_sockets_is_blocked(self):
        self.blocked(socket.socket, socket.AF_INET, socket.SOCK_STREAM)
        self.blocked(socket.socket, socket.AF_INET, socket.SOCK_DGRAM)
        self.blocked(_socket.socket, socket.AF_INET, socket.SOCK_DGRAM)

    def test_socket_methods_are_blocked_on_the_class(self):
        for name in ("connect", "connect_ex", "sendto", "send", "sendall"):
            self.blocked(getattr(socket.socket, name), object())

    def test_the_guard_applies_when_a_test_file_is_run_directly(self):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        code = ("import runpy,sys; sys.argv=['x']; "
                "import socket\ntry:\n    runpy.run_path(%r, run_name='not_main')\n"
                "except SystemExit:\n    pass\n"
                "try:\n    socket.gethostbyname('example.invalid')\n    print('UNGUARDED')\n"
                "except RuntimeError:\n    print('GUARDED')\n") % os.path.join(ROOT, "tests", "test_principal.py")
        out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True,
                             cwd=os.path.dirname(ROOT), env=env, timeout=60)
        self.assertIn("GUARDED", out.stdout + out.stderr)
        self.assertNotIn("UNGUARDED", out.stdout)


if __name__ == "__main__":
    unittest.main()
