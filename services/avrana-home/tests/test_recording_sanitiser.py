"""Recording sanitiser (AVR-376): offline, synthetic "raw" input standing in for an owner capture."""
import copy
import datetime
import json
from pathlib import Path
import tempfile
import unittest

from avrana_home import recording_sanitiser as rs
from tests.test_api_contract import CONTRACT, violations

SECRETS = ("Member Real Name", "realmember", "0f8fad5bd9cb469fa16570867728950e", "/mnt/media/Movies/Secret",
           "Private Show Title", "abcdef0123456789tag", "f81d4fae7dec11d0a76500a0c91e6bf6")

_ITEM = {"Id": SECRETS[2], "Name": SECRETS[4], "Type": "Episode", "SeriesName": SECRETS[4],
         "ParentIndexNumber": 2, "IndexNumber": 5, "RunTimeTicks": 13_000_000_000, "ProductionYear": 2021,
         "Path": SECRETS[3], "ProviderIds": {"Imdb": "tt0000001"}, "Overview": "A private overview text",
         "UserData": {"PlaybackPositionTicks": 6_000_000_000, "PlayedPercentage": 46.2, "Played": False,
                      "ItemId": SECRETS[2], "UserId": SECRETS[6], "Key": "Private Show Title-s2e5",
                      "LastPlayedDate": "2026-10-01T20:00:00Z"},
         "ImageTags": {"Primary": SECRETS[5], "Thumb": "thumbtag0000"}}
RAW_RESUME = {
    "Items": [copy.deepcopy(_ITEM) for _ in range(5)],
    "TotalRecordCount": 5,
    "StartIndex": 0,
    "SomethingNew": "server-added envelope field",
}
RAW_USERS = [{"Id": SECRETS[6], "Name": SECRETS[1], "Policy": {"IsDisabled": False, "IsAdministrator": True,
                                                                 "EnableAllFolders": True},
              "LastLoginDate": "2026-10-01T20:00:00Z", "ServerId": "server-id-0001"}]


def _leaves(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from _leaves(v)
    else:
        yield value


class SanitiserTests(unittest.TestCase):
    def test_output_conforms_and_carries_no_raw_value(self):
        for route, raw in (("resume", RAW_RESUME), ("users", RAW_USERS)):
            with self.subTest(route=route):
                rec = rs.build_recording(route, copy.deepcopy(raw), "10.11.11", CONTRACT,
                                         today=datetime.date(2026, 10, 14))
                self.assertEqual(violations(route, rec["response"]), [])
                text = json.dumps(rec)
                for secret in SECRETS + ("tt0000001", "A private overview", "server-id-0001", "2026-10-01T20"):
                    self.assertNotIn(secret, text)
                for key in ("route", "response", "_recorded", "_sanitised_by"):
                    self.assertIn(key, rec)

    def test_undeclared_fields_are_named_not_kept(self):
        rec = rs.build_recording("resume", copy.deepcopy(RAW_RESUME), "10.11.11", CONTRACT)
        self.assertEqual(rec["_undeclared_fields"], {
            "(envelope)": ["SomethingNew"], "item": ["Overview", "Path", "ProviderIds"],
            "item.ImageTags": ["Thumb"], "item.UserData": ["LastPlayedDate"]})
        item = rec["response"]["Items"][0]
        self.assertNotIn("Path", item)
        self.assertEqual(set(item["UserData"]), set(CONTRACT["entities"]["item.UserData"]))

    def test_keys_that_could_be_data_are_counted_not_named(self):
        raw = copy.deepcopy(RAW_RESUME)
        raw["Items"][0]["ImageTags"]["Member Real Name"] = "x"
        raw["Items"][0]["UserData"]["alice"] = 1
        raw["Items"][0]["/mnt/media/Secret Show"] = 1
        raw["Carol Secret Envelope"] = 1
        rec = rs.build_recording("resume", raw, "10.11.11", CONTRACT)
        text = json.dumps(rec)
        for secret in ("Member Real Name", "alice", "/mnt/media/Secret Show", "Carol Secret Envelope"):
            self.assertNotIn(secret, text)
        self.assertIn("(other keys omitted)", rec["_undeclared_fields"]["item.ImageTags"])
        self.assertIn("Thumb", rec["_undeclared_fields"]["item.ImageTags"])  # schema-shaped names still show

    def test_a_schema_shaped_key_that_is_also_a_raw_value_is_refused(self):
        raw = copy.deepcopy(RAW_USERS)
        raw[0]["Name"] = "AdaLovelace"
        raw[0]["Policy"]["AdaLovelace"] = True  # data used as a key, shaped like a field name
        with self.assertRaises(rs.SanitiseError):
            rs.build_recording("users", raw, "10.11.11", CONTRACT)

    def test_recursion_while_sanitising_is_a_clean_refusal(self):
        original = rs.build_recording
        def deep(*a, **k):
            raise RecursionError()
        with tempfile.TemporaryDirectory() as tmp:
            raw, out = Path(tmp, "raw.json"), Path(tmp, "out.json")
            raw.write_text(json.dumps(RAW_USERS), encoding="utf-8")
            try:
                rs.build_recording = deep
                self.assertEqual(rs.main(["--route", "users", "--server-version", "10.11.11", str(raw), str(out)]), 1)
            finally:
                rs.build_recording = original
            self.assertFalse(out.exists())

    def test_numbers_are_never_copied_through(self):
        rec = rs.build_recording("resume", copy.deepcopy(RAW_RESUME), "10.11.11", CONTRACT)
        numbers = [v for v in _leaves(rec["response"]) if isinstance(v, (int, float)) and not isinstance(v, bool)]
        self.assertTrue(numbers)
        for real in (13_000_000_000, 6_000_000_000, 46.2, 2021):
            self.assertNotIn(real, numbers)

    def test_deep_nesting_and_odd_versions_are_refused_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, out = Path(tmp, "raw.json"), Path(tmp, "out.json")
            raw.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
            self.assertIn(rs.main(["--route", "users", "--server-version", "10.11.11", str(raw), str(out)]), (1, 2))
            self.assertFalse(out.exists())
        for version in ("10.11.11 ", "1" * 100, "١٠.11", "10", "10..11"):
            with self.subTest(version=version), self.assertRaises(rs.SanitiseError):
                rs.build_recording("users", copy.deepcopy(RAW_USERS), version, CONTRACT)

    def test_lists_are_cut_and_count_follows(self):
        body = rs.build_recording("resume", copy.deepcopy(RAW_RESUME), "10.11.11", CONTRACT)["response"]
        self.assertEqual(len(body["Items"]), rs.MAX_ENTRIES)
        self.assertEqual(body["TotalRecordCount"], rs.MAX_ENTRIES)

    def test_a_type_change_on_the_server_still_fails_the_gate(self):
        raw = copy.deepcopy(RAW_RESUME)
        raw["Items"][0]["UserData"]["Played"] = "false"  # the server started sending a string
        raw["Items"][0]["RunTimeTicks"] = 1.5
        body = rs.build_recording("resume", raw, "10.11.11", CONTRACT)["response"]
        self.assertEqual(violations("resume", body), ["resume[0].RunTimeTicks: expected integer",
                                                      "resume[0].UserData.Played: expected boolean"])

    def test_values_that_resemble_key_names_are_fine(self):
        raw = {"Items": [{"Id": "series-id-0001", "Type": "Series", "Name": "SeriesName"}]}
        rec = rs.build_recording("resume", raw, "10.11.11", CONTRACT)
        self.assertEqual(rec["response"]["Items"][0]["Type"], "synthetic-type-1")

    def test_refuses_to_write_when_a_raw_value_survives(self):
        original = rs._Synth.value
        try:
            rs._Synth.value = lambda self, field, raw: raw  # a broken synthesiser copies values through
            with self.assertRaises(rs.SanitiseError) as caught:
                rs.build_recording("users", copy.deepcopy(RAW_USERS), "10.11.11", CONTRACT)
        finally:
            rs._Synth.value = original
        for secret in SECRETS:
            self.assertNotIn(secret, str(caught.exception))

    def test_bad_input_is_refused(self):
        for route, raw in (("resume", []), ("users", {"Items": []}), ("nope", []), ("users", ["x"])):
            with self.subTest(route=route, raw=raw):
                with self.assertRaises(rs.SanitiseError):
                    rs.build_recording(route, raw, "10.11.11", CONTRACT)
        with self.assertRaises(rs.SanitiseError):
            rs.build_recording("users", copy.deepcopy(RAW_USERS), "latest", CONTRACT)

    def test_cli_creates_once_and_never_prints_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, out = Path(tmp, "raw.json"), Path(tmp, "users.json")
            raw.write_text(json.dumps(RAW_USERS), encoding="utf-8")
            args = ["--route", "users", "--server-version", "10.11.11", str(raw), str(out)]
            self.assertEqual(rs.main(args), 0)
            first = out.read_bytes()
            self.assertNotIn(b"\r", first)
            self.assertEqual(rs.main(args), 1, "an existing recording is never overwritten")
            self.assertEqual(out.read_bytes(), first)
            raw.write_text("not json", encoding="utf-8")
            self.assertEqual(rs.main(["--route", "users", "--server-version", "1", str(raw), str(Path(tmp, "x"))]), 2)


if __name__ == "__main__":
    unittest.main()
