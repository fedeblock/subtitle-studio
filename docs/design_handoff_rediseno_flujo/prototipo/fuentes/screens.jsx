function BatchScreen({ onBack, onAdd }) {
  const { Button, Select } = window.SubtitleStudioDesignSystem_a45136;
  const eps = [
    { ep: 6, src: '.en.srt junto al vídeo' }, { ep: 7, src: 'Pista 2 · eng incrustada' }, { ep: 8, src: 'Subs/S01E08.English.srt' }, { ep: 9, src: 'Sin subtítulos → transcribir', asr: true }, { ep: 10, src: '.en.srt junto al vídeo' },
  ];
  const [sel, setSel] = React.useState(eps.map(e => e.ep));
  const [improve, setImprove] = React.useState(false);
  const [flag, setFlag] = React.useState(true);
  const [adv, setAdv] = React.useState(false);
  const toggle = ep => setSel(s => s.includes(ep) ? s.filter(x => x !== ep) : [...s, ep]);
  const lab = t => <div className="flabel">{t}</div>;
  return <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
    <header className="bar"><Button size="sm" variant="ghost" onClick={onBack}>‹ Biblioteca</Button><b style={{ fontSize: 13 }}>Nuevo lote</b><span className="mut12">5 archivos de /Series/It's a Sin/Temporada 1 (2)</span></header>
    <div style={{ flex: 1, overflow: 'auto' }}>
      <div style={{ maxWidth: 1040, margin: '0 auto', padding: '24px', display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 20 }}>
        <section className="panel">
          <div className="panel-h">Episodios detectados<span>It's a Sin · T1</span></div>
          {eps.map(e => <label key={e.ep} className="librow" style={{ gridTemplateColumns: '22px 44px minmax(0,1fr)', cursor: 'pointer' }}>
            <input type="checkbox" checked={sel.includes(e.ep)} onChange={() => toggle(e.ep)} style={{ accentColor: 'var(--blue-350)' }} />
            <span className="ep">E{String(e.ep).padStart(2, '0')}</span>
            <span style={{ fontSize: 12.5, color: e.asr ? 'var(--amber)' : 'var(--fg-body)' }}>{e.src}</span>
          </label>)}
          <div className="mut12" style={{ padding: '10px 14px' }}>12 subtítulos de otros episodios ignorados.</div>
        </section>
        <section className="panel" style={{ padding: '14px 16px', display: 'grid', gap: 12, alignContent: 'start' }}>
          <div className="panel-h" style={{ padding: 0, border: 0 }}>Receta</div>
          <div>{lab('Receta guardada')}<Select options={['Series inglés → español', 'Películas · solo transcribir', 'Nueva receta']} style={{ width: '100%' }} /></div>
          <div>{lab('Fuente preferida')}<Select options={['Subtítulos existentes en inglés', 'Siempre transcribir el audio']} style={{ width: '100%' }} /></div>
          <div>{lab('Si no hay subtítulos')}<Select options={['Transcribir con Qwen3-ASR 1.7B', 'Transcribir con Whisper large-v3']} style={{ width: '100%' }} /></div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}><div>{lab('Traducir a')}<Select options={['Español', 'Rumano', 'Inglés', 'Portugués']} style={{ width: '100%' }} /></div><div>{lab('Con')}<Select options={['qwen3:14b-q8_0', 'gemma3:12b']} style={{ width: '100%' }} /></div></div>
          <label className="check"><input type="checkbox" checked={improve} onChange={e => setImprove(e.target.checked)} />Mejorar mayúsculas y puntuación antes de traducir</label>
          <label className="check"><input type="checkbox" checked={flag} onChange={e => setFlag(e.target.checked)} />Marcar segmentos dudosos para revisar</label>
          <button className="fold" onClick={() => setAdv(!adv)}>{adv ? '⌄' : '›'} Avanzado</button>
          {adv && <div style={{ display: 'grid', gap: 10, paddingLeft: 14 }}><div>{lab('Idioma hablado')}<Select options={['Detección automática', 'Inglés', 'Rumano']} style={{ width: '100%' }} /></div><div>{lab('Exportar al terminar')}<Select options={['No, esperar a la revisión', 'Sí, si no hay dudosos']} style={{ width: '100%' }} /></div></div>}
        </section>
      </div>
    </div>
    <footer className="foot"><span className="mut12">Revisar es manual. El resto de pasos sigue solo mientras revisas otro episodio.</span><span style={{ flex: 1 }}></span><Button variant="primary" disabled={!sel.length} onClick={onAdd}>Añadir {sel.length} a la cola</Button></footer>
  </div>;
}

function QueueScreen({ projects, onBack, onOpen }) {
  const { Button, ProgressBar } = window.SubtitleStudioDesignSystem_a45136;
  const list = projects.filter(p => p.serie);
  const cell = (p, k) => {
    const s = window.libSummary(p);
    const ok = <span style={{ color: 'var(--fg-success)' }}>✓</span>, dash = <span style={{ color: 'var(--fg-dim)' }}>—</span>;
    if (p.stage === 'queued') return k === 'src' ? ok : k === 'proc' ? <span className="mut12">en cola</span> : dash;
    if (p.stage === 'source') return k === 'src' ? <span style={{ color: 'var(--fg-body)' }}>elegir</span> : dash;
    if (p.stage === 'processing') return k === 'src' ? ok : k === 'proc' ? <div style={{ display: 'grid', gap: 4 }}><span style={{ color: 'var(--fg-accent)' }}>{p.pct} %</span><ProgressBar value={p.pct} height={3} /></div> : dash;
    const cues = p.cues || [], sus = cues.filter(c => c.sus && !c.resolved).length, tr = cues.filter(c => c.translated).length;
    if (k === 'src' || k === 'proc') return ok;
    if (k === 'rev') return sus ? <span style={{ color: 'var(--amber)' }}>{sus} dudosos</span> : ok;
    if (k === 'tr') return tr === cues.length ? ok : p.translating ? <span style={{ color: 'var(--fg-accent)' }}>{Math.round(tr / cues.length * 100)} %</span> : <span className="mut12">{cues.length - tr} pend.</span>;
    if (k === 'exp') return p.exported ? ok : <span className="mut12">espera</span>;
  };
  const cols = '56px repeat(5,minmax(0,1fr)) 96px';
  const running = list.filter(p => p.stage === 'processing' || p.translating).length;
  return <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
    <header className="bar"><Button size="sm" variant="ghost" onClick={onBack}>‹ Biblioteca</Button><b style={{ fontSize: 13 }}>Cola · It's a Sin T1</b><span className="mut12">{running} en marcha · ~42 min restantes</span><span style={{ flex: 1 }}></span><Button size="sm">Pausar cola</Button></header>
    <div style={{ flex: 1, overflow: 'auto' }}><div style={{ maxWidth: 1040, margin: '0 auto', padding: 24 }}>
      <div className="panel">
        <div className="qrow qh" style={{ gridTemplateColumns: cols }}><span>Ep.</span><span>Fuente</span><span>Procesar</span><span>Revisar</span><span>Traducir</span><span>Exportar</span><span></span></div>
        {list.map(p => { const s = window.libSummary(p); const needs = s.tone === 'warn' || p.stage === 'source'; return <div key={p.id} className={'qrow' + (needs ? ' needs' : '')} style={{ gridTemplateColumns: cols }}>
          <span className="ep">E{String(p.ep).padStart(2, '0')}</span>
          {['src', 'proc', 'rev', 'tr', 'exp'].map(k => <span key={k}>{cell(p, k)}</span>)}
          <span style={{ display: 'flex', justifyContent: 'flex-end' }}>{p.stage !== 'queued' && <Button size="sm" variant={needs ? 'default' : 'ghost'} onClick={() => onOpen(p.id)}>{needs ? (p.stage === 'source' ? 'Elegir' : 'Revisar') : 'Abrir'}</Button>}</span>
        </div>; })}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14 }}><span className="mut12">Las filas resaltadas esperan a una persona.</span><span style={{ flex: 1 }}></span><Button size="sm">Exportar listos</Button></div>
    </div></div>
  </div>;
}

function SettingsScreen({ onBack }) {
  const { Button } = window.SubtitleStudioDesignSystem_a45136;
  const [tab, setTab] = React.useState('Modelos');
  const row = (name, size, def, actions) => <div className="librow" style={{ gridTemplateColumns: 'minmax(0,1fr) 90px auto' }}><span style={{ fontSize: 13 }}>{name}{def && <span className="tag">por defecto</span>}</span><span className="mut12" style={{ fontVariantNumeric: 'tabular-nums' }}>{size}</span><span style={{ display: 'flex', gap: 6 }}>{actions && <><Button size="xs">Verificar</Button><Button size="xs" variant="ghost">Borrar</Button></>}</span></div>;
  return <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
    <header className="bar"><Button size="sm" variant="ghost" onClick={onBack}>‹ Biblioteca</Button><b style={{ fontSize: 13 }}>Ajustes</b></header>
    <div style={{ flex: 1, overflow: 'auto' }}><div style={{ maxWidth: 900, margin: '0 auto', padding: 24, display: 'grid', gridTemplateColumns: '170px minmax(0,1fr)', gap: 24 }}>
      <nav style={{ display: 'grid', gap: 2, alignContent: 'start' }}>{['Modelos', 'Recetas', 'Revisión', 'Exportación'].map(t => <button key={t} className={'navi' + (tab === t ? ' on' : '')} onClick={() => setTab(t)}>{t}</button>)}</nav>
      <div style={{ display: 'grid', gap: 18, alignContent: 'start' }}>
        {tab === 'Modelos' && <><section className="panel"><div className="panel-h">Transcripción<span>caché de Hugging Face</span></div>{row('Qwen3-ASR 1.7B', '6,09 GiB', true, true)}{row('Whisper large-v3', '2,87 GiB', false, true)}</section>
          <section className="panel"><div className="panel-h">Traducción y mejora<span>Ollama · 127.0.0.1:11434</span></div>{row('qwen3:14b-q8_0', '15,7 GB', true)}{row('gemma3:12b', '8,1 GB')}</section>
          <p className="mut12" style={{ margin: 0 }}>La caché puede compartirse con otras aplicaciones: borrar un modelo también lo elimina para ellas.</p></>}
        {tab === 'Recetas' && <section className="panel"><div className="panel-h">Recetas</div>{row('Series inglés → español', '', true)}{row('Películas · solo transcribir', '')}</section>}
        {tab === 'Revisión' && <section className="panel" style={{ paddingBottom: 6 }}><div className="panel-h">Marcar como dudoso</div>{['Texto sin voz debajo', 'Repite el segmento anterior', 'Baja confianza del modelo', 'Tiempos fuera del tramo'].map(t => <label key={t} className="check" style={{ padding: '8px 14px' }}><input type="checkbox" defaultChecked />{t}</label>)}</section>}
        {tab === 'Exportación' && <section className="panel" style={{ padding: 14, display: 'grid', gap: 8 }}><div className="mut12">Nombre del archivo</div><code style={{ fontSize: 12, color: 'var(--fg-timecode)' }}>{'{nombre}.{idioma}.{formato}'}</code><div className="mut12">Si ya existe, se añade un número.</div></section>}
      </div>
    </div></div>
  </div>;
}
Object.assign(window, { BatchScreen, QueueScreen, SettingsScreen });
