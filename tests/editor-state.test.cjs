const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const editorPath = "../frontend/editor-state.js";
const CueEditor = fs.existsSync("frontend/editor-state.js")
  ? require(editorPath)
  : null;
const cue = { id: "c1", start: 0, end: 2, original: "Hello", translated: "" };
const deferred = () => {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
};

test("blur commits serialize without replacing newer edits; undo and redo persist", async () => {
  assert.ok(CueEditor, "editor controller is missing");
  const gate = deferred(),
    saved = [];
  const editor = new CueEditor([cue], async (id, value) => {
    if (!saved.length) await gate.promise;
    saved.push({ ...value });
    return { id, ...value };
  });
  editor.commit("c1", "original", "Hello again");
  editor.commit("c1", "translated", "Hola");
  assert.equal(editor.get("c1").translated, "Hola");
  gate.resolve();
  assert.equal(await editor.flush(), true);
  assert.equal(saved.length, 2);
  assert.equal(saved[1].original, "Hello again");
  editor.undo();
  await editor.flush();
  assert.equal(saved.at(-1).translated, "");
  assert.equal(saved.at(-1).original, "Hello again");
  editor.redo();
  await editor.flush();
  assert.equal(saved.at(-1).translated, "Hola");
});
test("network failure retains edits and ordered queue for retry", async () => {
  assert.ok(CueEditor, "editor controller is missing");
  let offline = true;
  const saved = [];
  const editor = new CueEditor([cue], async (id, value) => {
    if (offline) throw Error("offline");
    saved.push(value);
    return { id, ...value };
  });
  editor.commit("c1", "translated", "Hola");
  assert.equal(await editor.flush(), false);
  assert.equal(editor.get("c1").translated, "Hola");
  assert.ok(editor.error);
  assert.equal(editor.pending.length, 1);
  editor.commit("c1", "original", "Hi");
  offline = false;
  assert.equal(await editor.retry(), true);
  assert.equal(saved.at(-1).original, "Hi");
  assert.equal(saved.at(-1).translated, "Hola");
});
test("invalid timing and unchanged fields never enter history; editing after undo clears redo", async () => {
  assert.ok(CueEditor, "editor controller is missing");
  const editor = new CueEditor([cue], async (id, value) => ({ id, ...value }));
  assert.throws(() => editor.commit("c1", "start", 3));
  assert.equal(editor.commit("c1", "original", "Hello"), false);
  assert.equal(editor.undoStack.length, 0);
  editor.commit("c1", "start", 1);
  await editor.flush();
  editor.undo();
  await editor.flush();
  editor.commit("c1", "translated", "Hola");
  await editor.flush();
  assert.equal(editor.redoStack.length, 0);
  assert.equal(editor.get("c1").start, 0);
});
