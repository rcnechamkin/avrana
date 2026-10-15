"""Network guard: importing this module makes any attempt to open a socket or resolve a name raise.

Every test file imports it (also when run directly), so the adapter layer is exercised only through
fake transports as a checked property.
"""
import _socket
import socket


def _blocked(*args, **kwargs):
    raise RuntimeError("network access is forbidden in avrana-home tests")


for _name in ("connect", "connect_ex", "sendto", "send", "sendall", "__init__"):
    setattr(socket.socket, _name, _blocked)
_socket.socket = _blocked
for _name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex",
              "gethostbyaddr", "getnameinfo"):
    setattr(socket, _name, _blocked)
    if hasattr(_socket, _name):
        setattr(_socket, _name, _blocked)
