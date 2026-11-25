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
  inspectorCue = null,
  manualAnchors = {a:null, b:null},
  subtitlePreviewRevision = 0,
  initialRouteChecked = false,
  videoTextTrack = "original",
  voiceWindow = null,
  voiceRequest = 0,
  workspaceProject = null,
  currentStage = null,
  cueFilter = "all",
  editorSearch = "",
  translationDraft = null,
  exportOpen = false,
  exportLanguage = null,
  exportFormat = "srt",
  syncProposal = null,
  syncUndo = null,
  syncRunning = false,
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
    batch_queued: "En cola de lote",
    queued: "En cola",
    transcribing: "Transcripción en curso",
    translating: p.task_progress?.total ? `Traduciendo · ${p.task_progress.done}/${p.task_progress.total}` : "Traduciendo",
    improve_queued: "Mejora en cola",
    improving: `Mejorando texto · ${p.progress}%`,
    pausing: "Pausa solicitada",
    paused: "Pausado",
    cancelling: "Cancelación solicitada",
    cancelled: "Cancelado",
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
  updateTaskElapsed();
  try {
    projects = await api(`/api/projects${viewingTrash ? "?hidden=true" : ""}`);
    renderList();
    if (!initialRouteChecked) {
      initialRouteChecked = true;
      let route = "";
      try { route = window.location?.hash?.slice(1) || window.localStorage?.getItem("ss2-route") || "library"; } catch {}
      const id = route.startsWith("project:") ? route.slice(8) : null;
      if (id && projects.some(p => p.id === id)) await select(id);
      else if (['batch','queue'].includes(route) && typeof restoreAuxRoute === 'function') await restoreAuxRoute(route);
      else persistRoute("library");
    }
    if (typeof auxRoute !== 'undefined' && auxRoute === 'queue' && typeof refreshBatchQueue === 'function') void refreshBatchQueue();
    if (selected && !$('translation-dialog')?.open && !$('global-sync-dialog')?.open && !syncProposal && !document.querySelector?.('.cue-translate[open]') && !busy && !pendingEdits() && dirty.size === 0 && (typeof focusSession === 'undefined' || !focusSession)) {
      const pid = selected,
        revision = selectionRevision,
        edits = editRevision;
      const newDetail = await api(`/api/projects/${pid}`);
      if (
        selected !== pid ||
        revision !== selectionRevision ||
        edits !== editRevision ||
        $('global-sync-dialog')?.open ||
        syncProposal ||
        pendingEdits() ||
        busy ||
        (typeof focusSession !== 'undefined' && focusSession) ||
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
function persistRoute(route) {
  try {
    window.localStorage?.setItem("ss2-route", route);
    if (window.location && window.location.hash !== `#${route}`) window.location.hash = `#${route}`;
  } catch {}
}
async function select(pid) {
  if (busy) {
    alert("Espera a que termine el guardado.");
    return;
  }
  if ((dirty.size || pendingEdits()) && !(await settleEdits())) return;
  if (typeof closeAuxScreen === 'function') closeAuxScreen();
  cleanupAudioPreview();
  viewedCues = [];
  selected = pid;
  videoTextTrack = "original";
  persistRoute(`project:${pid}`);
  selectedCue = null;
  inspectorCue = null;
  manualAnchors = {a:null, b:null};
  editorSearch = "";
  translationDraft = null;
  subtitlePreviewRevision++;
  if (editorProject !== pid) {
    cueEditor = null;
    editorProject = null;
    syncProposal = null;
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
function taskProgress(project, duration) {
  const data = project.task_progress || {};
  if (project.state === 'pausing') return {label:'Pausa solicitada · esperando a que termine el tramo o lote actual.', percent:null};
  if (project.state === 'cancelling') return {label:'Cancelación solicitada · esperando a que termine el tramo o lote actual.', percent:null};
  if (project.state === 'paused') return {label:'Tarea pausada · se conserva el trabajo guardado.', percent:null};
  if (project.state === 'cancelled') return {label:'Tarea cancelada · se conserva el trabajo guardado.', percent:null};
  if (project.state === 'batch_queued' || project.state === 'queued' || project.state === 'improve_queued') return {label:'En cola · esperando turno', percent:null};
  if (project.state === 'transcribing') {
    if (typeof data.processed_seconds !== 'number') return {label:'Preparando la transcripción y los modelos…', percent:null};
    const validDuration = Number.isFinite(duration) && duration > 0;
    const seconds = Math.max(0, validDuration ? Math.min(data.processed_seconds, duration) : data.processed_seconds);
    const percent = validDuration ? Math.min(data.completed ? 100 : 99, Math.floor(100 * seconds / duration)) : null;
    const position = time(seconds).split('.')[0];
    const total = validDuration ? ` de ${time(duration).split('.')[0]}` : '';
    return {label:`Transcripción · ${position}${total} procesados${percent === null ? '' : ` · ${percent}%`}`, percent};
  }
  if (project.state === 'translating') {
    if (!(data.total > 0)) return {label:'Preparando la traducción…', percent:null};
    const percent = Math.min(100, Math.floor(100 * data.done / data.total));
    return {label:`Traducción · ${data.done} de ${data.total} segmentos · ${percent}%`, percent};
  }
  if (project.state === 'improving') {
    const percent = typeof data.percent === 'number' ? Math.max(0, Math.min(100, data.percent)) : null;
    return {label:`Mejora de transcripción${percent === null ? '…' : ` · ${percent}%`}`, percent, updatedAt:data.updated_at};
  }
  return null;
}
function renderTaskProgress() {
  const container = $('task-progress');
  if (!container || !detail) return;
  const info = taskProgress(detail.project, $('video')?.duration);
  if (!info) { container.innerHTML = ''; return; }
  const state = detail.project.state, pid = detail.project.id;
  const batch = detail.project.batch;
  const active = ['batch_queued','queued','transcribing','translating','improve_queued','improving'].includes(state);
  const controls = !viewingTrash ? `${active && batch?.status !== 'paused' ? `<button type="button" id="task-pause">${batch ? 'Pausar cola' : 'Pausar'}</button>` : ''}${state === 'paused' || batch?.status === 'paused' ? `<button type="button" id="task-resume">${batch ? 'Reanudar cola' : 'Reanudar'}</button>` : ''}${active || ['paused','pausing'].includes(state) ? '<button type="button" id="task-cancel">Cancelar tarea</button>' : ''}` : '';
  const showBar = !['paused','cancelled'].includes(state);
  container.innerHTML = `<div class="task-feedback"><div role="status" aria-live="polite"><strong>${esc(info.label)}</strong></div>${showBar ? `<progress max="100" ${info.percent === null ? '' : `value="${info.percent}"`} aria-label="${esc(info.label)}"></progress>` : ''}${info.updatedAt ? `<span class="tiny" data-progress-updated="${Number(info.updatedAt)}"></span>` : ''}${controls ? `<div class="task-actions">${controls}</div>` : ''}</div>`;
  for (const action of ['pause','resume','cancel']) if ($(`task-${action}`)) $(`task-${action}`).onclick = () => batch ? batchTaskAction(batch, action) : taskAction(pid, action);
  updateTaskElapsed();
}
async function taskAction(pid, action) {
  if (busy || !(await settleEdits())) return;
  if (action === 'cancel' && !confirm('¿Cancelar esta tarea? Se conservarán los segmentos guardados y el vídeo. El tramo o lote actual puede tardar en terminar.')) return;
  busy = true;
  try {
    await api(`/api/projects/${pid}/${action}`, {method:'POST',headers:{'X-Studio-Local':'1'}});
    busy = false;
    await select(pid);
    await refresh();
  } catch (error) { alert(error.message); }
  finally { busy = false; }
}
function updateTaskElapsed() {
  const el = document.querySelector?.('[data-progress-updated]');
  if (!el) return;
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - Number(el.dataset.progressUpdated)));
  el.textContent = seconds < 60 ? 'Último resultado recibido hace menos de un minuto.' : `Último resultado recibido hace ${Math.floor(seconds / 60)} min. Puede seguir procesando o reintentando el lote actual.`;
}
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
function workspaceMode(project, cues, inTrash) {
  if (project.state === "draft") return "draft";
  if (cues.length && inTrash) return "locked";
  if (cues.length && ["ready", "failed", "cancelled"].includes(project.state)) return "editable";
  return cues.length ? "locked" : "waiting";
}
function translationLanguage(project = {}) {
  return ({Spanish:['es','Español'],Romanian:['ro','Rumano'],English:['en','Inglés'],Portuguese:['pt','Portugués'],French:['fr','Francés'],Italian:['it','Italiano'],German:['de','Alemán'],Dutch:['nl','Neerlandés'],Japanese:['ja','Japonés'],Chinese:['zh','Chino']})[project.target_language] || ['es','Español'];
}
const translationLanguages = [['Spanish','Español'],['English','Inglés'],['Romanian','Rumano'],['Portuguese','Portugués'],['French','Francés'],['Italian','Italiano'],['German','Alemán'],['Dutch','Neerlandés'],['Japanese','Japonés'],['Chinese','Chino']];
function translationHeader(project, readOnly) {
  if (readOnly || viewingTrash || !['ready','failed','cancelled'].includes(project.state)) return 'traducción';
  const locked = project.translation_language_known && (detail?.cues || []).some(c => (c.translated || '').trim());
  const destination = translationDraft?.pid === project.id ? translationDraft.language : project.translation_language_known ? project.target_language : '';
  return `traducción <select id="translation-language" aria-label="Idioma de destino" ${locked ? 'disabled title="Idioma fijado por las traducciones existentes"' : ''}><option value="">Idioma…</option>${translationLanguages.map(([value,label])=>`<option value="${value}" ${value===destination?'selected':''}>${label}</option>`).join('')}</select>`;
}
function defaultExportLanguage(cues, project = {}) {
  return cues.some(c => (c.translated || "").trim()) ? translationLanguage(project)[0] : "original";
}


function renderExportChecks(cues) {
  const container = $('export-checks');
  if (!container) return;
  const valid = cues.filter(c => Number.isFinite(c.start) && Number.isFinite(c.end) && c.start >= 0 && c.end > c.start).length;
  const missing = cues.filter(c => !(c.translated || '').trim()).length;
  const suspicious = cues.filter(c => c.flag && !c.flag_resolved).length;
  container.innerHTML = `<p class="${valid === cues.length ? 'stage-ok' : 'stage-warning'}">${valid === cues.length ? '✓' : '⚠'} ${valid} de ${cues.length} segmentos con tiempos válidos</p>${exportLanguage === 'original' ? '' : missing ? `<p class="stage-warning">⚠ ${missing} sin traducir <button id="export-show-untranslated" type="button">ver</button></p>` : '<p class="stage-ok">✓ Todo traducido</p>'}${suspicious ? `<p class="stage-warning">⚠ ${suspicious} dudosos sin revisar <button id="export-show-suspicious" type="button">revisar</button></p>` : '<p class="stage-ok">✓ Sin dudosos pendientes</p>'}`;
  for (const [id,filter] of [['export-show-untranslated','untr'],['export-show-suspicious','sus']]) {
    const button=$(id);
    if (button) button.onclick = async () => { if (!(await settleEdits())) return; exportOpen=false; cueFilter=filter; if (filter === 'sus') currentStage='review'; renderWorkspace(); };
  }
}
function showExportToast(message) {
  let toast = $('export-toast');
  if (!toast) { toast = document.createElement('div'); toast.id='export-toast'; toast.className='export-toast'; document.body.appendChild(toast); }
  toast.textContent = message;
  setTimeout(() => toast.remove(), 2600);
}

function stageNavigation(project, cues) {
  const isDraft = project.state === 'draft';
  const running = ['queued','transcribing','translating','improve_queued','improving','pausing','cancelling'].includes(project.state);
  const suspicious = cues.filter(c => c.flag && !c.flag_resolved).length;
  return `<nav class="stage-navigation" aria-label="Etapas del proyecto">${[['source','Fuente'],['process','Procesar'],['review','Revisar'],['translate','Traducir'],['export','Exportar']].map(([stage,label],index) => `${index ? '<span class="stage-separator">›</span>' : ''}<button type="button" data-stage="${stage}" class="stage-button ${currentStage === stage ? 'current' : ''} ${stage === 'review' && suspicious ? 'warning' : ''}" ${isDraft && stage !== 'source' || stage === 'export' && running ? 'disabled' : ''}>${label}${stage === 'review' && suspicious ? ` · ${suspicious}` : ''}</button>`).join('')}</nav>`;
}
function stagePanel(project, cues) {
  if (currentStage === 'review') {
    const n = cues.filter(c => c.flag && !c.flag_resolved).length;
    return n ? `<div class="stage-summary"><strong class="stage-warning">${n} segmentos dudosos</strong><p>Revisa los segmentos marcados con el audio delante.</p><button type="button" id="start-focus-review" class="primary" ${viewingTrash || !['ready','failed','cancelled','transcribing'].includes(project.state) ? 'disabled title="La revisión estará disponible al terminar esta operación"' : ''}>Revisar uno a uno</button> <button type="button" id="show-suspicious">Ver dudosos</button></div>` : `<div class="stage-summary"><strong class="stage-ok">✓ Sin dudosos pendientes</strong><p><button type="button" id="stage-next-translate">Siguiente: traducir</button></p></div>`;
  }
  if (currentStage === 'process') return `<div class="stage-summary"><strong>Procesar</strong><p>Los tramos terminados se conservan y aparecen en la lista.</p></div>`;
  if (currentStage === 'source' && project.state !== 'draft') return '';
  if (currentStage === 'translate') {
    const pending = cues.filter(c => (c.original || '').trim() && !(c.translated || '').trim()).length;
    const completed = cues.filter(c => (c.translated || '').trim()).length;
    const existing = cues.some(c => (c.translated || '').trim());
    const locked = existing && project.translation_language_known;
    const editable = !viewingTrash && ['ready','failed','cancelled'].includes(project.state);
    const selectedLanguage = translationDraft?.pid === project.id ? translationDraft.language : project.translation_language_known ? project.target_language : "";
    const languageLabel = translationLanguages.find(([value]) => value === selectedLanguage)?.[1];
    return `<button type="button" id="open-translation-dialog">Traducir subtítulos · ${pending} pendientes</button><dialog id="translation-dialog" class="preferences-dialog translation-dialog" aria-labelledby="translation-title"><div class="preferences-heading"><strong id="translation-title">Traducir subtítulos</strong><button id="close-translation-dialog" type="button" aria-label="Cerrar">✕</button></div><div class="translation-setup"><p class="tiny">${pending} pendientes · ${completed} traducidos</p><p>Idioma de destino: <strong id="translation-language-label">${esc(languageLabel || "sin seleccionar")}</strong></p>${editable ? `<div class="translation-fields"><label>Modelo de Ollama <select id="translation-model"><option value="">Consultando modelos…</option></select></label>${pending ? '<button id="translate-pending" class="primary" type="button">Traducir pendientes</button>' : '<span class="stage-ok">Todo traducido</span>'}</div><div id="translation-model-status" class="tiny" role="status"><span class="spinner" aria-hidden="true"></span> Consultando modelos…</div>${locked ? '<p class="tiny">El idioma está fijado porque ya hay traducciones; se mantendrá para las entradas pendientes.</p>' : existing ? '<p class="tiny">Indica el idioma de las traducciones existentes en la columna: cierra esta ventana, elígelo y vuelve para confirmarlo.</p><button id="confirm-translation-language" type="button">Confirmar idioma existente</button>' : '<p class="tiny">Para elegir o cambiar el idioma, cierra esta ventana y usa el título de la columna de traducción.</p>'}` : '<p>La operación se está procesando. Los segmentos disponibles siguen visibles.</p>'}</div></dialog>`;
  }
  return '';
}
function cueFilters(cues) {
  const filters = [['all','Todo',cues.length],['sus','Dudosos',cues.filter(c=>c.flag&&!c.flag_resolved).length],['untr','Sin traducir',cues.filter(c=>!(c.translated||'').trim()).length],['prop','Mejoras propuestas',cues.filter(c=>c.proposal).length]];
  return `<div class="cue-filters">${filters.filter(([key,,n]) => key !== 'prop' || n).map(([key,label,n]) => `<button type="button" data-cue-filter="${key}" class="home-chip ${cueFilter === key ? 'active' : ''} ${key === 'sus' ? 'attention' : ''}">${label} · ${n}</button>`).join('')}</div>`;
}

function renderWorkspace() {
  if (!detail) return;
  let p = detail.project,
    cues = detail.cues;
  if (workspaceProject !== p.id) {
    workspaceProject = p.id;
    exportOpen = false; exportLanguage = null; exportFormat = "srt";
    currentStage = p.state === 'draft' ? 'source' : ['queued','transcribing'].includes(p.state) ? 'process' : cues.some(c => c.flag && !c.flag_resolved) ? 'review' : 'translate';
    cueFilter = currentStage === 'review' ? 'sus' : 'all';
  }
  const mode = workspaceMode(p, cues, viewingTrash);
  const ready = mode === "editable";
  const finished = ready;
  const showReadOnly = mode === "locked";
  const canTranslateCue = !viewingTrash && cues.length > 0 && (ready || p.state === "transcribing");
  const oldScroll = $("editor")?.scrollTop || 0;
  const workspace = $("workspace");
  if (workspace.dataset.projectId !== p.id || !$("video")) {
    if (playerAudioContext) { void playerAudioContext.close?.(); playerAudioContext = null; }
    const tracks = p.audio_tracks || [];
    voiceWindow = null;
    voiceRequest++;
    workspace.innerHTML = `<div id="voice-map" class="voice-map" aria-label="Mapa de audio"><span class="voice-empty">El mapa de audio aparecerá al cargar el vídeo.</span></div><div id="global-editor-bar" class="global-editor-bar" aria-label="Edición del proyecto"></div><div class="workspace-split"><div class="workspace-left player-frame"><div class="video-center"><div id="video-frame"><video id="video" class="player" controls preload="metadata" src="/api/projects/${p.id}/media"></video><div id="video-subtitles" class="video-subtitles" hidden></div></div></div><div class="overlay-options"><span>Sobre el vídeo</span><div class="overlay-segmented"><button type="button" id="overlay-original" aria-pressed="true">Original</button><button type="button" id="overlay-translated" aria-pressed="false">Traducción</button></div><button id="open-workspace-preferences" type="button">⚙ Audio y modelos</button></div><div id="workspace-controls"></div><div id="cue-inspector"></div><dialog id="workspace-preferences" class="preferences-dialog" aria-labelledby="preferences-title"><div class="preferences-heading"><strong id="preferences-title">Audio y modelos</strong><button id="close-workspace-preferences" type="button" aria-label="Cerrar">✕</button></div>${tracks.length ? `<details id="audio-controls" class="audio-details"><summary>Pista de audio</summary><div class="audio-options"><label>Audio del vídeo <select id="audio-track">${tracks.map(t => `<option value="${t.index}" ${t.index === p.audio_index ? "selected" : ""}>${esc(t.label)}</option>`).join("")}</select></label> <label>Volumen <input id="audio-volume" type="range" min="0" max="1" step="0.05" value="1"></label><audio id="player-audio" hidden preload="none"></audio><div id="audio-status" class="tiny" role="status"></div></div></details>` : ""}${modelControlsMarkup()}</dialog><div id="media-error" class="notice error" hidden></div></div><div id="project-content"></div></div>`;
    workspace.dataset.projectId = p.id;
    for (const [id, track] of [['overlay-original','original'],['overlay-translated','translated']]) {
      $(id).onclick = () => {
        videoTextTrack = track;
        $('overlay-original').setAttribute('aria-pressed', String(track === 'original'));
        $('overlay-translated').setAttribute('aria-pressed', String(track === 'translated'));
        updateVideoSubtitles();
      };
    }
    if (tracks.length) configurePlayerAudio(p.id);
    bindModelControls(p.id);
    $('open-workspace-preferences').onclick = () => $('workspace-preferences').showModal();
    $('close-workspace-preferences').onclick = () => $('workspace-preferences').close();
    $("video").addEventListener("timeupdate", updateVideoSubtitles);
    $("video").addEventListener("timeupdate", updateCueTimeline);
    $("video").addEventListener("timeupdate", () => syncVoiceMap());
    $("video").addEventListener("loadedmetadata", () => syncVoiceMap(true));
    $("video").addEventListener("seeked", () => syncVoiceMap());
    if ($('audio-track')) $('audio-track').addEventListener('change', () => syncVoiceMap(true));
    $("video").addEventListener("seeked", updateVideoSubtitles);
    $("video").addEventListener("seeked", updateCueTimeline);
    $("video").addEventListener("loadedmetadata", renderTaskProgress);
    $("video").onerror = () => {
      const message = $("media-error");
      message.hidden = false;
      message.textContent =
        "No se puede reproducir el original. Comprueba que sigue en su ubicación y que el navegador admite su formato. Los subtítulos se pueden editar igualmente.";
    };
  }
  if ($("audio-controls")) {
    if (mode === "draft") $("audio-controls").setAttribute("open", "");
    else $("audio-controls").removeAttribute("open");
  }
  $("project-header").innerHTML = `<div class="project-top"><strong class="project-title" title="${esc(p.name)}">${esc(p.name)}</strong><span class="status ${esc(p.state)}">${esc(stateName(p))}</span>${stageNavigation(p, cues)}${finished ? `<div class="export-group"><button type="button" id="export-toggle" class="primary" aria-expanded="${exportOpen}">Exportar ▾</button><div id="export-menu" class="export-menu" ${exportOpen ? '' : 'hidden'}><strong>Antes de guardar</strong><div id="export-checks"></div><div class="export-selects"><label>Idioma <select id="language" aria-label="Idioma de exportación"><option value="${translationLanguage(p)[0]}">${translationLanguage(p)[1]}</option><option value="original">Original</option><option value="bilingual">Bilingüe</option></select></label><label>Formato <select id="format" aria-label="Formato"><option>srt</option><option>vtt</option></select></label></div><p class="tiny">${p.source_kind === 'reference' ? 'Destino: misma carpeta del vídeo' : 'Destino: descarga desde el navegador'}</p><button id="export" class="primary">Guardar junto al vídeo</button> <button id="download">Descargar</button></div></div>` : ''}</div>`;
  if (!canTranslateCue) {
    cueEditor = null;
    editorProject = null;
  }
  if (canTranslateCue && (!cueEditor || editorProject !== p.id)) {
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
  if (canTranslateCue && cueEditor && !dirty.size && !pendingEdits())
    cueEditor.reconcile(cues);
  $('global-editor-bar').innerHTML = canTranslateCue ? `<div class="history-actions" role="group" aria-label="Historial de edición"><button id="undo-edit" title="Deshacer (⌘Z / Ctrl+Z)">↶ Deshacer</button><button id="redo-edit" title="Rehacer (⌘⇧Z / Ctrl+Shift+Z)">↷ Rehacer</button><button id="retry-save" hidden>Reintentar guardado</button></div>${ready ? editorToolbar(cues, p) : ''}<span id="save-status" role="status" aria-live="polite"></span>` : '';
  $('global-editor-bar').hidden = !canTranslateCue;
  $("workspace-controls").innerHTML = `<div id="stage-panel">${stagePanel(p, cues)}</div><div id="task-progress"></div>${p.error ? `<div class="notice error">${esc(p.error)} ${p.state === "failed" && !viewingTrash && !p.error.startsWith('Mejora incompleta:') ? '<button id="retry">Reintentar pendientes</button>' : ""}</div>` : ""}${p.timing_warnings?.length ? `<div class="notice">Revisa el texto y los tiempos aproximados en ${p.timing_warnings.length} tramo(s): ${p.timing_warnings.slice(0, 6).map(t => time(t)).join(', ')}${p.timing_warnings.length > 6 ? '…' : ''}. El modelo no pudo alinearlos y podría haber interpretado sonidos como voz.</div>` : ''}${!ready && showReadOnly ? editorToolbar(cues, p, true) : ""}${ready ? globalSyncDialogMarkup() : ''}${p.batch?.status === 'review' && !viewingTrash ? '<button id="continue-batch" class="primary">Continuar lote</button>' : ''}${!ready && !viewingTrash && p.source_kind === "reference" && ["ready", "failed", "cancelled"].includes(p.state) && (p.state === "ready" || p.state === "cancelled" || cues.length) ? '<button id="retranscribe">Volver a transcribir</button>' : ''}`;
  if (!cues.length && !viewingTrash && typeof lastComparisonUndo !== 'undefined' && lastComparisonUndo?.pid === p.id) {
    $('workspace-controls').insertAdjacentHTML('beforeend', '<button id="undo-empty-delete" type="button">Deshacer última operación</button>');
    $('undo-empty-delete').onclick = () => undoLastComparison(p.id);
  }
  renderTaskProgress();
  if (voiceWindow?.amplitudes) paintVoiceMap();
  const filteredCues = cues.filter(c => cueFilter === "all" || cueFilter === "sus" && c.flag && !c.flag_resolved || cueFilter === "untr" && !(c.translated || "").trim() || cueFilter === "prop" && c.proposal);
  const filterBar = cues.length ? cueFilters(cues) + `<div class="cue-search"><label>Buscar <input id="cue-search" type="search" placeholder="Buscar en original o traducción" value="${esc(editorSearch)}"></label></div>` : "";
  $("project-content").innerHTML = `<div id="sync-panel" hidden></div><div id="workspace-subtitles">${ready ? filterBar + editorTable(filteredCues, p) : showReadOnly ? filterBar + editorTable(filteredCues, p, true) : p.state === "draft" ? (viewingTrash ? '<div class="notice">Restaura el proyecto para procesarlo.</div>' : sourceChoices(p)) : p.state === "failed" ? '<div class="notice">La transcripción se detuvo. Puedes reintentar desde el último tramo guardado.</div>' : ['paused','cancelled'].includes(p.state) ? '<div class="notice">Los tramos procesados se han conservado.</div>' : '<div class="notice">Los segmentos aparecerán a medida que avance la transcripción. La primera ejecución puede necesitar descargar modelos.</div>'}</div>`;
  if (ready && inspectorCue && cues.some(c => c.id === inspectorCue)) drawCueInspector();
  else if ($('cue-inspector')) $('cue-inspector').innerHTML = ready ? '<p class="inspector-hint">Selecciona una entrada para editarla junto al vídeo.</p>' : '';
  if ($('cue-search')) {
    $('cue-search').oninput = event => { editorSearch = event.target.value; filterEditorSearch(); };
    filterEditorSearch();
  }
  document.querySelectorAll('[data-stage]').forEach(button => button.onclick = async () => {
    if (!(await settleEdits())) return;
    const stage = button.dataset.stage;
    if (stage === 'export') { if ($('export-menu')) { exportOpen = true; $('export-menu').hidden = false; $('export-toggle').setAttribute('aria-expanded','true'); } return; }
    currentStage = stage;
    cueFilter = stage === 'review' ? 'sus' : 'all';
    renderWorkspace();
  });
  document.querySelectorAll('[data-cue-filter]').forEach(button => button.onclick = async () => { if (!(await settleEdits())) return; cueFilter = button.dataset.cueFilter; renderWorkspace(); });
  if ($('show-suspicious')) $('show-suspicious').onclick = async () => { if (!(await settleEdits())) return; cueFilter = 'sus'; renderWorkspace(); };
  if ($('start-focus-review')) $('start-focus-review').onclick = () => openFocusReview();
  if ($('stage-next-translate')) $('stage-next-translate').onclick = async () => { if (!(await settleEdits())) return; currentStage = 'translate'; cueFilter = 'all'; renderWorkspace(); };
  if ($('open-translation-dialog')) $('open-translation-dialog').onclick = () => $('translation-dialog').showModal();
  if ($('close-translation-dialog')) $('close-translation-dialog').onclick = () => $('translation-dialog').close();
  if ($('global-sync-open')) $('global-sync-open').onclick = async () => { if (!busy && await settleEdits()) { $('project-operations').open = false; $('global-sync-dialog').showModal(); } };
  if ($('global-sync-close')) $('global-sync-close').onclick = () => $('global-sync-dialog').close();
  if ($('global-sync-preview')) $('global-sync-preview').onclick = previewGlobalAlignment;
  if ($('translation-language')) {
    if (translationDraft?.pid !== p.id) translationDraft = {pid:p.id, language:p.translation_language_known ? p.target_language : '', model:p.translation_model || ''};
    $('translation-language').onchange = () => {
      translationDraft.language = $('translation-language').value;
      if ($('translation-language-label')) $('translation-language-label').textContent = translationLanguages.find(([value]) => value === translationDraft.language)?.[1] || 'sin seleccionar';
      document.querySelectorAll('.cue-language').forEach(select => { select.value = translationDraft.language; });
    };
    if ($('translation-model')) { $('translation-model').onchange = () => { translationDraft.model = $('translation-model').value; }; void loadTranslationModels(p.id); }
  }
  if ($('confirm-translation-language')) $('confirm-translation-language').onclick = async () => {
    if (busy || !(await settleEdits())) return;
    const language = $('translation-language')?.value;
    if (!language) { alert('Elige el idioma de las traducciones existentes.'); return; }
    busy = true;
    try {
      await api(`/api/projects/${p.id}/translation-language`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_language:language})});
      p.target_language = language;
      p.translation_language_known = true;
      translationDraft.language = language;
      renderWorkspace();
    } catch(error) { alert(error.message); }
    finally { busy = false; }
  };
  if ($('sync-start')) $('sync-start').onclick = () => proposeSync(p.id);
  if ($('sync-undo')) $('sync-undo').onclick = () => applySync(p.id, syncUndo.cues, true);
  renderSyncPanel(p.id);
  if (!viewingTrash && p.state !== "draft" && cues.length && !syncProposal) {
    viewedCues = cues;
    updateVideoSubtitles();
  }
  if ($("editor")) $("editor").scrollTop = oldScroll;
  if ($("start-project")) {
    $("start-project").onclick = () => startProject(p.id);
    $("subtitle-source").onchange = () => {
      updateDraftAction();
      return loadSubtitlePreview(p.id);
    };
    updateDraftAction();
    if (selectedSource() && selectedSource() !== "asr") loadSubtitlePreview(p.id);
  }
  if (cues.length) {
    document.querySelectorAll(".cue[data-cue]").forEach((row) => {
      row.onfocusin = () => {
        if (selectedCue !== row.dataset.cue) seekCue(row);
        if (ready) showCueInspector(row.dataset.cue);
      };
      row.onfocusout = (event) => {
        if (!event.relatedTarget || !row.contains(event.relatedTarget))
          selectedCue = null;
      };
      row.addEventListener("focusin", row.onfocusin);
      row.addEventListener("focusout", row.onfocusout);
      row.onclick = (event) => {
        if (!["TEXTAREA", "INPUT", "BUTTON"].includes(event.target.tagName) || selectedCue !== row.dataset.cue)
          seekCue(row);
        if (ready) showCueInspector(row.dataset.cue);
      };
    });
  }
  if ($("retry")) $("retry").onclick = () => p.batch?.status === 'failed' ? retryBatchItem(p.batch.id, p.batch.item_id) : retryProject(p.id);
  if ($('continue-batch')) $('continue-batch').onclick = () => continueBatchItem(p.batch.id, p.batch.item_id);
  if ($("retranscribe")) $("retranscribe").onclick = () => retranscribeProject(p.id);
  if (canTranslateCue) {
    document.querySelectorAll('.cue-translate').forEach(menu => {
      menu.addEventListener('toggle', () => {
        if (!menu.open) return;
        document.querySelectorAll('.cue-translate[open]').forEach(other => { if (other !== menu) other.open = false; });
        positionCueMenu(menu);
      });
    });
    $('editor')?.addEventListener('scroll', () => document.querySelectorAll('.cue-translate[open]').forEach(menu => { menu.open = false; }), {passive:true});
    document.querySelectorAll('.cue-translate-direct').forEach(button => {
      const row = button.closest('.cue');
      button.onclick = () => {
        const language = $('translation-language')?.value || (translationDraft?.pid === p.id && translationDraft.language) || (p.translation_language_known && p.target_language);
        if (!language) { alert('Elige primero el idioma en la columna de traducción.'); return; }
        return translateCue(p.id, row.dataset.cue, 'forward', language);
      };
      button.oncontextmenu = event => { event.preventDefault(); const menu = row.querySelector('.cue-translate'); menu.open = true; positionCueMenu(menu); };
    });
    document.querySelectorAll('.cue-translate [data-direction]').forEach(button => {
      button.onclick = () => {
        const row = button.closest('.cue');
        const language = row.querySelector('.cue-language').value;
        return translateCue(p.id, row.dataset.cue, button.dataset.direction, language);
      };
    });
    document.querySelectorAll('.compare-range-button').forEach(button => { button.onclick = () => openRangeComparison(p.id, button.closest('.cue').dataset.cue); });
    document.querySelectorAll('.cue-model-comparison').forEach(panel => {
      panel.addEventListener('toggle', () => { if (panel.open) void loadCueComparison(panel.closest('.cue').dataset.cue); positionCueMenu(panel.closest('.cue-translate')); });
      panel.querySelector('.compare-cue-button').onclick = () => compareCueTranslations(p.id, panel.closest('.cue').dataset.cue);
    });
    if (!ready) {
      $('undo-edit').onclick = () => historyEdit('undo');
      $('redo-edit').onclick = () => historyEdit('redo');
      $('retry-save').onclick = () => cueEditor.retry();
      updateSaveStatus();
    }
  }
  if (finished) {
    if (exportLanguage === null) exportLanguage = defaultExportLanguage(cues, p);
    $("language").value = exportLanguage;
    $("format").value = exportFormat;
    $('export-toggle').onclick = () => { exportOpen = !exportOpen; $('export-menu').hidden = !exportOpen; $('export-toggle').setAttribute('aria-expanded',String(exportOpen)); };
    $('language').onchange = () => { exportLanguage = $('language').value; renderExportChecks(cues); };
    $('format').onchange = () => { exportFormat = $('format').value; };
    renderExportChecks(cues);
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
        showExportToast(`Guardado junto al vídeo: ${saved.path.split("/").pop()}`);
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
  if (canTranslateCue) {
    document.querySelectorAll(".cue[data-cue]").forEach((row) => {
      row.querySelectorAll("input:not([readonly]),textarea:not([readonly])").forEach((el) => {
        el.oninput = () => { editRevision++; dirty.add(row.dataset.cue); updateSaveStatus(); };
        el.onblur = () => commitField(row, el);
      });
    });
  }
  if (ready) {
    if ($("translate-pending"))
      $("translate-pending").onclick = () => { if (currentStage !== 'translate') { currentStage='translate'; renderWorkspace(); $('translation-dialog')?.showModal(); } else return translatePending(p.id); };
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
    document.querySelectorAll('[data-resolve-flag]').forEach(button => {
      button.onclick = async () => {
        if (busy || !(await settleEdits())) return;
        const id = button.closest('.cue').dataset.cue, current = cueEditor.get(id);
        busy = true;
        try {
          const {start, end, original, translated} = current;
          await api(`/api/projects/${p.id}/cues/${id}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({start,end,original,translated,expected:{start,end,original,translated},flag_resolved:true})});
          busy = false;
          await refresh();
        } catch (error) { alert(error.message); } finally { busy = false; }
      };
    });
    document.querySelectorAll('[data-proposal]').forEach(button => {
      button.onclick = async () => {
        if (busy || !(await settleEdits())) return;
        busy = true;
        try {
          await api(`/api/projects/${p.id}/cues/${button.closest('.cue').dataset.cue}/proposal/${button.dataset.proposal}`, {method:'POST', headers:{'X-Studio-Local':'1'}});
          busy = false;
          await refresh();
        } catch (error) { alert(error.message); } finally { busy = false; }
      };
    });
    if ($('accept-proposals')) $('accept-proposals').onclick = async () => {
      if (busy || !(await settleEdits())) return;
      busy = true;
      try {
        await api(`/api/projects/${p.id}/proposals/accept-all`, {method:'POST', headers:{'X-Studio-Local':'1'}});
        busy = false;
        await refresh();
      } catch (error) { alert(error.message); } finally { busy = false; }
    };
    $("improve-text").onclick = () => improveText(p.id);
    $("improve-picker").addEventListener('toggle', () => { if ($("improve-picker")?.open) loadImprovementModels(p.id); });
    if ($("undo-improvement"))
      $("undo-improvement").onclick = () => undoImprovement(p.id);
    if ($('undo-comparison')) $('undo-comparison').onclick = () => undoLastComparison(p.id);
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

function inspectorRow(id = inspectorCue) {
  return [...document.querySelectorAll('#editor .cue[data-cue]')].find(row => row.dataset.cue === id);
}

function filterEditorSearch() {
  const query = editorSearch.trim().toLocaleLowerCase();
  document.querySelectorAll('#editor .cue[data-cue]').forEach(row => {
    const cue = cueEditor?.get(row.dataset.cue) || detail?.cues.find(item => item.id === row.dataset.cue);
    row.hidden = !!query && !`${cue?.original || ''}\n${cue?.translated || ''}`.toLocaleLowerCase().includes(query);
  });
}

function showCueInspector(id) {
  if (id === inspectorCue && $('cue-edit-original')) return;
  if (inspectorCue && dirty.has(inspectorCue)) return;
  inspectorCue = id;
  drawCueInspector();
}

function drawCueInspector() {
  const panel = $('cue-inspector'), row = inspectorRow(), cue = cueEditor?.get(inspectorCue);
  if (!panel || !row || !cue) return;
  document.querySelectorAll('#editor .cue[data-cue]').forEach(item => item.classList.toggle('selected', item.dataset.cue === inspectorCue));
  panel.innerHTML = `<section class="inspector"><div class="inspector-heading"><strong>Subtítulo ${esc(row.querySelector('.cue-number')?.textContent || '')}</strong><span></span><button id="cue-prev" type="button" aria-label="Entrada anterior">‹</button><button id="cue-next" type="button" aria-label="Entrada siguiente">›</button><button id="cue-insert" type="button">＋ Añadir</button><button id="cue-delete" type="button">− Eliminar</button></div><div class="cue-timeline-heading"><span>Tramo del subtítulo · pulsa para mover el vídeo</span><span id="cue-timeline-position"></span></div><button id="cue-timeline" type="button" class="cue-timeline" role="slider" aria-label="Posición del vídeo en torno al subtítulo" title="Pulsa para mover el vídeo; las marcas no cambian"><span class="cue-timeline-range"></span><span class="cue-timeline-playhead" hidden></span></button><div class="inspector-times"><label>Entrada <input id="cue-edit-start" data-field="start" value="${time(cue.start)}"></label><button id="cue-mark-in" type="button" aria-label="Fijar entrada en la posición del vídeo" title="Fijar entrada en la posición actual del vídeo">Fijar</button><span class="cue-duration" id="cue-duration"></span><label>Salida <input id="cue-edit-end" data-field="end" value="${time(cue.end)}"></label><button id="cue-mark-out" type="button" aria-label="Fijar salida en la posición del vídeo" title="Fijar salida en la posición actual del vídeo">Fijar</button></div><div class="inspector-transport" aria-label="Mover reproducción"><span>Vídeo</span><button type="button" data-seek="-1">−1 s</button><button type="button" data-seek="1">+1 s</button><details class="transport-more"><summary>Más saltos ▾</summary><div><button type="button" data-seek="-30">−30 s</button><button type="button" data-seek="-5">−5 s</button><button type="button" data-seek="5">+5 s</button><button type="button" data-seek="30">+30 s</button></div></details></div><div class="inspector-text"><label>Original o transcripción <textarea id="cue-edit-original" data-field="original" ${row.querySelector('.original') ? '' : 'disabled'}>${esc(cue.original)}</textarea></label><label>Traducción <textarea id="cue-edit-translated" data-field="translated">${esc(cue.translated)}</textarea></label></div><details class="anchor-controls"><summary>Sincronizar con puntos de referencia</summary><div class="anchor-popover"><p>Elige una entrada, busca en el vídeo dónde empieza y fija un punto. Repite con otra entrada alejada.</p><button id="anchor-a" type="button">Fijar punto A</button> <span>${manualAnchors.a ? time(manualAnchors.a.target) : 'Sin fijar'}</span> <button id="anchor-b" type="button">Fijar punto B</button> <span>${manualAnchors.b ? time(manualAnchors.b.target) : 'Sin fijar'}</span> <button id="anchor-shift" type="button">Previsualizar desplazamiento desde A</button> <button id="anchor-preview" type="button">Previsualizar ajuste global con A y B</button></div></details><p id="cue-edit-error" role="status"></p></section>`;
  updateCueTimeline();
  $('cue-timeline').onclick = event => {
    const track = $('cue-timeline'), rect = track.getBoundingClientRect();
    if (!rect.width) return;
    const start = Number(track.dataset.from), end = Number(track.dataset.to);
    $('video').currentTime = start + Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * (end - start);
    updateCueTimeline();
  };
  $('cue-timeline').onkeydown = event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    const video = $('video'), track = $('cue-timeline'), from = Number(track.dataset.from), to = Number(track.dataset.to);
    video.currentTime = event.key === 'Home' ? from : event.key === 'End' ? to : Math.max(from, Math.min(to, (video.currentTime || 0) + (event.key === 'ArrowLeft' ? -1 : 1)));
    updateCueTimeline();
  };
  panel.querySelectorAll('[data-field]').forEach(field => {
    field.oninput = () => {
      const target = inspectorRow()?.querySelector(`[data-field="${field.dataset.field}"]`);
      if (!target) return;
      target.value = field.value;
      editRevision++;
      dirty.add(inspectorCue);
      updateSaveStatus();
    };
    field.onblur = () => {
      const currentRow = inspectorRow(), target = currentRow?.querySelector(`[data-field="${field.dataset.field}"]`);
      if (!target) return;
      target.value = field.value;
      commitField(currentRow, target);
      if (target.hasAttribute('aria-invalid')) { field.setAttribute('aria-invalid','true'); $('cue-edit-error').textContent = target.getAttribute('title'); }
      else { field.removeAttribute('aria-invalid'); $('cue-edit-error').textContent = ''; }
    };
  });
  const move = direction => {
    commitActiveField();
    if (dirty.size) return;
    const rows = [...document.querySelectorAll('#editor .cue[data-cue]')].filter(item => !item.hidden), index = rows.findIndex(item => item.dataset.cue === inspectorCue);
    const target = rows[index + direction];
    if (target) { seekCue(target); showCueInspector(target.dataset.cue); target.scrollIntoView?.({block:'nearest'}); }
  };
  $('cue-prev').onclick = () => move(-1);
  $('cue-next').onclick = () => move(1);
  $('cue-insert').onclick = async () => {
    if (busy || !(await settleEdits())) return;
    const id = inspectorCue, pid = detail.project.id;
    busy = true;
    try {
      const result = await api(`/api/projects/${pid}/cues/${id}/insert-after`, {method:'POST',headers:{'X-Studio-Local':'1'}});
      lastComparisonUndo = {pid,id:result.undo_id};
      detail = await api(`/api/projects/${pid}`);
      cueEditor = null;
      inspectorCue = result.cue.id;
      renderWorkspace();
      const newRow = inspectorRow();
      if (newRow) { seekCue(newRow); newRow.scrollIntoView?.({block:'nearest'}); }
    } catch (error) { alert(error.message); }
    finally { busy = false; }
  };
  $('cue-delete').onclick = async () => {
    if (busy || !(await settleEdits()) || !confirm('¿Eliminar esta entrada de los subtítulos del proyecto? Podrás deshacerlo si no cambian las entradas afectadas.')) return;
    const id = inspectorCue, pid = detail.project.id, current = cueEditor.get(id);
    const rows = [...document.querySelectorAll('#editor .cue[data-cue]')].filter(item => !item.hidden);
    const at = rows.findIndex(item => item.dataset.cue === id), next = rows[at + 1]?.dataset.cue || rows[at - 1]?.dataset.cue || null;
    busy = true;
    try {
      const {start,end,original,translated} = current;
      const result = await api(`/api/projects/${pid}/cues/${id}`, {method:'DELETE',headers:{'X-Studio-Local':'1','Content-Type':'application/json'},body:JSON.stringify({expected:{start,end,original,translated}})});
      lastComparisonUndo = {pid,id:result.undo_id};
      detail = await api(`/api/projects/${pid}`);
      cueEditor = null;
      inspectorCue = next;
      renderWorkspace();
      if (inspectorRow()) seekCue(inspectorRow());
    } catch (error) { alert(error.message); }
    finally { busy = false; }
  };
  panel.querySelectorAll('[data-seek]').forEach(button => button.onclick = () => {
    const video = $('video'), duration = Number.isFinite(video.duration) ? video.duration : Infinity;
    video.currentTime = Math.max(0, Math.min(duration, (video.currentTime || 0) + Number(button.dataset.seek)));
    updateCueTimeline();
  });
  for (const [button, name] of [['cue-mark-in','start'], ['cue-mark-out','end']]) $(button).onclick = () => {
    const field = $(`cue-edit-${name}`);
    field.value = time($('video').currentTime);
    field.oninput(); field.onblur();
  };
  for (const [button, key] of [['anchor-a','a'],['anchor-b','b']]) $(button).onclick = async () => {
    const id = inspectorCue, target = $('video').currentTime;
    if (!(await settleEdits()) || !Number.isFinite(target)) return;
    const current = cueEditor.get(id);
    if (!current || inspectorCue !== id) return;
    manualAnchors[key] = {id, start:current.start, target};
    drawCueInspector();
    $('cue-inspector').querySelector('.anchor-controls').open = true;
  };
  $('anchor-shift').onclick = async () => {
    if (!(await settleEdits())) return;
    const a = manualAnchors.a;
    if (!a || cueEditor.get(a.id)?.start !== a.start) { $('cue-edit-error').textContent = 'Fija un punto A cuyo tiempo no haya cambiado.'; return; }
    previewManualAlignment(a, 1);
  };
  $('anchor-preview').onclick = async () => {
    if (!(await settleEdits())) return;
    const {a,b} = manualAnchors;
    if (!a || !b || a.id === b.id || cueEditor.get(a.id)?.start !== a.start || cueEditor.get(b.id)?.start !== b.start || a.start === b.start) {
      $('cue-edit-error').textContent = 'Fija dos entradas distintas cuyos tiempos no hayan cambiado.'; return;
    }
    const scale = (b.target - a.target) / (b.start - a.start);
    if (!Number.isFinite(scale) || scale <= 0) { $('cue-edit-error').textContent = 'Los puntos deben seguir el mismo orden en el vídeo y los subtítulos.'; return; }
    previewManualAlignment(a, scale);
  };
}

function previewManualAlignment(anchor, scale) {
  const cues = detail.cues.map(item => cueEditor.get(item.id));
  const proposal = cues.map(item => ({id:item.id,start:item.start,end:item.end,new_start:anchor.target + (item.start-anchor.start)*scale,new_end:anchor.target + (item.end-anchor.start)*scale}));
  if (proposal.some(item => !Number.isFinite(item.new_start) || !Number.isFinite(item.new_end) || item.new_start < 0 || item.new_end <= item.new_start)) {
    $('cue-edit-error').textContent = 'El ajuste produciría tiempos negativos o inválidos. Revisa los puntos.'; return;
  }
  syncProposal = {pid:detail.project.id,cues:proposal,useNew:false,trackLabel:scale === 1 ? 'Desplazamiento manual' : 'Dos puntos manuales'};
  renderSyncPanel(detail.project.id);
}

function updateCueTimeline() {
  const track = $('cue-timeline'), video = $('video'), cue = cueEditor?.get(inspectorCue);
  if (!track || !video || !cue) return;
  const from = Math.max(0, cue.start - 3), to = Math.max(from + 1, cue.end + 3), span = to - from;
  track.dataset.from = from; track.dataset.to = to;
  track.setAttribute('aria-valuemin', String(from)); track.setAttribute('aria-valuemax', String(to));
  const range = track.querySelector('.cue-timeline-range'), head = track.querySelector('.cue-timeline-playhead');
  range.style.left = `${100 * (cue.start - from) / span}%`;
  range.style.width = `${100 * Math.max(0, cue.end - cue.start) / span}%`;
  const now = Number(video.currentTime);
  track.setAttribute('aria-valuenow', String(Number.isFinite(now) ? Math.max(from, Math.min(to, now)) : from));
  track.setAttribute('aria-valuetext', Number.isFinite(now) ? `Vídeo ${time(now)}` : 'Posición desconocida');
  head.hidden = !Number.isFinite(now) || now < from || now > to;
  if (!head.hidden) head.style.left = `${100 * (now - from) / span}%`;
  $('cue-duration').textContent = `${Math.max(0, cue.end - cue.start).toFixed(1)} s`;
  $('cue-timeline-position').textContent = Number.isFinite(now) ? `Vídeo ${time(now)}` : '';
}
function refreshInspectorValues() {
  const cue = cueEditor?.get(inspectorCue);
  if (!cue) return;
  for (const name of ['start','end','original','translated']) {
    const field = $(`cue-edit-${name}`);
    if (field && document.activeElement !== field) field.value = ['start','end'].includes(name) ? time(cue[name]) : cue[name] || '';
  }
  updateCueTimeline();
}

function updateVideoSubtitles() {
  const video = $("video"),
    display = $("video-subtitles");
  if (!video || !display) return;
  const now = video.currentTime;
  const lines = viewedCues
    .filter((cue) => cue.start <= now && now < cue.end)
    .map((cue) => cue[videoTextTrack] || "").filter(Boolean);
  display.textContent = lines.join("\n");
  display.hidden = lines.length === 0;
}


function voiceMapMarkup(values, start, end, cues, current, processedUntil) {
  const length = end - start;
  if (!(length > 0) || !values.length) return '';
  const bars = values.map((value, i) => {
    const moment = start + (i + .5) * length / values.length;
    const cue = cues.find(item => item.start <= moment && moment < item.end);
    const kind = processedUntil != null && moment >= processedUntil ? 'pending' : cue?.flag && !cue.flag_resolved ? 'suspect' : cue ? 'spoken' : 'silent';
    const amplitude = Math.max(0, Math.min(1, Number(value) || 0));
    return `<i class="voice-bar ${kind}" style="height:${Math.max(2, Math.round(Math.sqrt(amplitude) * 46))}px"></i>`;
  }).join('');
  const segments = cues.filter(c => c.end > start && c.start < end).map(c => {
    const left = Math.max(0, (c.start-start)/length*100), right = Math.min(100, (c.end-start)/length*100);
    return `<button type="button" class="voice-segment ${c.flag && !c.flag_resolved ? 'suspect' : ''}" data-voice-cue="${esc(c.id)}" style="left:${left}%;width:${Math.max(.2,right-left)}%" aria-label="Ir al segmento ${esc(c.position == null ? '' : c.position + 1)}"></button>`;
  }).join('');
  return `<div class="voice-bars" role="slider" tabindex="0" aria-label="Posición del audio" aria-valuemin="${start}" aria-valuemax="${end}" aria-valuenow="${current}">${bars}<span class="voice-playhead" style="left:${Math.max(0,Math.min(100,(current-start)/length*100))}%"></span></div><div class="voice-segments">${segments}</div><div class="voice-scale"><span>${time(start).slice(0,8)}</span><span>Mapa de audio · pulsa para ir a un momento</span><span>${time(end).slice(0,8)}</span></div>`;
}
function paintVoiceMap() {
  const container = $('voice-map'), video = $('video'), state = voiceWindow;
  if (!container || !video || !state?.amplitudes || !detail) return;
  const processed = detail.project.state === 'transcribing' ? detail.project.task_progress?.processed_until : null;
  container.innerHTML = voiceMapMarkup(state.amplitudes, state.start, state.end, detail.cues || [], video.currentTime || 0, processed);
  const bars = container.querySelector('.voice-bars');
  if (bars) bars.onclick = event => {
    const rect = bars.getBoundingClientRect();
    if (rect.width) video.currentTime = state.start + Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)) * (state.end-state.start);
  };
  if (bars) bars.onkeydown = event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    video.currentTime = event.key === 'Home' ? state.start : event.key === 'End' ? state.end : Math.max(state.start, Math.min(state.end, video.currentTime + (event.key === 'ArrowLeft' ? -5 : 5)));
  };
  container.querySelectorAll('[data-voice-cue]').forEach(button => button.onclick = () => {
    const cue = detail.cues.find(item => item.id === button.dataset.voiceCue);
    if (cue) video.currentTime = cue.start;
  });
}
async function syncVoiceMap(force = false) {
  const video = $('video'), container = $('voice-map'), project = detail?.project;
  if (!video || !container || !project || project.source_kind !== 'reference' || !(project.audio_tracks || []).length || !Number.isFinite(video.duration) || video.duration <= 0) return;
  const now = Math.max(0,video.currentTime || 0), index = Number($('audio-track')?.value ?? project.audio_tracks[0].index);
  if (!force && voiceWindow?.index === index && voiceWindow.failedUntil > Date.now()) return;
  if (!force && voiceWindow && voiceWindow.index === index && now >= voiceWindow.start && now < voiceWindow.end && (voiceWindow.end === video.duration || now < voiceWindow.end - 8)) {
    const marker = container.querySelector('.voice-playhead');
    if (marker) marker.style.left = `${Math.max(0,Math.min(100,(now-voiceWindow.start)/(voiceWindow.end-voiceWindow.start)*100))}%`;
    container.querySelector('.voice-bars')?.setAttribute('aria-valuenow', String(now));
    return;
  }
  const start = Math.max(0,Math.floor((now - 10) / 30) * 30), end = Math.min(video.duration, start + 70), key = `${index}:${start}:${end}`;
  if (!force && voiceWindow?.pending === key) return;
  const sequence = ++voiceRequest, pid = project.id;
  voiceWindow = {index,start,end,pending:key};
  container.innerHTML = '<span class="voice-empty">Analizando el audio…</span>';
  try {
    const result = await api(`/api/projects/${pid}/envelope?start=${start}&end=${end}&buckets=220&index=${index}`);
    if (sequence !== voiceRequest || detail?.project.id !== pid) return;
    if (!Array.isArray(result.amplitudes) || !result.amplitudes.length) throw Error('No hay datos de audio');
    voiceWindow = {index,start,end,amplitudes:result.amplitudes};
    paintVoiceMap();
  } catch (error) {
    if (sequence === voiceRequest && $('voice-map') === container) { voiceWindow = {index, failedUntil:Date.now() + 10000}; container.textContent = `Mapa de audio no disponible: ${error.message}`; }
  }
}

async function loadSubtitlePreview(pid) {
  const select = $("subtitle-source"),
    target = $("subtitle-preview");
  if (!select || !target) return;
  const source = selectedSource(),
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
      selectedSource() !== source
    )
      return;
    viewedCues = data.cues;
    const video = $("video");
    const first = data.cues.find(cue => Number.isFinite(cue.start) && Number.isFinite(cue.end) && cue.start >= 0 && cue.end > cue.start);
    const atBeginning = video && (!Number.isFinite(video.currentTime) || video.currentTime < 0.25);
    const visibleNow = video && data.cues.some(cue => cue.start <= video.currentTime && video.currentTime < cue.end);
    if (first && atBeginning && video.paused !== false && !visibleNow) {
      try { video.currentTime = first.start; }
      catch {
        video.addEventListener('loadedmetadata', () => {
          if (revision === subtitlePreviewRevision && selected === pid && selectedSource() === source && video.paused && video.currentTime < 0.25) video.currentTime = first.start;
        }, {once:true});
      }
    }
    updateVideoSubtitles();
    target.dataset.loadedSource = source;
    const previewCues = data.cues.map((c, i) => ({...c, id:`preview-${i}`, translated:""}));
    target.innerHTML = `<strong>Vista previa · ${data.cues.length} segmentos</strong><p class="tiny">Selecciona una línea para verla sobre el vídeo. Solo lectura hasta usar esta fuente.</p>${data.cues.length ? editorTable(previewCues, {action:"view",state:"ready"}, true).replace('id="editor"', 'id="preview-editor"') : "<p>No se encontraron líneas con tiempos válidos.</p>"}`;
    const seekPreview = (event) => {
      const row = event.target.closest?.(".cue");
      if (row && target.contains(row)) seekCue(row);
    };
    target.onfocusin = seekPreview;
    target.onclick = seekPreview;
  } catch (error) {
    if (revision === subtitlePreviewRevision && $("subtitle-source") === select)
      target.textContent = `No se pudo mostrar la pista: ${error.message}`;
  }
}
let playerAudioContext = null;
function cleanupAudioPreview() {
  const playerAudio = $("player-audio");
  if (playerAudio?.pause) {
    playerAudio.pause();
    playerAudio.removeAttribute("src");
    playerAudio.load?.();
  }
}

function configurePlayerAudio(pid) {
  const video = $("video"), audio = $("player-audio"), select = $("audio-track"), status = $("audio-status");
  let base = 0, correcting = false;
  let separateAudioControls = false;
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (AudioContext) {
      playerAudioContext = new AudioContext();
      const source = playerAudioContext.createMediaElementSource(video);
      const silence = playerAudioContext.createGain();
      silence.gain.value = 0;
      source.connect(silence); silence.connect(playerAudioContext.destination);
      separateAudioControls = true;
    }
  } catch (error) {
    if (playerAudioContext) void playerAudioContext.close?.();
    playerAudioContext = null;
  }
  if (!separateAudioControls) { video.muted = true; status.textContent = 'Usa el volumen de Audio y modelos para la pista seleccionada.'; }
  const volume = $("audio-volume");
  volume.oninput = () => {
    if (separateAudioControls) { video.volume = Number(volume.value); video.muted = false; }
    else audio.volume = Number(volume.value);
  };
  video.onvolumechange = () => {
    if (!separateAudioControls) { if (!video.muted) video.muted = true; return; }
    audio.volume = video.volume; audio.muted = video.muted; volume.value = video.volume;
  };
  if (separateAudioControls) video.onvolumechange();
  function stop() {
    audio.pause();
    audio.removeAttribute("src");
    audio.load?.();
  }
  function start() {
    stop();
    const index = Number(select.value);
    if (!Number.isInteger(index) || index < 0) return;
    base = Number.isFinite(video.currentTime) ? Math.max(0, video.currentTime) : 0;
    audio.src = `/api/projects/${pid}/audio-stream?index=${index}&start=${base.toFixed(3)}`;
    const playing = audio.play();
    if (playing?.catch) playing.catch(() => { status.textContent = "No se pudo reproducir el audio seleccionado."; });
  }
  video.onplay = () => { if (separateAudioControls) void playerAudioContext?.resume?.(); else video.muted = true; start(); };
  video.onpause = stop;
  video.onseeking = () => { if (!correcting) stop(); };
  video.onseeked = () => { if (correcting) { correcting = false; return; } if (!video.paused) start(); };
  select.onchange = () => { if (!video.paused) start(); };
  audio.onplaying = () => {
    if (separateAudioControls) status.textContent = "";
    if (!video.paused && Math.abs(video.currentTime - (base + audio.currentTime)) > 0.4) {
      correcting = true;
      video.currentTime = base + audio.currentTime;
    }
  };
  audio.onerror = () => { status.textContent = "No se pudo reproducir la pista de audio seleccionada."; };
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
function globalSyncDialogMarkup() {
  return `<dialog id="global-sync-dialog" class="preferences-dialog global-sync-dialog" aria-labelledby="global-sync-title"><div class="preferences-heading"><strong id="global-sync-title">Ajustar tiempos globalmente</strong><button id="global-sync-close" type="button" aria-label="Cerrar">✕</button></div><p>Usa un desplazamiento si todos los subtítulos llegan igual de pronto o tarde. Si fueron preparados para otra velocidad, indica ambas tasas.</p><div class="global-sync-fields"><label>FPS de los subtítulos <input id="sync-source-fps" type="number" min="1" max="240" step="any" list="sync-fps-presets" placeholder="Sin cambio"></label><label>FPS del vídeo <input id="sync-target-fps" type="number" min="1" max="240" step="any" list="sync-fps-presets" placeholder="Sin cambio"></label><datalist id="sync-fps-presets"><option value="23.976"><option value="24"><option value="25"><option value="29.97"><option value="30"><option value="50"><option value="59.94"><option value="60"></datalist><label>Desplazamiento en segundos <input id="sync-offset" type="number" step="any" value="0"></label></div><p class="tiny">Positivo: más tarde. Negativo: antes. El desplazamiento se aplica después de la conversión. El cambio de FPS solo es apropiado si la duración de las versiones realmente difiere.</p><p id="global-sync-error" role="alert"></p><button id="global-sync-preview" class="primary" type="button">Previsualizar ajuste</button></dialog>`;
}
function exactFrameRate(value) {
  const rate = Number(value);
  if (rate === 23.976) return 24000 / 1001;
  if (rate === 29.97) return 30000 / 1001;
  if (rate === 59.94) return 60000 / 1001;
  return rate;
}
async function previewGlobalAlignment() {
  if (busy || !(await settleEdits())) return;
  const source = $('sync-source-fps').value.trim(), target = $('sync-target-fps').value.trim();
  const offsetInput = $('sync-offset').value.trim(), offset = Number(offsetInput);
  const error = $('global-sync-error');
  if (!!source !== !!target) { error.textContent = 'Indica ambas tasas de FPS o deja las dos vacías.'; return; }
  const sourceFps = source ? exactFrameRate(source) : 1, targetFps = target ? exactFrameRate(target) : 1;
  if (!Number.isFinite(sourceFps) || !Number.isFinite(targetFps) || sourceFps < 1 || targetFps < 1 || sourceFps > 240 || targetFps > 240 || !offsetInput || !Number.isFinite(offset)) { error.textContent = 'Introduce FPS válidos y un desplazamiento numérico.'; return; }
  const scale = sourceFps / targetFps;
  const proposal = detail.cues.map(item => cueEditor.get(item.id)).map(item => ({id:item.id,start:item.start,end:item.end,new_start:item.start * scale + offset,new_end:item.end * scale + offset}));
  if (proposal.some(item => !Number.isFinite(item.new_start) || !Number.isFinite(item.new_end) || item.new_start < 0 || item.new_end <= item.new_start)) { error.textContent = 'El ajuste produciría tiempos negativos o inválidos. Cambia los valores antes de continuar.'; return; }
  const rateLabel = source ? `${source} → ${target} FPS` : 'sin cambio de FPS';
  syncProposal = {pid:detail.project.id, cues:proposal, useNew:true, trackLabel:`${rateLabel}; desplazamiento ${offset > 0 ? '+' : ''}${offset} s`};
  $('global-sync-dialog').close();
  renderSyncPanel(detail.project.id);
}
function renderSyncPanel(pid) {
  const panel = $('sync-panel');
  if (!panel || !syncProposal || syncProposal.pid !== pid) return;
  const entries = syncProposal.cues;
  panel.hidden = false;
  if ($('workspace-subtitles')) $('workspace-subtitles').hidden = true;
  panel.innerHTML = `<div class="sync-proposal"><strong>Propuesta de sincronización · ${entries.length} segmentos</strong><p>Referencia: ${esc(syncProposal.trackLabel)}. Comprueba varios momentos en el vídeo. El archivo original no se modifica.</p><div class="group"><button id="sync-preview-old">Ver tiempos actuales</button> <button id="sync-preview-new">Ver propuesta</button> <button id="sync-apply" class="primary">Aplicar propuesta</button> <button id="sync-discard">Descartar</button></div><p class="tiny">Elige una entrada para ir a su tiempo seleccionado en el vídeo.</p><div class="sync-list">${entries.map((c, i) => `<button type="button" data-sync-index="${i}">${i + 1} · ${time(c.start)}–${time(c.end)} → ${time(c.new_start)}–${time(c.new_end)} · ${esc(detail.cues[i]?.original || '')}</button>`).join('')}</div></div>`;
  const preview = useNew => {
    syncProposal.useNew = useNew;
    $('sync-preview-old').setAttribute('aria-pressed', String(!useNew));
    $('sync-preview-new').setAttribute('aria-pressed', String(useNew));
    viewedCues = detail.cues.map((c, i) => ({...c, start: useNew ? entries[i].new_start : entries[i].start, end: useNew ? entries[i].new_end : entries[i].end}));
    updateVideoSubtitles();
  };
  $('sync-preview-old').onclick = () => preview(false);
  $('sync-preview-new').onclick = () => preview(true);
  $('sync-apply').onclick = () => applySync(pid, entries, false);
  $('sync-discard').onclick = () => { syncProposal = null; viewedCues = detail.cues; updateVideoSubtitles(); panel.innerHTML = ''; panel.hidden = true; if ($('workspace-subtitles')) $('workspace-subtitles').hidden = false; };
  panel.querySelectorAll('[data-sync-index]').forEach(button => button.onclick = () => { const c = entries[Number(button.dataset.syncIndex)]; $('video').currentTime = syncProposal.useNew ? c.new_start : c.start; });
  preview(syncProposal.useNew);
}

async function proposeSync(pid) {
  if (busy || syncRunning || !(await settleEdits())) return;
  const track = $('audio-track');
  if (!track) return;
  busy = syncRunning = true;
  const panel = $('sync-panel');
  panel.hidden = false;
  if ($('workspace-subtitles')) $('workspace-subtitles').hidden = true;
  panel.innerHTML = '<div class="notice" role="status">Analizando la pista de audio y los subtítulos… Puede tardar varios minutos.</div>';
  try {
    const result = await api(`/api/projects/${pid}/sync-preview`, {method:'POST', headers:{'Content-Type':'application/json','X-Studio-Local':'1'}, body:JSON.stringify({audio_index:Number(track.value)})});
    syncProposal = {pid, cues:result.cues, useNew:false, trackLabel:track.selectedOptions?.[0]?.textContent || `Pista ${track.value}`};
    renderSyncPanel(pid);
  } catch (error) { panel.hidden = true; if ($('workspace-subtitles')) $('workspace-subtitles').hidden = false; alert(`No se pudo sincronizar: ${error.message}`); }
  finally { busy = syncRunning = false; }
}

async function applySync(pid, cues, undo) {
  if (busy || !(await settleEdits())) return;
  busy = true;
  try {
    await api(`/api/projects/${pid}/sync-apply`, {method:'POST', headers:{'Content-Type':'application/json','X-Studio-Local':'1'}, body:JSON.stringify({cues})});
    syncUndo = undo ? null : {pid, cues:cues.map(c => ({id:c.id, start:c.new_start, end:c.new_end, new_start:c.start, new_end:c.end}))};
    syncProposal = null;
    cueEditor = null;
    detail = await api(`/api/projects/${pid}`);
    renderWorkspace();
  } catch (error) { alert(error.message); }
  finally { busy = false; }
}

function editorToolbar(cues, project, readOnly = false) {
  const toolbar = readOnly
    ? project.state === 'transcribing' && !viewingTrash ? `<div class="editor-toolbar"><span class="tiny">Puedes traducir cada segmento mientras continúa la transcripción.</span></div>` : `<div class="notice">${viewingTrash ? "Restaura el proyecto para editarlo." : project.state === 'paused' ? "La tarea está pausada; puedes reanudarla o cancelarla." : "Segmentos visibles en modo lectura mientras se procesa; la edición se reactivará al terminar."}</div>`
    : `<div class="editor-toolbar"><details id="project-operations" class="project-operations"><summary>⋯ Herramientas de subtítulos <span aria-hidden="true">▾</span></summary><div class="operations-menu"><button id="global-sync-open" type="button">Ajustar tiempos globalmente</button>${project.source_kind === 'reference' && project.audio_tracks?.length ? '<button id="sync-start">Sincronizar con audio</button>' : ''}${syncUndo?.pid === project.id ? '<button id="sync-undo">Deshacer sincronización</button>' : ''}<details id="improve-picker" class="improve-picker"><summary>Mejorar transcripción</summary><div class="improve-options"><label>Modelo de Ollama <select id="improve-model"><option value="">Elige un modelo</option></select></label><span id="improve-model-status" class="tiny" role="status"></span><button id="improve-text" type="button">Iniciar mejora</button></div></details>${cues.some((c) => c.proposal) ? `<button id="accept-proposals">Aceptar ${cues.filter(c => c.proposal).length} propuestas</button>` : ""}${currentStage !== 'translate' && cues.some((c) => (c.original || "").trim() && !(c.translated || "").trim()) ? '<button id="translate-pending">Configurar traducción</button>' : ""}${project.can_undo_improvement ? '<button id="undo-improvement">Revertir última mejora</button>' : ""}${typeof lastComparisonUndo !== 'undefined' && lastComparisonUndo?.pid === project.id ? '<button id="undo-comparison">Deshacer última operación</button>' : ''}${project.source_kind === "reference" ? '<button id="retranscribe">Volver a transcribir</button>' : ''}</div></details></div>`;
  return toolbar;
}
function editorTable(cues, project, readOnly = false) {
  return `<div class="editor" id="editor"><table class="subtitle-table"><colgroup><col class="number-col"><col class="time-col"><col class="time-col"><col><col></colgroup><thead><tr><th scope="col">#</th><th scope="col">mark-in</th><th scope="col">mark-out</th><th scope="col">sub original (o transcripción)</th><th scope="col">${translationHeader(project, readOnly)}</th></tr></thead><tbody>${cues
    .map((item, index) => {
      const i = item.position ?? index;
      const c = cueEditor?.get(item.id) || item;
      const canTranslate = !viewingTrash && (!readOnly || project.state === 'transcribing');
      const textReadOnly = readOnly && !(project.state === "transcribing" && !viewingTrash);
      const menu = canTranslate ? `<button type="button" class="cue-translate-direct" title="Traducir al idioma de la columna; botón derecho para más opciones" aria-label="Traducir segmento ${i + 1}">→</button><details class="cue-translate"><summary title="Más opciones de traducción" aria-label="Más opciones del segmento ${i + 1}">⋮</summary><div class="cue-translate-menu"><label>Idioma de destino <select class="cue-language">${[["Spanish","Español"],["Romanian","Rumano"],["English","Inglés"],["Portuguese","Portugués"],["French","Francés"],["Italian","Italiano"],["German","Alemán"],["Dutch","Neerlandés"],["Japanese","Japonés"],["Chinese","Chino"]].map(([value,label])=>`<option value="${value}" ${value === (translationDraft?.pid === project.id && translationDraft.language || project.target_language || "Spanish") ? "selected" : ""}>${label}</option>`).join("")}</select></label><button type="button" data-direction="forward">Original → Traducción</button><button type="button" data-direction="backward">Original ← Traducción</button>${project.state === 'ready' ? '<button type="button" class="compare-range-button">Comparar traducción en este rango</button>' : ''}<details class="cue-model-comparison"><summary>Comparar modelos de Ollama</summary><div class="cue-comparison-body"><label>Dirección <select class="compare-direction"><option value="forward">Original → Traducción</option><option value="backward">Original ← Traducción</option></select></label><label>Modelo 1 <select class="compare-model"></select></label><label>Modelo 2 <select class="compare-model"></select></label><button type="button" class="compare-cue-button">Comparar</button><div class="cue-compare-results" role="status"></div></div></details></div></details>` : '';
      const flagLabels = {repeat:'repetición · Repite el segmento anterior o una frase', silence:'audio de baja energía · Comprueba si hay voz', low_confidence:'baja confianza · Revisa estas palabras', out_of_chunk:'fuera de tramo · Revisa los tiempos'};
      const warning = item.flag && !item.flag_resolved ? `<div class="cue-warning">⚠ ${esc(flagLabels[item.flag] || item.flag)} ${!readOnly ? '<button type="button" data-resolve-flag>Es correcto</button>' : ''}</div>` : '';
      const original = item.proposal && !readOnly ? `<div class="cue-proposal"><del>${esc(c.original)}</del><div>${esc(item.proposal)}</div><button type="button" data-proposal="accept">✓ Aceptar</button> <button type="button" data-proposal="reject">✕ Descartar</button></div>` : `<textarea class="original" data-field="original" ${textReadOnly ? "readonly" : ""} aria-label="Original ${i + 1}">${esc(c.original)}</textarea>`;
      return `<tr class="cue" tabindex="0" data-cue="${c.id}" data-start="${c.start}" data-end="${c.end}"><td class="cue-number">${i + 1}</td><td><input aria-label="Mark-in ${i + 1}" class="start" data-field="start" ${readOnly ? "readonly" : ""} value="${time(c.start)}"></td><td><input aria-label="Mark-out ${i + 1}" class="end" data-field="end" ${readOnly ? "readonly" : ""} value="${time(c.end)}"></td><td><div class="cue-source">${original}${menu}</div><div class="cue-operation-status tiny" role="status"></div>${warning}</td><td><textarea class="translated" data-field="translated" ${textReadOnly ? "readonly" : ""} aria-label="Traducción ${i + 1}">${esc(c.translated)}</textarea></td></tr>`;
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
    if (row.dataset.cue === inspectorCue) refreshInspectorValues();
  } catch (error) {
    field.setAttribute("aria-invalid", "true");
    field.setAttribute("title", error.message);
    dirty.add(row.dataset.cue);
  }
  updateSaveStatus();
}
function commitActiveField() {
  const field = document.activeElement;
  if (field?.closest?.('#cue-inspector') && field.dataset.field) { field.onblur?.(); return; }
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
  if (inspectorCue === action.id) refreshInspectorValues();
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
async function loadImprovementModels(pid) {
  const picker = $("improve-picker"), select = $("improve-model"), status = $("improve-model-status");
  if (!picker || !select || picker.dataset.loaded === '1') return;
  status.textContent = 'Consultando modelos…';
  try {
    const models = await api('/api/ollama/models');
    if ($('improve-picker') !== picker || detail?.project.id !== pid) return;
    select.innerHTML = '<option value="">Elige un modelo</option>' + models.map(model => `<option value="${esc(model.name)}">${esc(model.name)}</option>`).join('');
    status.textContent = models.length ? '' : 'No hay modelos instalados en Ollama.';
    picker.dataset.loaded = '1';
  } catch (error) { if ($('improve-picker') === picker) status.textContent = error.message; }
}
async function improveText(pid) {
  if (busy || !(await settleEdits())) return;
  const model = $("improve-model")?.value;
  if (!model) { alert('Elige un modelo de Ollama para la mejora.'); return; }
  if (
    !confirm(
      `Ollama usará ${model} para revisar puntuación y mayúsculas del texto original. Se conservará una copia para revertir la mejora; las traducciones existentes no se modificarán. ¿Continuar?`,
    )
  )
    return;
  busy = true;
  try {
    await api(`/api/projects/${pid}/improve`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({model}) });
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
async function startProject(pid) {
  if (busy) return;
  const source = selectedSource();
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
      body: JSON.stringify({
        source,
        action: "edit",
        asr_language: source === "asr" ? ($("asr-language")?.value || null) : null,
        asr_model: source === "asr" ? ($("asr-model")?.value || "qwen") : "qwen",
        audio_index:
          source === "asr" && $("audio-track")
            ? Number($("audio-track").value)
            : null,
      }),
    });
    // Refresh the existing project without replacing its video element.
    detail = await api(`/api/projects/${pid}`);
    currentStage = source === 'asr' ? 'process' : 'translate';
    renderWorkspace();
  } catch (e) {
    alert(e.message);
    if ($("start-project")) $("start-project").disabled = false;
  } finally {
    busy = false;
  }
}
async function retranscribeProject(pid) {
  if (busy || !(await settleEdits())) return;
  busy = true;
  try {
    const result = await api(`/api/projects/${pid}/retranscribe`, { method: "POST", headers: { "X-Studio-Local": "1" } });
    busy = false;
    await select(result.id);
    await refresh();
  } catch (error) { alert(error.message); }
  finally { busy = false; }
}
async function loadTranslationModels(pid) {
  const select = $('translation-model'), status = $('translation-model-status');
  if (!select || !status) return;
  try {
    const models = await api('/api/ollama/models');
    if ($('translation-model') !== select || detail?.project.id !== pid) return;
    select.innerHTML = '<option value="">Elige un modelo</option>' + models.map(model=>`<option value="${esc(model.name)}">${esc(model.name)}</option>`).join('');
    if (translationDraft?.pid === pid && models.some(model=>model.name === translationDraft.model)) select.value = translationDraft.model;
    status.textContent = models.length ? 'Se usará el modelo seleccionado en tu Mac.' : 'No hay modelos de Ollama disponibles. Descarga uno antes de traducir.';
  } catch (error) { if ($('translation-model') === select) status.textContent = `No se pudieron consultar los modelos: ${error.message}`; }
}
async function translatePending(pid) {
  if (busy || !(await settleEdits())) return;
  const language = $('translation-language')?.value, model = $('translation-model')?.value;
  if (!language || !model) { alert('Elige el idioma de destino y un modelo de Ollama.'); return; }
  busy = true;
  try {
    await api(`/api/projects/${pid}/translate`, { method: "POST", headers:{'Content-Type':'application/json'}, body:JSON.stringify({target_language:language,model}) });
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
function positionCueMenu(menu) {
  const content = menu.querySelector('.cue-translate-menu'), anchor = menu.getBoundingClientRect();
  if (!content || !anchor.width) return;
  const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
  const width = Math.min(320, viewportWidth - 16);
  const maxHeight = Math.max(100, viewportHeight - 16);
  content.style.width = `${width}px`;
  content.style.maxHeight = `${maxHeight}px`;
  content.style.left = `${Math.max(8, Math.min(viewportWidth - width - 8, anchor.right - width))}px`;
  content.style.top = `${Math.max(8, Math.min(anchor.bottom + 4, viewportHeight - Math.min(content.scrollHeight, maxHeight) - 8))}px`;
}
function showElapsedStatus(element, message) {
  if (!element) return () => {};
  const started = Date.now();
  const update = () => { element.innerHTML = `<span class="spinner" aria-hidden="true"></span> ${esc(message)} · ${Math.floor((Date.now() - started) / 1000)} s`; };
  update();
  const timer = setInterval(update, 1000);
  return () => { clearInterval(timer); };
}
async function translateCue(pid, cid, direction, language) {
  if (busy || !(await settleEdits()) || !cueEditor) return;
  const editor = cueEditor, current = editor.get(cid);
  if (!current) return;
  const from = direction === 'forward' ? 'original' : 'translated';
  const to = direction === 'forward' ? 'translated' : 'original';
  if (!current[from].trim()) { alert('El texto de origen está vacío.'); return; }
  if (current[to].trim() && !confirm('El texto de destino será reemplazado. Podrás deshacer el cambio. ¿Continuar?')) return;
  busy = true;
  const operationStatus = document.querySelector(`.cue[data-cue="${cid}"] .cue-operation-status`);
  const stopElapsed = showElapsedStatus(operationStatus, 'Traduciendo');
  try {
    const model = $('translation-model')?.value || (translationDraft?.pid === pid && translationDraft.model) || null;
    const result = await api(`/api/projects/${pid}/cues/${cid}/translate`, {method:'POST', headers:{'Content-Type':'application/json','X-Studio-Local':'1'}, body:JSON.stringify({direction, target_language:language, ...(model ? {model} : {})})});
    if (selected !== pid || cueEditor !== editor || dirty.size || editor.get(cid)?.[from] !== current[from] || editor.get(cid)?.[to] !== current[to] || (result.source !== undefined && result.source !== current[from])) {
      alert('El segmento cambió durante la traducción. Vuelve a intentarlo.'); return;
    }
    editor.commit(cid, to, result.text);
    editRevision++;
    const row = document.querySelector(`.cue[data-cue="${cid}"]`);
    const field = row?.querySelector(`[data-field="${to}"]`);
    if (field) field.value = result.text;
    const menu = row?.querySelector('.cue-translate');
    if (menu) menu.open = false;
    const saved = await editor.flush();
    if (direction === 'forward') {
      detail.project.target_language = language;
      detail.project.translation_language_known = true;
      if (model) detail.project.translation_model = model;
      if (translationDraft?.pid === pid) translationDraft.language = language;
      if ($('translation-language')) { $('translation-language').value = language; if (saved) $('translation-language').disabled = true; }
    }
    updateSaveStatus();
  } catch (error) { alert(error.message); }
  finally { stopElapsed(); if (operationStatus) operationStatus.textContent = ''; busy = false; }
}
async function loadCueComparison(cid) {
  const row = document.querySelector(`.cue[data-cue="${cid}"]`);
  if (!row) return;
  const panel = row.querySelector('.cue-model-comparison'), output = row.querySelector('.cue-compare-results');
  if (panel.dataset.loaded === '1') return;
  output.innerHTML = '<span class="spinner" aria-hidden="true"></span> Consultando modelos de Ollama…';
  try {
    const models = await api('/api/ollama/models');
    if (!panel.isConnected) return;
    const selections = panel.querySelectorAll('.compare-model');
    selections.forEach((select, index) => {
      select.innerHTML = models.map((m, i) => `<option value="${esc(m.name)}" ${i === index ? 'selected' : ''}>${esc(m.name)}</option>`).join('');
    });
    output.textContent = models.length < 2 ? 'Se necesitan al menos dos modelos instalados en Ollama.' : 'Elige dos modelos y compara el mismo texto.';
    panel.dataset.loaded = '1';
  } catch (error) { output.textContent = error.message; }
}
async function compareCueTranslations(pid, cid) {
  if (busy || !(await settleEdits()) || !cueEditor) return;
  const row = document.querySelector(`.cue[data-cue="${cid}"]`), editor = cueEditor;
  if (!row) return;
  const current = editor.get(cid), output = row.querySelector('.cue-compare-results');
  const models = [...row.querySelectorAll('.compare-model')].map(select => select.value);
  const direction = row.querySelector('.compare-direction').value, language = row.querySelector('.cue-language').value;
  const from = direction === 'forward' ? 'original' : 'translated', to = direction === 'forward' ? 'translated' : 'original';
  if (direction === 'forward' && detail.project.translation_language_known && detail.cues.some(cue => (cue.translated || '').trim()) && language !== detail.project.target_language) { output.textContent = 'Elige el idioma de destino del proyecto para no mezclar traducciones.'; return; }
  if (!current?.[from]?.trim()) { output.textContent = 'El texto de origen está vacío.'; return; }
  if (models.length !== 2 || !models[0] || !models[1] || models[0] === models[1]) { output.textContent = 'Elige dos modelos diferentes.'; return; }
  busy = true;
  const stopElapsed = showElapsedStatus(output, 'Comparando traducciones');
  try {
    const comparison = await api(`/api/projects/${pid}/cues/${cid}/compare-translations`, {method:'POST',headers:{'Content-Type':'application/json','X-Studio-Local':'1'},body:JSON.stringify({direction,target_language:language,models})});
    if (selected !== pid || cueEditor !== editor || !output.isConnected) return;
    if (dirty.size || editor.get(cid)?.[from] !== current[from] || editor.get(cid)?.[to] !== current[to] || comparison.source !== current[from]) { output.textContent = 'El segmento cambió. Vuelve a comparar.'; return; }
    output.innerHTML = comparison.results.map((result, index) => `<section><strong>${esc(result.model)}</strong>${result.seconds != null ? ` <span class="tiny">${esc(result.seconds)} s</span>` : ''}<p>${esc(result.error || result.text)}</p>${result.error ? '' : `<button type="button" data-use-result="${index}">Usar este resultado</button>`}</section>`).join('');
    positionCueMenu(row.querySelector('.cue-translate'));
    output.querySelectorAll('[data-use-result]').forEach(button => {
      button.onclick = async () => {
        if (busy || dirty.size || pendingEdits() || selected !== pid || cueEditor !== editor || editor.get(cid)?.[from] !== current[from] || editor.get(cid)?.[to] !== current[to]) { alert('El segmento cambió. Vuelve a comparar.'); return; }
        if (current[to].trim() && !confirm('El texto de destino será reemplazado. Podrás deshacer el cambio. ¿Continuar?')) return;
        const value = comparison.results[Number(button.dataset.useResult)].text;
        busy = true;
        try {
          editor.commit(cid, to, value); editRevision++;
          const field = row.querySelector(`[data-field="${to}"]`); if (field) field.value = value;
          const saved = await editor.flush();
          if (!saved) { updateSaveStatus(); return; }
          if (direction === 'forward' && !detail.project.translation_language_known) {
            await api(`/api/projects/${pid}/translation-language`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_language:language})});
            detail.project.target_language = language;
            detail.project.translation_language_known = true;
            if (translationDraft?.pid === pid) translationDraft.language = language;
            if ($('translation-language')) { $('translation-language').value = language; $('translation-language').disabled = true; }
          }
          updateSaveStatus();
          row.querySelector('.cue-translate').open = false;
        } catch (error) { alert(`No se pudo registrar el idioma: ${error.message}`); }
        finally { busy = false; }
      };
    });
  } catch (error) { if (output.isConnected) output.textContent = error.message; }
  finally { stopElapsed(); busy = false; }
}
async function resetWorkspace() {
  if (typeof comparisonSession !== 'undefined' && comparisonSession) { if (comparisonSession.running) return false; closeRangeComparison(); }
  if (typeof focusSession !== 'undefined' && focusSession && !(await closeFocusReview())) return false;
  if (busy || !(await settleEdits())) return false;
  cleanupAudioPreview();
  selected = null;
  if (typeof closeAuxScreen === 'function') closeAuxScreen();
  persistRoute("library");
  viewedCues = [];
  detail = null;
  cueEditor = null;
  editorProject = null;
  selectionRevision++;
  $("workspace").innerHTML = '<div class="empty">Selecciona un proyecto.</div>';
  $("project-header").innerHTML = "";
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
    if (pid === selected) await resetWorkspace();
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
    button.textContent = "Abrir archivos o carpeta";
  }
}
window.addEventListener("beforeunload", (e) => {
  if (dirty.size || busy || pendingEdits()) {
    e.preventDefault();
    e.returnValue = "";
  }
});
document.addEventListener?.('click', event => {
  document.querySelectorAll('.cue-translate').forEach(cueMenu => { if (cueMenu.open && !cueMenu.contains(event.target)) cueMenu.open = false; });
  const operations = $('project-operations');
  if (operations?.open && !operations.contains(event.target)) operations.open = false;
  const menu = $('export-menu'), toggle = $('export-toggle');
  if (exportOpen && menu && toggle && !menu.contains(event.target) && !toggle.contains(event.target) && !event.target.closest?.('[data-stage="export"]')) {
    exportOpen = false; menu.hidden = true; toggle.setAttribute('aria-expanded','false');
  }
});
$("open-local").onclick = openLocalFile;
refresh();
setInterval(refresh, 4000);
