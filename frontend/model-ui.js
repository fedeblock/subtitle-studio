function modelControlsMarkup() {
  return `<details id="models-controls" class="audio-details"><summary>Modelos de transcripción (ASR)</summary><div class="models-panel"><div id="models-list" class="tiny">Abre este panel para consultar la caché.</div><div id="models-status" class="tiny" role="status"></div><div class="compare-controls"><label>Idioma del fragmento <select id="compare-language"><option value="">Detección automática</option><option value="Romanian">Rumano</option><option value="Spanish">Español</option><option value="English">Inglés</option><option value="Portuguese">Portugués</option><option value="French">Francés</option><option value="Italian">Italiano</option><option value="German">Alemán</option><option value="Dutch">Neerlandés</option><option value="Japanese">Japonés</option><option value="Chinese">Chino</option></select></label> <button id="compare-models" type="button">Comparar 30 s desde el vídeo</button></div><p class="tiny">Se ejecutan Qwen y Whisper sobre el mismo fragmento. Si falta Whisper, se descargarán aproximadamente 3,1 GB; la primera comparación puede tardar. Los resultados no modifican el proyecto.</p><div id="compare-result"></div></div></details>`;
}
function formatModelSize(bytes) {
  return bytes ? `${(bytes / (1024 ** 3)).toFixed(2)} GiB` : "Sin archivos en caché";
}
async function refreshModels() {
  const list = $("models-list");
  if (!list) return;
  list.textContent = "Consultando modelos…";
  try {
    const entries = await api('/api/models');
    if ($("models-list") !== list) return;
    list.innerHTML = entries.filter(model => ['qwen','whisper'].includes(model.id)).map(model => `<div class="model-row"><span><strong>${esc(model.label)}</strong><br>${esc(formatModelSize(model.bytes))}${model.cached ? '' : ' · descarga pendiente'}</span><span><button type="button" data-model-download="${esc(model.id)}">${model.cached ? 'Verificar descarga' : 'Descargar'}</button>${model.bytes ? `<button type="button" data-model-delete="${esc(model.id)}">Borrar</button>` : ''}</span></div>`).join('');
    list.querySelectorAll('[data-model-download]').forEach(button => button.onclick = () => changeModelFiles(button.dataset.modelDownload, false));
    list.querySelectorAll('[data-model-delete]').forEach(button => button.onclick = () => changeModelFiles(button.dataset.modelDelete, true));
  } catch (error) { if ($("models-list") === list) list.textContent = error.message; }
}
async function changeModelFiles(model, remove) {
  if (busy || !['qwen','whisper'].includes(model)) return;
  const name = model === 'qwen' ? 'Qwen3-ASR y su alineador' : 'Whisper large-v3';
  if (remove && !confirm(`¿Borrar ${name} de la caché compartida de Hugging Face? Otras aplicaciones podrían necesitar descargarlo de nuevo. Los vídeos y subtítulos no se borrarán.`)) return;
  busy = true;
  const status = $("models-status");
  if (status) status.textContent = remove ? `Borrando ${name}…` : `Descargando ${name}… Puede tardar varios minutos.`;
  try {
    await api(`/api/models/${model}${remove ? '' : '/download'}`, {method: remove ? 'DELETE' : 'POST', headers:{'X-Studio-Local':'1'}});
    if (status) status.textContent = remove ? 'Archivos del modelo borrados.' : 'Descarga terminada.';
    await refreshModels();
  } catch (error) { if (status) status.textContent = error.message; }
  finally { busy = false; }
}
async function compareModels(pid) {
  if (busy || !(await settleEdits())) return;
  const video = $("video"), button = $("compare-models"), result = $("compare-result");
  if (!video || !button || !result) return;
  const start = Number.isFinite(video.currentTime) ? Math.max(0, Math.floor(video.currentTime)) : 0;
  const audio = $("audio-track");
  const audioIndex = audio && audio.value !== '' ? Number(audio.value) : null;
  const language = $("compare-language")?.value || null;
  busy = true; button.disabled = true;
  result.textContent = 'Comparando… Si falta algún modelo se descargará antes de comenzar.';
  try {
    const output = await api(`/api/projects/${pid}/compare-models`, {method:'POST', headers:{'Content-Type':'application/json','X-Studio-Local':'1'}, body:JSON.stringify({segment_start:start,audio_index:audioIndex,language})});
    if ($("compare-result") !== result) return;
    result.innerHTML = `<p class="tiny">Fragmento desde ${time(start)} · los tiempos incluyen carga y descarga.</p><div class="comparison">${['qwen','whisper'].map(id => `<section><strong>${id === 'qwen' ? 'Qwen3-ASR' : 'Whisper large-v3'}</strong><span class="tiny"> · ${esc(output.results[id].elapsed_seconds)} s</span><pre>${esc(output.results[id].srt || 'No se detectó voz.')}</pre></section>`).join('')}</div>`;
    await refreshModels();
  } catch (error) { if ($("compare-result") === result) result.textContent = error.message; }
  finally { busy = false; if ($("compare-models") === button) button.disabled = false; }
}
function bindModelControls(pid) {
  const panel = $("models-controls");
  if (!panel) return;
  panel.addEventListener('toggle', () => { if (panel.open) refreshModels(); });
  $("compare-models").onclick = () => compareModels(pid);
}
