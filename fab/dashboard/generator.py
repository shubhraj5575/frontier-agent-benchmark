"""Self-contained HTML dashboard generator.

Produces a single offline-capable ``index.html`` (no CDN, no external
assets) with: leaderboard, per-project radar cards, event timeline, filterable
event stream, comparison heatmap, failure/recovery stats and the provenance
legend.  All data is embedded as JSON; rendering is vanilla JS + SVG.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..analysis.comparison import ComparisonResult
from ..collector import ProjectBundle
from ..scoring.base import Scorecard

DIM_ORDER = ["completion", "reliability", "testing", "architecture",
             "performance", "documentation", "autonomy", "maintainability"]
DIM_LABELS = {d: d.replace("_", " ").title() for d in DIM_ORDER}

SEV_COLORS = {
    "success": "#34d399", "error": "#f87171", "critical": "#fb7185",
    "warn": "#fbbf24", "info": "#60a5fa",
}
TYPE_COLORS = {
    "agent_started": "#60a5fa", "task_completed": "#34d399",
    "test_failed": "#f87171", "test_passed": "#4ade80", "test_run": "#94a3b8",
    "bug_discovered": "#fb923c", "bug_fixed": "#2dd4bf",
    "commit_created": "#c084fc", "benchmark_completed": "#38bdf8",
    "build_failed": "#ef4444", "build_succeeded": "#22c55e",
    "milestone_reached": "#facc15", "error_observed": "#f87171",
    "retry_attempted": "#fbbf24", "tool_call": "#818cf8",
    "intervention_requested": "#f43f5e", "file_edited": "#a3e635",
    "coverage_reported": "#2dd4bf", "tokens_reported": "#94a3b8",
}


def build_payload(bundles: dict[str, ProjectBundle],
                  cards: dict[str, Scorecard],
                  comparison: ComparisonResult,
                  meta: dict[str, Any]) -> dict[str, Any]:
    projects = {}
    for name in sorted(bundles):
        b, c = bundles[name], cards[name]
        td = b.to_dict()
        peak_rss = None
        for ph in b.phases:
            if ph.run is not None and ph.run.peak_rss_mb is not None:
                peak_rss = max(peak_rss or 0, ph.run.peak_rss_mb)
        cpu_s = sum((ph.run.cpu_core_seconds_est or 0) for ph in b.phases)
        wall = sum(ph.run.duration_s for ph in b.phases if ph.run is not None)

        tests = next(({"passed": ph.counts.get("passed", 0),
                       "failed": ph.counts.get("failed", 0),
                       "errors": ph.counts.get("errors", 0),
                       "skipped": ph.counts.get("skipped", 0),
                       "duration_s": round(ph.run.duration_s, 2) if ph.run else None,
                       "ok": ph.ok}
                      for ph in b.phases if ph.phase == "tests"), None)
        build = next(({"ok": ph.ok,
                       "duration_s": round(ph.run.duration_s, 2) if ph.run else None}
                      for ph in b.phases if ph.phase == "build"), None)
        smoke = next(({"ok": ph.ok,
                       "duration_s": round(ph.run.duration_s, 2) if ph.run else None}
                      for ph in b.phases if ph.phase == "smoke"), None)

        m = b.measurements

        def md(key):
            mes = m.get(key)
            if not mes:
                return {"value": None, "provenance": "UNAVAILABLE"}
            return mes.to_dict()

        events = []
        for e in sorted(b.events, key=lambda x: x.ts or 9e18):
            events.append({
                "ts": e.ts, "type": e.type.value, "severity": e.severity,
                "message": (e.message or "")[:160],
                "provenance": e.provenance.value,
                "data_sha": (e.data or {}).get("sha"),
            })
        fa = comparison.failure_analysis.get(name, {})
        eff = comparison.efficiency.get(name, {})

        projects[name] = {
            "overall": c.to_dict()["overall"],
            "grade": c.to_dict()["grade"],
            "coverage": c.to_dict()["overall_coverage"],
            "dimensions": {d: {
                "value": (c.dimensions[d].value
                          if c.dimensions[d].value is not None else None),
                "coverage": c.dimensions[d].coverage,
            } for d in DIM_ORDER if d in c.dimensions},
            "components": {d: [comp.to_dict()
                               for comp in c.dimensions[d].components]
                           for d in c.dimensions},
            "notes": {d: c.dimensions[d].notes for d in c.dimensions},
            "git": {
                "is_repo": bool(b.git and b.git.is_git_repo),
                "total_commits": (b.git.total_commits if b.git else 0),
                "first_commit_iso": td["git"]["first_commit_iso"] if b.git else None,
                "last_commit_iso": td["git"]["last_commit_iso"] if b.git else None,
                "branch": (b.git.branch if b.git else None),
                "activity": b.activity,
            },
            "code": td.get("code") or {},
            "session": td.get("session"),
            "phases_summary": {"build": build, "tests": tests, "smoke": smoke},
            "resources": {"peak_rss_mb": (round(peak_rss, 1) if peak_rss else None),
                          "cpu_core_seconds_est": (round(cpu_s, 2) if cpu_s else None),
                          "wall_seconds": round(wall, 2) if wall else None},
            "metrics": {
                "tokens_total": md("tokens.total"),
                "tools_calls": md("tools.calls"),
                "loc_total": md("sloc_total"),
                "coverage_pct": md("coverage.percent"),
                "commits_total": md("commits_total"),
            },
            "failure_analysis": fa,
            "efficiency": eff,
            "events": events,
        }
    return {
        "meta": meta,
        "dim_order": DIM_ORDER,
        "dim_labels": DIM_LABELS,
        "TYPE_COLORS": TYPE_COLORS,
        "SEV_COLORS": SEV_COLORS,
        "leaderboard": [
            {"project": p, **{k: projects[p][k]
                              for k in ("overall", "grade", "coverage")}}
            for p in sorted(projects,
                            key=lambda x: -(projects[x]["overall"] or -1))
        ],
        "comparison": comparison.to_dict(),
        "projects": projects,
    }


def render_dashboard(bundles: dict[str, ProjectBundle],
                     cards: dict[str, Scorecard],
                     comparison: ComparisonResult,
                     meta: dict[str, Any]) -> str:
    payload = build_payload(bundles, cards, comparison, meta)
    data_json = json.dumps(payload).replace("</", "<\\/")
    return _TEMPLATE.replace("__FAB_DATA__", data_json)


def write_dashboard(out_path: Path, bundles, cards, comparison,
                    meta) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_dashboard(bundles, cards, comparison, meta),
                        encoding="utf-8")
    return out_path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Frontier Agent Benchmark</title>
<style>
:root{
  --bg:#0b1020;--bg2:#0f1729;--card:#131c31;--card2:#18233c;
  --line:#24304d;--txt:#dbe4f5;--mut:#7d8db1;--acc:#6ea8fe;
  --good:#34d399;--bad:#f87171;--warn:#fbbf24;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);
  font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  padding-bottom:60px}
a{color:var(--acc);text-decoration:none}
.wrap{max-width:1240px;margin:0 auto;padding:0 20px}
header{background:linear-gradient(180deg,#101a30,#0b1020);border-bottom:1px solid var(--line);
  padding:26px 0 18px;margin-bottom:22px}
h1{font-size:22px;font-weight:700;letter-spacing:.3px;display:flex;align-items:center;gap:10px}
h1 .logo{width:26px;height:26px;border-radius:7px;background:linear-gradient(135deg,#6ea8fe,#9f7aea);
  display:inline-flex;align-items:center;justify-content:center;font-size:14px;color:#fff}
.sub{color:var(--mut);margin-top:4px;font-size:13px}
.chips{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.chip{font-size:11px;padding:3px 10px;border-radius:999px;border:1px solid var(--line);color:var(--mut)}
.chip b{font-weight:600}
h2{font-size:15px;font-weight:650;margin:28px 0 12px;color:#cdd9f2;
  display:flex;align-items:center;gap:8px}
h2::before{content:"";width:3px;height:16px;background:var(--acc);border-radius:2px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--mut);text-align:left;font-weight:600;padding:8px 10px;
  border-bottom:1px solid var(--line);white-space:nowrap;cursor:pointer;user-select:none}
td{padding:8px 10px;border-bottom:1px solid #1c2740;vertical-align:middle}
tr:last-child td{border-bottom:none}
tbody tr:hover{background:#16203a}
.num{text-align:right;font-variant-numeric:tabular-nums}
.pill{display:inline-block;padding:1px 9px;border-radius:999px;font-size:11px;font-weight:600}
.pill.OBSERVED{background:rgba(52,211,153,.12);color:var(--good)}
.pill.ESTIMATED{background:rgba(251,191,36,.12);color:var(--warn)}
.pill.UNAVAILABLE{background:rgba(125,141,177,.12);color:var(--mut)}
.grade{display:inline-flex;width:34px;height:34px;border-radius:50%;align-items:center;
  justify-content:center;font-weight:700;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(370px,1fr));gap:16px}
.proj .head{display:flex;align-items:center;gap:12px;margin-bottom:10px}
.proj .name{font-size:16px;font-weight:700}
.proj .meta{color:var(--mut);font-size:12px}
.scorebar{height:7px;background:#0d1425;border-radius:99px;overflow:hidden;flex:1}
.scorebar i{display:block;height:100%;border-radius:99px}
.kv{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}
.kv div{background:var(--bg2);border:1px solid var(--line);border-radius:8px;padding:7px 9px}
.kv .k{color:var(--mut);font-size:10.5px;text-transform:uppercase;letter-spacing:.4px}
.kv .v{font-size:14px;font-weight:650;margin-top:2px;font-variant-numeric:tabular-nums}
.kv .p{font-size:9.5px;margin-top:1px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
select,input[type=text]{background:var(--bg2);color:var(--txt);border:1px solid var(--line);
  border-radius:8px;padding:6px 10px;font-size:12.5px}
.evt{padding:6px 10px;border-bottom:1px solid #1c2740;display:flex;gap:10px;
  align-items:baseline;font-size:12.5px}
.evt:hover{background:#16203a}
.evt .t{color:var(--mut);font-variant-numeric:tabular-nums;white-space:nowrap;font-size:11.5px}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;align-self:center}
.evt .ty{font-weight:650;white-space:nowrap}
.legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;font-size:11.5px;color:var(--mut)}
.legend span{display:inline-flex;align-items:center;gap:5px}
.matrix td{text-align:center;font-variant-numeric:tabular-nums}
.verdicts li{margin:7px 0 7px 18px}
footer{margin-top:40px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:14px}
.muted{color:var(--mut)}
.small{font-size:12px}
.spark{margin-top:8px}
.rank{color:var(--mut);font-weight:600}
.top1 .name{color:#fde68a}
@media(max-width:720px){.kv{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<header><div class="wrap">
  <h1><span class="logo">FAB</span> Frontier Agent Benchmark</h1>
  <div class="sub" id="subtitle"></div>
  <div class="chips" id="chips"></div>
</div></header>

<div class="wrap">

<h2>Leaderboard</h2>
<div class="card" style="overflow-x:auto"><table id="board"></table></div>

<h2>Projects</h2>
<div class="grid" id="projects"></div>

<h2>Timeline</h2>
<div class="card"><svg id="timeline" width="100%" height="220"></svg>
<div class="legend" id="tl_legend"></div></div>

<h2>Comparative analysis</h2>
<div class="grid" style="grid-template-columns:1fr 1fr">
  <div class="card matrix-wrap" style="overflow-x:auto"><table class="matrix" id="matrix"></table></div>
  <div class="card"><ul class="verdicts" id="verdicts"></ul></div>
</div>

<h2>Failures &amp; recovery</h2>
<div class="card"><table id="failtable"></table></div>

<h2>Event stream</h2>
<div class="filters">
 <select id="f_proj"><option value="">all projects</option></select>
 <select id="f_type"><option value="">all event types</option></select>
 <select id="f_sev"><option value="">all severities</option>
   <option>info</option><option>success</option><option>warn</option>
   <option>error</option><option>critical</option></select>
 <input type="text" id="f_q" placeholder="search message...">
 <span class="muted small" id="evt_count"></span>
</div>
<div class="card" id="stream" style="max-height:480px;overflow-y:auto"></div>

<footer id="foot"></footer>
</div>

<script>window.FAB_DATA=__FAB_DATA__;</script>
<script>
const D = window.FAB_DATA;
const esc = s => String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmtN = v => v==null ? '<span class="muted">n/a</span>' : (typeof v==="number"? (Math.round(v*100)/100).toLocaleString() : esc(v));
function provPill(p){return `<span class="pill ${esc(p)}">${esc(p)}</span>`;}
function scoreColor(v){if(v==null)return"#475569";return v>=85?"#34d399":v>=70?"#6ea8fe":v>=55?"#fbbf24":v>=40?"#fb923c":"#f87171";}
function gradeColor(g){return {A:"#34d399","A+":"#34d399",B:"#6ea8fe","B+":"#6ea8fe",C:"#fbbf24","C+":"#fbbf24",D:"#fb923c",F:"#f87171"}[g]||"#475569";}

/* subtitle + chips */
(function(){
  const m=D.meta||{};
  document.getElementById("subtitle").textContent =
    `Observability & benchmarking for autonomous AI engineering agents` +
    (m.generated_iso?` - generated ${m.generated_iso}`:"");
  const chips=[];
  chips.push(`<span class="chip">subjects <b>${Object.keys(D.projects).length}</b></span>`);
  let obs=0,est=0,una=0;
  Object.values(D.projects).forEach(p=>{
    Object.values(p.events).forEach(e=>{if(e.provenance==="OBSERVED")obs++;else if(e.provenance==="ESTIMATED")est++;else una++;});
  });
  chips.push(`<span class="chip">events observed <b>${obs}</b></span>`);
  chips.push(`<span class="chip">estimated <b>${est}</b></span>`);
  chips.push(`<span class="chip">unavailable <b>${una}</b></span>`);
  document.getElementById("chips").innerHTML=chips.join("");
})();

/* leaderboard */
(function(){
  const dims=D.dim_order;
  const cols=[{k:"rank",label:"#",sortable:false},{k:"project",label:"Project",sortable:true},
    {k:"overall",label:"Overall",sortable:true},{k:"grade",label:"Grade",sortable:true},
    {k:"coverage",label:"Data coverage",sortable:true}].concat(
    dims.map(d=>({k:"d_"+d,label:D.dim_labels[d],sortable:true})));
  let sortKey=null,dir=-1;
  function rows(){
    const arr=D.leaderboard.map(r=>r);
    if(sortKey){
      arr.sort((a,b)=>{
        const va=a[sortKey],vb=b[sortKey];
        if(va==null&&vb==null)return 0;if(va==null)return 1;if(vb==null)return -1;
        return (typeof va==="string"?va.localeCompare(vb):va-vb)*dir*-1*-1*(dir<0?-1:1)||0;
      });
      arr.sort((a,b)=>{const va=a[sortKey],vb=b[sortKey];
        if(va==null&&vb==null)return 0;if(va==null)return 1;if(vb==null)return -1;
        return dir*(typeof va==="string"?va.localeCompare(vb):va-vb);});
    }
    return arr;
  }
  function draw(){
    let html="<thead><tr>"+cols.map(c=>`<th data-k="${c.k}" class="${['rank','overall','coverage'].includes(c.k)||c.k.startsWith('d_')?'num':''}">${c.label}${sortKey===c.k?(dir<0?" ▼":" ▲"):''}</th>`).join("")+"</tr></thead><tbody>";
    rows().forEach((r,i)=>{
      const ov=r.overall;
      const cls=(i===0&&ov!=null)?"top1":"";
      html+=`<tr class="${cls}"><td class="rank num">${i+1}</td>`;
      html+=`<td class="name"><b>${esc(r.project)}</b></td>`;
      html+=`<td class="num"><div style="display:flex;align-items:center;gap:8px;min-width:120px">
        <div class="scorebar"><i style="width:${ov==null?0:Math.min(100,ov)}%;background:${scoreColor(ov)}"></i></div>
        <span>${fmtN(ov)}</span></div></td>`;
      html+=`<td class="num"><span class="grade" style="background:${gradeColor(r.grade)}22;color:${gradeColor(r.grade)};border:1px solid ${gradeColor(r.grade)}55">${esc(r.grade||"n/a")}</span></td>`;
      html+=`<td class="num muted">${(r.coverage*100).toFixed(0)}%</td>`;
      dims.forEach(d=>{const dv=r.project&&D.projects[r.project].dimensions[d];
        const v=dv?dv.value:null;
        html+=`<td class="num" style="${v!=null?`color:${scoreColor(v)}`:'color:#475569'}">${v==null?"n/a":v.toFixed(1)}</td>`;});
      html+="</tr>";
    });
    document.getElementById("board").innerHTML=html+"</tbody>";
    document.querySelectorAll("#board th").forEach(th=>th.onclick=()=>{
      const k=th.dataset.k;
      if(k==="rank")return;
      if(sortKey===k)dir*=-1;else{sortKey=k;dir=-1;}
      draw();});
  }
  draw();
})();

/* project cards with radar */
(function(){
  const wrap=document.getElementById("projects");
  function radar(dims){
    const n=dims.length,R=62,cx=86,cy=78;
    const pt=(i,f)=>{const a=-Math.PI/2+i*2*Math.PI/n;return[cx+R*f*Math.cos(a),cy+R*f*Math.sin(a)];};
    let s="";
    [0.25,0.5,0.75,1].forEach(f=>{s+=`<polygon points="${
      dims.map((_,i)=>pt(i,f).map(x=>x.toFixed(1)).join(",")).join(" ")
    }" fill="none" stroke="#24304d"/>`;});
    dims.forEach((_,i)=>{const[x,y]=pt(i,1);s+=`<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#24304d"/>`;});
    const vals=dims.map(d=>d.value==null?0:Math.max(0,Math.min(100,d.value))/100);
    const poly=dims.map((_,i)=>pt(i,vals[i]).map(x=>x.toFixed(1)).join(",")).join(" ");
    s+=`<polygon points="${poly}" fill="rgba(110,168,254,.25)" stroke="#6ea8fe" stroke-width="1.6"/>`;
    dims.forEach((d,i)=>{const[x,y]=pt(i,1.22);
      const lbl=d.label.split(" ")[0];
      const anchor=Math.abs(x-cx)<6?"middle":(x>cx?"start":"end");
      s+=`<text x="${x}" y="${y}" font-size="8.6" fill="${d.value==null?"#475569":"#9fb2d8"}" text-anchor="${anchor}">${lbl}${d.value==null?" (n/a)":""}</text>`;});
    return `<svg width="172" height="156" viewBox="0 0 172 156">${s}</svg>`;
  }
  function kv(label,payload,fmt){
    const prov=payload&&payload.provenance;
    const val=payload?payload.value:null;
    return `<div><div class="k">${label}</div>
      <div class="v">${val==null?"n/a":fmt(val)}</div>
      <div class="p">${provPill(prov||"UNAVAILABLE")}</div></div>`;
  }
  wrap.innerHTML=Object.keys(D.projects).sort().map(name=>{
    const p=D.projects[name];
    const dims=D.dim_order.map(d=>({label:D.dim_labels[d],
      value:p.dimensions[d]?p.dimensions[d].value:null}));
    const ov=p.overall;
    const g=p.session||{};
    const t=p.metrics.tokens_total;
    const git=p.git;
    const tests=p.phases_summary.tests;
    const build=p.phases_summary.build;
    const res=p.resources;
    const status = build==null?"static-only":
        (build.ok?(tests?(tests.ok?"healthy":"failing-tests"):"no-suite"):"build-broken");
    const statusColor={ "healthy":"#34d399","failing-tests":"#fbbf24","build-broken":"#f87171","no-suite":"#94a3b8","static-only":"#7d8db1" }[status];
    const spark = (git.activity&&git.activity.length)?(()=>{
      const a=git.activity.slice(-30);const mx=Math.max(...a.map(x=>x.commits),1);
      return `<svg class="spark" width="100%" height="30" preserveAspectRatio="none" viewBox="0 0 300 30">${
        a.map((x,i)=>{const w=300/a.length;const h=4+(x.commits/mx)*22;
          return `<rect x="${(i*w).toFixed(1)}" y="${30-h}" width="${(w-2).toFixed(1)}" height="${h.toFixed(1)}" rx="1.5" fill="#6ea8fe88"/>`;}).join("")
      }</svg>`;})():"";
    return `<div class="card proj" id="proj_${esc(name)}">
      <div class="head">
        <span class="grade" style="background:${gradeColor(p.grade)}22;color:${gradeColor(p.grade)};border:1px solid ${gradeColor(p.grade)}55">${esc(p.grade||"n/a")}</span>
        <div style="flex:1">
          <div class="name">${esc(name)}</div>
          <div class="meta">overall <b style="color:${scoreColor(ov)}">${ov==null?"n/a":ov.toFixed(1)}</b>/100 · data coverage ${(p.coverage*100).toFixed(0)}% · <span style="color:${statusColor}">● ${status}</span></div>
        </div>
        ${radar(dims)}
      </div>
      ${spark}
      <div class="kv">
        ${kv("commits",p.metrics.commits_total,v=>v.toLocaleString())}
        ${kv("SLOC",p.metrics.loc_total,v=>v.toLocaleString())}
        ${kv("tokens",t,v=>v>=1000?(v/1000).toFixed(1)+"k":v)}
        ${kv("peak RAM",{value:res.peak_rss_mb,provenance:res.peak_rss_mb!=null?"OBSERVED":"UNAVAILABLE"},v=>v+" MB")}
        ${kv("CPU core-s",{value:res.cpu_core_seconds_est,provenance:res.cpu_core_seconds_est!=null?"ESTIMATED":"UNAVAILABLE"},v=>v+"s")}
        ${kv("wall time",{value:res.wall_seconds,provenance:res.wall_seconds!=null?"OBSERVED":"UNAVAILABLE"},v=>v+"s")}
      </div>
      <div class="small muted" style="margin-top:9px">
        git: ${git.is_repo?`${git.total_commits} commits${git.branch?" · "+esc(git.branch):""}`:"not a repo"}
        · tests: ${tests?`${tests.passed}✓ ${tests.failed}✗ ${tests.errors}⚠`:"none executed"}
        · coverage: ${p.metrics.coverage_pct.value!=null?p.metrics.coverage_pct.value+"%":"n/a"}
      </div>
    </div>`;
  }).join("");
})();

/* timeline */
(function(){
  const svg=document.getElementById("timeline");
  const all=[];
  Object.values(D.projects).forEach(p=>p.events.forEach(e=>{if(e.ts!=null)all.push({proj:Object.keys(D.projects).find(k=>D.projects[k]===p),...e});}));
  all.sort((a,b)=>a.ts-b.ts);
  const names=Object.keys(D.projects).sort();
  const W=Math.max(900,window.innerWidth-80),H=Math.max(140,names.length*46+30);
  svg.setAttribute("viewBox",`0 0 ${W} ${H}`);svg.setAttribute("height",H);
  if(!all.length){svg.innerHTML=`<text x="20" y="40" fill="#7d8db1">No timestamped events available.</text>`;return;}
  const padL=130,padR=30,t0=all[0].ts,t1=all[all.length-1].ts+1;
  const x=t=>padL+(W-padL-padR)*(t-t0)/(t1-t0);
  let grid="";
  const span=t1-t0;
  const step=span/6;
  for(let i=0;i<=6;i++){
    const gx=x(t0+i*step);
    const d=new Date((t0+i*step)*1000);
    grid+=`<line x1="${gx}" y1="10" x2="${gx}" y2="${H-24}" stroke="#1c2740"/>
      <text x="${gx}" y="${H-8}" fill="#7d8db1" font-size="10" text-anchor="middle">${d.toISOString().slice(11,19)}</text>`;
  }
  let rows="";
  names.forEach((nm,row)=>{
    const y=30+row*44;
    rows+=`<text x="8" y="${y+4}" fill="#9fb2d8" font-size="11.5">${esc(nm)}</text>
      <line x1="${padL}" y1="${y}" x2="${W-padR}" y2="${y}" stroke="#24304d"/>`;
    all.filter(e=>e.proj===nm).forEach(e=>{
      const c=D.TYPE_COLORS&&D.TYPE_COLORS[e.type]||"#94a3b8";
      rows+=`<circle cx="${x(e.ts)}" cy="${y}" r="5" fill="${c}" opacity=".92"><title>${esc(e.type)} - ${esc(e.message)} [${e.provenance}]</title></circle>`;
    });
  });
  svg.innerHTML=grid+rows;
  document.getElementById("tl_legend").innerHTML=
    Object.entries({"commit_created":"#c084fc","build_failed":"#ef4444","build_succeeded":"#22c55e","test_failed":"#f87171","test_passed":"#4ade80","bug_discovered":"#fb923c","bug_fixed":"#2dd4bf","milestone_reached":"#facc15","task_completed":"#34d399"})
    .map(([k,c])=>`<span><i class="dot" style="display:inline-block;background:${c}"></i>${k.replace(/_/g," ")}</span>`).join("");
})();

/* comparison matrix */
(function(){
  const names=Object.keys(D.projects).sort();
  const M=D.comparison.matrix||{};
  let html="<thead><tr><th>Δ overall</th>"+names.map(n=>`<th>${esc(n)}</th>`).join("")+"</tr></thead><tbody>";
  names.forEach(a=>{
    html+=`<tr><td><b>${esc(a)}</b></td>`;
    names.forEach(b=>{
      const cell=(M[a]&&M[a][b])||{};
      const d=cell.delta;
      if(a===b){html+='<td class="muted">–</td>';}
      else if(d==null){html+='<td class="muted">n/a</td>';}
      else{
        const inten=Math.min(1,Math.abs(d)/40);
        const col=d>0?`rgba(52,211,153,${0.08+inten*.3})`:`rgba(248,113,113,${0.08+inten*.3})`;
        html+=`<td style="background:${col};color:${d>0?"#34d399":"#f87171"}">${d>0?"+":""}${d.toFixed(1)}</td>`;
      }
    });
    html+="</tr>";
  });
  document.getElementById("matrix").innerHTML=html+"</tbody>";

  /* verdicts */
  const v=D.comparison.verdicts||{};
  const items=[
    ["Most complete","most_complete"],["Most reliable","most_reliable"],
    ["Strongest architecture","strongest_architecture"],["Best tests","best_tests"],
    ["Best performance","best_performance"],["Strongest autonomy","strongest_autonomy"],
    ["Most maintainable","most_maintainable"],["Compute efficiency","most_efficient_compute"],
    ["Most failures","most_failures"],["Best failure recovery","best_failure_recovery"]];
  document.getElementById("verdicts").innerHTML=items.map(([lbl,k])=>{
    const a=v[k]||{};const p=a.project;
    const sc=a.score!=null?` (${Number(a.score).toFixed(1)})`:"";
    return `<li><span class="muted">${lbl}:</span> ${
      p?`<b>${esc(p)}</b>${sc}`:'<span class="pill UNAVAILABLE">UNAVAILABLE</span>'}</li>`;
  }).join("");
})();

/* failure table */
(function(){
  const fa=D.comparison.failure_analysis||{};
  const names=Object.keys(fa).sort();
  if(!names.length){document.getElementById("failtable").innerHTML='<span class="muted">no failure analysis available</span>';return;}
  let html="<thead><tr><th>Project</th><th class='num'>Build fails</th><th class='num'>Test fails</th><th class='num'>Errors</th><th class='num'>Recovered</th><th class='num'>Persisting</th><th class='num'>Recovery rate</th><th class='num'>MTTR (s)</th></tr></thead><tbody>";
  names.forEach(n=>{
    const f=fa[n];
    const rr=f.recovery_rate==null?"n/a":(f.recovery_rate*100).toFixed(0)+"%";
    html+=`<tr><td><b>${esc(n)}</b></td>
      <td class="num">${f.build_failures}</td><td class="num">${f.test_failures}</td>
      <td class="num">${f.errors_observed}</td><td class="num">${f.recovered}</td>
      <td class="num">${f.persisting}</td>
      <td class="num" style="color:${f.recovery_rate==null?"#7d8db1":f.recovery_rate>=0.5?"#34d399":"#fbbf24"}">${rr}</td>
      <td class="num">${f.mean_time_to_recovery_s==null?"n/a":f.mean_time_to_recovery_s}</td></tr>`;
  });
  document.getElementById("failtable").innerHTML=html+"</tbody>";
})();

/* event stream */
(function(){
  const stream=document.getElementById("stream");
  const fProj=document.getElementById("f_proj"),fType=document.getElementById("f_type"),
        fSev=document.getElementById("f_sev"),fQ=document.getElementById("f_q");
  const rows=[];
  Object.entries(D.projects).forEach(([nm,p])=>{
    p.events.forEach(e=>rows.push({proj:nm,...e}));
  });
  rows.sort((a,b)=>(b.ts||0)-(a.ts||0));
  [...new Set(Object.keys(D.projects).sort())].forEach(n=>{const o=document.createElement("option");o.textContent=n;fProj.appendChild(o);});
  [...new Set(rows.map(r=>r.type))].sort().forEach(t=>{const o=document.createElement("option");o.textContent=t;fType.appendChild(o);});
  function draw(){
    const q=fQ.value.toLowerCase();
    const shown=rows.filter(r=>
      (!fProj.value||r.proj===fProj.value)&&
      (!fType.value||r.type===fType.value)&&
      (!fSev.value||r.severity===fSev.value)&&
      (!q||(r.message||"").toLowerCase().includes(q))).slice(0,400);
    document.getElementById("evt_count").textContent=`showing ${shown.length} of ${rows.length}`;
    stream.innerHTML=shown.map(r=>{
      const t=r.ts?new Date(r.ts*1000).toISOString().replace("T"," ").slice(0,19):"(undated)";
      const c=D.TYPE_COLORS&&D.TYPE_COLORS[r.type]||"#94a3b8";
      return `<div class="evt"><span class="t">${t}</span>
        <span class="dot" style="background:${c}"></span>
        <span class="ty" style="color:${c}">${esc(r.type.replace(/_/g," "))}</span>
        <span style="flex:1">${esc(r.message||"")}</span>
        <span>${provPill(r.provenance)}</span></div>`;
    }).join("")||'<div class="muted" style="padding:14px">no events match filters</div>';
  }
  [fProj,fType,fSev].forEach(s=>s.onchange=draw);
  fQ.oninput=draw;
  draw();
})();

/* footer */
document.getElementById("foot").innerHTML=
  `${esc((D.meta&&D.meta.note)||"All values carry OBSERVED / ESTIMATED / UNAVAILABLE provenance. Nothing unavailable was inferred into existence.")}
   <br>Scores are deterministic functions of telemetry - formulas in docs/METRICS.md.
   Generated by FAB v${esc((D.meta&&D.meta.version)||"1.0")}.`;
</script>
</body>
</html>
"""
