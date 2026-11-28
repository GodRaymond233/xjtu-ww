import dashboard from "./dashboard.js";

const uuid = /^[a-f\d]{8}-[a-f\d]{4}-4[a-f\d]{3}-[89ab][a-f\d]{3}-[a-f\d]{12}$/i;
const version = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const via = { install: ["new_install", "legacy_migration"], upgrade: ["in_app_update", "manual_upgrade", "rollback"], active: ["none"] };
const fields = ["cid", "event", "ver", "prev_ver", "upgrade_via", "os"];
const minutes = new Map();

function clean(raw) {
  if (!raw || Object.keys(raw).length !== fields.length || !fields.every(k => typeof raw[k] === "string")) return null;
  const d = {...raw, cid: raw.cid.toLowerCase(), ver: raw.ver.replace(/^v/, ""), prev_ver: raw.prev_ver.replace(/^v/, "")};
  if (!uuid.test(d.cid) || !Object.hasOwn(via, d.event) || !via[d.event].includes(d.upgrade_via)
      || !version.test(d.ver) || d.ver.length > 32 || !["win", "win10", "win11", "unknown"].includes(d.os)) return null;
  if (d.event === "upgrade") {
    if (!version.test(d.prev_ver) || d.prev_ver.length > 32 || d.ver === d.prev_ver) return null;
  } else if (d.prev_ver) return null;
  return d;
}

function limited(ip, now) {
  if (!ip) return false;
  const minute = Math.floor(now / 60000);
  if (minutes.get("minute") !== minute) { minutes.clear(); minutes.set("minute", minute); }
  const count = minutes.get(ip) || 0;
  if (count >= 20 || (!count && minutes.size >= 20000)) return true;
  minutes.set(ip, count + 1);
  return false;
}

function day(now, offset = 0) {
  return new Date(+now + (8 + offset * 24) * 3600000).toISOString().slice(0, 10);
}
const json = (body, status = 200) => Response.json(body, {status, headers: {"cache-control": "no-store"}});

async function ping(req, db, now) {
  if (limited(req.headers.get("cf-connecting-ip"), +now)) return json({error:"Rate limited"}, 429);
  if (Number(req.headers.get("content-length")) > 2048) return json({error:"Payload too large"}, 413);
  const reader = req.body?.getReader(), buffer = new Uint8Array(2048);
  if (!reader) return json({error:"Empty body"}, 400);
  let size = 0;
  for (;;) {
    const {value, done} = await reader.read();
    if (done) break;
    if (size + value.length > buffer.length) { await reader.cancel(); return json({error:"Payload too large"}, 413); }
    buffer.set(value, size); size += value.length;
  }
  let d;
  try { d = clean(JSON.parse(new TextDecoder().decode(buffer.subarray(0,size)))); } catch {}
  if (!d) return json({error:"Invalid event"}, 400);
  const date = day(now), at = now.toISOString();
  await db.batch([
    db.prepare(`INSERT INTO users (cid,first_seen_date,last_seen_date,current_ver,first_via,os,updated_at)
      VALUES (?1,?2,?2,?3,?4,?5,?6) ON CONFLICT(cid) DO UPDATE SET
      last_seen_date=excluded.last_seen_date,current_ver=excluded.current_ver,os=excluded.os,updated_at=excluded.updated_at
      WHERE excluded.updated_at >= users.updated_at`).bind(d.cid,date,d.ver,d.event === "install" ? d.upgrade_via : "unknown",d.os,at),
    db.prepare("INSERT OR IGNORE INTO daily_events (day,cid,event,ver,prev_ver,upgrade_via,os,created_at) VALUES (?,?,?,?,?,?,?,?)")
      .bind(date,d.cid,d.event,d.ver,d.prev_ver,d.upgrade_via,d.os,at)
  ]);
  return new Response(null,{status:204});
}

async function authorized(header, token) {
  if (!token || !header?.startsWith("Bearer ")) return false;
  const bytes = new TextEncoder();
  const hashes = await Promise.all([header.slice(7),token].map(s => crypto.subtle.digest("SHA-256",bytes.encode(s))));
  const [a,b] = hashes.map(h => new Uint8Array(h));
  let difference = 0;
  for (let i=0; i<a.length; i++) difference |= a[i]^b[i];
  return difference === 0;
}

const counts = ["new_install","legacy_migration","in_app_update","manual_upgrade","rollback"]
  .map(v => `COUNT(DISTINCT CASE WHEN upgrade_via='${v}' THEN cid END) AS ${v}`).join(",");
async function stats(db, now, days) {
  const start = day(now,1-days);
  const [overview,versions,matrix,trend] = await db.batch([
    db.prepare(`SELECT (SELECT COUNT(*) FROM users) AS total_users,
      (SELECT COUNT(DISTINCT cid) FROM daily_events WHERE day>=?2) AS wau,
      (SELECT COUNT(DISTINCT cid) FROM daily_events WHERE day>=?3) AS mau,
      COUNT(DISTINCT cid) AS dau,${counts} FROM daily_events WHERE day=?1`).bind(day(now),day(now,-6),day(now,-29)),
    db.prepare(`SELECT ver,COUNT(DISTINCT cid) AS reached,COUNT(DISTINCT CASE WHEN day>=? THEN cid END) AS active,
      (SELECT COUNT(*) FROM users WHERE current_ver=e.ver) AS current,${counts}
      FROM daily_events e GROUP BY ver ORDER BY MAX(day) DESC,ver`).bind(start),
    db.prepare(`SELECT prev_ver,ver,upgrade_via,COUNT(DISTINCT cid) AS clients FROM daily_events
      WHERE day>=? AND event='upgrade' GROUP BY prev_ver,ver,upgrade_via ORDER BY clients DESC`).bind(start),
    db.prepare(`SELECT day,COUNT(DISTINCT cid) AS dau,${counts} FROM daily_events
      WHERE day>=? GROUP BY day ORDER BY day DESC`).bind(start)
  ]);
  return {days, day:day(now),overview:overview.results[0],versions:versions.results,upgrade_matrix:matrix.results,daily_trend:trend.results};
}

export async function handle(req, env, now = new Date()) {
  const url = new URL(req.url);
  if (req.method === "POST" && url.pathname === "/v1/ping") return ping(req,env.DB,now);
  if (req.method === "GET" && url.pathname === "/v1/stats") {
    if (!await authorized(req.headers.get("authorization"),env.ADMIN_TOKEN)) return json({error:"Unauthorized"},401);
    const days = Number(url.searchParams.get("days") || 30);
    if (!Number.isInteger(days) || days < 1 || days > 365) return json({error:"Invalid days"},400);
    return json(await stats(env.DB,now,days));
  }
  if (req.method === "GET" && url.pathname === "/health") return json({ok:true});
  if (req.method === "GET" && ["/","/dashboard"].includes(url.pathname)) return new Response(dashboard,
    {headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store","referrer-policy":"no-referrer","x-frame-options":"DENY"}});
  return json({error:"Not found"},404);
}
export default {fetch(req,env) { return handle(req,env); }};
