# Nota de testeo: sincronización y modelos

**Versión a revisar:** rama `feature/mvp-setup`, desde el commit `67e8fdc`. La aplicación local debe estar actualizada con esa rama; la versión `0.1.0` de npm es anterior y no incluye estos cambios.

**Objetivo:** comprobar el ajuste global por desplazamiento o FPS, la previsualización y la recuperación, y la información de los modelos descargados. Anota para cada caso si pasa o falla y cualquier diferencia observada.

## Preparación

1. Abre [Subtitle Studio local](http://localhost:3000/) en el Mac. Esta dirección funciona cuando los servicios locales están arrancados.
2. Utiliza un vídeo local y un SRT que puedas emplear para pruebas, por ejemplo *Sintel* y uno de los SRT de su carpeta. El selector abre el vídeo por referencia; no necesita copiarlo. La licencia de una pista de subtítulos puede ser distinta a la de la película si se van a publicar capturas o ejemplos.
3. Abre el vídeo como un proyecto de prueba y selecciona **Usar esta fuente** para importar la pista al editor. No necesitas iniciar una transcripción ni una traducción. Si vas a aplicar cambios, emplea un proyecto de prueba: se modifican las marcas guardadas en ese proyecto, no el archivo SRT original.
4. Apunta los tiempos de una entrada cercana al inicio y otra cercana al final. Si la pista incluye traducciones, comprueba también que se conservan sus textos.

Los ajustes están en **Herramientas de subtítulos → Ajustar tiempos globalmente**. La pantalla de propuesta ocupa la columna derecha y mantiene el vídeo visible a la izquierda.

## Casos de prueba

### 1. Desplazamiento positivo

- [ ] Deja vacíos los dos FPS, introduce `2` segundos y pulsa **Previsualizar ajuste**.
- [ ] Cada entrada muestra su tiempo anterior y el nuevo, dos segundos más tarde. Comprueba una entrada al principio y otra al final.
- [ ] Alterna **Ver tiempos actuales** y **Ver propuesta**; selecciona una entrada en la lista y comprueba que el vídeo salta al tiempo correspondiente. Reproduce el momento para comparar el subtítulo superpuesto.
- [ ] Pulsa **Descartar**. La tabla debe conservar los tiempos originales.

### 2. Adelanto y tiempos negativos

- [ ] Previsualiza un desplazamiento negativo que deje todos los tiempos en cero o más; las entradas deben adelantarse la cantidad indicada.
- [ ] Introduce un desplazamiento lo bastante negativo como para que alguna entrada quede antes de `00:00:00.000`. Debe aparecer un error y no debe aplicarse ninguna modificación. La aplicación no recorta ni elimina automáticamente esas entradas.

### 3. Conversión de FPS

- [ ] Con desplazamiento `0`, introduce `24` en **FPS de los subtítulos** y `25` en **FPS del vídeo**. Previsualiza: el tiempo nuevo debe ser el anterior multiplicado por `24/25`.
- [ ] Ejemplo calculado: una entrada en `00:01:00.000` debe aparecer en `00:00:57.600`. No es necesario que tu pista tenga exactamente esa entrada: contrasta una de sus marcas con la misma fórmula.
- [ ] Repite invirtiendo los FPS (`25` → `24`): las marcas se desplazan progresivamente más tarde. Para `23.976`, `29.97` y `59.94` se usan las tasas fraccionarias 24000/1001, 30000/1001 y 60000/1001.
- [ ] Introduce solo uno de los FPS: debe solicitar ambas tasas. Con los dos vacíos no hay conversión.
- [ ] Combina `24` → `25` con `2` segundos: una marca de `00:01:00.000` se propone en `00:00:59.600`. El desplazamiento se suma después de convertir.

**Precaución:** que un archivo informe un FPS distinto no demuestra que necesite conversión. Contrasta el principio y el final de versiones cuya duración o velocidad realmente difieran. Los cortes añadidos o eliminados en mitad de la película no se corrigen necesariamente con una sola transformación global.

### 4. Aplicar y deshacer

- [ ] En el proyecto de prueba, prepara un desplazamiento positivo y pulsa **Aplicar propuesta**. Comprueba que las nuevas marcas aparecen en la tabla y que los textos originales y las traducciones se conservan.
- [ ] Sin cerrar ni recargar la sesión y sin editar las marcas afectadas, usa **Herramientas de subtítulos → Deshacer sincronización**. Las marcas deben volver a sus valores anteriores.
- [ ] Si otra pestaña cambia las marcas después de generar una propuesta, la aplicación debe rechazar su aplicación y pedir una nueva propuesta. La recuperación de sincronización solo dura la sesión actual.
- [ ] Comprueba que el vídeo y el SRT originales siguen en su sitio. Si exportas para comprobar el resultado, utiliza un nombre nuevo y revisa el destino antes de guardar.

### 5. Ubicación y gestión de modelos

- [ ] Abre **Audio y modelos → Modelos de transcripción (ASR)**. Para los modelos detectados se deben mostrar nombre, tamaño y rutas en el Mac; Qwen puede mostrar rutas separadas para ASR y alineador.
- [ ] En la configuración habitual, las carpetas están bajo `~/.cache/huggingface/hub`. Si el entorno tiene otra caché configurada, debe mostrarse la ruta realmente detectada.
- [ ] Comprueba que la interfaz explica que los LLM de traducción y mejora se gestionan en Ollama. Sus modelos instalados se pueden listar en Terminal con `ollama list`.
- [ ] No pulses **Borrar** durante esta revisión salvo que quieras eliminar ese modelo también para otras aplicaciones que compartan la caché.

## Resultado y seguimiento

| Caso | Pasa / falla / no probado | Observaciones |
| --- | --- | --- |
| Desplazamiento positivo y descartar | | |
| Desplazamiento negativo y protección | | |
| Conversión de FPS y combinación | | |
| Aplicar y deshacer | | |
| Ubicación de modelos y Ollama | | |

Cuando informes de un fallo, indica el caso, los FPS y desplazamiento introducidos, una marca original y la esperada, y qué ocurrió. Evita incluir rutas personales, archivos o capturas con contenido que no quieras compartir públicamente.

**Comprobado previamente:** 115 pruebas de interfaz y 153 de Python; previsualización de un desplazamiento descartada en un proyecto existente y consulta de las rutas reales. **Pendiente:** validación completa de conversión, aplicación y deshacer sobre medios reales; los resultados automatizados no la sustituyen.
