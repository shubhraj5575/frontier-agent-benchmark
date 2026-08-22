"""CLI smoke tests."""

import json
import subprocess
import sys
from pathlib import Path

from fab.cli import main


def test_version(capsys):
    try:
        main(["--version"])
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    assert out.startswith("fab ")


def test_init_creates_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = main(["init", "--config", str(tmp_path / "bench.json")])
    assert rc == 0
    data = json.loads((tmp_path / "bench.json").read_text())
    assert "subjects" in data


def test_watch_wraps_command(tmp_path):
    out = tmp_path / "watch" / "session.json"
    rc = main(["watch", "--project", "demo", "--out", str(out), "--",
               sys.executable, "-c", "print(1)"])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["exit_code"] == 0
    assert data["runtime_s"] >= 0
    evs = [e["type"] for e in data["events"]]
    assert "run_started" in evs and "task_completed" in evs


def test_watch_fail_on_error(tmp_path):
    rc = main(["watch", "--fail-on-error", "--out",
               str(tmp_path / "w.json"), "--", sys.executable, "-c",
               "raise SystemExit(3)"])
    assert rc == 1


def test_ingest_reports_counts(tmp_path, capsys):
    log = tmp_path / "s.jsonl"
    log.write_text('{"type":"agent_started"}\n{"usage":{"total_tokens":1234}}\n')
    rc = main(["ingest", str(log), "--project", "x"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "agent_started: 1" in out
    assert "1234 [OBSERVED]" in out


def test_collect_on_directory(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "app.py").write_text("x = 1\n")
    (tmp_path / "bench.json").write_text(json.dumps({
        "subjects": [{"name": "proj", "path": str(proj)}]}))
    rc = main(["collect", "--config", str(tmp_path / "bench.json")])
    assert rc == 0
    assert "proj: files=1" in capsys.readouterr().out


def test_run_static_only_end_to_end(tmp_path, monkeypatch, capsys):
    import tempfile as _tf
    from tests.test_scoring import make_good_project, make_bad_project
    good = tmp_path / "good"
    make_good_project(good)
    badp = tmp_path / "bad"
    make_bad_project(badp)
    (tmp_path / "bench.json").write_text(json.dumps({
        "version": 1,
        "subjects": [
            {"name": "good", "path": str(good),
             "entrypoint": f"python -c \"import sys;sys.path.insert(0,'{good}');\""},
            {"name": "bad", "path": str(badp)},
        ]}))
    monkeypatch.chdir(_tf.mkdtemp())
    # point output into tmp dir by running from there
    import os
    os.makedirs("output", exist_ok=True)
    rc = main(["run", "--config", str(tmp_path / "bench.json"),
               "--static-only"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "leaderboard" in out
    assert (Path("output/results/results.json")).exists()
    assert (Path("output/dashboard/index.html")).exists()


def test_doctor_reports_capabilities(capsys):
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert "environment check" in out
    assert "git" in out
    assert rc in (0, 1)


def test_pages_publishes(tmp_path, monkeypatch):
    from fab.cli import DEFAULT_OUT
    monkeypatch.chdir(Path(__file__).parent.parent)
    dash = DEFAULT_OUT / "dashboard"
    dash.mkdir(parents=True, exist_ok=True)
    (dash / "index.html").write_text("<html>test dashboard</html>")
    rc = main(["pages"])
    assert rc == 0
    assert (Path("docs/index.html")).read_text().startswith("<html>")
