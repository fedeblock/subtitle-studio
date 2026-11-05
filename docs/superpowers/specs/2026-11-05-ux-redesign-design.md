# Rediseño de la experiencia de Subtitle Studio

Fecha: 2026-11-05
Estado: diseño aprobado pendiente de plan

## Intención

Subtitle Studio funciona, pero la interfaz está organizada alrededor de la
aplicación en vez de alrededor del trabajo. El trabajo es: **ver el vídeo y
arreglar los subtítulos**. Todo lo demás —la marca, los títulos de sección, los
textos explicativos, la insignia de procesamiento local, el pie con los nombres
de los modelos— ocupa hoy aproximadamente la mitad vertical de la pantalla antes
de que aparezca el primer segmento, y obliga a trabajar con el vídeo pequeño y
la tabla asomando por debajo.

Además hay una separación artificial entre "ver" y "editar" que no corresponde a
nada real en el sistema: son la misma tabla con un atributo `readonly` y una
bandera guardada en disco. Esa puerta obliga a decidir antes de haber visto nada
qué vas a hacer con un subtítulo que todavía no conoces.

Este rediseño quita la decoración, funde las dos vistas en una sola siempre
editable, reordena la elección de fuente alrededor de cómo se buscan de verdad
los subtítulos, y añade la capacidad que falta para poder terminar el trabajo
sin salir de la herramienta: traducir a un idioma que no sea el español.

Insertar y borrar segmentos se diseñó aquí y **queda aplazado a una versión
mayor** (decisión de Federico, 2026-11-05). Lo decidido se conserva en este
documento, marcado, para que esa versión no tenga que volver a decidirlo.

## Objetivos

1. El vídeo y la lista de subtítulos son lo único que ocupa espacio de forma
   permanente. Todo lo demás se pliega, se encoge o desaparece.
2. Una sola vista de subtítulos, siempre editable salvo mientras corre un
   proceso.
3. La biblioteca es plegable y las acciones de un proyecto están en el proyecto.
4. Elegir fuente es un paso corto y agrupado, no un desplegable plano de trece
   entradas con cosas que no se pueden usar.
5. Se puede traducir a un idioma destino elegido, no solo al español.
6. Mientras corre una traducción o una mejora se ven los cambios llegando y se
   puede detener la operación.

## No objetivos

- Varios idiomas de traducción conviviendo en el mismo proyecto. Siempre es uno
  a la vez. (Decisión explícita de Federico.)
- **Insertar y borrar segmentos. Aplazado a una versión mayor.** No entra en
  este ciclo, aunque su diseño esté cerrado más abajo.
- OCR para pistas de subtítulo de imagen (PGS, VobSub). Se siguen sin soportar;
  el cambio es que dejan de mostrarse.
- Dividir y unir segmentos, forma de onda, diarización, reglas CPS/CPL, quemado
  de subtítulos. Fuera del alcance, como ya dice el README.
- Autenticación, despliegue remoto, multiusuario. Sigue siendo una herramienta
  local de una sola persona.
- Rehacer el backend de ASR, el alineador o la gestión de memoria MLX.

## Anti-objetivos

Cosas que harían fracasar esto aunque técnicamente funcione:

- **Perder trabajo del usuario.** El proyecto tiene una ética clara de no
  destruir nada: la papelera es recuperable, la mejora guarda instantánea previa
  y se puede revertir, el reintento conserva traducciones existentes, no hay
  borrado definitivo desde la interfaz. Nada de este rediseño puede introducir
  una acción que borre trabajo sin vuelta atrás.
- **Minimalismo que esconde estado.** Quitar decoración no es quitar
  información. Si un proyecto está procesando, ha fallado, o tiene cambios sin
  guardar, eso tiene que verse. El objetivo es quitar lo que no dice nada, no
  quitar lo que avisa.
- **Una interfaz bonita que obliga a más clics.** Si plegar la biblioteca o
  agrupar las fuentes añade pasos al recorrido habitual, no sirve.

## Restricciones verificadas en el código

Estas no son suposiciones; están comprobadas en el repositorio en el commit
`4b2900a`.

1. **No hay migraciones de esquema.** `backend/app/core.py:17` solo llama a
   `Base.metadata.create_all`, que no añade columnas a tablas PostgreSQL ya
   existentes. Cualquier dato nuevo por proyecto debe ir a
   `data/<UUID>/source.json` mediante `save_workflow`
   (`backend/app/project_sources.py:14`), que es el precedente existente, o
   acompañado de un plan de migración explícito.
2. **"Ver" y "editar" ya son la misma tabla.** `editorMarkup(cues, project,
   readOnly)` en `frontend/app.js:423` genera el mismo marcado; `readOnly` solo
   añade el atributo. `POST /api/projects/{id}/edit-mode`
   (`backend/app/main.py:432`) únicamente cambia `action` de `"view"` a
   `"edit"` en `source.json`. No hay transición de estado ni trabajo de datos
   detrás.
3. **La edición está bloqueada durante el procesamiento, en el servidor.**
   `PUT /api/projects/{pid}/cues/{cid}` (`backend/app/main.py:655`) devuelve 409
   si el estado no es `ready` o `failed`. El bloqueo es real y se queda.
4. **No existe ningún endpoint para crear ni borrar segmentos.** Solo `PUT` de
   uno existente. Los segmentos tienen una columna `position` entera
   (`backend/app/core.py:45`) y se leen ordenados por ella.
5. **Traducción y mejora ya guardan lote a lote.** Ambas procesan en lotes de 6
   con `db.commit()` dentro del bucle (`backend/app/worker.py:92-111` y
   `132-163`) y actualizan `progress`. Mostrar los cambios en vivo es trabajo de
   interfaz, no de worker.
6. **No existe cancelación de ninguna clase.** No hay bandera, ni endpoint, ni
   comprobación en el bucle del worker. Es capacidad nueva.
7. **Una inferencia nativa ya iniciada no se puede abortar.** Lo dice el README
   y es consecuencia de cómo el gateway serializa MLX. Por tanto detener solo
   puede significar "no empezar más lotes".
8. **ASR entrega todo al final.** No hay resultados parciales que mostrar
   mientras transcribe, y no es una operación por lotes.
9. **El idioma de traducción está escrito en el prompt.**
   `mac-worker/server.py:350` fija "español de España". Cada segmento tiene una
   única columna `translated` (`backend/app/core.py:49`).
10. **Los archivos de subtítulo ya se filtran por extensión.**
    `mac-worker/local_files.py:62` solo acepta `.srt`, `.vtt`, `.ass`, `.ssa`, y
    todos se marcan `supported: True`. Lo único que puede venir sin soportar son
    pistas incrustadas con códec fuera de `TEXT_CODECS` (línea 89), que hoy se
    listan deshabilitadas con el texto "requiere OCR/conversión".
11. **"Revertir última mejora" restaura por id de segmento** desde una
    instantánea (`backend/app/main.py:521-554`) y rechaza la reversión si
    sobrescribiría una edición posterior.
12. **Deshacer/rehacer es por campo y vive solo en memoria del navegador**
    (`frontend/editor-state.js`), durante la sesión del proyecto.

## El recorrido

Así es como se usa la herramienta, en orden, y es el orden en el que debe
leerse la interfaz:

1. **Abrir un vídeo.** Desde la biblioteca o con el diálogo nativo de macOS. El
   original no se copia nunca.
2. **Elegir la fuente de los subtítulos.** Una de cuatro procedencias: una pista
   de texto incrustada en el contenedor, un archivo de subtítulo junto al vídeo,
   un archivo dentro de la carpeta `Subs`/`Subtitles`, o transcribir el audio
   con ASR. Si se elige ASR, hace falta además decir qué pista de audio.
3. **Trabajar.** Ver el vídeo con los subtítulos encima, corregir texto y
   tiempos, lanzar la mejora de transcripción,
   lanzar la traducción al idioma elegido.
4. **Exportar.** Guardar junto al vídeo o descargar, en SRT o VTT, en original o
   traducido.

Los pasos 3 y 4 no son fases secuenciales: se vuelve de uno a otro todo el rato.
El paso 2 sí ocurre una sola vez por proyecto.

## Decisiones tomadas

Todo lo de esta sección lo decidió Federico y no está a discusión del
constructor.

### Estructura general

- La cabecera actual (marca grande + insignia "Procesamiento local" en una
  franja propia), el título "Proyectos", el párrafo descriptivo y el pie
  "Qwen3-ASR · MLX · Ollama" ocupan espacio que pertenece al vídeo y a los
  subtítulos. Hay que reducirlos drásticamente.
- La insignia de procesamiento local **se queda**, pero pequeña. Es una promesa
  del producto, no decoración; lo que sobra es su tamaño.
- La biblioteca **se puede plegar** hasta desaparecer, y no necesita el
  encabezado "Biblioteca".

### Biblioteca

- **Quitar un proyecto de la biblioteca se hace desde el proyecto en la lista**,
  no desde un botón en la esquina opuesta de la pantalla. Esto es seguro porque
  quitar mueve a la papelera recuperable, no borra.

### Vista única

- Desaparece la distinción entre "Ver subtítulos" y "Editar o mejorar". Hay una
  sola vista y es editable.
- Desaparece el desplegable **Acción** del paso de elección de fuente. Eliges
  fuente y entras directo a la vista editable.
- Transcribir con ASR **no es una acción**: es una de las fuentes posibles, la
  que se usa cuando no hay ningún subtítulo aprovechable.
- Mejorar y traducir son acciones que se lanzan **desde dentro** de la vista,
  cuando ya has visto el material.

### Elección de fuente

- Las pistas incrustadas que no se pueden usar (subtítulos de imagen: PGS,
  VobSub) **no se muestran**. Hoy aparecen deshabilitadas; deben desaparecer de
  la lista.
- La lista debe venir **agrupada por procedencia** (pistas del contenedor,
  archivos junto al vídeo, carpeta `Subs`) en vez de ser un desplegable nativo
  plano. En el caso real que motivó esto había trece entradas mezcladas.

### Insertar y borrar segmentos · aplazado a una versión mayor

Nada de esta sección entra en el ciclo actual. Se conserva porque está decidido
y porque la fase 5 toca el mismo editor: quien la construya debe saber que esto
llegará.

- Se puede insertar un segmento **antes o después** de uno existente.
- **Si no hay hueco, se rechaza y se avisa.** Es decir: si el mark-out del nuevo
  segmento sería inmediato al mark-in del siguiente, o se solaparía con él, la
  inserción no se realiza. No se desplazan ni se acortan los segmentos vecinos
  automáticamente.
- El segmento nuevo nace vacío y cuenta como pendiente de traducir.

### Traducción

- El idioma destino se elige. Traducir deja de ser "traducir al español" y pasa
  a ser "traducir a este idioma".
- **Siempre un idioma a la vez por proyecto.** No conviven dos traducciones. Se
  mantiene la columna única `translated`.

### Procesos en marcha

- Mientras corre una traducción o una mejora, **se ven los cambios llegando**,
  no solo un porcentaje.
- Se puede **detener la operación**.

## Decisiones mías

Las tomo yo porque hacen falta para que esto sea construible y no cambian lo que
Federico pidió. Son revisables.

- **Dónde vive el idioma destino: en `source.json`, no en una columna nueva.**
  Por la restricción 1: `create_all` no migra tablas existentes y los proyectos
  del usuario ya están en PostgreSQL. `save_workflow` ya guarda ahí
  `selected_source`, `action` y `audio_index`. El idioma destino es del mismo
  tipo de dato. Lo mismo aplica a cualquier bandera nueva por proyecto.
- **Borrar segmentos entra en el alcance.** Federico pidió insertar
  explícitamente y no mencionó borrar, pero una lista en la que solo se puede
  añadir no es editable de verdad, y la mitad del coste (endpoint nuevo,
  renumerar `position`, encajar con deshacer) se paga una sola vez para las dos
  operaciones.
- **Detener significa "no empezar más lotes", y lo ya guardado se conserva.**
  Por las restricciones 5, 6 y 7. El proyecto queda utilizable con la parte
  traducida o mejorada que alcanzó a completarse, y se puede retomar: el
  reintento existente solo rellena entradas vacías, así que el camino ya está
  hecho. El estado al detener debe distinguirse de un fallo.
- **Detener no se ofrece durante ASR.** Por las restricciones 7 y 8: no hay
  lotes que interrumpir y no hay resultado parcial que conservar. Ofrecer un
  botón que no puede cumplir es peor que no ofrecerlo.
- **Quitar el ancho máximo de 1450 px.** El usuario trabaja en una pantalla
  ancha y hoy sobran márgenes vacíos a ambos lados mientras el vídeo va
  pequeño.
- **Papelera y "Vaciar biblioteca" salen del sitio privilegiado** que ocupan hoy
  (dos botones permanentes sobre la lista). Son operaciones raras y una de ellas
  es masiva.
- **El selector de pista de audio solo aparece cuando importa**, es decir
  cuando la fuente elegida es ASR o cuando se quiere escuchar el vídeo con otra
  pista. Hoy está siempre visible bajo el reproductor.
- **La exportación acepta el idioma destino elegido.** Hoy
  `LocalExportRequest.language` es `Literal["es", "original"]`
  (`backend/app/main.py:683`). Pasa a ser "original" o "traducción", y el nombre
  del archivo generado usa el código del idioma destino del proyecto.

- **Borrar o insertar segmentos deshabilita "Revertir última mejora".** Hoy
  `undo_improvement` (`backend/app/main.py:533-543`) devuelve 409 si falta
  cualquier id de la instantánea, mientras que `can_undo_improvement`
  (`main.py:67`) sigue devolviendo `true`. Sin tocar nada, borrar una sola línea
  dejaría para siempre un botón visible que falla en cada pulsación. El criterio
  es: una vez que el conjunto de segmentos cambia respecto a la instantánea, la
  reversión deja de ofrecerse, no falla.
- **Detener no es instantáneo, y se dice.** El endpoint marca la intención; es
  el worker quien cambia el estado a "detenido" al terminar el lote en curso.
  Mientras tanto la interfaz muestra "deteniendo…". El motivo no es comodidad:
  el worker de traducción escribe `translated` sin comprobar nada
  (`backend/app/worker.py:106-109`, a diferencia del de mejora en `150-158`), así
  que devolver la edición al usuario antes de que termine el lote en vuelo
  permitiría que ese lote pisara lo que acaba de escribir. La espera máxima es un
  lote de seis.
- **Un segmento insertado vacío cuenta como pendiente en la interfaz pero el
  worker lo salta.** La traducción valida que ninguna línea devuelta venga
  vacía, así que enviar un original vacío haría fallar el lote entero.

## Decisiones cerradas en la revisión

Las tres preguntas que levantó la revisión del documento están resueltas por
Federico. Se registran aquí porque corrigen o concretan lo anterior.

### Borrar un segmento: deshacer solo en el navegador · aplazado

Deshacer un borrado **puede residir únicamente en memoria del navegador**. No
hace falta registro recuperable en disco ni interfaz de restauración. Basta el
endpoint `DELETE`, la confirmación al borrar y el deshacer de sesión que ya
existe. Esto abarata la fase 3 considerablemente.

### Cambiar el idioma destino: se guarda lo hecho y se retraduce

Cuando una traducción termina **se guarda en un archivo**, y si quedó
incompleta se guarda igualmente con extensión `.part`. Por tanto cambiar el
idioma destino no destruye nada: lo traducido hasta ese momento ya está en
disco como archivo de subtítulo, y el proyecto vuelve a traducir desde cero al
idioma nuevo.

Esto resuelve el conflicto con el anti-objetivo de no perder trabajo sin
inventar instantáneas ni archivos laterales por segmento: **la traducción
múltiple se materializa como un archivo por idioma junto al vídeo**, mientras
el editor trabaja siempre con uno solo a la vez. La columna `translated` sigue
siendo única y se vacía al cambiar de idioma.

Queda al constructor dónde se escribe exactamente el archivo y cómo se nombra,
siguiendo el patrón de **Guardar junto al vídeo** que ya existe y añadiendo el
código del idioma. Lo que no es opcional: el guardado ocurre **antes** de
vaciar la columna, y si falla, el cambio de idioma no se realiza.

### Insertar: el segmento nuevo rellena el hueco · aplazado

No hay duración por defecto. El segmento insertado toma:

- **mark-in**: inmediatamente posterior al mark-out del segmento anterior.
- **mark-out**: inmediatamente anterior al mark-in del segmento siguiente.

"Inmediatamente" es la unidad mínima representable, que en esta herramienta es
el milisegundo: los tiempos se muestran y editan con tres decimales. Es decir,
`nuevo.start = anterior.end + 1 ms` y `nuevo.end = siguiente.start - 1 ms`.

De ahí sale la regla de rechazo sin necesidad de un número aparte: si el hueco
disponible no da para que `start` quede antes que `end`, no se inserta y se
avisa. Nunca se desplaza ni se acorta un segmento vecino.

Casos de borde que resuelvo yo, por coherencia con la regla:

- **Insertar antes del primero**: el borde anterior es el segundo cero del
  vídeo, y la regla se aplica igual.
- **Insertar después del último**: no hay siguiente que limite y el backend no
  conoce la duración del vídeo, porque `Project` no la guarda. El segmento nuevo
  arranca un milisegundo después del último y dura dos segundos, recortados a la
  duración del vídeo cuando el reproductor la conoce y puede comunicarla. Los
  tiempos quedan editables de inmediato, que es lo que el usuario va a hacer de
  todos modos en ese caso.

## Fases

Orden sugerido. Cada fase deja la herramienta en un estado usable.

1. **Estructura y biblioteca.** Cabecera, insignia, títulos, pie, ancho máximo,
   biblioteca plegable, acciones del proyecto en el proyecto, papelera y vaciar
   fuera del sitio privilegiado. Solo frontend. Es la fase que más alivio da por
   lo que cuesta.
2. **Vista única y elección de fuente.** Quitar la puerta ver/editar y el
   endpoint `edit-mode` con ella, agrupar las fuentes, esconder las pistas de
   imagen, mover el selector de audio. Frontend más limpieza de backend.
3. ~~**Insertar y borrar segmentos.**~~ **Aplazada a una versión mayor.** El
   número se conserva para que las referencias de los planes ya escritos sigan
   apuntando a lo mismo. Cuando llegue: endpoints nuevos, renumeración de
   `position`, regla de relleno de hueco con rechazo por solape, encaje con
   deshacer/rehacer (de sesión, sin registro en disco) y con la comprobación
   `expected` de conflicto entre pestañas. La reversión de mejora deja de
   ofrecerse en cuanto el conjunto de segmentos cambia.
4. **Idioma destino.** Planificada: tareas 11 a 15 de
   `docs/superpowers/plans/2026-11-05-ux-shell-unified-view.md`.
   Parametrizar el prompt del gateway, guardar el idioma en
   `source.json`, selector en la interfaz, exportación y nombres de archivo.
   Guardado del idioma saliente a archivo (con `.part` si quedó incompleto)
   antes de vaciar la columna al cambiar de idioma.
5. **Cambios en vivo y detener.** Planificada: tareas 16 a 20 del mismo plan.
   Refresco incremental de las filas mientras
   corre el proceso, bandera de detención comprobada entre lotes, estado
   "detenido" distinto de "fallido", y retomar.

Las fases 4 y 5 son independientes entre sí y dependen las dos de la 2. Ninguna
necesita la 3, así que aplazarla no bloquea nada. Lo único que la 3 se lleva
consigo es la retirada del botón "Revertir última mejora" cuando cambia el
conjunto de segmentos: sin inserción ni borrado ese conjunto no cambia, y el
botón sigue siendo correcto tal como está hoy.

## Qué queda al constructor

- La disposición concreta: si el vídeo va encima de la lista o al lado, cómo se
  pliega la biblioteca, qué controles son permanentes y cuáles aparecen al pasar
  por encima o al enfocar una fila.
- La forma de la agrupación de fuentes: lista con encabezados, pestañas, o algo
  distinto del desplegable nativo.
- Cómo se marcan visualmente las filas que acaban de cambiar durante un proceso.
  **Resuelto en el plan** (tarea 19): clase `cue-fresh` con animación corta,
  aplicada en el marcado a las filas cuyo campo relevante cambió respecto al
  render anterior, con alternativa sin movimiento.
- El mecanismo concreto de la bandera de detención (Redis, archivo en
  `data/<UUID>/`, columna). Solo se pide que el worker la compruebe entre lotes
  y que respete la restricción 1. **Resuelto en el plan** (tarea 17): un archivo
  `data/<UUID>/stop`, comprobado antes de cada lote y borrado en los cuatro
  caminos de encolado.
- La lista de idiomas destino ofrecidos. **Resuelta en el plan** (Parte 2): siete
  códigos —`es`, `en`, `pt-BR`, `fr`, `it`, `de`, `ca`— validados por separado en
  el backend y en el gateway, porque el código acaba dentro de un nombre de
  archivo en el disco del usuario. Los proyectos antiguos de copia se quedan en
  `es`, con el selector deshabilitado, porque no pueden guardar la traducción
  saliente junto al vídeo y ese guardado es obligatorio antes de vaciar la
  columna.
- Todo lo tipográfico y cromático, dentro del tema oscuro existente.

## Qué no se puede romper

El conjunto de pruebas existente (`tests/`) cubre el gateway, la API nativa, los
archivos locales y el frontend. Debe seguir pasando, adaptado donde el rediseño
cambie deliberadamente el comportamiento. En particular hay que conservar:

- La edición bloqueada durante el procesamiento (restricción 3).
- La detección de conflicto entre pestañas por `expected` (restricción 11 y
  `main.py:660`).
- La reversión de mejora con su negativa a sobrescribir ediciones posteriores,
  ahora además retirada de la interfaz cuando el conjunto de segmentos ha
  cambiado.
- El carácter recuperable de la papelera y del vaciado de biblioteca.
- Que el vídeo original nunca se copia ni se envía a ningún sitio.
