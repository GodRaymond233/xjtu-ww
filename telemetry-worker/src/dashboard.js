export default `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>XJTU-WW 匿名活跃与更新统计</title>
<style>
:root{font:16px/1.5 system-ui;color:#172931;background:#f3f6f6}main{max-width:1160px;margin:3rem auto;padding:0 1rem}
h1{font-size:clamp(1.6rem,4vw,2.6rem)}h2{font-size:1.2rem;margin-top:2rem}section{overflow:auto}
input,select,button{font:inherit;padding:.4em;border:1px solid #98aaa9;border-radius:4px}button{background:#155d54;color:white}
table{border-collapse:collapse;width:100%;background:white}td,th{padding:.65rem;text-align:right;white-space:nowrap;border-bottom:1px solid #dde5e3}th:first-child,td:first-child{text-align:left}p{color:#455b60}
</style><main><h1>XJTU-WW 匿名活跃与更新统计</h1>
<form><label>管理令牌 <input type="password" required autocomplete="off"></label>
<label>查询范围 <select><option value="7">近 7 天</option><option value="30" selected>近 30 天</option><option value="90">近 90 天</option></select></label>
<button>查询</button></form><p role="status"></p><div id="tables"></div></main>
<script>
const f=document.querySelector('form'), note=document.querySelector('[role=status]'), tables=document.querySelector('#tables');
const names={day:'日期',ver:'版本',current:'最近一次启动',reached:'累计触达',active:'期间活跃',new_install:'首次观测（无旧配置）',legacy_migration:'首次观测（有旧配置）',in_app_update:'内置更新',manual_upgrade:'其他升级',rollback:'降版',prev_ver:'原版本',upgrade_via:'方式',clients:'客户端数',dau:'日启动活跃',wau:'7日启动活跃',mau:'30日启动活跃',total_users:'累计客户端'};
function table(title,rows){const h=document.createElement('h2');h.textContent=title;tables.append(h);
if(!rows.length){const p=document.createElement('p');p.textContent='暂无记录';tables.append(p);return}
const box=document.createElement('section'),t=document.createElement('table'),keys=Object.keys(rows[0]);
const tr=t.createTHead().insertRow();for(const k of keys){const th=document.createElement('th');th.textContent=names[k]||k;tr.append(th)}
const body=t.createTBody();for(const r of rows){const row=body.insertRow();for(const k of keys)row.insertCell().textContent=k==='upgrade_via'?(names[r[k]]||r[k]):r[k]}box.append(t);tables.append(box)}
f.onsubmit=async e=>{e.preventDefault();tables.replaceChildren();note.textContent='查询中…';
try{const r=await fetch('/v1/stats?days='+f.querySelector('select').value,{headers:{Authorization:'Bearer '+f.querySelector('input').value}});
if(!r.ok)throw Error(r.status===401?'管理令牌无效':'查询失败');const s=await r.json();note.textContent='北京时间 '+s.day+'，按随机客户端标识去重。';
table('启动活跃与今日更新',[s.overview]);table('各版本触达',s.versions);table('版本迁移',s.upgrade_matrix);table('每日趋势',s.daily_trend)}
catch(err){note.textContent=err.message}};
</script></html>`;
