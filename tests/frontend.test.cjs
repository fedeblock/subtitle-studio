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
