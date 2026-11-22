function FocusReview({ cues, startId, onClose, onResolve, onDelete, onChange, onNextStage }) {
  const { Button, TextArea, TextField, VideoFrame } = window.SubtitleStudioDesignSystem_a45136;
  const queue = cues.filter(c => c.sus && !c.resolved);
  const [id, setId] = React.useState(startId && queue.some(c => c.id === startId) ? startId : queue[0] && queue[0].id);
  const idx = queue.findIndex(c => c.id === id);
  const cur = queue[idx] || queue[0];
  const total = React.useRef(queue.length).current;
  const nextId = () => { const rest = queue.filter(c => c.id !== cur.id); const after = rest.find(c => c.id > cur.id); return (after || rest[0] || {}).id; };
  const accept = () => { const n = nextId(); onResolve(cur.id); setId(n); };
  const del = () => { const n = nextId(); onDelete(cur.id); setId(n); };
  const move = d => { if (!queue.length) return; const i = (idx + d + queue.length) % queue.length; setId(queue[i].id); };
  React.useEffect(() => {
    const f = e => {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
      if (!cur) return;
      if (e.key === 'a' || e.key === 'A') accept();
      else if (e.key === 'b' || e.key === 'B') del();
      else if (e.key === 'ArrowRight') move(1);
      else if (e.key === 'ArrowLeft') move(-1);
    };
    window.addEventListener('keydown', f); return () => window.removeEventListener('keydown', f);
  });
  if (!cur) return <div className="focus"><div style={{ margin: 'auto', textAlign: 'center', display: 'grid', gap: 12, justifyItems: 'center' }}>
    <div style={{ fontSize: 30, color: 'var(--fg-success)' }}>✓</div><h2 style={{ margin: 0, fontSize: 18 }}>Has revisado los {total} dudosos</h2><p className="mut12" style={{ margin: 0 }}>Los cambios ya están guardados.</p>
    <div style={{ display: 'flex', gap: 8 }}><Button onClick={onClose}>Volver a la lista</Button><Button variant="primary" onClick={onNextStage}>Siguiente: traducir</Button></div></div></div>;
  const all = cues, ci = all.findIndex(c => c.id === cur.id), prev = all[ci - 1], next = all[ci + 1];
  const zoom = [cur.start - 4, cur.end + 4];
  let seed = cur.id * 7; const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
  const bars = Array.from({ length: 120 }, (_, i) => { const t = zoom[0] + (zoom[1] - zoom[0]) * (i + .5) / 120; const c = all.find(c => t >= c.start && t < c.end); const inCur = t >= cur.start && t < cur.end; const voiced = c && c.sus !== 'sin voz'; return { inCur, h: voiced ? 25 + rnd() * 75 : 4 + rnd() * 8 }; });
  return <div className="focus">
    <div className="focus-h">
      <Button size="sm" variant="ghost" onClick={onClose}>‹ Lista</Button>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}><button className="iconbtn" onClick={() => move(-1)}>‹</button><b style={{ fontSize: 13, minWidth: 110, textAlign: 'center' }}>Dudoso {total - queue.length + 1} de {total}</b><button className="iconbtn" onClick={() => move(1)}>›</button></div>
      <span className="reasonchip">⚠ {cur.sus}</span><span className="mut12">{window.SS2.reasons[cur.sus]}</span>
      <span style={{ flex: 1 }}></span><span className="mut12"><span className="kbd">Esc</span> volver a la lista</span>
    </div>
    <div className="focus-b">
      <div style={{ display: 'grid', gap: 12, alignContent: 'start', minWidth: 0 }}>
        <VideoFrame subtitle={cur.original} placeholder="" />
        <div style={{ display: 'grid', gap: 5 }}>
          <div style={{ height: 64, display: 'flex', alignItems: 'center', gap: 1, position: 'relative', background: 'var(--ink-1)', borderRadius: 8, padding: '0 8px' }}>
            {bars.map((x, i) => <i key={i} style={{ flex: 1, height: x.h + '%', minHeight: 2, borderRadius: 1, background: x.inCur ? 'var(--amber)' : 'var(--line-10)' }}></i>)}
          </div>
          <div className="mut12" style={{ display: 'flex', justifyContent: 'space-between', fontVariantNumeric: 'tabular-nums' }}><span>{window.SS2.fmtS(zoom[0])}</span><span>Audio ±4 s · en naranja, el segmento</span><span>{window.SS2.fmtS(zoom[1])}</span></div>
        </div>
      </div>
      <div style={{ display: 'grid', gap: 14, alignContent: 'start', minWidth: 0 }}>
        {prev && <div className="ctx"><span>#{prev.id}</span>{prev.original}</div>}
        <div style={{ display: 'grid', gap: 6 }}><div className="flabel">#{cur.id} · texto</div><TextArea value={cur.original} minHeight={84} onChange={v => onChange(cur.id, 'original', v)} style={{ fontSize: 16, lineHeight: 1.45, padding: '10px 12px' }} /></div>
        <div style={{ display: 'flex', gap: 8 }}><div style={{ width: 120 }}><div className="flabel">entrada</div><TextField timecode value={window.SS2.fmt(cur.start)} /></div><div style={{ width: 120 }}><div className="flabel">salida</div><TextField timecode value={window.SS2.fmt(cur.end)} invalid={cur.sus === 'fuera de tramo'} /></div></div>
        {next && <div className="ctx"><span>#{next.id}</span>{next.original}</div>}
      </div>
    </div>
    <div className="focus-f">
      <Button onClick={del}>Borrar segmento <span className="kbd">B</span></Button>
      <Button onClick={accept}>Es correcto <span className="kbd">A</span></Button>
      <span style={{ flex: 1 }}></span>
      <span className="mut12">Editar el texto y pasar al siguiente también lo da por revisado</span>
      <Button variant="primary" onClick={accept}>Siguiente dudoso <span className="kbd" style={{ borderColor: '#ffffff66', color: '#fff' }}>→</span></Button>
    </div>
  </div>;
}

function CompareModal({ cues, fromId, mode: initialMode, onClose, onApply }) {
  const { Button } = window.SubtitleStudioDesignSystem_a45136;
  const [mode, setMode] = React.useState(initialMode || 'stt');
  const i0 = Math.max(0, cues.findIndex(c => c.id === fromId) - 1);
  const rows = cues.slice(i0, i0 + 8);
  const [pick, setPick] = React.useState({});
  const A = mode === 'stt' ? { name: 'Qwen3-ASR 1.7B', time: '41 s', get: c => c.original } : { name: 'qwen3:14b-q8_0', time: '18 s', get: c => c.es };
  const B = mode === 'stt' ? { name: 'Whisper large-v3', time: '63 s', get: c => c.alt } : { name: 'gemma3:12b', time: '11 s', get: c => c.es2 };
  const choice = c => pick[mode + c.id] || 'a';
  const diffs = rows.filter(c => A.get(c) !== B.get(c)).length;
  const changes = rows.filter(c => choice(c) === 'b').length;
  const setAll = w => { const n = { ...pick }; rows.forEach(c => n[mode + c.id] = w); setPick(n); };
  const cell = (c, w, txt, other) => {
    const same = A.get(c) === B.get(c), sel = choice(c) === w;
    return <button className={'cmpcell' + (sel ? ' sel' : '') + (same ? ' same' : '')} onClick={() => setPick({ ...pick, [mode + c.id]: w })}>
      {txt ? (same ? txt : window.cueDiffWords(txt, other)) : <span style={{ color: 'var(--fg-dim)' }}>(sin texto)</span>}
      {mode === 'stt' && c.sus === 'sin voz' && txt && <span className="reasonchip" style={{ marginLeft: 6 }}>sin voz</span>}
    </button>;
  };
  return <div className="scrim" onMouseDown={e => e.target === e.currentTarget && onClose()}>
    <div className="modal">
      <div className="modal-h">
        <b style={{ fontSize: 14 }}>Comparar</b>
        <div className="seg">{[['stt', 'Transcripción'], ['tr', 'Traducción']].map(([k, l]) => <button key={k} className={mode === k ? 'on' : ''} onClick={() => setMode(k)}>{l}</button>)}</div>
        <span className="mut12">{window.SS2.fmtS(rows[0].start)} → {window.SS2.fmtS(rows[rows.length - 1].end)} · {rows.length} segmentos · {diffs} con diferencias</span>
        <span style={{ flex: 1 }}></span><button className="iconbtn" onClick={onClose}>✕</button>
      </div>
      <div className="cmprow cmphead"><span>#</span><span>{A.name} <em>{A.time}</em></span><span>{B.name} <em>{B.time}</em></span><span>elegido</span></div>
      <div style={{ overflow: 'auto', flex: 1 }}>
        {rows.map(c => { const a = A.get(c), b = B.get(c), ch = choice(c); return <div key={c.id} className="cmprow">
          <span className="cn">{c.id}</span>{cell(c, 'a', a, b)}{cell(c, 'b', b, a)}
          <span style={{ fontSize: 12.5, color: a === b ? 'var(--fg-dim)' : 'var(--fg-body)' }}>{a === b ? 'igual' : <>{(ch === 'a' ? a : b) || '(sin texto)'} <em className="src">· {(ch === 'a' ? A : B).name.split(' ')[0]}</em></>}</span>
        </div>; })}
      </div>
      <div className="modal-f">
        <span className="mut12">Clic en una celda para elegirla. Los tiempos incluyen la carga del modelo. Nada cambia hasta aplicar.</span>
        <span style={{ flex: 1 }}></span>
        <Button size="sm" onClick={() => setAll('a')}>Todo {A.name.split(' ')[0]}</Button><Button size="sm" onClick={() => setAll('b')}>Todo {B.name.split(' ')[0]}</Button>
        <Button size="sm" variant="primary" disabled={!changes} onClick={() => { onApply(mode, rows.filter(c => choice(c) === 'b').map(c => [c.id, B.get(c)])); }}>Aplicar {changes || ''} {changes === 1 ? 'cambio' : 'cambios'}</Button>
      </div>
    </div>
  </div>;
}

function ExportMenu({ project, onClose, onSave, onFilter }) {
  const { Button, Select } = window.SubtitleStudioDesignSystem_a45136;
  const cues = project.cues || [];
  const untr = cues.filter(c => !c.translated).length, sus = cues.filter(c => c.sus && !c.resolved).length;
  const [lang, setLang] = React.useState('Español');
  const ref = React.useRef(null);
  React.useEffect(() => { const f = e => { if (ref.current && !ref.current.contains(e.target) && !e.target.closest('[data-export-toggle]')) onClose(); }; document.addEventListener('mousedown', f); return () => document.removeEventListener('mousedown', f); }, []);
  const code = lang === 'Español' ? 'es' : lang === 'Original' ? 'en' : 'en-es';
  return <div ref={ref} className="pop" style={{ right: 10, top: 46, width: 320 }}>
    <b style={{ fontSize: 13 }}>Antes de guardar</b>
    <div className="chk ok">✓ {cues.length} segmentos con tiempos válidos</div>
    {lang !== 'Original' && (untr ? <div className="chk warn">⚠ {untr} sin traducir <button className="lnk" onClick={() => onFilter('untr')}>ver</button></div> : <div className="chk ok">✓ Todo traducido</div>)}
    {sus ? <div className="chk warn">⚠ {sus} dudosos sin revisar <button className="lnk" onClick={() => onFilter('sus')}>revisar</button></div> : <div className="chk ok">✓ Sin dudosos pendientes</div>}
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 90px', gap: 6, marginTop: 4 }}><Select value={lang} onChange={setLang} options={['Español', 'Original', 'Bilingüe']} /><Select options={['SRT', 'VTT']} /></div>
    <div className="mut12" style={{ wordBreak: 'break-all' }}>/Series/It's a Sin/{project.file.replace('.mkv', '')}.{code}.srt</div>
    <Button variant="primary" onClick={() => onSave(code)} style={{ justifyContent: 'center' }}>Guardar junto al vídeo</Button>
    <Button variant="ghost" onClick={() => onSave(code, true)} style={{ justifyContent: 'center' }}>Descargar</Button>
  </div>;
}
Object.assign(window, { FocusReview, CompareModal, ExportMenu });
