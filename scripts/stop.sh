#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose stop
printf 'Contenedores detenidos; datos, volúmenes y cola conservados.\n'
printf 'Detén el gateway con Ctrl+C en su terminal; Ollama es independiente.\n'
