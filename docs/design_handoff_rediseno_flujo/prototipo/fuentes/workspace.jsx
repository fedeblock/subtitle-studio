function wsStages(p) {
  const cues = p.cues || [];
  const sus = cues.filter(c => c.sus && !c.resolved).length;
  const untr = cues.filter(c => !c.translated).length;
  const pct = cues.length ? Math.round((cues.length - untr) / cues.length * 100) : 0;
  const pre = p.stage === 'source', proc = p.stage === 'processing';
  return [
    { k: 'source', label: 'Fuente', st: pre ? 'active' : 'done' },
    { k: 'process', label: proc ? `Procesar · ${p.pct || 0} %` : 'Procesar', st: proc ? 'run' : pre ? 'todo' : p.source === 'asr' ? 'done' : 'skip' },
    { k: 'review', label: sus ? `Revisar · ${sus}` : 'Revisar', st: pre ? 'todo' : sus ? 'warn' : proc ? 'todo' : 'done' },
    { k: 'translate', label: p.translating ? `Traducir · ${pct} %` : untr && !pre && !proc ? `Traducir · ${untr}` : 'Traducir', st: p.translating ? 'run' : pre || proc ? 'todo' : untr ? 'todo' : 'done' },
    { k: 'export', label: 'Exportar', st: p.exported ? 'done' : 'todo' },
  ];
}
function wsDefaultPanel(p) {
  if (p.stage === 'source') return 'source';
  if (p.stage === 'processing') return 'process';
  const cues = p.cues || [];
  if (cues.some(c => c.sus && !c.resolved)) return 'review';
  return 'translate';
}

function StagePanel({ p, panel, actions, srcPick, setSrcPick }) {
  const { Button, Select, ProgressBar, SourceOption } = window.SubtitleStudioDesignSystem_a45136;
  const cues = p.cues || [];
  const [showHidden, setShowHidden] = React.useState(false);
  if (panel === 'source') {
    const src = window.SS2.sources(p.ep || 1);
    return <div className="spanel">
      <div className="sp-h">¿De dónde salen los subtítulos?</div>
      <div className="mut12">Solo se muestran las fuentes de este episodio.</div>
      <div style={{ display: 'grid', gap: 5 }}>{src.match.map(s => <SourceOption key={s.id} label={s.label} tag={s.rec ? 'recomendada' : s.tag} selected={srcPick === s.id} onSelect={() => setSrcPick(s.id)} />)}
        <SourceOption label="Transcribir el audio" tag="~18 min" generate selected={srcPick === 'asr'} onSelect={() => setSrcPick('asr')} /></div>
      {srcPick === 'asr' && <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}><Select options={['Qwen3-ASR 1.7B', 'Whisper large-v3']} /><Select options={['Detección automática', 'Inglés', 'Rumano']} /></div>}
      <button className="fold" onClick={() => setShowHidden(!showHidden)}>{showHidden ? '⌄' : '›'} {src.hidden.length} subtítulos de otros episodios ocultos</button>
      {showHidden && <div style={{ display: 'grid', gap: 3, paddingLeft: 14 }}>{src.hidden.map(h => <span key={h} className="mut12" style={{ color: 'var(--fg-dim)' }}>{h}</span>)}</div>}
      <div style={{ marginTop: 'auto', display: 'flex', gap: 8 }}><Button variant="primary" onClick={() => actions.chooseSource(srcPick)}>{srcPick === 'asr' ? 'Transcribir' : 'Usar esta fuente'}</Button></div>
    </div>;
  }
  if (panel === 'process') {
    const total = 117, chunk = Math.max(1, Math.round((p.pct || 0) / 100 * total));
    return <div className="spanel">
      <div className="sp-h">Transcribiendo con Qwen3-ASR</div>
      <div style={{ display: 'flex', justifyContent: 'space-between' }} className="mut12"><span>tramo {chunk} de {total}</span><span>~{Math.max(1, Math.round(18 * (1 - (p.pct || 0) / 100)))} min restantes</span></div>
      <ProgressBar value={p.pct || 0} height={5} />
      <p className="mut12" style={{ margin: 0, lineHeight: 1.5 }}>Cada tramo terminado aparece en la lista y ya se puede editar. Los dudosos se marcan a medida que llegan.</p>
      <div style={{ display: 'flex', gap: 8 }}><Button size="sm" onClick={actions.togglePause}>{p.paused ? 'Reanudar' : 'Pausar'}</Button><Button size="sm" variant="ghost">Cancelar</Button></div>
    </div>;
  }
  if (panel === 'review') {
    const sus = cues.filter(c => c.sus && !c.resolved);
    const by = {}; sus.forEach(c => by[c.sus] = (by[c.sus] || 0) + 1);
    if (!sus.length) return <div className="spanel"><div className="sp-h" style={{ color: 'var(--fg-success)' }}>✓ Sin dudosos pendientes</div><p className="mut12" style={{ margin: 0 }}>Puedes seguir revisando la lista o pasar a traducir.</p><div><Button size="sm" onClick={() => actions.setPanel('translate')}>Siguiente: traducir</Button></div></div>;
    return <div className="spanel">
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}><span style={{ fontSize: 26, fontWeight: 700, color: 'var(--amber)', lineHeight: 1 }}>{sus.length}</span><span className="sp-h">segmentos dudosos</span></div>
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>{Object.entries(by).map(([k, n]) => <span key={k} className="reasonchip">{k} · {n}</span>)}</div>
      <p className="mut12" style={{ margin: 0, lineHeight: 1.5 }}>Suelen ser texto inventado en silencios o repeticiones. Revísalos uno a uno con el audio delante.</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}><Button variant="primary" onClick={() => actions.openFocus()}>Revisar uno a uno</Button><Button onClick={() => actions.compare(sus[0].id, 'stt')}>Comparar con Whisper</Button></div>
    </div>;
  }
  const untr = cues.filter(c => !c.translated).length, pct = Math.round((cues.length - untr) / cues.length * 100);
  const props = cues.filter(c => c.proposal).length;
  return <div className="spanel">
    <div className="sp-h">{untr ? 'Traducir' : '✓ Todo traducido'}</div>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}><Select options={['Español', 'Rumano', 'Portugués']} /><Select options={['qwen3:14b-q8_0', 'gemma3:12b']} /></div>
    {p.translating ? <><div className="mut12" style={{ display: 'flex', justifyContent: 'space-between' }}><span>{cues.length - untr} de {cues.length}</span><span>{pct} %</span></div><ProgressBar value={pct} height={5} /><div><Button size="sm" onClick={actions.stopTranslate}>Pausar</Button></div></>
      : untr ? <div><Button variant="primary" onClick={actions.translateAll}>Traducir {untr} pendientes</Button></div> : null}
    <div style={{ borderTop: '1px solid var(--border-soft)', paddingTop: 10, display: 'grid', gap: 6 }}>
      <div style={{ fontSize: 12.5, fontWeight: 600 }}>Mejorar el original</div>
      <p className="mut12" style={{ margin: 0, lineHeight: 1.5 }}>Ollama propone mayúsculas y puntuación. Nada cambia hasta que aceptas.</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{props ? <><Button size="sm" variant="primary" onClick={actions.acceptAll}>Aceptar {props} propuestas</Button><Button size="sm" onClick={() => actions.setFilter('prop')}>Ver una a una</Button></> : <Button size="sm" onClick={actions.improve} disabled={p.improving}>{p.improving ? 'Analizando…' : 'Proponer mejoras'}</Button>}</div>
    </div>
  </div>;
}

function Workspace({ p, onBack, actions }) {
  const { Button, LocalBadge, VideoFrame, Scrubber, Disclosure, Select } = window.SubtitleStudioDesignSystem_a45136;
  const cues = p.cues || [];
  const [panel, setPanel] = React.useState(wsDefaultPanel(p));
  const [filter, setFilter] = React.useState('all');
  const [time, setTime] = React.useState(cues[0] ? cues[0].start + .2 : window.SS2.WIN[0] + 4);
  const [playing, setPlaying] = React.useState(false);
  const [srcPick, setSrcPick] = React.useState('side');
  const [exp, setExp] = React.useState(false);
  const [focus, setFocus] = React.useState(null);
  const [cmp, setCmp] = React.useState(null);
  const [onVideo, setOnVideo] = React.useState('original');
  const prevStage = React.useRef(p.stage);
  React.useEffect(() => { if (prevStage.current !== p.stage) { setPanel(wsDefaultPanel(p)); prevStage.current = p.stage; } }, [p.stage]);
  React.useEffect(() => { if (!playing) return; const t = setInterval(() => setTime(x => x + .1 > window.SS2.WIN[1] ? window.SS2.WIN[0] : x + .1), 100); return () => clearInterval(t); }, [playing]);
  const previewCues = React.useMemo(() => window.SS2.makeCues({ sus: false }), []);
  const listCues = p.stage === 'source' ? (srcPick === 'asr' ? [] : previewCues) : cues;
  const active = listCues.find(c => time >= c.start && time < c.end);
  const sub = active ? (onVideo === 'tr' && active.translated ? active.translated : active.original) : '';
  const st = wsStages(p);
  const A = { ...actions, setPanel, setFilter, openFocus: id => setFocus({ id }), compare: (id, mode) => setCmp({ id, mode }) };
  const seek = t => { setTime(t); };
  return <div style={{ height: '100%', display: 'flex', flexDirection: 'column', position: 'relative' }}>
    <header className="bar">
      <Button size="sm" variant="ghost" onClick={onBack}>‹</Button>
      <div style={{ minWidth: 0, display: 'grid' }}><b style={{ fontSize: 13, whiteSpace: 'nowrap' }}>{p.serie ? `${p.serie} · T${p.season} · E${String(p.ep).padStart(2, '0')}` : p.title}</b><span style={{ fontSize: 10.5, color: 'var(--fg-subtle)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.file}</span></div>
      <nav className="stages">{st.map((s, i) => <React.Fragment key={s.k}>{i > 0 && <span className="sep">›</span>}
        <button data-export-toggle={s.k === 'export' ? 1 : undefined} className={'stage ' + s.st + ((s.k === panel && s.k !== 'export') || (s.k === 'export' && exp) ? ' cur' : '')} disabled={(p.stage === 'source' && s.k !== 'source') || s.st === 'skip'} title={s.st === 'skip' ? 'No hace falta: la fuente ya tiene texto' : ''}
          onClick={() => s.k === 'export' ? setExp(!exp) : setPanel(s.k)}>{s.st === 'done' && <span className="ck">✓</span>}{s.st === 'run' && <span className="pulse"></span>}{s.label}</button></React.Fragment>)}</nav>
      <span style={{ flex: 1 }}></span>
      <LocalBadge />
      <Button size="sm" variant={!cues.some(c => !c.translated) && !p.exported && p.stage === 'edit' ? 'primary' : 'default'} disabled={p.stage !== 'edit'} data-export-toggle="1" onClick={() => setExp(!exp)}>Exportar ▾</Button>
    </header>
    {exp && <ExportMenu project={p} onClose={() => setExp(false)} onFilter={k => { setExp(false); setFilter(k); if (k === 'sus') setPanel('review'); }} onSave={(code, dl) => { setExp(false); actions.exported(code, dl); }} />}
    <div style={{ padding: '10px 14px 8px', borderBottom: '1px solid var(--border-soft)', background: 'var(--bg-bar)' }}>
      <VoiceMap cues={listCues} time={time} onSeek={seek} processedUntil={p.stage === 'processing' ? p.processedUntil : null} />
    </div>
    <div className="split">
      <div className="leftcol">
        <VideoFrame subtitle={sub} placeholder="" />
        <Scrubber current={window.SS2.fmtS(time)} duration={window.SS2.fmtS(window.SS2.DURATION)} value={time / window.SS2.DURATION} playing={playing} onToggle={() => setPlaying(!playing)} onSeek={f => seek(f * window.SS2.DURATION)} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="mut12">Sobre el vídeo</span>
          <div className="seg sm">{[['original', 'Original'], ['tr', 'Traducción']].map(([k, l]) => <button key={k} className={onVideo === k ? 'on' : ''} onClick={() => setOnVideo(k)}>{l}</button>)}</div>
          <span style={{ flex: 1 }}></span>
          <Disclosure summary="Audio · Pista 1 · eng" style={{ minWidth: 0 }}><Select options={['Pista 1 · eng · eac3', 'Pista 2 · eng · commentary']} size="sm" /></Disclosure>
        </div>
        <StagePanel p={p} panel={panel} actions={A} srcPick={srcPick} setSrcPick={setSrcPick} />
      </div>
      {p.stage === 'source' && srcPick === 'asr' ? <div className="empty" style={{ alignSelf: 'center' }}>Al transcribir, los segmentos aparecerán aquí tramo a tramo.<br />El vídeo no se copia ni se envía a Internet.</div>
        : <CueList cues={listCues} readOnly={p.stage === 'source'} activeId={active && active.id} filter={filter} setFilter={setFilter} onSelect={c => setTime(c.start + .05)} onChange={actions.change} onFix={actions.fix} onTranslateOne={actions.translateOne} onCompare={(id, mode) => setCmp({ id, mode })} processedUntil={p.stage === 'processing' ? p.processedUntil : null} chunk={Math.max(1, Math.round((p.pct || 0) / 100 * 117)) + 1} translatingId={p.translatingId} />}
    </div>
    {focus && <FocusReview cues={cues} startId={focus.id} onClose={() => { setFocus(null); setFilter(cues.some(c => c.sus && !c.resolved) ? 'sus' : 'all'); }} onResolve={actions.resolve} onDelete={actions.remove} onChange={actions.change} onNextStage={() => { setFocus(null); setFilter('all'); setPanel('translate'); }} />}
    {cmp && <CompareModal cues={cues.length ? cues : previewCues} fromId={cmp.id} mode={cmp.mode} onClose={() => setCmp(null)} onApply={(mode, list) => { actions.applyCompare(mode, list); setCmp(null); }} />}
  </div>;
}
window.Workspace = Workspace;
