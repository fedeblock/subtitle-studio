function libSummary(p) {
  if (p.stage === 'source') return { label: 'Elige los subtítulos · 3 encontrados', tone: 'text', action: 'Elegir' };
  if (p.stage === 'queued') return { label: 'En cola', tone: 'mut' };
  if (p.stage === 'failed') return { label: p.failNote, tone: 'err', action: 'Reintentar', pct: 35 };
  if (p.stage === 'processing') return { label: `Transcribiendo · ${p.pct || 0} %`, tone: 'work', pct: p.pct || 0 };
  const cues = p.cues || [];
  const sus = cues.filter(c => c.sus && !c.resolved).length;
  const untr = cues.filter(c => !c.translated).length;
  const done = cues.length - untr;
  if (p.translating) return { label: `Traduciendo · ${done}/${cues.length}`, tone: 'work', pct: Math.round(done / cues.length * 100), action: 'Ver', quiet: true };
  if (sus) return { label: `${sus} segmentos dudosos`, tone: 'warn', action: 'Revisar', pct: 60 };
  if (untr) return { label: `${untr} sin traducir`, tone: 'text', action: 'Traducir', pct: Math.round(done / cues.length * 100) };
  if (!p.exported) return { label: 'Listo para exportar', tone: 'ok', action: 'Exportar', pct: 100 };
  return { label: 'Exportado · .es.srt', tone: 'ok', action: 'Abrir', pct: 100, quiet: true };
}
const libTone = { text: 'var(--fg-body)', mut: 'var(--fg-subtle)', err: 'var(--fg-error)', work: 'var(--fg-accent)', warn: 'var(--amber)', ok: 'var(--fg-success)' };
function libFilterOf(s, p) {
  if (s.tone === 'warn' || s.tone === 'err') return 'attention';
  if (s.tone === 'work' || p.stage === 'queued') return 'running';
  if (p.stage === 'source' || s.action === 'Traducir') return 'todo';
  return 'done';
}

function LibraryScreen({ projects, onOpen, onBatch, onSettings, onQueue, onRetry }) {
  const { Button, LocalBadge, ProgressBar } = window.SubtitleStudioDesignSystem_a45136;
  const [q, setQ] = React.useState('');
  const [f, setF] = React.useState('all');
  const rows = projects.map(p => ({ p, s: libSummary(p) })).map(r => ({ ...r, k: libFilterOf(r.s, r.p) }));
  const count = k => rows.filter(r => r.k === k).length;
  const vis = rows.filter(r => (f === 'all' || r.k === f) && (!q || (r.p.serie || r.p.title).toLowerCase().includes(q.toLowerCase()) || r.s.label.toLowerCase().includes(q.toLowerCase())));
  const series = {};
  vis.forEach(r => { const key = r.p.serie ? `${r.p.serie} · Temporada ${r.p.season}` : 'Películas'; (series[key] = series[key] || []).push(r); });
  const queued = projects.filter(p => ['queued', 'processing'].includes(p.stage) || p.translating).length;
  const chip = (k, label, n, warn) => <button key={k} className={'chip' + (f === k ? ' on' : '') + (warn ? ' warnc' : '')} onClick={() => setF(k)}>{label}{n != null && <span className="n">{n}</span>}</button>;
  return <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
    <header className="bar">
      <span className="wordmark">Subtitle <em>Studio</em></span>
      <div className="search"><span style={{ color: 'var(--fg-dim)' }}>⌕</span><input value={q} onChange={e => setQ(e.target.value)} placeholder="Buscar serie, película o estado" /></div>
      <span style={{ flex: 1 }}></span>
      <LocalBadge />
      <Button size="sm" variant="ghost" onClick={onSettings} title="Ajustes">Ajustes</Button>
      <Button size="sm" variant="primary" onClick={onBatch}>Abrir archivos o carpeta</Button>
    </header>
    <div style={{ flex: 1, overflow: 'auto' }}>
      <div style={{ maxWidth: 980, margin: '0 auto', padding: '22px 24px 60px' }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 18 }}>
          {chip('all', 'Todo')}{chip('attention', 'Necesita atención', count('attention'), true)}{chip('todo', 'Por hacer', count('todo'))}{chip('running', 'En curso', count('running'))}{chip('done', 'Listo', count('done'))}
          <span style={{ flex: 1 }}></span>
          {queued > 0 && <Button size="sm" onClick={onQueue}>Cola · {queued} ›</Button>}
        </div>
        {Object.keys(series).length === 0 && <div className="empty">Nada coincide con la búsqueda.</div>}
        {Object.entries(series).map(([title, list]) => <section key={title} style={{ marginBottom: 22 }}>
          <h2 className="grp-h">{title}<span>{list.length} {title === 'Películas' ? 'títulos' : 'episodios'}</span></h2>
          <div className="libtable">
            {list.map(({ p, s }) => <div key={p.id} className="librow" onClick={() => s.action && (s.action === 'Reintentar' ? onRetry(p.id) : onOpen(p.id))} style={{ cursor: s.action ? 'pointer' : 'default' }}>
              <span className="ep">{p.serie ? 'E' + String(p.ep).padStart(2, '0') : p.year}</span>
              <div style={{ minWidth: 0 }}>
                <div className="nm">{p.serie ? p.file : p.title}</div>
                <div style={{ fontSize: 12, color: libTone[s.tone], marginTop: 2 }}>{s.label}</div>
              </div>
              <div style={{ width: 140 }}>{s.pct != null && <ProgressBar value={s.pct} height={3} />}</div>
              <div style={{ width: 96, display: 'flex', justifyContent: 'flex-end' }}>{s.action && <Button size="sm" variant={s.quiet ? 'ghost' : 'default'}>{s.action}</Button>}</div>
            </div>)}
          </div>
        </section>)}
        <div style={{ display: 'flex', gap: 14, marginTop: 8 }}><Button variant="link">Papelera</Button></div>
      </div>
    </div>
  </div>;
}
Object.assign(window, { LibraryScreen, libSummary });
