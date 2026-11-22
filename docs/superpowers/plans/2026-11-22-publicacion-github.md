# Plan de publicación de Subtitle Studio

**Objetivo:** publicar un MVP reproducible en GitHub sin alterar el historial existente ni incluir medios, subtítulos, credenciales o datos personales.

**Estado de partida:** `feature/mvp-setup` sigue a `origin/feature/mvp-setup`; el repositorio ya existe y es privado. La entrega será un único commit nuevo sobre esa rama. `origin/main` y su historia se conservan; no se reescribirá el historial ni se usará `push --force`.

## 1. Licencia y película de demostración

- [x] Licencia del código: MIT, incluyendo el aviso de copyright.
- [x] Película propuesta: *Sintel* (Blender Foundation), con diálogo y versiones disponibles con subtítulos. Licencia de la película: CC BY 3.0; es independiente de la licencia del código.
- [x] Descargar el tráiler oficial de Blender en `data/demo/sintel_trailer-720p.mp4`, ignorado por Git, y verificarlo con ffprobe: 52,208 s, H.264 y audio AAC; no incluye pistas de subtítulos. Este tráiler sirve para capturas y no sustituye a la película con subtítulos para probar pistas incrustadas.
- [x] El usuario dispone de la película completa en un volumen local: `ffprobe` confirma 14:48, vídeo MPEG-4 y una pista de audio AC-3. Hay cuatro SRT vecinos de procedencia aún no comprobada; ni los originales ni su ubicación se incorporan a Git.
- [ ] Crear capturas y demostraciones con una biblioteca de prueba aislada; revisar que no aparezcan rutas, nombres, vídeos ni datos personales.
- [ ] Añadir junto a cada captura o demostración el crédito de la obra, su fuente, licencia y modificaciones. Si se exhibe la película completa, conservar sus créditos finales conforme a las indicaciones del proyecto.

Fuentes: <https://durian.blender.org/about/> y <https://durian.blender.org/download/>; licencia: <https://creativecommons.org/licenses/by/3.0/>. Verificar la licencia específica de cualquier pista de subtítulos de terceros antes de redistribuirla.

## 2. Revisión de la entrega

- [ ] Actualizar README y handoff: se corrigieron varias contradicciones y se quitó la ruta personal del handoff; quedan por revisar los flujos completos y el arranque desde cero.
- [ ] Revisar los archivos nuevos y su procedencia. El prototipo autocontenido incluye JavaScript y fuentes empaquetados: conservar ambos HTML de referencia localmente y excluirlos de la entrega mientras no se revisen sus licencias; se incluyen la especificación, los tokens y las fuentes legibles.
- [ ] Revisar diferencias y archivos ignorados antes de preparar el commit; verificar que `.env`, `data/`, medios, modelos, cachés y volúmenes no se incluyan.
- [ ] Revisar también el historial completo que será visible al cambiar la visibilidad del repositorio. Búsqueda preliminar: sin coincidencias para patrones comunes de tokens o claves privadas; se encontró una ruta de usuario en el commit `86a434d`, aunque se corrija el archivo actual. Una búsqueda por patrones no garantiza ausencia de secretos o información privada. No reescribir historial sin una decisión explícita.
- [ ] Revisar dependencias y licencias de distribución; documentar límites de compatibilidad y de uso comercial de los modelos elegidos sin atribuirles la licencia MIT del código.
  Comprobación parcial de metadatos de paquetes instalados: ffsubsync, mlx-whisper y MLX declaran MIT; mlx-qwen3-asr declara Apache-2.0. Esto no verifica las licencias de todas las dependencias transitivas ni de los pesos de los modelos.

## 3. Verificación

- [x] Ejecutar `npm test` (108 pruebas), `.venv/bin/python -m pytest -q` (153 pruebas; una advertencia de desuso de AnyIO), `git diff --check` y la validación de Docker Compose sin mostrar valores de `.env`.
- [x] En una copia temporal aislada con macOS Apple Silicon, ejecutar `scripts/setup.sh` y validar Compose; no se instalaron servicios ni se descargaron modelos.
- [x] Ejecutar la prueba Docker `scripts/smoke.py` con inferencia simulada: API, worker, PostgreSQL, Redis, edición, exportación, recuperación y lote. Sus contenedores se detuvieron sin borrar los volúmenes ni los datos.
- [ ] Completar la prueba desde cero con modelos reales, el servicio nativo y medios reales; la prueba simulada no la sustituye.
- [ ] Probar con el vídeo de demo: abrir sin copia, elegir audio/subtítulo, previsualizar, editar, deshacer, transcribir, traducir, comparar y exportar con nombre nuevo. Anotar lo que no se pueda verificar.
- [ ] Comprobar capturas y demos en distintos tamaños de ventana y sus atribuciones.

## 4. Commit y GitHub

- [ ] Revisar la lista exacta de archivos a incluir y el diff preparado; no usar `git add -A` sin revisión.
- [ ] Crear un único commit de entrega en `feature/mvp-setup` y comprobar su contenido y la ausencia de datos excluidos.
- [ ] Consultar el estado actualizado de las ramas remotas. Subir la rama sin forzar; si existe divergencia, preservar ambas historias y resolverla sin sobrescribir.
- [ ] Preparar un PR hacia `main` con resumen, pruebas, capturas autorizadas y limitaciones. Revisar antes de integrar.
- [ ] La visibilidad pública del repositorio es un paso separado: realizarla solo cuando la auditoría del historial y la revisión de la entrega estén completas y se haya confirmado la decisión de hacer público el repositorio.
