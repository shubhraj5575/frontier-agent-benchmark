"""Test / build / smoke-run execution harness.

The harness runs inside an isolated workspace copy (never the original repo).
Framework detection is file-based; result parsing uses each tool's summary
output.  All counts parsed from actual tool output are OBSERVED; coverage is
OBSERVED only when a coverage tool produced a machine-readable report,
otherwise UNAVAILABLE.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..models import Event, EventType, Measurement, Provenance
from .process_monitor import MonitoredRun, measurements_from_run, run_monitored

SOURCE = "harness"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

@dataclass
class TestPlan:
    framework: str            # pytest|unittest|jest|vitest|mocha|go|cargo|none
    cmd: list[str]
    label: str


@dataclass
class BuildPlan:
    name: str
    cmd: list[str] | None     # None => nothing to build for this stack


def _has(root: Path, *names: str) -> bool:
    return any(root.joinpath(n).exists() for n in names)


def detect_test_plan(root: Path, override: str | None = None) -> TestPlan:
    if override:
        import shlex
        return TestPlan(framework="custom", cmd=shlex.split(override), label="tests")
    if _has(root, "pyproject.toml", "pytest.ini", "setup.cfg") or root.joinpath("tests").is_dir():
        if shutil.which("pytest"):
            return TestPlan("pytest", ["pytest", "-q", "--no-header"], "pytest")
        return TestPlan("unittest", ["python3", "-m", "unittest", "discover",
                                     "-s", "tests", "-v"], "unittest")
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        scripts = data.get("scripts") or {}
        if shutil.which("npx"):
            if any((root / f).exists() for f in ("vitest.config.js", "vitest.config.ts")):
                return TestPlan("vitest", ["npx", "vitest", "run"], "vitest")
            if any((root / f).exists() for f in ("jest.config.js", "jest.config.ts")) or \
                    "test" in scripts and "jest" in str(scripts.get("test")):
                return TestPlan("jest", ["npx", "jest"], "jest")
            if "test" in scripts:
                return TestPlan("npm-test", ["npm", "test", "--silent"], "npm test")
    if _has(root, "go.mod"):
        return TestPlan("go", ["go", "test", "./..."], "go test")
    if _has(root, "Cargo.toml"):
        return TestPlan("cargo", ["cargo", "test", "--quiet"], "cargo test")
    return TestPlan("none", [], "none")


def detect_build_plan(root: Path, override: str | None = None) -> BuildPlan:
    if override:
        import shlex
        return BuildPlan("custom", shlex.split(override))
    pkg = root / "package.json"
    if pkg.exists():
        try:
            scripts = (json.loads(pkg.read_text(encoding="utf-8"))
                       .get("scripts") or {})
        except Exception:
            scripts = {}
        if "build" in scripts and shutil.which("npm"):
            return BuildPlan("npm-build", ["npm", "run", "build", "--silent"])
    if _has(root, "Cargo.toml"):
        return BuildPlan("cargo-build", ["cargo", "build", "--quiet"])
    if _has(root, "go.mod"):
        return BuildPlan("go-build", ["go", "build", "./..."])
    if _has(root, "pyproject.toml", "setup.py"):
        # python projects have no mandatory build step; compile check suffices
        return BuildPlan("py-compileall", None)
    return BuildPlan("none", None)


# ---------------------------------------------------------------------------
# Output parsers (exact counts from observed tool output -> OBSERVED)
# ---------------------------------------------------------------------------

_PYTEST_PASS_RE = re.compile(r"(\d+) passed")
_PYTEST_FAIL_RE = re.compile(r"(\d+) failed")
_PYTEST_ERR_RE = re.compile(r"(?<![\w])(\d+) errors?")
_PYTEST_SKIP_RE = re.compile(r"(\d+) skipped")


def parse_pytest(out: str, err: str) -> dict[str, int]:
    text = out + "\n" + err
    res = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for key, rx in (("passed", _PYTEST_PASS_RE), ("failed", _PYTEST_FAIL_RE),
                    ("errors", _PYTEST_ERR_RE), ("skipped", _PYTEST_SKIP_RE)):
        m = rx.search(text)
        if m:
            res[key] = int(m.group(1))
    return res


_JEST_SUMMARY_RE = re.compile(
    r"Tests:\s+(?:(\d+)\s+passed)?[,\s]*(?: (\d+)\s+failed)?[,\s]*(?:(\d+)\s+skipped)?",
)


def parse_jest(out: str, err: str) -> dict[str, int]:
    res = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    text = out + "\n" + err
    m = re.search(r"Tests:\s+(.*)", text)
    if m:
        seg = m.group(1)
        pm = re.search(r"(\d+) passed", seg)
        fm = re.search(r"(\d+) failed", seg)
        sm = re.search(r"(\d+) skipped", seg)
        im = re.search(r"(\d+) incomplete", seg)
        res["passed"] = int(pm.group(1)) if pm else 0
        res["failed"] = int(fm.group(1)) if fm else 0
        res["skipped"] = (int(sm.group(1)) if sm else 0) + \
                         (int(im.group(1)) if im else 0)
    tm = re.search(r"Test Suites:\s+(.*)", text)
    if tm and "failed" in tm.group(1):
        fm2 = re.search(r"(\d+) failed", tm.group(1))
        if fm2 and not res["failed"]:
            res["failed"] = int(fm2.group(1))
    return res


_GO_OK_RE = re.compile(r"^ok\s+(\S+)", re.M)
_GO_FAIL_RE = re.compile(r"^FAIL", re.M)
_GO_TESTCOUNT_RE = re.compile(r"--- (?:PASS|FAIL): \S+")


def parse_go(out: str, err: str) -> dict[str, int]:
    text = out + "\n" + err
    fails = len(_GO_FAIL_RE.findall(text))
    passes = len(re.findall(r"--- PASS:", text))
    return {"passed": passes, "failed": fails, "errors": 0, "skipped": 0}


_CARGO_RES_RE = re.compile(
    r"test result:\s*(\w+)\.\s*(\d+) passed;\s*(\d+) failed;\s*(\d+) ignored;")


def parse_cargo(out: str, err: str) -> dict[str, int]:
    res = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for m in _CARGO_RES_RE.finditer(out + "\n" + err):
        res["passed"] += int(m.group(2))
        res["failed"] += int(m.group(3))
        res["skipped"] += int(m.group(4))
    return res


PARSERS = {
    "pytest": parse_pytest,
    "unittest": parse_pytest,
    "jest": parse_jest,
    "vitest": parse_jest,
    "mocha": parse_jest,
    "npm-test": parse_jest,
    "go": parse_go,
    "cargo": parse_cargo,
}


# ---------------------------------------------------------------------------
# Coverage extraction (only when a real report exists)
# ---------------------------------------------------------------------------

_COV_LINE_TOTALS = re.compile(
    r"(?:TOTAL|total).*?(\d+(?:\.\d+)?)\s*%", re.I)


def extract_coverage(workspace: Path) -> tuple[float | None, str]:
    """Look for a machine-readable coverage report.  Returns (percent, source)."""
    cov_json = workspace / "coverage.json"
    if cov_json.exists():
        try:
            data = json.loads(cov_json.read_text(encoding="utf-8"))
            t = data.get("totals", {})
            if "percent_covered" in t:
                return float(t["percent_covered"]), "coverage.py json"
        except Exception:
            pass
    lcov = workspace / "lcov.info"
    if lcov.exists():
        try:
            lines_hit = lines_found = 0
            for ln in lcov.read_text(encoding="utf-8").splitlines():
                if ln.startswith("LF:"):
                    lines_found += int(ln[3:])
                elif ln.startswith("LH:"):
                    lines_hit += int(ln[3:])
            if lines_found:
                return round(100.0 * lines_hit / lines_found, 2), "lcov"
        except Exception:
            pass
    return None, ""


def has_coverage_tool() -> bool:
    return shutil.which("coverage") is not None


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

@dataclass
class PhaseResult:
    phase: str                 # build|tests|smoke
    run: MonitoredRun | None
    counts: dict[str, int] = field(default_factory=dict)
    coverage_pct: float | None = None
    coverage_source: str = ""
    ok: bool = False

    def events(self, project: str, session_id: str) -> list[Event]:
        evs: list[Event] = []
        base = dict(project=project, session_id=session_id, source=SOURCE)
        ts = self.run.finished_at if self.run else None
        dur = self.run.duration_s if self.run else None
        if self.phase == "build":
            etype = EventType.BUILD_SUCCEEDED if self.ok else EventType.BUILD_FAILED
            evs.append(Event(type=etype, ts=ts,
                             severity="success" if self.ok else "error",
                             message=f"{self.phase} {'ok' if self.ok else 'FAILED'}"
                                     f" ({dur:.1f}s)" if dur else self.phase,
                             provenance=Provenance.OBSERVED, **base))
            if not self.ok and self.run and self.run.stderr_tail:
                first_err = next((ln for ln in self.run.stderr_tail.splitlines()
                                  if ln.strip()), "")
                if first_err:
                    evs.append(Event(type=EventType.ERROR_OBSERVED, ts=ts,
                                     severity="error",
                                     message=first_err[:200],
                                     data={"phase": "build"},
                                     provenance=Provenance.OBSERVED, **base))
        elif self.phase == "tests":
            c = self.counts
            evs.append(Event(type=EventType.TEST_RUN, ts=ts,
                             severity="success" if self.ok else "warn",
                             message=(f"{c.get('passed', 0)} passed, "
                                      f"{c.get('failed', 0)} failed, "
                                      f"{c.get('errors', 0)} errors"),
                             data=dict(c), provenance=Provenance.OBSERVED, **base))
            if c.get("failed") or c.get("errors"):
                evs.append(Event(type=EventType.TEST_FAILED, ts=ts,
                                 severity="error",
                                 message=f"{c.get('failed', 0)} failed / "
                                         f"{c.get('errors', 0)} errors",
                                 data=dict(c),
                                 provenance=Provenance.OBSERVED, **base))
                failing = [ln.strip() for ln in
                           (self.run.stdout_tail if self.run else "").splitlines()
                           + (self.run.stderr_tail if self.run else "").splitlines()
                           if ln.startswith(("FAILED", "E   "))][:5]
                for i, fl in enumerate(failing):
                    evs.append(Event(type=EventType.BUG_DISCOVERED, ts=ts,
                                     severity="warn", message=fl[:200],
                                     data={"index": i},
                                     provenance=Provenance.ESTIMATED,
                                     note="failing-test line interpreted as bug signal",
                                     **base))
            elif c.get("passed"):
                evs.append(Event(type=EventType.TEST_PASSED, ts=ts,
                                 severity="success",
                                 message=f"{c['passed']} passed",
                                 data=dict(c),
                                 provenance=Provenance.OBSERVED, **base))
            if self.coverage_pct is not None:
                evs.append(Event(type=EventType.COVERAGE_REPORTED, ts=ts,
                                 severity="info",
                                 message=f"coverage {self.coverage_pct}%",
                                 data={"coverage_pct": self.coverage_pct,
                                       "source": self.coverage_source},
                                 provenance=Provenance.OBSERVED, **base))
        elif self.phase == "smoke":
            etype = EventType.TASK_COMPLETED if self.ok else EventType.ERROR_OBSERVED
            evs.append(Event(type=etype, ts=ts,
                             severity="success" if self.ok else "critical",
                             message=("entrypoint smoke-run ok"
                                      if self.ok else "entrypoint smoke-run FAILED"),
                             provenance=Provenance.OBSERVED, **base))
        return evs

    def measurements(self) -> dict[str, Measurement]:
        out: dict[str, Measurement] = {}
        if self.run is not None:
            out.update(measurements_from_run(self.run, self.phase))
        for k, v in self.counts.items():
            out[f"{self.phase}.{k}"] = Measurement.observed(v, SOURCE)
        if self.coverage_pct is not None:
            out["coverage.percent"] = Measurement.observed(
                self.coverage_pct, SOURCE, note=self.coverage_source)
        else:
            out["coverage.percent"] = Measurement.unavailable(
                SOURCE, "no machine-readable coverage report found")
        return out


class Harness:
    """Executes build/test/smoke phases against a workspace copy."""

    def __init__(self, timeout_s: float = 600, sample_interval_s: float = 0.15,
                 use_coverage: bool = True):
        self.timeout_s = timeout_s
        self.sample_interval_s = max(0.05, sample_interval_s)
        self.use_coverage = use_coverage

    def _exec(self, cmd: list[str], cwd: Path) -> MonitoredRun:
        return run_monitored(cmd, cwd=cwd, timeout_s=self.timeout_s,
                             sample_interval_s=self.sample_interval_s)

    def build_phase(self, plan: BuildPlan, project: str, session_id: str,
                    cwd: Path) -> PhaseResult:
        if plan.cmd is None:
            # python: syntax-compile everything as a lightweight build proxy
            run = self._exec(["python3", "-m", "compileall", "-q", "."], cwd)
            pr = PhaseResult("build", run, ok=run.exit_code == 0)
            return pr
        if plan.name == "none":
            return PhaseResult("build", None, ok=True)
        run = self._exec(plan.cmd, cwd)
        pr = PhaseResult("build", run, ok=(not run.timed_out and run.exit_code == 0))
        return pr

    def test_phase(self, plan: TestPlan, project: str, session_id: str,
                   cwd: Path) -> PhaseResult:
        parser = PARSERS.get(plan.framework)
        run = self._exec(plan.cmd, cwd)
        counts = parser(run.stdout_tail, run.stderr_tail) if parser else {}
        pr = PhaseResult("tests", run, counts=counts)
        pr.ok = (not run.timed_out and run.exit_code == 0
                 and not counts.get("failed") and not counts.get("errors"))

        # optional coverage pass (rerun tests under coverage.py when present)
        if (self.use_coverage and plan.framework == "pytest"
                and has_coverage_tool()):
            cov_run = self._exec(
                ["coverage", "run", "--branch", "-m", "pytest", "-q"],
                cwd)
            if cov_run.exit_code == 0 or cov_run.exit_code == 1:
                self._exec(["coverage", "json", "-o", "coverage.json"], cwd)
                pct, src = extract_coverage(cwd)
                if pct is not None:
                    pr.coverage_pct = pct
                    pr.coverage_source = src
        elif self.use_coverage and plan.framework in {"jest", "vitest"}:
            pct, src = extract_coverage(cwd)
            if pct is not None:
                pr.coverage_pct = pct
                pr.coverage_source = src
        return pr

    def smoke_phase(self, entry_cmd: str | None, project: str, session_id: str,
                    cwd: Path, timeout_s: float = 60) -> PhaseResult:
        import shlex
        if not entry_cmd:
            return PhaseResult("smoke", None, ok=False)
        run = self._exec(shlex.split(entry_cmd), cwd)
        pr = PhaseResult("smoke", run, ok=(not run.timed_out
                                           and run.exit_code == 0))
        return pr
