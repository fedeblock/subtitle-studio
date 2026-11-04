let projects = [],
  selected = null,
  detail = null,
  dirty = new Set(),
  busy = false,
  refreshing = false,
  selectionRevision = 0;
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
    if (selected && !busy && dirty.size === 0) {
      const pid = selected,
        revision = selectionRevision;
      const newDetail = await api(`/api/projects/${pid}`);
      if (
        selected !== pid ||
        revision !== selectionRevision ||
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
  if (dirty.size && !confirm("Hay cambios sin guardar. ¿Cambiar de proyecto?"))
    return;
  selected = pid;
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
  $("project-content").innerHTML =
    `<div class="controls"><span class="muted">${cues.length} segmentos · ${p.source_kind === "reference" ? "Archivo original, sin copia" : "Copia local existente"}</span><span class="tiny">Los cambios se guardan por segmento.</span></div>${ready ? `<div class="cue tiny" style="border-top:1px solid #2d394f"><div>TIEMPOS</div><div>TEXTO ORIGINAL</div><div>TRADUCCIÓN AL ESPAÑOL</div><div>GUARDAR</div></div><div class="editor" id="editor">${cues.map((c, i) => `<div class="cue" data-cue="${c.id}" data-start="${c.start}" data-end="${c.end}"><div class="time"><span class="tiny">#${i + 1}</span><input aria-label="Inicio" class="start" value="${time(c.start)}"><input aria-label="Fin" class="end" value="${time(c.end)}"></div><textarea class="original" aria-label="Original">${esc(c.original)}</textarea><textarea class="translated" aria-label="Español">${esc(c.translated)}</textarea><div class="save"><button class="savebtn" disabled>Guardar</button></div></div>`).join("")}</div>` : p.state === "draft" ? sourceChoices(p) : '<div class="notice">Puedes previsualizar el original mientras se procesa. Durante la transcripción no hay un porcentaje de avance disponible; la primera ejecución puede necesitar descargar modelos.</div>'}`;
  if ($("start-project")) $("start-project").onclick = () => startProject(p.id);
  if ($("retry")) $("retry").onclick = () => retryProject(p.id);
  if (ready) {
    if (p.action === "edit") $("language").value = "original";
    $("export").onclick = () => {
      if (busy || dirty.size) {
        alert("Guarda los cambios antes de exportar.");
        return;
      }
      location.href = `/api/projects/${p.id}/export?language=${$("language").value}&format=${$("format").value}`;
    };
    document.querySelectorAll(".cue[data-cue]").forEach((row) => {
      row.querySelectorAll("input,textarea").forEach(
        (el) =>
          (el.oninput = () => {
            dirty.add(row.dataset.cue);
            row.querySelector(".savebtn").disabled = false;
          }),
      );
      row.querySelector(".savebtn").onclick = () => saveCue(row);
      row.ondblclick = (e) => {
        if (["TEXTAREA", "INPUT", "BUTTON"].includes(e.target.tagName)) return;
        $("video").currentTime = +row.dataset.start;
        $("video").play();
      };
    });
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
  if (busy || dirty.size) {
    alert("Guarda los cambios antes de reintentar.");
    return;
  }
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
async function saveCue(row) {
  if (busy) return;
  const pid = selected;
  let id = row.dataset.cue;
  let start = secs(row.querySelector(".start").value),
    end = secs(row.querySelector(".end").value);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    alert("Tiempos incorrectos. Usa HH:MM:SS.mmm");
    return;
  }
  const btn = row.querySelector(".savebtn");
  btn.disabled = true;
  btn.textContent = "Guardando";
  busy = true;
  const fields = [...row.querySelectorAll("input,textarea")];
  fields.forEach((el) => (el.disabled = true));
  try {
    const saved = await api(`/api/projects/${pid}/cues/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        start,
        end,
        original: row.querySelector(".original").value,
        translated: row.querySelector(".translated").value,
      }),
    });
    const index = detail.cues.findIndex((c) => c.id === id);
    if (index >= 0) detail.cues[index] = saved;
    row.dataset.start = start;
    row.dataset.end = end;
    dirty.delete(id);
    btn.textContent = "Guardado ✓";
    setTimeout(() => {
      btn.textContent = "Guardar";
    }, 1400);
  } catch (e) {
    btn.textContent = "Reintentar";
    btn.disabled = false;
    alert(e.message);
  } finally {
    fields.forEach((el) => (el.disabled = false));
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
  if (dirty.size || busy) {
    e.preventDefault();
    e.returnValue = "";
  }
});
$("open-local").onclick = openLocalFile;
refresh();
setInterval(refresh, 4000);
