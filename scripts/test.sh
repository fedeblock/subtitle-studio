#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m pytest "$@"
node --test tests/frontend.test.cjs
node --check frontend/app.js
bash -n scripts/setup.sh scripts/start-mac.sh scripts/stop.sh scripts/test.sh
