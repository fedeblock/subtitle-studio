function groupSources(options, projectName = "") {
  const groups = [
    { title: "Pistas del vídeo", items: [] },
    { title: "Junto al vídeo", items: [] },
    { title: "Carpeta de subtítulos", items: [] },
  ];
  let hidden = 0;
  const otherEpisodes = [];
  const episode = (name) => {
    const match = /(?:s(\d{1,2})e(\d{1,3})|(?:^|\D)(\d{1,2})x(\d{1,3}))/i.exec(name);
    return match ? `${Number(match[1] || match[3])}:${Number(match[2] || match[4])}` : null;
  };
  const targetEpisode = episode(projectName);
  for (const option of options) {
    if (!option.supported) { hidden++; continue; }
    const isOther = option.match === false || (option.match === undefined && option.kind === "file" && targetEpisode && episode(option.label) !== targetEpisode);
    if (isOther) { otherEpisodes.push(option); continue; }
    const index = option.kind === "embedded" ? 0 : option.label.includes("/") ? 2 : 1;
    groups[index].items.push(option);
  }
  return { groups: groups.filter(group => group.items.length), hidden, otherEpisodes };
}
function selectedSource() {
  const options = [...document.querySelectorAll('input[name="subtitle-source"]')];
  return options.find(option => option.checked === true)?.value ||
    options.find(option => option.checked === undefined && option.hasAttribute('checked'))?.value || "";
}
function sourceChoices(project) {
  if (project.prefer_asr) {
    const languages = [["", "Detección automática"], ["Romanian", "Rumano"], ["Spanish", "Español"], ["English", "Inglés"], ["Portuguese", "Portugués"], ["French", "Francés"], ["Italian", "Italiano"], ["German", "Alemán"], ["Dutch", "Neerlandés"], ["Japanese", "Japonés"], ["Chinese", "Chino"]];
    return `<div class="source-picker"><h2>Nueva transcripción</h2><p class="source-note">La versión anterior queda guardada en la biblioteca. Puedes elegir otra pista de audio junto al vídeo.</p><div id="subtitle-source" role="radiogroup" aria-label="Fuente de subtítulos"><input type="radio" name="subtitle-source" value="asr" checked hidden><div id="asr-options"><label>Modelo <select id="asr-model"><option value="qwen" ${project.asr_model === 'whisper' ? '' : 'selected'}>Qwen3-ASR 1.7B</option><option value="whisper" ${project.asr_model === 'whisper' ? 'selected' : ''}>Whisper large-v3 · descarga aprox. 3,1 GB</option></select></label><p class="source-note">Los modelos se descargan al primer uso si faltan.</p><label>Idioma hablado <select id="asr-language">${languages.map(([value,label]) => `<option value="${value}" ${value === (project.asr_language || '') ? 'selected' : ''}>${label}</option>`).join('')}</select></label><p class="source-note">Para varios idiomas, usa detección automática. En rumano, revisa los tiempos.</p></div></div><div class="source-cta"><button id="start-project" class="primary">Transcribir</button></div><div id="subtitle-preview" class="subtitle-preview" hidden></div></div>`;
  }
  const {groups, hidden, otherEpisodes} = groupSources(project.subtitle_options || [], project.name);
  const items = groups.flatMap(group => group.items);
  const recommended = items.find(item => item.recommended) || items.find(item => item.kind === 'file' && !item.label.includes('/')) || items.find(item => item.kind === 'file') || items[0];
  const noSources = groups.length === 0;
  const noUsable = noSources || project.prefer_asr;
  const radio = (value, label, checked = false) => `<label class="source-option"><input type="radio" name="subtitle-source" value="${esc(value)}" ${checked ? "checked" : ""}><span>${esc(label)}</span></label>`;
  const descriptions = groups.map(group => `<section class="source-group"><h3>${esc(group.title)}</h3>${group.items.map(item => radio(item.id, item.label + (item.recommended ? " · recomendada" : ""), item.id === recommended?.id)).join("")}</section>`).join("");
  const otherNote = otherEpisodes.length ? `<details class="source-note"><summary>${otherEpisodes.length} ${otherEpisodes.length === 1 ? "subtítulo de otro episodio oculto" : "subtítulos de otros episodios ocultos"}</summary>${otherEpisodes.map(item => `<div>${esc(item.label)}</div>`).join("")}</details>` : "";
  const hiddenNote = hidden ? `<p class="source-note">${hidden === 1 ? '1 pista de imagen oculta: necesita OCR.' : `${hidden} pistas de imagen ocultas: necesitan OCR.`}</p>` : noSources ? '<p class="source-note">No se encontraron subtítulos disponibles.</p>' : '';
  return `<div class="source-picker"><h2>Subtítulos</h2><div class="source-cta"><button id="start-project" class="primary" ${noUsable ? '' : 'disabled'}>${noUsable ? 'Transcribir' : 'Abrir y revisar'}</button>${noUsable ? "" : '<span class="source-note">Elige una fuente; después podrás revisar o traducir.</span>'}</div><div id="subtitle-source" class="${noSources ? '' : 'source-list-scroll'}" role="radiogroup" aria-label="Fuente de subtítulos">${descriptions}${hiddenNote}${otherNote}<section class="source-group"><h3>${noUsable ? 'Generar subtítulos' : 'Si ninguna sirve'}</h3>${radio('asr','Transcribir el audio',noUsable)}<div id="asr-options" ${noUsable ? '' : 'hidden'}><label>Modelo <select id="asr-model"><option value="qwen">Qwen3-ASR 1.7B</option><option value="whisper">Whisper large-v3 · descarga aprox. 3,1 GB</option></select></label><p class="source-note">Los modelos se descargan al primer uso si faltan.</p><label>Idioma hablado <select id="asr-language"><option value="">Detección automática</option><option value="Romanian">Rumano</option><option value="Spanish">Español</option><option value="English">Inglés</option><option value="Portuguese">Portugués</option><option value="French">Francés</option><option value="Italian">Italiano</option><option value="German">Alemán</option><option value="Dutch">Neerlandés</option><option value="Japanese">Japonés</option><option value="Chinese">Chino</option></select></label><p class="source-note">Para varios idiomas, usa detección automática. En rumano, revisa los tiempos.</p></div></section></div>${(project.source_warnings || []).map(w => `<p class="source-note">${esc(w)}</p>`).join('')}<div id="subtitle-preview" class="subtitle-preview" hidden></div></div>`;
}
function updateDraftAction() {
  const button = $("start-project");
  if (!button) return;
  const source = selectedSource();
  button.disabled = !source;
  const hint = document.querySelector('.source-cta .source-note');
  if (hint) hint.hidden = !!source;
  if ($("asr-options")) $("asr-options").hidden = source !== "asr";
  button.textContent = source === "asr" ? "Transcribir" : "Abrir y revisar";
}
