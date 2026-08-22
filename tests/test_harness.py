"""Tests for process monitor + harness parsers."""

import sys
import textwrap
import time

from fab.telemetry.harness import (Harness, detect_test_plan,
                                   parse_cargo, parse_go, parse_jest,
                                   parse_pytest)
from fab.telemetry.process_monitor import (HAS_PSUTIL, measurements_from_run,
                                           run_monitored)
from fab.telemetry.workspace import make_workspace


def test_run_monitored_measures_sleep():
    mr = run_monitored([sys.executable, "-c", "import time; time.sleep(0.8)"],
                       timeout_s=10)
    assert mr.exit_code == 0
    assert 0.5 <= mr.duration_s <= 6.0
    if HAS_PSUTIL or True:
        # samples may be sparse on fast commands but the mechanism must work
        assert isinstance(mr.samples, list)
    m = measurements_from_run(mr, "tests")
    assert m["tests.exit_code"].value == 0
    assert m["tests.duration_s"].available


def test_run_monitored_timeout_kills():
    mr = run_monitored([sys.executable, "-c", "import time; time.sleep(60)"],
                       timeout_s=1)
    assert mr.timed_out
    assert mr.duration_s < 5


def test_parse_pytest_summary():
    out = "3 failed, 12 passed, 2 skipped, 1 error in 1.23s"
    c = parse_pytest(out, "")
    assert c == {"passed": 12, "failed": 3, "errors": 1, "skipped": 2}


def test_parse_pytest_all_pass():
    c = parse_pytest("7 passed in 0.05s", "")
    assert c["passed"] == 7 and c["failed"] == 0


def test_parse_jest_summary():
    out = "Test Suites: 1 failed, 2 passed, 3 total\n" \
          "Tests:       1 failed, 20 passed, 2 skipped, 23 total"
    c = parse_jest(out, "")
    assert c["passed"] == 20 and c["failed"] == 1 and c["skipped"] == 2


def test_parse_go():
    out = "--- PASS: TestAdd (0.00s)\n--- FAIL: TestSub (0.00s)\nFAIL\n" \
          "ok  	example.com/pkg	0.01s"
    c = parse_go(out, "")
    assert c["passed"] == 1 and c["failed"] == 1


def test_parse_cargo():
    out = "test result: ok. 9 passed; 0 failed; 1 ignored; 0 measured"
    c = parse_cargo(out, "")
    assert c["passed"] == 9 and c["skipped"] == 1


def test_detect_test_plan_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n")
    plan = detect_test_plan(tmp_path)
    assert plan.framework == "pytest"


def _mini_py_project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "app.py").write_text(
        textwrap.dedent("""
            def add(a, b):
                return a + b
            def broken(a, b):
                return a - b  # intentional bug: should add
        """))
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text(textwrap.dedent("""
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        from app import add, broken

        def test_add():
            assert add(1, 2) == 3

        def test_broken_is_actually_add():
            assert broken(4, 2) == 6
    """))
    return root


def test_harness_end_to_end_counts_and_events(tmp_path):
    root = _mini_py_project(tmp_path)
    ws, meta = make_workspace("demo", root, tmp_path / "fabdata")
    h = Harness(timeout_s=120)
    plan = detect_test_plan(ws)
    pr = h.test_phase(plan, "demo", meta.session_id, ws)
    assert plan.framework == "pytest"
    assert pr.counts.get("failed") == 1
    assert pr.counts.get("passed") >= 1
    assert not pr.ok
    evs = pr.events("demo", meta.session_id)
    types = [e.type.name for e in evs]
    assert "TEST_RUN" in types and "TEST_FAILED" in types
    bugs = [e for e in evs if e.type.name == "BUG_DISCOVERED"]
    assert bugs and bugs[0].provenance.value == "ESTIMATED"


def test_workspace_isolation_original_untouched(tmp_path):
    root = _mini_py_project(tmp_path)
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                    if p.is_file())
    ws, meta = make_workspace("iso", root, tmp_path / "fab")
    (ws / "junk.txt").write_text("scratch data")
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                   if p.is_file())
    assert before == after
    assert (ws / "junk.txt").exists()


def test_measurements_provenance_on_real_run(tmp_path):
    mr = run_monitored([sys.executable, "-c", "print('ok')"], timeout_s=30)
    m = measurements_from_run(mr, "smoke")
    assert m["smoke.exit_code"].provenance.value == "OBSERVED"
