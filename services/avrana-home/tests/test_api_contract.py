"""API-contract gate for the Jellyfin adapter (AVR-386, AVR-376). Offline, synthetic data only.

`contracts/jellyfin.json` declares the routes the adapter may call and the response fields it may
read, with their JSON types. This gate fails the build when:
  * the adapter's allow-listed routes and the contract's routes differ;
  * the adapter reads a response field the contract does not declare (silent drift);
  * a fixture, or an owner-approved recording under fixtures/jellyfin/recorded/, carries a declared
    field with the wrong type or the wrong envelope.
Recordings are absent until the owner approves capturing and sanitising them; the gate then
covers them automatically. Hostile fixtures are type-correct by design (their hostility is in
values), so they are checked too.
"""
import json
from pathlib import Path
import re
import unittest

from avrana_home.adapters import jellyfin

HOME = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((HOME / "contracts/jellyfin.json").read_text(encoding="utf-8"))
FIXTURES = HOME / "tests/fixtures/jellyfin"
SOURCE = (HOME / "avrana_home/adapters/jellyfin.py").read_text(encoding="utf-8")

# fixture file -> route it is shaped like
FIXTURE_ROUTES = {
    "users.json": "users",
    "resume_member_a.json": "resume", "resume_member_b.json": "resume",
    "hostile_resume_b_for_a.json": "resume",
    "latest_member_a.json": "latest", "latest_member_b.json": "latest",
    "nextup_member_a.json": "next_up",
}

TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def violations(route, body):
    """Contract violations for one response body, as stable strings. Pure."""
    spec = CONTRACT["routes"][route]
    if spec["envelope"] == "list":
        if not isinstance(body, list):
            return [f"{route}: body is not a list"]
        entities = body
    else:
        if not isinstance(body, dict) or not isinstance(body.get("Items"), list):
            return [f"{route}: body has no Items list"]
        entities = body["Items"]
    found = []
    entity = spec["entity"]
    for index, raw in enumerate(entities):
        if not isinstance(raw, dict):
            found.append(f"{route}[{index}]: entry is not an object")
            continue
        found += _fields(f"{route}[{index}]", entity, raw)
    return found


def _fields(where, entity, raw):
    found = []
    for name, kind in CONTRACT["entities"][entity].items():
        if name in raw and raw[name] is not None and not TYPES[kind](raw[name]):
            found.append(f"{where}.{name}: expected {kind}")
        nested = f"{entity}.{name}"
        if nested in CONTRACT["entities"] and isinstance(raw.get(name), dict):
            found += _fields(f"{where}.{name}", nested, raw[name])
    return found


def field_reads(text):
    """Capitalised (Jellyfin-style) keys read via .get("X"[, default]), ["X"] or "X" in name."""
    q = r"[\"']"
    found = set(re.findall(rf"\.get\({q}([A-Z]\w*){q}\s*[,)]", text))
    found |= set(re.findall(rf"\[{q}([A-Z]\w*){q}\]", text))
    found |= set(re.findall(rf"{q}([A-Z]\w*){q} in \w+", text))
    return found


def bodies():
    for name, route in FIXTURE_ROUTES.items():
        yield name, route, json.loads((FIXTURES / name).read_text(encoding="utf-8"))["response"]
    recorded = FIXTURES / "recorded"
    for path in sorted(recorded.glob("*.json")) if recorded.is_dir() else []:
        data = json.loads(path.read_text(encoding="utf-8"))
        yield f"recorded/{path.name}", data["route"], data["response"]


class ContractTests(unittest.TestCase):
    def test_routes_match_the_adapter_allow_list(self):
        # The image route returns bytes, not JSON, so it has no field contract.
        adapter = sorted(r.name for r in jellyfin.ALLOWED_ROUTES if r.name != "image")
        self.assertEqual(adapter, sorted(CONTRACT["routes"]))
        for name, spec in CONTRACT["routes"].items():
            self.assertTrue(any(r.name == name and r.pattern.fullmatch(spec["path"])
                                for r in jellyfin.ALLOWED_ROUTES), name)

    def test_every_field_the_adapter_reads_is_declared(self):
        # Field NAMES only: placement on the right entity is checked by the fixture conformance test.
        read = field_reads(SOURCE)
        declared = set()
        for fields in CONTRACT["entities"].values():
            declared |= set(fields)
        declared |= {"Items", "TotalRecordCount"}  # envelope
        self.assertTrue(read, "field scan found nothing: the scan itself is broken")
        self.assertEqual(sorted(read - declared), [], "adapter reads undeclared fields: update the contract")

    def test_every_fixture_is_mapped_to_a_route(self):
        on_disk = sorted(p.name for p in FIXTURES.glob("*.json"))
        self.assertEqual(on_disk, sorted(FIXTURE_ROUTES))

    def test_fixtures_and_recordings_conform(self):
        seen = 0
        for name, route, body in bodies():
            with self.subTest(fixture=name):
                self.assertEqual(violations(route, body), [])
                seen += 1
        self.assertGreaterEqual(seen, len(FIXTURE_ROUTES))

    def test_recordings_are_labelled_and_synthetic_fixtures_say_so(self):
        for name in FIXTURE_ROUTES:
            data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
            self.assertIn("SYNTHETIC", data["_synthetic"], name)
        recorded = FIXTURES / "recorded"
        for path in sorted(recorded.glob("*.json")) if recorded.is_dir() else []:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in ("route", "response", "_recorded", "_sanitised_by"):
                self.assertIn(key, data, path.name)

    def test_gate_rejects_drift(self):
        """The validator is not vacuous: each kind of drift is caught."""
        self.assertEqual(violations("resume", [{"Id": "x"}]), ["resume: body has no Items list"])
        self.assertEqual(violations("latest", {"Items": []}), ["latest: body is not a list"])
        self.assertEqual(violations("users", [{"Id": 5}]), ["users[0].Id: expected string"])
        self.assertEqual(violations("users", [{"Policy": {"IsDisabled": "false"}}]),
                         ["users[0].Policy.IsDisabled: expected boolean"])
        self.assertEqual(violations("resume", {"Items": [{"UserData": {"PlaybackPositionTicks": "1"}}]}),
                         ["resume[0].UserData.PlaybackPositionTicks: expected integer"])
        self.assertEqual(violations("latest", [{"RunTimeTicks": True}]), ["latest[0].RunTimeTicks: expected integer"])
        self.assertEqual(violations("latest", ["x"]), ["latest[0]: entry is not an object"])
        self.assertEqual(violations("latest", [{"Id": None, "Unknown": 1}]), [])

    def test_field_scan_sees_default_and_single_quote_forms(self):
        sample = """raw.get("A1", 0); raw.get('B2'); raw["C3"]; "D4" in data"""
        self.assertEqual(field_reads(sample), {"A1", "B2", "C3", "D4"})


if __name__ == "__main__":
    unittest.main()
