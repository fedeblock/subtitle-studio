#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env || ! -x mac-worker/.venv/bin/python ]]; then
  echo 'Ejecuta primero: bash scripts/setup.sh' >&2; exit 1
fi
exec mac-worker/.venv/bin/python mac-worker/launch.py
