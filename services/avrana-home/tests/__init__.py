"""Test package guard: any attempt to open a network connection fails the test run loudly.

The adapter layer is exercised only through fake transports; this makes that a checked property
rather than a habit.
"""
import socket


def _blocked(*args, **kwargs):
    raise RuntimeError("network access is forbidden in avrana-home tests")


socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
