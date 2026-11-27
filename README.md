# Subtitle Studio — MVP local para Apple Silicon

[![npm](https://img.shields.io/npm/v/subtitle-studio?logo=npm&label=npm)](https://www.npmjs.com/package/subtitle-studio)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)
![Status: MVP](https://img.shields.io/badge/status-MVP-orange)
![100% local](https://img.shields.io/badge/processing-100%25%20local-2ea44f)
![macOS Apple Silicon](https://img.shields.io/badge/macOS-Apple%20Silicon-000000?logo=apple&logoColor=white)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![Node 18.17+](https://img.shields.io/badge/node-%E2%89%A518.17-339933?logo=nodedotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/docker-supported-2496ED?logo=docker&logoColor=white)
![MLX](https://img.shields.io/badge/MLX-Metal-lightgrey)
![Qwen3-ASR](https://img.shields.io/badge/ASR-Qwen3--ASR-6F42C1)
![Ollama](https://img.shields.io/badge/LLM-Ollama-black)
![SRT · VTT](https://img.shields.io/badge/export-SRT%20%C2%B7%20VTT-informational)

Transcripción, traducción a un idioma de destino, edición por segmento y exportación SRT/VTT. Frontend Nginx, API FastAPI, worker RQ, PostgreSQL y Redis ejecutan en Docker. Qwen3-ASR y su alineador ejecutan con **MLX/Metal nativo en macOS**; Ollama también es nativo.

## Preparación y arranque

### Obtener el proyecto desde npm

Con Node.js 18.17 o posterior se puede preparar una copia nueva con:

```bash
npx subtitle-studio init mi-subtitle-studio
cd mi-subtitle-studio
```

El comando solo crea archivos en un directorio nuevo; no instala servicios ni descarga modelos. A continuación se requieren macOS con Apple Silicon y Docker, y se siguen los pasos de preparación de abajo. El funcionamiento, la reproducción y el procesamiento son locales.

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

Abre [Subtitle Studio](http://localhost:3000). Pulsa **Abrir archivo local** y selecciona el original en el diálogo nativo de macOS. El vídeo no se copia ni se envía a servicios externos. Elige una fuente: transcribir una pista de audio concreta, un subtítulo vecino/en `Subs` o `Subtitles`, o una pista de texto incrustada. Al elegir un subtítulo se muestra la pista completa para identificarla aunque no tenga idioma; pulsa una línea para ir a ese momento y verla sobre el vídeo. Las fuentes aparecen agrupadas por procedencia; elegir una pista muestra una vista previa sin iniciar procesamiento. **Usar esta fuente** abre los segmentos directamente en el editor. Selecciona la pista de audio en **Audio del vídeo** y usa los controles del vídeo para reproducirla; el control **Volumen** ajusta esa pista. FFmpeg genera el audio localmente al vuelo, sin copiar el original. En el editor puedes corregir los segmentos o pulsar **Mejorar transcripción**, y después **Traducir pendientes**. Importar subtítulos existentes conserva sus tiempos y evita ASR; revisar sin pulsar Mejora evita también Ollama. Si eliges transcribir el audio, el resultado se abre directamente en el editor. Las pistas de audio elegidas se decodifican a memoria para MLX sin copiar el vídeo. Puedes previsualizar el vídeo mientras se procesa, si el navegador admite el formato. Los segmentos que ya existen se muestran en modo lectura durante la traducción y mejora; la transcripción inicial aparece por tramos durante ASR y se puede previsualizar al avanzar. La elección opcional de idioma hablado orienta el reconocimiento; con varios idiomas puede utilizarse detección automática. **Guardar junto al vídeo** escribe el SRT/VTT en la carpeta del original con un nombre nuevo si ya existe; **Descargar** usa el navegador. Los proyectos antiguos sin ruta original conservada solo permiten descargar. Los proyectos fallidos permiten recuperar los originales, exportar el trabajo parcial y **Reintentar pendientes**. El reintento conserva textos, tiempos y traducciones guardadas; solo traduce las entradas vacías. No usar `rq requeue` directamente: la recuperación debe pasar por la interfaz o `POST /api/projects/{id}/retry`.

Para detener los contenedores: `bash scripts/stop.sh`. El script usa `docker compose stop`: conserva contenedores, base de datos, cola y medios. El registro del gateway en launchd y Ollama son independientes. launchd conserva el puerto y arranca el gateway cuando recibe una petición; el proceso termina tras 10 minutos sin peticiones activas. Las transcripciones y reproducciones en curso no cuentan como inactividad. Para detener el servicio nativo hasta el próximo inicio de sesión, ejecuta `launchctl bootout gui/$(id -u)/com.subtitle-studio.gateway`; vuelve a iniciarlo con `python3 scripts/install-mac-service.py`. Sus registros están en `~/Library/Logs/subtitle-studio-gateway.err.log` y `subtitle-studio-gateway.out.log`. Evita detener mientras se procesa un trabajo; un proceso terminado abruptamente puede requerir revisar el estado en BD/RQ antes de recuperarlo.

La transcripción de archivos locales se procesa en tramos de hasta 30 segundos. Cada tramo terminado y su punto de reanudación se guardan juntos; durante ASR los segmentos ya disponibles se pueden revisar y editar. Si se interrumpe, **Reintentar pendientes** continúa desde el último tramo guardado. Al transcribir se puede elegir un idioma hablado, o dejar la detección automática para contenido multilingüe. Qwen3-ASR admite rumano, pero Qwen3-ForcedAligner no lo incluye en su lista oficial de idiomas, por lo que conviene revisar los tiempos; los cortes entre tramos también pueden requerir revisión.

Durante una tarea, el panel de progreso muestra el audio ya procesado y, si el reproductor conoce la duración, su porcentaje; la traducción muestra los segmentos guardados sobre el total y la mejora, el porcentaje confirmado y el tiempo desde el último resultado recibido. Los indicadores se actualizan mientras la página está abierta. Las operaciones en cola o sin datos suficientes muestran actividad sin un porcentaje estimado.

El panel permite **Pausar**, **Reanudar** y **Cancelar tarea**. La pausa y la cancelación se hacen efectivas después de guardar el tramo o lote en curso; mientras tanto se muestra que la solicitud está pendiente y una llamada al modelo puede tardar en terminar. Al reanudar, solo se procesan los tramos o segmentos pendientes. Cancelar conserva los resultados guardados y el vídeo; una mejora parcial conserva también su copia para **Revertir última mejora**. Las tareas en cola se detienen inmediatamente.

Si el modelo produce texto pero no puede alinearlo, se conserva como un segmento con la duración aproximada del tramo y se muestra un aviso con su posición. Revisa tanto el texto como los tiempos: en tramos sin voz el modelo también puede producir texto inventado.

Si Whisper devuelve marcas que exceden la duración del audio decodificado, se ajustan al tramo y se señala su posición para revisión. El punto de reanudación y los subtítulos se confirman juntos, de modo que un error posterior no vuelve a transcribir ni sobrescribe los tramos ya guardados.

Ante un error temporal de conexión o una respuesta temporal del servicio, el worker reintenta hasta tres veces la misma petición, esperando 2, 4 y 8 segundos entre intentos. Esto se aplica a la transcripción, la traducción y la mejora; los datos ya guardados se conservan. Los errores de configuración o solicitudes inválidas se muestran sin reintentos. Si se agotan, el proyecto queda en estado fallido y **Reintentar pendientes** permite continuarlo desde el último punto guardado.

Al elegir transcribir se puede seleccionar **Qwen3-ASR 1.7B** o **Whisper large-v3**. Los modelos se descargan a la caché local de Hugging Face cuando se necesitan; Whisper ocupa aproximadamente 3,1 GB. En **Audio y modelos**, junto al reproductor, se puede consultar el espacio utilizado, descargar o verificar los archivos y borrar el modelo elegido. La caché puede compartirse con otras aplicaciones: borrar un modelo también lo elimina para ellas, tras una confirmación. No se borran vídeos ni subtítulos.

En un proyecto terminado o fallido, **Volver a transcribir** abre un proyecto nuevo que apunta al mismo vídeo y permite elegir de nuevo la pista de audio, el idioma y el modelo. La transcripción, las ediciones y la traducción anteriores quedan en el proyecto original; el vídeo no se duplica.

Al seleccionar una pista o archivo de subtítulos, su vista previa aparece debajo de una lista de fuentes desplazable. Si el vídeo está pausado al principio y no hay subtítulo en ese instante, la aplicación va a la primera línea para mostrarla sobre la imagen sin reproducir automáticamente. Si ya estabas viendo otro momento, conserva esa posición; al seleccionar cualquier línea de la tabla, el vídeo salta a su marca de entrada.

La flecha **→** entre los textos traduce ese segmento al idioma elegido en el encabezado de la columna. El botón **⋮**, o el botón derecho sobre la flecha, abre las opciones avanzadas, incluida la traducción inversa. El menú se cierra al hacer clic fuera o al desplazar la lista. Se puede usar durante la transcripción y en el editor; los cambios se guardan y se pueden deshacer durante la sesión. Si el campo de destino ya contiene texto, se pide confirmación antes de reemplazarlo. **Traducir pendientes** procesa en lote los segmentos sin traducción en el idioma elegido para el proyecto.

En ese mismo menú, **Comparar modelos de Ollama** permite elegir dos modelos ya instalados y comparar sus traducciones del mismo segmento, dirección e idioma. Se ejecutan uno después del otro y los tiempos incluyen la carga. Los resultados no modifican el proyecto hasta pulsar **Usar este resultado**; esa elección se puede deshacer. La comparación no descarga modelos de Ollama.

Para comparar, sitúa el vídeo en un fragmento representativo, selecciona la pista de audio y, si lo deseas, el idioma; **Comparar 30 segundos** muestra las dos transcripciones y sus tiempos sin modificar el proyecto. La primera ejecución puede incluir la descarga y carga de los modelos, por lo que esos tiempos no son una medida aislada de velocidad. Compara también varios fragmentos y revisa manualmente el texto y los tiempos antes de elegir.

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

La acción opcional **Mejorar transcripción** permite elegir entre los modelos instalados en Ollama y pide al modelo corregir mayúsculas y puntuación del texto original sin cambiar los tiempos. El modelo elegido se usa en todos los lotes. Conserva una instantánea previa y ofrece **Revertir última mejora**; rechaza la reversión si sobrescribiría una edición posterior. Revisa las propuestas: un modelo puede cambiar palabras o sentido. Las traducciones existentes no se actualizan automáticamente. La operación usa el modelo local y puede tardar.

## Modelos bajo demanda y memoria

- Arrancar la web o el gateway no descarga ni carga pesos.
- La primera transcripción crea `Session` y `ForcedAligner` de `mlx-qwen3-asr==0.4.4`; descarga los pesos ausentes a la caché local de Hugging Face. La agrupación de palabras en subtítulos usa el formateador de esa versión.
- Carga, inferencia y liberación MLX ocurren en **un único hilo**. La sesión y el alineador se reutilizan. Tras **600 segundos desde el fin del último uso**, el barrido (cada segundo) elimina sus referencias, ejecuta GC y vacía la caché Metal. No interrumpe una inferencia en marcha. Los pesos siguen en disco.
- Ollama recibe `keep_alive: "10m"` en cada generación y gestiona su descarga de memoria. Debe tener el modelo descargado previamente; no se sustituye por un servicio Docker.
- El despliegue previsto tiene un worker RQ; el gateway serializa ASR. En modo launchd el gateway se activa al recibir una conexión y se apaga tras 10 minutos sin actividad; el puerto queda reservado por macOS. No activar múltiples procesos Uvicorn: duplicarían los modelos.

Referencias: [API de sesión MLX](https://github.com/moona3k/mlx-qwen3-asr/blob/v0.4.4/mlx_qwen3_asr/session.py), [agrupación SRT](https://github.com/moona3k/mlx-qwen3-asr/blob/v0.4.4/mlx_qwen3_asr/writers.py), [Ollama keep_alive](https://docs.ollama.com/api/generate).

## Datos y límites

### Sincronizar subtítulos con el audio

En un proyecto local con subtítulos ya incorporados, elige la pista en «Pista de audio» y pulsa «Sincronizar con audio». ffsubsync analiza localmente cuándo hay voz y propone tiempos nuevos; no necesita transcribir ni descargar un modelo de voz. Compara los tiempos y previsualiza la propuesta sobre el vídeo antes de aplicarla. «Descartar» conserva los tiempos actuales; después de aplicar, «Deshacer sincronización» permite revertirlos durante la sesión, siempre que los tiempos no hayan cambiado. Exporta el resultado por separado: el archivo original no se sobrescribe.

La sincronización es aproximada y puede fallar con música, silencios, doblajes o montajes distintos. Si el resultado pierde o cambia segmentos, la aplicación lo rechaza. No estima todavía una confianza por segmento ni ofrece pausa o cancelación durante el análisis; muestra actividad indeterminada. La ejecución no modifica el vídeo, aunque utiliza archivos temporales de subtítulos que elimina al terminar. Requiere ffsubsync en el entorno nativo, instalado por `scripts/setup.sh`.

### Edición junto al vídeo

Selecciona una fila para abrir su editor bajo el reproductor. La banda azul representa la duración del subtítulo y la línea blanca la posición del vídeo; pulsar la banda mueve el vídeo sin cambiar las marcas. Los botones **Fijar** usan la posición actual del vídeo para establecer la entrada o la salida. Permite editar original o transcripción, traducción, entrada y salida; los cambios se guardan al salir del campo y se pueden deshacer durante la sesión. Los botones mueven la reproducción, usan su posición como marca y pasan a la entrada anterior o siguiente. La búsqueda filtra ambos textos sin modificarlos.

«Añadir» crea una entrada después de la selección y «Eliminar» solicita confirmación. La última operación puede deshacerse mientras las entradas afectadas no hayan cambiado; esto evita sobrescribir ediciones posteriores. Para sincronizar manualmente, fija el punto A en una entrada y en su posición correcta del vídeo. Un punto propone un desplazamiento global; dos puntos proponen un ajuste lineal global. Revisa la propuesta antes de aplicarla. Los montajes con escenas añadidas o eliminadas necesitan ajustes por tramos; estos controles todavía no los calculan automáticamente. La navegación por fotogramas y la incorporación de subtítulos dentro del vídeo aún no están implementadas.

El espacio de edición ajusta el tamaño del vídeo para mantener visibles la entrada seleccionada y los controles en una ventana de escritorio. La lista de subtítulos se desplaza dentro de su panel. La configuración de traducción se abre en una ventana modal; la sincronización manual usa un menú junto al editor.

### Traducir un proyecto

Elige una pista existente y pulsa **Abrir y revisar**, o transcribe el audio. Elige el idioma de destino junto al encabezado **traducción** y, en la etapa **Traducir**, selecciona un modelo que ya esté instalado en Ollama; después pulsa **Traducir pendientes**. Se conservan las traducciones existentes y solo se procesan entradas con texto original aún no traducidas. Puedes revisar y editar los resultados o traducir una línea desde su menú. El botón **Audio y modelos** abre los ajustes de pista de audio y modelos ASR; los modelos de traducción se eligen en la etapa Traducir.

Para comparar un rango, abre **⋮** en una entrada y elige **Comparar traducción en este rango**. Se incluyen esa entrada, la anterior si existe y las siguientes, hasta ocho en total. Los dos modelos instalados traducen los mismos originales secuencialmente; el indicador muestra el tiempo transcurrido, que incluye la carga y la generación, sin estimar el tiempo restante. Revisa el original, las propuestas y la traducción actual, y selecciona las opciones que quieras aplicar. No se modifica nada hasta pulsar **Aplicar**.

El idioma elegido se guarda con el proyecto y determina la etiqueta de exportación. Si hay traducciones y el proyecto ya tiene un idioma registrado, la traducción automática de pendientes conserva ese idioma. Si son traducciones antiguas sin idioma registrado, indica su idioma antes de continuar. La columna admite un idioma de destino por proyecto; crear versiones independientes para varios idiomas sigue pendiente.

- Los nuevos proyectos guardan solo una referencia `data/<UUID>/source.json`; el vídeo original debe permanecer accesible en su ubicación. Las copias de proyectos anteriores se conservan en `data/<UUID>/`; PostgreSQL en `pgdata`; Redis con AOF en `redisdata`. Un fallo de cola tras persistir el proyecto conserva el medio y registra un error recuperable. Cada lote traducido se guarda por separado.
- **Quitar de biblioteca** y **Vaciar biblioteca** mueven los proyectos a la papelera recuperable; los trabajos activos se mantienen visibles. Se conservan las entradas, originales, datos y copias. **Papelera** permite restaurar uno o todos. No hay migraciones destructivas ni borrado definitivo de proyectos desde la UI. `create_all` inicializa tablas sin sustituir datos. No ejecutar `docker compose down -v`, `docker volume prune` ni borrar `data/` para resolver fallos.
- UI/API son locales, sin autenticación de usuarios. No exponerlas a Internet. El gateway escucha en todas las interfaces por compatibilidad con Docker: protege el puerto mediante firewall/red de confianza y conserva el token en secreto. Ollama puede permanecer en loopback.
- Abrir un original por referencia no tiene el límite de subida de 2 GiB. La API de subida anterior sigue disponible para compatibilidad, conserva ese límite y sí crea una copia local. RQ limita el trabajo a cuatro horas; cada lote de traducción tiene un timeout de 900 s. La cancelación del cliente/RQ no cancela necesariamente una inferencia nativa ya iniciada.
- Durante traducción y mejora, los segmentos permanecen visibles y la edición se bloquea para evitar sobrescrituras; durante la transcripción se pueden editar los tramos ya guardados. Al entrar en una fila de subtítulo el vídeo salta a su mark-in sin comenzar a reproducirse. Cada campo se guarda al salir de él; Deshacer/Rehacer conserva el historial durante la sesión del proyecto. La UI protege selección, exportación y cierre con cambios pendientes y permite reintentar si falla el guardado. Si una fila ha cambiado en otra pestaña, se rechaza el guardado y se conserva el texto editado para que puedas copiarlo y revisar el conflicto; no hay fusión automática.
- El mapa de audio muestra una envolvente local por tramos; no es un editor de forma de onda detallada. No incluye diarización, división/unión, historial persistente de edición, reglas editoriales CPS/CPL ni quemado de subtítulos en vídeo. Se importan pistas incrustadas de texto; PGS/VobSub y otras pistas de imagen necesitan OCR, aún no implementado. La compatibilidad de reproducción depende de los códecs del navegador, aunque FFmpeg pueda transcribir el archivo.
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

## Licencia y demostraciones

El código de Subtitle Studio se distribuye bajo la [licencia MIT](LICENSE). Los modelos, películas, subtítulos y demás materiales de terceros tienen sus propias licencias; MIT no las sustituye.

Para las capturas y demostraciones se propone *Sintel* (Blender Foundation, 2010), un cortometraje con diálogos disponible bajo [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). Crédito: © copyright Blender Foundation | [durian.blender.org](https://durian.blender.org/). Consulta las [condiciones del proyecto](https://durian.blender.org/sharing/): al distribuir o proyectar la película hay que conservar sus créditos; identifica cualquier recorte o modificación y verifica la licencia específica de los subtítulos empleados. Los logos y marcas tienen condiciones distintas.

El tráiler oficial se puede descargar desde [Blender](https://download.blender.org/durian/trailer/sintel_trailer-720p.mp4); el archivo se mantiene local y no se incluye en el repositorio. La película completa y sus versiones están descritas en la [página de descarga](https://durian.blender.org/download/).
