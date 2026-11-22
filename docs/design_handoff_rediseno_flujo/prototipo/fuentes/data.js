(() => {
  const p2 = n => String(n).padStart(2, '0');
  const fmt = s => { const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s - h * 3600 - m * 60; return p2(h) + ':' + p2(m) + ':' + x.toFixed(3).padStart(6, '0'); };
  const fmtS = s => { s = Math.max(0, Math.floor(s)); return p2(Math.floor(s / 3600)) + ':' + p2(Math.floor(s % 3600 / 60)) + ':' + p2(s % 60); };
  // [start, end, original (Qwen3-ASR), español, extra]
  const raw = [
    [380.2, 382.1, 'Where are you going?', '¿Adónde vas?', { alt: 'Where are ya going?', es2: '¿A dónde te vas?' }],
    [382.4, 384.0, 'To London. Tonight.', 'A Londres. Esta noche.', { alt: 'To London, tonight.', es2: 'A Londres, esta noche.' }],
    [384.6, 387.2, "you can't just leave like that", 'No puedes irte así sin más.', { fix: "You can't just leave like that.", alt: "You can't just leave like that.", es2: 'No puedes marcharte así.' }],
    [387.5, 389.0, 'Watch me.', 'Ya lo verás.', { es2: 'Mírame.' }],
    [391.5, 394.0, 'Thank you for watching.', 'Gracias por ver el vídeo.', { sus: 'sin voz', alt: '' }],
    [394.8, 397.1, 'Your mother will be furious.', 'Tu madre se pondrá furiosa.', { es2: 'Tu madre va a estar furiosa.' }],
    [397.3, 399.9, "She'll get over it. She always does.", 'Ya se le pasará. Siempre se le pasa.', { alt: "She'll get over it, she always does." }],
    [400.2, 402.0, 'What about your exams?', '¿Y tus exámenes?'],
    [402.3, 404.6, "i'll come back for them", 'Volveré para hacerlos.', { fix: "I'll come back for them." }],
    [405.0, 406.1, 'Promise?', '¿Me lo prometes?'],
    [406.3, 407.4, 'Promise.', 'Te lo prometo.', { sus: 'repetición' }],
    [409.0, 412.5, "I— I— I don't know what I'll do here without you.", 'No… no sé qué voy a hacer aquí sin ti.', { sus: 'baja confianza', alt: "I don't know what I'll do here without you." }],
    [413.0, 415.2, "You'll be fine.", 'Estarás bien.'],
    [415.6, 418.4, "There's a train at half past nine.", 'Hay un tren a las nueve y media.'],
    [418.8, 420.0, 'Ritchie, wait.', 'Ritchie, espera.'],
    [420.5, 423.0, 'Take this. For the ticket.', 'Toma. Para el billete.'],
    [423.4, 425.0, "I can't take your money.", 'No puedo aceptar tu dinero.'],
    [425.3, 427.9, "it's not my money it's dad's", 'No es mi dinero. Es de papá.', { fix: "It's not my money. It's Dad's." }],
    [431.0, 433.5, 'Subtitles by the community', 'Subtítulos de la comunidad', { sus: 'sin voz', alt: '' }],
    [434.0, 436.2, 'Call me when you get there.', 'Llámame cuando llegues.'],
    [436.5, 438.0, 'I will.', 'Lo haré.'],
    [438.2, 443.4, 'Go on, before I change my mind.', 'Venga, vete antes de que cambie de opinión.', { sus: 'fuera de tramo' }],
  ];
  const makeCues = ({ sus = true, translated = 0 } = {}) => raw.map((r, i) => {
    const x = r[4] || {};
    return { id: i + 1, start: r[0], end: r[1], original: r[2], translated: i < translated ? r[3] : '', es: r[3], es2: x.es2 || r[3], alt: x.alt ?? r[2], fix: x.fix || null, sus: sus ? (x.sus || null) : null, resolved: false, proposal: null };
  });
  const projects = [
    { id: 'e01', serie: "It's a Sin", season: 1, ep: 1, file: 'Its.a.Sin.S01E01.mkv', stage: 'edit', cues: makeCues({ sus: false, translated: 99 }), exported: true },
    { id: 'e02', serie: "It's a Sin", season: 1, ep: 2, file: 'Its.a.Sin.S01E02.mkv', stage: 'edit', cues: makeCues(), exported: false, source: 'asr' },
    { id: 'e03', serie: "It's a Sin", season: 1, ep: 3, file: 'Its.a.Sin.S01E03.mkv', stage: 'edit', cues: makeCues({ sus: false, translated: 7 }), exported: false, translating: true },
    { id: 'e04', serie: "It's a Sin", season: 1, ep: 4, file: 'Its.a.Sin.S01E04.mkv', stage: 'queued' },
    { id: 'e05', serie: "It's a Sin", season: 1, ep: 5, file: 'Its.a.Sin.S01E05.mkv', stage: 'source' },
    { id: 'q05', title: 'The Quiet', year: 2005, file: 'The.Quiet.2005.720p.BluRay.mp4', stage: 'failed', failNote: 'Se detuvo en el tramo 41 de 117' },
    { id: 'y25', title: '28 Years Later', year: 2025, file: '28.Years.Later.2025.mp4', stage: 'edit', cues: makeCues({ sus: false, translated: 99 }), exported: true },
  ];
  const sources = ep => ({
    match: [
      { id: 'side', label: `Its.a.Sin.S01E0${ep}.en.srt`, tag: 'junto al vídeo · inglés', rec: true },
      { id: 'emb', label: 'Pista 2 · eng · subrip', tag: 'incrustada' },
      { id: 'subs', label: `Subs/S01E0${ep}.English.srt`, tag: 'carpeta Subs' },
    ],
    hidden: [1, 2, 3, 4].filter(n => n !== ep).flatMap(n => [`Its.a.Sin.S01E0${n}.en.srt`, `Subs/S01E0${n}.English.srt`, `Subs/S01E0${n}.Spanish.srt`]).concat(['Subs/S01E06.English.srt', 'Subs/S01E06.Spanish.srt']),
  });
  const reasons = { 'sin voz': 'El audio no tiene voz bajo este texto', 'repetición': 'Repite el segmento anterior', 'baja confianza': 'El modelo dio baja confianza a estas palabras', 'fuera de tramo': 'El final se sale del tramo de audio' };
  window.SS2 = { fmt, fmtS, makeCues, projects, sources, reasons, DURATION: 2878, WIN: [376, 446] };
})();
