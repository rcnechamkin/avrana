"""Regression tests for the companion's Libation export mapping.

These pin `_normalize_export` against the REAL `LibationCli export -j` schema (v13.7.7),
captured 2026-08-14 from the admin Libation instance's populated library and sanitized into
`fixtures/libation_export_v13.7.7.json` (fake ASINs/titles/authors/account, real field names,
real ownership flags). No Audible account is involved — `export` is a local read of
Libation's own database.

Why these exist: the original mapping was written defensively against guessed key names and
got the two that matter wrong. It looked for `Authors`/`Narrators` (real: `AuthorNames`/
`NarratorNames`) and derived Audible Plus from `ContentType` containing "plus"/"ayce" — but
real `ContentType` is "Product" for owned AND Plus titles, so every Plus title was reported
as a purchase. In the live library that was 22 of 211 titles offered as downloadable when
they are not owned.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "libation_export_v13.7.7.json"
COMPANION_PY = (
    Path(__file__).resolve().parents[2] / "companion" / "api" / "companion.py"
)


def _load_companion():
    """Import the companion module by path — it lives outside the connector package."""
    spec = importlib.util.spec_from_file_location("companion_under_test", COMPANION_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def items():
    companion = _load_companion()
    return {i["asin"]: i for i in companion._normalize_export(json.loads(FIXTURE.read_text()))}


def test_all_records_survive_normalization(items):
    assert len(items) == 5, f"expected every fixture record to map, got {sorted(items)}"


def test_owned_purchase_is_purchasable(items):
    owned = items["B00FIXTUR1"]
    assert owned["isPurchased"] is True
    assert owned["isPlus"] is False
    assert owned["purchaseStatus"] == "purchased"


def test_audible_plus_title_is_never_purchasable(items):
    """The core regression: IsAudiblePlus is the ownership discriminator, not ContentType."""
    plus = items["B00FIXTUR3"]
    assert plus["isPlus"] is True
    assert plus["isPurchased"] is False, "a Plus title must never be offered as a purchase"
    assert plus["purchaseStatus"] == "plus"


def test_content_type_alone_cannot_classify_ownership(items):
    """Guards the exact mistake: owned and Plus records share ContentType 'Product'."""
    raw = {r["AudibleProductId"]: r for r in json.loads(FIXTURE.read_text())}
    assert raw["B00FIXTUR1"]["ContentType"] == raw["B00FIXTUR3"]["ContentType"] == "Product"
    assert items["B00FIXTUR1"]["isPurchased"] != items["B00FIXTUR3"]["isPurchased"]


def test_title_absent_from_account_is_not_purchasable(items):
    """AbsentFromLastScan = no longer in the account; licensing would fail."""
    assert items["B00FIXTUR4"]["isPurchased"] is False


def test_author_and_narrator_come_from_the_real_key_names(items):
    owned = items["B00FIXTUR1"]
    assert owned["author"] == "Fixture Author 1"
    assert owned["narrator"] == "Fixture Narrator 1"


def test_runtime_is_mapped(items):
    assert isinstance(items["B00FIXTUR1"]["runtimeMinutes"], int)


def test_cover_is_a_usable_url_not_a_bare_image_id(items):
    """The export carries Amazon image ids; the UI puts this straight into <img src>."""
    cover = items["B00FIXTUR1"]["coverUrl"]
    assert cover.startswith("https://"), f"cover must be a URL, got {cover!r}"
    assert "81FIXTURE1L" in cover


def test_pdf_flag_is_surfaced(items):
    assert items["B00FIXTUR2"]["hasPdf"] is True
    assert items["B00FIXTUR1"]["hasPdf"] is False


def test_hostile_picture_id_cannot_escape_the_url_template():
    companion = _load_companion()
    assert companion._cover_url({"PictureLarge": "../../evil"}) is None
    assert companion._cover_url({"PictureLarge": "a b/c?d=e"}) is None
    assert companion._cover_url({}) is None
    # An explicit URL is passed through unchanged.
    assert companion._cover_url({"PictureLarge": "https://example.invalid/x.jpg"}) == (
        "https://example.invalid/x.jpg"
    )


def test_unparseable_records_are_dropped_not_guessed():
    companion = _load_companion()
    out = companion._normalize_export(
        [{"AudibleProductId": "nope"}, {"no": "asin"}, "not-a-dict", {"AudibleProductId": ""}]
    )
    assert out == []
