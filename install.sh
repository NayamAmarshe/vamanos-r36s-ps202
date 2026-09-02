#!/usr/bin/env bash
# vamanOS for R36S PS202 - macOS / Linux launcher.
# Requires Python 3 and adb. See README.md.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  elif command -v python >/dev/null 2>&1 \
      && python -c 'import sys; raise SystemExit(sys.version_info[0] != 3)' >/dev/null 2>&1; then
    PYTHON=python
  else
    echo "Python 3 is required but was not found on PATH." >&2
    exit 2
  fi
fi

exec "$PYTHON" "$SCRIPT_DIR/vamanos_installer.py" "$@"
