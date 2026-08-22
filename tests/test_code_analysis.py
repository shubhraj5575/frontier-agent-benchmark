"""Tests for static code analysis collector."""

from pathlib import Path

from fab.telemetry.code_analysis import collect_code_telemetry


def make_project(root: Path):
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "core.py").write_text(
        '"""Core module."""\n'
        "from pkg.helpers import add\n"
        "\n"
        "def run(n):\n"
        '    """Run the thing.\n\n    Args: n.\n    """\n'
        "    if n > 10:\n"
        "        return add(n, 1)\n"
        "    for i in range(n):\n"
        "        if i % 2 == 0:\n"
        "            n += i\n"
        "    return n\n"
        "\n"
        "def _hidden():\n"
        "    return 1\n"
    )
    (root / "pkg" / "helpers.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n"
    )
    (root / "pkg" / "cycle_a.py").write_text(
        "from pkg import cycle_b\n"
    )
    (root / "pkg" / "cycle_b.py").write_text(
        "from pkg import cycle_a\n"
    )
    (root / "tests" / "test_core.py").write_text(
        "from pkg.core import run\n"
        "\n"
        "def test_run():\n"
        "    assert run(2) == 2\n"
        "# TODO: more tests\n"
    )
    (root / "README.md").write_text("# demo\n")
    return root


def test_counts_loc_and_languages(tmp_path):
    root = make_project(tmp_path / "proj")
    tel = collect_code_telemetry(root)
    assert tel.languages["python"] > 20
    assert tel.n_test_files >= 1
    assert tel.test_sloc > 0
    assert tel.readme_path == "README.md"


def test_complexity_and_docstrings(tmp_path):
    root = make_project(tmp_path / "proj")
    tel = collect_code_telemetry(root)
    m = tel.measurements()
    run_fn = next(f for f in tel.python_functions if f.name == "run")
    assert run_fn.complexity >= 4      # if + for + if
    assert run_fn.has_docstring
    hidden = next(f for f in tel.python_functions if f.name == "_hidden")
    assert not hidden.is_public and not hidden.has_docstring
    # docstring coverage over public functions: run documented, add/_hidden not public-or-documented mix
    assert m["docstring_coverage"].available
    assert 0.0 < m["docstring_coverage"].value <= 1.0
    assert m["max_complexity"].available


def test_circular_import_detected(tmp_path):
    root = make_project(tmp_path / "proj")
    tel = collect_code_telemetry(root)
    assert len(tel.circular_imports) >= 1
    cyc = tel.circular_imports[0]
    names = set(cyc)
    assert {"pkg/cycle_a.py", "pkg/cycle_b.py"} <= names


def test_duplication_estimate(tmp_path):
    dup = tmp_path / "dup"
    dup.mkdir()
    block = "\n".join(f"x_{i} = compute({i}) + validate({i})" for i in range(30))
    for name in ("a.py", "b.py"):
        (dup / name).write_text(block)
    tel = collect_code_telemetry(dup)
    assert tel.duplicate_sloc_fraction > 0.5


def test_no_fabrication_on_empty_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    tel = collect_code_telemetry(empty)
    m = tel.measurements()
    assert m["sloc_total"].value == 0          # observed zero is honest here
    assert not m["max_complexity"].available   # absent stays unavailable
    assert m["max_complexity"].provenance.value == "UNAVAILABLE"


def test_skips_venv_and_pycache(tmp_path):
    root = tmp_path / "proj"
    make_project(root)
    venv = root / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "huge.py").write_text("y = 1\n" * 1000)
    pycache = root / "pkg" / "__pycache__"
    pycache.mkdir()
    (pycache / "core.cpython-312.pyc").write_bytes(b"\x00\x01")
    tel = collect_code_telemetry(root)
    rels = {f.rel_display for f in tel.files}
    assert not any(r.startswith(".venv") or "__pycache__" in r for r in rels)


def test_todo_counting(tmp_path):
    root = make_project(tmp_path / "proj")
    tel = collect_code_telemetry(root)
    assert tel.todo_count >= 1
