let libraryCollapsed = true;
let libraryFilter = "all", librarySearch = "";
const workingStates = new Set(["batch_queued", "queued", "transcribing", "translating", "improve_queued", "improving", "pausing", "cancelling"]);

function librarySummary(project) {
  const counts = project.counts || {}, progress = taskProgress(project);
  if (project.state === "draft") return { label:`Elige los subtítulos · ${(project.subtitle_options || []).filter(s => s.supported && s.match !== false).length} encontrados`, category:"todo", action:"Elegir" };
  if (project.state === "failed") return {label:"Necesita atención", category:"attention", tone:"error", action:"Revisar"};
  if (workingStates.has(project.state)) return {label:stateName(project), category:"running", tone:"work", action:"Ver", percent:progress?.percent};
  if (counts.flagged_open) return {label:`${counts.flagged_open} segmentos dudosos`, category:"attention", tone:"warn", action:"Revisar"};
  if (counts.untranslated) return {label:`${counts.untranslated} sin traducir`, category:"todo", action:"Traducir", percent:counts.cues ? Math.round(100 * (counts.cues - counts.untranslated) / counts.cues) : null};
  return {label:counts.cues ? "Listo para exportar" : stateName(project), category:"done", tone:"ok", action:counts.cues ? "Exportar" : "Abrir", percent:counts.cues ? 100 : null};
}

function renderLibraryHome() {
  const home = $("library-home");
  if (!home) return;
  const wasSearching = document.activeElement === home.querySelector('.home-search');
  const searchCursor = wasSearching ? document.activeElement.selectionStart : null;
  document.body.classList.toggle("home-visible", !selected);
  const rows = projects.map(project => ({project, summary:librarySummary(project)}));
  const filters = [["all","Todo"],["attention","Necesita atención"],["todo","Por hacer"],["running","En curso"],["done","Listo"]];
  const matching = rows.filter(({project, summary}) => (libraryFilter === "all" || summary.category === libraryFilter) && `${project.name} ${project.serie || ""} ${summary.label}`.toLocaleLowerCase().includes(librarySearch.toLocaleLowerCase()));
  const groups = new Map();
  for (const row of matching) {
    const p = row.project, name = p.serie ? `${p.serie} · Temporada ${p.season}` : "Películas";
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(row);
  }
  const groupHtml = [...groups].map(([name, group]) => `<section class="home-group"><h2>${esc(name)}<span>${group.length} ${name === "Películas" ? "títulos" : "episodios"}</span></h2><div class="home-table">${group.sort((a,b) => (a.project.episode || 0) - (b.project.episode || 0)).map(({project:p,summary:s}) => `<div class="home-row" data-home-project="${esc(p.id)}"><span class="home-episode">${p.episode ? `E${String(p.episode).padStart(2,"0")}` : esc(p.year || "")}</span><button class="home-open" type="button"><span class="home-name" title="${esc(p.name)}">${esc(p.name)}</span><small class="${esc(s.tone || "")}">${esc(s.label)}</small></button><div class="home-progress">${s.percent == null ? "" : `<span style="width:${Math.max(0,Math.min(100,s.percent))}%"></span>`}</div><button class="home-action" type="button">${esc(s.action)}</button>${workingStates.has(p.state) ? '<span></span>' : `<button class="home-remove" type="button" title="${viewingTrash ? "Restaurar" : "Quitar de la biblioteca"}" aria-label="${viewingTrash ? "Restaurar" : "Quitar"} ${esc(p.name)}">${viewingTrash ? "↶" : "✕"}</button>`}</div>`).join("")}</div></section>`).join("");
  const batchProjects = projects.filter(p => p.batch);
  home.innerHTML = `<div class="home-content"><div class="home-controls"><input class="home-search" type="search" aria-label="Buscar proyectos" placeholder="Buscar serie, película o estado" value="${esc(librarySearch)}">${filters.map(([key,label]) => `<button type="button" data-library-filter="${key}" class="home-chip ${key === libraryFilter ? "active" : ""} ${key === "attention" ? "attention" : ""}">${label} <span>${key === "all" ? rows.length : rows.filter(row => row.summary.category === key).length}</span></button>`).join("")}${batchProjects.length ? `<button type="button" id="home-queue">Cola · ${batchProjects.length} ›</button>` : ''}</div>${groupHtml || `<div class="empty">${viewingTrash ? "Papelera vacía." : rows.length ? "Nada coincide con la búsqueda." : "Aún no hay proyectos."}</div>`}<div class="home-footer"><button type="button" id="home-trash">${viewingTrash ? "Ver biblioteca" : "Papelera"}</button><button type="button" id="home-clear">${viewingTrash ? "Restaurar todo" : "Vaciar biblioteca"}</button></div></div>`;
  home.querySelectorAll('[data-library-filter]').forEach(button => button.onclick = () => { libraryFilter = button.dataset.libraryFilter; renderLibraryHome(); });
  const search = home.querySelector('.home-search');
  search.oninput = () => { const cursor = search.selectionStart; librarySearch = search.value; renderLibraryHome(); const next = home.querySelector('.home-search'); next.focus(); if (cursor != null && next.setSelectionRange) next.setSelectionRange(cursor, cursor); };
  if (wasSearching) { search.focus(); if (searchCursor != null && search.setSelectionRange) search.setSelectionRange(searchCursor, searchCursor); }
  home.querySelectorAll('[data-home-project]').forEach(row => {
    row.onclick = event => { if (!event.target.closest('button')) select(row.dataset.homeProject); };
    row.querySelector('.home-open').onclick = () => select(row.dataset.homeProject);
    row.querySelector('.home-action').onclick = () => select(row.dataset.homeProject);
    const remove = row.querySelector('.home-remove');
    if (remove) remove.onclick = () => removeProject(row.dataset.homeProject);
  });
  home.querySelector('#home-trash').onclick = toggleTrash;
  home.querySelector('#home-clear').onclick = viewingTrash ? restoreLibrary : clearLibrary;
  if (home.querySelector('#home-queue')) home.querySelector('#home-queue').onclick = () => openBatchQueue(batchProjects[0].batch.id);
}
function toggleLibrary() {
  libraryCollapsed = !libraryCollapsed;
  document.body.classList.toggle("library-collapsed", libraryCollapsed);
  $("library-toggle").setAttribute("aria-expanded", String(!libraryCollapsed));
  $("library-toggle").setAttribute("aria-label", libraryCollapsed ? "Mostrar biblioteca" : "Ocultar biblioteca");
}
function renderList() {
  renderLibraryHome();
  const activeStates = new Set(["batch_queued", "queued", "transcribing", "translating", "improve_queued", "improving", "pausing", "cancelling"]);
  $("projects").innerHTML = projects.length ? projects.map(p => { const info = taskProgress(p); const percent = info?.percent ?? (p.state === 'ready' ? 100 : null); return `<div class="project ${selected === p.id ? "active" : ""}" data-id="${esc(p.id)}"><button class="project-open" type="button"><span class="name">${esc(p.name)}</span><small>${esc(stateName(p))}</small><span class="progress ${percent === null && info ? 'indeterminate' : ''}"><span style="width:${percent ?? 0}%"></span></span></button>${activeStates.has(p.state) ? "" : `<button type="button" data-action="remove" title="${viewingTrash ? "Restaurar" : "Quitar de la biblioteca"}" aria-label="${viewingTrash ? "Restaurar" : "Quitar"} ${esc(p.name)}">${viewingTrash ? "↶" : "✕"}</button>`}</div>`; }).join("") : `<div class="empty">${viewingTrash ? "Papelera vacía." : "Aún no hay proyectos."}</div>`;
  $("show-trash").textContent = viewingTrash ? "Ver biblioteca" : "Papelera";
  $("clear-library").hidden = viewingTrash;
  $("restore-library").hidden = !viewingTrash;
  document.querySelectorAll(".project[data-id]").forEach(row => {
    row.querySelector(".project-open").onclick = () => select(row.dataset.id);
    const remove = row.querySelector('[data-action="remove"]');
    if (remove) remove.onclick = () => removeProject(row.dataset.id);
  });
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

function bindLibrary() {
  document.body.classList.toggle("library-collapsed", libraryCollapsed);
  $("library-toggle").onclick = async () => { if (await resetWorkspace()) renderList(); };
  $("show-trash").onclick = toggleTrash;
  $("clear-library").onclick = clearLibrary;
  $("restore-library").onclick = restoreLibrary;
  document.addEventListener("click", (event) => {
    if (!libraryCollapsed && !$("library-toggle").contains(event.target) && !document.querySelector(".library").contains(event.target))
      toggleLibrary();
  });
  window.addEventListener("hashchange", async () => {
    const route = window.location?.hash?.slice(1);
    if (route === "library" && selected) {
      if (await resetWorkspace()) renderList();
      else persistRoute(`project:${selected}`);
    } else if (route?.startsWith("project:") && route.slice(8) !== selected) {
      const id = route.slice(8);
      if (projects.some(p => p.id === id)) await select(id);
      else persistRoute(selected ? `project:${selected}` : "library");
    }
  });
}
bindLibrary();
