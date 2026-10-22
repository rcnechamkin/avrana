#!/usr/bin/env python3
"""A mock Calibre-Web (OPDS) on 127.0.0.1, serving the repository's SYNTHETIC fixture
(tests/fake_calibre_web.py, loaded by path, read-only). Same server, modes and control routes as
`mock_audiobookshelf` (ok, slow, down, 500, malformed); it expects HTTP Basic `viewer:<mock key>`.
Not Calibre-Web.

    python dev/mock_calibre_web.py --port 18099 --mode ok
"""
from __future__ import annotations

import argparse
import base64
import sys
import time
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))
from dev.mock_audiobookshelf import MODES, MOCK_KEY, MockAudiobookshelf, load_fake   # noqa: E402

FakeCalibreWeb = load_fake("fake_calibre_web.py", "FakeCalibreWeb")
EXPECTED_BASIC = base64.b64encode(("viewer:" + MOCK_KEY).encode()).decode()


class MockCalibreWeb(MockAudiobookshelf):
    FAKE = staticmethod(lambda: FakeCalibreWeb())
    MALFORMED = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>'
    NAME = "calibre-web"
    SHAPE = "book"

    def __init__(self, *a, **kw):
        kw.setdefault("api_key", EXPECTED_BASIC)
        super().__init__(*a, **kw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=18099)
    ap.add_argument("--mode", default="ok", choices=MODES)
    args = ap.parse_args(argv)
    with MockCalibreWeb("127.0.0.1", args.port, args.mode) as mock:
        print(f"mock Calibre-Web: {mock.url} (SYNTHETIC)", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
