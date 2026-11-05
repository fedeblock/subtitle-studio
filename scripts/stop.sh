#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose stop
printf 'Contenedores detenidos; datos, volúmenes y cola conservados.\n'
printf 'El servicio nativo y Ollama siguen activos; consulta el README para detener el servicio.\n'
