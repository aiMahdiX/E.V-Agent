#!/usr/bin/env bash
# Backward-compatible entry point for the optional Voice & Live setup wizard.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python3 ]; then
  echo "Run ./setup.sh first to create E.V.'s virtual environment." >&2
  exit 1
fi

exec .venv/bin/python3 -m voice.setup