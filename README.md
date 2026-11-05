# Subtitle Studio — MVP local para Apple Silicon

Transcripción, traducción al español, edición por segmento y exportación SRT/VTT. Frontend Nginx, API FastAPI, worker RQ, PostgreSQL y Redis ejecutan en Docker. Qwen3-ASR y su alineador ejecutan con **MLX/Metal nativo en macOS**; Ollama también es nativo.

## Preparación y arranque

Requisitos: macOS Apple Silicon, Docker Desktop en ejecución, Python 3.12, FFmpeg y Ollama. `setup.sh` puede instalar Python/FFmpeg con Homebrew si faltan. Se necesita espacio para vídeos y pesos; la primera descarga requiere Internet.

Desde este checkout:

```bash
bash scripts/setup.sh
# Instala/abre Ollama desde https://ollama.com/download/mac si falta.
# Descarga a disco el modelo configurado; esto no lo precarga en memoria:
ollama pull qwen3:14b-q8_0

# Instala una vez el gateway como servicio del usuario de macOS.
# macOS lo activa bajo demanda y lo apaga tras 10 minutos sin actividad.
python3 scripts/install-mac-service.py

# Infraestructura Docker
docker compose up -d --build --wait
```

Abre [Subtitle Studio](http://localhost:3000). Pulsa **Abrir archivo local** y selecciona el original en el diálogo nativo de macOS. El vídeo no se copia ni se envía a servicios externos. Elige una fuente: transcribir una pista de audio concreta, un subtítulo vecino/en `Subs` o `Subtitles`, o una pista de texto incrustada. Al elegir un subtítulo se muestra la pista completa para identificarla aunque no tenga idioma; pulsa una línea para ir a ese momento y verla sobre el vídeo. La primera acción es **Ver subtítulos**, sin iniciar procesamiento para pistas existentes. Selecciona la pista de audio en **Audio del vídeo** y usa los controles del vídeo para reproducirla; el control **Volumen** ajusta esa pista. FFmpeg genera el audio localmente al vuelo, sin copiar el original. Para revisar antes de traducir, elige **Editar o mejorar**; cuando estén disponibles los segmentos, puedes editarlos o pulsar **Mejorar transcripción**, y después **Traducir pendientes**. Importar subtítulos existentes conserva sus tiempos y evita ASR; revisar sin pulsar Mejora evita también Ollama. Si eliges audio y **Ver subtítulos**, primero se transcribe y el resultado aparece en modo lectura, con opciones para editar o traducir después. Las pistas de audio elegidas se decodifican a memoria para MLX sin copiar el vídeo. Puedes previsualizar el vídeo mientras se procesa, si el navegador admite el formato. Los segmentos que ya existen se muestran en modo lectura durante la traducción y mejora; la transcripción inicial aparece al finalizar ASR. **Guardar junto al vídeo** escribe el SRT/VTT en la carpeta del original con un nombre nuevo si ya existe; **Descargar** usa el navegador. Los proyectos antiguos sin ruta original conservada solo permiten descargar. Los proyectos fallidos permiten recuperar los originales, exportar el trabajo parcial y **Reintentar pendientes**. El reintento conserva textos, tiempos y traducciones guardadas; solo traduce las entradas vacías. No usar `rq requeue` directamente: la recuperación debe pasar por la interfaz o `POST /api/projects/{id}/retry`.

Para detener los contenedores: `bash scripts/stop.sh`. El script usa `docker compose stop`: conserva contenedores, base de datos, cola y medios. El registro del gateway en launchd y Ollama son independientes. launchd conserva el puerto y arranca el gateway cuando recibe una petición; el proceso termina tras 10 minutos sin peticiones activas. Las transcripciones y reproducciones en curso no cuentan como inactividad. Para detener el servicio nativo hasta el próximo inicio de sesión, ejecuta `launchctl bootout gui/$(id -u)/com.subtitle-studio.gateway`; vuelve a iniciarlo con `python3 scripts/install-mac-service.py`. Sus registros están en `~/Library/Logs/subtitle-studio-gateway.err.log` y `subtitle-studio-gateway.out.log`. Evita detener mientras se procesa un trabajo; un proceso terminado abruptamente puede requerir revisar el estado en BD/RQ antes de recuperarlo.

## Configuración

`setup.sh` crea `.env` con secretos aleatorios y permisos `0600` **solo si no existe**. No cambia contraseñas existentes. Si se copió `.env.example` manualmente, sustituye ambos `CHANGE_…` antes de arrancar. Usa una contraseña de BD alfanumérica/URL-safe; si contiene caracteres reservados de URL hay que codificarlos en la URL de conexión. No cambies la contraseña de un volumen PostgreSQL ya inicializado sin planificar su rotación.

| Variable | Predeterminado / uso |
| --- | --- |
| `DB_PASSWORD` | Secreto generado; PostgreSQL y API/worker |
| `MAC_TOKEN` | Secreto generado; autenticación `X-Worker-Token` |
| `TRANSLATION_MODEL` | `qwen3:14b-q8_0`; preparar con `ollama pull` |
| `ASR_MODEL` | `Qwen/Qwen3-ASR-1.7B` |
| `ALIGNER_MODEL` | `Qwen/Qwen3-ForcedAligner-0.6B` |
| `FRONTEND_PORT` | `3000`; publicación solo en `127.0.0.1` |
| `MAC_PORT` | `8765`; gateway y URL usada desde Docker |
| `MAC_URL` | Override opcional de `http://host.docker.internal:${MAC_PORT}` |
| `STUDIO_DATA_DIR` | `./data`; misma carpeta en gateway y contenedores |
| `OLLAMA_URL` | `http://127.0.0.1:11434`; solo lo consume el gateway nativo |
| `MAC_BIND_HOST` | `0.0.0.0` para permitir acceso desde Docker Desktop |

El gateway lee `.env` como datos mediante python-dotenv, sin ejecutarlo como shell. Variables exportadas en la terminal prevalecen; usa los mismos valores en ambas terminales. Un cambio en frontend/API requiere `docker compose up -d --build`.

La acción opcional **Mejorar transcripción** pide a Ollama corregir mayúsculas y puntuación del texto original sin cambiar los tiempos. Conserva una instantánea previa y ofrece **Revertir última mejora**; rechaza la reversión si sobrescribiría una edición posterior. Revisa las propuestas: un modelo puede cambiar palabras o sentido. Las traducciones existentes no se actualizan automáticamente. La operación usa el modelo local y puede tardar.

## Modelos bajo demanda y memoria

- Arrancar la web o el gateway no descarga ni carga pesos.
- La primera transcripción crea `Session` y `ForcedAligner` de `mlx-qwen3-asr==0.4.4`; descarga los pesos ausentes a la caché local de Hugging Face. La agrupación de palabras en subtítulos usa el formateador de esa versión.
- Carga, inferencia y liberación MLX ocurren en **un único hilo**. La sesión y el alineador se reutilizan. Tras **600 segundos desde el fin del último uso**, el barrido (cada segundo) elimina sus referencias, ejecuta GC y vacía la caché Metal. No interrumpe una inferencia en marcha. Los pesos siguen en disco.
- Ollama recibe `keep_alive: "10m"` en cada generación y gestiona su descarga de memoria. Debe tener el modelo descargado previamente; no se sustituye por un servicio Docker.
- El despliegue previsto tiene un worker RQ; el gateway serializa ASR. En modo launchd el gateway se activa al recibir una conexión y se apaga tras 10 minutos sin actividad; el puerto queda reservado por macOS. No activar múltiples procesos Uvicorn: duplicarían los modelos.

Referencias: [API de sesión MLX](https://github.com/moona3k/mlx-qwen3-asr/blob/v0.4.4/mlx_qwen3_asr/session.py), [agrupación SRT](https://github.com/moona3k/mlx-qwen3-asr/blob/v0.4.4/mlx_qwen3_asr/writers.py), [Ollama keep_alive](https://docs.ollama.com/api/generate).

## Datos y límites

- Los nuevos proyectos guardan solo una referencia `data/<UUID>/source.json`; el vídeo original debe permanecer accesible en su ubicación. Las copias de proyectos anteriores se conservan en `data/<UUID>/`; PostgreSQL en `pgdata`; Redis con AOF en `redisdata`. Un fallo de cola tras persistir el proyecto conserva el medio y registra un error recuperable. Cada lote traducido se guarda por separado.
- **Quitar de biblioteca** y **Vaciar biblioteca** mueven los proyectos a la papelera recuperable; los trabajos activos se mantienen visibles. Se conservan las entradas, originales, datos y copias. **Papelera** permite restaurar uno o todos. No hay migraciones destructivas ni borrado definitivo de proyectos desde la UI. `create_all` inicializa tablas sin sustituir datos. No ejecutar `docker compose down -v`, `docker volume prune` ni borrar `data/` para resolver fallos.
- UI/API son locales, sin autenticación de usuarios. No exponerlas a Internet. El gateway escucha en todas las interfaces por compatibilidad con Docker: protege el puerto mediante firewall/red de confianza y conserva el token en secreto. Ollama puede permanecer en loopback.
- Abrir un original por referencia no tiene el límite de subida de 2 GiB. La API de subida anterior sigue disponible para compatibilidad, conserva ese límite y sí crea una copia local. RQ limita el trabajo a cuatro horas; cada lote de traducción tiene un timeout de 900 s. La cancelación del cliente/RQ no cancela necesariamente una inferencia nativa ya iniciada.
- Mientras se procesa, la edición se bloquea para evitar sobrescrituras. Al entrar en una fila de subtítulo el vídeo salta a su mark-in sin comenzar a reproducirse. Cada campo se guarda al salir de él; Deshacer/Rehacer conserva el historial durante la sesión del proyecto. La UI protege selección, exportación y cierre con cambios pendientes y permite reintentar si falla el guardado. Si una fila ha cambiado en otra pestaña, se rechaza el guardado y se conserva el texto editado para que puedas copiarlo y revisar el conflicto; no hay fusión automática.
- No incluye diarización, waveform, división/unión, historial persistente de edición, reglas editoriales CPS/CPL ni quemado de subtítulos en vídeo. Se importan pistas incrustadas de texto; PGS/VobSub y otras pistas de imagen necesitan OCR, aún no implementado. La compatibilidad de reproducción depende de los códecs del navegador, aunque FFmpeg pueda transcribir el archivo.
- Redis AOF `everysec` tolera reinicios normales, pero no equivale a una cola transaccional con PostgreSQL: queda una ventana entre commit y enqueue ante una caída abrupta. No hay reconciliación automática de trabajos abandonados. Conserva y revisa BD, cola y logs antes de recuperar manualmente un proyecto atascado.

## Diagnóstico y pruebas

```bash
docker compose ps
docker compose logs -f api worker
curl http://localhost:3000/api/health
mac-worker/.venv/bin/mlx-qwen3-asr --doctor
curl http://127.0.0.1:11434/api/tags
curl http://127.0.0.1:11434/api/ps

# Tests sin modelos ni Docker; SQLite/archivos temporales aislados
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
npm ci # Node.js para pruebas de frontend
bash scripts/test.sh

# Integración con Docker real e inferencia simulada; requiere 13000/18765 libres
.venv/bin/python scripts/smoke.py
```

`/api/health` comprueba BD y Redis; no carga modelos ni implica que Ollama esté disponible. `/health` del gateway requiere el token y tampoco precarga modelos. La prueba smoke crea un proyecto Compose único, verifica fallo/reintento, procesamiento, edición, exportación, rangos de medios y reinicio de BD/Redis. Detiene sus contenedores al terminar y **conserva** los volúmenes y la carpeta temporal que imprime para revisión.

Flujo de originales y subtítulos asociados: [archivos locales](docs/LOCAL-FILES.md).

Resultados y límites de validación: [informe del MVP](docs/MVP-VALIDATION.md).

## Colaboración y Git

`origin`: [fedeblock/subtitle-studio](https://github.com/fedeblock/subtitle-studio). Trabajar en ramas `feature/*` o `fix/*` y revisar mediante pull requests antes de integrar en `main`. El trabajo de esta revisión está en `feature/mvp-setup`. Los historiales iniciales local y remoto se integraron con un merge que conserva ambas raíces; no se reescribió ni se forzó un push. Credenciales, medios, datos, entornos virtuales y cachés de modelos están excluidos de Git.
