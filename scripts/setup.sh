#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo 'La inferencia MLX necesita macOS Apple Silicon.' >&2; exit 1
fi
if ! command -v python3.12 >/dev/null || ! command -v ffmpeg >/dev/null; then
  if ! command -v brew >/dev/null; then echo 'Instala Homebrew: https://brew.sh' >&2; exit 1; fi
  command -v python3.12 >/dev/null || brew install python@3.12
  command -v ffmpeg >/dev/null || brew install ffmpeg
fi
python3.12 scripts/init-env.py
mkdir -p data
if [[ ! -x mac-worker/.venv/bin/python ]]; then
  python3.12 -m venv mac-worker/.venv
fi
mac-worker/.venv/bin/python -m pip install -r mac-worker/requirements.txt
printf '\nEntorno preparado. No se han descargado pesos.\n'
printf 'Abre Ollama y prepara el modelo configurado (por defecto: ollama pull qwen3:14b-q8_0).\n'
printf 'Después: python3 scripts/install-mac-service.py y docker compose up -d --build\n'
