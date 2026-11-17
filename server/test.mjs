// node server/test.mjs   (Node 22+; uses the built-in SQLite, which is what D1 is)
import { DatabaseSync } from "node:sqlite";
import assert from "node:assert/strict";
import worker from "./worker.js";
const handle = worker.handle;

function d1() {
  const db = new DatabaseSync(":memory:");
  return { prepare(sql) {
    let args = [];
    const st = { bind(...a) { args = a; return st; },
      async run() { db.prepare(sql).run(...args); return {}; },
      async first() { return db.prepare(sql).get(...args) ?? null; },
      async all() { return { results: db.prepare(sql).all(...args) }; } };
    return st; } };
}
const env = { DB: d1(), ADMIN_KEY: "owner-secret-key-123" };
const T0 = 1_800_000_000_000;
const post = (p, body, key) => new Request("https://x" + p, { method: "POST", headers: key ? { authorization: "Bearer " + key } : {}, body: JSON.stringify(body) });
const get = (p, key) => new Request("https://x" + p, { headers: key ? { authorization: "Bearer " + key } : {} });
const ping = (o, now) => handle(post("/ping", { id: "a1b2c3d4e5f6", name: "Ali-MacBook", display_name: "Ali", platform: "mac", version: "1.0.4", captures: 0, last_capture: 0, ...o }), env, now);

let r = await ping({}, T0); assert.equal(r.status, 200); assert.deepEqual(await r.json(), { allowed: true, message: "" });
r = await handle(get("/api/devices"), env, T0); assert.equal(r.status, 401);                       // no key
r = await handle(get("/api/devices", "wrong"), env, T0); assert.equal(r.status, 401);
r = await handle(get("/api/devices", "owner-secret-key-123"), env, T0 + 1000); let j = await r.json();
assert.equal(j.total, 1); assert.equal(j.online, 1); assert.equal(j.devices[0].display_name, "Ali"); assert.equal(j.devices[0].using, false);
// takes a capture: shows "using"
await ping({ captures: 3, last_capture: (T0 + 5000) / 1000 }, T0 + 6000);
j = await (await handle(get("/api/devices", "owner-secret-key-123"), env, T0 + 7000)).json(); assert.equal(j.devices[0].using, true); assert.equal(j.devices[0].captures, 3);
// time passes: offline
j = await (await handle(get("/api/devices", "owner-secret-key-123"), env, T0 + 10 * 60_000)).json(); assert.equal(j.devices[0].online, false); assert.equal(j.devices[0].using, false);
// counters never go backwards; first_seen kept
await ping({ captures: 1 }, T0 + 20_000); j = await (await handle(get("/api/devices", "owner-secret-key-123"), env, T0 + 21_000)).json();
assert.equal(j.devices[0].captures, 3); assert.equal(j.devices[0].first_seen, T0);
// block -> next ping says not allowed
r = await handle(post("/api/block", { id: "a1b2c3d4e5f6", blocked: true, message: "Switched off" }, "owner-secret-key-123"), env, T0); assert.equal((await r.json()).ok, true);
assert.deepEqual(await (await ping({}, T0 + 30_000)).json(), { allowed: false, message: "Switched off" });
await handle(post("/api/block", { id: "a1b2c3d4e5f6", blocked: false }, "owner-secret-key-123"), env, T0); assert.equal((await (await ping({}, T0 + 40_000)).json()).allowed, true);
// nickname: owner-set, survives later pings, needs the key, markup stripped, empty removes it
r = await handle(post("/api/nickname", { id: "a1b2c3d4e5f6", nickname: "Ali (cousin)" }), env, T0); assert.equal(r.status, 401);
r = await handle(post("/api/nickname", { id: "a1b2c3d4e5f6", nickname: "Ali <b>(cousin)</b>" }, "owner-secret-key-123"), env, T0); assert.equal((await r.json()).ok, true);
await ping({ display_name: "Different" }, T0 + 50_000);
j = await (await handle(get("/api/devices", "owner-secret-key-123"), env, T0 + 51_000)).json(); assert.equal(j.devices[0].nickname, "Ali b(cousin)/b"); assert.equal(j.devices[0].display_name, "Different");
await handle(post("/api/nickname", { id: "a1b2c3d4e5f6", nickname: "" }, "owner-secret-key-123"), env, T0);
j = await (await handle(get("/api/devices", "owner-secret-key-123"), env, T0 + 52_000)).json(); assert.equal(j.devices[0].nickname, "");
// bad input
assert.equal((await ping({ id: "nothex" }, T0)).status, 400);
assert.equal((await handle(new Request("https://x/ping", { method: "POST", body: "{" }), env, T0)).status, 400);
r = await handle(post("/api/block", { id: "a1b2c3d4e5f6", blocked: true }), env, T0); assert.equal(r.status, 401);       // block needs the key
// markup in names is stripped
await ping({ id: "0123456789ab", name: "<img src=x onerror=alert(1)>", display_name: "<b>x</b>" }, T0);
j = await (await handle(get("/api/devices", "owner-secret-key-123"), env, T0 + 1)).json(); assert.ok(!JSON.stringify(j).includes("<"));
// forget
await handle(post("/api/forget", { id: "0123456789ab" }, "owner-secret-key-123"), env, T0);
j = await (await handle(get("/api/devices", "owner-secret-key-123"), env, T0 + 1)).json(); assert.equal(j.total, 1);
// weak/missing admin key is refused even if it "matches"
assert.equal((await handle(get("/api/devices", "short"), { ...env, ADMIN_KEY: "short" }, T0)).status, 401);
assert.equal((await handle(get("/api/devices", ""), { ...env, ADMIN_KEY: undefined }, T0)).status, 401);
// dashboard page holds no data and is locked down
r = await handle(get("/admin"), env, T0); const html = await r.text(); assert.equal(r.status, 200); assert.ok(html.includes("Admin key")); assert.ok(!html.includes("Ali"));
assert.ok(r.headers.get("content-security-policy").includes("default-src 'none'"));
// migration: a table created by an older worker (no nickname column) is upgraded in place, rows kept
{
  const { default: fresh } = await import("./worker.js?migrate");
  const old = new DatabaseSync(":memory:");
  old.exec("CREATE TABLE devices (id TEXT PRIMARY KEY, name TEXT, display_name TEXT, platform TEXT, version TEXT, first_seen INTEGER, last_seen INTEGER, captures INTEGER DEFAULT 0, last_capture INTEGER DEFAULT 0, blocked INTEGER DEFAULT 0, block_message TEXT DEFAULT '')");
  old.exec("INSERT INTO devices (id, name, first_seen, last_seen) VALUES ('ffffffffffff', 'Old PC', 1, 2)");
  const wrap = { prepare(sql) { let a = []; const st = { bind(...x) { a = x; return st; }, async run() { old.prepare(sql).run(...a); return {}; }, async first() { return old.prepare(sql).get(...a) ?? null; }, async all() { return { results: old.prepare(sql).all(...a) }; } }; return st; } };
  const e2 = { DB: wrap, ADMIN_KEY: "owner-secret-key-123" };
  const j2 = await (await fresh.handle(get("/api/devices", "owner-secret-key-123"), e2, T0)).json();
  assert.equal(j2.devices[0].name, "Old PC"); assert.equal(j2.devices[0].nickname, "");
  await fresh.handle(post("/api/nickname", { id: "ffffffffffff", nickname: "Dad" }, "owner-secret-key-123"), e2, T0);
  assert.equal((await (await fresh.handle(get("/api/devices", "owner-secret-key-123"), e2, T0)).json()).devices[0].nickname, "Dad");
}
console.log("worker tests OK");
