let projects = [],
  selected = null,
  detail = null,
  dirty = new Set(),
  busy = false,
  refreshing = false,
  selectionRevision = 0,
  editRevision = 0,
  cueEditor = null,
  editorProject = null;
const $ = (x) => document.getElementById(x),
  esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
const stateName = (p) =>
  ({
    draft: "Elige los subtítulos",
    queued: "En cola",
    transcribing: "Transcripción en curso",
    translating: `Traduciendo · ${p.progress}%`,
    improve_queued: "Mejora en cola",
    improving: `Mejorando texto · ${p.progress}%`,
    ready: "Listo",
    failed: "Necesita atención",
  })[p.state] || p.state;
async function api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let v;
    try {
      v = await r.json();
    } catch {}
    throw Error(v?.detail || `Error HTTP ${r.status}`);
  }
  return r.headers.get("content-type")?.includes("application/json")
    ? r.json()
    : r.text();
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    projects = await api("/api/projects");
    renderList();
    if (selected && !busy && !pendingEdits() && dirty.size === 0) {
      const pid = selected,
        revision = selectionRevision,
        edits = editRevision;
      const newDetail = await api(`/api/projects/${pid}`);
      if (
        selected !== pid ||
        revision !== selectionRevision ||
        edits !== editRevision ||
        pendingEdits() ||
        busy ||
        dirty.size
      )
        return;
      const previous = detail;
      detail = newDetail;
      if (JSON.stringify(previous) !== JSON.stringify(detail))
        renderWorkspace();
    }
  } catch (e) {
    $("projects").textContent = e.message;
  } finally {
    refreshing = false;
  }
}
function renderList() {
  $("projects").innerHTML = projects.length
    ? projects
        .map(
          (p) =>
            `<button class="project ${selected === p.id ? "active" : ""}" data-id="${p.id}"><div class="name">${esc(p.name)}</div><small>${esc(stateName(p))}</small><div class="progress"><span style="width:${p.progress}%"></span></div></button>`,
        )
        .join("")
    : '<div class="empty">Aún no hay proyectos.</div>';
  document
    .querySelectorAll(".project")
    .forEach((b) => (b.onclick = () => select(b.dataset.id)));
}
async function select(pid) {
  if (busy) {
    alert("Espera a que termine el guardado.");
    return;
  }
  if ((dirty.size || pendingEdits()) && !(await settleEdits())) return;
  selected = pid;
  if (editorProject !== pid) {
    cueEditor = null;
    editorProject = null;
  }
  const revision = ++selectionRevision;
  dirty.clear();
  detail = null;
  renderList();
  $("workspace").textContent = "Cargando…";
  try {
    const loaded = await api(`/api/projects/${pid}`);
    if (selected !== pid || revision !== selectionRevision) return;
    detail = loaded;
    renderWorkspace();
  } catch (e) {
    if (revision === selectionRevision) $("workspace").textContent = e.message;
  }
}
const time = (t) => {
  let ms = Math.max(0, Math.round((Number(t) || 0) * 1000));
  const h = Math.floor(ms / 3600000);
  ms %= 3600000;
  const m = Math.floor(ms / 60000);
  ms %= 60000;
  const s = Math.floor(ms / 1000);
  ms %= 1000;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
};
const secs = (s) => {
  const match = /^(\d+):([0-5]\d):([0-5]\d)(?:[.,](\d{1,3}))?$/.exec(s.trim());
  if (!match) return NaN;
  return (
    Number(match[1]) * 3600 +
    Number(match[2]) * 60 +
    Number(match[3]) +
    Number((match[4] || "").padEnd(3, "0")) / 1000
  );
};
function renderWorkspace() {
  if (!detail) return;
  let p = detail.project,
    cues = detail.cues;
  const ready = ["ready", "failed"].includes(p.state) && cues.length > 0;
  const workspace = $("workspace");
  if (workspace.dataset.projectId !== p.id || !$("video")) {
    workspace.innerHTML = `<div id="project-header"></div><video id="video" class="player" controls preload="metadata" src="/api/projects/${p.id}/media"></video><div id="media-error" class="notice error" hidden></div><div id="project-content"></div>`;
    workspace.dataset.projectId = p.id;
    $("video").onerror = () => {
      const message = $("media-error");
      message.hidden = false;
      message.textContent =
        "No se puede reproducir el original. Comprueba que sigue en su ubicación y que el navegador admite su formato. Los subtítulos se pueden editar igualmente.";
    };
  }
  $("project-header").innerHTML =
    `<div class="top"><div><h2>${esc(p.name)}</h2><span class="status ${esc(p.state)}">Estado: ${esc(stateName(p))}</span></div>${ready ? '<div class="group"><select id="language"><option value="es">Español</option><option value="original">Original</option></select><select id="format"><option>srt</option><option>vtt</option></select><button id="export" class="primary">Exportar</button></div>' : ""}</div>${p.error ? `<div class="notice error">${esc(p.error)} ${p.state === "failed" ? '<button id="retry">Reintentar pendientes</button>' : ""}</div>` : ""}`;
  if (!ready) {
    cueEditor = null;
    editorProject = null;
  }
  if (ready && (!cueEditor || editorProject !== p.id)) {
    editorProject = p.id;
    cueEditor = new CueEditor(
      cues,
      (id, value, expected) =>
        api(`/api/projects/${p.id}/cues/${id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...value, expected }),
        }),
      (saved) => {
        if (detail?.project.id !== p.id) return;
        if (saved) {
          const index = detail.cues.findIndex((c) => c.id === saved.id);
          if (index >= 0) detail.cues[index] = saved;
        }
        updateSaveStatus();
      },
    );
  }
  if (ready && cueEditor && !dirty.size && !pendingEdits())
    cueEditor.reconcile(cues);
  $("project-content").innerHTML =
    `<div class="controls"><span class="muted">${cues.length} segmentos · ${p.source_kind === "reference" ? "Archivo original, sin copia" : "Copia local existente"}</span></div>${ready ? editorMarkup(cues, p) : p.state === "draft" ? sourceChoices(p) : '<div class="notice">Puedes previsualizar el original mientras se procesa. Durante la transcripción no hay un porcentaje de avance disponible; la primera ejecución puede necesitar descargar modelos.</div>'}`;
  if ($("start-project")) $("start-project").onclick = () => startProject(p.id);
  if ($("retry")) $("retry").onclick = () => retryProject(p.id);
  if (ready) {
    if (p.action === "edit") $("language").value = "original";
    $("export").onclick = async () => {
      if (busy || !(await settleEdits())) return;
      location.href = `/api/projects/${p.id}/export?language=${$("language").value}&format=${$("format").value}`;
    };
    document.querySelectorAll(".cue[data-cue]").forEach((row) => {
      row.querySelectorAll("input,textarea").forEach((el) => {
        el.oninput = () => {
          editRevision++;
          dirty.add(row.dataset.cue);
          updateSaveStatus();
        };
        el.onblur = () => commitField(row, el);
      });
      row.ondblclick = (e) => {
        if (["TEXTAREA", "INPUT", "BUTTON"].includes(e.target.tagName)) return;
        $("video").currentTime = +row.dataset.start;
        $("video").play();
      };
    });
    $("improve-text").onclick = () => improveText(p.id);
    if ($("undo-improvement"))
      $("undo-improvement").onclick = () => undoImprovement(p.id);
    $("undo-edit").onclick = () => historyEdit("undo");
    $("redo-edit").onclick = () => historyEdit("redo");
    $("retry-save").onclick = () => cueEditor.retry();
    updateSaveStatus();
    $("video").ontimeupdate = () => {
      let t = $("video").currentTime;
      document
        .querySelectorAll(".cue[data-cue]")
        .forEach((row) =>
          row.classList.toggle(
            "active",
            t >= +row.dataset.start && t < +row.dataset.end,
          ),
        );
    };
  }
}
async function retryProject(pid) {
  if (busy || !(await settleEdits())) return;
  busy = true;
  try {
    await api(`/api/projects/${pid}/retry`, { method: "POST" });
    busy = false;
    if (selected === pid) await select(pid);
    await refresh();
  } catch (e) {
    alert(e.message);
  } finally {
    busy = false;
  }
}
function pendingEdits() {
  return !!cueEditor?.pending.length;
}
function editorMarkup(cues, project) {
  return `<div class="editor-toolbar"><div class="group"><button id="undo-edit" title="Deshacer (⌘Z / Ctrl+Z)">↶ Deshacer</button><button id="redo-edit" title="Rehacer (⌘⇧Z / Ctrl+Shift+Z)">↷ Rehacer</button><button id="retry-save" hidden>Reintentar guardado</button><button id="improve-text" title="Corregir puntuación y mayúsculas con Ollama">Mejorar transcripción</button>${project.can_undo_improvement ? '<button id="undo-improvement">Revertir última mejora</button>' : ""}</div><span id="save-status" role="status" aria-live="polite"></span></div><p class="tiny">Guardado automático al salir de cada campo · Deshacer disponible durante esta sesión del proyecto.</p><div class="editor" id="editor"><table class="subtitle-table"><colgroup><col class="number-col"><col class="time-col"><col class="time-col"><col><col></colgroup><thead><tr><th scope="col">#</th><th scope="col">mark-in</th><th scope="col">mark-out</th><th scope="col">sub original (o transcripción)</th><th scope="col">traducción</th></tr></thead><tbody>${cues
    .map((item, i) => {
      const c = cueEditor.get(item.id) || item;
      return `<tr class="cue" data-cue="${c.id}" data-start="${c.start}" data-end="${c.end}"><td class="cue-number">${i + 1}</td><td><input aria-label="Mark-in ${i + 1}" class="start" data-field="start" value="${time(c.start)}"></td><td><input aria-label="Mark-out ${i + 1}" class="end" data-field="end" value="${time(c.end)}"></td><td><textarea class="original" data-field="original" aria-label="Original ${i + 1}">${esc(c.original)}</textarea></td><td><textarea class="translated" data-field="translated" aria-label="Traducción ${i + 1}">${esc(c.translated)}</textarea></td></tr>`;
    })
    .join("")}</tbody></table></div>`;
}
function updateSaveStatus() {
  if (!$("save-status") || !cueEditor) return;
  const invalid = document.querySelector?.('[aria-invalid="true"]');
  const error = cueEditor.error;
  $("save-status").textContent = error
    ? `Sin guardar: ${error.message}`
    : invalid
      ? "Revisa los tiempos marcados; ese cambio no se ha guardado."
      : pendingEdits()
        ? `Guardando… (${cueEditor.pending.length})`
        : dirty.size
          ? "Editando… se guardará al salir del campo"
          : "Todos los cambios guardados";
  $("save-status").classList.toggle("save-error", !!(error || invalid));
  $("retry-save").hidden = !error;
  $("undo-edit").disabled = !cueEditor.undoStack.length;
  $("redo-edit").disabled = !cueEditor.redoStack.length;
}
function commitField(row, field) {
  if (!cueEditor) return;
  const key = field.dataset.field;
  const value = ["start", "end"].includes(key)
    ? secs(field.value)
    : field.value;
  try {
    cueEditor.commit(row.dataset.cue, key, value);
    field.removeAttribute("aria-invalid");
    field.removeAttribute("title");
    const desired = cueEditor.get(row.dataset.cue);
    row.dataset.start = desired.start;
    row.dataset.end = desired.end;
    const changed = [...row.querySelectorAll("input,textarea")].some((el) => {
      const k = el.dataset.field;
      return (
        (["start", "end"].includes(k) ? secs(el.value) : el.value) !==
        desired[k]
      );
    });
    if (!changed) dirty.delete(row.dataset.cue);
  } catch (error) {
    field.setAttribute("aria-invalid", "true");
    field.setAttribute("title", error.message);
    dirty.add(row.dataset.cue);
  }
  updateSaveStatus();
}
function commitActiveField() {
  const field = document.activeElement;
  const row = field?.closest?.(".cue[data-cue]");
  if (row && field.dataset.field) commitField(row, field);
}
async function settleEdits() {
  commitActiveField();
  if (dirty.size) {
    alert("Corrige los campos pendientes antes de continuar.");
    return false;
  }
  if (cueEditor && !(await cueEditor.flush())) {
    updateSaveStatus();
    return false;
  }
  if (dirty.size || pendingEdits()) {
    alert(
      "Hay cambios nuevos pendientes. Termina de editarlos antes de continuar.",
    );
    return false;
  }
  return true;
}
function historyEdit(direction) {
  commitActiveField();
  if (dirty.size || !cueEditor) return;
  const action = cueEditor[direction]();
  if (!action) return;
  editRevision++;
  const row = document.querySelector(`.cue[data-cue="${action.id}"]`);
  const value = cueEditor.get(action.id);
  const field = row?.querySelector(`[data-field="${action.field}"]`);
  if (field)
    field.value = ["start", "end"].includes(action.field)
      ? time(value[action.field])
      : value[action.field];
  if (row) {
    row.dataset.start = value.start;
    row.dataset.end = value.end;
  }
  updateSaveStatus();
}
window.addEventListener("keydown", (e) => {
  if (
    !(e.metaKey || e.ctrlKey) ||
    e.altKey ||
    e.key.toLowerCase() !== "z" ||
    !cueEditor
  )
    return;
  // Preserve native text undo while a field contains an uncommitted edit.
  if (dirty.size && e.target?.matches?.("input,textarea")) return;
  e.preventDefault();
  historyEdit(e.shiftKey ? "redo" : "undo");
});
async function improveText(pid) {
  if (busy || !(await settleEdits())) return;
  if (
    !confirm(
      "Ollama revisará puntuación y mayúsculas del texto original. Se conservará una copia para revertir la mejora; las traducciones existentes no se modificarán. ¿Continuar?",
    )
  )
    return;
  busy = true;
  try {
    await api(`/api/projects/${pid}/improve`, { method: "POST" });
    cueEditor = null;
    editorProject = null;
    busy = false;
    await select(pid);
    await refresh();
  } catch (error) {
    alert(error.message);
  } finally {
    busy = false;
  }
}
async function undoImprovement(pid) {
  if (busy || !(await settleEdits())) return;
  if (
    !confirm(
      "¿Restaurar el texto anterior a la última mejora? Los tiempos y traducciones se conservarán.",
    )
  )
    return;
  busy = true;
  try {
    await api(`/api/projects/${pid}/improve/undo`, { method: "POST" });
    cueEditor = null;
    editorProject = null;
    busy = false;
    await select(pid);
    await refresh();
  } catch (error) {
    alert(error.message);
  } finally {
    busy = false;
  }
}
function sourceChoices(p) {
  const options = p.subtitle_options || [];
  return `<div class="notice"><h2>¿Qué subtítulos quieres usar?</h2><p>El vídeo se lee desde su ubicación original. No se copia ni se envía a Internet.</p><label>Fuente <select id="subtitle-source"><option value="" selected disabled>Elige una fuente</option><option value="asr">Generar desde el audio con ASR</option>${options.map((o) => `<option value="${esc(o.id)}" ${o.supported ? "" : "disabled"}>${esc(o.label)} · ${o.kind === "embedded" ? "incrustado" : "archivo"}${o.supported ? "" : " · requiere OCR/conversión"}</option>`).join("")}</select></label><label> Acción <select id="subtitle-action"><option value="translate">Traducir al español</option><option value="edit">Solo editar / corregir</option></select></label><button id="start-project" class="primary">Continuar</button>${options.length ? "" : "<p>No se encontraron archivos de subtítulos ni pistas incrustadas.</p>"}${(p.source_warnings || []).map((w) => `<p>${esc(w)}</p>`).join("")}</div>`;
}
async function startProject(pid) {
  if (busy) return;
  const source = $("subtitle-source").value;
  if (!source) {
    alert("Elige una fuente de subtítulos.");
    return;
  }
  busy = true;
  $("start-project").disabled = true;
  try {
    await api(`/api/projects/${pid}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, action: $("subtitle-action").value }),
    });
    // Refresh the existing project without replacing its video element.
    detail = await api(`/api/projects/${pid}`);
    renderWorkspace();
  } catch (e) {
    alert(e.message);
    if ($("start-project")) $("start-project").disabled = false;
  } finally {
    busy = false;
  }
}
async function openLocalFile() {
  const button = $("open-local");
  if (button.disabled) return;
  button.disabled = true;
  button.textContent = "Elige el archivo en macOS…";
  try {
    const result = await api("/api/projects/local", {
      method: "POST",
      headers: { "X-Studio-Local": "1" },
    });
    if (result?.id) {
      await refresh();
      await select(result.id);
    }
  } catch (e) {
    alert(e.message);
  } finally {
    button.disabled = false;
    button.textContent = "Abrir archivo local";
  }
}
window.addEventListener("beforeunload", (e) => {
  if (dirty.size || busy || pendingEdits()) {
    e.preventDefault();
    e.returnValue = "";
  }
});
$("open-local").onclick = openLocalFile;
refresh();
setInterval(refresh, 4000);
