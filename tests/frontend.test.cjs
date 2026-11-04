const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
function setup() {
  const html = fs.readFileSync("frontend/index.html", "utf8");
  const source = fs.existsSync("frontend/app.js")
    ? fs.readFileSync("frontend/app.js", "utf8")
    : html.match(/<script>([\s\S]*)<\/script>/)[1];
  const elements = {};
  const ctx = vm.createContext({
    document: {
      getElementById: (id) => (elements[id] ||= {}),
      querySelectorAll: () => [],
    },
    window: { addEventListener: () => {} },
    console,
    alert: () => {},
    confirm: () => true,
    setInterval: () => {},
    setTimeout: () => {},
    fetch: async () => ({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => [],
    }),
  });
  vm.runInContext(fs.readFileSync("frontend/editor-state.js", "utf8"), ctx);
  vm.runInContext(
    source.replace(/refresh\(\);\s*setInterval\(refresh,\s*4000\);/, ""),
    ctx,
  );
  vm.runInContext("renderList=()=>{};renderWorkspace=()=>{};", ctx);
  return ctx;
}
const evaluate = (ctx, script) => vm.runInContext(script, ctx);
const deferred = () => {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
};

test("time formatter carries rounded milliseconds into next minute", () => {
  const c = setup();
  assert.equal(evaluate(c, "time(59.9996)"), "00:01:00.000");
});
test("invalid timestamp fields are rejected", () => {
  const c = setup();
  for (const value of ["00:99:00", "00:00:-1", "00::01", "-1:00:00"])
    assert.ok(
      Number.isNaN(evaluate(c, `secs(${JSON.stringify(value)})`)),
      value,
    );
});
test("slow selection cannot replace a newer selected project", async () => {
  const c = setup(),
    a = deferred(),
    b = deferred();
  c.api = (url) => (url.endsWith("/a") ? a.promise : b.promise);
  const first = evaluate(c, "select('a')"),
    second = evaluate(c, "select('b')");
  b.resolve({ project: { id: "b" }, cues: [] });
  await second;
  a.resolve({ project: { id: "a" }, cues: [] });
  await first;
  assert.equal(evaluate(c, "detail.project.id"), "b");
});
test("polling never replaces edits started while request was in flight", async () => {
  const c = setup(),
    response = deferred(),
    started = deferred();
  c.api = async (url) => {
    if (url === "/api/projects") return [];
    started.resolve();
    return response.promise;
  };
  evaluate(c, "selected='a';detail={project:{id:'a',state:'ready'},cues:[]};");
  const refreshing = evaluate(c, "refresh()");
  await started.promise;
  evaluate(c, "dirty.add('cue');");
  response.resolve({ project: { id: "a", state: "failed" }, cues: [] });
  await refreshing;
  assert.equal(evaluate(c, "detail.project.state"), "ready");
});

test("preview keeps the same media element across processing updates", () => {
  const { parseHTML } = require("linkedom");
  const c = setup();
  const { document } = parseHTML(
    fs.readFileSync("frontend/index.html", "utf8"),
  );
  c.document = document;
  // Restore the real renderer while retaining the API-independent harness.
  const source = fs.readFileSync("frontend/app.js", "utf8");
  const renderer = source.slice(
    source.indexOf("function renderWorkspace()"),
    source.indexOf("async function retryProject("),
  );
  evaluate(c, renderer);
  evaluate(
    c,
    "detail={project:{id:'a',name:'movie.mp4',state:'transcribing',progress:10},cues:[]};renderWorkspace();",
  );
  const video = document.getElementById("video");
  video.currentTime = 20;
  for (const state of ["transcribing", "translating", "ready"]) {
    evaluate(
      c,
      `detail.project.state=${JSON.stringify(state)};renderWorkspace();`,
    );
    assert.ok(
      document.getElementById("video") === video,
      "player node was replaced",
    );
    assert.equal(video.currentTime, 20);
  }
});

test("draft source choices retain selection during unchanged polling", async () => {
  const { parseHTML } = require("linkedom");
  const c = setup();
  c.document = parseHTML(
    fs.readFileSync("frontend/index.html", "utf8"),
  ).document;
  const source = fs.readFileSync("frontend/app.js", "utf8");
  evaluate(
    c,
    source.slice(
      source.indexOf("function renderWorkspace()"),
      source.indexOf("async function retryProject("),
    ),
  );
  const data = {
    project: {
      id: "a",
      name: "movie.mp4",
      state: "draft",
      progress: 0,
      source_kind: "reference",
      subtitle_options: [
        { id: "srt", label: "Subs/English.srt", kind: "file", supported: true },
        { id: "pgs", label: "PGS", kind: "embedded", supported: false },
      ],
    },
    cues: [],
  };
  c.data = data;
  evaluate(c, "selected='a';detail=data;renderWorkspace();");
  const choices = c.document.getElementById("subtitle-source");
  assert.ok(choices.textContent.includes("Subs/English.srt"));
  assert.ok(
    choices.querySelector('option[value="pgs"]').hasAttribute("disabled"),
  );
  c.api = async (url) =>
    url === "/api/projects" ? [] : JSON.parse(JSON.stringify(data));
  await evaluate(c, "refresh()");
  assert.ok(c.document.getElementById("subtitle-source") === choices);
});

function editorSetup() {
  const { parseHTML } = require("linkedom");
  const c = setup();
  c.document = parseHTML(
    fs.readFileSync("frontend/index.html", "utf8"),
  ).document;
  const source = fs.readFileSync("frontend/app.js", "utf8");
  evaluate(
    c,
    source.slice(
      source.indexOf("function renderWorkspace()"),
      source.indexOf("async function retryProject("),
    ),
  );
  evaluate(
    c,
    "selected='a';detail={project:{id:'a',name:'test',state:'ready',progress:100},cues:[{id:'c1',position:0,start:0,end:2,original:'Hello',translated:''}]};renderWorkspace();",
  );
  return c;
}
test("editor has five columns and saves on blur; undo restores saved value", async () => {
  const c = editorSetup(),
    doc = c.document;
  assert.equal(doc.querySelectorAll("th").length, 5);
  assert.equal(doc.querySelector(".savebtn"), null);
  const saved = [];
  c.api = async (url, opts) => {
    const value = JSON.parse(opts.body);
    saved.push(value);
    return { id: "c1", position: 0, ...value };
  };
  const field = doc.querySelector(".translated");
  field.value = "Hola";
  field.oninput();
  assert.equal(saved.length, 0);
  field.onblur();
  await evaluate(c, "cueEditor.flush()");
  assert.equal(saved.at(-1).translated, "Hola");
  assert.ok(doc.querySelector(".translated") === field);
  doc.getElementById("undo-edit").onclick();
  await evaluate(c, "cueEditor.flush()");
  assert.equal(field.value, "");
  assert.equal(saved.at(-1).translated, "");
});
test("invalid timing stays visible and unsaved until corrected", async () => {
  const c = editorSetup();
  let saves = 0;
  c.api = async (url, opts) => {
    saves++;
    return { id: "c1", ...JSON.parse(opts.body) };
  };
  const field = c.document.querySelector(".start");
  field.value = "00:00:03.000";
  field.oninput();
  field.onblur();
  assert.equal(saves, 0);
  assert.equal(field.getAttribute("aria-invalid"), "true");
  assert.equal(evaluate(c, "dirty.size"), 1);
  field.value = "00:00:01.000";
  field.oninput();
  field.onblur();
  await evaluate(c, "cueEditor.flush()");
  assert.equal(saves, 1);
  assert.equal(field.getAttribute("aria-invalid"), null);
});

test("switching project while saving never drops a later edit", async () => {
  const c = editorSetup(),
    gate = deferred();
  c.api = async (url, opts) => {
    if (opts?.method === "PUT") {
      await gate.promise;
      return { id: "c1", position: 0, ...JSON.parse(opts.body) };
    }
    return { project: { id: "b", name: "other", state: "ready" }, cues: [] };
  };
  const first = c.document.querySelector(".translated");
  first.value = "Primero";
  first.oninput();
  first.onblur();
  const switching = evaluate(c, "select('b')");
  const next = c.document.querySelector(".original");
  next.value = "Later unsaved edit";
  next.oninput();
  gate.resolve();
  await switching;
  assert.equal(evaluate(c, "selected"), "a");
  assert.equal(next.value, "Later unsaved edit");
});
test("new server data replaces an idle editor snapshot", () => {
  const c = editorSetup();
  evaluate(c, "detail.cues[0].original='Server correction';renderWorkspace();");
  assert.equal(
    c.document.querySelector(".original").value,
    "Server correction",
  );
});
