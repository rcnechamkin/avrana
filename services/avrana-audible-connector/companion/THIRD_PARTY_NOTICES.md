# Third-Party Notices — Avrana Libation Companion

This service is built on top of, and invokes, third-party software. It does not modify their
source; it runs the shipped `LibationCli` as a separate process and adds a thin HTTP adapter.

## Libation
- Project: https://github.com/rmcrackan/Libation
- License: GPL-3.0-or-later (see `LICENSES/Libation-GPL-3.0.txt`).
- Distributed here as the container image `rmcrackan/libation` pinned by digest
  `sha256:a1b4a10150d785ddbb3359ccb0cfd089abd2a462330d30ffb68b638e8d3ad6d6` (v13.7.7),
  the same digest already deployed on this host. The image is used unmodified; only
  additional packages (python3, FastAPI, uvicorn) and this adapter are layered on top.

## Design inspiration
- The companion HTTP surface is adapted in spirit from Shelfarr's `libation_companion`
  (https://github.com/Pedro-Revez-Silva/shelfarr, `services/libation_companion`), MIT/Apache
  per that repository's LICENSES. This is an independent reimplementation in Python that adds
  per-account profile isolation and an idempotent `/v1/revoke` operation; no Shelfarr source
  code is copied here. If any Shelfarr source is later vendored, retain its license header.

## This adapter
- `api/companion.py` and the Dockerfile in this directory are part of the Avrana repository
  and inherit its MIT license, EXCEPT where they interact with GPL-3.0 Libation at runtime as
  a separate process (arm's-length invocation, not linking).
