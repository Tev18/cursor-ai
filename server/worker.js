// Cursor AI device tracker: a small Cloudflare Worker + D1 database. Only the owner can open the dashboard.
//
//   POST /ping          the app reports itself once a minute (public; it can only write its own row)
//   GET  /admin         the dashboard page (the page itself holds no data; it asks for your admin key)
//   GET  /api/devices   (admin key)  everyone who ever used the app
//   POST /api/block     (admin key)  {id, blocked, message?}  switch a device off/on
//   POST /api/whitelist (admin key)  {on}                             new devices need your approval (default) / are allowed automatically
//   POST /api/nickname  (admin key)  {id, nickname}               your own label for a device (empty = remove)
//   POST /api/forget    (admin key)  {id}                     delete a device's row
//
// Bindings (Settings -> Bindings / Variables): DB = D1 database, ADMIN_KEY = a long secret you choose.
// Never stored: screenshots, answers, prompts, API keys, IP addresses.

const ONLINE_MS = 150000;   // heard from within 2.5 min = online
const USING_MS = 300000;    // took a capture within 5 min = using it right now

const SCHEMA = `CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY, name TEXT, display_name TEXT, platform TEXT, version TEXT,
  first_seen INTEGER, last_seen INTEGER, captures INTEGER DEFAULT 0, last_capture INTEGER DEFAULT 0,
  blocked INTEGER DEFAULT 0, block_message TEXT DEFAULT '', nickname TEXT DEFAULT '', pending INTEGER DEFAULT 0)`;
const PENDING_MESSAGE = "Waiting for the owner to approve this device. Send them your name and Device ID.";

const json = (o, status = 200) => new Response(JSON.stringify(o), {
  status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const ea = new TextEncoder().encode(a), eb = new TextEncoder().encode(b);
  let diff = ea.length ^ eb.length;
  for (let i = 0; i < Math.max(ea.length, eb.length); i++) diff |= (ea[i] || 0) ^ (eb[i] || 0);
  return diff === 0;
}
function isAdmin(request, env) {
  const key = env.ADMIN_KEY;
  if (typeof key !== "string" || key.length < 12) return false;    // refuse to run with a weak/missing key
  return safeEqual((request.headers.get("authorization") || "").replace(/^Bearer /, ""), key);
}
const clip = (v, n) => (typeof v === "string" ? v.replace(/[\u0000-\u001f<>]/g, "").trim().slice(0, n) : "");

// Whitelist mode (default ON): a device that reports for the first time is blocked until the owner approves it.
async function whitelistOn(env) {
  const row = await env.DB.prepare("SELECT value FROM settings WHERE key = 'whitelist'").first();
  return !row || row.value !== "0";
}

let ready = false;
async function ensureSchema(env) {
  if (ready) return;
  await env.DB.prepare(SCHEMA).run();
  // Older deployments have the table without the nickname column: add it once.
  const { results } = await env.DB.prepare("PRAGMA table_info(devices)").all();
  if (!results.some((c) => c.name === "nickname")) {
    await env.DB.prepare("ALTER TABLE devices ADD COLUMN nickname TEXT DEFAULT ''").run();
  }
  if (!results.some((c) => c.name === "pending")) {
    await env.DB.prepare("ALTER TABLE devices ADD COLUMN pending INTEGER DEFAULT 0").run();
  }
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)").run();
  ready = true;
}

async function handle(request, env, now = Date.now()) {
  const url = new URL(request.url);
  const path = url.pathname;

  if (request.method === "GET" && (path === "/admin" || path === "/")) {
    return new Response(ADMIN_HTML, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store",
      "content-security-policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'" } });
  }
  await ensureSchema(env);

  if (request.method === "POST" && path === "/ping") {
    let b;
    try { b = await request.json(); } catch { return json({ error: "bad json" }, 400); }
    const id = String(b && b.id || "");
    if (!/^[0-9a-f]{12}$/.test(id)) return json({ error: "bad id" }, 400);
    const captures = Number.isInteger(b.captures) && b.captures >= 0 ? Math.min(b.captures, 1e9) : 0;
    const lastCapture = Number.isFinite(b.last_capture) && b.last_capture > 0 ? Math.min(Math.round(b.last_capture * 1000), now) : 0;
    const newbie = await whitelistOn(env);   // only applies if this id is new: existing rows keep their own state
    await env.DB.prepare(
      `INSERT INTO devices (id, name, display_name, platform, version, first_seen, last_seen, captures, last_capture, blocked, pending, block_message)
       VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6, ?7, ?8, ?9, ?9, ?10)
       ON CONFLICT(id) DO UPDATE SET name = ?2, display_name = ?3, platform = ?4, version = ?5, last_seen = ?6,
         captures = MAX(devices.captures, ?7), last_capture = MAX(devices.last_capture, ?8)`)
      .bind(id, clip(b.name, 60), clip(b.display_name, 40), clip(b.platform, 20), clip(b.version, 20), now, captures, lastCapture,
            newbie ? 1 : 0, newbie ? PENDING_MESSAGE : "").run();
    const row = await env.DB.prepare("SELECT blocked, pending, block_message FROM devices WHERE id = ?1").bind(id).first();
    const reply = { allowed: !(row && row.blocked), message: (row && row.block_message) || "" };
    if (row && row.pending) reply.pending = true;     // waiting for the owner's approval (whitelist mode)
    return json(reply);
  }

  if (path.startsWith("/api/")) {
    if (!isAdmin(request, env)) return json({ error: "unauthorized" }, 401);
    if (request.method === "GET" && path === "/api/devices") {
      const { results } = await env.DB.prepare("SELECT * FROM devices ORDER BY last_seen DESC LIMIT 1000").all();
      const devices = results.map((d) => ({ ...d, blocked: !!d.blocked, pending: !!d.pending,
        online: now - d.last_seen < ONLINE_MS, using: d.last_capture > 0 && now - d.last_capture < USING_MS }));
      return json({ now, devices, online: devices.filter((d) => d.online).length, total: devices.length,
        waiting: devices.filter((d) => d.pending).length, whitelist: await whitelistOn(env) });
    }
    if (request.method === "POST" && path === "/api/whitelist") {
      let b;
      try { b = await request.json(); } catch { return json({ error: "bad json" }, 400); }
      await env.DB.prepare("INSERT INTO settings (key, value) VALUES ('whitelist', ?1) ON CONFLICT(key) DO UPDATE SET value = ?1")
        .bind(b && b.on === false ? "0" : "1").run();
      return json({ ok: true });
    }
    if (request.method === "POST" && (path === "/api/block" || path === "/api/forget" || path === "/api/nickname")) {
      let b;
      try { b = await request.json(); } catch { return json({ error: "bad json" }, 400); }
      const id = String(b && b.id || "");
      if (!/^[0-9a-f]{12}$/.test(id)) return json({ error: "bad id" }, 400);
      if (path === "/api/forget") await env.DB.prepare("DELETE FROM devices WHERE id = ?1").bind(id).run();
      else if (path === "/api/nickname") await env.DB.prepare("UPDATE devices SET nickname = ?2 WHERE id = ?1").bind(id, clip(b.nickname, 40)).run();
      else await env.DB.prepare("UPDATE devices SET blocked = ?2, pending = 0, block_message = ?3 WHERE id = ?1")
        .bind(id, b.blocked ? 1 : 0, b.blocked ? clip(b.message, 200) : "").run();
      return json({ ok: true });
    }
  }
  return json({ error: "not found" }, 404);
}

// `handle` rides along on the default export so server/test.mjs can call it with a fake clock; the runtime ignores it.
export default { fetch: (request, env) => handle(request, env), handle };

const ADMIN_HTML = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cursor AI devices</title><style>
:root{--bg:#0d0d0f;--card:#191919;--line:#34302a;--text:#f5f2ea;--mut:#b8b3a8;--gold:#d4af37;--ok:#76dca1;--bad:#ff6b6b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.4 -apple-system,system-ui,sans-serif;padding:24px}
h1{margin:0 0 4px;font-size:24px}.sub{color:var(--mut);margin-bottom:16px}
.bar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:16px}
.pill{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:6px 14px}
button{background:var(--card);color:var(--gold);border:1px solid var(--line);border-radius:8px;padding:8px 14px;font:inherit;cursor:pointer}
button.bad{color:var(--bad)}input{background:var(--card);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:10px;font:inherit;width:100%;max-width:360px}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;min-width:760px;background:var(--card)}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--mut);font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:.4px}
tr:last-child td{border-bottom:0}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;background:#6b6a65}
.on{background:var(--ok)}.pend{background:var(--gold)}.off{background:var(--bad)}.mut{color:var(--mut)}#login{max-width:420px;margin:12vh auto}.err{color:var(--bad);min-height:20px}
</style></head><body>
<div id="login"><h1>Cursor AI devices</h1><p class="sub">Owner only. Enter your admin key.</p>
<input id="key" type="password" autocomplete="off" placeholder="Admin key"> <p><button id="go">Open dashboard</button></p><div class="err" id="err"></div></div>
<div id="app" hidden><h1>Cursor AI devices</h1><div class="sub">Everyone who has ever used the app. Updates every 10 seconds.</div>
<div class="bar"><span class="pill" id="s_online"></span><span class="pill" id="s_total"></span><span class="pill" id="s_wait" hidden></span><button id="wl"></button><button id="out">Lock</button></div>
<div class="wrap"><table><thead><tr><th>Status</th><th>Name</th><th>Device</th><th>System</th><th>Version</th><th>Last seen</th><th>Captures</th><th>First seen</th><th></th></tr></thead><tbody id="rows"></tbody></table></div></div>
<script>
var KEY=sessionStorage.getItem("k")||"",WL=true;
function $(i){return document.getElementById(i)}
function ago(ms,now){if(!ms)return "never";var s=Math.max(0,Math.round((now-ms)/1000));if(s<60)return s+"s ago";if(s<3600)return Math.round(s/60)+" min ago";if(s<86400)return Math.round(s/3600)+" h ago";return Math.round(s/86400)+" d ago"}
function td(tr,text,cls){var c=document.createElement("td");c.textContent=text;if(cls)c.className=cls;tr.appendChild(c);return c}
function api(path,body){return fetch(path,{method:body?"POST":"GET",headers:{"authorization":"Bearer "+KEY,"content-type":"application/json"},body:body?JSON.stringify(body):undefined}).then(function(r){if(r.status===401)throw new Error("Wrong admin key");if(!r.ok)throw new Error("Error "+r.status);return r.json()})}
function show(d){$("login").hidden=true;$("app").hidden=false;$("s_online").textContent=d.online+" online now";$("s_total").textContent=d.total+" device"+(d.total===1?"":"s")+" ever";WL=d.whitelist;$("wl").textContent=WL?"New devices: need my approval":"New devices: allowed automatically";$("wl").title="Click to switch";
$("s_wait").hidden=!d.waiting;$("s_wait").textContent=d.waiting+" waiting for approval";$("s_wait").style.borderColor="#d4af37";
var body=$("rows");body.textContent="";
d.devices.forEach(function(x){var tr=document.createElement("tr");var c=document.createElement("td");var dot=document.createElement("span");dot.className="dot"+(x.pending?" pend":x.blocked?" off":(x.online?" on":""));c.appendChild(dot);
c.appendChild(document.createTextNode(x.pending?"Pending approval":x.blocked?"Blocked":(x.using?"Using now":(x.online?"Online":"Offline"))));tr.appendChild(c);
var nc=td(tr,x.nickname||x.display_name||"(no name)");if(x.nickname&&x.display_name&&x.display_name!==x.nickname){var sm=document.createElement("div");sm.className="mut";sm.style.fontSize="12px";sm.textContent="says: "+x.display_name;nc.appendChild(sm)}
td(tr,x.name+"  ·  "+x.id,"mut");td(tr,x.platform,"mut");td(tr,x.version,"mut");td(tr,ago(x.last_seen,d.now),x.online?"":"mut");td(tr,String(x.captures),"mut");td(tr,ago(x.first_seen,d.now),"mut");
var a=document.createElement("td");var b=document.createElement("button");b.textContent=x.pending?"Approve":x.blocked?"Allow":"Block";if(!x.blocked)b.className="bad";
b.onclick=function(){api("/api/block",{id:x.id,blocked:!x.blocked}).then(load).catch(fail)};a.appendChild(b);
var n=document.createElement("button");n.textContent="Nickname";n.style.marginLeft="8px";n.onclick=function(){var v=prompt("Nickname for "+(x.display_name||x.name)+" (leave empty to remove):",x.nickname||"");if(v!==null)api("/api/nickname",{id:x.id,nickname:v}).then(load).catch(fail)};a.appendChild(n);
var f=document.createElement("button");f.textContent="Forget";f.style.marginLeft="8px";f.onclick=function(){if(confirm("Delete "+(x.nickname||x.display_name||x.name)+" from the list?"))api("/api/forget",{id:x.id}).then(load).catch(fail)};a.appendChild(f);tr.appendChild(a);body.appendChild(tr)})}
function fail(e){sessionStorage.removeItem("k");KEY="";$("app").hidden=true;$("login").hidden=false;$("err").textContent=e.message}
function load(){if(!KEY)return;api("/api/devices").then(show).catch(fail)}
$("go").onclick=function(){KEY=$("key").value.trim();sessionStorage.setItem("k",KEY);$("err").textContent="";load()};
$("key").onkeydown=function(e){if(e.key==="Enter")$("go").click()};
$("wl").onclick=function(){if(WL&&!confirm("Allow every NEW device automatically from now on? (Devices already waiting stay blocked until you approve them.)"))return;api("/api/whitelist",{on:!WL}).then(load).catch(fail)};
$("out").onclick=function(){fail(new Error("Locked"))};
setInterval(load,10000);load();
</script></body></html>`;
