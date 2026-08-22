"""Exporter and final-report tests."""

import csv
import io
import json
import tempfile
from pathlib import Path

from fab.analysis.comparison import compare
from fab.report.exporters import export_csv, export_json, export_markdown, \
    write_exports
from fab.report.final_report import generate_final_report
from fab.scoring.engine import score_project

WEIGHTS = {
    "completion": 0.20, "reliability": 0.15, "testing": 0.15,
    "architecture": 0.125, "performance": 0.075, "documentation": 0.075,
    "autonomy": 0.125, "maintainability": 0.10,
}


def _build(tmp_root):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from test_scoring import make_bad_project, make_good_project
    from fab.models import SubjectSpec
    from fab.collector import collect_static

    groot = tmp_root / "good-proj"
    make_good_project(groot)
    bad = tmp_root / "bad-proj"
    make_bad_project(bad)
    specs = [SubjectSpec(name="good-proj", path=str(groot)),
             SubjectSpec(name="bad-proj", path=str(bad))]
    bundles, cards = {}, {}
    for s in specs:
        b = collect_static(s, tmp_root)
        bundles[s.name] = b
        cards[s.name] = score_project(b, WEIGHTS)
    comparison = compare(bundles, cards)
    return bundles, cards, comparison


def test_export_json_roundtrip():
    tmp = Path(tempfile.mkdtemp())
    bundles, cards, comp = _build(tmp)
    raw = export_json(bundles, cards, comp, {"generated_iso": "t"})
    data = json.loads(raw)
    assert set(data) >= {"meta", "leaderboard", "projects", "comparison"}
    assert len(data["projects"]) == 2
    # provenance survives serialization
    blob = raw
    assert '"OBSERVED"' in blob and '"UNAVAILABLE"' in blob


def test_export_csv_provenance_column():
    tmp = Path(tempfile.mkdtemp())
    bundles, cards, comp = _build(tmp)
    rows = list(csv.reader(io.StringIO(export_csv(bundles, cards, comp))))
    header = rows[0]
    assert header == ["project", "section", "metric", "value",
                      "provenance", "source", "note"]
    body = rows[1:]
    prov_idx = header.index("provenance")
    vals = {r[prov_idx] for r in body}
    assert {"OBSERVED", "UNAVAILABLE"} <= vals


def test_markdown_report_contains_nine_questions():
    tmp = Path(tempfile.mkdtemp())
    bundles, cards, comp = _build(tmp)
    md = generate_final_report(bundles, cards, comp, {"version": "1.0"})
    for q in ("most complete", "most reliable", "strongest architecture",
              "best tests", "best performance", "strongest autonomy",
              "compute most efficiently", "most failures",
              "recovers from failures"):
        assert q in md.lower(), f"missing question: {q}"
    for label in ("OBSERVED", "ESTIMATED", "UNAVAILABLE"):
        assert label in md
    # leaderboard present with both projects
    assert "good-proj" in md and "bad-proj" in md


def test_unavailable_verdict_is_honest():
    """A single subject without dynamic data must not fabricate verdicts."""
    tmp = Path(tempfile.mkdtemp())
    sys_path = str(Path(__file__).parent)
    import sys
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    from test_scoring import make_bad_project
    from fab.models import SubjectSpec
    from fab.collector import collect_static

    root = tmp / "lonely"
    make_bad_project(root)
    b = collect_static(SubjectSpec(name="lonely", path=str(root)), tmp)
    card = score_project(b, WEIGHTS)
    comp = compare({"lonely": b}, {"lonely": card})
    md = generate_final_report({"lonely": b}, {"lonely": card}, comp, {})
    assert "**UNAVAILABLE**" in md      # performance/autonomy questions say so


def test_write_exports_creates_files():
    tmp = Path(tempfile.mkdtemp())
    bundles, cards, comp = _build(tmp)
    paths = write_exports(tmp / "out", bundles, cards, comp,
                          {"generated_iso": "now", "version": "1.0"})
    assert paths["json"].exists() and paths["csv"].exists()
    assert paths["markdown"].exists()
    assert paths["json"].stat().st_size > 1000


def test_manifest_pins_reproducibility():
    from fab.report.manifest import build_manifest
    tmp = Path(tempfile.mkdtemp())
    bundles, cards, comp = _build(tmp)
    m = build_manifest(bundles, cards, {"generated_iso": "t",
                                        "monitor_backend": "test"})
    assert m["fab_version"]
    assert "scoring_weights" in m and abs(sum(m["scoring_weights"].values()) - 1) < 1e-9
    for name, subj in m["subjects"].items():
        assert subj["file_checksums_sha256"], "checksums must pin inputs"
        assert all(len(v) == 64 for v in subj["file_checksums_sha256"].values())
