// The admin panel page itself. Served only after the password check in admin.js.
export const PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">
<title>Admin | HaulTimes</title><link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/style.css"><style>
.adm h1{font-family:var(--display);font-weight:800;font-stretch:78%;font-size:34px;margin:18px 0 2px}
.adm .sub{color:var(--muted);font-size:14px;margin:0 0 16px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));border-top:3px solid var(--navy);border-bottom:1px solid var(--rule)}
.kpis div{padding:12px 14px 12px 0;display:flex;flex-direction:column;gap:2px}
.kpis .k{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.kpis .v{font-family:var(--display);font-weight:800;font-stretch:80%;font-size:32px;line-height:1.1}
.kpis .s{font-size:13px;color:var(--faint)}
.adm h2{margin:28px 0 8px;padding-bottom:6px;border-bottom:2px solid var(--navy);font-family:var(--display);font-weight:800;font-stretch:85%;font-size:15px;text-transform:uppercase;letter-spacing:.06em}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:8px 32px}
.bars{display:flex;align-items:flex-end;gap:3px;height:120px;border-bottom:1px solid var(--rule);margin-top:6px}
.bars i{flex:1;background:var(--navy);min-height:1px;position:relative}
.bars i.b{background:var(--amber)}
.bx{display:flex;justify-content:space-between;font-size:12px;color:var(--faint);margin-top:4px}
.lg{font-size:13px;color:var(--muted);display:flex;gap:16px;margin-top:4px}.lg span::before{content:"";display:inline-block;width:10px;height:10px;margin-right:6px;background:var(--c)}
table.t{width:100%;border-collapse:collapse;font-size:14px}
table.t th{text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);border-bottom:2px solid var(--navy);padding:6px 8px}
table.t td{border-bottom:1px solid var(--rule-soft);padding:7px 8px;vertical-align:top}
table.t tr.hid td{color:var(--faint);text-decoration:line-through}
table.t td.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
.flt{display:flex;flex-wrap:wrap;gap:8px;align-items:end;margin:8px 0 10px}
.flt label{display:flex;flex-direction:column;font-size:12px;font-weight:700;gap:3px}
.flt input,.flt select{font:inherit;font-size:14px;min-height:38px;padding:0 8px;border:1px solid #B9C0C8;background:#fff}
.b2{font:600 14px var(--body);min-height:38px;padding:0 12px;border:1px solid var(--navy);background:#fff;cursor:pointer}
.b2.dark{background:var(--navy);color:#fff}.b2.sm{min-height:30px;font-size:13px}
code{font-size:12px;background:var(--wash);padding:1px 4px}
.muted{color:var(--faint);font-size:13px}
</style></head><body><main class="wrap adm">
<h1>HaulTimes admin</h1><p class="sub">Private. Updated <span id="upd">…</span> · <a href="/freight-market/">Freight Market page ›</a><br>Views are unique: one per person, per page, per day. Your own visits in this browser are not counted.</p>
<div class="kpis" id="kpis"></div>
<div class="cols">
<section><h2>Visitors, last 30 days</h2><div class="bars" id="ch-visits"></div><div class="bx" id="ch-visits-x"></div>
<div class="lg"><span style="--c:var(--navy)">Unique visitors per day</span></div></section>
<section><h2>Submissions, last 30 days</h2><div class="bars" id="ch-subs"></div><div class="bx" id="ch-subs-x"></div>
<div class="lg"><span style="--c:var(--navy)">Rate reports</span><span style="--c:var(--amber)">Poll answers</span></div></section>
</div>
<div class="cols">
<section><h2>Top pages, 7 days</h2><table class="t" id="pages"></table></section>
<section><h2>Where visitors came from, 7 days</h2><table class="t" id="refs"></table>
<h2>Stories shared, 7 days</h2><table class="t" id="shares"></table></section>
</div>
<div class="cols">
<section><h2>Map and lane coverage this week</h2><table class="t" id="cov"></table><p class="muted" id="cov-note"></p></section>
<section><h2>Most active reporters, 7 days</h2><table class="t" id="busy"></table>
<p class="muted">Anonymous codes. They change every week, so nobody can be tracked over time. A code with many reports on one lane may be someone trying to push a rate.</p></section>
</div>
<section><h2>Rate reports (raw data)</h2>
<form class="flt" id="flt"><label>Period<select name="days"><option value="7">7 days</option><option value="30" selected>30 days</option><option value="90">90 days</option><option value="3650">All</option></select></label>
<label>Equipment<select name="eq"><option value="">All</option><option value="van">Dry van</option><option value="reefer">Reefer</option><option value="flatbed">Flatbed</option><option value="stepdeck">Step deck</option></select></label>
<label>Market<select name="market"><option value="">All</option><option value="US">US</option><option value="CA">Canada</option><option value="XB">Cross-border</option></select></label>
<label>From<input name="o" size="3" maxlength="2" placeholder="TX"></label><label>To<input name="d" size="3" maxlength="2" placeholder="GA"></label>
<label>Reporter code<input name="voter" size="10" placeholder="optional"></label>
<label>Show<select name="hidden"><option value="">All</option><option value="1">Hidden only</option></select></label>
<button class="b2 dark" type="submit">Filter</button>
<a class="b2" href="/admin/api/export?table=rates" style="display:inline-flex;align-items:center">Download all reports (CSV)</a>
<a class="b2" href="/admin/api/export?table=polls" style="display:inline-flex;align-items:center">Poll answers (CSV)</a>
<a class="b2" href="/admin/api/export?table=views" style="display:inline-flex;align-items:center">Page views (CSV)</a></form>
<p class="muted" id="rates-count"></p>
<div class="scroll"><table class="t" id="rates"></table></div>
<p><button class="b2" id="more" hidden>Show more</button></p>
<p class="muted">Hide removes a report from the map, lane table and rate checker. It is kept in the database and can be shown again.</p></section>
<section><h2>Poll answers this week</h2><div class="scroll"><table class="t" id="polls"></table></div></section>
</main>
<script>
(function(){
try{localStorage.setItem("ht_owner","1")}catch(e){}  // opening the admin panel stops this browser from being counted
var EQ={van:"Dry van",reefer:"Reefer",flatbed:"Flatbed",stepdeck:"Step deck"},MK={US:"US",CA:"Canada",XB:"Cross-border"};
var $=function(s){return document.querySelector(s)};
var esc=function(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})};
var n=function(x){return Number(x||0).toLocaleString("en-US")};
function get(u){return fetch(u,{credentials:"same-origin"}).then(function(r){return r.json()})}
function bars(id,series,keys){
  var max=Math.max.apply(null,series.map(function(d){return keys.reduce(function(s,k){return Math.max(s,d[k])},0)}).concat([1]));
  $("#"+id).innerHTML=series.map(function(d){return keys.map(function(k,i){return '<i class="'+(i?"b":"")+'" style="height:'+(d[k]/max*100)+'%" title="'+d.day+": "+d[k]+'"></i>'}).join("")}).join("");
  $("#"+id+"-x").innerHTML="<span>"+series[0].day.slice(5)+"</span><span>"+series[series.length-1].day.slice(5)+"</span>";
}
function table(id,head,rows){$("#"+id).innerHTML="<tr>"+head.map(function(h){return"<th>"+h+"</th>"}).join("")+"</tr>"+(rows.length?rows.join(""):'<tr><td colspan="'+head.length+'" class="muted">Nothing yet.</td></tr>')}
get("/admin/api/stats").then(function(s){
  var S=s.submissions,V=s.visits;
  $("#upd").textContent=new Date(s.now).toLocaleString();
  $("#kpis").innerHTML=[["Visitors today",n(V.visitors_today),n(V.views_today)+" page views"],["Page views, 7 days",n(V.views_7d),n(V.views_30d)+" in 30 days"],
    ["Freight Market views, 7 days",n(V.market_views_7d),"the reports page"],["Rate reports, 7 days",n(S.rates_7d),n(S.rate_people_7d)+" people · "+n(S.rates_today)+" today"],
    ["Poll answers this week",n(S.polls_this_week),n(S.poll_people_this_week)+" people · last week "+n(S.polls_last_week)],["All rate reports",n(S.rates_all),n(S.rates_hidden)+" hidden"]]
    .map(function(k){return'<div><span class="k">'+k[0]+'</span><span class="v">'+k[1]+'</span><span class="s">'+k[2]+"</span></div>"}).join("");
  bars("ch-visits",s.series,["visitors"]);bars("ch-subs",s.series,["rates","polls"]);
  table("pages",["Page","Views"],V.top_pages.map(function(p){return'<tr><td><a href="'+esc(p.path)+'">'+esc(p.path)+'</a></td><td class="num">'+n(p.n)+"</td></tr>"}));
  var NET={text:"Text message",whatsapp:"WhatsApp",facebook:"Facebook",email:"Email",x:"X",copy:"Copied link",native:"Phone share menu"};
  table("shares",["Shared by","Clicks"],(V.shares||[]).map(function(p){return"<tr><td>"+esc(NET[p.net]||p.net)+'</td><td class="num">'+n(p.n)+"</td></tr>"}));
  table("refs",["Source","Views"],V.top_refs.map(function(p){return"<tr><td>"+esc(p.host)+'</td><td class="num">'+n(p.n)+"</td></tr>"}));
  table("cov",["Equipment","Areas on map","Lanes shown"],Object.keys(EQ).map(function(k){var c=s.coverage.by_equipment[k];return"<tr><td>"+EQ[k]+'</td><td class="num">'+c.areas+'</td><td class="num">'+c.lanes+"</td></tr>"}));
  $("#cov-note").textContent=s.coverage.lanes_waiting+" more lanes have some reports but not enough to show yet.";
  table("busy",["Code","Reports","Lanes",""],s.busiest.map(function(b){return"<tr><td><code>"+esc(b.voter.slice(0,10))+'</code></td><td class="num">'+b.n+'</td><td class="num">'+b.lanes+'</td><td><button class="b2 sm" data-v="'+esc(b.voter)+'">View</button></td></tr>'}));
  document.querySelectorAll("#busy [data-v]").forEach(function(b){b.onclick=function(){$("#flt [name=voter]").value=b.dataset.v.slice(0,10);load(0);$("#flt").scrollIntoView()}});
});
var off=0;
function load(o){
  off=o;var f=new FormData($("#flt")),q=new URLSearchParams();f.forEach(function(v,k){if(v)q.set(k,k==="o"||k==="d"?v.toUpperCase():v)});q.set("offset",o);
  get("/admin/api/rates?"+q).then(function(r){
    $("#rates-count").textContent=n(r.total)+" reports match.";
    var rows=r.rows.map(function(x){var cur=x.currency==="CAD"?"C$":"US$";return'<tr class="'+(x.hidden?"hid":"")+'"><td>'+esc(x.created.slice(0,16).replace("T"," "))+"</td><td>"+esc(x.load_date)+"</td><td><b>"+esc(x.o)+" → "+esc(x.d)+'</b><br><span class="muted">'+MK[x.market]+"</span></td><td>"+EQ[x.equipment]+'</td><td class="num">'+cur+n(x.amount)+'</td><td class="num">'+n(x.miles)+' mi</td><td class="num"><b>'+cur+Number(x.rpm).toFixed(2)+"</b></td><td><code>"+esc(x.voter.slice(0,10))+'</code></td><td><button class="b2 sm" data-id="'+x.id+'" data-h="'+(x.hidden?0:1)+'">'+(x.hidden?"Show":"Hide")+"</button></td></tr>"});
    var head="<tr><th>Received (UTC)</th><th>Load date</th><th>Lane</th><th>Equipment</th><th>Rate</th><th>Distance</th><th>Per mile</th><th>Reporter</th><th></th></tr>";
    $("#rates").innerHTML=(o?$("#rates").innerHTML:head)+(rows.length?rows.join(""):(o?"":'<tr><td colspan="9" class="muted">No reports yet.</td></tr>'));
    $("#more").hidden=o+100>=r.total;
    document.querySelectorAll("#rates [data-id]").forEach(function(b){b.onclick=function(){
      fetch("/admin/api/hide",{method:"POST",credentials:"same-origin",headers:{"content-type":"application/json"},body:JSON.stringify({id:b.dataset.id,hidden:b.dataset.h==="1"})}).then(function(){load(0)})}});
  });
}
$("#flt").addEventListener("submit",function(e){e.preventDefault();load(0)});
$("#more").onclick=function(){load(off+100)};
load(0);
get("/admin/api/polls").then(function(p){
  table("polls",["Area","Equipment","Hot","Normal","Slow","Answers"],p.rows.map(function(r){return"<tr><td>"+esc(r.region)+"</td><td>"+EQ[r.equipment]+'</td><td class="num">'+r.hot+'</td><td class="num">'+r.normal+'</td><td class="num">'+r.slow+'</td><td class="num"><b>'+r.n+"</b></td></tr>"}));
});
})();
</script></body></html>`;
