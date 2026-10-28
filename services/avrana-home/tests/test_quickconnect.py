"""Embedded Quick Connect approval (quickconnect.py; owner decision 2026-10-27, ME-05 option C2). SYNTHETIC data only.

Pins the guardrails: exactly three allow-listed requests; the member's Jellyfin id only from the exact-username match;
never an administrator, disabled, unmatched or ambiguous account; only six digits; rate limits before any upstream
call; a timeout after sending is "unknown" and never retried.
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import json
import unittest

from avrana_home import quickconnect as qc
from avrana_home.resilience import (FakeClock, TransportResponse, UpstreamAuthError, UpstreamHTTPError,
                                    UpstreamNotFound, UpstreamTimeout)
from tests.helpers import make_principal

A_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
A_HEX = A_ID.replace("-", "")


def users(*extra, policy=None):
    base = [{"Id": A_ID, "Name": "member-a", "Policy": policy if policy is not None
             else {"IsAdministrator": False, "IsDisabled": False}},
            {"Id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "Name": "member-b",
             "Policy": {"IsAdministrator": False, "IsDisabled": False}}]
    return base + list(extra)


class Fake:
    """A transport answering the three routes; `authorize` may be a TransportResponse or an exception to raise."""

    def __init__(self, enabled=b"true", user_list=None, authorize=None, users_error=None):
        self.calls = []
        self.enabled, self.user_list, self.users_error = enabled, user_list or users(), users_error
        self.authorize = authorize if authorize is not None else TransportResponse(200, b"true", "application/json")

    def request(self, method, path, query, timeout, max_bytes):
        self.calls.append((method, path, dict(query or {})))
        if path == "/QuickConnect/Enabled":
            return TransportResponse(200, self.enabled, "application/json")
        if path == "/Users":
            if self.users_error:
                raise self.users_error
            return TransportResponse(200, json.dumps(self.user_list).encode(), "application/json")
        if isinstance(self.authorize, Exception):
            raise self.authorize
        return self.authorize

    def authorizations(self):
        return [c for c in self.calls if c[1] == "/QuickConnect/Authorize"]


VIDEO = ("avrana-users", "avrana-videos")


class ApproveTests(unittest.TestCase):
    def setUp(self):
        self.a = make_principal("member-a", VIDEO)

    def run_with(self, fake, code="123456", principal=None):
        return qc.QuickConnect(fake).approve(principal or self.a, code)

    def test_approves_as_the_member_with_their_own_id(self):
        fake = Fake()
        self.assertEqual(qc.APPROVED, self.run_with(fake))
        self.assertEqual([("GET", "/QuickConnect/Enabled", {}), ("GET", "/Users", {}),
                          ("POST", "/QuickConnect/Authorize", {"code": "123456", "userId": A_HEX})], fake.calls)

    def test_never_for_an_administrator_disabled_missing_policy_unmatched_or_ambiguous_account(self):
        cases = {
            "admin": users(policy={"IsAdministrator": True, "IsDisabled": False}),
            "disabled": users(policy={"IsAdministrator": False, "IsDisabled": True}),
            "no policy": users(policy={}),
            "half policy": users(policy={"IsDisabled": False}),
            "unmatched": [u for u in users() if u["Name"] != "member-a"],
            "loose only": [dict(users()[0], Name="Member-A")],
            "ambiguous": users({"Id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "Name": "member-a",
                                "Policy": {"IsAdministrator": False, "IsDisabled": False}}),
        }
        for name, user_list in cases.items():
            with self.subTest(case=name):
                fake = Fake(user_list=user_list)
                self.assertEqual(qc.NOT_ELIGIBLE, self.run_with(fake))
                self.assertEqual([], fake.authorizations())

    def test_needs_tv_and_movies_access_and_makes_no_call_without_it(self):
        fake = Fake()
        self.assertEqual(qc.NOT_ELIGIBLE, self.run_with(fake, principal=make_principal("member-a", ("avrana-books",))))
        self.assertEqual([], fake.calls)

    def test_only_six_digits_and_nothing_sent_otherwise(self):
        for code in ("", "12345", "1234567", "12345a", " 123456", "123456\n", "１２３４５６", None, 123456):
            with self.subTest(code=code):
                fake = Fake()
                self.assertEqual(qc.BAD_CODE, self.run_with(fake, code=code))
                self.assertEqual([], fake.calls)

    def test_switched_off_is_off_and_nothing_is_approved(self):
        fake = Fake(enabled=b"false")
        self.assertEqual(qc.OFF, self.run_with(fake))
        self.assertEqual([], fake.authorizations())
        self.assertEqual(qc.OFF, self.run_with(Fake(authorize=UpstreamAuthError(401))))   # turned off in between
        self.assertEqual(qc.UNAVAILABLE, self.run_with(Fake(authorize=UpstreamAuthError(403))))   # key lacks rights

    def test_upstream_answers_map_to_fixed_outcomes(self):
        for answer, outcome in ((UpstreamNotFound(404), qc.NOT_FOUND), (UpstreamHTTPError(500), qc.NOT_ACCEPTED),
                                (TransportResponse(200, b"false", "application/json"), qc.NOT_ACCEPTED),
                                (UpstreamTimeout(), qc.UNKNOWN)):
            with self.subTest(answer=type(answer).__name__):
                self.assertEqual(outcome, self.run_with(Fake(authorize=answer)))

    def test_a_timeout_after_sending_is_never_retried(self):
        fake = Fake(authorize=UpstreamTimeout())
        self.assertEqual(qc.UNKNOWN, self.run_with(fake))
        self.assertEqual(1, len(fake.authorizations()))

    def test_trouble_before_sending_is_unavailable_and_sends_nothing(self):
        for fake in (Fake(users_error=UpstreamTimeout()), Fake(user_list={"not": "a list"})):
            with self.subTest():
                self.assertEqual(qc.UNAVAILABLE, self.run_with(fake))
                self.assertEqual([], fake.authorizations())


class RateLimitTests(unittest.TestCase):
    def test_five_per_member_then_busy_before_any_call(self):
        clock = FakeClock()
        connect = qc.QuickConnect(Fake(), limit=qc.RateLimit(clock=clock.now))
        a, b = make_principal("member-a", VIDEO), make_principal("member-b", VIDEO)
        for _ in range(5):
            self.assertEqual(qc.APPROVED, connect.approve(a, "123456"))
        fake = Fake()
        connect._transport = fake
        self.assertEqual(qc.BUSY, connect.approve(a, "123456"))
        self.assertEqual([], fake.calls)
        self.assertNotEqual(qc.BUSY, connect.approve(b, "123456"))        # another member is not blocked
        clock.advance(601)
        self.assertEqual(qc.APPROVED, connect.approve(a, "123456"))       # the window moves on

    def test_overall_cap(self):
        clock = FakeClock()
        limit = qc.RateLimit(per_member=5, overall=3, clock=clock.now)
        self.assertEqual([True, True, True, False], [limit.take(f"m{i}") for i in range(4)])


class AllowListTests(unittest.TestCase):
    def test_only_the_three_requests(self):
        qc.check_request("GET", "/QuickConnect/Enabled", None)
        qc.check_request("GET", "/Users", {})
        qc.check_request("POST", "/QuickConnect/Authorize", {"code": "123456", "userId": A_HEX})
        for method, path, query in (
                ("DELETE", "/Users", None), ("POST", "/Users", None), ("GET", "/QuickConnect/Authorize", None),
                ("POST", "/QuickConnect/Authorize", {"code": "123456"}),
                ("POST", "/QuickConnect/Authorize", {"code": "123456", "userId": A_ID}),          # dashed: not ours
                ("POST", "/QuickConnect/Authorize", {"code": "12345x", "userId": A_HEX}),
                ("POST", "/QuickConnect/Authorize", {"code": "123456", "userId": A_HEX, "x": "1"}),
                ("POST", "/QuickConnect/Initiate", None), ("GET", "/Users", {"isDisabled": "false"})):
            with self.subTest(method=method, path=path, query=query), \
                    self.assertRaises(qc.ForbiddenQuickConnectRequest):
                qc.check_request(method, path, query)


class StatusTests(unittest.TestCase):
    def test_status_for_the_page(self):
        a = make_principal("member-a", VIDEO)
        self.assertEqual(qc.READY, qc.QuickConnect(Fake()).status(a))
        self.assertEqual(qc.OFF, qc.QuickConnect(Fake(enabled=b"false")).status(a))
        self.assertEqual(qc.NOT_ELIGIBLE, qc.QuickConnect(Fake(user_list=users(
            policy={"IsAdministrator": True, "IsDisabled": False}))).status(a))
        self.assertEqual(qc.UNAVAILABLE, qc.QuickConnect(Fake(users_error=UpstreamTimeout())).status(a))
        fake = Fake()
        qc.QuickConnect(fake).status(a)
        self.assertEqual([], fake.authorizations())                       # the page never approves anything

    def test_status_is_reused_per_member_for_a_short_while(self):
        clock, fake = FakeClock(), Fake()
        connect = qc.QuickConnect(fake, clock=clock.now)
        a, b = make_principal("member-a", VIDEO), make_principal("member-b", VIDEO)
        connect.status(a)
        connect.status(a)
        self.assertEqual(2, len(fake.calls))                              # one look: Enabled + Users
        connect.status(b)
        self.assertEqual(4, len(fake.calls))                              # each member has their own
        clock.advance(qc.STATUS_TTL + 1)
        connect.status(a)
        self.assertEqual(6, len(fake.calls))

    def test_an_unavailable_look_is_retried_sooner_and_a_failed_approval_forgets_the_status(self):
        clock = FakeClock()
        a = make_principal("member-a", VIDEO)
        connect = qc.QuickConnect(Fake(users_error=UpstreamTimeout()), clock=clock.now)
        self.assertEqual(qc.UNAVAILABLE, connect.status(a))
        connect._transport = Fake()
        self.assertEqual(qc.UNAVAILABLE, connect.status(a))               # still within the short window
        clock.advance(qc.STATUS_TTL_UNAVAILABLE + 1)
        self.assertEqual(qc.READY, connect.status(a))
        connect._transport = Fake(enabled=b"false")
        self.assertEqual(qc.OFF, connect.approve(a, "123456"))
        self.assertEqual(qc.OFF, connect.status(a))                       # looked again, not the cached READY

    def test_repr_is_redacted(self):
        self.assertEqual("QuickConnect(<redacted>)", repr(qc.QuickConnect(Fake())))


if __name__ == "__main__":
    unittest.main()
