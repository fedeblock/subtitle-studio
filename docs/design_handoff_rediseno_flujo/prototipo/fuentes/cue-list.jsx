function cueDiffWords(a, b) {
  const bs = new Set((b || '').toLowerCase().split(/\s+/));
  return (a || '').split(/(\s+)/).map((w, i) => /\s/.test(w) || bs.has(w.toLowerCase()) ? w : <mark key={i} className="hlw">{w}</mark>);
}

function CueMenu({ cue, onTranslateOne, onCompare }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);
  React.useEffect(() => { if (!open) return; const f = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }; document.addEventListener('mousedown', f); return () => document.removeEventListener('mousedown', f); }, [open]);
  const go = fn => () => { setOpen(false); fn(); };
  return <div ref={ref} style={{ position: 'relative' }}>
    <button className="iconbtn" title="Traducir o comparar este segmento" onClick={() => setOpen(!open)}>⇄</button>
    {open && <div className="menu" style={{ right: 0, top: 28 }}>
      <button onClick={go(() => onTranslateOne(cue.id))}>Traducir este segmento</button>
      <button onClick={go(() => onCompare(cue.id, 'stt'))}>Comparar transcripción aquí</button>
      <button onClick={go(() => onCompare(cue.id, 'tr'))}>Comparar modelos de traducción</button>
    </div>}
  </div>;
}

function CueList({ cues, readOnly, activeId, filter, setFilter, onSelect, onChange, onFix, onTranslateOne, onCompare, processedUntil, translatingId, chunk }) {
  const { TextArea } = window.SubtitleStudioDesignSystem_a45136;
  const visible = processedUntil == null ? cues : cues.filter(c => c.end <= processedUntil);
  const sus = visible.filter(c => c.sus && !c.resolved).length;
  const untr = visible.filter(c => !c.translated).length;
  const props = visible.filter(c => c.proposal).length;
  const shown = visible.filter(c => filter === 'sus' ? c.sus && !c.resolved : filter === 'untr' ? !c.translated : filter === 'prop' ? c.proposal : true);
  const scroller = React.useRef(null);
  React.useEffect(() => { const el = scroller.current && scroller.current.querySelector('[data-active="1"]'); if (el && scroller.current) { const s = scroller.current, top = el.offsetTop - s.offsetTop; if (top < s.scrollTop + 40 || top > s.scrollTop + s.clientHeight - 90) s.scrollTop = top - 80; } }, [activeId]);
  const chip = (k, label, n, cls) => <button className={'chip' + (filter === k ? ' on' : '') + (cls ? ' ' + cls : '')} onClick={() => setFilter(k)}>{label}{n != null && <span className="n">{n}</span>}</button>;
  const cols = '38px 92px minmax(0,1fr) minmax(0,1fr) 30px';
  return <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', borderBottom: '1px solid var(--border-soft)', flexWrap: 'wrap' }}>
      {readOnly && <span className="mut12" style={{ marginRight: 6 }}>Vista previa · solo lectura hasta usar la fuente</span>}{chip('all', 'Todo', visible.length)}{chip('sus', 'Dudosos', sus, 'warnc')}{chip('untr', 'Sin traducir', untr)}{props > 0 && chip('prop', 'Mejoras propuestas', props, 'accc')}
    </div>
    <div className="cuehead" style={{ gridTemplateColumns: cols }}><span>#</span><span>tiempos</span><span>original · inglés</span><span>traducción · español</span><span></span></div>
    <div ref={scroller} style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
      {shown.length === 0 && <div className="empty">{filter === 'sus' ? 'No quedan dudosos.' : filter === 'untr' ? 'Todo está traducido.' : 'Nada que mostrar.'}</div>}
      {shown.map(c => {
        const on = c.id === activeId, s = c.sus && !c.resolved;
        return <div key={c.id} data-active={on ? 1 : 0} className={'cuerow' + (on ? ' on' : '') + (s ? ' sus' : '')} style={{ gridTemplateColumns: cols }} onClick={() => onSelect(c)}>
          <span className="cn">{c.id}</span>
          <span className="tcs"><span>{window.SS2.fmt(c.start)}</span><span>{window.SS2.fmt(c.end)}</span></span>
          <div style={{ minWidth: 0, display: 'grid', gap: 5 }}>
            {c.proposal ? <div className="diff">
              <div><del>{c.original}</del></div><div><ins>{c.proposal}</ins></div>
              <div style={{ display: 'flex', gap: 6, marginTop: 2 }}><button className="mini ok" onClick={e => { e.stopPropagation(); onFix(c.id, true); }}>✓ Aceptar</button><button className="mini" onClick={e => { e.stopPropagation(); onFix(c.id, false); }}>✕ Descartar</button></div>
            </div> : <TextArea readOnly={readOnly} value={c.original} minHeight={40} onChange={v => onChange(c.id, 'original', v)} />}
            {s && <span className="reason">⚠ {c.sus} · {window.SS2.reasons[c.sus]}</span>}
          </div>
          <div style={{ minWidth: 0 }}>{translatingId === c.id ? <div className="tr-busy">traduciendo…</div> : <TextArea readOnly={readOnly} value={c.translated} minHeight={40} onChange={v => onChange(c.id, 'translated', v)} />}</div>
          <div onClick={e => e.stopPropagation()}>{!readOnly && <CueMenu cue={c} onTranslateOne={onTranslateOne} onCompare={onCompare} />}</div>
        </div>;
      })}
      {processedUntil != null && filter === 'all' && <>
        <div className="cuerow ghost" style={{ gridTemplateColumns: cols }}><span className="cn">·</span><span className="tcs"><span>{window.SS2.fmt(processedUntil)}</span></span><div className="skel" style={{ width: '70%' }}></div><span style={{ fontSize: 12, color: 'var(--fg-accent)' }}>tramo {chunk} · procesando…</span><span></span></div>
        <div className="cuerow ghost" style={{ gridTemplateColumns: cols }}><span className="cn">·</span><span className="tcs"><span>{window.SS2.fmt(processedUntil + 30)}</span></span><div className="skel" style={{ width: '50%' }}></div><span className="mut12">pendiente</span><span></span></div>
      </>}
    </div>
  </div>;
}
Object.assign(window, { CueList, cueDiffWords });
