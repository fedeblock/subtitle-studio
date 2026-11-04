# Revisión y validación del MVP

Fecha: 4 de noviembre de 2026 (Europe/Madrid). Directorio: `/Users/federico/Desarrollo/subtitle-studio`. Rama de trabajo: `feature/mvp-setup`.

## Git y preservación

- Inicio: rama `main`, árbol limpio, commit local `c84030a`; sin remotos. `data/` contenía únicamente `.gitkeep`; no existía `.env`.
- `origin` configurado como `https://github.com/fedeblock/subtitle-studio.git` y consultado con fetch.
- Remoto: `10e5eec` y `60c786b`, con raíz independiente del MVP local.
- Merge `610e3c1`: conserva ambas raíces y resuelve los conflictos add/add de README y `.gitignore`, uniendo exclusiones e instrucciones de colaboración.
- `main` local y remoto no se modificaron. No se ejecutó push, force-push, reset destructivo ni borrado de volúmenes.
- `.env` generado con secretos aleatorios y permisos 0600; fuera de Git. Una segunda ejecución de inicialización conservó exactamente su contenido. Se crearon entornos virtuales locales ignorados.

## Cambios y motivos

| Área | Fallo comprobado | Resultado |
| --- | --- | --- |
| Upload | Fallo al encolar borraba el medio después del commit | Medio/proyecto conservados, estado failed y HTTP 503 recuperable |
| Validación | Aceptaba uploads vacíos y tiempos infinitos | HTTP 400 para vacío; validación de tiempos finitos y orden |
| Edición | API permitía editar durante traducción | HTTP 409 durante procesamiento; bloqueo de fila en edición/reintento |
| Worker | Reprocesaba duplicados y sustituía cues | Reclamación atómica solo desde queued; ready no se reprocesa |
| Traducción | Todos los lotes se persistían al final | Cada lote se guarda; un fallo posterior conserva el trabajo |
| Recuperación | No había transición segura para volver a encolar | API y botón Reintentar pendientes; solo traduce entradas vacías |
| MLX | CLI por trabajo liberaba inmediatamente los modelos | Session + alineador explícitos, un hilo, retención de 600 s y limpieza Metal |
| Gateway | Un enlace simbólico podía escapar de data/ | Validación de carpeta y destino real; autenticación también en health |
| Frontend | Respuestas tardías reemplazaban selección/ediciones | Revisión de selección y dirty/busy al recibir respuestas |
| Tiempos UI | Redondeo producía 00:00:60.000 | Cálculo por milisegundos y validación de componentes |
| Docker | Redis efímero, dependencias solo por orden, frontend montado | AOF/volumen, healthchecks y frontend con Dockerfile propio |
| Scripts | `.env` se ejecutaba mediante source | Lectura de dotenv como datos; configuración conservadora y stop sin borrar |
| Configuración | MAC_PORT no se propagaba al worker | Interpolación coherente en MAC_URL; probado con puerto alternativo |

## Evidencia ejecutada

- **21 pruebas Python**, todas verdes. SQLite y uploads en directorios temporales, sin usar BD ni medios reales. Incluyen cola caída, vacío, exportación/media, tiempos, edición concurrente con worker, reintentos, lotes parciales, duplicados, token, symlinks, traducción inválida, carga perezosa, reutilización, expiración a 600 s, recarga y afinidad de hilo.
- **4 pruebas Node**, todas verdes: redondeo, campos de tiempo inválidos, respuestas de selección fuera de orden y polling que llega tras empezar a editar.
- `node --check frontend/app.js`, `bash -n`, `docker compose config --quiet`, Ruff sobre Python modificado y `git diff --check`.
- `pip check` en los entornos backend/test y mac-worker: sin dependencias rotas. `setup.sh` completo repetido correctamente sobre el entorno instalado, conservando `.env` y sin descargar pesos.
- Construcción correcta de imágenes frontend, API y worker. Arranque con **los cinco servicios healthy**.
- Smoke Docker con Nginx, FastAPI, PostgreSQL, Redis y worker RQ reales. Solo el servidor de inferencia usa respuestas deterministas. Se comprueba: WAV → cola → fallo de traducción HTTP 503 → estado failed → retry → ready → edición → exportación SRT/VTT. También HTTP 206 para rangos, rechazo de vacío y persistencia de BD/Redis tras reiniciarlos.
- Navegador: biblioteca y editor del proyecto smoke visibles, original y traducción recuperados; sin errores de consola. Inspección visual de escritorio, sin una matriz completa de móviles/códecs.
- Equipo confirmado: **Apple M1 Ultra**. MLX 0.32.4 / mlx-qwen3-asr 0.4.4 instalados; Metal disponible y operación real de arrays verificada (`[2, 4, 6]`). Firmas Session/ForcedAligner y agrupación SRT verificadas contra la biblioteca instalada.
- `mlx-qwen3-asr --doctor`: OK; dos avisos de diarización opcional (extras/token ausentes). La diarización queda fuera del MVP.
- Gateway nativo arrancado y detenido en `127.0.0.1:18766`; `/health` autenticado correcto, idle_seconds=600, sin cargar pesos.
- Revisión independiente de código: dos hallazgos corregidos (recuperación segura y MAC_PORT). Cada corrección de recuperación tiene prueba de regresión; el puerto se verifica con Compose renderizado.

Comandos reproducibles en README y `scripts/test.sh` / `scripts/smoke.py`.

## Artefactos de la sesión

Solo se detienen contenedores creados para estas pruebas. El proyecto Docker preexistente `mapbox` no se modifica.

| Ejecución | Proyecto Compose | Datos conservados |
| --- | --- | --- |
| Smoke inicial | `subtitle-studio-mvp-check` | `/var/folders/hn/95yv2d917_ndgz0vrlpkh3gm0000gn/T/subtitle-studio-smoke-nln9pt4n` |
| Smoke con fallo/reintento y revisión UI | `subtitle-studio-check-lm2bs_56` | `/var/folders/hn/95yv2d917_ndgz0vrlpkh3gm0000gn/T/subtitle-studio-smoke-lm2bs_56` |

Se conservan sus volúmenes `pgdata` y `redisdata` con prefijo del proyecto. Los contenedores de pruebas quedan detenidos al finalizar. Logs de esta sesión en `/tmp/studio-docker-build.log`, `/tmp/studio-smoke.log`, `/tmp/studio-smoke-final.log` y `/tmp/studio-native-gateway.log`. Estos logs y las carpetas temporales no forman parte del repositorio y el sistema puede limpiarlos posteriormente.

## Límites y pendientes

1. **No se realizó inferencia real con pesos Qwen3-ASR/Ollama**. Ollama no apareció en PATH ni en las ubicaciones de aplicación comprobadas, y su puerto 11434 no respondió. No se instaló globalmente ni se descargaron modelos. La prueba Metal no acredita precisión ASR/traducción, latencia ni consumo máximo de memoria.
2. La retención/expiración de MLX está probada con reloj controlado y sustitutos del modelo. Falta medir la liberación física de memoria con pesos reales después de diez minutos y comprobar el keep_alive efectivo de Ollama bajo carga.
3. No se probaron archivos de 2 GiB, vídeos de varias horas ni apagado abrupto durante inferencia. Un worker terminado por fuerza o un fallo entre commit y enqueue puede dejar estado atascado. No existe reconciliación automática; revisar cola/BD antes de recuperar. La inferencia nativa en marcha no tiene cancelación coordinada.
4. Se conserva un aviso de deprecación de Starlette/AnyIO en TestClient; la suite pasa. No se ampliaron actualizaciones de framework fuera de esta revisión.
5. UI local sin autenticación multiusuario y gateway accesible a la red con token; no es un despliegue público. No hay historial/versiones por cue entre pestañas.
6. Siguiente validación operativa: instalar/abrir Ollama, preparar el modelo configurado, ejecutar un clip conocido con voz, revisar alineación/traducción y medir memoria antes/después de los 600 s. No confundir descarga de pesos a disco con carga de modelos en memoria.
