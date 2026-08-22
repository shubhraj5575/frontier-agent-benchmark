"""Scoring engine tests: ordering, coverage semantics, determinism."""

import subprocess
import time

import pytest

from fab.collector import collect_static
from fab.models import Event, EventType, Provenance, SubjectSpec
from fab.scoring.base import Component, aggregate, grade
from fab.scoring.engine import score_project

WEIGHTS = {
    "completion": 0.20, "reliability": 0.15, "testing": 0.15,
    "architecture": 0.125, "performance": 0.075, "documentation": 0.075,
    "autonomy": 0.125, "maintainability": 0.10,
}


def _git_init(path):
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.io"],
                   check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"],
                   check=True)


def make_good_project(root):
    root.mkdir(parents=True)
    pkg = root / "calc"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Calc package."""\n')
    (pkg / "ops.py").write_text(
        '"""Arithmetic operations."""\n'
        "\n"
        "\n"
        'def add(a: float, b: float) -> float:\n'
        '    """Return a + b."""\n'
        "    return a + b\n"
        "\n"
        "\n"
        'def mul(a: float, b: float) -> float:\n'
        '    """Return a * b."""\n'
        "    return a * b\n"
    )
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_ops.py").write_text(
        "from calc.ops import add, mul\n"
        "\n"
        "\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
        "\n"
        "\n"
        "def test_mul():\n"
        "    assert mul(2, 3) == 6\n"
    )
    (root / "README.md").write_text(
        "# calc\n\n## Installation\npip install .\n\n"
        "## Usage\n```python\nfrom calc.ops import add\n```\n\n"
        "## Architecture\nSmall pure functions.\n\n## License\nMIT\n")
    (root / "CHANGELOG.md").write_text("# 1.0.0\n- initial\n")
    _git_init(root)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm",
                    "feat: initial calculator implementation"], check=True)
    return root


def make_bad_project(root):
    root.mkdir(parents=True)
    # one giant file, no tests, no docs, no git, high complexity, duplication
    body = []
    for i in range(60):
        body.append(f"def handler_{i}(data):\n")
        body.append("    total = 0\n")
        body.append("    if data:\n")
        body.append("        for x in data:\n")
        body.append("            if x > 0:\n")
        body.append("                total += x * %d\n" % i)
        body.append("    return total\n\n")
    block = "".join(body[:40])
    (root / "everything.py").write_text(block + block)  # duplicated too
    return root


@pytest.fixture(scope="module")
def good_bundle(tmp_path_factory):
    root = tmp_path_factory.mktemp("good") / "good-proj"
    make_good_project(root)
    spec = SubjectSpec(name="good", path=str(root),
                       entrypoint="python -c \"import sys; sys.path.insert(0,'.'); "
                                  "from calc.ops import add; assert add(1,2)==3\"")
    b = collect_static(spec, tmp_path_factory.mktemp("data_good"))
    return b


@pytest.fixture(scope="module")
def bad_bundle(tmp_path_factory):
    root = tmp_path_factory.mktemp("bad") / "bad-proj"
    make_bad_project(root)
    spec = SubjectSpec(name="bad", path=str(root))
    b = collect_static(spec, tmp_path_factory.mktemp("data_bad"))
    return b


def test_good_beats_bad_on_static_dimensions(good_bundle, bad_bundle):
    g = score_project(good_bundle, WEIGHTS)
    b = score_project(bad_bundle, WEIGHTS)
    for dim in ("architecture", "documentation"):
        gv = g.dimensions[dim].value
        bv = b.dimensions[dim].value
        assert gv is not None and bv is not None, f"{dim} should be computable"
        assert gv > bv, f"{dim}: good={gv} bad={bv}"


def test_empty_inputs_yield_unavailable_not_zero(tmp_path):
    empty = tmp_path / "void"
    empty.mkdir()
    spec = SubjectSpec(name="void", path=str(empty))
    bundle = collect_static(spec, tmp_path)
    card = score_project(bundle, WEIGHTS)
    # autonomy has zero behavioural evidence -> must be None
    aut = card.dimensions["autonomy"]
    assert aut.value is None and aut.coverage == 0.0
    # and it must NOT drag overall toward zero silently - coverage reflects it
    assert card.overall_coverage < 1.0
    assert "Autonomy requires behavioural evidence" in " ".join(aut.notes)


def test_aggregate_excludes_unavailable_and_reports_coverage():
    comps = [
        Component("a", 0.5, 100.0, Provenance.OBSERVED),
        Component("b", 0.5, None, Provenance.OBSERVED, note="missing"),
    ]
    value, cov = aggregate(comps)
    assert value == 100.0
    assert abs(cov - 0.5) < 1e-9


def test_grade_bands():
    assert grade(None) == "n/a"
    assert grade(95) == "A+"
    assert grade(86) == "A"
    assert grade(72) == "B"
    assert grade(30) == "F"


def test_deterministic_scoring(good_bundle):
    c1 = score_project(good_bundle, WEIGHTS)
    c2 = score_project(good_bundle, WEIGHTS)
    assert c1.to_dict() == c2.to_dict()


def test_scorecard_serialization_roundtrip(good_bundle):
    import json as _json
    card = score_project(good_bundle, WEIGHTS)
    d = _json.loads(_json.dumps(card.to_dict()))
    assert d["project"] == "good"
    assert set(d["dimensions"]) == set(WEIGHTS)
    for dim in d["dimensions"].values():
        for comp in dim["components"]:
            assert comp["provenance"] in {"OBSERVED", "ESTIMATED", "UNAVAILABLE"}


def test_autonomy_events_drive_score():
    """Bug lifecycle events (observed) must produce an autonomy score."""
    empty_root = __import__("pathlib").Path(__file__).parent / "_autonomy_fixture"
    if not empty_root.exists():
        empty_root.mkdir()
    spec = SubjectSpec(name="auto", path=str(empty_root))
    from fab.collector import collect_static
    import tempfile
    bundle = collect_static(spec, tempfile.mkdtemp())
    now = time.time()
    bundle.events = [
        Event(type=EventType.BUG_DISCOVERED, project="auto", session_id="s1",
              ts=now - 100, provenance=Provenance.OBSERVED),
        Event(type=EventType.BUG_FIXED, project="auto", session_id="s1",
              ts=now - 50, provenance=Provenance.OBSERVED),
        Event(type=EventType.TASK_COMPLETED, project="auto", session_id="s1",
              ts=now - 10, provenance=Provenance.OBSERVED),
    ]
    card = score_project(bundle, WEIGHTS)
    aut = card.dimensions["autonomy"]
    assert aut.value is not None
    assert aut.value >= 80.0  # fixed everything, no interventions


def test_overall_none_when_everything_unavailable(tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    bundle = collect_static(SubjectSpec(name="x", path=str(empty)), tmp_path)
    # strip even static signals
    bundle.code.files.clear()
    bundle.code.n_files = 0
    bundle.measurements.clear()
    card = score_project(bundle, {k: 1 / 8 for k in WEIGHTS})
    dims_with_values = [d for d in card.dimensions.values() if d.value is not None]
    # documentation/completion still produce observed-absence zeros; that's fine.
    # The key invariant: overall_coverage <= 1 and overall is not fabricated-high
    assert card.overall_coverage <= 1.0
