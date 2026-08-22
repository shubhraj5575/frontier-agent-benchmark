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
