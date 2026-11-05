let libraryCollapsed = true;
function toggleLibrary() {
  libraryCollapsed = !libraryCollapsed;
  document.body.classList.toggle("library-collapsed", libraryCollapsed);
  $("library-toggle").setAttribute("aria-expanded", String(!libraryCollapsed));
  $("library-toggle").setAttribute("aria-label", libraryCollapsed ? "Mostrar biblioteca" : "Ocultar biblioteca");
}
function renderList() {
  const activeStates = new Set(["queued", "transcribing", "translating", "improve_queued", "improving"]);
  $("projects").innerHTML = projects.length ? projects.map(p => `<div class="project ${selected === p.id ? "active" : ""}" data-id="${esc(p.id)}"><button class="project-open" type="button"><span class="name">${esc(p.name)}</span><small>${esc(stateName(p))}</small><span class="progress"><span style="width:${Number(p.progress) || 0}%"></span></span></button>${activeStates.has(p.state) ? "" : `<button type="button" data-action="remove" title="${viewingTrash ? "Restaurar" : "Quitar de la biblioteca"}" aria-label="${viewingTrash ? "Restaurar" : "Quitar"} ${esc(p.name)}">${viewingTrash ? "↶" : "✕"}</button>`}</div>`).join("") : `<div class="empty">${viewingTrash ? "Papelera vacía." : "Aún no hay proyectos."}</div>`;
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
  $("library-toggle").onclick = toggleLibrary;
  $("show-trash").onclick = toggleTrash;
  $("clear-library").onclick = clearLibrary;
  $("restore-library").onclick = restoreLibrary;
}
bindLibrary();
