# Rediseño UX · Fases 1, 2, 4 y 5 — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Devolver la pantalla al vídeo y a los subtítulos, y fundir las vistas "ver" y "editar" en una sola vista siempre editable con una elección de fuente agrupada.

**Architecture:** Todo el trabajo vive en el frontend salvo la retirada del endpoint `edit-mode`. `frontend/app.js` (771 líneas) se adelgaza extrayendo dos responsabilidades que este plan reescribe enteras: la lista de biblioteca a `frontend/library.js` y el paso de elección de fuente a `frontend/sources.js`. Los tres son scripts clásicos que comparten el ámbito léxico global, igual que ya hace `editor-state.js`. **`library.js` y `sources.js` se cargan después de `app.js`**, porque las declaraciones `let` de `app.js` están en zona muerta temporal hasta que ese script termina; ningún script nuevo puede tocar `$`, `esc` ni una variable de `app.js` en su nivel superior, solo dentro de funciones. Las pruebas de frontend pasan de recortar `app.js` por nombres de función a cargar todos los scripts sobre un DOM real de linkedom.

**Tech Stack:** HTML/CSS/JS sin framework, servido por Nginx. Pruebas con `node --test` y `linkedom` 0.18.12 (ya es devDependency). Backend FastAPI con pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-ux-redesign-design.md`

**Mockups:** `docs/mockups/2026-11-05-ux-redesign.html`. Ábrelo en un navegador antes de empezar. Son cuatro pantallas estáticas —vista única con biblioteca abierta, biblioteca plegada, elección de fuente y ventana estrecha— construidas con la paleta y los componentes que ya existen. **Donde el plan y el mockup discrepen, manda el plan**; el mockup resuelve lo que el plan deja en prosa: densidad, orden de los mandos, rótulos y proporciones.

**Partes:** la **Parte 1** (tareas 1 a 10) cubre las fases 1 y 2 del diseño: el armazón, la biblioteca plegable, la vista única y la elección de fuente. La **Parte 2** (tareas 11 a 20) cubre las fases 4 y 5: el idioma destino, y los cambios en vivo con detención. Entre las dos hay una parada obligatoria. La fase 3 está aplazada a una versión mayor y no se construye.

**Quién implementa:** Codex, que no puede preguntar nada a quien escribió esto. Cada decisión que haga falta está en el plan, en el diseño o en el mockup. Si tu entorno no tiene las skills de superpowers citadas arriba, ejecuta las tareas en orden, respetando el ciclo de cada una: prueba que falla, mínimo código, prueba que pasa, commit.

## Global Constraints

- Toda la copia de interfaz va en español. El tema oscuro existente no cambia de paleta.
- No se añaden dependencias. `linkedom` ya está instalada.
- No se añaden columnas a tablas existentes: `backend/app/core.py:17` solo llama a `create_all`, que no migra. Restricción 1 del diseño.
- `frontend/app.js` debe terminar exactamente con `refresh();` seguido de `setInterval(refresh, 4000);`, porque `setup()` en `tests/frontend.test.cjs` los elimina por expresión regular. Si cambian, se actualiza la expresión en la misma tarea.
- **Las variables `let` del nivel superior de un script no son propiedades del objeto global.** En las pruebas no se pueden fijar con `c.projects = …`; hay que escribirlas con `evaluate(c, "projects=[…]")`. Las declaraciones de función sí son propiedades, así que `c.api = …` y `c.resetWorkspace = …` funcionan.
- Nginx sirve una copia de los archivos: nada se ve en http://localhost:3000 hasta ejecutar `docker compose up -d --build`.
- El vídeo original nunca se copia ni se envía a ningún sitio.
- Línea base verde que hay que mantener: `npm test` → 28 pass, 0 fail. `.venv/bin/python -m pytest -q` → 60 passed.
- Rama de trabajo: `feature/mvp-setup`. Un commit por tarea.

## Review Focus

Cinco modos de fallo que el diseño implica y que ninguna tarea probaría por sí sola. Cada línea tiene su prueba asignada a la tarea que posee el código.

1. **Un id que desaparece de `index.html` rompe la aplicación entera y en silencio.** `app.js` termina con `$("open-local").onclick = …`, `$("show-trash")`, `$("clear-library")`, `$("restore-library")`. Si el rediseño del armazón renombra o elimina uno, `.onclick` sobre `null` lanza, `refresh()` nunca llega a ejecutarse y la aplicación se queda en "Cargando…" para siempre. El arnés actual no puede detectarlo porque `getElementById` devuelve `{}` para cualquier id. → Tarea 1.
2. **Quitar un proyecto desde la lista borra el espacio de trabajo de otro.** `removeProject` (`app.js:692`) llama siempre a `resetWorkspace()`. Con el botón en cada fila, quitar el proyecto B mientras editas el A tira el A. → Tarea 3.
3. **`renderList` reconstruye la lista con `innerHTML` cada 4 segundos.** Cualquier menú desplegable dentro de una fila se cerraría solo cada 4 segundos, y el estado de plegado de la biblioteca se perdería si viviera dentro de ese DOM. → Tarea 3.
4. **Un proyecto en la papelera dejaría de mostrar sus segmentos.** Hoy un proyecto `ready` en papelera enseña la tabla en solo lectura. La vista única no puede hacerlo caer en el aviso de "mientras se procesa". → Tarea 6.
5. **Un vídeo cuyas únicas pistas son de imagen diría que no hay ninguna.** Al ocultar las no soportadas, la comprobación `options.length` afirmaría "No se encontraron archivos de subtítulos ni pistas incrustadas", que es falso, y es exactamente el anti-objetivo de esconder estado. → Tarea 8.

---

### Task 1: Arnés de pruebas sobre DOM real

El arnés actual tiene dos límites que impiden escribir pruebas de marcado: `setup()` devuelve `{}` para cualquier id y anula `renderList`/`renderWorkspace`, y las tres pruebas que sí usan linkedom recortan `app.js` entre `"function renderWorkspace()"` y `"async function retryProject("`, lo que se rompe en cuanto se mueve una función.

**Files:**
- Modify: `tests/frontend.test.cjs:1-40` (añadir `domSetup`) y las tres pruebas que recortan por índice (líneas 86, 118, 160)

**Interfaces:**
- Produces: `domSetup()` → contexto VM con `document` de linkedom construido desde `frontend/index.html`, con **todos** los `<script src>` de `index.html` ejecutados en el orden en que aparecen, y con los renderizadores reales intactos. Las tareas 2 a 9 escriben sus pruebas sobre él.

- [ ] **Step 1: Escribir la prueba que falla**

```js
test("every element app.js binds at load exists in index.html", () => {
  const c = domSetup();
  for (const id of ["open-local", "show-trash", "clear-library", "restore-library", "projects", "workspace"])
    assert.ok(c.document.getElementById(id), `falta #${id}`);
});
```

- [ ] **Step 2: Ejecutar y ver que falla**

Run: `npm test 2>&1 | grep -A3 "exists in index.html"`
Expected: FAIL con `domSetup is not defined`.

- [ ] **Step 3: Implementar `domSetup()` en `tests/frontend.test.cjs`**

Misma forma que `setup()`, con tres diferencias: `document` es `parseHTML(fs.readFileSync("frontend/index.html","utf8")).document` desde el principio; no se ejecuta la línea `renderList=()=>{};renderWorkspace=()=>{};`; y en vez de cargar dos archivos fijos, **descubre los scripts del propio `index.html`** (`document.querySelectorAll("script[src]")`, mapeando `/x.js` → `frontend/x.js`) y los ejecuta en ese orden, aplicando a cada uno el mismo reemplazo de `refresh(); setInterval(…)`. Así las tareas 3 y 8 no tienen que tocar el arnés al añadir archivos. Como los enlaces del final de `app.js` se ejecutan de verdad, un id ausente lanza al cargar, que es justo lo que esta tarea quiere detectar.

- [ ] **Step 4: Migrar las tres pruebas que recortan `app.js`**

Las de las líneas 86, 118 y 160 pasan a usar `domSetup()` y pierden el `source.slice(...)`. Conservan sus aserciones tal cual; la de `option[value="pgs"]` se reescribe más tarde, en la tarea 8.

- [ ] **Step 5: Ejecutar la suite completa**

Run: `npm test`
Expected: 29 pass, 0 fail.

- [ ] **Step 6: Commit**

```bash
git add tests/frontend.test.cjs
git commit -m "test: load the real DOM and every script in frontend tests"
```

---

### Task 2: Armazón — cabecera, anchura y cromo fuera

Hoy, antes del primer segmento, la pantalla gasta: una franja de cabecera con la marca y la insignia, un `<h1>Proyectos</h1>`, un párrafo descriptivo, el encabezado "Biblioteca" y un pie con los nombres de los modelos. Y `main` está limitado a 1450 px, lo que deja márgenes vacíos en pantalla ancha mientras el vídeo va pequeño.

**Files:**
- Modify: `frontend/index.html` (bloque `<style>` y todo el `<body>`)
- Test: `tests/frontend.test.cjs`

**Interfaces:**
- Produces: el armazón conserva los ids `open-local`, `show-trash`, `clear-library`, `restore-library`, `projects`, `workspace`. Añade `library-toggle` (consumido por la tarea 3).
- Produces: **`#project-header` sale de `#workspace` y pasa a ser un hueco estático dentro de la banda superior.** Hoy `renderWorkspace` lo crea dentro de `workspace.innerHTML` (`app.js:162`); a partir de ahora lo encuentra ya en el DOM y sólo le escribe dentro. Es lo que permite que la aplicación tenga **una sola** banda de cromo en vez de dos.

- [ ] **Step 1: Escribir las pruebas que fallan**

```js
test("the shell keeps only video and subtitles as permanent chrome", () => {
  const c = domSetup();
  const html = c.document.documentElement.innerHTML;
  assert.equal(c.document.querySelector("h1"), null);
  assert.ok(!html.includes("Qwen3-ASR · MLX · Ollama"));
  assert.ok(!html.includes("sin copiarlos ni enviarlos a Internet"));
  assert.ok(c.document.querySelector(".badge"), "la insignia local se conserva");
  assert.ok(c.document.getElementById("library-toggle"));
});
test("the layout is not capped at a fixed width", () => {
  const css = fs.readFileSync("frontend/index.html", "utf8");
  assert.ok(!/max-width:\s*1450px/.test(css));
});
test("the project header shares the one chrome band", () => {
  const c = domSetup();
  const header = c.document.getElementById("project-header");
  assert.ok(header, "existe en index.html, no lo crea renderWorkspace");
  assert.ok(c.document.querySelector(".topbar #project-header"));
  assert.equal(c.document.getElementById("workspace").querySelector("#project-header"), null);
});
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `npm test 2>&1 | grep -E "permanent chrome|fixed width|one chrome band"`
Expected: FAIL las tres.

- [ ] **Step 3: Reescribir el armazón en `frontend/index.html`**

Pantalla 1 del mockup. **Una sola banda de 40 px, la única de la aplicación**, que contiene de izquierda a derecha: el botón `library-toggle`, la marca reducida a su glifo, el hueco `#project-header` —nombre del proyecto, estado y, pegado a la derecha, el grupo de exportación—, la insignia `.badge` reducida a un punto y "Local" en 11 px, y el botón `open-local`. Con el espacio de trabajo vacío, `#project-header` no pinta nada y la banda queda con marca, insignia y abrir.

Desaparecen el `<h1>`, el párrafo, el encabezado "Biblioteca", el pie, y la banda aparte de cabecera de proyecto. `main` pierde el `max-width` y queda a `padding: 0`.

`show-trash`, `clear-library` y `restore-library` siguen existiendo estáticamente —la tarea 1 lo exige— pero bajan a una fila `.library-footer` al pie del `<aside>`, en `font-size: 11px`, fuera del sitio privilegiado que ocupan hoy sobre la lista. La paleta no cambia.

- [ ] **Step 4: Ejecutar las pruebas**

Run: `npm test`
Expected: 32 pass, 0 fail.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html tests/frontend.test.cjs
git commit -m "feat: strip permanent chrome from the shell"
```

---

### Task 3: Biblioteca plegable con acciones en cada proyecto

**Files:**
- Create: `frontend/library.js`
- Modify: `frontend/app.js` (borrar `renderList` de 83-99 y `toggleTrash`, `clearLibrary`, `restoreLibrary` de 698-736, y sus tres enlaces del final), `frontend/index.html` (añadir `<script src="/library.js" defer>` **después** de `app.js`), `frontend/app.js:678-697` (`removeProject`)
- Test: `tests/frontend.test.cjs`

**Interfaces:**
- Consumes: `api`, `refresh`, `select`, `selected`, `projects`, `viewingTrash`, `stateName`, `esc`, `resetWorkspace`, `settleEdits` de `app.js`, todo ello desde dentro de funciones, nunca en el nivel superior del script.
- Produces: `renderList()`, `toggleTrash()`, `clearLibrary()`, `restoreLibrary()`, `toggleLibrary()`, y `libraryCollapsed` (estado de módulo, fuera del DOM de la lista).

- [ ] **Step 1: Escribir las pruebas que fallan**

```js
test("each project carries its own remove control", () => {
  const c = domSetup();
  evaluate(c, "projects=[{id:'a',name:'a.mkv',state:'ready',progress:100}];renderList()");
  assert.ok(c.document.querySelector('.project[data-id="a"] [data-action="remove"]'));
});
test("an active project offers no remove control", () => {
  const c = domSetup();
  evaluate(c, "projects=[{id:'a',name:'a.mkv',state:'translating',progress:20}];renderList()");
  assert.equal(c.document.querySelector('.project[data-id="a"] [data-action="remove"]'), null);
});
test("removing a project other than the open one keeps the workspace", async () => {
  const c = domSetup();
  let reset = false;
  c.resetWorkspace = async () => { reset = true; return true; };
  c.api = async () => ({ ok: true });
  evaluate(c, "selected='a'");
  await evaluate(c, "removeProject('b')");
  assert.equal(reset, false);
});
test("collapsing the library survives a list re-render", () => {
  const c = domSetup();
  evaluate(c, "projects=[{id:'a',name:'a.mkv',state:'ready',progress:100}];renderList()");
  assert.ok(c.document.body.classList.contains("library-collapsed"), "arranca cerrada");
  evaluate(c, "toggleLibrary();renderList()");
  assert.equal(c.document.body.classList.contains("library-collapsed"), false);
});
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `npm test 2>&1 | grep -E "remove control|keeps the workspace|survives a list"`
Expected: FAIL las cuatro.

- [ ] **Step 3: Crear `frontend/library.js`**

Pantallas 1 y 2 del mockup. `renderList()` emite por proyecto un `<div class="project" data-id>` —contenedor, no `<button>`, porque un botón dentro de otro es marcado inválido y su clic burbujearía a `select()`— con un `<button class="project-open">` para el nombre y el estado, y un `<button data-action="remove">` sólo cuando `p.state` no está en los estados activos, porque `DELETE /api/projects/{pid}` devuelve 409 para esos (`backend/app/main.py:126`). En papelera ese botón dice "Restaurar".

`toggleLibrary()` invierte `libraryCollapsed`, variable del módulo, y refleja el estado en `document.body.classList`, nunca dentro del DOM que `renderList` reconstruye cada 4 segundos. Nada de menús desplegables dentro de las filas, por el mismo motivo.

**La biblioteca arranca cerrada y se superpone al abrirse**, en `position: absolute` sobre la columna de trabajo, no empujándola: abrirla para cambiar de proyecto no debe reflotar la rejilla ni encoger el vídeo. Pantallas 1 y 2 del mockup.

`clearLibrary`, `restoreLibrary` y `toggleTrash` se mueven aquí sin cambio de comportamiento, y sus enlaces pasan a hacerse dentro de una función `bindLibrary()` que `library.js` llama al final, ya con `app.js` evaluado.

- [ ] **Step 4: Cambiar `removeProject` en `app.js`**

Que llame a `resetWorkspace()` solamente cuando `pid === selected`.

- [ ] **Step 5: Ejecutar las pruebas**

Run: `npm test`
Expected: 36 pass, 0 fail.

- [ ] **Step 6: Commit**

```bash
git add frontend/library.js frontend/app.js frontend/index.html tests/frontend.test.cjs
git commit -m "feat: collapsible library with per-project actions"
```

---

### Task 4: El vídeo y la tabla ocupan la pantalla

Ésta es la tarea que cumple el objetivo 1 del diseño. Hoy el vídeo está tapado a `max-height: 410px` con `aspect-ratio: 16/7`, la tabla vive en un `max-height: 64vh` debajo, y entre ambos hay tres filas de texto: el encabezado del proyecto con su botón "Quitar de biblioteca" en la esquina opuesta a la lista, la línea "N segmentos · Archivo original, sin copia" y el `.tiny` de "Guardado automático al salir de cada campo".

**Files:**
- Modify: `frontend/index.html` (reglas `.player`, `.editor`, `.layout`, `.work`, `.controls`), `frontend/app.js:160-175` (armazón y `project-header`), `frontend/app.js:202-203` (`project-content`), `frontend/app.js:213-214` (borrar el enlace de `project-remove`)
- Test: `tests/frontend.test.cjs`

**Interfaces:**
- Produces: el armazón del espacio de trabajo, construido una sola vez por proyecto —esa condición la impone la prueba que exige que el nodo `<video>` no se reemplace entre renders—, con esta estructura:
  - `.workspace-split`, la rejilla.
  - `#video-frame`, celda izquierda, `position: relative` y `aspect-ratio: 16/9`, conteniendo **sólo** `<video id="video">` y `#video-subtitles`. Es el ancestro posicionado del overlay, así que nada más puede entrar.
  - `#workspace-controls`, celda izquierda, bajo el marco: barra del reproductor, pista de audio, deshacer/rehacer, mejorar, traducir, estado de guardado y la línea de "N segmentos".
  - `#project-content`, celda derecha: nada más que la lista.
- Produces: `editorMarkup` se parte en `editorToolbar(cues, project, readOnly)`, que se pinta en `#workspace-controls`, y `editorTable(cues, project, readOnly)`, que se pinta en `#project-content`. `loadSubtitlePreview` pasa a usar sólo `editorTable`.
- Produces: `project-remove` desaparece del espacio de trabajo; su única casa es la fila de la lista, de la tarea 3. El encabezado del proyecto ya no vive aquí: la tarea 2 lo subió a la banda.

- [ ] **Step 1: Escribir las pruebas que fallan**

```js
test("the workspace header no longer carries the remove button", () => {
  const c = domSetup();
  evaluate(c, "detail={project:{id:'a',name:'a.mkv',state:'ready',progress:100,source_kind:'reference'},cues:[{id:'1',start:1,end:2,original:'hi',translated:''}]};renderWorkspace();");
  assert.equal(c.document.getElementById("project-remove"), null);
  assert.ok(c.document.querySelector(".workspace-split"));
});
test("neither the player nor the editor is capped at a fixed height", () => {
  const css = fs.readFileSync("frontend/index.html", "utf8");
  assert.ok(!/max-height:\s*410px/.test(css));
  assert.ok(!/max-height:\s*64vh/.test(css));
});
test("the right cell holds the list and nothing else", () => {
  const c = domSetup();
  evaluate(c, "detail={project:{id:'a',name:'a.mkv',state:'ready',progress:100,source_kind:'reference'},cues:[{id:'1',start:1,end:2,original:'hi',translated:''}]};renderWorkspace();");
  const right = c.document.getElementById("project-content");
  assert.ok(right.querySelector("#editor"), "la lista va a la derecha");
  assert.equal(right.querySelector("#save-status"), null);
  assert.equal(right.querySelector("#undo-edit"), null);
  assert.ok(c.document.getElementById("workspace-controls").querySelector("#undo-edit"));
});
test("nothing but the video shares the overlay's positioned ancestor", () => {
  const t = JSON.stringify([{ index: 1, label: "Pista 1 · und · aac" }]);
  const c = domSetup();
  evaluate(c, `detail={project:{id:'a',name:'a.mkv',state:'ready',progress:100,source_kind:'reference',audio_tracks:${t}},cues:[{id:'1',start:1,end:2,original:'hi',translated:''}]};renderWorkspace();`);
  const frame = c.document.getElementById("video-frame");
  assert.ok(frame.querySelector("#video-subtitles"));
  assert.equal(frame.querySelector("#audio-controls"), null);
});
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `npm test 2>&1 | grep -E "remove button|fixed height|right cell|positioned ancestor"`
Expected: FAIL las cuatro.

- [ ] **Step 3: Reescribir la disposición**

Pantallas 1 y 4 del mockup. `.workspace-split` es una rejilla de dos columnas a partir de 1280 px, 46 % y 54 %: a la izquierda el visor y **todos** los mandos, a la derecha nada más que la lista, ambas a la altura de la ventana menos la barra. Por debajo de 1280 px, una sola columna con el vídeo arriba.

El marco del vídeo pierde el `max-height: 410px` y pasa a `aspect-ratio: 16/9` a lo ancho de su columna, centrado vertical­mente en un contenedor flexible. **No puede limitarse a llenar la celda**: el overlay de subtítulos se posiciona contra el marco, así que si el marco fuera más alto que la imagen el texto caería sobre la banda negra. En la columna única el vídeo se dimensiona por altura y se centra, con barras a los lados. `object-fit: contain` se queda.

`.editor` pierde el `max-height: 64vh` y pasa a `min-height: 0; overflow: auto` dentro de la celda de la rejilla, que es lo que hace que desplace sin empujar al vídeo fuera.

El reparto izquierda/derecha es el motivo de partir `editorMarkup`: hoy devuelve barra y tabla en una sola cadena que cae entera en `#project-content`. Hay que separarlas para que la barra viva con el vídeo.

`.workspace-split` ocupa todo lo que hay bajo la banda: no queda ninguna fila de cabecera entre medias. Se borra `project-remove` del marcado y su enlace. La línea de "N segmentos" y el `.tiny` de guardado automático se funden en `#workspace-controls`, junto a `save-status`.

- [ ] **Step 4: Ejecutar las pruebas**

Run: `npm test`
Expected: 40 pass, 0 fail.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/app.js tests/frontend.test.cjs
git commit -m "feat: give the screen to the video and the subtitle table"
```

---

### Task 5: Punto de control visual con Federico

Fin de la fase 1. Hasta aquí Federico ha visto el mockup, no la aplicación; este paso compara una contra el otro antes de seguir.

- [ ] **Step 1: Reconstruir**

Run: `docker compose up -d --build`
Expected: los contenedores levantan sin error.

- [ ] **Step 2: Capturar**

Abrir http://localhost:3000 a 1570 px y a 1024 px de ancho, con un proyecto "Listo" abierto, y tomar una captura de cada uno. Compararlas con las pantallas 1 y 4 del mockup. No pulsar nada que escriba en los datos de Federico: ni "Abrir archivo local", ni "Mejorar transcripción", ni "Quitar", ni "Vaciar", ni escribir en campos de segmento.

- [ ] **Step 3: Parar**

Detente aquí. Deja las dos capturas donde Federico pueda verlas y **termina la ejecución**. La tarea 6 empieza en otra ejecución, cuando él apruebe. No sigas por tu cuenta aunque todo parezca correcto: la disposición izquierda/derecha es una decisión de diseño que él todavía no ha visto construida.

---

### Task 6: Vista única en el frontend

`renderWorkspace` calcula hoy `viewMode` y `ready` a partir de `p.action` (`app.js:155-157`) y, en modo vista, dibuja la tabla con `readonly` más dos botones, "Editar o mejorar" y "Traducir pendientes".

**Files:**
- Modify: `frontend/app.js:149-300` (`renderWorkspace`), `frontend/app.js:636-649` (borrar `editViewedProject`), `frontend/app.js:243`
- Test: `tests/frontend.test.cjs` (reescribir la prueba de la línea 469, que hoy exige `edit-view` y `translate-view`)

**Interfaces:**
- Produces: `workspaceMode(project, cues, viewingTrash)` → `"editable" | "locked" | "draft" | "waiting"`. Función pura que sustituye a los tres booleanos. `"locked"` es la tabla de solo lectura, y es el único caso que conserva `readonly`. También `defaultExportLanguage(cues)` → `"es" | "original"`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```js
test("a legacy view project opens editable", () => {
  const c = domSetup();
  assert.equal(evaluate(c, `workspaceMode({state:'ready',action:'view'},[{id:'1'}],false)`), "editable");
});
test("a project being translated stays locked", () => {
  const c = domSetup();
  assert.equal(evaluate(c, `workspaceMode({state:'translating',action:'edit'},[{id:'1'}],false)`), "locked");
});
test("a ready project in the trash still shows its cues", () => {
  const c = domSetup();
  assert.equal(evaluate(c, `workspaceMode({state:'ready',action:'edit'},[{id:'1'}],true)`), "locked");
});
test("the editable view offers no mode switch and saves", () => {
  const c = domSetup();
  evaluate(c, "detail={project:{id:'a',name:'a.mkv',state:'ready',action:'view',progress:100,source_kind:'reference'},cues:[{id:'1',start:1,end:2,original:'hi',translated:''}]};renderWorkspace();");
  assert.equal(c.document.getElementById("edit-view"), null);
  assert.equal(c.document.querySelector(".cue textarea[readonly]"), null);
  assert.ok(c.document.getElementById("save-status"), "el guardado automático sigue activo");
});
test("export language follows the data, not the stored action", () => {
  const c = domSetup();
  assert.equal(evaluate(c, `defaultExportLanguage([{translated:''}])`), "original");
  assert.equal(evaluate(c, `defaultExportLanguage([{translated:'hola'}])`), "es");
});
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `npm test 2>&1 | grep -E "legacy view|stays locked|in the trash|no mode switch|follows the data"`
Expected: FAIL las cinco.

- [ ] **Step 3: Implementar `workspaceMode` y `defaultExportLanguage` en `frontend/app.js`**

`workspaceMode` deja de leer `p.action` por completo. En orden: `"draft"` si el estado es `draft`; `"locked"` si hay segmentos y estamos en papelera —hoy un proyecto `ready` en papelera muestra su tabla en solo lectura y debe seguir haciéndolo—; `"editable"` si el estado es `ready` o `failed` y hay segmentos; `"locked"` si hay segmentos; `"waiting"` en el resto.

`defaultExportLanguage` reemplaza la línea 243, que hoy decide con `p.action`, un dato que deja de significar nada.

Con eso fuera, en `renderWorkspace` desaparece la rama `viewMode` entera y con ella `edit-view` y `translate-view`, y se borra `editViewedProject`. `editorMarkup` conserva su parámetro `readOnly`: lo siguen usando el modo `"locked"` y la vista previa de pista de `loadSubtitlePreview`.

- [ ] **Step 4: Reescribir la prueba existente de la línea 469**

Hoy afirma que un proyecto con `action:'view'` muestra `edit-view` y `translate-view`. Pasa a afirmar lo contrario: que la tabla sale editable y que "Traducir pendientes" sigue disponible desde la barra del editor.

- [ ] **Step 5: Ejecutar las pruebas**

Run: `npm test`
Expected: 45 pass, 0 fail.

- [ ] **Step 6: Commit**

```bash
git add frontend/app.js tests/frontend.test.cjs
git commit -m "feat: single always-editable subtitle view"
```

---

### Task 7: Retirar el endpoint `edit-mode`

**Files:**
- Modify: `backend/app/main.py:432-448` (borrar `edit_mode`), `backend/app/main.py:270-273` (`StartRequest`)
- Test: `tests/test_native_api.py:210-237`

**Interfaces:**
- Consumes: después de la tarea 6 nada del frontend llama a `/edit-mode`.
- Produces: `StartRequest.action` pasa de `Literal["translate", "edit", "view"]` a `Literal["translate", "edit"]`. **El valor por defecto sigue siendo `"translate"`**: el frontend siempre envía `action`, así que cambiarlo no aporta nada y sí voltearía en silencio cualquier prueba de backend que lo omita.

El worker (`backend/app/worker.py:76`) comprueba `reference(pid).get("action") in ("edit", "view")`. Esa comprobación **se queda como está**: los `source.json` ya escritos en el disco de Federico contienen `"view"` y deben seguir funcionando. Lo que se retira es la posibilidad de escribir `"view"` de nuevo.

- [ ] **Step 1: Reescribir las pruebas afectadas**

`test_transcribe_to_view_then_enter_edit_mode` (línea 210) pasa a `test_transcribe_lands_editable_without_edit_mode`: arranca con `action="edit"`, comprueba que el proyecto queda en `ready` y que `POST /api/projects/{pid}/edit-mode` devuelve 404. Añadir `test_start_rejects_view_action`: `action="view"` devuelve 422. `test_asr_edit_mode_does_not_call_translation` (`tests/test_worker.py:116`) se conserva tal cual, porque sigue siendo cierta con `"edit"`.

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `.venv/bin/python -m pytest tests/test_native_api.py -q`
Expected: FAIL, `edit-mode` sigue devolviendo 200.

- [ ] **Step 3: Borrar el endpoint y estrechar el literal**

- [ ] **Step 4: Ejecutar las dos suites**

Run: `.venv/bin/python -m pytest -q && npm test`
Expected: 61 passed y 45 pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py tests/test_native_api.py
git commit -m "refactor: drop the view/edit gate from the API"
```

---

### Task 8: Elección de fuente agrupada

Hoy es un `<select>` nativo plano que en un caso real traía trece entradas mezclando pistas incrustadas, archivos hermanos y la carpeta `Subs`, más las no soportadas en gris con "requiere OCR/conversión", más un segundo `<select>` de Acción, más el botón, todo ello por debajo de una vista previa que puede tener 1314 filas.

**Files:**
- Create: `frontend/sources.js`
- Modify: `frontend/app.js:579-635` (borrar `sourceChoices`, `updateDraftAction`, y el `action` variable de `startProject`), `frontend/index.html` (añadir `<script src="/sources.js" defer>` **después** de `app.js`)
- Test: `tests/frontend.test.cjs` (reescribir tres aserciones existentes: la de `option[value="pgs"]` en la línea 152, la de `subtitle-action` en 379-380, y la de `action: "view"` en el cuerpo enviado, línea 464)

**Interfaces:**
- Consumes: `api`, `esc`, `loadSubtitlePreview`, `editorMarkup`, `busy`, `selected`.
- Produces: `groupSources(options)` → `{ groups: [{ title, items }], hidden: number }`. Tres grupos en este orden, omitiendo los vacíos: `"Pistas del vídeo"` (`kind === "embedded"`), `"Junto al vídeo"` (`kind === "file"` con etiqueta sin `/`), `"Carpeta de subtítulos"` (el resto). Las opciones con `supported: false` no entran en ningún grupo y se cuentan en `hidden`. También `sourceChoices(project)`, que sustituye a la de `app.js`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```js
const OPTS = [
  { id: "1", kind: "embedded", label: "Pista 2 · eng · subrip", supported: true },
  { id: "2", kind: "embedded", label: "Pista 3 · spa · hdmv_pgs", supported: false },
  { id: "3", kind: "file", label: "movie.en.srt", supported: true },
  { id: "4", kind: "file", label: "Subs/English.srt", supported: true },
];
test("sources are grouped by provenance and image tracks are hidden", () => {
  const c = domSetup();
  const r = JSON.parse(evaluate(c, `JSON.stringify(groupSources(${JSON.stringify(OPTS)}))`));
  assert.deepEqual(r.groups.map((g) => g.title), ["Pistas del vídeo", "Junto al vídeo", "Carpeta de subtítulos"]);
  assert.deepEqual(r.groups[0].items.map((i) => i.id), ["1"]);
  assert.equal(r.hidden, 1);
});
test("empty groups are omitted", () => {
  const c = domSetup();
  const r = JSON.parse(evaluate(c, `JSON.stringify(groupSources(${JSON.stringify([OPTS[3]])}))`));
  assert.deepEqual(r.groups.map((g) => g.title), ["Carpeta de subtítulos"]);
});
test("a video with only image tracks says so instead of saying there are none", () => {
  const c = domSetup();
  evaluate(c, `detail={project:{id:'a',name:'a.mkv',state:'draft',progress:0,source_kind:'reference',subtitle_options:[${JSON.stringify(OPTS[1])}]},cues:[]};renderWorkspace();`);
  const text = c.document.getElementById("workspace").textContent;
  assert.ok(text.includes("1 pista"), text);
  assert.ok(text.includes("OCR"), text);
  assert.ok(!text.includes("No se encontraron"), text);
});
test("choosing a source no longer asks for an action", () => {
  const c = domSetup();
  evaluate(c, `detail={project:{id:'a',name:'a.mkv',state:'draft',progress:0,source_kind:'reference',subtitle_options:${JSON.stringify(OPTS)}},cues:[]};renderWorkspace();`);
  assert.equal(c.document.getElementById("subtitle-action"), null);
  assert.ok(c.document.getElementById("start-project"));
});
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `npm test 2>&1 | grep -E "grouped by provenance|empty groups|only image tracks|no longer asks"`
Expected: FAIL las cuatro.

- [ ] **Step 3: Crear `frontend/sources.js` con `groupSources` y `sourceChoices`**

`sourceChoices` dibuja los grupos como lista con encabezados, no como `<select>` nativo. `#subtitle-source` pasa a ser un `<div role="radiogroup">` que contiene un `<input type="radio" name="subtitle-source">` por fuente, ASR incluido con `value="asr"`. Así su `textContent` sigue conteniendo las etiquetas —la prueba de polling existente lo lee— mientras el valor vive en el radio marcado. Se añade `selectedSource()`, que devuelve el valor marcado o `""`, y `loadSubtitlePreview`, `startProject` y el rótulo del botón pasan todos por ella en vez de leer `$("subtitle-source").value`; el enlace deja de ser `.onchange` del select y pasa a escuchar `change` en el grupo. Se conserva la vista previa de solo lectura de la pista: es lo que permite identificar una pista sin idioma, y es reciente y deliberada.

Transcribir con ASR no pertenece a ninguno de los tres grupos de procedencia, porque genera en vez de importar: va en un cuarto bloque al final, rotulado "Si ninguna sirve", como en la pantalla 3 del mockup.

Desaparece el `<select id="subtitle-action">`. En su lugar un único botón primario `start-project`, rotulado "Transcribir" cuando la fuente es ASR y "Usar esta fuente" en los demás casos, que llama a `/start` con `action: "edit"` siempre. El botón queda por encima de la vista previa, no por debajo, para no obligar a recorrer mil filas antes de poder actuar.

Cuando `hidden > 0`, bajo los grupos aparece una línea en `.tiny`, con las dos formas escritas: `"1 pista de imagen oculta: necesita OCR."` y `"N pistas de imagen ocultas: necesitan OCR."` Sólo cuando no hay ningún grupo **y** `hidden` es 0 se dice que no se encontró nada.

- [ ] **Step 4: Reescribir las tres aserciones existentes**

La de la línea 152 deja de exigir `option[value="pgs"][disabled]` y pasa a exigir que `pgs` no aparezca y que el aviso de OCR sí. Las de 379-380 y 464 dejan de hablar de Acción y de `action: "view"`: la primera comprueba el rótulo del botón según la fuente, la segunda que el cuerpo enviado lleva `action: "edit"`.

- [ ] **Step 5: Ejecutar las pruebas**

Run: `npm test`
Expected: 49 pass, 0 fail.

- [ ] **Step 6: Commit**

```bash
git add frontend/sources.js frontend/app.js frontend/index.html tests/frontend.test.cjs
git commit -m "feat: grouped subtitle source picker without the action step"
```

---

### Task 9: El selector de pista de audio sólo cuando importa

Hoy el `<label>Audio del vídeo` y el de volumen están siempre bajo el reproductor (`app.js:162`), ocupando una fila permanente en todos los proyectos, incluidos los que ya tienen sus segmentos y no van a transcribir nada.

**Files:**
- Modify: `frontend/app.js:160-175` (armazón del reproductor y cada render), `frontend/index.html` (estilos del detalle plegable)
- Test: `tests/frontend.test.cjs`

- [ ] **Step 1: Escribir la prueba que falla**

```js
test("audio track controls fold away once cues exist", () => {
  const t = JSON.stringify([{ index: 1, label: "Pista 1 · und · aac" }]);
  const c = domSetup();
  evaluate(c, `detail={project:{id:'a',name:'a.mkv',state:'draft',progress:0,source_kind:'reference',audio_tracks:${t},subtitle_options:[]},cues:[]};renderWorkspace();`);
  assert.ok(c.document.querySelector("#audio-controls[open]"));
  evaluate(c, `detail.project.state='ready';detail.project.progress=100;detail.cues=[{id:'1',start:1,end:2,original:'hi',translated:''}];renderWorkspace();`);
  assert.equal(c.document.querySelector("#audio-controls[open]"), null);
});
```

La segunda mitad reutiliza el mismo proyecto a propósito: `renderWorkspace` sólo reconstruye el armazón cuando cambia `workspace.dataset.projectId`, así que el atributo `open` tiene que fijarse en **cada** render, no sólo al construir.

- [ ] **Step 2: Ejecutar y ver que falla**

Run: `npm test 2>&1 | grep -A3 "fold away"`
Expected: FAIL.

- [ ] **Step 3: Envolver los controles de audio en `<details id="audio-controls">`**

Rotulado "Pista de audio". En cada render, `open` se fija a `workspaceMode(...) === "draft"`: elegir pista es parte del trabajo sólo mientras no hay segmentos. `configurePlayerAudio` no cambia: sigue encontrando `audio-track`, `audio-volume`, `player-audio` y `audio-status` por id dentro del detalle.

- [ ] **Step 4: Ejecutar las dos suites**

Run: `npm test && .venv/bin/python -m pytest -q`
Expected: 50 pass y 61 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js frontend/index.html tests/frontend.test.cjs
git commit -m "feat: fold audio track controls away once cues exist"
```

---

### Task 10: Verificación final sobre la aplicación real

- [ ] **Step 1: Reconstruir**

Run: `docker compose up -d --build`

- [ ] **Step 2: Comprobar el recorrido**

En http://localhost:3000: la biblioteca se pliega y se despliega; un proyecto "Listo" abre directamente editable, sin botón "Editar o mejorar" y sin "Quitar de biblioteca" en el encabezado; un proyecto en "Elige los subtítulos" muestra las fuentes agrupadas, sin pistas de imagen y con el botón por encima de la vista previa. Sin pulsar nada que escriba datos.

- [ ] **Step 3: Suites completas**

Run: `npm test && .venv/bin/python -m pytest -q`
Expected: 50 pass, 0 fail y 61 passed.

- [ ] **Step 4: Actualizar el README**

Las secciones que describen el recorrido mencionan "La primera acción es **Ver subtítulos**", el desplegable de Acción y **Editar o mejorar** como paso previo. Reescribirlas para el recorrido nuevo.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: describe the single editable view"
```

---

## Fuera de la Parte 1

Las fases 4 y 5 del diseño —idioma destino, y cambios en vivo con detención— están en la **Parte 2** de este mismo archivo, tareas 11 a 20, después de la parada obligatoria. Las dos dependen de la fase 2 y son independientes entre sí.

La fase 3, insertar y borrar segmentos, **está aplazada a una versión mayor**. No la construyas ni la prepares: nada de este plan debe dejar hueco para ella. En particular, la tabla de subtítulos no lleva columna de acciones por fila, y "Revertir última mejora" se comporta hoy como siempre, porque sin inserción ni borrado el conjunto de segmentos no cambia.

---

## Parada obligatoria antes de la Parte 2

**Detente aquí.** La Parte 2 no empieza en la misma ejecución que la Parte 1.

Las fases 4 y 5 se construyen sobre el código tal como quede cuando la Parte 1
haya aterrizado y esté commiteada, y mientras se escribía esta parte había otro
trabajo en vuelo en `backend/app/worker.py` y `backend/app/project_sources.py`
(transcripción incremental). Antes de abrir la Tarea 11:

- Confirma que el árbol está limpio y que las dos suites pasan.
- Anota los dos números de partida de `npm test` y de
  `.venv/bin/python -m pytest -q`. En la Parte 2 cada tarea expresa lo que
  espera como un **incremento sobre el recuento con el que esa tarea empieza**,
  nunca como un absoluto: el código se mueve, y las partes 2A y 2B se pueden
  hacer en cualquier orden.
- **Localiza el código por nombre de símbolo, no por número de línea.** Los
  números que aparecen en esta parte son orientativos y pueden haberse movido.

---

## Parte 2 · Fases 4 y 5

Dos bloques independientes entre sí. El 2A (tareas 11 a 15) parametriza el
idioma destino; el 2B (tareas 16 a 20) muestra los cambios en vivo y permite
detener. Se pueden ejecutar en cualquier orden; si se hacen los dos, la tarea 20
cierra los dos.

### Decisión fijada: la lista de idiomas destino

El diseño deja la lista al constructor. **La fijo yo**, porque un código de
idioma acaba dentro de un nombre de archivo en el disco del usuario
(`mac-worker/local_files.py` no interviene, pero `export_next_to_source` compone
`f"{source.stem}.{req.language}"`), así que no puede ser texto libre. Los
códigos son exactamente estos siete, y la misma lista se valida **dos veces**:
en el backend y en el gateway.

| Código | Rótulo en la interfaz | Frase para el prompt |
|---|---|---|
| `es` | Español (España) | español de España |
| `en` | Inglés | inglés |
| `pt-BR` | Portugués (Brasil) | portugués de Brasil |
| `fr` | Francés | francés |
| `it` | Italiano | italiano |
| `de` | Alemán | alemán |
| `ca` | Catalán | catalán |

`es` es el valor por omisión en todas partes. Un proyecto sin la clave
`target_language` en `source.json` se comporta exactamente como hoy.

### Decisión fijada: los proyectos de copia no cambian de idioma

Cambiar de idioma **obliga** a guardar antes la traducción saliente en un
archivo (decisión cerrada del diseño), y eso sólo se puede hacer junto al vídeo
original. Los proyectos antiguos de copia (`project.filename != "source.json"`)
no tienen vídeo original localizable: `export_local` ya les devuelve 409 y
`as_project` no les lee `source.json` en absoluto. Escribirles un `source.json`
cruzaría además la frontera de confianza contenedor→host, porque el gateway usa
la existencia de ese archivo para distinguir un proyecto de referencia.

Por tanto: en un proyecto de copia el idioma destino es `es`, fijo, y el
selector aparece deshabilitado con el motivo escrito. No es una regresión: hoy
tampoco pueden traducir a otra cosa.

### Review Focus (Parte 2)

1. **Un literal `"es"` olvidado exporta originales en silencio.** El código
   `"es"` significa hoy dos cosas a la vez: "la columna traducida" y "el idioma
   español". La fase 4 las separa. Los seis sitios donde aparece son
   `LocalExportRequest.language`, el `pattern` y el nombre de archivo de
   `get_export`, `ExportRequest.language` del gateway, la comparación
   `language == 'es'` de `subtitles.export`, `defaultExportLanguage` y los
   `<option>` del selector de exportación. Si se cambia el `pattern` y no la
   comparación, exportar "traducción" devuelve los originales sin avisar. →
   Tarea 13, con un paso de `grep` que lo verifica.
2. **Deshacer después de cambiar de idioma provoca un 409 engañoso.**
   `CueEditor` guarda en su pila de deshacer el texto del idioma anterior y lo
   reenvía con `expected`; el servidor responde "Este segmento cambió en otra
   pestaña", que es falso y asusta. → Tarea 15.
3. **Un proyecto detenido que se queda sin editar es el anti-objetivo exacto.**
   El estado `"stopped"` tiene que atravesar las cuatro puertas de
   `("ready", "failed")` de `main.py` más `workspaceMode` y `stateName` en el
   frontend. Una puerta olvidada deja al usuario con el trabajo hecho y la tabla
   bloqueada. → Tarea 16, con una prueba por puerta.
4. **Una bandera de detención que sobrevive mata el trabajo siguiente.** Si se
   pide detener justo cuando el lote final terminaba, el archivo queda en disco
   y el siguiente encolado se detiene solo tras su primer lote. → Tarea 17:
   se borra en **todos** los caminos de encolado.
5. **`stop_requested` no expuesto pierde "Deteniendo…" al recargar.** El
   refresco de 4 segundos reconstruye el aviso desde el proyecto; si la
   intención de detener sólo vive en memoria del navegador, el botón "Detener"
   reaparece habilitado un segundo después de pulsarlo. → Tarea 18.

---

## Parte 2A · Fase 4: idioma destino

### Task 11: El gateway acepta idiomas y marcas parciales

El gateway es la frontera de confianza con el disco del usuario: valida la lista
por su cuenta, sin fiarse del backend.

**Files:**
- Modify: `mac-worker/server.py` (`TranslateRequest`, `translate`, `ExportRequest`, `export_next_to_source`)
- Test: `tests/test_gateway.py`

**Interfaces:**
- Produces: `LANGUAGES`, un `dict` de código → frase para el prompt, con las siete entradas de la tabla de arriba. `TranslateRequest.language: Literal[...]` con esos siete códigos, por omisión `"es"`. `ExportRequest.language: Literal[...]` con los siete códigos **más** `"original"`, y `ExportRequest.partial: bool = False`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_translation_prompt_follows_the_requested_language(gateway, monkeypatch):
    payloads = []

    def respond(request, timeout):
        payloads.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"response": '{"1":"Hello"}'}).encode())

    monkeypatch.setattr(server.urllib.request, "urlopen", respond)
    result = gateway.post(
        "/translate",
        json={"texts": ["Hola"], "language": "en"},
        headers={"X-Worker-Token": server.TOKEN},
    )
    assert result.json() == {"texts": ["Hello"]}
    assert "inglés" in payloads[0]["prompt"]
    assert "español de España" not in payloads[0]["prompt"]


def test_translation_rejects_an_unknown_language(gateway):
    assert (
        gateway.post(
            "/translate",
            json={"texts": ["Hola"], "language": "../../etc"},
            headers={"X-Worker-Token": server.TOKEN},
        ).status_code
        == 422
    )
```

Y una tercera, sobre el nombre del archivo parcial, reutilizando el montaje de
`test_export_saves_next_to_original_without_overwriting`:

```python
    result = gateway.post(
        "/files/export",
        headers=headers,
        json={"project_id": pid, "content": "1\n00:00:00,000 --> 00:00:01,000\nHi\n",
              "language": "en", "format": "srt", "partial": True},
    )
    assert result.json()["filename"] == "Movie.en.srt.part"
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `.venv/bin/python -m pytest tests/test_gateway.py -q -k "language or partial"`
Expected: FAIL las tres.

- [ ] **Step 3: Parametrizar el prompt y el nombre del archivo**

`translate` compone la instrucción con `LANGUAGES[req.language]`:
`f"Traduce subtítulos audiovisuales al {LANGUAGES[req.language]} con naturalidad y precisión. No resumas, no añadas información."` El resto del endpoint
—el reintento uno a uno y el rechazo de líneas vacías— no cambia.

`export_next_to_source` añade el sufijo `.part` **después** de la extensión:
`dest = source.parent / f"{base}{suffix}.{req.format}{'.part' if req.partial else ''}"`.
El orden importa: con `.part` al final, `discover_subtitles` no lo ofrece como
fuente seleccionable (sólo acepta sufijos en `{.srt,.vtt,.ass,.ssa}`), que es
exactamente lo que queremos de una traducción a medias. El bucle de 10000
intentos con `open("x")` no cambia: sigue sin sobrescribir nada.

- [ ] **Step 4: Ejecutar las pruebas**

Run: `.venv/bin/python -m pytest tests/test_gateway.py -q`
Expected: todas pasan.

- [ ] **Step 5: Commit**

```bash
git add mac-worker/server.py tests/test_gateway.py
git commit -m "feat: let the gateway translate into a chosen language"
```

---

### Task 12: El idioma destino vive en `source.json`

**Files:**
- Create: `backend/app/languages.py`
- Modify: `backend/app/project_sources.py` (`save_workflow`), `backend/app/main.py` (`as_project`, `StartRequest`, `start_project`), `backend/app/worker.py` (`process_project`)
- Test: `tests/test_api.py` o `tests/test_native_api.py`, `tests/test_worker.py`

**Interfaces:**
- Produces: `backend/app/languages.py` con `TARGET_LANGUAGES`, un `dict` de los siete códigos a su rótulo de interfaz (columna 2 de la tabla), y `DEFAULT_LANGUAGE = "es"`. `save_workflow(pid, source, action, audio_index=None, asr_language=None, target_language=None)`, siguiendo el patrón de `asr_language` que ya existe: la clave sólo se escribe si el argumento no es `None`. `as_project` añade `target_language` (por omisión `"es"`), `target_languages` (la lista de `{code, label}` de `TARGET_LANGUAGES`, en el orden de la tabla, para que el frontend no la duplique) y `can_change_language` (`False` cuando `filename != "source.json"`).

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_project_reports_its_target_language(...):
    # un proyecto de referencia iniciado con target_language "en" lo expone
    # en GET /api/projects y can_change_language es True
    # un proyecto sin la clave expone "es"

def test_copy_projects_cannot_change_language(...):
    # filename != "source.json" → target_language "es", can_change_language False
```

Y en `tests/test_worker.py`, que el cuerpo enviado a `/translate` lleve el
idioma del proyecto:

```python
def test_worker_translates_into_the_project_language(...):
    # source.json con target_language "fr" → cada mac_post("/translate", …)
    # incluye {"language": "fr"}; sin la clave, incluye "es"
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `.venv/bin/python -m pytest -q -k "target_language or cannot_change_language or project_language"`
Expected: FAIL.

- [ ] **Step 3: Implementar**

`StartRequest` gana `target_language: Literal[...] = "es"` con los siete códigos.
`start_project` lo pasa a `save_workflow`. `process_project` lee
`reference(pid).get("target_language", "es")` **una vez**, antes del bucle de
lotes, y lo incluye en cada `mac_post("/translate", …)`. Leerlo una vez basta:
la puerta de estado impide cambiar el idioma mientras el trabajo corre.

- [ ] **Step 4: Ejecutar las pruebas**

Run: `.venv/bin/python -m pytest -q`
Expected: los recuentos de antes de esta tarea más 3 en pytest, 0 fallos.

- [ ] **Step 5: Commit**

```bash
git add backend/app/languages.py backend/app/project_sources.py backend/app/main.py backend/app/worker.py tests/
git commit -m "feat: record the target language per project"
```

---

### Task 13: Exportar la traducción, no "el español"

**Files:**
- Modify: `backend/app/subtitles.py` (`export`), `backend/app/main.py` (`LocalExportRequest`, `export_local`, `get_export`), `frontend/app.js` (`defaultExportLanguage`, el grupo de exportación de `renderWorkspace`)
- Test: `tests/test_api.py`, `tests/frontend.test.cjs`

**Interfaces:**
- Produces: `export(cues, language, vtt)` devuelve originales cuando `language == "original"` y traducciones en cualquier otro caso. `LocalExportRequest.language: Literal["translated", "original"] = "translated"`. `get_export` con `pattern="^(translated|original)$"`. `defaultExportLanguage(cues)` devuelve `"translated"` o `"original"`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_export_uses_the_translated_column_for_any_language(...):
    # POST export/local con language "translated" en un proyecto cuyo
    # target_language es "en" → el gateway recibe language "en"
    # GET export?language=translated → Content-Disposition con ".en.srt"
    # GET export?language=es → 422
```

```js
test("the export selector offers the project's target language", () => {
  // target_language "fr" → #export-language tiene value "translated" con
  // rótulo que contiene "Francés", y value "original"; no existe #language
});
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `.venv/bin/python -m pytest -q -k translated_column; npm test 2>&1 | grep -A3 "target language"`
Expected: FAIL.

- [ ] **Step 3: Separar "columna" de "idioma"**

En `subtitles.export`, la condición pasa a `c.original if language == "original" else c.translated`. El backend es el único que traduce
`"translated"` al código del proyecto: `export_local` lee
`reference(pid).get("target_language", "es")` y envía ese código al gateway
cuando el cuerpo pide `"translated"`, o `"original"` cuando pide originales.
`get_export` hace lo mismo para el nombre del archivo descargado:
`f"{pid}.{code}.{format}"`.

En el frontend, el `<select>` de exportación pasa a `id="export-language"` —el
id `language` queda libre y **no se reutiliza**, para que un selector no se
confunda con el otro— con dos opciones: `translated`, rotulada
`Traducción (<rótulo del idioma>)`, y `original`.

- [ ] **Step 4: Verificar que no queda ningún `"es"` colgando**

Run: `grep -rn "'es'\|\"es\"" backend/app frontend/*.js mac-worker/server.py | grep -v languages.py`
Expected: ninguna línea donde `"es"` signifique "la columna traducida". Las que
queden son valores por omisión del idioma destino, y son correctas.

- [ ] **Step 5: Ejecutar las dos suites**

Run: `npm test && .venv/bin/python -m pytest -q`
Expected: los recuentos de antes de esta tarea más 1 en `npm test` y 1 en pytest, 0 fallos.

- [ ] **Step 6: Commit**

```bash
git add backend/app/subtitles.py backend/app/main.py frontend/app.js tests/
git commit -m "feat: export the translation in the project's target language"
```

---

### Task 14: Cambiar de idioma guarda lo hecho antes de vaciar

El orden no es negociable: **primero el archivo, después la columna.** Si el
guardado falla, el cambio de idioma no se realiza y nada se pierde.

**Files:**
- Modify: `backend/app/main.py` (nuevo endpoint)
- Test: `tests/test_native_api.py`

**Interfaces:**
- Consumes: `TARGET_LANGUAGES` y `save_workflow(..., target_language=…)` de la Tarea 12; `export(cues, "translated", vtt)` de la Tarea 13; `ExportRequest.partial` del gateway, Tarea 11.
- Produces: `POST /api/projects/{pid}/target-language`, cuerpo `{"language": <código>}`, respuesta `{"language": <código>, "saved": <nombre de archivo o null>}`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_changing_language_saves_the_outgoing_translation_first(...):
    # dos segmentos traducidos, uno vacío → el gateway recibe /files/export con
    # language "es" y partial True; después las tres columnas translated están
    # vacías y source.json dice "en"

def test_a_failing_export_leaves_the_language_and_the_translation_intact(...):
    # el gateway devuelve 409 → la respuesta es 409, source.json sigue en "es"
    # y las traducciones siguen ahí

def test_changing_language_is_refused_while_processing(...):
    # state "translating" → 409

def test_changing_language_is_refused_on_copy_projects(...):
    # filename != "source.json" → 409
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `.venv/bin/python -m pytest tests/test_native_api.py -q -k language`
Expected: FAIL las cuatro.

- [ ] **Step 3: Implementar el endpoint**

En este orden exacto, todo dentro de una sesión con
`select(...).with_for_update()`:

1. 404 si no existe; `require_visible`.
2. 409 si `project.state` no está en `EDITABLE_STATES` si la Tarea 16 ya ha
   aterrizado, y en `("ready", "failed")` si no. Las dos partes son
   independientes: la que llegue segunda alinea esta comprobación.
3. 409 si `project.filename != "source.json"`, con el motivo escrito.
4. Si el código pedido es el que ya tiene, devolver `{"language": …, "saved": None}` sin tocar nada.
5. Si **algún** segmento tiene traducción: `export(cues, "translated", False)` y
   `native_request("POST", "/files/export", json={... "language": <código saliente>,
   "format": "srt", "partial": <algún segmento sin traducir>})`. Cualquier error
   del gateway se propaga tal cual y **aquí termina la petición**: no se ha
   tocado nada.
6. Vaciar `translated` en todos los segmentos, `save_workflow(..., target_language=<nuevo>)`, `db.commit()`.

Si ningún segmento tiene traducción, el paso 5 se salta y `saved` es `None`.

- [ ] **Step 4: Ejecutar las pruebas**

Run: `.venv/bin/python -m pytest -q`
Expected: los recuentos de antes de esta tarea más 4 en pytest, 0 fallos.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py tests/test_native_api.py
git commit -m "feat: save the outgoing translation when the target language changes"
```

---

### Task 15: El selector de idioma destino en la barra del editor

**Files:**
- Modify: `frontend/app.js` (`editorToolbar`, los enlaces de `renderWorkspace`), `frontend/index.html` (estilos del selector)
- Test: `tests/frontend.test.cjs`

- [ ] **Step 1: Escribir las pruebas que fallan**

```js
test("the target language selector is disabled on copy projects", () => {
  // can_change_language false → #target-language existe, está disabled y
  // la razón se muestra como title
});

test("changing the target language rebuilds the editor", () => {
  // con un proyecto editable y traducciones: cambiar #target-language llama a
  // POST /api/projects/<id>/target-language con {language:"en"} y después
  // cueEditor es un objeto nuevo (editorProject vuelve a null antes del render)
});
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `npm test 2>&1 | grep -E "disabled on copy|rebuilds the editor"`
Expected: FAIL las dos.

- [ ] **Step 3: Añadir el selector y su confirmación**

`editorToolbar` añade, en el grupo de la izquierda y sólo cuando no es
`readOnly`, un `<select id="target-language" aria-label="Idioma de la traducción">` con las siete opciones de `TARGET_LANGUAGES` —el rótulo lo
sirve `as_project`, así que el frontend no duplica la tabla: la lista llega en
`project.target_language` más una lista `target_languages` que `as_project`
expone junto a él— y `selected` en el actual. Deshabilitado cuando
`can_change_language` es falso, con `title` explicando que el proyecto no
conserva la ubicación del vídeo.

Al cambiar, en este orden:

1. `confirm()` con el texto exacto: `"Se guardará la traducción actual junto al vídeo y la columna quedará vacía para traducir al idioma nuevo. ¿Continuar?"` Si se cancela, el `<select>` vuelve a su valor anterior.
2. `if (busy || !(await settleEdits())) return;`
3. `POST` al endpoint de la Tarea 13. Si responde error, `alert` con el mensaje
   y el `<select>` vuelve atrás; **nada más**.
4. Si responde bien y trae `saved`, `alert` con el nombre del archivo guardado.
5. `cueEditor = null; editorProject = null;` y `refresh()`. Esto es obligatorio,
   no cosmético: la pila de deshacer de `CueEditor` contiene el texto del idioma
   anterior y lo reenviaría con `expected`, provocando el 409 de "cambió en otra
   pestaña", que sería mentira.

- [ ] **Step 4: Ejecutar las dos suites**

Run: `npm test && .venv/bin/python -m pytest -q`
Expected: los recuentos de antes de esta tarea más 2 en `npm test`, pytest sin cambio, 0 fallos.

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js frontend/index.html tests/frontend.test.cjs
git commit -m "feat: choose the target language from the editor toolbar"
```

---

## Parte 2B · Fase 5: cambios en vivo y detener

### Task 16: El estado "detenido", distinto de "fallido"

`Project.state` es `Column(String)` (`backend/app/core.py`), no un enumerado, así
que un valor nuevo no necesita migración. Lo que sí necesita es atravesar todas
las puertas: un proyecto detenido que no se puede editar sería el anti-objetivo
del diseño cumplido al pie de la letra.

**Files:**
- Modify: `backend/app/main.py` (las cuatro comprobaciones `("ready", "failed")`), `frontend/app.js` (`stateName`, `workspaceMode`)
- Test: `tests/test_api.py`, `tests/frontend.test.cjs`

**Interfaces:**
- Produces: `EDITABLE_STATES = {"ready", "failed", "stopped"}` en `backend/app/main.py`, junto a `ACTIVE_STATES`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Una prueba parametrizada que recorra las cuatro puertas sobre un proyecto en
estado `"stopped"`:

```python
@pytest.mark.parametrize("call", ["cue", "translate", "improve", "undo"])
def test_a_stopped_project_stays_editable(client, call, ...):
    # PUT cues/<id> → 200; POST translate → 200; POST improve → 200;
    # POST improve/undo → 404 "no hay mejora" (no 409 "espera")
```

Y en el frontend:

```js
test("a stopped project is editable and says so", () => {
  // state "stopped" con segmentos → workspaceMode devuelve "editable",
  // stateName devuelve "Detenido" y la tabla no lleva readonly
});
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `.venv/bin/python -m pytest -q -k stopped; npm test 2>&1 | grep -A3 "stopped project"`
Expected: FAIL.

- [ ] **Step 3: Abrir las puertas**

Sustituir las cuatro comprobaciones `if ... state not in ("ready", "failed")` de
`update_cue`, `translate_pending`, `improve_transcript` y `undo_improvement` por
`EDITABLE_STATES`. **`retry_project` no cambia**: sigue aceptando sólo
`"failed"`. Retomar una traducción detenida es "Traducir pendientes", que ya
rellena únicamente las entradas vacías; reintentar es para fallos.

En el frontend, `stateName` gana `stopped: "Detenido"` y la lista de
`workspaceMode` pasa a `["ready", "failed", "stopped"]`.

- [ ] **Step 4: Ejecutar las dos suites**

Run: `npm test && .venv/bin/python -m pytest -q`
Expected: los recuentos de antes de esta tarea más 1 en `npm test` y 4 en pytest, 0 fallos.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py frontend/app.js tests/
git commit -m "feat: treat a stopped project as editable, not failed"
```

---

### Task 17: La bandera de detención y los lotes del worker

El mecanismo lo elijo yo: **un archivo en `data/<UUID>/stop`**. La API y el
worker comparten ese volumen —las instantáneas de mejora ya lo demuestran—, no
añade columna ninguna (restricción 1) y sobrevive a un reinicio de Redis. Su
sola presencia significa "no empieces otro lote".

**Files:**
- Create: `backend/app/stopping.py`
- Modify: `backend/app/worker.py` (los dos bucles de lotes), `backend/app/main.py` (`enqueue_project`, `translate_pending`, `retry_project`, `improve_transcript`)
- Test: `tests/test_worker.py`

**Interfaces:**
- Produces: `request_stop(pid)`, `stop_requested(pid) -> bool`, `clear_stop(pid)`. `clear_stop` borra el archivo si existe y no falla si no.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_translation_stops_between_batches_and_keeps_what_it_did(...):
    # 18 segmentos, la bandera se escribe durante el segundo lote →
    # mac_post("/translate") se llama exactamente 2 veces, los 12 primeros
    # segmentos quedan traducidos, el estado final es "stopped" con error ""
    # y el archivo de bandera ya no existe

def test_a_stop_flag_from_a_previous_run_never_touches_the_next_job(...):
    # bandera presente antes de encolar → translate_pending la borra y el
    # trabajo completa los tres lotes

def test_improvement_stops_between_batches_and_can_still_be_undone(...):
    # estado final "stopped", backup["stopped"] True, y POST improve/undo
    # devuelve el proyecto a previous_state
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `.venv/bin/python -m pytest tests/test_worker.py -q -k stop`
Expected: FAIL las tres.

- [ ] **Step 3: Comprobar antes de cada lote**

En los dos bucles —el de traducción en `process_project` y el de mejora en
`improve_project`— la primera línea del cuerpo del `for` es la comprobación,
**antes del primer lote incluido**:

```python
if stop_requested(pid):
    clear_stop(pid)
    set_status(pid, "stopped", <progreso alcanzado>)
    return
```

En `improve_project`, antes del `return`, se escribe `backup["stopped"] = True`
con `improvement.write(path, backup)`, para que `undo_improvement` sepa que esa
mejora quedó a medias por decisión del usuario y no por un fallo. La condición
de restauración de estado de `undo_improvement` pasa a cubrir los dos casos:
`(project.state == "stopped" and backup.get("stopped"))` o la de
`"Mejora incompleta:"` que ya existe.

`clear_stop(pid)` se llama en **los cuatro** caminos que ponen trabajo en la
cola: `enqueue_project`, `translate_pending`, `retry_project` y
`improve_transcript`. Una bandera que sobrevive a su trabajo mata el siguiente
tras su primer lote, y el usuario no tendría ni cómo saber por qué.

- [ ] **Step 4: Ejecutar las pruebas**

Run: `.venv/bin/python -m pytest -q`
Expected: los recuentos de antes de esta tarea más 3 en pytest, 0 fallos.

- [ ] **Step 5: Commit**

```bash
git add backend/app/stopping.py backend/app/worker.py backend/app/main.py tests/test_worker.py
git commit -m "feat: stop translation and improvement between batches"
```

---

### Task 18: Pedir la detención, y decir que no es instantánea

**Files:**
- Modify: `backend/app/main.py` (nuevo endpoint, `as_project`), `frontend/app.js` (el aviso de procesamiento de `renderWorkspace`)
- Test: `tests/test_api.py`, `tests/frontend.test.cjs`

**Interfaces:**
- Consumes: `request_stop` y `stop_requested` de la Tarea 17.
- Produces: `POST /api/projects/{pid}/stop` → `{"stopping": True}`. `as_project` añade `stop_requested: bool`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_stop_is_only_offered_while_batches_run(client, ...):
    # state "translating" → 200 y as_project dice stop_requested True
    # state "improving" → 200
    # state "transcribing" → 409; "queued" → 409; "ready" → 409
```

```js
test("the stop button says it is stopping and does not come back", () => {
  // state "translating" → existe #stop-processing habilitado
  // stop_requested true → sigue existiendo, disabled, y su texto es "Deteniendo…"
  // state "transcribing" → no existe
});
```

El tercer caso es el que importa más: ASR no tiene lotes que interrumpir ni
resultado parcial que conservar (restricciones 7 y 8), así que ofrecer el botón
sería prometer algo que no se puede cumplir.

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `.venv/bin/python -m pytest -q -k stop_is_only_offered; npm test 2>&1 | grep -A3 "says it is stopping"`
Expected: FAIL.

- [ ] **Step 3: Implementar**

El endpoint devuelve 409 si el estado no es `"translating"` ni `"improving"`, con
el motivo escrito (`"La transcripción no se puede detener a mitad"` para
`transcribing` y `queued`, `"No hay nada en marcha"` para el resto). No cambia
el estado: sólo escribe la bandera. Es el worker quien pasa a `"stopped"`.

En el frontend, el aviso de procesamiento lleva el botón
`<button id="stop-processing">`, rotulado `Detener` o `Deteniendo…` y
deshabilitado según `project.stop_requested`, con una línea en `.tiny`:
`"Se detendrá al terminar el lote en curso; lo ya traducido se conserva."` La espera
máxima es un lote de seis, y no se puede acortar: el bucle de traducción escribe
`translated` sin comprobar nada, así que devolver la edición antes de que el
lote en vuelo termine permitiría que pisara lo que el usuario acaba de
escribir.

- [ ] **Step 4: Ejecutar las dos suites**

Run: `npm test && .venv/bin/python -m pytest -q`
Expected: los recuentos de antes de esta tarea más 1 en `npm test` y 1 en pytest, 0 fallos.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py frontend/app.js tests/
git commit -m "feat: ask to stop a running batch job"
```

---

### Task 19: Ver los cambios llegando

No hay que tocar el worker: traducción y mejora ya hacen `db.commit()` por lote
(restricción 5) y `refresh()` ya vuelve a renderizar cada 4 segundos mientras
procesa, porque su guarda `!busy && !pendingEdits() && !dirty.size` se cumple
cuando el usuario no está editando. Lo que falta es **decir qué cambió** y
**cuánto queda**.

**Files:**
- Modify: `frontend/app.js` (`renderWorkspace`, `editorToolbar`), `frontend/index.html` (la animación)
- Test: `tests/frontend.test.cjs`

- [ ] **Step 1: Escribir la prueba que falla**

```js
test("rows that just changed are marked, and only those", () => {
  // primer render traduciendo, tres segmentos sin traducir
  // segundo render con el segundo segmento ya traducido →
  // sólo esa fila lleva la clase "cue-fresh", y el recuento dice "1 de 3"
  // tercer render sin cambios → ninguna fila lleva la clase
});
```

- [ ] **Step 2: Ejecutar y ver que falla**

Run: `npm test 2>&1 | grep -A3 "just changed are marked"`
Expected: FAIL.

- [ ] **Step 3: Marcar las filas y contar**

`renderWorkspace` guarda, en una variable de módulo junto a `viewedCues`, el
valor del campo relevante de cada segmento por id tal como se renderizó la vez
anterior: `translated` mientras el estado es `"translating"`, `original`
mientras es `"improving"`. En el render siguiente, cada fila cuyo valor difiera
del guardado recibe la clase `cue-fresh`. El mapa se reinicia al cambiar de
proyecto y al salir de un estado activo.

La clase se aplica en el marcado, no después: `renderWorkspace` reconstruye
`#project-content` con `innerHTML` en cada pasada, así que una animación CSS
sobre una clase recién puesta arranca sola. En `index.html`:
`.cue-fresh { animation: cue-fresh 1.4s ease-out; }` con un fotograma inicial de
fondo acentuado, y `@media (prefers-reduced-motion: reduce)` que la sustituye
por un borde izquierdo acentuado sin animación.

El recuento va en el aviso de solo lectura de `editorToolbar`, que es lo que se
dibuja mientras procesa: `N de M traducidos` cuando el estado es
`"translating"`, `N de M revisados` cuando es `"improving"`. Se cuenta sobre los
segmentos, no sobre `project.progress`, porque es el número que el usuario puede
verificar mirando la tabla.

- [ ] **Step 4: Ejecutar las dos suites**

Run: `npm test && .venv/bin/python -m pytest -q`
Expected: los recuentos de antes de esta tarea más 1 en `npm test`, pytest sin cambio, 0 fallos.

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js frontend/index.html tests/frontend.test.cjs
git commit -m "feat: mark the rows a running job just changed"
```

---

### Task 20: Verificación final de la Parte 2

- [ ] **Step 1: Reconstruir**

Run: `docker compose up -d --build`

- [ ] **Step 2: Comprobar sin escribir datos**

En http://localhost:3000, con los datos reales de Federico: el selector de
idioma destino aparece en la barra del editor de un proyecto listo y muestra el
idioma actual; el selector de exportación dice "Traducción (…)" con ese mismo
idioma. **No pulses** "Abrir archivo local", "Mejorar transcripción",
"Revertir", "Quitar", "Vaciar", el selector de idioma destino, ni escribas en
ningún campo de segmento: todo eso escribe en los proyectos del usuario o abre
un diálogo nativo en su pantalla. Lo que hay que comprobar aquí es lo que se ve,
no lo que hace.

- [ ] **Step 3: Las dos suites completas**

Run: `npm test && .venv/bin/python -m pytest -q`
Expected: 0 fail, 0 failed.

- [ ] **Step 4: Actualizar el README**

Las secciones que describen la traducción dicen "al español" y las de
exportación hablan de `es`. Reescribirlas: el idioma destino se elige por
proyecto entre los siete de la lista, cambiarlo guarda la traducción saliente
junto al vídeo (con `.part` si quedó a medias), y una traducción o una mejora en
marcha se puede detener entre lotes, conservando lo hecho.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: describe the target language and stopping a running job"
```
