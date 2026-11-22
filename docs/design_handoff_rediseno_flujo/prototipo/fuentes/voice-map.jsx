function VoiceMap({ cues, time, onSeek, processedUntil, compact }) {
  const [a, b] = window.SS2.WIN;
  const N = compact ? 90 : 220;
  const bars = React.useMemo(() => {
    let seed = 11; const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
    return Array.from({ length: N }, (_, i) => {
      const t = a + (b - a) * (i + .5) / N;
      const c = cues.find(c => t >= c.start && t < c.end);
      const voiced = c && c.sus !== 'sin voz';
      return { t, c, h: voiced ? 30 + rnd() * 70 : 4 + rnd() * 9 };
    });
  }, [cues.length, N]);
  const ref = React.useRef(null);
  const pos = t => (t - a) / (b - a) * 100 + '%';
  const click = e => { const r = ref.current.getBoundingClientRect(); onSeek && onSeek(a + (b - a) * (e.clientX - r.left) / r.width); };
  const overviewSus = [.06, .13, .135, .41, .62, .63, .81, .9];
  return <div style={{ display: 'grid', gap: 5 }}>
    <div ref={ref} onClick={click} style={{ position: 'relative', height: compact ? 40 : 46, display: 'flex', alignItems: 'center', gap: 1, cursor: 'pointer' }}>
      {bars.map((x, i) => {
        const sus = x.c && x.c.sus && !x.c.resolved;
        const pending = processedUntil != null && x.t > processedUntil;
        const bg = pending ? 'var(--ink-14)' : sus ? 'var(--amber)' : x.c ? 'var(--blue-400)' : 'var(--line-7)';
        return <i key={i} style={{ flex: 1, height: (pending ? 8 : x.h) + '%', minHeight: 2, background: bg, borderRadius: 1, opacity: pending ? .7 : 1 }}></i>;
      })}
      {processedUntil != null && processedUntil < b && <div style={{ position: 'absolute', left: pos(Math.max(a, processedUntil)), right: 0, top: 0, bottom: 0, borderLeft: '1px dashed var(--blue-300)', background: 'repeating-linear-gradient(90deg,transparent 0 6px,#67c3ff10 6px 7px)' }}></div>}
      <div style={{ position: 'absolute', left: pos(time), top: -3, bottom: -3, width: 2, marginLeft: -1, background: 'var(--text-1)', borderRadius: 1, pointerEvents: 'none' }}></div>
    </div>
    <div style={{ position: 'relative', height: 6 }}>
      {cues.filter(c => processedUntil == null || c.start < processedUntil).map(c => <span key={c.id} onClick={() => onSeek && onSeek(c.start)} title={'#' + c.id} style={{ position: 'absolute', left: pos(c.start), width: `calc(${(c.end - c.start) / (b - a) * 100}% - 1px)`, top: 0, bottom: 0, borderRadius: 2, cursor: 'pointer', background: c.sus && !c.resolved ? 'var(--amber)' : 'var(--line-10)' }}></span>)}
    </div>
    {!compact && <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 10.5, color: 'var(--fg-subtle)', fontVariantNumeric: 'tabular-nums' }}>
      <span>{window.SS2.fmtS(a)}</span>
      <div style={{ flex: 1, position: 'relative', height: 4, background: 'var(--ink-14)', borderRadius: 2 }}>
        {overviewSus.map((f, i) => <i key={i} style={{ position: 'absolute', left: f * 100 + '%', top: -2, width: 2, height: 8, background: 'var(--amber)', borderRadius: 1 }}></i>)}
        <i style={{ position: 'absolute', left: a / window.SS2.DURATION * 100 + '%', width: Math.max(1.2, (b - a) / window.SS2.DURATION * 100) + '%', top: -3, height: 10, border: '1px solid var(--text-1)', borderRadius: 2 }}></i>
      </div>
      <span>{window.SS2.fmtS(b)}</span>
      <span style={{ color: 'var(--amber)' }}>■ texto sin voz o dudoso</span>
    </div>}
  </div>;
}
window.VoiceMap = VoiceMap;
