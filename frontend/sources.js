function groupSources(options) {
  const groups = [
    { title: "Pistas del vídeo", items: [] },
    { title: "Junto al vídeo", items: [] },
    { title: "Carpeta de subtítulos", items: [] },
  ];
  let hidden = 0;
  for (const option of options) {
    if (!option.supported) { hidden++; continue; }
    const index = option.kind === "embedded" ? 0 : option.label.includes("/") ? 2 : 1;
    groups[index].items.push(option);
  }
  return { groups: groups.filter(group => group.items.length), hidden };
}
function selectedSource() {
  const options = [...document.querySelectorAll('input[name="subtitle-source"]')];
  return options.find(option => option.checked === true)?.value ||
    options.find(option => option.checked === undefined && option.hasAttribute('checked'))?.value || "";
}
function sourceChoices(project) {
  const {groups, hidden} = groupSources(project.subtitle_options || []);
  const noUsable = groups.length === 0;
  const radio = (value, label, checked = false) => `<label class="source-option"><input type="radio" name="subtitle-source" value="${esc(value)}" ${checked ? "checked" : ""}><span>${esc(label)}</span></label>`;
  const descriptions = groups.map(group => `<section class="source-group"><h3>${esc(group.title)}</h3>${group.items.map(item => radio(item.id, item.label)).join("")}</section>`).join("");
  const hiddenNote = hidden ? `<p class="source-note">${hidden === 1 ? '1 pista de imagen oculta: necesita OCR.' : `${hidden} pistas de imagen ocultas: necesitan OCR.`}</p>` : noUsable ? '<p class="source-note">No se encontraron subtítulos disponibles.</p>' : '';
  return `<div class="source-picker"><h2>Subtítulos</h2><div class="source-cta"><button id="start-project" class="primary" ${noUsable ? '' : 'disabled'}>${noUsable ? 'Transcribir' : 'Usar esta fuente'}</button>${noUsable ? "" : '<span class="source-note">Elige una fuente para comenzar.</span>'}</div><div id="subtitle-source" role="radiogroup" aria-label="Fuente de subtítulos">${descriptions}${hiddenNote}<section class="source-group"><h3>${noUsable ? 'Generar subtítulos' : 'Si ninguna sirve'}</h3>${radio('asr','Transcribir el audio',noUsable)}<div id="asr-options" ${noUsable ? '' : 'hidden'}><label>Idioma hablado <select id="asr-language"><option value="">Detección automática</option><option value="Romanian">Rumano</option><option value="Spanish">Español</option><option value="English">Inglés</option><option value="Portuguese">Portugués</option><option value="French">Francés</option><option value="Italian">Italiano</option><option value="German">Alemán</option><option value="Dutch">Neerlandés</option><option value="Japanese">Japonés</option><option value="Chinese">Chino</option></select></label><p class="source-note">Para varios idiomas, usa detección automática. En rumano, revisa los tiempos.</p></div></section></div>${(project.source_warnings || []).map(w => `<p class="source-note">${esc(w)}</p>`).join('')}<div id="subtitle-preview" class="subtitle-preview" hidden></div></div>`;
}
function updateDraftAction() {
  const button = $("start-project");
  if (!button) return;
  const source = selectedSource();
  button.disabled = !source;
  if ($("asr-options")) $("asr-options").hidden = source !== "asr";
  button.textContent = source === "asr" ? "Transcribir" : "Usar esta fuente";
}
