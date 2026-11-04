#!/usr/bin/env bash
cd "$(dirname "$0")/.."
docker compose down
printf 'Docker detenido. Detén el gateway con Ctrl+C en su terminal; Ollama es independiente.\n'
