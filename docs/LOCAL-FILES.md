# Archivos locales sin duplicación

Requisito confirmado el 2026-11-04: selector nativo de macOS; procesar el original sin copiarlo.

- El botón Abrir archivo local solicita al gateway autenticado abrir el selector de macOS.
- Solo el selector nativo aporta la ruta; la API web no admite rutas arbitrarias.
- data/<UUID>/source.json conserva una referencia al archivo original. La BD conserva nombre/estado/subtítulos; no hay migración destructiva.
- El gateway sirve el original por rangos para previsualizarlo, a través de la API Docker, sin buffering en disco. MLX lee la ruta original.
- Los proyectos previos con source.mp4/etc. siguen funcionando. No se borra ninguna copia existente.
- Si se mueve/elimina el original, se informa explícitamente. Los montajes externos deben permanecer disponibles.
- El reproductor permanece montado durante los sondeos de estado y las transiciones de procesamiento.

Cobertura automatizada: referencia sin copia, cancelar selector, fichero ausente, rechazo de rutas/symlinks no autorizados, transcripción sobre original, streaming Range/HEAD, reproducción estable durante polling y suite completa.


## Fuentes de subtítulos

Tras abrir un original, el proyecto queda en borrador hasta elegir una fuente y acción:

- Transcripción del audio con MLX.
- Archivos SRT/VTT/ASS/SSA en la misma carpeta, `Subs` o `Subtitles` (sin distinguir mayúsculas), incluyendo un nivel de subcarpetas. Máximo 200 candidatos externos, 20 MiB por subtítulo; no se siguen enlaces simbólicos.
- Pistas incrustadas de texto detectadas con FFprobe. FFmpeg extrae únicamente el texto a memoria; no remultiplexa ni copia el vídeo. PGS/VobSub y otros formatos no compatibles se muestran deshabilitados con indicación de OCR/conversión.

No se elige automáticamente un subtítulo por nombre o idioma: el usuario puede escoger entre varias versiones. `Solo editar` importa texto y tiempos sin inferencia; `Traducir al español` conserva el original y traduce las entradas pendientes. Una importación inválida conserva el borrador para elegir otra fuente. Los originales y sidecars nunca se sobrescriben; Exportar descarga un archivo nuevo.

La previsualización transmite bytes dentro del propio equipo (navegador → API Docker → gateway nativo). No se guarda otra copia del vídeo. La compatibilidad MKV depende del contenedor/códecs admitidos por el navegador; importar sus subtítulos no garantiza reproducción. Si se cambia una ruta por un enlace simbólico se rechaza la referencia.

## Validación del 2026-11-04

- Suite: 34 pruebas Python y 6 pruebas Node, incluidas extracción de un MKV sintético real, importación para editar/traducir, cancelación, original movido, rechazo de redirección por symlink y conservación del elemento de vídeo al actualizar estados.
- Construcción Docker de API, worker y frontend correcta.
- El proyecto de película anterior conserva sus 1162 segmentos y 84 traducciones. Su fallo de traducción se reprodujo como `Empty translations` de Ollama; la versión nueva muestra el detalle del gateway para facilitar el diagnóstico. No se eliminó ni convirtió su copia existente.
- Integración con servicios reales: Range 206 y HEAD 200 sobre el original; detección de dos sidecars y una pista SubRip interna; importación para editar y exportación correctas. El proyecto de prueba `5cdd908f-2583-460c-9707-b59bde775efb` conserva solo `source.json`; fixture en la carpeta temporal `subtitle-studio-local-p2ehc7n2`.
- La automatización gráfica de macOS se bloqueó al intentar controlar el selector; este terminó por timeout sin crear proyecto. No se confirma la selección manual real. Las pruebas automatizadas sustituyen únicamente la selección del sistema, no el acceso al archivo ni la extracción de subtítulos.

## Edición y traducción

- La tabla incluye número, mark-in, mark-out, texto original y traducción. El guardado se inicia al salir del campo; la cola ordenada conserva los cambios si falla la conexión. Deshacer/Rehacer guarda la reversión y mantiene su historial durante la sesión; al cambiar de proyecto o recargar se pierde el historial de edición.
- Ollama puede omitir una entrada del JSON. Se reproduce con el lote posterior a 00:05:38.821: 169 tokens de entrada frente a una ventana de 8192; cinco respuestas válidas y una vacía. Pedir la entrada omitida individualmente devolvió texto. Ahora se reintenta solo cada entrada vacía; si el lote devuelve claves incorrectas o JSON inválido se solicita cada entrada individualmente. Si vuelve a fallar, se conserva lo guardado anteriormente.
- La mejora opcional del original hace una pasada de Ollama, guarda una instantánea con el texto anterior y permite restaurar la última mejora sin sobrescribir ediciones posteriores. No modifica tiempos ni traducciones ya existentes. Debe revisarse la corrección y puede tardar.

- Durante la validación real la traducción superó 00:05:38.821 y alcanzó 132 segmentos antes de que Ollama devolviera claves inesperadas; esta segunda respuesta motivó el reintento individual del lote. La corrección del modelo se comprobó en un ejemplo sintético; no se ha validado la calidad de una película completa.

- Tras el segundo ajuste, el proyecto de la película que referencia el original se reanudó y superó los 192 segmentos traducidos. Continúa en segundo plano; no se ha comprobado aún el final completo de la traducción. La antigua copia del proyecto `ff12559a-d294-4564-81b2-ff1d83101699` no estaba disponible al reintentarlo; se usó el proyecto más reciente `913ed2a0-70df-43d0-b952-eeb91f71e65f`, con textos y tiempos idénticos y original accesible.
- Verificación final: 40 pruebas Python y 13 Node; imágenes Docker construidas, servicios activos y prueba de autoguardado/deshacer en navegador sobre proyecto sintético. Revisión adicional de las carreras de guardado y protección de conflictos entre pestañas.

## Error de sentencias preparadas en mejoras sucesivas

El 2026-11-04 la mejora del proyecto de la película falló con `DuplicatePreparedStatement: _pg3_0`; la reversión recuperó el texto y el proyecto quedó listo. La traducción ya había terminado. La causa se reprodujo con PostgreSQL real y consultas `SELECT`: RQ crea un proceso hijo por trabajo y ambos heredaban una conexión ya abierta en el proceso principal. Tras varias transacciones confirmadas, el segundo hijo intentaba preparar un nombre que seguía existiendo en la sesión compartida.

`ForkSafeWorker` reemplaza el pool del hijo con `engine.dispose(close=False)` antes de que RQ ejecute cada trabajo, sin cerrar las conexiones del padre. Cobertura: prueba unitaria del orden; `scripts/test-fork-postgres.py` ejecuta dos hijos consecutivos con PostgreSQL real y valida que cada proceso tenga una conexión diferente; dos mejoras y reversiones reales con Ollama y RQ sobre un proyecto sintético, sin modificar la película. Suite completa: 41 pruebas Python y 13 Node. Se conserva el proyecto de prueba `fdfc4b94-cc1c-4317-93f7-471b227d01b0`.

Referencias técnicas: [SQLAlchemy: conexiones y procesos bifurcados](https://docs.sqlalchemy.org/en/21/core/connections.html#engine-disposal) y [Psycopg: concurrencia y procesos](https://www.psycopg.org/psycopg3/docs/advanced/async.html#concurrent-operations).
