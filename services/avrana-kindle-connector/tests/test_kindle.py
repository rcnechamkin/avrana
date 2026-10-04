"""Tests for the Kindle Connector.

Pure-logic tests plus live gating checks against the running container. Nothing here writes to a
real user's account: the write paths were proven separately against the Homepage service account
and a scoped-then-removed ABS device.
"""
import importlib.util
import pathlib
import subprocess
import sys

spec = importlib.util.spec_from_file_location(
    "kindle", pathlib.Path(__file__).resolve().parents[1] / "kindle.py")
kindle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kindle)


# ---------------------------------------------------------------- address validation
def test_accepts_real_kindle_addresses():
    for a in ("cnechamkin_WquaKC@kindle.com", "a.b+c@kindle.com", "UPPER@KINDLE.COM"):
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


# ---------------------------------------------------------------- live gating
def curl(*args):
    return subprocess.run(
        ["docker", "run", "--rm", "--network", "authentik_frontend",
         "curlimages/curl:latest", "-s", *args],
        capture_output=True, text=True).stdout


def test_denied_without_the_books_group():
    out = curl("-o", "/dev/null", "-w", "%{http_code}",
               "-H", "X-authentik-username: nobody",
               "-H", "X-authentik-groups: avrana-users",
               "http://avrana-kindle-connector:8096/")
    assert out.strip() == "403", out


def test_denied_with_no_headers_at_all():
    out = curl("-o", "/dev/null", "-w", "%{http_code}", "http://avrana-kindle-connector:8096/")
    assert out.strip() == "403", out


def test_healthz_is_open_for_the_healthcheck():
    out = curl("-o", "/dev/null", "-w", "%{http_code}", "http://avrana-kindle-connector:8096/healthz")
    assert out.strip() == "200", out


def test_books_user_sees_the_amazon_link_and_sender():
    out = curl("-H", "X-authentik-username: akadmin",
               "-H", "X-authentik-groups: avrana-users|avrana-books",
               "http://avrana-kindle-connector:8096/")
    assert "amazon.com/hz/mycd/myx" in out
    assert "cody@avrana.net" in out


def test_bad_address_is_rejected_by_the_running_service():
    out = curl("-X", "POST",
               "-H", "X-authentik-username: nobody-at-all",
               "-H", "X-authentik-groups: avrana-users|avrana-books",
               "-d", "address=someone@gmail.com",
               "http://avrana-kindle-connector:8096/save")
    assert "not a @kindle.com address" in out


def test_no_secrets_in_rendered_page():
    out = curl("-H", "X-authentik-username: akadmin",
               "-H", "X-authentik-groups: avrana-users|avrana-books",
               "http://avrana-kindle-connector:8096/")
    # The ABS admin key lives in this process's environment; it must never reach the page.
    import re
    assert not re.search(r"\b[a-f0-9]{32,}\b", out), "possible key material in page"
