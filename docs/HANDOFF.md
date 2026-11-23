> **Revisión del 22 de noviembre de 2026:** Las secciones siguientes conservan apuntes históricos; sus recuentos de pruebas, flujos y pendientes pueden haber cambiado. Para la preparación de GitHub consulta el [plan de publicación](superpowers/plans/2026-11-22-publicacion-github.md) y el [README](../README.md). El historial remoto existente se debe preservar.

# Subtitle Studio — traspaso de desarrollo

## Situación: 23 de noviembre de 2026

- La sincronización global permite proponer un desplazamiento y una conversión entre FPS conocidos. La propuesta ocupa el panel de subtítulos junto al vídeo, puede descartarse o aplicarse, y el ajuste aplicado puede deshacerse durante la sesión si los tiempos no han cambiado. Se rechazan tiempos negativos; no se eliminan entradas ni se sobrescriben archivos originales. Revisar en distintos momentos: un cambio de FPS no implica por sí solo un cambio de duración y los montajes con cortes intermedios pueden necesitar ajustes por tramos.
- La API del gateway informa de las rutas de modelos presentes en la caché compartida de Hugging Face; **Audio y modelos** las muestra. Los modelos de traducción y mejora se consultan y gestionan por separado con Ollama. El frontend se reconstruyó y el gateway nativo se reinició bajo demanda sin tareas ni conexiones activas. En la UI se comprobó una propuesta de desplazamiento y se descartó, sin aplicar cambios al proyecto; se verificaron también las rutas reales de los modelos.
- La demo de línea de tiempo ajena al proyecto se retiró del árbol actual. GitHub Pages fue despublicado y su origen se configuró como `None`; se conservó el historial. Los dos HTML autocontenidos del handoff de diseño siguen sin seguimiento, pendientes de revisión de procedencia y licencias; no deben incluirse accidentalmente.
- El paquete npm `0.1.0` es una versión anterior a estos cambios; no se ha publicado una actualización de npm en esta sesión. Sus metadatos y los commits antiguos pueden contener direcciones de correo anteriores: cambiar la configuración Git no reescribe el historial ni modifica metadatos publicados.
- Pendiente de validación integral: probar en medios reales una conversión de FPS y un desplazamiento, con aplicación, reproducción y deshacer; comprobar comportamiento en montajes con cortes intermedios. No se ha realizado una prueba integral con inferencia real como parte de este cambio. La reversión de sincronización actual se conserva solo en la sesión. La revisión del rediseño general y demás pendientes históricos siguen requiriendo una auditoría actualizada; los recuentos y estados del apartado del 7 de noviembre no son el estado actual.

## Rediseño de flujo: trabajo en curso

### Avance del 7 de noviembre de 2026

La biblioteca inicial agrupa episodios por serie y temporada y ofrece búsqueda, filtros, papelera y ruta persistente. El espacio de trabajo incorpora navegación por etapas, filtros de líneas, selector del texto sobre el vídeo, un mapa de audio calculado a partir de la pista seleccionada y un menú de exportación con comprobaciones. En el navegador se verificaron la biblioteca, la apertura de un episodio, el salto desde el mapa, las comprobaciones de exportación y la apertura del comparador; no se lanzó inferencia ni se aplicaron cambios a los subtítulos de ese episodio.

La revisión individual y la comparación de traducción por rangos de hasta ocho segmentos están implementadas y cubiertas por pruebas aisladas. Aplicar una comparación guarda una instantánea recuperable y comprueba el estado anterior; también se conservan los segmentos eliminados desde la revisión para poder restaurarlos. La comparación de transcripción por rango todavía no está implementada. Los indicadores de baja energía y de confianza de Whisper se derivan de los datos de audio y del modelo; se etiquetan para revisión y no son una prueba de ausencia de voz. La interfaz de revisión y la última protección de borrado necesitan otra comprobación visual/de integración.

La versión desplegada durante esta sesión incluye biblioteca, etapas, mapa, exportación, revisión y comparador de traducción. Después se añadió en el árbol de trabajo la instantánea recuperable para los borrados desde revisión: requiere reconstruir API y frontend para estar activa. El gateway se reinició de forma controlada sin trabajos activos y el nuevo endpoint de comparación respondió con el error esperado al rechazar dos modelos inexistentes; no se ejecutó una comparación real. Las pruebas anteriores de esta sesión fueron 123 de Python y 78 de interfaz, antes de los cambios posteriores; repetirlas al continuar.

Siguen pendientes: lotes, selección múltiple y carpetas, recetas y cola; comparación de transcripción por rango; ajustes; completar la estructura y el comportamiento de todos los paneles de etapa; vista general de audio; actualización incremental de filas sin reconstrucción; diagnóstico de tiempos fuera de tramo y revisión con medios reales; verificación final en macOS y actualización del README. El prototipo local quedó inaccesible desde el navegador por una política de seguridad; se han consultado sus fuentes. La rama y los cambios sin confirmar deben conservarse.

El encargo de `docs/design_handoff_rediseno_flujo/README.md` **no está terminado**. El plan de trabajo está en `docs/superpowers/plans/2026-11-06-redisenyo-flujo.md`. Las notas de situación que siguen describen revisiones anteriores; comprobar de nuevo los servicios y proyectos antes de operar.

Avances implementados: metadatos de episodios y recuentos en la API; clasificación y recomendación de fuentes de subtítulos por episodio con vista previa automática; exportación bilingüe; mejoras nuevas guardadas como propuestas con aceptación y descarte explícitos; edición de texto de tramos terminados durante la transcripción; detección y revisión básica de repeticiones; y endpoints de envolvente calculada sobre audio real. La nueva tabla `cue_reviews` se crea de forma aditiva al iniciar la API. Las instantáneas de mejoras antiguas conservan su comportamiento de recuperación anterior.

Para el estado más reciente y las tareas pendientes, véase el apartado del 7 de noviembre. La clasificación de películas y las referencias antiguas necesitan más cobertura. No presentar esta versión como el rediseño terminado.

Antes de desplegar, revisar los cambios sin confirmar y comprobar que no haya tareas activas. El cambio de frontend/API requiere reconstruir las imágenes y el gateway nativo debe recargar sus archivos; no borrar volúmenes ni datos. Verificar también contra PostgreSQL real y el gateway en macOS: las pruebas automatizadas usan datos temporales y no sustituyen una prueba completa de la aplicación.

Fecha de revisión: 6 de noviembre de 2026. Este documento describe el estado del checkout y del entorno local en esa fecha; no sustituye al [README](../README.md).

## Situación al entregar

- Repositorio: `subtitle-studio`. Rama: `feature/mvp-setup`. `origin` apunta a `https://github.com/fedeblock/subtitle-studio.git`.
- `HEAD` y la referencia remota local `origin/feature/mvp-setup` apuntaban a `634c102`. Esa es la última referencia remota conocida localmente; esta revisión no hizo `fetch` ni verificó cambios posteriores en GitHub.
- **Hay cambios importantes sin confirmar**, incluidos archivos nuevos. No hacer `reset`, `clean`, checkout de archivos, `stash` destructivo ni push forzado. Revisar `git status --short` y `git diff`; tener en cuenta que `git diff` no muestra el contenido de los archivos nuevos sin seguimiento. El código que está funcionando incluye esos cambios, no solo `634c102`.
- Los contenedores `frontend`, `api`, `worker`, `db` y `redis` estaban en ejecución y sanos; la cola estaba vacía y no había trabajos activos. El gateway nativo estaba registrado en launchd y responde bajo demanda.
- Se detuvo a petición del usuario una mejora de **Ink.Wash**, tras quedar bloqueada al 2 %. En esta revisión el proyecto figura como `cancelled` y su instantánea de mejora no revertida contiene 24 entradas con resultados; pueden haberse realizado otras operaciones desde la detención original. La interfaz ofrece **Revertir última mejora**. Conservar esa instantánea y las ediciones hasta que el usuario decida qué hacer.

## Qué hace el MVP

La aplicación abre un vídeo local mediante el selector de macOS y conserva una referencia a su ruta. El original no se copia en el flujo nuevo y la inferencia se realiza localmente. Detecta subtítulos junto al vídeo, en carpetas `Subs`/`Subtitles` y pistas de texto incrustadas; permite escoger y escuchar la pista de audio. Al seleccionar subtítulos se muestra la tabla de vista previa y, si el vídeo está pausado al comienzo, se busca la primera línea para mostrarla sobre la imagen sin reproducir automáticamente. Las pistas de subtítulos de imagen necesitan OCR y no se importan directamente.

El editor muestra tiempos, original y traducción; guarda al salir de cada campo, permite deshacer/rehacer en la sesión y salta al mark-in. Pueden traducirse entradas individuales en ambos sentidos y compararse dos modelos instalados en Ollama antes de aplicar una propuesta. La traducción por lotes de pendientes está orientada al español. La mejora de transcripción permite escoger un modelo instalado y mantiene una copia reversible; no modifica automáticamente las traducciones existentes.

**Volver a transcribir** crea otro proyecto que apunta al mismo vídeo y conserva el anterior. Los archivos SRT/VTT se pueden descargar o guardar junto al original sin sobrescribir uno existente. La biblioteca tiene papelera recuperable; no hay borrado definitivo de proyectos desde la UI.

La transcripción se procesa en tramos de 30 segundos y publica los segmentos guardados durante el trabajo. El panel muestra avance, y ofrece **Pausar**, **Reanudar** y **Cancelar tarea**. La pausa y la cancelación son cooperativas: se aplican al terminar el tramo o lote actual; una inferencia nativa bloqueada puede tardar en devolver el control. Las tareas en cola se detienen inmediatamente. Cancelar conserva el trabajo guardado; la mejora conserva además su instantánea para revertirla.

## Arquitectura y datos

| Componente | Ubicación y función |
| --- | --- |
| Frontend | `frontend/`, Nginx en Docker, publicado en `127.0.0.1:3000`. |
| API y worker | `backend/app/main.py` y `backend/app/worker.py`; FastAPI y un worker RQ en Docker. |
| Persistencia y cola | PostgreSQL (`pgdata`) y Redis AOF (`redisdata`) en Docker. `TaskControl` registra la operación pausada; `TranscriptionProgress` guarda el siguiente tramo. |
| Gateway local | `mac-worker/server.py`, Python nativo de macOS, autenticado con `X-Worker-Token`. launchd conserva el socket y arranca el proceso al recibir una petición; se apaga tras 10 minutos de inactividad. |
| ASR | `mac-worker/model_runtime.py`: Qwen3-ASR/ForcedAligner y Whisper large-v3 mediante MLX/Metal nativo. Se cargan bajo demanda y el trabajo ASR se serializa. |
| LLM | Ollama nativo en macOS; el modelo de traducción predeterminado es `qwen3:14b-q8_0`. Se envía `keep_alive: 10m`. |

Los nuevos proyectos referencian el original desde `data/<UUID>/source.json`. Las instantáneas de mejora también se guardan dentro del directorio del proyecto. Los proyectos antiguos pueden contener copias locales; la API de subida antigua sigue creando copias. `.env`, `data/`, las bases de datos, los entornos virtuales y las cachés de modelos contienen datos o configuración del usuario: no borrarlos ni publicarlos. `Base.metadata.create_all()` crea tablas ausentes, pero no es un sistema completo de migraciones.

Estado observado de modelos: Qwen3-ASR y su alineador en caché (~6,54 GB), Whisper large-v3 (~3,08 GB); Ollama devolvió `qwen3:14b-q8_0`, `nemotron-3.5-lightning:latest` y `qwen3.8:27b`. Son datos de este equipo y pueden cambiar. El borrado de modelos ASR actúa sobre la caché compartida de Hugging Face y solicita confirmación: puede afectar a otras aplicaciones.

## Recuperación y límites conocidos

- Sincronización local: el editor genera una propuesta con `ffsubsync==0.5.1` en el gateway nativo y la pista seleccionada; compara y aplica tiempos mediante comprobación optimista. Se rechazan resultados que pierden o alteran segmentos. El usuario puede descartar la propuesta o deshacerla durante la sesión. El análisis usa temporales de SRT, no sobrescribe el original y aún no tiene pausa/cancelación ni progreso porcentual. La calidad debe comprobarse con audio real; un resultado de VAD no garantiza una alineación correcta.
- Editor: selección con campos ampliados de ambos idiomas, búsqueda, navegación, marcas desde el reproductor y propuestas manuales globales de desplazamiento o escala con uno o dos puntos. Insertar/eliminar crea una instantánea reversible con control de cambios; deshacer no sobreescribe entradas modificadas después. La sincronización manual por escenas, el avance por fotograma y multiplexar la exportación aún están pendientes.

- El avance ASR y los segmentos del tramo se confirman juntos. Ante errores temporales de conexión o determinadas respuestas de servidor, el worker hace tres reintentos adicionales con pausas de 2, 4 y 8 segundos. No todos los errores son transitorios; al agotarlos se conserva lo ya guardado.
- Qwen puede devolver texto con alineación inválida. Se conserva con tiempos aproximados y un aviso; hay que revisar el texto porque puede incluir alucinaciones. Qwen3-ForcedAligner no incluye rumano en su lista oficial de idiomas. Whisper puede producir marcas fuera del tramo: se ajustan al audio disponible y se avisa.
- La mejora escribe una instantánea antes de aplicar cada lote. La reanudación revisa qué entradas ya se aplicaron y protege contra ediciones posteriores. No llamar directamente a `rq requeue`: usar los controles de la aplicación y revisar el estado y la copia antes de recuperar trabajos abandonados.
- Redis y PostgreSQL no forman una transacción conjunta: sigue existiendo una ventana entre guardar estado y encolar. No hay reconciliación automática completa tras una caída brusca. El límite de RQ es de cuatro horas; un cliente cancelado no cancela necesariamente una inferencia ya iniciada en Ollama/MLX.
- El porcentaje ASR depende de la duración que pueda obtener el reproductor; si no está disponible se muestra el tiempo procesado sin inventar porcentaje. La traducción usa el número de segmentos guardados y la mejora el porcentaje confirmado y la última respuesta registrada.
- Una mejora pausada/cancelada espera al final de la petición en curso; no es una interrupción inmediata del modelo. Las pruebas de pausa/cancelación cubren transcripción, traducción y mejora con servicios simulados; conviene validar también un ciclo completo con vídeo y modelos reales, incluidos fallos/reinicio durante una petición larga.
- La calidad de ASR, el idioma detectado, la sincronización y las traducciones requieren revisión humana. La compatibilidad de reproducción MKV depende del navegador/códecs. La comparación entre modelos sirve para revisar resultados; los tiempos de primera ejecución incluyen la carga y no son una medición aislada de velocidad.

## Puesta en marcha y comprobación

Consultar los requisitos y el procedimiento completo en el [README](../README.md). Con Docker Desktop abierto y la configuración ya instalada:

```bash
docker compose up -d --build --wait
```

Abrir `http://localhost:3000/`, no `frontend/index.html` como archivo. El gateway se activa bajo demanda si está instalado con `python3 scripts/install-mac-service.py`. Antes de reiniciar servicios comprobar si hay una tarea activa: una parada abrupta puede dejar una operación que necesite recuperación.

```bash
docker compose ps
docker compose logs --tail=100 api worker
curl http://localhost:3000/api/health
curl http://127.0.0.1:11434/api/tags
```

No ejecutar `docker compose down -v`, `docker volume prune` ni borrar `data/` como medida de diagnóstico. No imprimir ni compartir `.env` o tokens. Los registros del gateway se encuentran en `~/Library/Logs/subtitle-studio-gateway.err.log` y `subtitle-studio-gateway.out.log`.

## Pruebas y próximos pasos

Última verificación en este checkout, el 6 de noviembre de 2026: **106 pruebas de Python y 63 de frontend aprobadas**. La suite Python mostró una advertencia de deprecación de Starlette/AnyIO. Se ejecutaron `.venv/bin/pytest -q` y `npm test`; estas pruebas usan almacenamiento aislado y servicios simulados cuando corresponde. Se verificó además la vista previa con un vídeo sintético y, en la aplicación, el acceso a la reversión y el selector de modelos; esto no equivale a una prueba completa de todos los flujos con modelos y archivos reales.

1. Revisar los cambios sin confirmar y los archivos nuevos, contrastarlos con los planes en `docs/superpowers/` y decidir cómo dividirlos en commits. Preservar los historiales local y remoto; no forzar el push.
2. Con permiso y datos adecuados, validar un recorrido real de pausa, reanudación y cancelación en transcripción, traducción y mejora; comprobar que no se duplican segmentos, que la mejora conserva la reversión y que el vídeo original no se copia.
3. Revisar con el usuario la mejora parcial detenida de Ink.Wash antes de revertirla, volver a procesarla o eliminar cualquier dato.
4. Revisar las limitaciones de reconciliación de trabajos, la detención de inferencias largas y la calidad de marcas de tiempo para rumano; evitar presentar aproximaciones como marcas exactas.

Documentación complementaria: [archivos locales](LOCAL-FILES.md), [validación del MVP](MVP-VALIDATION.md), [diseño de interfaz](superpowers/specs/2026-11-05-ux-redesign-design.md) y [mockup](mockups/2026-11-05-ux-redesign.html).
