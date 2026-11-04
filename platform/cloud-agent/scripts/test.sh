#!/bin/sh
# Local test entry point.  Run from anywhere; no network or credentials needed.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
exec python3 -m unittest discover -s tests -t . -v
