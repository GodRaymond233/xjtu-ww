import {test} from "node:test";
import assert from "node:assert/strict";
import {DatabaseSync} from "node:sqlite";
import {readFileSync} from "node:fs";
import {handle} from "../src/index.js";

function fixture() {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(readFileSync(new URL("../schema.sql",import.meta.url),"utf8"));
  const env = {ADMIN_TOKEN: "test-only", DB: {
    prepare(sql) { return {bind(...args) { return () => {
      const stmt = sqlite.prepare(sql);
      const indexed = /\?1/.test(sql);
      const values = indexed ? [Object.fromEntries(args.map((v,i) => [String(i+1),v]))] : args;
      if (sql.trimStart().startsWith("SELECT")) return {results:stmt.all(...values)};
      stmt.run(...values); return {};
    }; }}; }, batch(statements) { return statements.map(f=>f()); }
  }};
  return {env, ping: (data,time) => handle(new Request("https://test/v1/ping",{method:"POST",body:JSON.stringify(data)}),env,time),
    stats: async time => (await handle(new Request("https://test/v1/stats?days=7",{headers:{authorization:"Bearer test-only"}}),env,time)).json()};
}
const data = {cid:"4ff5d9c3-a3fe-478a-b5c8-3838409d45fe",event:"install",ver:"v1.5.1",prev_ver:"",os:"win11",upgrade_via:"new_install"};

test("daily and version counts deduplicate retries, split UTC+8 days and attribute committed upgrades",async()=>{
  const f=fixture(), first=new Date("2026-11-27T15:59Z"), next=new Date("2026-11-27T16:01Z");
  for(let i=0;i<2;i++) assert.equal((await f.ping(data,first)).status,204);
  const up={...data,event:"upgrade",upgrade_via:"in_app_update",prev_ver:"1.5.1",ver:"1.5.2"};
  for(let i=0;i<2;i++) assert.equal((await f.ping(up,next)).status,204);
  const s=await f.stats(next);
  assert.deepEqual([s.overview.total_users,s.overview.dau,s.overview.wau,s.overview.mau,s.overview.in_app_update],[1,1,1,1,1]);
  assert.equal(s.versions.find(v=>v.ver==="1.5.2").current,1);
  assert.deepEqual(s.daily_trend.map(r=>r.day),["2026-11-28","2026-11-27"]);
  assert.equal(s.upgrade_matrix[0].clients,1);
});
test("stats require bearer and intake rejects unexpected identifiers and invalid combinations",async()=>{
  const f=fixture();
  for(const data2 of [{...data,cid:"not-a-uuid"},{...data,ip:"extra"},{...data,event:"upgrade"},{...data,ver:"dev-build"}])
    assert.equal((await f.ping(data2)).status,400);
  assert.equal((await f.ping({...data,extra:"x".repeat(2100)})).status,413);
  assert.equal((await handle(new Request("https://test/v1/stats"),f.env)).status,401);
});
