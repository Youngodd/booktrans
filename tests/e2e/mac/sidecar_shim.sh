#!/bin/sh
# Use as BOOKTRANS_SIDECAR so the real shell (booktrans.desktop.shell) starts the test shim instead of the plain sidecar.
# Needs REPO set to the repository root.
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "${REPO:?set REPO}/.venv/bin/python" "$DIR/shim.py" "$@"
