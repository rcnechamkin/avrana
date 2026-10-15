"""Tier A (standard library): the artwork gateway's own guards, without HTTP."""
import unittest

from avrana_home.app import artwork
from avrana_home.contract import ArtworkResult, SectionState, Service

PNG = b"\x89PNG\r\n\x1a\n" + b"x"
REF = "jellyfin/primary/aaaa0000000000000000000000000001"


class _Recorder:
    service = Service.JELLYFIN

    def __init__(self):
        self.calls = []

    def fetch_artwork(self, principal, ref):
        self.calls.append((principal, ref))
        return ArtworkResult(SectionState.OK, "image/png", PNG)


class _Principal:
    pass


class GatewayGuardTests(unittest.TestCase):
    def test_no_principal_returns_none_and_never_reaches_an_adapter(self):
        adapter = _Recorder()
        self.assertIsNone(artwork.fetch(None, [adapter], REF))
        self.assertEqual([], adapter.calls)

    def test_a_bad_ref_returns_none_and_never_reaches_an_adapter(self):
        adapter = _Recorder()
        for ref in ("", "jellyfin", "jellyfin/primary/../x", "jellyfin/primary/a%2fb", "https://x/y/z"):
            self.assertIsNone(artwork.fetch(_Principal(), [adapter], ref), ref)
        self.assertEqual([], adapter.calls)

    def test_an_unknown_service_returns_none_and_a_valid_call_passes_through(self):
        adapter = _Recorder()
        self.assertIsNone(artwork.fetch(_Principal(), [adapter], "komga/book/AbC123"))
        self.assertEqual([], adapter.calls)
        principal = _Principal()
        out = artwork.fetch(principal, [adapter], REF)
        self.assertEqual("image/png", out.content_type)
        self.assertEqual([(principal, REF)], adapter.calls)


if __name__ == "__main__":
    unittest.main()
