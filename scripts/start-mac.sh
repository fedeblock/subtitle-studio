#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then echo 'Falta .env: cp .env.example .env'; exit 1; fi
set -a; source .env; set +a
if [[ ! -x mac-worker/.venv/bin/python ]]; then echo 'Instala primero mac-worker/.venv según README'; exit 1; fi
export STUDIO_DATA="$PWD/data" STUDIO_TOKEN="$MAC_TOKEN"
export STUDIO_TRANSLATION_MODEL="${TRANSLATION_MODEL:-qwen3:14b-q8_0}"
exec mac-worker/.venv/bin/uvicorn server:app --app-dir mac-worker --host 0.0.0.0 --port 8765
