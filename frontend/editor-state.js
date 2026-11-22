/* Ordered, recoverable saves and session history, independent of the DOM. */
class CueEditor {
  constructor(cues, save, onChange = () => {}) {
    this.rows = new Map(cues.map((c) => [c.id, { ...c }]));
    this.confirmed = new Map(cues.map((c) => [c.id, { ...c }]));
    this.save = save;
    this.onChange = onChange;
    this.undoStack = [];
    this.redoStack = [];
    this.pending = [];
    this.running = null;
    this.error = null;
  }
  get(id) {
    return this.rows.get(id);
  }
  reconcile(cues) {
    const fields = ["start", "end", "original", "translated"];
    const incoming = new Map(cues.map(c => [c.id, c]));
    if ([...this.rows].every(([id, row]) => incoming.has(id) && fields.every(f => row[f] === incoming.get(id)[f]))) {
      for (const cue of cues) if (!this.rows.has(cue.id)) {
        this.rows.set(cue.id, {...cue});
        this.confirmed.set(cue.id, {...cue});
      }
      return;
    }
    if (
      cues.length !== this.rows.size ||
      cues.some(
        (c) =>
          !this.rows.has(c.id) ||
          fields.some((f) => this.rows.get(c.id)[f] !== c[f]),
      )
    ) {
      this.rows = new Map(cues.map((c) => [c.id, { ...c }]));
      this.confirmed = new Map(cues.map((c) => [c.id, { ...c }]));
      this.undoStack = [];
      this.redoStack = [];
    }
  }
  commit(id, field, value) {
    const before = this.get(id);
    if (!["start", "end", "original", "translated"].includes(field) || !before)
      throw Error("Campo inválido");
    if (before[field] === value) return false;
    const after = { ...before, [field]: value };
    if (
      !Number.isFinite(after.start) ||
      !Number.isFinite(after.end) ||
      after.start < 0 ||
      after.end <= after.start
    ) {
      throw Error("Mark-out debe ser posterior a mark-in. Usa HH:MM:SS.mmm.");
    }
    this.undoStack.push({ id, field, before, after });
    this.redoStack = [];
    this.apply(id, after);
    return true;
  }
  apply(id, value) {
    this.rows.set(id, { ...value });
    this.pending.push({ id, value: { ...value } });
    this.onChange();
    void this.flush();
  }
  undo() {
    const action = this.undoStack.pop();
    if (!action) return null;
    this.redoStack.push(action);
    this.apply(action.id, action.before);
    return action;
  }
  redo() {
    const action = this.redoStack.pop();
    if (!action) return null;
    this.undoStack.push(action);
    this.apply(action.id, action.after);
    return action;
  }
  flush() {
    if (this.running) return this.running;
    if (this.error) return Promise.resolve(false);
    // Defer the drain so running is assigned before callbacks can enqueue more work.
    this.running = Promise.resolve().then(async () => {
      try {
        while (this.pending.length) {
          const { id, value } = this.pending[0];
          const saved = await this.save(id, value, this.confirmed.get(id));
          this.confirmed.set(id, { ...saved });
          this.pending.shift();
          this.onChange(saved);
        }
        return true;
      } catch (error) {
        this.error = error;
        return false;
      } finally {
        this.running = null;
        this.onChange();
      }
    });
    return this.running;
  }
  retry() {
    this.error = null;
    return this.flush();
  }
}
if (typeof module !== "undefined") module.exports = CueEditor;
