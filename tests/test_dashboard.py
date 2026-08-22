"""Dashboard generator tests."""

import json
import re
import tempfile
from pathlib import Path

from fab.dashboard.generator import build_payload, render_dashboard, \
    write_dashboard
from fab.analysis.comparison import compare
from fab.scoring.engine import score_project

WEIGHTS = {
    "completion": 0.20, "reliability": 0.15, "testing": 0.15,
    "architecture": 0.125, "performance": 0.075, "documentation": 0.075,
    "autonomy": 0.125, "maintainability": 0.10,
}


def _build(tmp_root):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from test_scoring import make_good_project
    from test_scoring import make_bad_project
    from fab.models import SubjectSpec
    from fab.collector import collect_static

    bundles, cards = {}, {}
    for maker, nm in ((make_good_project, "good-proj"),
                      (make_bad_project, "bad-proj")):
        root = tmp_root / nm
        maker(root)
        b = collect_static(SubjectSpec(name=nm, path=str(root)), tmp_root)
        bundles[nm] = b
        cards[nm] = score_project(b, WEIGHTS)
    return bundles, cards, compare(bundles, cards)


def test_payload_structure():
    tmp = Path(tempfile.mkdtemp())
    bundles, cards, comp = _build(tmp)
    payload = build_payload(bundles, cards, comp, {"generated_iso": "x"})
    assert set(payload) >= {"meta", "leaderboard", "projects", "comparison",
                            "dim_order", "TYPE_COLORS"}
    p = payload["projects"]["good-proj"]
    assert set(p) >= {"overall", "grade", "coverage", "dimensions", "git",
                      "code", "events", "metrics", "failure_analysis"}
    assert len(payload["leaderboard"]) == 2


def test_render_is_selfcontained_html():
    tmp = Path(tempfile.mkdtemp())
    bundles, cards, comp = _build(tmp)
    html = render_dashboard(bundles, cards, comp, {"version": "1.0"})
    assert html.startswith("<!DOCTYPE html>")
    # no external resources
    assert not re.search(r'src=["\']http', html)
    assert not re.search(r'href=["\']http', html)
    # embedded data present and parseable after unescaping
    m = re.search(r"window\.FAB_DATA=(.*?);</script>", html, re.S)
    assert m
    raw = m.group(1).replace("<\\/", "</")
    data = json.loads(raw)
    assert set(data["projects"]) == {"good-proj", "bad-proj"}
    assert "Leaderboard" in html


def test_write_dashboard_file():
    tmp = Path(tempfile.mkdtemp())
    bundles, cards, comp = _build(tmp)
    out = write_dashboard(tmp / "dash" / "index.html", bundles, cards, comp,
                          {"generated_iso": "now"})
    assert out.exists() and out.stat().st_size > 20_000


def test_dashboard_javascript_renders_all_panels():
    """Execute the embedded JS against the real payload (node required)."""
    import re as _re
    import shutil as _sh
    import subprocess as _sp

    if not _sh.which("node"):
        import pytest
        pytest.skip("node not available")
    tmp = Path(tempfile.mkdtemp())
    bundles, cards, comp = _build(tmp)
    html = render_dashboard(bundles, cards, comp, {"generated_iso": "x"})
    scripts = _re.findall(r"<script>([\s\S]*?)</script>", html)
    assert len(scripts) == 2
    harness_js = r'''
const fs=require("fs");
function makeEl(){return new Proxy({innerHTML:"",textContent:"",value:""},{
 get(t,k){if(k in t)return t[k];
  if(["setAttribute","appendChild","addEventListener"].includes(k))return()=>{};
  return undefined;},
 set(t,k,v){t[k]=v;return true;}});}
const els={};
global.document={getElementById(id){return els[id]||(els[id]=makeEl());},
 querySelectorAll(){return [];},createElement(){return makeEl();}};
global.window={innerWidth:1400};
const scripts=JSON.parse(fs.readFileSync(process.argv[1+1],"utf8"));
eval(scripts[0]);global.D=window.FAB_DATA;eval(scripts[1]);
const checks={board:els["board"].innerHTML.includes("<td"),
 projects:els["projects"].innerHTML.length>500,
 timeline:(els["timeline"].innerHTML||"").length>50,
 matrix:els["matrix"].innerHTML.length>50,
 verdicts:els["verdicts"].innerHTML.length>50,
 stream:els["stream"].innerHTML.length>100};
console.log(JSON.stringify(checks));
'''
    script_file = tmp / "render_check.js"
    script_file.write_text(harness_js)
    payload_file = tmp / "scripts.json"
    payload_file.write_text(json.dumps(scripts))
    sp = _sp.run(["node", str(script_file), str(payload_file)],
                 capture_output=True, text=True)
    assert sp.returncode == 0, sp.stderr
    checks = json.loads(sp.stdout.strip().splitlines()[-1])
    assert all(checks.values()), checks
