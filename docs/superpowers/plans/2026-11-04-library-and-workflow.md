# Biblioteca y flujo de subtítulos

**Objetivo:** biblioteca con papelera recuperable, exportación junto al original sin sobrescrituras, elección de pista de audio o subtítulos y posibilidad de mejorar y revisar segmentos antes/durante la traducción.

**Diseño:** tabla auxiliar de papelera sin borrar archivos ni proyectos; el usuario puede quitar un proyecto o vaciar la biblioteca y restaurar lo quitado. Los trabajos activos no se ocultan. El gateway nativo guarda SRT/VTT como hermano del vídeo con creación exclusiva y sufijo numérico; el navegador ofrece descarga alternativa. Para copias históricas sin ruta original conocida se mantiene descarga explícita. FFprobe detecta índices globales de pistas y FFmpeg decodifica la elegida a memoria para MLX; no se duplica el vídeo. Los subtítulos importados y transcripciones pueden quedar listos para corregir, mejorar y luego iniciar la traducción de pendientes. Durante el procesamiento se muestran segmentos existentes en modo lectura con actualización sin reemplazar el reproductor.

- [x] Pruebas y API para quitar/restaurar proyectos conservando los datos y rechazando trabajos activos.
- [x] Detección y selección validada de pistas de audio; extracción de pista concreta y prueba de MKV real.
- [x] Exportación local junto al original, sin sobrescribir y con prueba de colisiones/permisos.
- [x] Flujo de revisión/mejora antes de traducción y vista de segmentos durante procesamiento.
- [x] Integración, documentación y comprobación de servicios sin interrumpir el trabajo existente.
