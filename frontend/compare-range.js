/* Range comparisons are read-only until the user explicitly applies choices. */
let comparisonSession = null;
let lastComparisonUndo = null;

async function openRangeComparison(pid, cueId) {
  if (!detail || detail.project.id !== pid || !(await settleEdits())) return;
  const index = detail.cues.findIndex(cue => cue.id === cueId);
  if (index < 0) return;
  const start = Math.max(0,index - 1);
  const cues = detail.cues.slice(start,start + 8).map(cue => ({...(cueEditor?.get(cue.id) || cue)}));
  comparisonSession = {pid,cues,choices:{},result:null};
  const modal = document.createElement('div');
  modal.id = 'compare-modal'; modal.className = 'compare-scrim';
  modal.innerHTML = `<div class="compare-dialog" role="dialog" aria-modal="true" aria-labelledby="compare-title"><div class="compare-heading"><strong id="compare-title">Comparar traducción</strong><span>${time(cues[0].start).slice(0,8)} → ${time(cues[cues.length-1].end).slice(0,8)} · ${cues.length} segmentos</span><button id="close-range-comparison" type="button" aria-label="Cerrar">✕</button></div><p>Se compara la entrada elegida, la anterior si existe y las siguientes, hasta un máximo de 8. Cada modelo traduce el mismo texto por separado; eliges qué resultados aplicar.</p><div class="compare-config"><label>Idioma <select id="compare-range-language"><option value="Spanish">Español</option><option value="English">Inglés</option><option value="Romanian">Rumano</option><option value="Portuguese">Portugués</option><option value="French">Francés</option><option value="Italian">Italiano</option><option value="German">Alemán</option></select></label><label>Modelo A <select id="compare-model-a"></select></label><label>Modelo B <select id="compare-model-b"></select></label><button id="run-range-comparison" type="button" class="primary">Comparar</button></div><div id="range-comparison-status" role="status"><span class="spinner" aria-hidden="true"></span> Consultando modelos…</div><div id="range-comparison-results" class="compare-results"></div><div class="compare-footer"><span>Las opciones no cambian el proyecto hasta aplicarlas.</span><button id="compare-all-a" type="button" disabled>Todo A</button><button id="compare-all-b" type="button" disabled>Todo B</button><button id="apply-range-comparison" type="button" class="primary" disabled>Aplicar 0 cambios</button></div></div>`;
  document.body.appendChild(modal);
  if (translationDraft?.pid === pid && translationDraft.language) $('compare-range-language').value = translationDraft.language;
  if (detail.project.translation_language_known) {
    $('compare-range-language').value = detail.project.target_language;
    if (detail.cues.some(cue => (cue.translated || '').trim())) $('compare-range-language').disabled = true;
  }
  $('close-range-comparison').onclick = closeRangeComparison;
  $('run-range-comparison').onclick = runRangeComparison;
  $('compare-all-a').onclick = () => chooseAllComparison(0);
  $('compare-all-b').onclick = () => chooseAllComparison(1);
  $('apply-range-comparison').onclick = applyRangeComparison;
  try {
    const models = await api('/api/ollama/models');
    if (comparisonSession?.pid !== pid || $('compare-modal') !== modal) return;
    const names = models.map(model => model.name).filter(Boolean);
    for (const id of ['compare-model-a','compare-model-b']) $(id).innerHTML = names.map(name => `<option value="${esc(name)}">${esc(name)}</option>`).join('');
    if (names.length > 1) $('compare-model-b').value = names[1];
    $('range-comparison-status').textContent = names.length < 2 ? 'Instala al menos dos modelos de Ollama para comparar.' : 'Elige dos modelos instalados.';
    $('run-range-comparison').disabled = names.length < 2;
  } catch (error) { if ($('compare-modal') === modal) $('range-comparison-status').textContent = error.message; }
}
function closeRangeComparison() {
  if (comparisonSession?.running) return;
  $('compare-modal')?.remove(); comparisonSession = null;
}
async function runRangeComparison() {
  const session=comparisonSession;
  if (!session || session.running) return;
  const models=[$('compare-model-a').value,$('compare-model-b').value];
  if (models[0] === models[1]) { $('range-comparison-status').textContent='Elige dos modelos diferentes.'; return; }
  session.running=true; $('run-range-comparison').disabled=true;
  const stopElapsed = showElapsedStatus($('range-comparison-status'), 'Comparando traducciones');
  try {
    session.result=await api(`/api/projects/${session.pid}/compare-translations`,{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Local':'1'},body:JSON.stringify({cue_ids:session.cues.map(c=>c.id),direction:'forward',target_language:$('compare-range-language').value,models})});
    session.choices={};
    if (comparisonSession === session) { $('range-comparison-status').textContent='Elige un resultado por segmento.'; drawRangeComparison(); }
  } catch(error) { if(comparisonSession === session) $('range-comparison-status').textContent=error.message; }
  finally { stopElapsed(); session.running=false; if(comparisonSession === session) $('run-range-comparison').disabled=false; }
}
function drawRangeComparison() {
  const session=comparisonSession, results=session?.result?.results;
  if (!session || !results || results.length !== 2) return;
  const target=$('range-comparison-results');
  target.innerHTML=`<div class="compare-grid compare-header"><span>#</span><strong>Original</strong>${results.map(r=>`<strong>${esc(r.model)}${r.seconds != null ? ` · ${r.seconds} s` : ''}</strong>`).join('')}<strong>Actual</strong></div>${session.cues.map((cue,i)=>`<div class="compare-grid"><span>${cue.position + 1}</span><span>${esc(cue.original)}</span>${results.map((r,choice)=>{const value=r.texts?.[i];return `<button type="button" data-compare-cue="${esc(cue.id)}" data-compare-choice="${choice}" class="compare-cell ${session.choices[cue.id]===choice ? 'selected' : ''}" ${typeof value !== 'string' || !value.trim() ? 'disabled' : ''}>${esc(typeof value === 'string' ? value || '(sin texto)' : r.error || 'No disponible')}</button>`}).join('')}<span>${esc(cue.translated || '(sin texto)')}</span></div>`).join('')}`;
  target.querySelectorAll('[data-compare-cue]').forEach(button => button.onclick=()=>{session.choices[button.dataset.compareCue]=Number(button.dataset.compareChoice);drawRangeComparison();});
  $('compare-all-a').disabled=!results[0].texts;
  $('compare-all-b').disabled=!results[1].texts;
  const n=comparisonChanges(session).length;
  $('apply-range-comparison').disabled=!n;
  $('apply-range-comparison').textContent=`Aplicar ${n} cambios`;
}
function comparisonChanges(session) {
  return session.cues.flatMap((cue,index)=>{
    const choice=session.choices[cue.id];
    if (choice === undefined) return [];
    const value=session.result?.results[choice]?.texts?.[index];
    if (typeof value !== 'string' || !value.trim() || value === cue.translated) return [];
    const {start,end,original,translated}=cue;
    return [{cue_id:cue.id,field:'translated',value,expected:{start,end,original,translated}}];
  });
}
function chooseAllComparison(choice) {
  const session=comparisonSession;
  if (!session?.result?.results[choice]?.texts) return;
  session.cues.forEach(cue=>session.choices[cue.id]=choice);
  drawRangeComparison();
}
async function applyRangeComparison() {
  const session=comparisonSession;
  if (!session || session.running) return;
  const changes=comparisonChanges(session);
  if (!changes.length) return;
  if (changes.some(change=>!change.value.trim()) && !confirm('Una opción vacía borrará su segmento. ¿Continuar?')) return;
  session.running=true; $('apply-range-comparison').disabled=true;
  try {
    const result=await api(`/api/projects/${session.pid}/apply-comparison`,{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Local':'1'},body:JSON.stringify({changes})});
    lastComparisonUndo={pid:session.pid,id:result.undo_id};
    session.running=false; closeRangeComparison();
    await refresh();
    if (detail?.project.id === session.pid) renderWorkspace();
  } catch(error) { if(comparisonSession === session) $('range-comparison-status').textContent=error.message; }
  finally { session.running=false; if(comparisonSession === session) drawRangeComparison(); }
}
async function undoLastComparison(pid) {
  if (!lastComparisonUndo || lastComparisonUndo.pid !== pid || !(await settleEdits())) return;
  try {
    await api(`/api/projects/${pid}/comparisons/${lastComparisonUndo.id}/undo`,{method:'POST',headers:{'X-Studio-Local':'1'}});
    lastComparisonUndo=null;
    await refresh();
  } catch(error) { alert(error.message); }
}
window.addEventListener('keydown',event=>{if(event.key==='Escape' && comparisonSession && !comparisonSession.running) closeRangeComparison();});
