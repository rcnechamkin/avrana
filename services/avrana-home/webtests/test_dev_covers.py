"""The dev mocks serve real, decodable SYNTHETIC covers in each kind's natural shape (so a review of the dev stack
shows real layout, not the browser's broken-image icon), and they still reach the page only through the
member-scoped /art/ route. Loopback only; images are generated in memory, nothing binary is committed."""
import re
import struct
import unittest
import zlib

from dev import synthetic_art
from dev.mock_audiobookshelf import MockAudiobookshelf
from dev.mock_calibre_web import MockCalibreWeb
from dev.mock_jellyfin import MockJellyfin
from dev.mock_komga import MockKomga

from .support import GROUPS, USER, make_client, make_settings, require_framework

require_framework()

EVERYTHING = "avrana-users|avrana-videos|avrana-audiobooks|avrana-comics|avrana-books"
A = [(USER, "member-a"), (GROUPS, EVERYTHING)]
CRED = "viewer:mock-api-key-not-real"


def decode_png(data: bytes):
    """(width, height) after checking every chunk CRC and that the pixel data inflates to exactly the size the
    header promises (8-bit truecolour, one filter byte per row): a browser can draw it."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG signature"
    pos, chunks = 8, {}
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        assert zlib.crc32(kind + body) & 0xFFFFFFFF == crc, f"bad CRC in {kind!r}"
        chunks.setdefault(kind, b"")
        chunks[kind] += body
        pos += 12 + length
    w, h, depth, colour = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (depth, colour) == (8, 2)
    assert len(zlib.decompress(chunks[b"IDAT"])) == h * (1 + 3 * w)
    assert b"IEND" in chunks
    return w, h


class SyntheticArt(unittest.TestCase):
    def test_every_shape_is_a_valid_png_of_its_natural_ratio(self):
        ratios = {"poster": 2 / 3, "book": 2 / 3, "square": 1.0, "still": 16 / 9, "comic": 13 / 20}
        for shape, ratio in ratios.items():
            w, h = decode_png(synthetic_art.cover(shape, "/x/" + shape))
            self.assertAlmostEqual(ratio, w / h, places=2, msg=shape)

    def test_colour_follows_the_seed_and_size_stays_small(self):
        self.assertNotEqual(synthetic_art.cover("poster", "a"), synthetic_art.cover("poster", "b"))
        self.assertLess(len(synthetic_art.cover("comic", "a")), 4096)


class MockCoversThroughTheArtRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jf, cls.ab, cls.kg, cls.cw = (MockJellyfin().start(), MockAudiobookshelf().start(),
                                          MockKomga().start(), MockCalibreWeb().start())

    @classmethod
    def tearDownClass(cls):
        for m in (cls.jf, cls.ab, cls.kg, cls.cw):
            m.stop()

    def test_each_service_cover_decodes_in_its_shape(self):
        c = make_client(make_settings(home_sections=True, jellyfin_base_url=self.jf.url,
                                      audiobookshelf_base_url=self.ab.url, audiobookshelf_token="mock-api-key-not-real",
                                      komga_base_url=self.kg.url, komga_token="mock-api-key-not-real",
                                      calibre_web_base_url=self.cw.url, calibre_web_credential=CRED, timeout=1.5))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        home = c.get("/", headers=A).text
        refs = dict.fromkeys(re.findall(r'<li class="w-([a-z]+)">(?:<a class="card"[^>]*>\s*)?<span class="frame">'
                                        r'<span class="ph"[^>]*>[^<]*</span><img class="art" src="(/art/[^"]+)"', home))
        shapes = set()
        for shape, src in refs:
            r = c.get(src, headers=A)
            self.assertEqual((200, "image/png"), (r.status_code, r.headers["content-type"]), src)
            w, h = decode_png(r.content)
            want = {"poster": 2 / 3, "book": 2 / 3, "square": 1.0, "still": 16 / 9, "comic": 13 / 20}[shape]
            self.assertAlmostEqual(want, w / h, places=2, msg=src)
            shapes.add(shape)
        self.assertGreaterEqual(len(shapes), 3, shapes)        # more than one natural shape on the page

    def test_a_test_can_still_serve_the_fakes_own_bytes(self):
        import urllib.request
        self.ab.synthetic_covers = False
        self.addCleanup(setattr, self.ab, "synthetic_covers", True)
        req = urllib.request.Request(self.ab.url + "/api/items/li_book000001/cover",
                                     headers={"Authorization": "Bearer mock-api-key-not-real"})
        with urllib.request.urlopen(req, timeout=3) as r:
            self.assertTrue(r.read().startswith(b"\xff\xd8\xff"))


if __name__ == "__main__":
    unittest.main()
