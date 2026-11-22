/* Local batch creation: project IDs reference user-selected files, never copies. */
let auxRoute = null, batchProjectIds = [], currentBatchId = null, queueRefreshing = false;

function closeAuxScreen() {
  auxRoute = null;
  document.body.classList.remove('aux-visible');
}
function showAuxScreen(route) {
  auxRoute = route;
  document.body.classList.add('home-visible','aux-visible');
  persistRoute(route);
}
function saveLocalState(key, value) { try { window.localStorage?.setItem(key,JSON.stringify(value)); } catch {} }
function readLocalState(key) { try { return JSON.parse(window.localStorage?.getItem(key) || 'null'); } catch { return null; } }

async function openLocalMany() {
  if (busy || !(await settleEdits())) return;
  const button=$('open-local');
  button.disabled=true; button.textContent='Elige archivos en macOS…'; busy=true;
  try {
    const result=await api('/api/projects/local-many',{method:'POST',headers:{'X-Studio-Local':'1'}});
    busy=false;
    if (!result?.projects?.length) return;
    await refresh();
    if (result.errors?.length) alert(`${result.errors.length} archivo(s) no pudieron abrirse. Los demás se conservaron.`);
    const ids=result.projects.map(project=>project.id);
    if (ids.some(id=>!projects.some(project=>project.id===id))) {
      const latest=await api('/api/projects');
      if (Array.isArray(latest)) { projects=latest; renderList(); }
    }
    if (ids.length===1) await select(ids[0]);
    else await openBatchRecipe(ids);
  } catch(error) { alert(error.message); }
  finally { busy=false; button.disabled=false; button.textContent='Abrir archivos o carpeta'; }
}
async function openBatchRecipe(ids) {
  if (!(await settleEdits())) return;
  if (selected && !(await resetWorkspace())) return;
  batchProjectIds=ids; saveLocalState('ss2-batch-projects',ids); selected=null;
  showAuxScreen('batch');
  const selectedProjects=ids.map(id=>projects.find(project=>project.id===id)).filter(Boolean);
  const aux=$('aux-screen');
  aux.innerHTML=`<div class="batch-page"><div class="batch-heading"><button id="batch-back" type="button">‹ Biblioteca</button><strong>Nuevo lote</strong><span>${selectedProjects.length} archivos locales</span></div><div class="batch-columns"><section class="batch-panel"><h2>Episodios detectados</h2><div class="batch-episodes">${selectedProjects.map(project=>{const sources=(project.subtitle_options || []).filter(s=>s.supported&&s.match!==false), recommended=sources.find(s=>s.recommended)||sources[0];return `<label class="batch-episode"><input type="checkbox" data-batch-project="${esc(project.id)}" checked><span>${project.episode ? `E${String(project.episode).padStart(2,'0')}` : ''}</span><span><strong>${esc(project.name)}</strong><small>${recommended ? esc(recommended.label) : 'Sin subtítulos → transcribir'}</small></span></label>`}).join('')}</div></section><section class="batch-panel"><h2>Receta</h2><div class="batch-form"><label>Receta guardada <select id="batch-saved-recipe"><option value="">Nueva receta</option></select></label><label>Nombre <input id="batch-recipe-name" value="Mi receta"></label><label>Fuente preferida <select id="batch-source"><option value="recommended">Subtítulo recomendado</option><option value="english">Inglés si está disponible</option><option value="asr">Transcribir el audio</option></select></label><label>Si no hay subtítulos <select id="batch-asr"><option value="qwen">Qwen3-ASR 1.7B</option><option value="whisper">Whisper large-v3</option></select></label><label>Idioma hablado <select id="batch-spoken"><option value="">Detección automática</option><option value="English">Inglés</option><option value="Romanian">Rumano</option><option value="Spanish">Español</option><option value="Portuguese">Portugués</option><option value="French">Francés</option><option value="Italian">Italiano</option><option value="German">Alemán</option></select></label><label>Traducir a <select id="batch-target"><option value="Spanish">Español</option><option value="English">Inglés</option><option value="Romanian">Rumano</option><option value="Portuguese">Portugués</option><option value="French">Francés</option><option value="Italian">Italiano</option><option value="German">Alemán</option></select></label><label>Modelo de Ollama <select id="batch-model"></select></label><label class="batch-check"><input id="batch-improve" type="checkbox"> Proponer mejoras antes de traducir</label><label class="batch-check"><input id="batch-flags" type="checkbox" checked> Marcar segmentos dudosos</label><label class="batch-check"><input id="batch-autoexport" type="checkbox"> Guardar junto al vídeo al terminar</label><p class="tiny">Las mejoras se revisan y aceptan antes de traducir. Los originales no se copian.</p></div></section></div><div id="batch-status" role="status"></div><div class="batch-footer"><span>La revisión es manual. El resto avanza mientras revisas otro episodio.</span><button id="batch-add" class="primary" type="button" disabled>Añadir a la cola</button></div></div>`;
  $('batch-back').onclick = async()=>{if(await resetWorkspace()) renderList();};
  try {
    const [modelResult,recipeResult]=await Promise.allSettled([api('/api/ollama/models'),api('/api/recipes')]);
    if (auxRoute!=='batch' || $('aux-screen')!==aux) return;
    const models=modelResult.status==='fulfilled' && Array.isArray(modelResult.value) ? modelResult.value : [];
    const recipes=recipeResult.status==='fulfilled' && Array.isArray(recipeResult.value) ? recipeResult.value : [];
    $('batch-model').innerHTML=models.map(m=>`<option value="${esc(m.name)}">${esc(m.name)}</option>`).join('');
    const preferred=models.find(m=>m.name==='qwen3:14b-q8_0');
    if (preferred) $('batch-model').value=preferred.name;
    $('batch-saved-recipe').innerHTML='<option value="">Nueva receta</option>'+recipes.map(r=>`<option value="${esc(r.id)}">${esc(r.name)}</option>`).join('');
    $('batch-saved-recipe').onchange=()=>{const recipe=recipes.find(r=>r.id===$('batch-saved-recipe').value);if(!recipe)return;for(const [id,key] of [['batch-recipe-name','name'],['batch-source','source_pref'],['batch-asr','asr_model'],['batch-spoken','asr_language'],['batch-target','target_language'],['batch-model','translation_model']]) $(id).value=recipe[key] || '';for(const [id,key] of [['batch-improve','improve_before_translate'],['batch-flags','flag_suspicious'],['batch-autoexport','export_when_clean']]) $(id).checked=!!recipe[key];};
    $('batch-add').disabled=!models.length || !selectedProjects.length;
    $('batch-status').textContent=models.length ? '' : 'Instala o inicia un modelo de Ollama antes de añadir el lote.';
    $('batch-add').onclick=async()=>{
      const picked=[...document.querySelectorAll('[data-batch-project]')].filter(el=>el.checked || el.checked===undefined&&el.hasAttribute('checked')).map(el=>el.dataset.batchProject);
      if (!picked.length) { $('batch-status').textContent='Selecciona al menos un episodio.'; return; }
      const config={name:$('batch-recipe-name').value.trim() || 'Mi receta',source_pref:$('batch-source').value,asr_model:$('batch-asr').value,asr_language:$('batch-spoken').value || null,target_language:$('batch-target').value,translation_model:$('batch-model').value,improve_before_translate:$('batch-improve').checked,flag_suspicious:$('batch-flags').checked,export_when_clean:$('batch-autoexport').checked};
      const saved=recipes.find(r=>r.id===$('batch-saved-recipe').value);
      const matches=saved && Object.keys(config).every(key=>config[key]===saved[key]);
      $('batch-add').disabled=true; $('batch-status').textContent='Preparando la cola…';
      try {
        const recipe=matches ? saved : await api('/api/recipes',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Local':'1'},body:JSON.stringify(config)});
        const batch=await api('/api/batches',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Local':'1'},body:JSON.stringify({recipe_id:recipe.id,project_ids:picked})});
        if (batch.enqueue_failed) alert(`${batch.enqueue_failed} episodio(s) no se pudieron enviar; puedes reintentarlos en la cola.`);
        await openBatchQueue(batch.id);
      } catch(error) { if ($('batch-status')) $('batch-status').textContent=error.message; if ($('batch-add')) $('batch-add').disabled=false; }
    };
  } catch(error) { if ($('batch-status')) $('batch-status').textContent=error.message; }
}
async function openBatchQueue(id) {
  if (selected && !(await resetWorkspace())) return;
  currentBatchId=id; saveLocalState('ss2-batch-id',id); selected=null;
  showAuxScreen('queue');
  $('aux-screen').innerHTML='<div class="batch-page">Cargando cola…</div>';
  await refreshBatchQueue();
}
async function refreshBatchQueue() {
  if (auxRoute!=='queue' || !currentBatchId || queueRefreshing) return;
  queueRefreshing=true;
  try { const data=await api(`/api/batches/${currentBatchId}`); if(auxRoute==='queue' && currentBatchId===data.id) renderBatchQueue(data); }
  catch(error) { if(auxRoute==='queue') $('aux-screen').textContent=error.message; }
  finally { queueRefreshing=false; }
}
function renderBatchQueue(batch) {
  const aux=$('aux-screen');
  const stageOrder=['source','process','review','translate','export'];
  const labels={source:'Fuente',process:'Procesar',improve:'Mejorar',review:'Revisar',translate:'Traducir',export:'Exportar',done:'Listo'};
  const cell=(item,stage)=>{const current=item.stage==='improve'?'review':item.stage;const at=stageOrder.indexOf(current), i=stageOrder.indexOf(stage);if(item.status==='done'||i<at)return '✓';if(i>at)return '—';if(item.status==='review'){const flags=item.project.counts?.flagged_open || 0, proposals=item.project.counts?.proposals || 0;return [flags ? `${flags} dudosos` : '',proposals ? `${proposals} propuestas` : ''].filter(Boolean).join(' · ') || 'Listo para continuar';}if(item.status==='failed')return 'Error';if(item.status==='paused')return 'Pausado';if(item.status==='queued')return 'En cola';return stage==='process'||stage==='translate' ? stateName(item.project) : labels[item.stage] || item.stage;};
  aux.innerHTML=`<div class="batch-page"><div class="batch-heading"><button id="queue-back" type="button">‹ Biblioteca</button><strong>Cola</strong><span>${batch.items.filter(i=>i.status==='running').length} en marcha</span><button id="queue-pause" type="button">${batch.paused?'Reanudar cola':'Pausar cola'}</button></div><div class="queue-table"><div class="queue-row queue-head"><span>Ep.</span>${stageOrder.map(s=>`<span>${labels[s]}</span>`).join('')}<span></span></div>${batch.items.map(item=>`<div class="queue-row ${item.status==='review'?'queue-warning':''}"><span>${item.project.episode ? `E${String(item.project.episode).padStart(2,'0')}` : esc(item.project.name)}</span>${stageOrder.map(stage=>`<span>${esc(cell(item,stage))}</span>`).join('')}<span>${item.status==='failed'?`<button type="button" data-queue-retry="${esc(item.id)}">Reintentar</button>`:item.status==='review' && !(item.project.counts?.flagged_open || item.project.counts?.proposals) ? `<button type="button" data-queue-continue="${esc(item.id)}">Continuar</button>` : `<button type="button" data-queue-open="${esc(item.project.id)}">${item.status==='review'?'Revisar':'Abrir'}</button>`}</span>${item.error ? `<small class="queue-error">${esc(item.error)}</small>` : ''}</div>`).join('')}</div><p class="tiny">Las filas resaltadas esperan una revisión. La pausa se aplica al terminar el tramo actual.</p></div>`;
  $('queue-back').onclick=async()=>{if(await resetWorkspace())renderList();};
  $('queue-pause').onclick=async()=>{try{await api(`/api/batches/${batch.id}/${batch.paused?'resume':'pause'}`,{method:'POST',headers:{'X-Studio-Local':'1'}});await refreshBatchQueue();}catch(error){alert(error.message);}};
  aux.querySelectorAll('[data-queue-open]').forEach(button=>button.onclick=()=>select(button.dataset.queueOpen));
  aux.querySelectorAll('[data-queue-continue]').forEach(button=>button.onclick=()=>continueBatchItem(batch.id,button.dataset.queueContinue));
  aux.querySelectorAll('[data-queue-retry]').forEach(button=>button.onclick=async()=>{try{await api(`/api/batches/${batch.id}/items/${button.dataset.queueRetry}/retry`,{method:'POST',headers:{'X-Studio-Local':'1'}});await refreshBatchQueue();}catch(error){alert(error.message);}});
}
async function continueBatchItem(batchId,itemId) {
  if (busy || !(await settleEdits())) return;
  try { const result=await api(`/api/batches/${batchId}/items/${itemId}/continue`,{method:'POST',headers:{'X-Studio-Local':'1'}});if(result.enqueue_failed)throw Error('No se pudo reanudar; vuelve a intentarlo desde la cola.');await openBatchQueue(batchId); }
  catch(error){alert(error.message);}
}
async function batchTaskAction(batch,action) {
  if (busy || !(await settleEdits())) return;
  if (action==='cancel' && !confirm('¿Cancelar este episodio del lote? Se conservarán los segmentos y el vídeo.')) return;
  const path=action==='cancel' ? `/api/batches/${batch.id}/items/${batch.item_id}/cancel` : `/api/batches/${batch.id}/${action}`;
  try { await api(path,{method:'POST',headers:{'X-Studio-Local':'1'}}); await refresh(); }
  catch(error) { alert(error.message); }
}
async function retryBatchItem(batchId,itemId) {
  if (busy || !(await settleEdits())) return;
  try { const result=await api(`/api/batches/${batchId}/items/${itemId}/retry`,{method:'POST',headers:{'X-Studio-Local':'1'}}); if(result.enqueue_failed) throw Error('No se pudo enviar a la cola.'); await refresh(); }
  catch(error) { alert(error.message); }
}
async function restoreAuxRoute(route) {
  if (route==='queue') { const id=readLocalState('ss2-batch-id'); if(id){await openBatchQueue(id);return;} }
  if (route==='batch') { const ids=readLocalState('ss2-batch-projects'); if(Array.isArray(ids)&&ids.length){await openBatchRecipe(ids);return;} }
  closeAuxScreen(); persistRoute('library');
}
$('open-local').onclick=openLocalMany;
