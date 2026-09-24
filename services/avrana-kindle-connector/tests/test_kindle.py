"""Offline Kindle validation/group tests. Live Docker tests deliberately omitted."""
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location(
    "kindle", pathlib.Path(__file__).resolve().parents[1] / "kindle.py")
kindle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kindle)


# ---------------------------------------------------------------- address validation
def test_accepts_real_kindle_addresses():
    for a in ("reader_example@kindle.com", "a.b+c@kindle.com", "UPPER@KINDLE.COM"):
        assert kindle.KINDLE_RE.match(a), a


def test_rejects_anything_that_is_not_kindle():
    # A typo here means Amazon silently discards the book, so this must be strict.
    for a in ("someone@gmail.com", "me@free.kindle.com", "me@kindle.com.evil.com",
              "me@kindle.co", "@kindle.com", "me@kindle.com ", "", "me at kindle.com"):
        assert not kindle.KINDLE_RE.match(a.strip()) or a.strip() != a, a


def test_rejects_injection_shaped_input():
    for a in ("a@kindle.com,b@evil.com", "a@kindle.com\nBcc: x@y.com", "'; DROP TABLE user;--"):
        assert not kindle.KINDLE_RE.match(a), a


# ---------------------------------------------------------------- group parsing
def test_parses_authentik_group_separator():
    assert kindle.parse_groups("avrana-users|avrana-books") == {"avrana-users", "avrana-books"}
    assert "authentik Admins" in kindle.parse_groups("avrana-users|authentik Admins")
    assert kindle.parse_groups("") == set()
