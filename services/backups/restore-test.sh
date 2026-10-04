#!/usr/bin/env bash
# Kept for the old name. The restore test is restore-test.py; see its header and README.md.
exec python3 "$(dirname "$(readlink -f "$0")")/restore-test.py" "$@"
