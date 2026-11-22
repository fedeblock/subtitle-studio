/* Review existing segments without copying the video or mutating text before saving. */
let focusSession = null;
let focusBusy = false;

async function runFocusAction(action) {
  if (focusBusy) return;
  focusBusy = true;
  try { await action(); } finally { focusBusy = false; }
}

async function openFocusReview() {
  if (!detail || !cueEditor || !(await settleEdits())) return;
  const ids = detail.cues.filter(c => c.flag && !c.flag_resolved).map(c => c.id);
  if (!ids.length) return;
  focusSession = {project:detail.project.id, ids, index:0, total:ids.length, reviewed:0};
  const overlay = document.createElement('div');
  overlay.id = 'focus-review';
  overlay.className = 'focus-review';
  $('workspace').appendChild(overlay);
  drawFocusReview();
}

function drawFocusReview() {
  const session = focusSession, overlay = $('focus-review'), frame = $('video-frame');
  if (!session || !overlay || !frame) return;
  const id = session.ids[session.index];
  const cue = detail?.cues.find(c => c.id === id);
  if (!cue) {
    $('video-center')?.appendChild(frame);
    overlay.innerHTML = `<div class="focus-complete"><strong>✓ Has revisado ${session.reviewed} segmentos</strong><p>Los cambios ya están guardados.</p><button id="focus-close" type="button">Volver a la lista</button><button id="focus-translate" class="primary" type="button">Siguiente: traducir</button></div>`;
    $('focus-close').onclick = closeFocusReview;
    $('focus-translate').onclick = async () => { if (await closeFocusReview()) { currentStage='translate'; cueFilter='all'; renderWorkspace(); } };
    return;
  }
  const row = cueEditor.get(id) || cue;
  const all = detail.cues, pos = all.findIndex(c => c.id === id);
  const reasons = {repeat:'Repetición · Repite el segmento anterior o una frase',silence:'Audio de baja energía · Comprueba si hay voz',low_confidence:'Baja confianza · Revisa estas palabras',out_of_chunk:'Fuera de tramo · Revisa los tiempos'};
  overlay.innerHTML = `<div class="focus-bar"><button id="focus-close" type="button">‹ Lista</button><button id="focus-prev" type="button" aria-label="Dudoso anterior">‹</button><strong>Dudoso ${session.index + 1} de ${session.ids.length}</strong><button id="focus-next-top" type="button" aria-label="Dudoso siguiente">›</button><span class="focus-reason">⚠ ${esc(reasons[cue.flag] || cue.flag)}</span><span class="focus-hint">Esc volver a la lista</span></div><div class="focus-body"><div class="focus-media"><div id="focus-video"></div><div id="focus-audio" class="focus-audio">Audio del segmento</div></div><div class="focus-fields"><p class="focus-context">${esc(all[pos-1]?.original || '')}</p><label>Original <textarea id="focus-text">${esc(row.original)}</textarea></label><div class="focus-times"><label>Entrada <input id="focus-start" value="${time(row.start)}"></label><label>Salida <input id="focus-end" value="${time(row.end)}"></label></div><p class="focus-context">${esc(all[pos+1]?.original || '')}</p><p id="focus-error" role="status"></p></div></div><div class="focus-footer"><button id="focus-delete" type="button" ${detail.project.state === 'transcribing' ? 'disabled title="Espera a que termine la transcripción"' : ''}>Borrar segmento [B]</button><button id="focus-accept" type="button">Es correcto [A]</button><span>Editar el texto y pasar al siguiente también lo da por revisado.</span><button id="focus-next" type="button" class="primary">Siguiente dudoso [→]</button></div>`;
  $('focus-video').appendChild(frame);
  const video = $('video');
  video.currentTime = row.start;
  $('focus-close').onclick = closeFocusReview;
  $('focus-prev').onclick = () => runFocusAction(() => moveFocus(-1));
  $('focus-next-top').onclick = () => runFocusAction(() => moveFocus(1));
  $('focus-next').onclick = () => runFocusAction(() => moveFocus(1));
  $('focus-accept').onclick = () => runFocusAction(acceptFocusCue);
  $('focus-delete').onclick = () => runFocusAction(deleteFocusCue);
  void loadFocusAudio(session, cue);
}

async function loadFocusAudio(session, cue) {
  const target = $('focus-audio'), video = $('video');
  if (!target || !video || detail?.project.source_kind !== 'reference' || !detail.project.audio_tracks?.length) return;
  const start = Math.max(0, cue.start - 4), end = Math.min(video.duration || cue.end + 4, cue.end + 4);
  const index = Number($('audio-track')?.value ?? detail.project.audio_tracks[0].index);
  try {
    const data = await api(`/api/projects/${session.project}/envelope?start=${start}&end=${end}&buckets=160&index=${index}`);
    if (focusSession !== session || $('focus-audio') !== target || session.ids[session.index] !== cue.id) return;
    if (!Array.isArray(data.amplitudes)) return;
    target.innerHTML = `<div class="focus-wave">${data.amplitudes.map((v,i) => { const t=start+(i+.5)*(end-start)/data.amplitudes.length; return `<i class="${t >= cue.start && t < cue.end ? 'selected' : ''}" style="height:${Math.max(2,Math.round(Math.sqrt(Math.max(0,Math.min(1,Number(v)||0)))*60))}px"></i>`; }).join('')}</div><div class="voice-scale"><span>${time(start).slice(0,8)}</span><span>Audio ±4 s · en naranja, el segmento</span><span>${time(end).slice(0,8)}</span></div>`;
  } catch { if ($('focus-audio') === target) target.textContent = 'No se pudo analizar este fragmento de audio.'; }
}

async function saveFocusChanges() {
  const session = focusSession, id = session?.ids[session.index], current = cueEditor?.get(id);
  if (!current || !$('focus-text')) return {ok:true, changed:false};
  const start = secs($('focus-start').value), end = secs($('focus-end').value), text = $('focus-text').value;
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) {
    $('focus-error').textContent = 'Revisa los tiempos: la salida debe ser posterior a la entrada.';
    return {ok:false, changed:false};
  }
  if (detail.project.state === 'transcribing' && (start !== current.start || end !== current.end)) {
    $('focus-error').textContent = 'Los tiempos podrán editarse cuando termine la transcripción.';
    return {ok:false, changed:false};
  }
  const changed = text !== current.original || start !== current.start || end !== current.end;
  try {
    if (start >= current.end) { cueEditor.commit(id,'end',end); cueEditor.commit(id,'start',start); }
    else { cueEditor.commit(id,'start',start); cueEditor.commit(id,'end',end); }
    cueEditor.commit(id,'original',text);
    if (!(await cueEditor.flush())) throw cueEditor.error || Error('No se pudo guardar');
    return {ok:true, changed};
  } catch (error) { $('focus-error').textContent = error.message; return {ok:false, changed:false}; }
}

async function resolveFocusCue() {
  const session = focusSession, id = session?.ids[session.index], c = cueEditor?.get(id);
  if (!session || !c) return false;
  const {start,end,original,translated} = c;
  try {
    const saved = await api(`/api/projects/${session.project}/cues/${id}`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({start,end,original,translated,expected:{start,end,original,translated},flag_resolved:true})});
    const at = detail.cues.findIndex(item => item.id === id);
    if (at >= 0) detail.cues[at] = saved;
    session.ids.splice(session.index,1); session.reviewed++;
    if (session.index >= session.ids.length) session.index = Math.max(0, session.ids.length - 1);
    return true;
  } catch (error) { $('focus-error').textContent = error.message; return false; }
}
async function acceptFocusCue() {
  const result = await saveFocusChanges();
  if (!result.ok || !(await resolveFocusCue())) return;
  drawFocusReview();
}
async function moveFocus(direction) {
  const session = focusSession, result = await saveFocusChanges();
  if (!session || !result.ok) return;
  if (result.changed) { if (!(await resolveFocusCue())) return; }
  else session.index = Math.max(0,Math.min(session.ids.length - 1,session.index + direction));
  drawFocusReview();
}
async function deleteFocusCue() {
  const session = focusSession, id = session?.ids[session.index];
  if (!id || !confirm('¿Borrar este segmento de los subtítulos del proyecto? El vídeo original se conservará.')) return;
  if (!(await saveFocusChanges()).ok) return;
  try {
    const {start,end,original,translated} = cueEditor.get(id);
    const result = await api(`/api/projects/${session.project}/cues/${id}`, {method:'DELETE',headers:{'X-Studio-Local':'1','Content-Type':'application/json'},body:JSON.stringify({expected:{start,end,original,translated}})});
    if (result.undo_id) lastComparisonUndo = {pid:session.project,id:result.undo_id};
    detail.cues = detail.cues.filter(c => c.id !== id);
    cueEditor.rows.delete(id); cueEditor.confirmed.delete(id);
    cueEditor.undoStack = cueEditor.undoStack.filter(a => a.id !== id);
    cueEditor.redoStack = cueEditor.redoStack.filter(a => a.id !== id);
    session.ids.splice(session.index,1); session.reviewed++;
    if (session.index >= session.ids.length) session.index = Math.max(0, session.ids.length - 1);
    drawFocusReview();
  } catch (error) { $('focus-error').textContent = error.message; }
}
async function closeFocusReview() {
  if (!focusSession) return true;
  if (focusBusy) return false;
  const saved = await saveFocusChanges();
  if (!saved.ok || saved.changed && !(await resolveFocusCue())) return false;
  const frame = $('video-frame');
  if (frame) $('video-center')?.appendChild(frame);
  $('focus-review')?.remove();
  focusSession = null;
  cueFilter = 'sus';
  renderWorkspace();
  return true;
}
window.addEventListener('keydown', event => {
  if (!focusSession) return;
  if (event.key === 'Escape') { event.preventDefault(); void closeFocusReview(); return; }
  if (['INPUT','TEXTAREA','SELECT'].includes(event.target?.tagName)) return;
  if (event.key.toLowerCase() === 'a') { event.preventDefault(); void runFocusAction(acceptFocusCue); }
  else if (event.key.toLowerCase() === 'b' && !$('focus-delete')?.disabled) { event.preventDefault(); void runFocusAction(deleteFocusCue); }
  else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); void runFocusAction(() => moveFocus(event.key === 'ArrowRight' ? 1 : -1)); }
});
