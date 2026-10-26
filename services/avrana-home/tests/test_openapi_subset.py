"""The Jellyfin adapter checked against Jellyfin's own published OpenAPI interface (R2-A, AVR-747). Offline.

`contracts/jellyfin-openapi-subset.json` holds route parameter names, response envelopes, schema property names
and types, and four enums, extracted by `tools/extract_openapi_subset.py` from the official spec files for
10.11.11 (deployed) and 12.3.0 (current release). This gate fails when, for ANY recorded version:
  * the adapter allow-lists a route the spec does not have, or a query key that route does not accept;
  * a user-scoped route stops accepting `userId` (an API key is an administrator, so a route without it would
    answer unfiltered: docs/audits/2026-10-26-oss-reuse-audit.md, section 6);
  * the adapter actually SENDS a `fields`, `enableImageTypes`, `includeItemTypes` or `mediaTypes` value the
    spec's enum does not list (captured from real adapter calls against the synthetic fake);
  * `contracts/jellyfin.json` declares an envelope or a field the spec does not have, or with another type,
    unless the divergence is recorded in KNOWN_ABSENT with its reason.
It proves agreement with the published interface, not with the deployed server (that is the owner's recorded
check, ADAPTER-CONTRACT.md section 9).
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import json
from pathlib import Path
import unittest

from avrana_home.adapters.jellyfin import ALLOWED_ROUTES, JellyfinAdapter
from avrana_home.resilience import FakeClock
from tests.fake_jellyfin import A, FakeJellyfin, FakeTransport, load
from tests.helpers import make_principal

HOME = Path(__file__).resolve().parents[1]
SUBSET = json.loads((HOME / "contracts/jellyfin-openapi-subset.json").read_text(encoding="utf-8"))
CONTRACT = json.loads((HOME / "contracts/jellyfin.json").read_text(encoding="utf-8"))
VERSIONS = SUBSET["versions"]

# adapter route name -> the spec path template it corresponds to
SPEC_PATH = {"users": "/Users", "resume": "/UserItems/Resume", "latest": "/Items/Latest", "items": "/Items",
             "image": "/Items/{itemId}/Images/{imageType}"}
# contract entity -> spec schema
SPEC_SCHEMA = {"item": "BaseItemDto", "item.UserData": "UserItemDataDto", "user": "UserDto",
               "user.Policy": "UserPolicy"}
# query key -> enum its comma-separated values must belong to
VALUE_ENUM = {"fields": "ItemFields", "enableImageTypes": "ImageType", "includeItemTypes": "BaseItemKind",
              "mediaTypes": "MediaType"}
# Declared in contracts/jellyfin.json but not in the published schema. Each entry says why it stays declared.
KNOWN_ABSENT = {
    ("item.UserData", "UserId"): "not in UserItemDataDto in 10.11.11 or 12.3.0; the adapter's scope tripwire "
                                 "reads it only when present, so it is harmless but in practice never fires",
}
COMPATIBLE = {"string": {"string", "enum"}, "integer": {"integer"}, "number": {"number", "integer"},
              "boolean": {"boolean"}, "object": {"object"}}


class SubsetFileTests(unittest.TestCase):
    def test_records_the_deployed_and_the_current_release(self):
        self.assertIn("10.11.11", VERSIONS)
        self.assertTrue(any(v.startswith("12.") for v in VERSIONS), sorted(VERSIONS))
        for version, doc in VERSIONS.items():
            self.assertRegex(doc["sha256"], r"\A[0-9a-f]{64}\Z", version)
            self.assertTrue(doc["source_url"].startswith("https://repo.jellyfin.org/"), version)

    def test_holds_names_and_types_only(self):
        # no upstream prose is copied: every leaf is a short identifier
        def leaves(node):
            if isinstance(node, dict):
                for value in node.values():
                    yield from leaves(value)
            elif isinstance(node, list):
                for value in node:
                    yield from leaves(value)
            else:
                yield node
        for version, doc in VERSIONS.items():
            for key in ("paths", "schemas", "enums"):
                for leaf in leaves(doc[key]):
                    if isinstance(leaf, str):
                        self.assertNotIn(" ", leaf, (version, key, leaf))
                        self.assertLess(len(leaf), 64, (version, key, leaf))


class RouteTests(unittest.TestCase):
    def test_every_allow_listed_route_and_query_key_exists_in_every_version(self):
        self.assertEqual({r.name for r in ALLOWED_ROUTES}, set(SPEC_PATH))
        for version, doc in VERSIONS.items():
            for route in ALLOWED_ROUTES:
                spec = doc["paths"].get(SPEC_PATH[route.name])
                self.assertIsNotNone(spec, (version, route.name))
                self.assertFalse(spec["deprecated"], (version, route.name))
                missing = set(route.query_keys) - set(spec["query"])
                self.assertEqual(missing, set(), (version, route.name))

    def test_user_scoped_routes_accept_user_id_in_every_version(self):
        for version, doc in VERSIONS.items():
            for route in ALLOWED_ROUTES:
                if route.user_scoped:
                    self.assertIn("userId", doc["paths"][SPEC_PATH[route.name]]["query"], (version, route.name))

    def test_the_image_route_is_the_only_unauthenticated_one(self):
        # Matches the audit's finding: images are anonymous upstream, so the adapter re-checks visibility.
        for version, doc in VERSIONS.items():
            open_routes = {name for name, path in SPEC_PATH.items() if not doc["paths"][path]["authenticated"]}
            self.assertEqual(open_routes, {"image"}, version)
            self.assertTrue(JellyfinAdapter.artwork_rechecks_visibility)

    def test_contract_envelopes_match_the_spec(self):
        expected = {"list": "array:{}", "items": "{}QueryResult"}
        entity_schema = {"item": "BaseItemDto", "user": "UserDto"}
        for version, doc in VERSIONS.items():
            for name, spec in CONTRACT["routes"].items():
                want = expected[spec["envelope"]].format(entity_schema[spec["entity"]])
                self.assertEqual(doc["paths"][SPEC_PATH[name]]["response"], want, (version, name))


class SentValueTests(unittest.TestCase):
    """The values the adapter really sends, captured from every public operation against the synthetic fake."""

    @classmethod
    def setUpClass(cls):
        fake = FakeJellyfin(FakeClock())
        adapter = JellyfinAdapter(FakeTransport(fake), clock=FakeClock())
        member = make_principal("member-a", ("avrana-users", "avrana-videos"))
        adapter.continue_items(member)
        adapter.recent_items(member)
        adapter.search(member, "synthetic")
        resume = load("resume_member_a.json")["Items"]
        first = next(i["Id"] for i in resume if not i["Id"].startswith("../")).replace("-", "").lower()
        adapter.item(member, first, fresh=True)
        adapter.fetch_artwork(member, f"jellyfin/primary/{first}")
        cls.requests = list(fake.requests)
        cls.user = A

    def test_every_operation_was_exercised(self):
        paths = {path for _method, path, _query in self.requests}
        for wanted in ("/Users", "/UserItems/Resume", "/Items/Latest", "/Items"):
            self.assertIn(wanted, paths)
        self.assertTrue(any(p.endswith("/Images/Primary") for p in paths), paths)

    def test_sent_enum_values_are_in_every_version(self):
        sent = {}
        for _method, _path, query in self.requests:
            for key, enum in VALUE_ENUM.items():
                if key in query:
                    sent.setdefault(enum, set()).update(v for v in query[key].split(",") if v)
        self.assertTrue(sent, "no enum-valued parameter was sent")
        for version, doc in VERSIONS.items():
            for enum, values in sent.items():
                self.assertEqual(values - set(doc["enums"][enum]), set(), (version, enum))

    def test_image_type_in_the_path_is_in_every_version(self):
        for version, doc in VERSIONS.items():
            self.assertIn("Primary", doc["enums"]["ImageType"], version)


class SchemaTests(unittest.TestCase):
    def test_declared_fields_exist_with_a_compatible_type(self):
        for version, doc in VERSIONS.items():
            for entity, fields in CONTRACT["entities"].items():
                schema_name = SPEC_SCHEMA.get(entity)
                if schema_name is None:          # item.ImageTags: a string map, checked below
                    continue
                props = doc["schemas"][schema_name]
                for field, json_type in fields.items():
                    if (entity, field) in KNOWN_ABSENT:
                        continue
                    self.assertIn(field, props, (version, entity, field))
                    spec_type = props[field]
                    if spec_type.startswith("ref:") and spec_type[4:] in doc["enums"]:
                        spec_type = "enum"           # e.g. Type -> BaseItemKind, a string enum
                    if spec_type.startswith("ref:"):
                        self.assertEqual(json_type, "object", (version, entity, field, spec_type))
                    else:
                        self.assertIn(spec_type, COMPATIBLE[json_type], (version, entity, field))

    def test_image_tags_is_a_string_map(self):
        for version, doc in VERSIONS.items():
            self.assertEqual(doc["schemas"]["BaseItemDto"]["ImageTags"], "object", version)

    def test_known_absent_entries_are_still_absent(self):
        # an exception that the upstream has since fixed must be removed, not kept forever
        for version, doc in VERSIONS.items():
            for entity, field in KNOWN_ABSENT:
                self.assertNotIn(field, doc["schemas"][SPEC_SCHEMA[entity]], (version, entity, field))


if __name__ == "__main__":
    unittest.main()
