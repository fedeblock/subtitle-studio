# Handoff: rediseño del flujo de Subtitle Studio

> Nota de publicación: los HTML autocontenidos del prototipo y de la referencia se conservan en el entorno local mientras se revisan los recursos de terceros incluidos; pueden no estar presentes en el repositorio. Las fuentes legibles y los tokens acompañan este documento.

## Resumen
Rediseño completo del recorrido del usuario en Subtitle Studio (repo `subtitle-studio/`). Hoy la app es una sola vista con una biblioteca lateral, y la fuente, el editor, los modelos y la comparación se apilan bajo el vídeo. El nuevo diseño organiza el trabajo en **etapas** (Fuente → Procesar → Revisar → Traducir → Exportar) dentro de un espacio de trabajo único. Además añade:
- una **biblioteca de inicio** agrupada por serie,
- **lote con receta y cola** para temporadas enteras,
- **revisión de segmentos dudosos** (texto inventado en silencios, repeticiones, baja confianza, tiempos fuera de tramo) con mapa de voz y un modo foco,
- **comparación lado a lado** de motores STT y de traducción,
- **mejora con Ollama como propuestas** que se aceptan por segmento,
- **exportación con comprobaciones** previas.

El encargo es implementarlo **todo** en este repo: frontend y backend.

## Sobre los archivos de diseño
Los archivos de `prototipo/` y `referencia/` son **referencias de diseño hechas en HTML**: prototipos que muestran el aspecto y el comportamiento esperados. No son código de producción para copiar. El prototipo usa React por comodidad, pero el frontend real es **JS vanilla** (`frontend/app.js`, `library.js`, `sources.js`, `model-ui.js`, `editor-state.js`) con plantillas `innerHTML` y CSS en `frontend/index.html`. Recrea el diseño **dentro de ese entorno y con sus patrones**. No introduzcas React ni un bundler. Si un archivo crece demasiado, divídelo en módulos JS como los existentes.

Los datos del prototipo (`data.js`) son inventados: textos, tiempos, forma de onda y dudosos. En producción salen del backend.

## Fidelidad
**Alta fidelidad.** Colores, tipografía, espaciados, radios y estados son finales. La paleta es la actual de la app (navy oscuro), con un único color nuevo: el **ámbar de dudosos**. Recréalo con precisión.

## Archivos
- `prototipo/Prototipo.html`: prototipo navegable, autocontenido. Ábrelo en el navegador. Recorrido: Biblioteca → E02 «Revisar» → «Revisar uno a uno» (teclas A/B/→/Esc) → etapa Traducir → «Traducir 22 pendientes» / «Proponer mejoras» → ⇄ en una fila → «Exportar ▾». También E05 «Elegir» → «Transcribir» (procesado progresivo), «Abrir archivos o carpeta» → receta → cola, y «Ajustes».
- `prototipo/fuentes/*.jsx`, `data.js`: fuentes legibles del prototipo, para consultar estructura y valores exactos (`workspace.jsx` contiene el espacio de trabajo, la barra de etapas y los paneles de etapa; `cue-list.jsx` la lista; `overlays.jsx` el modo foco, la comparación y el menú de exportar; `voice-map.jsx` el mapa de voz; `library-screen.jsx` y `screens.jsx` la biblioteca, el lote, la cola y los ajustes).
- `referencia/UX Journey.html`: mapa del journey y wireframes, con la tabla «Mezcla» que justifica cada decisión.
- `tokens/*.css`: tokens del sistema (valores tomados del `index.html` actual).

---

## Pantallas

### 1. Biblioteca (pantalla de inicio)
Sustituye al panel lateral `.library` como vista inicial. El panel superpuesto desaparece y se vuelve a la biblioteca con «‹» en la cabecera del proyecto.
- **Cabecera** (48 px, `#11192a`, borde inferior `1px #263148`, padding `0 12px`, gap 10 px): marca «Subtitle **Studio**» (14 px / 700 / −0.2 px, «Studio» en `#67c3ff`). Buscador de 30 px de alto y ancho `min(360px,40vw)`, fondo `#0d172a`, borde `#314057`, radio 8 px, placeholder «Buscar serie, película o estado». Espaciador. Badge «● Local». Botón ghost «Ajustes». Botón primario «Abrir archivos o carpeta».
- **Contenido**: columna centrada, `max-width:980px`, padding `22px 24px 60px`.
- **Filtros** (chips, radio 20 px, borde `#2b3850`, 12 px, padding `4px 10px`): Todo · Necesita atención · Por hacer · En curso · Listo, cada uno con su contador (11 px, `#7f8fa8`; ámbar en «Necesita atención»). Chip activo: fondo `#203451`, borde `#57b5fa`; en la variante ámbar, fondo `#2e2418` y borde `#f0a75a`. A la derecha, «Cola · N ›» si hay trabajos en marcha.
- **Grupos**: series agrupadas por nombre y temporada, a partir del patrón `SxxEyy` del nombre de archivo, y un grupo «Películas» para el resto. Cabecera de grupo en 13 px / 650 con el contador en 12 px `#7f8fa8`.
- **Fila** (contenedor con borde `#2b3850`, radio 10 px, fondo `#141e31`; filas separadas con `1px #263148`; hover `#19243a`): rejilla `52px | 1fr | 140px | 96px`, gap 14, padding `10px 14px`. Columnas: «E02» o año (12 px, `#7f8fa8`, cifras tabulares) · nombre de archivo (13 px / 600, con elipsis) y debajo el estado (12 px, coloreado según el tono) · barra de progreso de 3 px · botón de siguiente acción (sm). La fila entera es clicable.
- **Estado y acción por fila** (la lógica está en `libSummary`, en `fuentes/library-screen.jsx`):

| Condición | Texto | Color | Acción |
|---|---|---|---|
| draft | «Elige los subtítulos · N encontrados» | `#e8edf7` | Elegir |
| en cola | «En cola» | `#7f8fa8` | — |
| fallido | «Se detuvo en el tramo X de Y» | `#ff8495` | Reintentar |
| transcribiendo | «Transcribiendo · N %» | `#67c3ff` | — |
| traduciendo | «Traduciendo · a/b» | `#67c3ff` | Ver (ghost) |
| dudosos > 0 | «N segmentos dudosos» | `#f0a75a` | Revisar |
| sin traducir > 0 | «N sin traducir» | `#e8edf7` | Traducir |
| completo, no exportado | «Listo para exportar» | `#73deb3` | Exportar |
| exportado | «Exportado · .es.srt» | `#73deb3` | Abrir (ghost) |

- Pie: enlace «Papelera», que conserva la función actual de papelera.

### 2. Nuevo lote (receta)
Se abre desde «Abrir archivos o carpeta» cuando se eligen varios archivos o una carpeta. El diálogo nativo de macOS debe permitir **selección múltiple y carpetas**.
- Cabecera: «‹ Biblioteca» · «Nuevo lote» · ruta de la carpeta (12 px, `#94a3b8`).
- Dos paneles en rejilla `1fr 1fr`, gap 20, `max-width:1040px`.
  - **Episodios detectados**: casilla + «E06» + fuente detectada por episodio (p. ej. «.en.srt junto al vídeo», «Pista 2 · eng incrustada», «Subs/S01E08.English.srt», o «Sin subtítulos → transcribir» en ámbar). Nota final: «N subtítulos de otros episodios ignorados.»
  - **Receta**: Receta guardada (select) · Fuente preferida · Si no hay subtítulos (motor ASR) · Traducir a + modelo de Ollama · ☐ Mejorar mayúsculas y puntuación antes de traducir · ☑ Marcar segmentos dudosos para revisar · «› Avanzado» (plegado: idioma hablado, exportar al terminar).
- Pie fijo: «Revisar es manual. El resto de pasos sigue solo mientras revisas otro episodio.» · botón primario «Añadir N a la cola».

### 3. Cola
- Cabecera: «‹ Biblioteca» · «Cola · {serie}» · «N en marcha · ~X min restantes» · «Pausar cola».
- Tabla en panel. Columnas `56px | 5 × 1fr | 96px`: Ep. · Fuente · Procesar · Revisar · Traducir · Exportar · acción. Celdas: ✓ en `#73deb3`; «—» en `#6d7f99`; «en cola» o «espera» en muted; porcentaje en `#67c3ff` con barra de 3 px; «N dudosos» en ámbar.
- Las filas que esperan a una persona (dudosos o fuente sin elegir) llevan fondo `#2e2418`, y su botón es «Revisar» o «Elegir».
- Pie: «Las filas resaltadas esperan a una persona.» · «Exportar listos».

### 4. Espacio de trabajo (proyecto)
Estructura fija de arriba abajo:
1. **Cabecera** (48 px): «‹» · título en dos líneas («It's a Sin · T1 · E02» en 13 px / 700 y nombre de archivo en 10.5 px `#7f8fa8`) · **barra de etapas** · espaciador · badge Local · «Exportar ▾». Este botón es primario cuando todo está traducido y aún no se ha exportado; está desactivado mientras la fuente no esté elegida o se esté procesando.
2. **Mapa de voz** (franja con fondo `#11192a`, padding `10px 14px 8px`, borde inferior).
3. **Split** `42% | 58%`. A la izquierda, vídeo y panel de la etapa (con scroll propio). A la derecha, la lista de segmentos. Por debajo de **1100 px** se apila en una columna y la parte izquierda queda limitada a `max-height:46vh`.

**Barra de etapas.** Botones de 12 px, padding `4px 9px`, radio 7, separados por «›» en `#6d7f99`. Cada etapa tiene un estado:
- `done`: texto `#aebdd4` con «✓» en `#73deb3`.
- `cur` (la del panel abierto): fondo `#203451`, borde `#57b5fa`.
- `warn`: texto ámbar, por ejemplo «Revisar · 4»; si además está abierta, fondo `#2e2418` y borde ámbar.
- `run`: texto `#67c3ff` con un punto de 6 px que pulsa (opacidad 0,3 ↔ 1, 1,2 s, ease-in-out, alternando; desactivado con `prefers-reduced-motion`). Ejemplos: «Procesar · 34 %», «Traducir · 64 %».
- `skip`: tachado; se usa en Procesar cuando la fuente ya es un .srt, con el tooltip «No hace falta: la fuente ya tiene texto».
- `todo`: `#7f8fa8`.

Mientras la fuente no está elegida, el resto de etapas está desactivado (opacidad 0,55). Hacer clic en una etapa abre su panel; «Exportar» abre el menú de exportar. El panel por defecto al abrir un proyecto es: fuente si es draft, procesar si se está procesando, revisar si hay dudosos y traducir en el resto de casos.

**Mapa de voz.** Representa una ventana de audio sincronizada con la lista; en el prototipo, unos 70 s.
- Envolvente de amplitud de unas 220 barras en 46 px de alto, separadas 1 px y con radio 1. Color de cada barra: `#4eacec` si cae bajo un segmento; ámbar si el segmento es dudoso sin resolver; `#344158` si no hay segmento; `#243149` si el tramo aún está pendiente de procesar.
- Debajo, una pista de 6 px con bloques por segmento (`#405473`, o ámbar si es dudoso). Al hacer clic en un bloque se salta a ese segmento.
- Cabezal de reproducción: línea de 2 px en `#eff4ff`. Al hacer clic en el mapa se salta a ese momento.
- Durante el procesado, la zona pendiente se marca con un borde discontinuo `#67c3ff`.
- Última fila: inicio y fin de la ventana, una **vista general del episodio** de 4 px con marcas ámbar de todos los dudosos y un rectángulo con borde `#eff4ff` que indica la ventana visible, y la leyenda «■ texto sin voz o dudoso» en ámbar.

**Columna izquierda** (padding 12, gap 10):
- Vídeo 16:9 con la superposición de subtítulos actual, sin cambios de estilo.
- Barra de reproducción: ▶, tiempo, pista de 3 px y ⛶.
- Fila «Sobre el vídeo» con un control segmentado Original | Traducción, que decide qué texto se superpone en el vídeo, y a la derecha un desplegable plegado «Audio · Pista 1 · eng» con el selector de pista y el volumen.
- **Panel de etapa** (borde `#2b3850`, radio 10, fondo `#141e31`, padding 14, gap 10, ocupa el alto restante, `min-height:180px`):
  - **Fuente**: «¿De dónde salen los subtítulos?» y «Solo se muestran las fuentes de este episodio.» Opciones radio, con la recomendada preseleccionada y marcada «recomendada»; luego «Transcribir el audio» con borde discontinuo y la etiqueta «~18 min». Si se elige transcribir, aparecen dos selects (motor ASR e idioma hablado). Debajo, «› N subtítulos de otros episodios ocultos», que al desplegarse lista esos archivos atenuados. Botón primario «Usar esta fuente» o «Transcribir». Mientras se elige, la lista de la derecha es una **vista previa en solo lectura** de la fuente seleccionada, con la nota «Vista previa · solo lectura hasta usar la fuente». Si se elige transcribir, la derecha muestra un texto vacío: «Al transcribir, los segmentos aparecerán aquí tramo a tramo. El vídeo no se copia ni se envía a Internet.»
  - **Procesar**: «Transcribiendo con Qwen3-ASR» · «tramo X de Y» / «~N min restantes» · barra de 5 px · «Cada tramo terminado aparece en la lista y ya se puede editar. Los dudosos se marcan a medida que llegan.» · Pausar/Reanudar · Cancelar.
  - **Revisar**: número grande (26 px / 700, ámbar) + «segmentos dudosos» · chips por motivo («sin voz · 2», etc.) · «Suelen ser texto inventado en silencios o repeticiones. Revísalos uno a uno con el audio delante.» · primario «Revisar uno a uno» · «Comparar con Whisper». Sin dudosos: «✓ Sin dudosos pendientes» (verde) + «Siguiente: traducir».
  - **Traducir**: selects de idioma y modelo de Ollama · primario «Traducir N pendientes»; mientras traduce, «a de b · N %» + barra + Pausar · separador · «Mejorar el original» + «Ollama propone mayúsculas y puntuación. Nada cambia hasta que aceptas.» · «Proponer mejoras» (pasa a «Analizando…» mientras trabaja). Cuando hay propuestas, los botones son «Aceptar N propuestas» (primario) y «Ver una a una», que activa el filtro de propuestas.

**Lista de segmentos (derecha):**
- Fila de filtros (chips, padding `8px 12px`): Todo · Dudosos (ámbar) · Sin traducir · Mejoras propuestas (solo si hay alguna).
- Cabecera sticky en `#1b2942`, 10.5 px / 600, `#a9bad2`. Rejilla `38px | 92px | 1fr | 1fr | 30px`: # · tiempos · original · traducción · menú. Las etiquetas de idioma salen del proyecto.
- Fila: padding `7px 12px`, borde inferior `1px #222e42`.
  - Tiempos apilados en 11 px con cifras tabulares: la entrada en `#c4d9f7` y la salida en `#7f8fa8`. Los campos de tiempo siguen siendo editables en el modo foco.
  - Original y traducción en textareas (`min-height:40px`, 12.5 px, line-height 1.45, radio 7, fondo `#0d172a`).
  - Fila activa: fondo `#20314e`.
  - Fila dudosa: `box-shadow: inset 3px 0 0 #f0a75a`, y bajo el original «⚠ {motivo} · {explicación}» en 11 px ámbar.
  - Explicaciones de cada motivo: *sin voz*: «El audio no tiene voz bajo este texto»; *repetición*: «Repite el segmento anterior»; *baja confianza*: «El modelo dio baja confianza a estas palabras»; *fuera de tramo*: «El final se sale del tramo de audio».
  - Propuesta de mejora: en lugar del textarea, una caja (borde `#405473`, radio 7, fondo `#0d172a`) con el texto actual tachado en `#ffadb7` y el propuesto en `#8be2b1`, más los botones «✓ Aceptar» (fondo `#163d31`, borde `#25664c`) y «✕ Descartar».
  - Mientras se traduce un segmento, su celda de traducción muestra «traduciendo…» en `#67c3ff`.
  - Menú ⇄ (botón de 26 px, borde `#34425c`): popover de 230 px con «Traducir este segmento» · «Comparar transcripción aquí» · «Comparar modelos de traducción».
  - Al hacer clic en una fila se lleva el vídeo a su entrada. La lista sigue al segmento activo durante la reproducción.
- Durante el procesado se añaden al final dos filas fantasma (opacidad 0,7): «tramo N · procesando…» en azul y «pendiente», con barras esqueleto de 9 px en `#243149`.

### 5. Modo foco (revisión de dudosos)
Capa opaca (`#0c1220`) que cubre el espacio de trabajo bajo la cabecera.
- Barra superior: «‹ Lista» · «‹ Dudoso N de M ›» · chip del motivo (ámbar sobre `#2e2418`, borde `#6b4a24`) · explicación · a la derecha, «Esc volver a la lista».
- Cuerpo en rejilla `1.25fr | 1fr`, gap 24, padding `20px 24px`:
  - Izquierda: vídeo con el texto superpuesto y debajo la **forma de onda ampliada** al segmento ±4 s (64 px, fondo `#070b12`, radio 8; las barras del segmento en ámbar y el resto en `#405473`) con los rótulos de inicio, «Audio ±4 s · en naranja, el segmento» y fin.
  - Derecha: el segmento anterior como contexto (12.5 px, `#7f8fa8`) · textarea grande (16 px, `min-height:84px`) · entrada y salida (TextField de timecode; la salida se marca inválida si el motivo es «fuera de tramo») · el segmento siguiente como contexto.
- Pie: «Borrar segmento [B]» · «Es correcto [A]» · nota «Editar el texto y pasar al siguiente también lo da por revisado» · primario «Siguiente dudoso [→]».
- Teclado: **A** marca el segmento como resuelto y avanza · **B** lo borra y avanza · **→ / ←** navegan · **Esc** cierra y deja activo el filtro «Dudosos» si queda alguno. Las teclas se ignoran mientras el foco está en un input o un textarea, salvo Esc.
- Al terminar: «✓ Has revisado los N dudosos» · «Los cambios ya están guardados.» · «Volver a la lista» · primario «Siguiente: traducir».

### 6. Comparar motores (modal)
Se abre desde ⇄ o desde el panel Revisar. Scrim `#05080ecc`; caja de `min(1040px,100%)` con fondo `#141e31`, borde `#405473`, radio 12 y sombra `0 8px 24px #0008`.
- Cabecera: «Comparar» · control segmentado Transcripción | Traducción · «hh:mm:ss → hh:mm:ss · N segmentos · K con diferencias» · ✕.
- Rejilla `38px | 1fr | 1fr | 1fr`: # · motor A con su tiempo (p. ej. «Qwen3-ASR 1.7B 41 s») · motor B («Whisper large-v3 63 s») · elegido. En Traducción, A y B son dos modelos de Ollama.
- Cada celda es un botón (fondo `#0d172a`, borde `#314057`, radio 7). La seleccionada lleva borde `#57b5fa` y halo de 1 px del mismo color. Las palabras distintas se resaltan con `#67c3ff2e` y texto `#eff4ff`. Las filas iguales van atenuadas, con «igual» en la columna elegido. Un texto vacío se muestra como «(sin texto)». En Transcripción, si un motor genera texto sobre silencio, lleva el chip «sin voz».
- Pie: «Clic en una celda para elegirla. Los tiempos incluyen la carga del modelo. Nada cambia hasta aplicar.» · «Todo A» · «Todo B» · primario «Aplicar N cambios» (desactivado si no hay ninguno). Si se elige «(sin texto)», el segmento se elimina.
- Rango: el segmento de origen, uno anterior y hasta 8 en total. El backend recibe ese rango, no una ventana fija de 30 s.

### 7. Menú «Exportar ▾»
Popover de 320 px anclado bajo el botón (`top:46px; right:10px`), padding 14, gap 9.
- «Antes de guardar»
- «✓ N segmentos con tiempos válidos»
- «⚠ N sin traducir **ver**» o «✓ Todo traducido» (esta línea se oculta si el idioma es Original)
- «⚠ N dudosos sin revisar **revisar**» o «✓ Sin dudosos pendientes»
- Selects de idioma (Español / Original / **Bilingüe**) y formato (SRT / VTT)
- Ruta de destino en 12 px muted
- Primario «Guardar junto al vídeo» · ghost «Descargar»

Los enlaces cierran el menú y activan el filtro correspondiente (y el panel Revisar en el caso de dudosos). Tras guardar aparece un toast abajo al centro (fondo `#163d31`, borde `#25664c`, texto `#8be2b1`, radio 9, padding `10px 14px`): «Guardado junto al vídeo: {nombre}.{idioma}.srt», que se cierra solo a los 2,6 s. El idioma «Bilingüe» es nuevo: cada segmento lleva el original y la traducción en dos líneas.

### 8. Ajustes
Accesible desde la biblioteca. Navegación lateral de 170 px (Modelos · Recetas · Revisión · Exportación) y contenido en paneles.
- **Modelos**: incluye la gestión que hoy vive en `model-ui.js`. En Transcripción, una fila por modelo con nombre, chip «por defecto», tamaño y botones Verificar / Borrar, y la nota sobre la caché compartida. En Traducción y mejora, los modelos instalados en Ollama con su tamaño.
- **Recetas**: lista de recetas guardadas.
- **Revisión**: casillas para cada criterio de dudoso.
- **Exportación**: patrón de nombre `{nombre}.{idioma}.{formato}`; si el archivo ya existe se añade un número.

El panel «Modelos y comparación» que hoy está bajo el vídeo **desaparece**: la gestión pasa a Ajustes y la comparación al modal.

---

## Cambios de backend necesarios
Rutas actuales relevantes en `backend/app/main.py`: `/api/projects`, `/api/projects/local`, `/start`, `/translate`, `/improve`, `/improve/undo`, `/compare-models`, `/cues/{cid}/translate`, `/cues/{cid}/compare-translations`, `/export/local`, `/pause`, `/resume`, `/cancel`, `/retry`. El descubrimiento de subtítulos está en `mac-worker/local_files.py` (`discover_subtitles`).

1. **Filtrar las fuentes por episodio.** En `discover_subtitles`, comparar cada candidato con el vídeo por la raíz del nombre y por `SxxEyy` (y `1x02`). Devolver `match: [...]` y `other_episodes: [...]`, con `recommended: true` en la mejor coincidencia. Criterio: idioma original del audio y, si no, inglés; preferir el archivo junto al vídeo, después la carpeta `Subs`, después la pista incrustada. Las pistas de imagen siguen ocultas, con su contador.
2. **Agrupación por serie.** Parsear `serie`, `season` y `episode` del nombre (o del título de la carpeta) y devolverlos en `as_project`. Las películas llevan `year` cuando se pueda extraer.
3. **Segmentos dudosos.** Añadir a cada cue `flag: null | "silence" | "repeat" | "low_confidence" | "out_of_chunk"` y `flag_resolved: bool`.
   - `silence`: energía o VAD del audio decodificado por debajo de un umbral en más del 80 % de la duración del cue. Se calcula en el worker por tramo, con el audio que ya está en memoria.
   - `repeat`: texto normalizado igual al del cue anterior, o una n-grama repetida dentro del cue.
   - `low_confidence`: si el motor ASR expone probabilidades (Whisper `avg_logprob` / `no_speech_prob`); en Qwen, omitir si no está disponible.
   - `out_of_chunk`: reutilizar la detección actual de `timing_warnings`.
   - Las fuentes .srt importadas no se marcan.
   - Endpoints: `PUT /cues/{cid}` acepta `flag_resolved`; `DELETE /cues/{cid}` es nuevo.
4. **Envolvente de audio para el mapa de voz.** `GET /api/projects/{pid}/envelope?start&end&buckets` devuelve un array de amplitudes normalizadas de 0 a 1 (RMS por bucket), cacheado por proyecto y pista. Además, `GET /envelope/overview` devuelve unos 400 buckets de todo el episodio.
5. **Procesado progresivo visible.** El proyecto ya guarda los tramos. Exponer en `task_progress` `chunk`, `chunks_total`, `processed_until` (en segundos) y `eta_seconds`. El frontend dibuja la zona pendiente a partir de `processed_until`.
6. **Mejora como propuestas.** `POST /improve` deja de sobrescribir y guarda `proposal` por cue. Endpoints nuevos: `POST /cues/{cid}/proposal/accept`, `POST /cues/{cid}/proposal/reject` y `POST /proposals/accept-all`. Con esto, `improve/undo` deja de ser necesario, aunque se puede conservar mientras exista la sesión de deshacer.
7. **Comparar por rango.** `POST /compare-models` acepta `{start, end}` (o `cue_ids`) y devuelve los resultados alineados por cue. La comparación de traducción por rango aplica lo mismo a `compare-translations`. `POST /apply-comparison` recibe `[{cue_id, field, value}]`, donde un `value` vacío borra el cue.
8. **Lote y recetas.** Tabla o JSON de recetas: `{id, name, source_pref, asr_model, asr_language, target_language, translation_model, improve_before_translate, flag_suspicious, export_when_clean}`. `POST /api/batches` recibe `{paths:[...], recipe_id}`, crea un proyecto por archivo y los encola. Las etapas automáticas (fuente según la receta, ASR, traducción) se encadenan; la revisión se detiene si hay dudosos. `GET /api/batches/{id}` devuelve el estado de cada etapa por episodio. El diálogo nativo (`choose_local_file`) debe permitir selección múltiple y carpetas.
9. **Exportación bilingüe** en `subtitles.export`: el original y la traducción en dos líneas por cue.
10. **Comprobaciones previas a exportar.** `as_project` devuelve `counts: {cues, untranslated, flagged_open, proposals}`.

## Estado del frontend
- Ruta: `library | batch | queue | settings | project:{id}`. Persistir en `localStorage` (`ss2-route`) y reflejarla en el hash.
- Por proyecto: `panel` (etapa abierta), `filter` (`all|sus|untr|prop`), `time` (posición de reproducción), `onVideo` (`original|tr`), `exportOpen`, `focus` (id del cue o null) y `compare` (`{cueId, mode}` o null).
- Sondeo: mantener el refresco actual cada 4 s para la biblioteca y la cola. En el proyecto activo, refrescar solo los cues nuevos o cambiados, sin reconstruir la lista entera (hoy `renderList` reconstruye todo). Conservar el foco y el cursor de los textareas al actualizar.
- Mantener la lógica actual de deshacer/rehacer y el estado de guardado de `editor-state.js` (⌘Z / ⌘⇧Z). El texto «Todos los cambios guardados» pasa a la barra inferior de la lista o junto a los filtros.

## Tokens
Usar las variables de `tokens/colors.css` (valores de hoy en `frontend/index.html`). Las más usadas en este diseño:
- Fondos: app `#0c1220` · barras `#11192a` · paneles `#141e31` · campos `#0d172a` · fila hover `#19243a` · seleccionado `#203451` · cue activo `#20314e` · cabecera de tabla `#1b2942`.
- Líneas: `#263148` (suave) · `#2b3850` (panel) · `#222e42` (filas) · `#314057` (campos) · `#34425c` (textarea) · `#405473` (popover).
- Texto: `#e8edf7` · `#eff4ff` · `#c4d9f7` (timecode) · `#aebdd4` · `#a9bad2` · `#94a3b8` (muted) · `#7f8fa8` (sutil) · `#6d7f99` (tenue).
- Azul: `#67c3ff` acento / en curso · `#57b5fa` selección · `#4eacec` progreso / voz · `#1976d2` primario (hover `#1f86ea`, borde `#278bf0`) · `#2683d3` foco.
- Verde: `#73deb3` listo · `#8be2b1` sobre `#163d31` / `#25664c`.
- Rojo: `#ff8495` · `#ffadb7` · `#4a202c`.
- **Nuevo, ámbar de dudosos:** `--amber:#f0a75a` · `--amber-bg:#2e2418` · `--amber-line:#6b4a24`.
- Tipografía: Inter (con fallback a system-ui). Escala: 10.5 / 11 / 12 / 12.5 / 13 / 14 / 16 / 26 px; pesos 400 / 600 / 650 / 700; cifras tabulares en tiempos.
- Radios: 6 (campos) · 7 (textarea, chips de etapa) · 8 (botones, menús) · 9 (toast) · 10 (paneles, vídeo) · 12 (modal) · 20 (chips).
- Sombras, solo en elementos flotantes: `0 8px 24px #0008`.
- Cabecera: 48 px (antes 40).
- Movimiento: solo el pulso de etapa en curso y la barra indeterminada actual; respetar `prefers-reduced-motion`.

## Iconografía
Sigue sin haber librería de iconos: se usan caracteres Unicode, como ahora. ⇄ menú del segmento · ✓ hecho · ⚠ aviso · ‹ › navegación · ⌄ plegado · ▶ / ❚❚ reproducción · ⛶ pantalla completa · ✕ cerrar · ● Local. No añadir emoji.

## Orden de implementación sugerido (todo en una entrega)
1. Backend: campos y endpoints nuevos (puntos 1–10), con tests en `tests/test_api.py`, `test_local_files.py` y `test_worker.py`.
2. Frontend: router y pantalla Biblioteca; retirar el panel lateral.
3. Espacio de trabajo: cabecera con etapas, mapa de voz, split, paneles de etapa y lista con filtros.
4. Modo foco, comparar y menú de exportar.
5. Lote, cola y ajustes (mover `model-ui.js` a Ajustes).
6. Actualizar `tests/frontend.test.cjs` y `editor-state.test.cjs`, y el README del repo con el nuevo flujo.

## Criterios de aceptación
- Abrir un episodio muestra solo las fuentes de ese episodio, con una recomendada preseleccionada.
- Durante la transcripción, los segmentos aparecen en la lista según termina cada tramo y se pueden editar.
- Los dudosos se ven en el mapa de voz y en la lista, y se pueden recorrer con A / B / → / Esc.
- La comparación muestra dos motores lado a lado y solo aplica lo elegido.
- La mejora nunca cambia el texto sin aceptación.
- Exportar avisa de lo que falta antes de guardar.
- Un lote de N episodios avanza solo hasta la revisión y la cola indica qué espera a una persona.
- El resto del comportamiento actual (pausar, reanudar, cancelar, reintentar, papelera, «Volver a transcribir», deshacer/rehacer) sigue funcionando.
