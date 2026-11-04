# Subtitle Studio — MVP local para Apple Silicon

Editor de subtítulos originales y traducidos al español con API, procesador en cola y exportación SRT/VTT. Frontend, API, Redis y PostgreSQL en Docker; inferencia MLX + Ollama ejecutada **nativamente en el Mac** para poder utilizar Metal.

## Requisitos

- macOS Apple Silicon (probado conceptualmente para Mac Studio M1 Ultra / 64 GB; **no probado físicamente en ese equipo**)
- Docker Desktop, Homebrew, Ollama, Python 3.12, FFmpeg
- Espacio libre para los modelos y vídeos; conexión para descargarlos la primera vez

## Instalación

```bash
# En Terminal, dentro de la carpeta subtitle-studio
bash scripts/setup.sh
ollama pull qwen3:14b-q8_0
```

El instalador crea `.env` con contraseñas aleatorias e instala el gateway MLX en un entorno virtual. Instala Ollama si aún no lo tienes (https://ollama.com/download/mac) y **abre la aplicación**. Si macOS solicita permisos de red entrante para Python, autoriza solo en una red de confianza; el gateway se escucha en el puerto 8765 para que Docker pueda contactar con él.

**Terminal 1:**

```bash
bash scripts/start-mac.sh
```

**Terminal 2:**

```bash
docker compose up -d --build
docker compose logs -f worker
```

Visita **http://localhost:3000**. Sube un vídeo o audio. Cuando termine la transcripción y traducción, podrás editar cada subtítulo y exportar `.srt`/`.vtt`.

Detener: `bash scripts/stop.sh` y Ctrl+C en Terminal 1.

## Esquema de ejecución y memoria

- **MLX**: una ejecución CLI nativa por trabajo; carga modelos al iniciar el proceso y los libera al terminar. **No conserva 10 minutos en memoria en este MVP**: requiere un servidor de sesión persistente y pruebas específicas de su API. En la primera ejecución descarga los modelos ASR y alineador a caché.
- **Ollama**: cada petición usa `keep_alive: "10m"` para liberar su traductor tras ~10 minutos sin solicitudes. Ollama permanece como servicio nativo.
- El worker procesa una tarea por vez. La traducción se realiza en lotes de 6 segmentos y se persiste cuando todos finalizan; se pueden recuperar los originales en la BD antes de finalizar la traducción.

## Protección y límites

- Interfaz y API expuestas únicamente a localhost (`127.0.0.1:3000`), sin autenticación de usuarios. **No publicar en Internet ni abrir puertos con redirección** sin añadir autenticación, CSRF, cuotas y controles adicionales.
- Gateway nativo usa token aleatorio en `X-Worker-Token`; el puerto 8765 debe quedar limitado por firewall a tu equipo. Para una instalación endurecida, se recomienda un socket Unix o túnel local, no una interfaz `0.0.0.0`.
- El límite de carga es 2 GB; para vídeos muy grandes, implementar upload reanudable y almacenamiento incremental. No hay borrado desde UI todavía.
- El parser conserva los segmentos del ASR. El editor permite editar texto y dos tiempos por fila, pero no incluye aún división/unión, undo/redo, waveform, diarización o control CPS automático.
- Los subtítulos de idioma original se pueden descargar antes de una traducción completada mediante la API (`/api/projects/{id}/export?language=original`).
- La traducción puede requerir revisión humana para preservar intención, modismos y duración de lectura.

## Depuración

```bash
docker compose ps
docker compose logs -f api worker
curl http://localhost:3000/api/health
# diagnóstico ASR
mac-worker/.venv/bin/mlx-qwen3-asr --doctor
# Ollama
curl http://127.0.0.1:11434/api/tags
```

Si el gateway falla en `mlx-qwen3-asr`, verifica la versión con `--help`. El CLI y su soporte de SRT se basan en la documentación del repositorio [moona3k/mlx-qwen3-asr](https://github.com/moona3k/mlx-qwen3-asr). Ollama documenta `keep_alive` en https://docs.ollama.com/api/generate.

## Próximas mejoras

1. Segmentación editorial CPS/CPL y controles de calidad, re-traducción por segmento y progreso incremental.
2. Forma de onda y timeline interactivo, división/unión, historial de cambios y subtítulos incrustados.
3. Sesiones MLX persistentes con temporizador de 10 minutos, monitorización de memoria y pruebas automatizadas en Apple Silicon.

## Colaboración

Trabajar en ramas `feature/*` o `fix/*` y revisar mediante pull requests antes de integrar en `main`. No versionar credenciales, datos ni modelos.
