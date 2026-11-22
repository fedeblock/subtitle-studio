# Previsualización de pistas y navegación por segmentos

**Objetivo:** identificar pistas sin etiquetas antes de importar/transcribir y saltar al mark-in al seleccionar un segmento.

**Diseño:** la API recupera, solo en borrador, una muestra limitada de la pista de subtítulo elegida mediante el gateway autenticado. Para audio, FFmpeg genera en memoria una muestra MP3 de hasta 30 segundos desde la posición actual del vídeo, con índice de pista verificado contra el fichero seleccionado; un reproductor de muestra bajo el vídeo permite escucharla y actualizar su posición. No se copia el vídeo ni se necesita cargar MLX/Ollama. Seleccionar o enfocar una fila mueve el vídeo al mark-in sin arrancar la reproducción automáticamente; al cambiar de campo dentro de la misma fila no vuelve a saltar. Conservar el reproductor y los cambios pendientes durante el sondeo.

- [x] Probar selección/validación y contenido de pistas reales, sin datos de usuario.
- [x] Mostrar muestras de subtítulos y audio en la interfaz y manejar respuestas tardías y errores.
- [x] Sincronizar selección de filas con mark-in en modo editable y lectura.
- [x] Ejecutar suite, integración y documentación sin interrumpir trabajos existentes.
