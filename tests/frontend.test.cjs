const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
function setup() {
  const html = fs.readFileSync("frontend/index.html", "utf8");
  const source = fs.existsSync("frontend/app.js")
    ? fs.readFileSync("frontend/app.js", "utf8")
    : html.match(/<script>([\s\S]*)<\/script>/)[1];
  const elements = {};
  const ctx = vm.createContext({
    document: {
      getElementById: (id) => (elements[id] ||= {}),
      querySelectorAll: () => [],
    },
    window: { addEventListener: () => {} },
    console,
    alert: () => {},
    confirm: () => true,
    setInterval: () => {}, clearInterval: () => {},
    setTimeout: () => {},
    fetch: async () => ({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => [],
    }),
  });
  vm.runInContext(fs.readFileSync("frontend/editor-state.js", "utf8"), ctx);
  vm.runInContext(
    source.replace(/refresh\(\);\s*setInterval\(refresh,\s*4000\);/, ""),
    ctx,
  );
  vm.runInContext("renderList=()=>{};renderWorkspace=()=>{};", ctx);
  return ctx;
}
function domSetup() {
  const { parseHTML } = require("linkedom");
  const document = parseHTML(fs.readFileSync("frontend/index.html", "utf8")).document;
  const ctx = vm.createContext({
    document, window: { addEventListener: () => {} }, console,
    alert: () => {}, confirm: () => true, setInterval: () => {}, clearInterval: () => {}, setTimeout: () => {},
    fetch: async () => ({ ok: true, headers: { get: () => "application/json" }, json: async () => [] }),
  });
  for (const script of document.querySelectorAll("script[src]")) {
    const path = `frontend/${script.getAttribute("src").split("?")[0].replace(/^\//, "")}`;
    vm.runInContext(fs.readFileSync(path, "utf8").replace(/refresh\(\);\s*setInterval\(refresh,\s*4000\);/, ""), ctx);
  }
  return ctx;
}
const evaluate = (ctx, script) => vm.runInContext(script, ctx);
const deferred = () => {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
};

test('the library groups episodes and filters projects by review state', () => {
  const c = domSetup();
  evaluate(c, `projects=[
    {id:'e2',name:'Serie.S01E02.mkv',serie:'Serie',season:1,episode:2,state:'ready',counts:{cues:4,untranslated:1,flagged_open:2}},
    {id:'e1',name:'Serie.S01E01.mkv',serie:'Serie',season:1,episode:1,state:'ready',counts:{cues:1,untranslated:0,flagged_open:0}},
    {id:'m',name:'Film.2020.mp4',year:2020,state:'draft',subtitle_options:[]}
  ];renderList()`);
  const home = c.document.getElementById('library-home');
  assert.match(home.textContent, /Serie · Temporada 1/);
  assert.match(home.textContent, /Películas/);
  assert.match(home.textContent, /2 segmentos dudosos/);
  home.querySelector('[data-library-filter="attention"]').click();
  assert.ok(home.querySelector('[data-home-project="e2"]'));
  assert.equal(home.querySelector('[data-home-project="m"]'), null);
});

test('opening a project persists its route and the back action returns to the library', async () => {
  const c = domSetup(), data = {};
  c.window.localStorage = {getItem:key=>data[key],setItem:(key,value)=>data[key]=value};
  c.window.location = {hash:''};
  c.api = async () => ({project:{id:'p',name:'clip',state:'ready',audio_tracks:[]},cues:[]});
  await evaluate(c, `select('p')`);
  assert.equal(data['ss2-route'], 'project:p');
  assert.equal(c.window.location.hash, '#project:p');
  await c.document.getElementById('library-toggle').onclick();
  assert.equal(data['ss2-route'], 'library');
  assert.ok(c.document.body.classList.contains('home-visible'));
});

test('video overlay can switch between original and translated subtitles', () => {
  const c = domSetup();
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'ready',source_kind:'reference',audio_tracks:[]},cues:[{id:'c',position:0,start:0,end:10,original:'Hello',translated:'Hola'}]};selected='p';renderWorkspace();document.getElementById('video').currentTime=1;updateVideoSubtitles()`);
  assert.equal(c.document.getElementById('video-subtitles').textContent, 'Hello');
  c.document.getElementById('overlay-translated').click();
  assert.equal(c.document.getElementById('video-subtitles').textContent, 'Hola');
});

test('voice map colors real amplitudes according to subtitle review state', () => {
  const c = domSetup();
  const html = evaluate(c, `voiceMapMarkup([0,0.25,0.5,1], 0, 4, [{id:'a',start:1,end:2,flag:'repeat',flag_resolved:false},{id:'b',start:2,end:3}], 1.5, null)`);
  assert.match(html, /voice-bar silent/);
  assert.match(html, /voice-bar suspect/);
  assert.match(html, /voice-bar spoken/);
  assert.match(html, /voice-playhead/);
  assert.match(html, /data-voice-cue="a"/);
});

test('review stage filters unresolved cues and leaves translated cues intact', async () => {
  const c = domSetup();
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'ready',source_kind:'reference',audio_tracks:[]},cues:[{id:'a',position:0,start:0,end:1,original:'Uno',translated:'One',flag:'repeat',flag_resolved:false},{id:'b',position:1,start:1,end:2,original:'Dos',translated:'Two'}]};selected='p';renderWorkspace()`);
  assert.equal(c.document.querySelectorAll('[data-stage]').length, 5);
  await c.document.querySelector('[data-stage="review"]').onclick();
  assert.ok(c.document.querySelector('.cue[data-cue="a"]'));
  assert.equal(c.document.querySelector('.cue[data-cue="b"]'), null);
  await c.document.querySelector('[data-cue-filter="all"]').onclick();
  assert.ok(c.document.querySelector('.cue[data-cue="b"]'));
});

test('changing cue filter does not discard invalid unsaved edits', async () => {
  const c=domSetup();
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'ready',source_kind:'reference',audio_tracks:[]},cues:[{id:'a',position:0,start:0,end:1,original:'Uno',translated:''}]};selected='p';renderWorkspace();dirty.add('a')`);
  const row = c.document.querySelector('.cue[data-cue="a"]');
  await c.document.querySelector('[data-cue-filter="sus"]').onclick();
  assert.ok(c.document.querySelector('.cue[data-cue="a"]') === row);
});

test('focus review opens an unresolved cue with editable text and returns to the list', async () => {
  const c=domSetup();
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'ready',source_kind:'reference',audio_tracks:[]},cues:[{id:'a',position:0,start:1,end:2,original:'Hola',translated:'',flag:'repeat',flag_resolved:false}]};selected='p';renderWorkspace()`);
  await c.document.getElementById('start-focus-review').onclick();
  assert.equal(c.document.getElementById('focus-text').value, 'Hola');
  assert.match(c.document.getElementById('focus-review').textContent, /Dudoso 1 de 1/);
  await c.document.getElementById('focus-close').onclick();
  assert.equal(c.document.getElementById('focus-review'), null);
  assert.ok(c.document.querySelector('.video-center #video'));
});

test('focus review marks a cue resolved without deleting it', async () => {
  const c=domSetup(), calls=[];
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'ready',source_kind:'reference',audio_tracks:[]},cues:[{id:'a',position:0,start:1,end:2,original:'Hola',translated:'',flag:'repeat',flag_resolved:false}]};selected='p';renderWorkspace()`);
  c.api=async (url, options) => { const value=JSON.parse(options.body); calls.push({url,value}); return {id:'a',position:0,...value,flag:'repeat'}; };
  await c.document.getElementById('start-focus-review').onclick();
  await c.document.getElementById('focus-accept').onclick();
  assert.equal(calls.length,1);
  assert.equal(calls[0].value.flag_resolved,true);
  assert.match(c.document.getElementById('focus-review').textContent,/Has revisado 1 segmentos/);
  assert.equal(evaluate(c, 'detail.cues.length'),1);
});

test('focus review refuses invalid timings without saving or leaving the segment', async () => {
  const c=domSetup(); let requests=0;
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'ready',source_kind:'reference',audio_tracks:[]},cues:[{id:'a',position:0,start:1,end:2,original:'Hola',translated:'',flag:'repeat',flag_resolved:false}]};selected='p';renderWorkspace()`);
  c.api=async()=>{requests++};
  await c.document.getElementById('start-focus-review').onclick();
  c.document.getElementById('focus-end').value='00:00:00.500';
  await c.document.getElementById('focus-accept').onclick();
  assert.equal(requests,0);
  assert.match(c.document.getElementById('focus-error').textContent,/Revisa los tiempos/);
});

test('export menu checks translations and unresolved review before saving', async () => {
  const c = domSetup();
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'ready',source_kind:'reference',audio_tracks:[]},cues:[{id:'a',position:0,start:1,end:2,original:'Hola',translated:'',flag:'repeat',flag_resolved:false}]};selected='p';renderWorkspace()`);
  c.document.getElementById('export-toggle').click();
  assert.equal(c.document.getElementById('export-menu').hidden,false);
  c.document.getElementById('language').value='es';
  c.document.getElementById('language').onchange();
  assert.match(c.document.getElementById('export-checks').textContent,/1 sin traducir/);
  assert.match(c.document.getElementById('export-checks').textContent,/1 dudosos sin revisar/);
  await c.document.getElementById('export-show-untranslated').onclick();
  assert.ok(c.document.querySelector('.cue[data-cue="a"]'));
  assert.equal(c.document.getElementById('export-menu').hidden,true);
});

test('export uses the project target language rather than labeling every translation Spanish', () => {
  const c=domSetup();
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'ready',source_kind:'reference',target_language:'Romanian',audio_tracks:[]},cues:[{id:'a',position:0,start:1,end:2,original:'Hello',translated:'Bună'}]};selected='p';renderWorkspace()`);
  const option=c.document.querySelector('#language option[value="ro"]');
  assert.ok(option);
  assert.match(option.textContent,/Rumano/);
});

test('range comparison applies only selected translations after review', async () => {
  const c=domSetup(), calls=[];
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'ready',source_kind:'reference',audio_tracks:[]},cues:[{id:'a',position:0,start:0,end:1,original:'Hello',translated:''},{id:'b',position:1,start:1,end:2,original:'World',translated:''}]};selected='p';renderWorkspace()`);
  c.api=async (url,options) => {
    calls.push({url,options});
    if (url.endsWith('/ollama/models')) return [{name:'one'},{name:'two'}];
    if (url.endsWith('/compare-translations')) return {cues:[{cue_id:'a',current:''},{cue_id:'b',current:''}],results:[{model:'one',texts:['Hola','Mundo']},{model:'two',texts:['Buenas','Mundo']}]};
    if (url.endsWith('/apply-comparison')) return {undo_id:'backup'};
    return [];
  };
  c.refresh=async()=>{};
  await evaluate(c, `openRangeComparison('p','a')`);
  c.document.querySelector('#compare-model-a option[value="one"]').setAttribute('selected','');
  c.document.querySelector('#compare-model-b option[value="two"]').setAttribute('selected','');
  await c.document.getElementById('run-range-comparison').onclick();
  const alternative = c.document.querySelector('[data-compare-cue="a"][data-compare-choice="1"]');
  assert.ok(alternative, c.document.getElementById('range-comparison-status').textContent);
  alternative.click();
  await c.document.getElementById('apply-range-comparison').onclick();
  const applied=JSON.parse(calls.find(call=>call.url.endsWith('/apply-comparison')).options.body);
  assert.equal(applied.changes.length,1);
  assert.equal(applied.changes[0].value,'Buenas');
  assert.equal(applied.changes[0].expected.original,'Hello');
});

test('selecting multiple local videos opens a recipe without starting processing', async () => {
  const c=domSetup(), calls=[];
  evaluate(c, `projects=[{id:'a',name:'show.s01e01.mkv',state:'draft',subtitle_options:[]},{id:'b',name:'show.s01e02.mkv',state:'draft',subtitle_options:[]}]`);
  c.api=async (url,options) => { calls.push(url); if(url==='/api/projects/local-many') return {projects:[{id:'a'},{id:'b'}],errors:[]}; if(url==='/api/ollama/models') return [{name:'local'}]; return []; };
  c.refresh=async()=>{};
  await evaluate(c,'openLocalMany()');
  assert.ok(c.document.getElementById('batch-add'));
  assert.match(c.document.getElementById('aux-screen').textContent,/Episodios detectados/);
  assert.ok(!calls.includes('/api/batches'));
});

test('batch queue identifies episodes waiting for review', () => {
  const c=domSetup();
  evaluate(c, `renderBatchQueue({id:'batch',paused:false,items:[{id:'i',stage:'review',status:'review',project:{id:'p',name:'ep.mkv',episode:2,state:'ready',counts:{flagged_open:3}}}]})`);
  assert.match(c.document.getElementById('aux-screen').textContent,/3 dudosos/);
  assert.ok(c.document.querySelector('[data-queue-open="p"]'));
});

test('batch project pause and cancel act on its queue item', async () => {
  const c=domSetup(), calls=[];
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'transcribing',source_kind:'reference',audio_tracks:[],batch:{id:'b',item_id:'i',status:'running'}},cues:[]};selected='p';renderWorkspace()`);
  c.api=async (url,options)=>{calls.push({url,options});return {}};
  c.refresh=async()=>{};
  await c.document.getElementById('task-pause').onclick();
  assert.equal(calls[0].url,'/api/batches/b/pause');
  await c.document.getElementById('task-cancel').onclick();
  assert.equal(calls[1].url,'/api/batches/b/items/i/cancel');
});

test('improvement proposals require explicit acceptance in the editor', () => {
  const c = domSetup();
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'ready',source_kind:'reference',audio_tracks:[]},cues:[{id:'c',position:0,start:0,end:1,original:'hola',translated:'',proposal:'Hola.'}]};selected='p';renderWorkspace()`);
  assert.match(c.document.querySelector('.cue-proposal').textContent, /hola/);
  assert.match(c.document.querySelector('.cue-proposal').textContent, /Hola\./);
  assert.ok(c.document.querySelector('[data-proposal="accept"]'));
  assert.ok(c.document.querySelector('[data-proposal="reject"]'));
  assert.ok(c.document.getElementById('accept-proposals'));
  assert.ok(c.document.querySelector('#language option[value="bilingual"]'));
});

test('completed transcription chunks allow text edits while later chunks run', () => {
  const c = domSetup();
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'transcribing',source_kind:'reference',audio_tracks:[]},cues:[{id:'c',position:0,start:0,end:1,original:'hola',translated:''}]};selected='p';renderWorkspace()`);
  const row = c.document.querySelector('.cue');
  assert.equal(row.querySelector('.original').hasAttribute('readonly'), false);
  assert.equal(row.querySelector('.translated').hasAttribute('readonly'), false);
  assert.equal(row.querySelector('.start').hasAttribute('readonly'), true);
  assert.equal(typeof row.querySelector('.original').onblur, 'function');
});

test('an unresolved repeated segment is visibly marked for review', () => {
  const c = domSetup();
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'ready',source_kind:'reference',audio_tracks:[]},cues:[{id:'c',position:0,start:0,end:1,original:'hola',translated:'',flag:'repeat',flag_resolved:false}]};selected='p';renderWorkspace()`);
  assert.match(c.document.querySelector('.cue').textContent, /repetición/i);
  assert.ok(c.document.querySelector('[data-resolve-flag]'));
});

test('existing episode references hide neighboring episodes and recommend a source', () => {
  const c = domSetup();
  const html = evaluate(c, `sourceChoices({name:'Serie.S01E02.mkv', subtitle_options:[{id:'other',kind:'file',label:'Serie.S01E01.es.srt',supported:true},{id:'embedded',kind:'embedded',label:'Pista 2 · eng',supported:true}]})`);
  assert.match(html, /1 subtítulo de otro episodio oculto/);
  assert.match(html, /value="embedded" checked/);
  assert.doesNotMatch(html, /value="other"/);
});

test('retranscription preserves the original and opens a new ASR draft', async () => {
  const c = domSetup();
  evaluate(c, `detail={project:{id:'p',name:'video.mp4',state:'ready',source_kind:'reference',audio_tracks:[]},cues:[{id:'c',position:0,start:0,end:1,original:'Original',translated:'Traducción'}]};selected='p';renderWorkspace()`);
  assert.ok(c.document.getElementById('retranscribe'));
  let request; c.api=async (url, options)=>{request={url,options};return {id:'new'}};
  c.select=async id=>{c.opened=id}; c.refresh=async()=>{};
  await evaluate(c, "retranscribeProject('p')");
  assert.equal(request.url, '/api/projects/p/retranscribe');
  assert.equal(request.options.headers['X-Studio-Local'], '1');
  assert.equal(c.opened,'new');
  const html = evaluate(c, `sourceChoices({prefer_asr:true,subtitle_options:[{id:'s',label:'sub.srt',supported:true}]})`);
  assert.match(html, /value="asr" checked/);
});

test('new transcription explains preservation and retains language and model', () => {
  const c=domSetup();
  evaluate(c, `detail={project:{id:'p',name:'clip',state:'draft',source_kind:'reference',audio_tracks:[],prefer_asr:true,asr_language:'Romanian',asr_model:'whisper'},cues:[]};selected='p';renderWorkspace()`);
  assert.match(c.document.getElementById('project-content').textContent,/Nueva transcripción/);
  assert.match(c.document.getElementById('project-content').textContent,/anterior/);
  assert.equal(c.document.getElementById('asr-model').value,'whisper');
  assert.equal(c.document.getElementById('asr-language').value,'Romanian');
});

test("every element app.js binds at load exists in index.html", () => {
  const c = domSetup();
  for (const id of ["open-local", "show-trash", "clear-library", "restore-library", "projects", "workspace"])
    assert.ok(c.document.getElementById(id), `falta #${id}`);
});
test("the shell keeps only video and subtitles as permanent chrome", () => {
  const c = domSetup(), html = c.document.documentElement.innerHTML;
  assert.equal(c.document.querySelector("h1"), null);
  assert.ok(!html.includes("Qwen3-ASR · MLX · Ollama"));
  assert.ok(!html.includes("sin copiarlos ni enviarlos a Internet"));
  assert.ok(c.document.querySelector(".badge"));
  assert.ok(c.document.getElementById("library-toggle"));
});
test("the layout is not capped at a fixed width", () => {
  assert.ok(!/max-width:\s*1450px/.test(fs.readFileSync("frontend/index.html", "utf8")));
});
test("the project header shares the one chrome band", () => {
  const c = domSetup(), header = c.document.getElementById("project-header");
  assert.ok(header && c.document.querySelector(".topbar #project-header"));
  assert.equal(c.document.getElementById("workspace").querySelector("#project-header"), null);
});
test("each project carries its own remove control", () => {
  const c=domSetup(); evaluate(c,"projects=[{id:'a',name:'a.mkv',state:'ready',progress:100}];renderList()");
  assert.ok(c.document.querySelector('.project[data-id="a"] [data-action="remove"]'));
});
test("an active project offers no remove control", () => {
  const c=domSetup(); evaluate(c,"projects=[{id:'a',name:'a.mkv',state:'translating',progress:20}];renderList()");
  assert.equal(c.document.querySelector('.project[data-id="a"] [data-action="remove"]'),null);
});
test("removing a project other than the open one keeps the workspace", async () => {
  const c=domSetup(); let reset=false; c.resetWorkspace=async()=>{reset=true;return true}; c.api=async()=>({ok:true});
  evaluate(c,"selected='a'"); await evaluate(c,"removeProject('b')"); assert.equal(reset,false);
});
test("collapsing the library survives a list re-render", () => {
  const c=domSetup(); evaluate(c,"projects=[{id:'a',name:'a.mkv',state:'ready',progress:100}];renderList()");
  assert.ok(c.document.body.classList.contains('library-collapsed')); evaluate(c,'toggleLibrary();renderList()');
  assert.equal(c.document.body.classList.contains('library-collapsed'),false);
});
test("clicking outside the library closes it, while clicking inside keeps it open", () => {
  const c = domSetup(), d = c.document;
  evaluate(c, "toggleLibrary()");
  d.querySelector('.library').dispatchEvent(new d.defaultView.Event('click', {bubbles:true}));
  assert.equal(d.body.classList.contains('library-collapsed'), false);
  d.getElementById('workspace').dispatchEvent(new d.defaultView.Event('click', {bubbles:true}));
  assert.equal(d.body.classList.contains('library-collapsed'), true);
  assert.equal(d.getElementById('library-toggle').getAttribute('aria-expanded'), 'false');
});
test("the workspace header no longer carries the remove button", () => {
  const c=domSetup(); evaluate(c,"detail={project:{id:'a',name:'a.mkv',state:'ready',progress:100,source_kind:'reference'},cues:[{id:'1',start:1,end:2,original:'hi',translated:''}]};renderWorkspace();");
  assert.equal(c.document.getElementById('project-remove'),null); assert.ok(c.document.querySelector('.workspace-split'));
});
test("neither the player nor the editor is capped at a fixed height", () => {
  const css=fs.readFileSync('frontend/index.html','utf8'); assert.ok(!/max-height:\s*410px/.test(css)); assert.ok(!/max-height:\s*64vh/.test(css));
});
test('workspace keeps the player and selected entry inside the viewport', () => {
  const css=fs.readFileSync('frontend/index.html','utf8');
  assert.match(css,/\.workspace-left\s*\{[^}]*overflow\s*:\s*hidden/);
  assert.match(css,/\.video-center\s*\{[^}]*flex\s*:\s*1\s+1\s+0/);
  assert.match(css,/\.editor\s*\{[^}]*overflow\s*:\s*auto/);
});
test("the right cell holds the list and nothing else", () => {
  const c=domSetup(); evaluate(c,"detail={project:{id:'a',name:'a.mkv',state:'ready',progress:100},cues:[{id:'1',start:1,end:2,original:'hi',translated:''}]};renderWorkspace();");
  const right=c.document.getElementById('project-content'); assert.ok(right.querySelector('#editor')); assert.equal(right.querySelector('#save-status'),null); assert.ok(c.document.getElementById('global-editor-bar').querySelector('#undo-edit'));
});
test("nothing but the video shares the overlay's positioned ancestor", () => {
  const c=domSetup(); evaluate(c,"detail={project:{id:'a',name:'a.mkv',state:'ready',progress:100,audio_tracks:[{index:1,label:'audio'}]},cues:[{id:'1',start:1,end:2,original:'hi',translated:''}]};renderWorkspace();");
  const frame=c.document.getElementById('video-frame'); assert.ok(frame.querySelector('#video-subtitles')); assert.equal(frame.querySelector('#audio-controls'),null);
});
test("workspace modes preserve editing and lock active or trashed projects", () => {
  const c=domSetup();
  assert.equal(evaluate(c,"workspaceMode({state:'ready',action:'view'},[{id:'1'}],false)"),'editable');
  assert.equal(evaluate(c,"workspaceMode({state:'translating'},[{id:'1'}],false)"),'locked');
  assert.equal(evaluate(c,"workspaceMode({state:'ready'},[{id:'1'}],true)"),'locked');
  assert.equal(evaluate(c,"defaultExportLanguage([{translated:''}])"),'original');
  assert.equal(evaluate(c,"defaultExportLanguage([{translated:'hola'}])"),'es');
});
test('task feedback reports real saved progress and avoids invented percentages', () => {
  const c=domSetup(), doc=c.document;
  evaluate(c, `detail={project:{id:'a',name:'clip',state:'transcribing',progress:10,task_progress:{processed_seconds:330}},cues:[]};selected='a';renderWorkspace()`);
  assert.match(doc.getElementById('workspace-controls').textContent,/00:05:30/);
  assert.doesNotMatch(doc.getElementById('workspace-controls').textContent,/10%/);
  evaluate(c, `detail.project.state='translating';detail.project.task_progress={done:2,total:8};renderWorkspace()`);
  assert.match(doc.getElementById('workspace-controls').textContent,/2 de 8/);
  assert.match(doc.getElementById('workspace-controls').textContent,/25%/);
  evaluate(c, `detail.project.state='improving';detail.project.progress=42;detail.project.task_progress={percent:42};renderWorkspace()`);
  assert.match(doc.getElementById('workspace-controls').textContent,/42%/);
});
test('transcription percentage uses media duration and queue is indeterminate', () => {
  const c=domSetup();
  const progress=evaluate(c, `taskProgress({state:'transcribing',task_progress:{processed_seconds:30,completed:false}},120)`);
  assert.equal(progress.percent,25);
  assert.match(progress.label,/00:00:30 de 00:02:00/);
  assert.equal(evaluate(c, `taskProgress({state:'transcribing',task_progress:{processed_seconds:120,completed:false}},120).percent`),99);
  assert.equal(evaluate(c, `taskProgress({state:'queued'},120).percent`),null);
});
test('task controls offer pause, cancel and resume without discarding data', async () => {
  const c=domSetup(), doc=c.document; let calls=[];
  c.api=async (url,opts)=>{calls.push([url,opts]);return {state:'pausing'}};
  c.select=async()=>{}; c.refresh=async()=>{};
  evaluate(c, `detail={project:{id:'a',name:'clip',state:'transcribing',task_progress:{processed_seconds:30}},cues:[]};selected='a';renderWorkspace()`);
  assert.ok(doc.getElementById('task-pause'));
  assert.ok(doc.getElementById('task-cancel'));
  await evaluate(c,"taskAction('a','pause')");
  assert.equal(calls[0][0],'/api/projects/a/pause');
  assert.equal(calls[0][1].headers['X-Studio-Local'],'1');
  evaluate(c,`detail.project.state='pausing';renderWorkspace()`);
  assert.match(doc.getElementById('task-progress').textContent,/lote|tramo/i);
  evaluate(c,`detail.project.state='paused';renderWorkspace()`);
  assert.ok(doc.getElementById('task-resume'));
  assert.ok(doc.getElementById('task-cancel'));
});
test('interrupted improvement offers revert without retrying the wrong operation', () => {
  const c=domSetup(), doc=c.document;
  evaluate(c, `detail={project:{id:'a',name:'clip',state:'failed',error:'Mejora incompleta: detenida.',can_undo_improvement:true},cues:[{id:'c',start:0,end:1,original:'texto',translated:''}]};selected='a';renderWorkspace()`);
  assert.ok(!doc.getElementById('retry'));
  assert.ok(doc.getElementById('undo-improvement'));
});
test("subtitle sources are grouped and unsupported image tracks are counted", () => {
  const c=domSetup(), opts=[{id:'1',kind:'embedded',label:'Pista',supported:true},{id:'2',kind:'embedded',label:'PGS',supported:false},{id:'3',kind:'file',label:'movie.en.srt',supported:true},{id:'4',kind:'file',label:'Subs/English.srt',supported:true}];
  const result=JSON.parse(evaluate(c,`JSON.stringify(groupSources(${JSON.stringify(opts)}))`));
  assert.deepEqual(result.groups.map(x=>x.title),['Pistas del vídeo','Junto al vídeo','Carpeta de subtítulos']);
  assert.equal(result.hidden,1);
});
test("a video with only image subtitles explains OCR and offers ASR", () => {
  const c=domSetup(); evaluate(c,"detail={project:{id:'a',name:'a.mkv',state:'draft',subtitle_options:[{id:'pgs',kind:'embedded',label:'PGS',supported:false}]},cues:[]};renderWorkspace()");
  assert.match(c.document.getElementById('workspace').textContent,/1 pista de imagen oculta.*OCR/);
  assert.equal(c.document.getElementById('subtitle-action'),null);
  assert.ok(c.document.querySelector('input[value="asr"]'));
});
test("ASR language selection offers Romanian and sends it with the task", async () => {
  const c=editorSetup(); evaluate(c,"detail={project:{id:'a',name:'test',state:'draft',audio_tracks:[],subtitle_options:[]},cues:[]};renderWorkspace()");
  const doc=c.document, input=doc.getElementById('asr-language');
  assert.ok(input.querySelector('option[value="Romanian"]'));
  input.querySelectorAll('option').forEach(option=>option.removeAttribute('selected'));
  input.querySelector('option[value="Romanian"]').setAttribute('selected','');
  const calls=[];c.api=async (url,opts)=>{calls.push([url,opts]);return opts?.method==='POST'?{id:'a'}:{project:{id:'a',name:'test',state:'queued'},cues:[]};};
  await evaluate(c,"startProject('a')");
  assert.equal(JSON.parse(calls[0][1].body).asr_language,'Romanian');
});
test("ASR model selector sends the chosen model without starting downloads", async () => {
  const c=editorSetup(); evaluate(c,"detail={project:{id:'a',name:'test',state:'draft',audio_tracks:[],subtitle_options:[]},cues:[]};renderWorkspace()");
  const selector=c.document.getElementById('asr-model');
  assert.ok(selector.querySelector('option[value="whisper"]'));
  selector.querySelectorAll('option').forEach(o=>o.removeAttribute('selected'));
  selector.querySelector('option[value="whisper"]').setAttribute('selected','');
  const calls=[];c.api=async (url,opts)=>{calls.push([url,opts]);return opts?.method==='POST'?{id:'a'}:{project:{id:'a',name:'test',state:'queued'},cues:[]};};
  await evaluate(c,"startProject('a')");
  assert.equal(JSON.parse(calls[0][1].body).asr_model,'whisper');
  assert.ok(calls.every(([url])=>!url.includes('/download')));
});
test("model comparison uses the current video position without editing cues", async () => {
  const c=editorSetup(), doc=c.document;
  doc.getElementById('video').currentTime=42.8;
  const calls=[];
  c.api=async (url,opts)=>{ calls.push([url,opts]);return {results:{qwen:{srt:'Qwen text',elapsed_seconds:1},whisper:{srt:'Whisper text',elapsed_seconds:2}}}; };
  await evaluate(c,"compareModels('a')");
  assert.equal(calls[0][0],'/api/projects/a/compare-models');
  assert.equal(JSON.parse(calls[0][1].body).segment_start,42);
  assert.match(doc.getElementById('compare-result').textContent,/Qwen text/);
  assert.match(doc.getElementById('compare-result').textContent,/Whisper text/);
  assert.equal(evaluate(c,"detail.cues[0].original"),'Hello');
});
test("deleting a model asks before touching the shared cache", async () => {
  const c=editorSetup(); const calls=[]; c.api=async (url,opts)=>{calls.push([url,opts]);return url==='/api/models'?[]:{freed_bytes:1};};
  c.confirm=()=>false; await evaluate(c,"changeModelFiles('whisper', true)"); assert.equal(calls.length,0);
  c.confirm=()=>true; await evaluate(c,"changeModelFiles('whisper', true)");
  assert.equal(calls[0][0],'/api/models/whisper');
  assert.equal(calls[0][1].method,'DELETE');
  assert.equal(calls[0][1].headers['X-Studio-Local'],'1');
});
test("audio controls fold after subtitle segments become available", () => {
  const c=domSetup(); evaluate(c,"detail={project:{id:'a',name:'test',state:'draft',audio_tracks:[{index:1,label:'audio'}],subtitle_options:[]},cues:[]};renderWorkspace()");
  assert.ok(c.document.querySelector('#audio-controls[open]'));
  evaluate(c,"detail.project.state='ready';detail.cues=[{id:'1',start:1,end:2,original:'text',translated:''}];renderWorkspace()");
  assert.equal(c.document.querySelector('#audio-controls[open]'),null);
});

test("time formatter carries rounded milliseconds into next minute", () => {
  const c = setup();
  assert.equal(evaluate(c, "time(59.9996)"), "00:01:00.000");
});
test("invalid timestamp fields are rejected", () => {
  const c = setup();
  for (const value of ["00:99:00", "00:00:-1", "00::01", "-1:00:00"])
    assert.ok(
      Number.isNaN(evaluate(c, `secs(${JSON.stringify(value)})`)),
      value,
    );
});
test("slow selection cannot replace a newer selected project", async () => {
  const c = setup(),
    a = deferred(),
    b = deferred();
  c.api = (url) => (url.endsWith("/a") ? a.promise : b.promise);
  const first = evaluate(c, "select('a')"),
    second = evaluate(c, "select('b')");
  b.resolve({ project: { id: "b" }, cues: [] });
  await second;
  a.resolve({ project: { id: "a" }, cues: [] });
  await first;
  assert.equal(evaluate(c, "detail.project.id"), "b");
});
test("polling never replaces edits started while request was in flight", async () => {
  const c = setup(),
    response = deferred(),
    started = deferred();
  c.api = async (url) => {
    if (url === "/api/projects") return [];
    started.resolve();
    return response.promise;
  };
  evaluate(c, "selected='a';detail={project:{id:'a',state:'ready'},cues:[]};");
  const refreshing = evaluate(c, "refresh()");
  await started.promise;
  evaluate(c, "dirty.add('cue');");
  response.resolve({ project: { id: "a", state: "failed" }, cues: [] });
  await refreshing;
  assert.equal(evaluate(c, "detail.project.state"), "ready");
});

test("preview keeps the same media element across processing updates", () => {
  const c = domSetup(), document = c.document;
  evaluate(
    c,
    "detail={project:{id:'a',name:'movie.mp4',state:'transcribing',progress:10},cues:[]};renderWorkspace();",
  );
  const video = document.getElementById("video");
  video.currentTime = 20;
  for (const state of ["transcribing", "translating", "ready"]) {
    evaluate(
      c,
      `detail.project.state=${JSON.stringify(state)};renderWorkspace();`,
    );
    assert.ok(
      document.getElementById("video") === video,
      "player node was replaced",
    );
    assert.equal(video.currentTime, 20);
  }
});

test("draft source choices retain selection during unchanged polling", async () => {
  const c = domSetup();
  const data = {
    project: {
      id: "a",
      name: "movie.mp4",
      state: "draft",
      progress: 0,
      source_kind: "reference",
      subtitle_options: [
        { id: "srt", label: "Subs/English.srt", kind: "file", supported: true },
        { id: "pgs", label: "PGS", kind: "embedded", supported: false },
      ],
    },
    cues: [],
  };
  c.data = data;
  evaluate(c, "selected='a';detail=data;renderWorkspace();");
  const choices = c.document.getElementById("subtitle-source");
  assert.ok(choices.textContent.includes("Subs/English.srt"));
  assert.equal(choices.querySelector('input[value="pgs"]'), null);
  assert.match(choices.textContent, /OCR/);
  c.api = async (url) =>
    url === "/api/projects" ? [] : JSON.parse(JSON.stringify(data));
  await evaluate(c, "refresh()");
  assert.ok(c.document.getElementById("subtitle-source") === choices);
});

function editorSetup() {
  const c = domSetup();
  evaluate(
    c,
    "selected='a';detail={project:{id:'a',name:'test',state:'ready',progress:100},cues:[{id:'c1',position:0,start:0,end:2,original:'Hello',translated:''}]};renderWorkspace();",
  );
  return c;
}
test('improvement lists installed models and sends the selection', async () => {
  const c=editorSetup(), doc=c.document; let calls=[];
  c.api=async (url,opts)=>{calls.push([url,opts]); if(url==='/api/ollama/models') return [{name:'one:latest'}, {name:'two:latest'}]; return {};};
  c.select=async()=>{}; c.refresh=async()=>{};
  await evaluate(c, "loadImprovementModels('a')");
  const dropdown=doc.getElementById('improve-model');
  assert.equal(dropdown.querySelectorAll('option').length,3);
  dropdown.querySelector('option[value="two:latest"]').setAttribute('selected','');
  await evaluate(c, "improveText('a')");
  assert.equal(JSON.parse(calls.find(([url])=>url.endsWith('/improve'))[1].body).model,'two:latest');
});
test('individual translation is available while transcribing and supports undo', async () => {
  const c=editorSetup();
  evaluate(c, "detail.project.state='transcribing';renderWorkspace()");
  assert.ok(c.document.querySelector('.cue-translate'));
  assert.ok(!c.document.querySelector('.original').hasAttribute('readonly'));
  let calls=[];
  c.api=async (url,opts)=>{calls.push([url,opts]); if(url.endsWith('/translate')) return {text:'Hola'}; return {id:'c1',position:0,...JSON.parse(opts.body)};};
  await evaluate(c, "translateCue('a','c1','forward','Spanish')");
  await evaluate(c, 'cueEditor.flush()');
  assert.equal(evaluate(c,"cueEditor.get('c1').translated"),'Hola');
  evaluate(c, "historyEdit('undo')");
  await evaluate(c, 'cueEditor.flush()');
  assert.equal(evaluate(c,"cueEditor.get('c1').translated"),'');
});
test('reverse translation respects the selected language and confirms replacement', async () => {
  const c=editorSetup(); let calls=[];
  c.api=async (url,opts)=>{calls.push([url,opts]); if(url.endsWith('/translate')) return {text:'Bună'}; return {id:'c1',position:0,...JSON.parse(opts.body)};};
  evaluate(c,"cueEditor.rows.get('c1').translated='Hola';cueEditor.confirmed.get('c1').translated='Hola'");
  c.confirm=()=>false; await evaluate(c,"translateCue('a','c1','backward','Romanian')");
  assert.equal(calls.length,0);
  c.confirm=()=>true; await evaluate(c,"translateCue('a','c1','backward','Romanian')");
  assert.equal(JSON.parse(calls[0][1].body).target_language,'Romanian');
  assert.equal(JSON.parse(calls[0][1].body).direction,'backward');
  assert.equal(evaluate(c,"cueEditor.get('c1').original"),'Bună');
});
test('model comparison proposes alternatives without changing the cue until chosen', async () => {
  const c=editorSetup(); let calls=[];
  c.api=async (url,opts)=>{calls.push([url,opts]); if(url==='/api/ollama/models') return [{name:'a'},{name:'b'}]; if(url.endsWith('/compare-translations')) return {source:'Hello',results:[{model:'a',text:'Hola'},{model:'b',text:'Buenas'}]}; return {id:'c1',position:0,...JSON.parse(opts.body)};};
  await evaluate(c,"loadCueComparison('c1')");
  const row=c.document.querySelector('.cue');
  assert.equal(row.querySelectorAll('.compare-model option').length,4);
  row.querySelector('.compare-direction option[value="forward"]').setAttribute('selected','');
  assert.equal(row.querySelector('.compare-direction').value, 'forward');
  row.querySelector('.cue-language option[value="Spanish"]').setAttribute('selected','');
  await evaluate(c,"compareCueTranslations('a','c1')");
  assert.equal(evaluate(c,"cueEditor.get('c1').translated"),'');
  assert.match(row.querySelector('.cue-compare-results').textContent,/Buenas/);
  await row.querySelector('[data-use-result="1"]').onclick();
  await evaluate(c,'cueEditor.flush()');
  assert.equal(evaluate(c,"cueEditor.get('c1').translated"),'Buenas');
  assert.equal(JSON.parse(calls.find(([url])=>url.endsWith('/translation-language'))[1].body).target_language,'Spanish');
  assert.equal(evaluate(c,'detail.project.translation_language_known'),true);
});

test('contextual translation options close when clicking outside', () => {
  const c=editorSetup(), doc=c.document, menu=doc.querySelector('.cue-translate');
  menu.open=true;
  doc.body.dispatchEvent(new doc.defaultView.Event('click', {bubbles:true}));
  assert.equal(menu.open,false);
});

test('native video volume controls the selected audio track', () => {
  const c=editorSetup(), doc=c.document;
  let zeroed=false;
  c.window.AudioContext=class {createMediaElementSource(){return {connect(){}}} createGain(){return {gain:{set value(v){zeroed=v===0}},connect(){}}} get destination(){return {}}};
  doc.getElementById('workspace').innerHTML='';
  evaluate(c,"detail={project:{id:'a',name:'x',state:'draft',audio_tracks:[{index:2,label:'Audio'}],subtitle_options:[]},cues:[]};renderWorkspace()");
  const video=doc.getElementById('video'), audio=doc.getElementById('player-audio');
  video.volume=0.4; video.muted=false; video.onvolumechange();
  assert.ok(zeroed); assert.equal(audio.volume,0.4); assert.equal(audio.muted,false); assert.equal(video.muted,false);
  video.muted=true; video.onvolumechange(); assert.equal(audio.muted,true);
});
test("editor has five columns and saves on blur; undo restores saved value", async () => {
  const c = editorSetup(),
    doc = c.document;
  assert.equal(doc.querySelectorAll("th").length, 5);
  assert.equal(doc.querySelector(".savebtn"), null);
  const saved = [];
  c.api = async (url, opts) => {
    const value = JSON.parse(opts.body);
    saved.push(value);
    return { id: "c1", position: 0, ...value };
  };
  const field = doc.querySelector(".translated");
  field.value = "Hola";
  field.oninput();
  assert.equal(saved.length, 0);
  field.onblur();
  await evaluate(c, "cueEditor.flush()");
  assert.equal(saved.at(-1).translated, "Hola");
  assert.ok(doc.querySelector(".translated") === field);
  doc.getElementById("undo-edit").onclick();
  await evaluate(c, "cueEditor.flush()");
  assert.equal(field.value, "");
  assert.equal(saved.at(-1).translated, "");
});
test("invalid timing stays visible and unsaved until corrected", async () => {
  const c = editorSetup();
  let saves = 0;
  c.api = async (url, opts) => {
    saves++;
    return { id: "c1", ...JSON.parse(opts.body) };
  };
  const field = c.document.querySelector(".start");
  field.value = "00:00:03.000";
  field.oninput();
  field.onblur();
  assert.equal(saves, 0);
  assert.equal(field.getAttribute("aria-invalid"), "true");
  assert.equal(evaluate(c, "dirty.size"), 1);
  field.value = "00:00:01.000";
  field.oninput();
  field.onblur();
  await evaluate(c, "cueEditor.flush()");
  assert.equal(saves, 1);
  assert.equal(field.getAttribute("aria-invalid"), null);
});

test("switching project while saving never drops a later edit", async () => {
  const c = editorSetup(),
    gate = deferred();
  c.api = async (url, opts) => {
    if (opts?.method === "PUT") {
      await gate.promise;
      return { id: "c1", position: 0, ...JSON.parse(opts.body) };
    }
    return { project: { id: "b", name: "other", state: "ready" }, cues: [] };
  };
  const first = c.document.querySelector(".translated");
  first.value = "Primero";
  first.oninput();
  first.onblur();
  const switching = evaluate(c, "select('b')");
  const next = c.document.querySelector(".original");
  next.value = "Later unsaved edit";
  next.oninput();
  gate.resolve();
  await switching;
  assert.equal(evaluate(c, "selected"), "a");
  assert.equal(next.value, "Later unsaved edit");
});
test("new server data replaces an idle editor snapshot", () => {
  const c = editorSetup();
  evaluate(c, "detail.cues[0].original='Server correction';renderWorkspace();");
  assert.equal(
    c.document.querySelector(".original").value,
    "Server correction",
  );
});

test("segments remain visible and read-only during translation and improvement", () => {
  const c = editorSetup(),
    doc = c.document;
  for (const state of ["translating", "improving"]) {
    evaluate(
      c,
      `detail.project.state=${JSON.stringify(state)};renderWorkspace();`,
    );
    assert.equal(doc.querySelector(".original").value, "Hello");
    assert.ok(doc.querySelector(".original").hasAttribute("readonly"));
    assert.ok(doc.querySelector(".start").hasAttribute("readonly"));
  }
});
test("draft exposes audio tracks alongside existing subtitles", () => {
  const c = editorSetup();
  c.document.getElementById("workspace").innerHTML = "";
  evaluate(
    c,
    "detail={project:{id:'a',name:'test',state:'draft',audio_tracks:[{index:2,label:'Pista 2 · eng'},{index:3,label:'Pista 3 · spa'}],subtitle_options:[{id:'s',kind:'embedded',label:'Pista texto',supported:true}]},cues:[]};renderWorkspace();",
  );
  assert.equal(c.document.querySelectorAll("#audio-track option").length, 2);
  assert.ok(c.document.querySelector('#subtitle-source input[value="s"]'));
});

test("draft in trash must be restored before it can start", () => {
  const c = editorSetup();
  evaluate(
    c,
    "viewingTrash=true;detail={project:{id:'a',name:'test',state:'draft',subtitle_options:[]},cues:[]};renderWorkspace();",
  );
  assert.equal(c.document.querySelector("#start-project"), null);
  assert.match(
    c.document.getElementById("project-content").textContent,
    /Restaura/,
  );
});

test("focusing a subtitle seeks to mark-in without autoplay", () => {
  const c = editorSetup(),
    doc = c.document;
  const video = doc.getElementById("video"),
    row = doc.querySelector("tr.cue");
  row.dataset.start = "12.5";
  let plays = 0;
  video.play = () => {
    plays++;
  };
  video.currentTime = 0;
  row.onfocusin({ target: row.querySelector(".original") });
  assert.equal(video.currentTime, 12.5);
  assert.equal(plays, 0);
  video.currentTime = 14;
  row.onfocusin({ target: row.querySelector(".translated") });
  assert.equal(video.currentTime, 14);
  row.onclick({ target: row.querySelector(".cue-number") });
  assert.equal(video.currentTime, 12.5);
});

test("clicking inside a subtitle field seeks to that row", () => {
  const c = editorSetup(), doc = c.document, row = doc.querySelector('tr.cue'), video = doc.getElementById('video');
  row.dataset.start = '23.5';
  video.currentTime = 0;
  row.onclick({target: row.querySelector('.original')});
  assert.equal(video.currentTime, 23.5);
});

test("subtitle source selection shows text and ignores slower previous response", async () => {
  const c = editorSetup(),
    a = deferred(),
    b = deferred();
  evaluate(
    c,
    "detail={project:{id:'a',name:'test',state:'draft',audio_tracks:[],subtitle_options:[{id:'s1',kind:'embedded',label:'1',supported:true},{id:'s2',kind:'embedded',label:'2',supported:true}]},cues:[]};renderWorkspace();",
  );
  const select = c.document.getElementById("subtitle-source");
  c.api = (url) => (url.includes("s1") ? a.promise : b.promise);
  const options = select.querySelectorAll("input");
  options.forEach((o) => { o.checked = false; });
  select.querySelector('input[value="s1"]').checked = true;
  const first = select.onchange();
  select.querySelector('input[value="s1"]').checked = false;
  select.querySelector('input[value="s2"]').checked = true;
  const second = select.onchange();
  b.resolve({ cues: [{ start: 1, end: 2, original: "Newest track" }] });
  await second;
  a.resolve({ cues: [{ start: 1, end: 2, original: "Stale track" }] });
  await first;
  assert.match(
    c.document.getElementById("subtitle-preview").textContent,
    /Newest track/,
  );
  assert.doesNotMatch(
    c.document.getElementById("subtitle-preview").textContent,
    /Stale track/,
  );
});

test("returning to same subtitle after leaving it seeks again", () => {
  const c = editorSetup(),
    doc = c.document,
    row = doc.querySelector("tr.cue"),
    video = doc.getElementById("video");
  row.dataset.start = "7";
  video.currentTime = 0;
  row.onfocusin({ target: row.querySelector(".original") });
  assert.equal(video.currentTime, 7);
  row.onfocusout({ relatedTarget: video });
  video.currentTime = 20;
  row.onfocusin({ target: row.querySelector(".original") });
  assert.equal(video.currentTime, 7);
});

test("preview displays all cues without starting a project", async () => {
  const c=editorSetup(); evaluate(c,"detail={project:{id:'a',name:'test',state:'draft',subtitle_options:[{id:'s1',kind:'embedded',label:'1',supported:true}]},cues:[]};renderWorkspace()");
  const doc=c.document, source=doc.getElementById('subtitle-source');
  source.querySelector('input[value="s1"]').checked=true;
  const calls=[]; c.api=async (url,opts)=>{calls.push([url,opts]);return {cues:Array.from({length:12},(_,i)=>({start:i,end:i+1,original:'Line '+i}))}};
  await source.onchange(); assert.equal(doc.querySelectorAll('#subtitle-preview .cue').length,12);
  assert.ok(calls.every(([url,opts])=>!opts || opts.method!=='POST'));
  assert.equal(doc.querySelectorAll('#subtitle-preview textarea.original')[11].value,'Line 11');
  assert.equal(doc.getElementById('subtitle-action'),null);
});

test('choosing a subtitle previews its first line without starting playback', async () => {
  const c=editorSetup();
  evaluate(c, `detail={project:{id:'a',name:'test',state:'draft',subtitle_options:[{id:'s1',kind:'embedded',label:'Pista 1',supported:true}]},cues:[]};renderWorkspace()`);
  const doc=c.document, source=doc.getElementById('subtitle-source'), video=doc.getElementById('video');
  source.querySelector('input[value="s1"]').checked=true;
  video.currentTime=0;
  c.api=async()=>({cues:[{start:15,end:17,original:'Primera línea'}]});
  await source.onchange();
  assert.equal(video.currentTime,15);
  assert.equal(doc.getElementById('video-subtitles').textContent,'Primera línea');
  assert.ok(!doc.getElementById('subtitle-preview').hidden);
});

test('choosing a subtitle keeps an existing playback position', async () => {
  const c=editorSetup();
  evaluate(c, `detail={project:{id:'a',name:'test',state:'draft',subtitle_options:[{id:'s1',kind:'file',label:'test.srt',supported:true}]},cues:[]};renderWorkspace()`);
  const doc=c.document, source=doc.getElementById('subtitle-source'), video=doc.getElementById('video');
  source.querySelector('input[value="s1"]').checked=true;
  video.currentTime=45;
  c.api=async()=>({cues:[{start:15,end:17,original:'Primera línea'}]});
  await source.onchange();
  assert.equal(video.currentTime,45);
});

test('choosing a subtitle does not interrupt playback at the beginning', async () => {
  const c=editorSetup();
  evaluate(c, `detail={project:{id:'a',name:'test',state:'draft',subtitle_options:[{id:'s1',kind:'file',label:'test.srt',supported:true}]},cues:[]};renderWorkspace()`);
  const doc=c.document, source=doc.getElementById('subtitle-source'), video=doc.getElementById('video');
  source.querySelector('input[value="s1"]').checked=true;
  video.currentTime=0;
  Object.defineProperty(video,'paused',{value:false,configurable:true});
  c.api=async()=>({cues:[{start:15,end:17,original:'Primera línea'}]});
  await source.onchange();
  assert.equal(video.currentTime,0);
});

test("existing subtitles use the same time and text columns as the editor", async () => {
  const c = editorSetup();
  evaluate(c, "detail={project:{id:'a',name:'test',state:'draft',audio_tracks:[],subtitle_options:[{id:'s1',kind:'embedded',label:'1',supported:true}]},cues:[]};renderWorkspace();");
  const source = c.document.getElementById('subtitle-source');
  source.querySelector('input[value="s1"]').checked=true;
  c.api = async () => ({cues:[{start:2,end:3,original:'Text',translated:''}]});
  await source.onchange();
  assert.deepEqual([...c.document.querySelectorAll('#subtitle-preview th')].map(x => x.textContent), ['#','mark-in','mark-out','sub original (o transcripción)','traducción']);
  assert.ok(c.document.querySelector('#subtitle-preview textarea.original').hasAttribute('readonly'));
});

test("audio track selection belongs to the video player and follows playback", () => {
  const c = editorSetup();
  c.document.getElementById("workspace").innerHTML = "";
  evaluate(c, "detail={project:{id:'a',name:'test',state:'draft',audio_tracks:[{index:2,label:'Español'}],subtitle_options:[]},cues:[]};renderWorkspace();");
  const doc = c.document;
  assert.ok(doc.querySelector('.player-frame #audio-track'));
  assert.ok(doc.querySelector('.player-frame #player-audio'));
  assert.equal(doc.getElementById('audio-preview'), null);
  const video = doc.getElementById('video'), audio = doc.getElementById('player-audio');
  doc.querySelector('#audio-track option').setAttribute('selected', '');
  Object.defineProperty(video, 'paused', {value:false, configurable:true});
  audio.play = () => Promise.resolve();
  audio.pause = () => {};
  let cancelled = 0;
  audio.load = () => { cancelled++; };
  video.currentTime = 42;
  video.onplay();
  assert.match(audio.src, /audio-stream\?index=2&start=42\.000/);
  video.currentTime = 85;
  video.onseeking();
  video.onseeked();
  assert.match(audio.src, /index=2&start=85\.000/);
  video.onpause();
  assert.equal(audio.getAttribute('src'), null);
  assert.ok(cancelled > 0);
});

test("viewing an ASR source transcribes without starting translation", async () => {
  const c = editorSetup();
  evaluate(
    c,
    "detail={project:{id:'a',name:'test',state:'draft',audio_tracks:[],subtitle_options:[]},cues:[]};renderWorkspace();",
  );
  const source = c.document.getElementById("subtitle-source");
  source.querySelector('input[value="asr"]').checked=true;
  const calls = [];
  c.api = async (url, opts) => {
    calls.push([url, opts]);
    return opts?.method === "POST"
      ? { id: "a" }
      : {
          project: { id: "a", name: "test", state: "queued", progress: 0 },
          cues: [],
        };
  };
  await evaluate(c, "startProject('a')");
  assert.equal(JSON.parse(calls[0][1].body).action, "edit");
});

test("completed legacy view mode is editable and can be translated", () => {
  const c = editorSetup();
  evaluate(c, "detail={project:{id:'a',name:'test',state:'ready',action:'view'},cues:[{id:'c',start:1,end:3,original:'Hello',translated:''}]};renderWorkspace();");
  const doc = c.document;
  assert.equal(doc.querySelector('textarea.original').hasAttribute('readonly'), false);
  assert.equal(doc.getElementById('edit-view'), null);
  assert.ok(doc.getElementById('translate-pending'));
  doc.getElementById('video').currentTime = 2;
  evaluate(c, 'updateVideoSubtitles()');
  assert.equal(doc.getElementById('video-subtitles').textContent, 'Hello');
});

test("an imported subtitle stays visible on the video in the editor", () => {
  const c = editorSetup(), doc = c.document;
  doc.getElementById('video').currentTime = 0.5;
  evaluate(c, 'updateVideoSubtitles()');
  assert.equal(doc.getElementById('video-subtitles').textContent, 'Hello');
});

test("clicking a viewed subtitle seeks the video to its mark-in", async () => {
  const c = editorSetup();
  evaluate(
    c,
    "detail={project:{id:'a',name:'test',state:'draft',audio_tracks:[],subtitle_options:[{id:'s1',kind:'embedded',label:'1',supported:true}]},cues:[]};renderWorkspace();",
  );
  const doc = c.document,
    source = doc.getElementById("subtitle-source");
  source.querySelector('input[value="s1"]').checked=true;
  c.api = async () => ({ cues: [{ start: 21.5, end: 22, original: "Text" }] });
  await source.onchange();
  const target = doc.getElementById("subtitle-preview"),
    button = target.querySelector(".cue");
  doc.getElementById("video").currentTime = 0;
  target.onclick({ target: button });
  assert.equal(doc.getElementById("video").currentTime, 21.5);
});

test("selected subtitle is shown on the video at its timestamps", async () => {
  const c = editorSetup();
  evaluate(
    c,
    "detail={project:{id:'a',name:'test',state:'draft',audio_tracks:[],subtitle_options:[{id:'s1',kind:'embedded',label:'1',supported:true}]},cues:[]};renderWorkspace();",
  );
  const doc = c.document,
    source = doc.getElementById("subtitle-source");
  source.querySelector('input[value="s1"]').checked=true;
  c.api = async () => ({
    cues: [{ start: 3, end: 5, original: "Visible subtitle" }],
  });
  await source.onchange();
  doc.getElementById("video").currentTime = 4;
  evaluate(c, "updateVideoSubtitles()");
  assert.equal(
    doc.getElementById("video-subtitles").textContent,
    "Visible subtitle",
  );
  doc.getElementById("video").currentTime = 6;
  evaluate(c, "updateVideoSubtitles()");
  assert.equal(doc.getElementById("video-subtitles").textContent, "");
});

test('editor offers synchronization only for local projects with audio', () => {
  const ctx = setup();
  const markup = vm.runInContext("editorToolbar([{id:'x'}], {id:'p', source_kind:'reference', audio_tracks:[{index:0}], state:'ready'})", ctx);
  assert.match(markup, /Sincronizar con audio/);
  const withoutAudio = vm.runInContext("editorToolbar([{id:'x'}], {id:'p', source_kind:'reference', audio_tracks:[], state:'ready'})", ctx);
  assert.doesNotMatch(withoutAudio, /Sincronizar con audio/);
});

test('cue timeline seeks the video without changing the subtitle', () => {
  const c=editorSetup(), doc=c.document;
  const row=doc.querySelector('tr.cue'); row.onfocusin({target:row.querySelector('.original')});
  const timeline=doc.getElementById('cue-timeline');
  assert.ok(timeline.querySelector('.cue-timeline-range'));
  assert.ok(timeline.querySelector('.cue-timeline-playhead'));
  timeline.getBoundingClientRect=()=>({left:0,width:100});
  const before=evaluate(c,"cueEditor.get('c1').start");
  timeline.onclick({clientX:50});
  assert.ok(doc.getElementById('video').currentTime>0);
  assert.equal(evaluate(c,"cueEditor.get('c1').start"),before);
});

test('selected subtitle has a dedicated editor and saves both languages on blur', async () => {
  const c = editorSetup(), doc = c.document;
  const row = doc.querySelector('tr.cue');
  row.onfocusin({target: row.querySelector('.original')});
  assert.equal(doc.getElementById('cue-edit-original').value, 'Hello');
  let saves = [];
  c.api = async (url, opts) => { const body = JSON.parse(opts.body); saves.push(body); return {id:'c1', position:0, ...body}; };
  const field = doc.getElementById('cue-edit-translated');
  field.value = 'Hola'; field.oninput(); field.onblur();
  await evaluate(c, 'cueEditor.flush()');
  assert.equal(saves.at(-1).translated, 'Hola');
  assert.equal(row.querySelector('.translated').value, 'Hola');
  doc.getElementById('undo-edit').onclick();
  await evaluate(c, 'cueEditor.flush()');
  assert.equal(doc.getElementById('cue-edit-translated').value, '');
});

test('selected subtitle navigation seeks and updates editing fields', () => {
  const c = editorSetup(), doc = c.document;
  evaluate(c, `detail.cues.push({id:'c2',position:1,start:10,end:12,original:'Next',translated:'Siguiente'});renderWorkspace()`);
  const row=doc.querySelector('[data-cue="c1"]');
  row.onfocusin({target:row});
  doc.getElementById('cue-next').onclick();
  assert.equal(doc.getElementById('video').currentTime, 10);
  assert.equal(doc.getElementById('cue-edit-original').value, 'Next');
  assert.equal(doc.getElementById('cue-edit-translated').value, 'Siguiente');
});

test('mark-in can be set to playback position and undone', async () => {
  const c = editorSetup(), doc = c.document, row = doc.querySelector('tr.cue');
  c.api = async (url, opts) => ({id:'c1',position:0,...JSON.parse(opts.body)});
  row.onfocusin({target:row});
  doc.getElementById('video').currentTime = 1;
  doc.getElementById('cue-mark-in').onclick();
  await evaluate(c,'cueEditor.flush()');
  assert.equal(evaluate(c,"cueEditor.get('c1').start"),1);
  doc.getElementById('undo-edit').onclick();
  await evaluate(c,'cueEditor.flush()');
  assert.equal(doc.getElementById('cue-edit-start').value,'00:00:00.000');
});

test('dedicated editor follows inline edits to the selected subtitle', async () => {
  const c = editorSetup(), doc = c.document, row = doc.querySelector('tr.cue');
  c.api = async (url, opts) => ({id:'c1',position:0,...JSON.parse(opts.body)});
  row.onfocusin({target:row});
  const field = row.querySelector('.original');
  field.value = 'Edited'; field.oninput(); field.onblur();
  await evaluate(c,'cueEditor.flush()');
  assert.equal(doc.getElementById('cue-edit-original').value,'Edited');
});

test('two manual anchors propose a drift correction without editing the subtitles', async () => {
  const c=editorSetup(), doc=c.document;
  evaluate(c, `detail.cues.push({id:'c2',position:1,start:10,end:12,original:'Next',translated:'Siguiente'});renderWorkspace()`);
  let row=doc.querySelector('[data-cue="c1"]'); row.onfocusin({target:row});
  doc.getElementById('video').currentTime=2;
  await doc.getElementById('anchor-a').onclick();
  doc.getElementById('cue-next').onclick();
  doc.getElementById('video').currentTime=14;
  await doc.getElementById('anchor-b').onclick();
  await doc.getElementById('anchor-preview').onclick();
  const proposal=evaluate(c,'syncProposal.cues');
  assert.equal(proposal[0].new_start,2);
  assert.equal(proposal[1].new_start,14);
  assert.equal(evaluate(c,"cueEditor.get('c1').start"),0);
  assert.match(doc.getElementById('sync-panel').textContent,/Propuesta de sincronización/);
});

test('search narrows subtitle rows by original or translation without editing them', () => {
  const c=editorSetup(), doc=c.document;
  evaluate(c, `detail.cues.push({id:'c2',position:1,start:10,end:12,original:'Next',translated:'Buenos días'});renderWorkspace()`);
  const search=doc.getElementById('cue-search');
  search.value='buenos'; search.oninput({target:search});
  assert.equal(doc.querySelector('[data-cue="c1"]').hidden,true);
  assert.equal(doc.querySelector('[data-cue="c2"]').hidden,false);
  assert.equal(evaluate(c,"cueEditor.get('c2').translated"),'Buenos días');
  search.value=''; search.oninput({target:search});
  assert.equal(doc.querySelector('[data-cue="c1"]').hidden,false);
});

test('inserting a subtitle refreshes the list and selects the new entry', async () => {
  const c=editorSetup(), doc=c.document; let calls=[];
  const cues=[{id:'c1',position:0,start:0,end:2,original:'Hello',translated:''},{id:'new',position:1,start:2,end:4,original:'',translated:''}];
  c.api=async (url,opts)=>{calls.push([url,opts]); return url.endsWith('/insert-after') ? {cue:cues[1],undo_id:'u1'} : {project:{id:'a',name:'test',state:'ready',progress:100},cues};};
  const row=doc.querySelector('tr.cue'); row.onfocusin({target:row});
  await doc.getElementById('cue-insert').onclick();
  assert.ok(calls.some(([url])=>url.endsWith('/cues/c1/insert-after')));
  assert.ok(doc.querySelector('[data-cue="new"]'));
  assert.equal(evaluate(c,'inspectorCue'),'new');
  assert.equal(evaluate(c,'lastComparisonUndo.id'),'u1');
});

test('one manual anchor can preview a constant shift', async () => {
  const c=editorSetup(), doc=c.document, row=doc.querySelector('tr.cue');
  row.onfocusin({target:row});
  doc.getElementById('video').currentTime=3;
  await doc.getElementById('anchor-a').onclick();
  await doc.getElementById('anchor-shift').onclick();
  const entry=evaluate(c,'syncProposal.cues[0]');
  assert.equal(entry.new_start,3);
  assert.equal(entry.new_end,5);
  assert.equal(evaluate(c,"cueEditor.get('c1').start"),0);
});

test('deleting an entry asks for confirmation and retains a recovery action', async () => {
  const c=editorSetup(), doc=c.document; let calls=[];
  c.api=async (url,opts)=>{calls.push([url,opts]); return opts?.method==='DELETE' ? {ok:true,undo_id:'recover'} : {project:{id:'a',name:'test',state:'ready',progress:100},cues:[]};};
  doc.querySelector('tr.cue').onfocusin({target:doc.querySelector('tr.cue')});
  await doc.getElementById('cue-delete').onclick();
  assert.ok(calls.some(([url,opts])=>url.endsWith('/cues/c1') && opts.method==='DELETE'));
  assert.equal(evaluate(c,'lastComparisonUndo.id'),'recover');
  assert.ok(doc.getElementById('undo-empty-delete'));
});

test('opening the HTML as a file shows an actionable link to the local application', () => {
  const html = fs.readFileSync('frontend/index.html','utf8');
  const {parseHTML} = require('linkedom');
  const doc = parseHTML(html).document;
  const script = doc.getElementById('file-open-guard');
  assert.ok(script);
  vm.runInNewContext(script.textContent, {document:doc, location:{protocol:'file:'}});
  assert.ok(doc.documentElement.classList.contains('opened-as-file'));
  assert.equal(doc.getElementById('local-app-link').getAttribute('href'),'http://localhost:3000/');
});

test('translation stage lets the user choose destination and model before starting', async () => {
  const c = editorSetup(), doc = c.document, calls = [];
  c.api = async (url, opts) => {
    calls.push([url, opts]);
    if (url === '/api/ollama/models') return [{name:'first:model'}, {name:'second:model'}];
    if (url.endsWith('/translate')) return {id:'a'};
    return {project:{id:'a',name:'test',state:'queued'}, cues:[]};
  };
  c.select = async () => {}; c.refresh = async () => {};
  evaluate(c, "currentStage='translate';renderWorkspace()");
  await evaluate(c,"loadTranslationModels('a')");
  const language=doc.getElementById('translation-language');
  const model=doc.getElementById('translation-model');
  language.querySelector('option[selected]')?.removeAttribute('selected');
  language.querySelector('option[value="Romanian"]').setAttribute('selected','');
  model.querySelector('option[value="second:model"]').setAttribute('selected','');
  await doc.getElementById('translate-pending').onclick();
  const sent=JSON.parse(calls.find(([url])=>url.endsWith('/translate'))[1].body);
  assert.deepEqual(sent,{target_language:'Romanian',model:'second:model'});
});

test('translation stage explains when an existing destination is locked', () => {
  const c=editorSetup(),doc=c.document;
  evaluate(c,"detail.project.target_language='Romanian';detail.project.translation_language_known=true;detail.cues[0].translated='Bună';currentStage='translate';renderWorkspace()");
  assert.ok(doc.getElementById('translation-language').hasAttribute('disabled'));
  assert.match(doc.getElementById('stage-panel').textContent,/ya hay traducciones/i);
});

test('existing translations without recorded language request explicit identification', () => {
  const c=editorSetup(),doc=c.document;
  evaluate(c,"detail.cues[0].translated='Bună';currentStage='translate';renderWorkspace()");
  assert.equal(doc.getElementById('translation-language').hasAttribute('disabled'),false);
  assert.match(doc.getElementById('stage-panel').textContent,/Indica el idioma de las traducciones existentes/);
});

test('existing translations can have their language identified without starting a task', async () => {
  const c=editorSetup(),doc=c.document,calls=[];
  c.api=async (url,opts)=>{calls.push([url,opts]); if(url==='/api/ollama/models')return []; return {target_language:'Romanian'};};
  evaluate(c,"detail.cues[0].translated='Bună';currentStage='translate';renderWorkspace()");
  const select=doc.getElementById('translation-language');
  select.querySelector('option[value="Romanian"]').setAttribute('selected','');
  await doc.getElementById('confirm-translation-language').onclick();
  assert.equal(JSON.parse(calls.find(([url])=>url.endsWith('/translation-language'))[1].body).target_language,'Romanian');
  assert.equal(evaluate(c,'detail.project.translation_language_known'),true);
});

test('destination language is available in the translation column heading', () => {
  const c=editorSetup(),doc=c.document;
  const heading=doc.querySelector('.subtitle-table thead th:last-child');
  assert.ok(heading.querySelector('#translation-language'));
  assert.equal(doc.querySelectorAll('#translation-language').length,1);
});

test('translation settings open in a modal above the workspace and close without edits', () => {
  const c=editorSetup(), doc=c.document;
  evaluate(c,"currentStage='translate';renderWorkspace()");
  const dialog=doc.getElementById('translation-dialog');
  assert.equal(dialog?.tagName,'DIALOG');
  let opened=false, closed=false;
  dialog.showModal=()=>{opened=true}; dialog.close=()=>{closed=true};
  doc.getElementById('open-translation-dialog').onclick();
  assert.ok(opened);
  doc.getElementById('close-translation-dialog').onclick();
  assert.ok(closed);
});

test('project history and save status are separated from processing and cue actions', () => {
  const c=editorSetup(), doc=c.document;
  assert.ok(doc.querySelector('#global-editor-bar #undo-edit'));
  assert.ok(doc.querySelector('#global-editor-bar #redo-edit'));
  assert.ok(doc.querySelector('#global-editor-bar #save-status'));
  assert.ok(doc.querySelector('#project-operations #improve-picker'));
  assert.equal(doc.querySelector('#cue-inspector #undo-edit'),null);
});

test('one click translates the segment into the column language', async () => {
  const c=editorSetup(), calls=[];
  c.api=async (url,opts)=>{calls.push([url,opts]); if(url.endsWith('/translate')) return {text:'Salut'}; return {id:'c1',position:0,...JSON.parse(opts.body)};};
  const language=c.document.getElementById('translation-language');
  language.querySelector('option[value="French"]').setAttribute('selected','');
  language.onchange();
  await c.document.querySelector('.cue-translate-direct').onclick();
  assert.equal(JSON.parse(calls.find(([url])=>url.endsWith('/translate'))[1].body).target_language,'French');
});

test('translation shows elapsed time while awaiting the model', async () => {
  const c=editorSetup(), wait=deferred();
  c.clearInterval=()=>{};
  c.api=async url=>url.endsWith('/translate') ? wait.promise : {};
  const running=evaluate(c,"translateCue('a','c1','forward','Spanish')");
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(c.document.querySelector('.cue-operation-status').textContent,/0 s/);
  wait.resolve({text:'Hola'}); await running;
});

test('audio and transcription model options are grouped in preferences', () => {
  const c=editorSetup();
  assert.ok(c.document.querySelector('#workspace-preferences #models-controls'));
  assert.ok(c.document.getElementById('open-workspace-preferences'));
});

test('comparing translations shows an indeterminate loading indicator', async () => {
  const c=editorSetup(), wait=deferred();
  c.api=async (url)=>url==='/api/ollama/models' ? [{name:'a'},{name:'b'}] : wait.promise;
  await evaluate(c,"loadCueComparison('c1')");
  const row=c.document.querySelector('.cue');
  row.querySelector('.compare-direction option[value="forward"]').setAttribute('selected','');
  row.querySelector('.compare-model option[value="a"]').setAttribute('selected','');
  row.querySelectorAll('.compare-model')[1].querySelector('option[value="b"]').setAttribute('selected','');
  const running=evaluate(c,"compareCueTranslations('a','c1')");
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(row.querySelector('.cue-compare-results .spinner'),row.querySelector('.cue-compare-results').textContent);
  wait.resolve({source:'Hello',results:[{model:'a',text:'Hola'},{model:'b',text:'Buenas'}]});
  await running;
  assert.equal(row.querySelector('.cue-compare-results .spinner'),null);
});
