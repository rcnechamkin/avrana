#!/usr/bin/env python3
"""A mock Komga on 127.0.0.1, serving the repository's SYNTHETIC fixtures (tests/fake_komga.py, loaded by
path, read-only). Same server, modes and control routes as `mock_audiobookshelf` (ok, slow, down, 500,
malformed; `POST /__mock/mode/<mode>`); the key is expected in `X-API-Key`. Not Komga.

    python dev/mock_komga.py --port 18098 --mode ok
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))
from dev.mock_audiobookshelf import MODES, MockAudiobookshelf, load_fake   # noqa: E402

FakeKomga = load_fake("fake_komga.py", "FakeKomga")


class MockKomga(MockAudiobookshelf):
    FAKE = staticmethod(lambda: FakeKomga())
    MALFORMED = b'{"content": [{"id": "BOOKAAAA'
    NAME = "komga"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=18098)
    ap.add_argument("--mode", default="ok", choices=MODES)
    args = ap.parse_args(argv)
    with MockKomga("127.0.0.1", args.port, args.mode) as mock:
        print(f"mock Komga: {mock.url} (SYNTHETIC)", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
