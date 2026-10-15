"""The service-neutral guard and helpers every adapter builds on (identity bound in the PATH, per-route
404 classes, exact-or-refuse mapping). Synthetic data only."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import re
import unittest

from avrana_home.adapters._base import (GuardedTransport, Route, bounded_int, check_request,
                                        image_magic_ok, match_exactly_one)
from avrana_home.contract import AmbiguousMappingError, ForbiddenRequest, MappingFailed
from avrana_home.resilience import (ItemGone, RouteMissing, TransportResponse, UpstreamMalformed,
                                    UpstreamNotFound, UserGone)

UID = re.compile(r"usr_[a-z0-9]{6,20}")
ME = "usr_aaaaaa11"
OTHER = "usr_bbbbbb22"
ROUTES = (
    Route("list", r"/api/users", (), user_scoped=False, needs_user=False, not_found=RouteMissing),
    Route("progress", r"/api/users/(?P<user>[^/]+)/progress", ("limit",), user_scoped=True,
          bind_in="path", not_found=UserGone),
    Route("item", r"/api/items/[a-z0-9]{6,20}", (), user_scoped=False, not_found=ItemGone),
)


class PathBoundRoutes(unittest.TestCase):
    def ok(self, path, query=None, bound=ME, method="GET"):
        return check_request(ROUTES, UID, method, path, query, bound)

    def refused(self, path, query=None, bound=ME, method="GET"):
        with self.assertRaises(ForbiddenRequest):
            self.ok(path, query, bound, method)

    def test_the_bound_user_in_the_path_is_allowed(self):
        self.assertEqual(self.ok(f"/api/users/{ME}/progress", {"limit": "5"}).name, "progress")

    def test_another_users_id_in_the_path_is_refused(self):
        self.refused(f"/api/users/{OTHER}/progress")

    def test_encoded_slashes_traversal_and_look_alikes_are_refused(self):
        for evil in (f"/api/users/{ME}%2f..%2f{OTHER}/progress", f"/api/users/{ME}/../{OTHER}/progress",
                     f"/api/users/{ME}/progress/", f"/api/users//progress", f"/api/users/{ME}x/progress",
                     f"/api/users/{ME}/progress?x=1", "/api/users/%s/progress" % ME.upper()):
            self.refused(evil)

    def test_no_bound_user_means_no_user_route(self):
        self.refused(f"/api/users/{ME}/progress", bound=None)

    def test_a_malformed_bound_id_is_refused_and_cannot_be_bound(self):
        self.refused(f"/api/users/{ME}/progress", bound="../x")
        with self.assertRaises(ForbiddenRequest):
            GuardedTransport(object(), ROUTES, UID, "usr_a b")

    def test_extra_query_keys_and_non_get_are_refused(self):
        self.refused(f"/api/users/{ME}/progress", {"limit": "5", "token": "x"})
        for method in ("POST", "PUT", "DELETE", "PATCH", "get", None):
            self.refused(f"/api/users/{ME}/progress", method=method)

    def test_a_path_route_without_a_user_group_cannot_be_declared(self):
        with self.assertRaises(ValueError):
            Route("bad", r"/api/users/[^/]+/progress", (), user_scoped=True, bind_in="path")


class Recorder:
    def __init__(self, exc=None):
        self.exc = exc
        self.calls = []

    def request(self, method, path, query, timeout, max_bytes):
        self.calls.append((method, path))
        if self.exc is not None:
            raise self.exc
        return TransportResponse(200, b"{}", "application/json")


class NotFoundClassesAreDeclaredByTheRoute(unittest.TestCase):
    def go(self, path, bound=ME):
        inner = Recorder(UpstreamNotFound(404))
        with self.assertRaises(UpstreamNotFound) as cm:
            GuardedTransport(inner, ROUTES, UID, bound).request("GET", path, None, 1.0, 100)
        return type(cm.exception)

    def test_each_route_names_what_its_404_means(self):
        self.assertIs(self.go("/api/users", bound=None), RouteMissing)
        self.assertIs(self.go(f"/api/users/{ME}/progress"), UserGone)
        self.assertIs(self.go("/api/items/abcdef12"), ItemGone)

    def test_an_already_classified_404_is_left_alone(self):
        inner = Recorder(ItemGone(404))
        with self.assertRaises(ItemGone):
            GuardedTransport(inner, ROUTES, UID, ME).request("GET", f"/api/users/{ME}/progress", None, 1.0, 1)

    def test_a_refused_request_never_reaches_the_inner_transport(self):
        inner = Recorder()
        guard = GuardedTransport(inner, ROUTES, UID, ME)
        for path in (f"/api/users/{OTHER}/progress", "/admin", "/api/items/../x"):
            with self.assertRaises(ForbiddenRequest):
                guard.request("GET", path, None, 1.0, 1)
        with self.assertRaises(ForbiddenRequest):
            guard.request("POST", "/api/users", None, 1.0, 1)
        self.assertEqual(inner.calls, [])

    def test_repr_hides_everything(self):
        self.assertEqual(repr(GuardedTransport(Recorder(), ROUTES, UID, ME)), "GuardedTransport(<redacted>)")


class ExactOrRefuse(unittest.TestCase):
    @staticmethod
    def extract(entry):
        if isinstance(entry, dict) and isinstance(entry.get("name"), str) and isinstance(entry.get("id"), str):
            return entry["name"], entry["id"]
        return None

    def pick(self, wanted, entries):
        return match_exactly_one(wanted, entries, self.extract)

    def test_exact_match_links(self):
        uid, entry = self.pick("member-a", [{"name": "member-b", "id": "2"}, {"name": "member-a", "id": "1"}])
        self.assertEqual(uid, "1")
        self.assertEqual(entry["name"], "member-a")

    def test_loose_matches_never_link(self):
        for other in ("Member-A", " member-a", "member-a ", "MEMBER-A"):
            with self.assertRaises(MappingFailed) as cm:
                self.pick("member-a", [{"name": other, "id": "1"}])
            self.assertEqual(cm.exception.reason, "case_or_unicode_mismatch")

    def test_no_match_and_empty_list_are_unmapped(self):
        for entries in ([], [{"name": "someone", "id": "1"}]):
            with self.assertRaises(MappingFailed) as cm:
                self.pick("member-a", entries)
            self.assertEqual(cm.exception.reason, "unmapped")

    def test_two_exact_matches_or_an_exact_plus_a_loose_collision_is_refused(self):
        with self.assertRaises(AmbiguousMappingError):
            self.pick("member-a", [{"name": "member-a", "id": "1"}, {"name": "member-a", "id": "2"}])
        with self.assertRaises(AmbiguousMappingError):
            self.pick("member-a", [{"name": "member-a", "id": "1"}, {"name": "Member-A", "id": "2"}])

    def test_the_same_account_listed_twice_is_not_ambiguous(self):
        uid, _ = self.pick("member-a", [{"name": "member-a", "id": "1"}, {"name": "member-a", "id": "1"}])
        self.assertEqual(uid, "1")

    def test_a_non_empty_list_nobody_can_be_parsed_from_is_drift_not_unmapped(self):
        with self.assertRaises(UpstreamMalformed):
            self.pick("member-a", [{"nom": "member-a"}, "x", None, 5])
        uid, _ = self.pick("member-a", [{"nom": "x"}, {"name": "member-a", "id": "9"}])   # partial drift is fine
        self.assertEqual(uid, "9")

    def test_unicode_look_alikes_do_not_link(self):
        with self.assertRaises(MappingFailed):
            self.pick("member-a", [{"name": "member‐a", "id": "1"}])          # a hyphen look-alike


class SmallHelpers(unittest.TestCase):
    def test_bounded_int(self):
        self.assertEqual(bounded_int(5), 5)
        self.assertEqual(bounded_int(5.9), 5)
        for bad in (True, "5", None, 10 ** 400, -(10 ** 30), float("nan"), float("inf")):
            self.assertIsNone(bounded_int(bad))

    def test_image_magic(self):
        self.assertTrue(image_magic_ok("image/png", b"\x89PNG\r\n\x1a\nxx"))
        self.assertTrue(image_magic_ok("image/jpeg", b"\xff\xd8\xffxx"))
        self.assertTrue(image_magic_ok("image/webp", b"RIFF\x00\x00\x00\x00WEBPxx"))
        self.assertFalse(image_magic_ok("image/png", b"<html>"))
        self.assertFalse(image_magic_ok("image/svg+xml", b"<svg/>"))


if __name__ == "__main__":
    unittest.main()
