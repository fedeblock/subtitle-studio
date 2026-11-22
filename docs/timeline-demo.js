'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const defaults = [
    { start: 1.4, end: 4.2, text: 'Todo comienza con una idea.' },
    { start: 6.1, end: 9.3, text: 'Una historia encuentra su voz.' },
    { start: 11.2, end: 14.8, text: 'Cada palabra tiene su momento.' },
    { start: 17.1, end: 20.5, text: 'Y cada momento merece ser compartido.' },
  ];
  const duration = 24;
  let cues = defaults.map(cue => ({ ...cue }));
  let selected = 0, current = cues[0].start, playing = false, lastFrame = 0;
  const time = value => {
    const ms = Math.max(0, Math.round(value * 1000));
    return `${String(Math.floor(ms / 3600000)).padStart(2, '0')}:${String(Math.floor(ms / 60000) % 60).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}.${String(ms % 1000).padStart(3, '0')}`;
  };
  const windowFor = cue => ({ from: Math.max(0, cue.start - 3), to: Math.min(duration, Math.max(cue.end + 3, cue.start + 7)) });
  for (let i = 0; i < 112; i++) {
    const bar = document.createElement('i');
    bar.style.height = `${8 + Math.abs(Math.sin(i * 2.17) * Math.sin(i * .12)) * 68}%`;
    $('waveform').appendChild(bar);
  }
  function render() {
    const cue = cues[selected], { from, to } = windowFor(cue), span = to - from;
    $('cues').replaceChildren(...cues.map((item, i) => {
      const button = document.createElement('button');
      button.type = 'button'; button.className = `cue${i === selected ? ' active' : ''}`;
      button.setAttribute('aria-pressed', String(i === selected));
      const number = document.createElement('span'); number.className = 'cue-number'; number.textContent = String(i + 1).padStart(2, '0');
      const start = document.createElement('span'); start.className = 'cue-time'; start.textContent = time(item.start);
      const text = document.createElement('span'); text.textContent = item.text;
      button.append(number, start, text);
      button.addEventListener('click', () => select(i));
      return button;
    }));
    $('selected-title').textContent = `Entrada ${String(selected + 1).padStart(2, '0')}`;
    $('prev').disabled = selected === 0; $('next').disabled = selected === cues.length - 1;
    $('mark-in').textContent = time(cue.start); $('mark-out').textContent = time(cue.end);
    $('duration').textContent = `${(cue.end - cue.start).toFixed(2)} s`;
    $('play-time').textContent = time(current); $('position').textContent = `Vídeo ${time(current)}`;
    $('scale-start').textContent = time(from); $('scale-end').textContent = time(to);
    $('range').style.left = `${(cue.start - from) / span * 100}%`;
    $('range').style.width = `${(cue.end - cue.start) / span * 100}%`;
    $('playhead').style.left = `${Math.max(0, Math.min(1, (current - from) / span)) * 100}%`;
    $('playhead').hidden = current < from || current > to;
    $('timeline').setAttribute('aria-valuemin', from.toFixed(3)); $('timeline').setAttribute('aria-valuemax', to.toFixed(3));
    $('timeline').setAttribute('aria-valuenow', Math.max(from, Math.min(to, current)).toFixed(3)); $('timeline').setAttribute('aria-valuetext', time(current));
    $('video-caption').textContent = cues.find(item => current >= item.start && current <= item.end)?.text || '';
    $('play').textContent = playing ? '❚❚' : '▶'; $('play').setAttribute('aria-label', playing ? 'Pausar ejemplo' : 'Reproducir ejemplo');
  }
  function select(index) { selected = index; current = cues[index].start; playing = false; $('message').textContent = 'Pulsa en la línea de tiempo para mover el cabezal. También puedes usar las flechas del teclado.'; render(); }
  function seekPointer(event) { const rect = $('timeline').getBoundingClientRect(), { from, to } = windowFor(cues[selected]); if (!rect.width) return; current = from + Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * (to - from); render(); }
  $('timeline').addEventListener('pointerdown', event => { $('timeline').setPointerCapture(event.pointerId); seekPointer(event); });
  $('timeline').addEventListener('pointermove', event => { if ($('timeline').hasPointerCapture(event.pointerId)) seekPointer(event); });
  $('timeline').addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault(); const { from, to } = windowFor(cues[selected]);
    current = event.key === 'Home' ? from : event.key === 'End' ? to : Math.max(from, Math.min(to, current + (event.key === 'ArrowLeft' ? -.1 : .1)));
    render();
  });
  $('set-in').addEventListener('click', () => { if (current >= cues[selected].end) { $('message').textContent = 'La entrada debe estar antes de la salida.'; return; } cues[selected].start = current; $('message').textContent = 'Entrada fijada en la posición del cabezal.'; render(); });
  $('set-out').addEventListener('click', () => { if (current <= cues[selected].start) { $('message').textContent = 'La salida debe estar después de la entrada.'; return; } cues[selected].end = current; $('message').textContent = 'Salida fijada en la posición del cabezal.'; render(); });
  $('prev').addEventListener('click', () => select(Math.max(0, selected - 1))); $('next').addEventListener('click', () => select(Math.min(cues.length - 1, selected + 1)));
  $('reset').addEventListener('click', () => { cues = defaults.map(cue => ({ ...cue })); select(0); $('message').textContent = 'Se han restaurado los valores de ejemplo.'; });
  $('play').addEventListener('click', () => { playing = !playing; if (current >= duration) current = 0; lastFrame = 0; render(); if (playing) requestAnimationFrame(tick); });
  function tick(timestamp) { if (!playing) return; if (lastFrame) current = Math.min(duration, current + (timestamp - lastFrame) / 1000); lastFrame = timestamp; if (current >= duration) playing = false; render(); if (playing) requestAnimationFrame(tick); }
  render();
})();
