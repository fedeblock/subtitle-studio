let projects = [],
  selected = null,
  detail = null,
  dirty = new Set(),
  busy = false,
  refreshing = false,
  selectionRevision = 0,
  editRevision = 0,
  cueEditor = null,
  editorProject = null,
  viewingTrash = false,
  selectedCue = null,
  subtitlePreviewRevision = 0,
  viewedCues = [];
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
    projects = await api(`/api/projects${viewingTrash ? "?hidden=true" : ""}`);
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
    : `<div class="empty">${viewingTrash ? "Papelera vacía." : "Aún no hay proyectos."}</div>`;
  if ($("show-trash"))
    $("show-trash").textContent = viewingTrash ? "Ver biblioteca" : "Papelera";
  if ($("clear-library")) $("clear-library").hidden = viewingTrash;
  if ($("restore-library")) $("restore-library").hidden = !viewingTrash;
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
  cleanupAudioPreview();
  viewedCues = [];
  selected = pid;
  selectedCue = null;
  subtitlePreviewRevision++;
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
  const finished =
    !viewingTrash && ["ready", "failed"].includes(p.state) && cues.length > 0;
  const viewMode = finished && p.action === "view";
  const ready = finished && !viewMode;
  const showReadOnly = !ready && p.state !== "draft" && cues.length > 0;
  const oldScroll = $("editor")?.scrollTop || 0;
  const workspace = $("workspace");
  if (workspace.dataset.projectId !== p.id || !$("video")) {
    workspace.innerHTML = `<div id="project-header"></div><div class="player-frame"><video id="video" class="player" controls preload="metadata" src="/api/projects/${p.id}/media"></video><div id="video-subtitles" class="video-subtitles" hidden></div></div><div id="media-error" class="notice error" hidden></div><div id="project-content"></div>`;
    workspace.dataset.projectId = p.id;
    $("video").addEventListener("timeupdate", updateVideoSubtitles);
    $("video").addEventListener("seeked", updateVideoSubtitles);
    $("video").onerror = () => {
      const message = $("media-error");
      message.hidden = false;
      message.textContent =
        "No se puede reproducir el original. Comprueba que sigue en su ubicación y que el navegador admite su formato. Los subtítulos se pueden editar igualmente.";
    };
  }
  $("project-header").innerHTML =
    `<div class="top"><div><h2>${esc(p.name)}</h2><span class="status ${esc(p.state)}">Estado: ${esc(stateName(p))}</span></div>${finished ? '<div class="group"><select id="language"><option value="es">Español</option><option value="original">Original</option></select><select id="format"><option>srt</option><option>vtt</option></select><button id="export" class="primary">Guardar junto al vídeo</button><button id="download">Descargar</button></div>' : ""}<button id="project-remove">${viewingTrash ? "Restaurar" : "Quitar de biblioteca"}</button></div>${p.error ? `<div class="notice error">${esc(p.error)} ${p.state === "failed" && !viewingTrash ? '<button id="retry">Reintentar pendientes</button>' : ""}</div>` : ""}`;
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
  cleanupAudioPreview();
  $("project-content").innerHTML =
    `<div class="controls"><span class="muted">${cues.length} segmentos · ${p.source_kind === "reference" ? "Archivo original, sin copia" : "Copia local existente"}</span></div>${viewMode ? `<div class="group"><button id="edit-view">Editar o mejorar</button>${cues.some(c => !(c.translated || "").trim()) ? '<button id="translate-view">Traducir pendientes</button>' : ""}</div>` : ""}${ready ? editorMarkup(cues, p) : showReadOnly ? editorMarkup(cues, p, true) : p.state === "draft" ? (viewingTrash ? '<div class="notice">Restaura el proyecto para procesarlo.</div>' : sourceChoices(p)) : '<div class="notice">Puedes previsualizar el original mientras se procesa. Durante la transcripción no hay un porcentaje de avance disponible; la primera ejecución puede necesitar descargar modelos.</div>'}`;
  if (viewMode) {
    viewedCues = cues;
    updateVideoSubtitles();
    $("edit-view").onclick = () => editViewedProject(p.id);
    if ($("translate-view")) $("translate-view").onclick = () => translatePending(p.id);
  }
  if ($("editor")) $("editor").scrollTop = oldScroll;
  if ($("project-remove"))
    $("project-remove").onclick = () => removeProject(p.id);
  if ($("start-project")) {
    $("start-project").onclick = () => startProject(p.id);
    $("subtitle-source").onchange = () => {
      updateDraftAction();
      return loadSubtitlePreview(p.id);
    };
    $("subtitle-action").onchange = updateDraftAction;
    updateDraftAction();
    if ($("audio-track")) {
      $("audio-track").onchange = () => configureAudioPreview(p.id);
      $("refresh-audio-preview").onclick = () => configureAudioPreview(p.id);
      configureAudioPreview(p.id);
    }
  }
  if (cues.length) {
    document.querySelectorAll(".cue[data-cue]").forEach((row) => {
      row.onfocusin = () => {
        if (selectedCue !== row.dataset.cue) seekCue(row);
      };
      row.onfocusout = (event) => {
        if (!event.relatedTarget || !row.contains(event.relatedTarget))
          selectedCue = null;
      };
      row.onclick = (event) => {
        if (!["TEXTAREA", "INPUT", "BUTTON"].includes(event.target.tagName))
          seekCue(row);
      };
    });
  }
  if ($("retry")) $("retry").onclick = () => retryProject(p.id);
  if (finished) {
    if (p.action === "edit" || p.action === "view") $("language").value = "original";
    $("export").onclick = async () => {
      if (busy || !(await settleEdits())) return;
      busy = true;
      try {
        const saved = await api(`/api/projects/${p.id}/export/local`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            language: $("language").value,
            format: $("format").value,
          }),
        });
        alert(`Subtítulos guardados en: ${saved.path}`);
      } catch (error) {
        alert(`${error.message} Puedes usar Descargar.`);
      } finally {
        busy = false;
      }
    };
    $("download").onclick = async () => {
      if (busy || !(await settleEdits())) return;
      location.href = `/api/projects/${p.id}/export?language=${$("language").value}&format=${$("format").value}`;
    };
  }
  if (ready) {
    if ($("translate-pending"))
      $("translate-pending").onclick = () => translatePending(p.id);
    document.querySelectorAll(".cue[data-cue]").forEach((row) => {
      row.querySelectorAll("input,textarea").forEach((el) => {
        el.oninput = () => {
          editRevision++;
          dirty.add(row.dataset.cue);
          updateSaveStatus();
        };
        el.onblur = () => commitField(row, el);
      });
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
function seekCue(row) {
  const start = Number(row.dataset.start);
  if (!Number.isFinite(start) || !$("video")) return;
  selectedCue = row.dataset.cue;
  $("video").currentTime = start;
}
function updateVideoSubtitles() {
  const video = $("video"),
    display = $("video-subtitles");
  if (!video || !display) return;
  const now = video.currentTime;
  const lines = viewedCues
    .filter((cue) => cue.start <= now && now < cue.end)
    .map((cue) => cue.original);
  display.textContent = lines.join("\n");
  display.hidden = lines.length === 0;
}

async function loadSubtitlePreview(pid) {
  const select = $("subtitle-source"),
    target = $("subtitle-preview");
  if (!select || !target) return;
  const source = select.value,
    revision = ++subtitlePreviewRevision;
  viewedCues = [];
  updateVideoSubtitles();
  if (!source || source === "asr") {
    target.hidden = true;
    target.innerHTML = "";
    return;
  }
  target.hidden = false;
  target.dataset.loadedSource = "";
  target.textContent = "Cargando subtítulos…";
  try {
    const data = await api(
      `/api/projects/${pid}/subtitle-preview?subtitle_id=${encodeURIComponent(source)}`,
    );
    if (
      revision !== subtitlePreviewRevision ||
      $("subtitle-source") !== select ||
      selected !== pid ||
      select.value !== source
    )
      return;
    viewedCues = data.cues;
    updateVideoSubtitles();
    target.dataset.loadedSource = source;
    target.innerHTML = `<strong>Subtítulos de esta pista · ${data.cues.length} segmentos</strong><p class="tiny">Solo lectura. Selecciona un segmento para ir a ese momento del vídeo.</p>${data.cues.length ? `<ol>${data.cues.map((c) => `<li><button type="button" class="preview-segment" data-start="${Number(c.start)}"><span class="tiny">${time(c.start)}</span> ${esc(c.original)}</button></li>`).join("")}</ol>` : "<p>No se encontraron líneas con tiempos válidos.</p>"}`;
    target.onclick = (event) => {
      const entry = event.target.closest?.(".preview-segment");
      if (!entry || !target.contains(entry)) return;
      const start = Number(entry.dataset.start);
      if (Number.isFinite(start) && $("video")) $("video").currentTime = start;
    };
  } catch (error) {
    if (revision === subtitlePreviewRevision && $("subtitle-source") === select)
      target.textContent = `No se pudo mostrar la pista: ${error.message}`;
  }
}
function cleanupAudioPreview() {
  const audio = $("audio-preview"),
    video = $("video");
  if (!audio || !video) return;
  const active = audio.paused === false;
  audio.onpause = audio.onplay = audio.ontimeupdate = null;
  video.onpause = video.onplay = video.onplaying = video.onseeked = null;
  if (active) {
    audio.pause();
    video.pause();
    video.muted = audio.dataset.previousMuted === "1";
  }
}
function configureAudioPreview(pid) {
  const select = $("audio-track"),
    previous = $("audio-preview"),
    video = $("video");
  if (!select || !previous || !video) return;
  // A fresh element prevents queued events from the previous sample affecting this one.
  cleanupAudioPreview();
  const audio = previous.cloneNode(false);
  previous.replaceWith(audio);
  const start = Number.isFinite(video.currentTime)
    ? Math.max(0, video.currentTime)
    : 0;
  const index = Number(select.value);
  if (!Number.isInteger(index) || index < 0) return;
  let sampleActive = false,
    videoStarted = false;
  const sampleDuration = () =>
    Number.isFinite(audio.duration) ? Math.min(audio.duration, 30) : 30;
  audio.dataset.start = String(start);
  audio.src = `/api/projects/${pid}/audio-preview?index=${index}&start=${start.toFixed(3)}`;
  $("audio-preview-position").textContent =
    `Muestra de hasta 30 s desde ${time(start)}. Usa los controles para escucharla.`;
  audio.onplay = () => {
    sampleActive = true;
    videoStarted = false;
    audio.dataset.previousMuted = video.muted ? "1" : "0";
    video.muted = true;
    try {
      video.currentTime = start + audio.currentTime;
    } catch {}
    try {
      const playing = video.play();
      if (playing?.catch) playing.catch(() => {});
    } catch {}
  };
  audio.ontimeupdate = () => {
    if (
      !audio.paused &&
      Math.abs(video.currentTime - (start + audio.currentTime)) > 0.8
    ) {
      try {
        video.currentTime = start + audio.currentTime;
      } catch {}
    }
  };
  audio.onpause = () => {
    video.pause();
    video.muted = audio.dataset.previousMuted === "1";
  };
  audio.onended = () => {
    sampleActive = false;
  };
  audio.onerror = () => {
    sampleActive = false;
    $("audio-preview-position").textContent =
      "No se puede escuchar esta pista en esta posición. Prueba otra posición o pista.";
  };
  video.onplaying = () => {
    if (sampleActive && video.paused === false) videoStarted = true;
  };
  video.onpause = () => {
    if (
      sampleActive &&
      videoStarted &&
      video.paused === true &&
      audio.paused === false
    )
      audio.pause();
  };
  video.onplay = () => {
    if (
      sampleActive &&
      audio.paused &&
      video.currentTime >= start &&
      video.currentTime < start + sampleDuration()
    ) {
      const playing = audio.play();
      if (playing?.catch) playing.catch(() => {});
    }
  };
  video.onseeked = () => {
    if (!sampleActive) return;
    const position = video.currentTime - start;
    if (position < 0 || position >= sampleDuration()) {
      sampleActive = false;
      if (!audio.paused) audio.pause();
      $("audio-preview-position").textContent =
        "Posición fuera de la muestra. Pulsa «Escuchar desde la posición del vídeo».";
      return;
    }
    if (Math.abs(audio.currentTime - position) > 0.4)
      audio.currentTime = position;
  };
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
function editorMarkup(cues, project, readOnly = false) {
  const toolbar = readOnly
    ? `<div class="notice">${project.action === "view" && project.state === "ready" ? "Vista de solo lectura. Puedes elegir editar o traducir cuando quieras." : "Segmentos visibles en modo lectura mientras se procesa; la edición se reactivará al terminar."}</div>`
    : `<div class="editor-toolbar"><div class="group"><button id="undo-edit" title="Deshacer (⌘Z / Ctrl+Z)">↶ Deshacer</button><button id="redo-edit" title="Rehacer (⌘⇧Z / Ctrl+Shift+Z)">↷ Rehacer</button><button id="retry-save" hidden>Reintentar guardado</button><button id="improve-text" title="Corregir puntuación y mayúsculas con Ollama">Mejorar transcripción</button>${cues.some((c) => !(c.translated || "").trim()) ? '<button id="translate-pending">Traducir pendientes</button>' : ""}${project.can_undo_improvement ? '<button id="undo-improvement">Revertir última mejora</button>' : ""}</div><span id="save-status" role="status" aria-live="polite"></span></div><p class="tiny">Guardado automático al salir de cada campo · Deshacer disponible durante esta sesión del proyecto.</p>`;
  return `${toolbar}<div class="editor" id="editor"><table class="subtitle-table"><colgroup><col class="number-col"><col class="time-col"><col class="time-col"><col><col></colgroup><thead><tr><th scope="col">#</th><th scope="col">mark-in</th><th scope="col">mark-out</th><th scope="col">sub original (o transcripción)</th><th scope="col">traducción</th></tr></thead><tbody>${cues
    .map((item, i) => {
      const c = cueEditor?.get(item.id) || item;
      return `<tr class="cue" tabindex="0" data-cue="${c.id}" data-start="${c.start}" data-end="${c.end}"><td class="cue-number">${i + 1}</td><td><input aria-label="Mark-in ${i + 1}" class="start" data-field="start" ${readOnly ? "readonly" : ""} value="${time(c.start)}"></td><td><input aria-label="Mark-out ${i + 1}" class="end" data-field="end" ${readOnly ? "readonly" : ""} value="${time(c.end)}"></td><td><textarea class="original" data-field="original" ${readOnly ? "readonly" : ""} aria-label="Original ${i + 1}">${esc(c.original)}</textarea></td><td><textarea class="translated" data-field="translated" ${readOnly ? "readonly" : ""} aria-label="Traducción ${i + 1}">${esc(c.translated)}</textarea></td></tr>`;
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
  const options = p.subtitle_options || [],
    tracks = p.audio_tracks || [];
  return `<div class="notice"><h2>¿Qué subtítulos quieres usar?</h2><p>El vídeo se lee desde su ubicación original. No se copia ni se envía a Internet.</p><label>Fuente <select id="subtitle-source"><option value="" selected disabled>Elige una fuente</option><option value="asr">Generar desde el audio con ASR</option>${options.map((o) => `<option value="${esc(o.id)}" ${o.supported ? "" : "disabled"}>${esc(o.label)} · ${o.kind === "embedded" ? "incrustado" : "archivo"}${o.supported ? "" : " · requiere OCR/conversión"}</option>`).join("")}</select></label>${tracks.length ? `<label> Pista de audio para transcribir <select id="audio-track">${tracks.map((t) => `<option value="${t.index}">${esc(t.label)}</option>`).join("")}</select></label><div class="audio-sample"><audio id="audio-preview" controls preload="none"></audio><div id="audio-preview-position" class="tiny"></div><button id="refresh-audio-preview" type="button">Escuchar desde la posición del vídeo</button></div>` : ""}<div id="subtitle-preview" class="subtitle-preview" hidden></div><label> Acción <select id="subtitle-action"><option value="view" selected>Ver subtítulos</option><option value="edit">Editar o mejorar</option><option value="translate">Traducir al español</option></select></label><button id="start-project" class="primary">Ver subtítulos</button>${options.length ? "" : "<p>No se encontraron archivos de subtítulos ni pistas incrustadas.</p>"}${(p.source_warnings || []).map((w) => `<p>${esc(w)}</p>`).join("")}</div>`;
}
function updateDraftAction() {
  if (!$("start-project") || !$("subtitle-action") || !$("subtitle-source"))
    return;
  const viewing = $("subtitle-action").value === "view";
  $("start-project").textContent = viewing
    ? $("subtitle-source").value === "asr"
      ? "Transcribir para ver"
      : "Ver subtítulos"
    : "Continuar";
}
async function startProject(pid) {
  if (busy) return;
  const source = $("subtitle-source").value;
  if (!source) {
    alert("Elige una fuente de subtítulos.");
    return;
  }
  const action = $("subtitle-action").value;
  if (action === "view" && source !== "asr") {
    if ($("subtitle-preview").dataset.loadedSource !== source)
      await loadSubtitlePreview(pid);
    $("subtitle-preview")?.scrollIntoView?.({
      block: "nearest",
      behavior: "smooth",
    });
    return;
  }
  busy = true;
  $("start-project").disabled = true;
  try {
    await api(`/api/projects/${pid}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source,
        action,
        audio_index:
          source === "asr" && $("audio-track")
            ? Number($("audio-track").value)
            : null,
      }),
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
async function editViewedProject(pid) {
  if (busy) return;
  busy = true;
  try {
    await api(`/api/projects/${pid}/edit-mode`, { method: "POST" });
    busy = false;
    await select(pid);
    await refresh();
  } catch (error) {
    alert(error.message);
  } finally {
    busy = false;
  }
}
async function translatePending(pid) {
  if (busy || !(await settleEdits())) return;
  busy = true;
  try {
    await api(`/api/projects/${pid}/translate`, { method: "POST" });
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
async function resetWorkspace() {
  if (busy || !(await settleEdits())) return false;
  cleanupAudioPreview();
  selected = null;
  viewedCues = [];
  detail = null;
  cueEditor = null;
  editorProject = null;
  selectionRevision++;
  $("workspace").innerHTML = '<div class="empty">Selecciona un proyecto.</div>';
  return true;
}
async function removeProject(pid) {
  if (busy || !(await settleEdits())) return;
  const restoring = viewingTrash;
  if (
    !restoring &&
    !confirm(
      "¿Quitar este proyecto de la biblioteca? Podrás restaurarlo desde la papelera. No se borrarán los archivos.",
    )
  )
    return;
  try {
    await api(`/api/projects/${pid}${restoring ? "/restore" : ""}`, {
      method: restoring ? "POST" : "DELETE",
    });
    await resetWorkspace();
    await refresh();
  } catch (error) {
    alert(error.message);
  }
}
async function toggleTrash() {
  if (!(await resetWorkspace())) return;
  viewingTrash = !viewingTrash;
  await refresh();
}
async function clearLibrary() {
  if (busy || !(await settleEdits())) return;
  if (
    !confirm(
      "¿Quitar los proyectos de la biblioteca? Los archivos se conservan y los proyectos se podrán restaurar desde la papelera. Los trabajos activos permanecerán visibles.",
    )
  )
    return;
  try {
    const result = await api("/api/library/clear", {
      method: "POST",
      headers: { "X-Studio-Local": "1" },
    });
    await resetWorkspace();
    await refresh();
    if (result.active)
      alert(`${result.active} proyecto(s) siguen activos y no se quitaron.`);
  } catch (error) {
    alert(error.message);
  }
}
async function restoreLibrary() {
  if (busy || !(await settleEdits())) return;
  try {
    await api("/api/library/restore", {
      method: "POST",
      headers: { "X-Studio-Local": "1" },
    });
    await resetWorkspace();
    await refresh();
  } catch (error) {
    alert(error.message);
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
$("show-trash").onclick = toggleTrash;
$("clear-library").onclick = clearLibrary;
$("restore-library").onclick = restoreLibrary;
refresh();
setInterval(refresh, 4000);
