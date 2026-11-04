#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  cp .env.example .env
  python3 - <<'PY2'
from pathlib import Path
import secrets
p=Path('.env');s=p.read_text().replace('CHANGE_DB_PASSWORD',secrets.token_urlsafe(28)).replace('CHANGE_MAC_TOKEN',secrets.token_urlsafe(36));p.write_text(s)
PY2
fi
mkdir -p data
if ! command -v brew >/dev/null; then echo 'Instala Homebrew primero: https://brew.sh'; exit 1; fi
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg
"$(brew --prefix python@3.12)/bin/python3.12" -m venv mac-worker/.venv
mac-worker/.venv/bin/pip install -r mac-worker/requirements.txt
printf '\nListo. Instala Ollama y ejecuta: ollama pull qwen3:14b-q8_0\n'
