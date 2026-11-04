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
