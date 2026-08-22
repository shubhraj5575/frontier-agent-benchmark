"""Collector orchestrator: gathers all telemetry for one subject into a bundle.

The bundle is the single input to the scoring engine.
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import BenchConfig
from .models import Event, Measurement, SessionMeta, SubjectSpec
from .telemetry.code_analysis import CodeTelemetry, collect_code_telemetry
from .telemetry.git_telemetry import GitTelemetry, collect_git_telemetry, \
    commit_activity_series
from .telemetry.harness import (Harness, detect_build_plan,
                                detect_test_plan, has_coverage_tool)
from .telemetry.log_ingest import IngestResult
from .telemetry.workspace import cleanup_workspace, make_workspace

COLLECTOR_VERSION = "1.0"


@dataclass
class ProjectBundle:
    spec: SubjectSpec
    session: SessionMeta | None = None
    git: GitTelemetry | None = None
    code: CodeTelemetry | None = None
    phases: list[Any] = field(default_factory=list)   # PhaseResult list
    events: list[Event] = field(default_factory=list)
    ingest: IngestResult | None = None
    measurements: dict[str, Measurement] = field(default_factory=dict)
    activity: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.to_dict(),
            "session": self.session.to_dict() if self.session else None,
            "git": self.git.to_dict() if self.git else None,
            "code": self.code.to_dict() if self.code else None,
            "phases": [
                {
                    "phase": p.phase,
                    "ok": p.ok,
                    "counts": p.counts,
                    "coverage_pct": p.coverage_pct,
                    "coverage_source": p.coverage_source,
                    "run": p.run.summary() if (p.run is not None and hasattr(p.run, "summary")) else (
                        {"exit_code": getattr(p.run, "exit_code", None),
                         "duration_s": round(getattr(p.run, "duration_s", 0.0), 3)}
                        if p.run is not None else None),
                }
                for p in self.phases
            ],
            "events": [e.to_dict() for e in self.events],
            "measurements": {k: v.to_dict() for k, v in self.measurements.items()},
            "activity": self.activity,
        }


def collect_static(spec: SubjectSpec, data_root: Path) -> ProjectBundle:
    """Read-only static collection (safe on any directory)."""
    started = time.time()
    session = SessionMeta(
        session_id=f"static-{int(started)}",
        project=spec.name,
        started_at=started,
        collector_versions={"fab": COLLECTOR_VERSION},
        host=platform.node(),
    )
    bundle = ProjectBundle(spec=spec, session=session)
    path = Path(spec.path)
    bundle.git = collect_git_telemetry(path)
    bundle.code = collect_code_telemetry(path, exclude=spec.exclude)
    bundle.events.extend(bundle.git.events(spec.name, session.session_id))
    bundle.measurements.update(bundle.git.measurements())
    bundle.measurements.update(bundle.code.measurements())
    if bundle.git.commits:
        bundle.activity = commit_activity_series(bundle.git.commits)
    return bundle


def collect_dynamic(spec: SubjectSpec, data_root: Path, cfg: BenchConfig,
                    keep_workspaces: bool = False,
                    run_build: bool = True,
                    run_tests: bool = True,
                    run_smoke: bool = True,
                    repeats: int = 1) -> tuple[ProjectBundle, Path]:
    """Full collection with execution inside an isolated workspace copy.

    ``repeats`` runs the test suite multiple times on the same workspace,
    which is what makes stability / flakiness observable rather than
    assumed.  Returns (bundle, workspace_path).  Caller decides cleanup.
    """
    ws, meta = make_workspace(spec.name, spec.path, data_root,
                              exclude=spec.exclude)
    meta.collector_versions = {"fab": COLLECTOR_VERSION}
    meta.host = platform.node()
    bundle = ProjectBundle(spec=spec, session=meta)

    from .models import Event, EventType

    harness = Harness(timeout_s=cfg.test_timeout_seconds,
                      sample_interval_s=max(0.05, cfg.sample_interval_ms / 1000.0))

    test_plan = detect_test_plan(ws, override=None)
    build_plan = detect_build_plan(ws, override=spec.build_cmd)

    if run_build:
        pr = harness.build_phase(build_plan, spec.name, meta.session_id, ws)
        bundle.phases.append(pr)
        bundle.events.extend(pr.events(spec.name, meta.session_id))
        bundle.measurements.update(pr.measurements())
    if run_tests and test_plan.framework != "none":
        n_runs = max(1, int(repeats))
        last_pr = None
        for i in range(n_runs):
            pr = harness.test_phase(test_plan, spec.name, meta.session_id, ws)
            if n_runs > 1 and pr.run is not None:
                pr.run.stdout_tail += f"\n[fab] repeat {i + 1}/{n_runs}"
            bundle.phases.append(pr)
            bundle.events.extend(pr.events(spec.name, meta.session_id))
            bundle.measurements.update(pr.measurements())
            last_pr = pr
        # coverage only needs to be extracted once
        if last_pr is not None and last_pr.coverage_pct is None \
                and has_coverage_tool() and test_plan.framework == "pytest" \
                and n_runs > 1:
            pass  # per-run coverage already attempted inside each phase
    elif run_tests:
        bundle.measurements["tests.available"] = Measurement.observed(False, "harness")
    if run_smoke and spec.entrypoint:
        pr = harness.smoke_phase(spec.entrypoint, spec.name, meta.session_id, ws,
                                 timeout_s=cfg.smoke_timeout_seconds)
        bundle.phases.append(pr)
        bundle.events.append(Event(
            type=EventType.RUN_STARTED, ts=pr.run.started_at if pr.run else None,
            project=spec.name, session_id=meta.session_id,
            message="smoke-run start", source="harness"))
        bundle.events.extend(pr.events(spec.name, meta.session_id))
        bundle.measurements.update(pr.measurements())

    # refresh static telemetry against the pristine original (read-only)
    bundle.git = collect_git_telemetry(Path(spec.path))
    bundle.code = collect_code_telemetry(Path(spec.path),
                                         exclude=spec.exclude)
    bundle.measurements.update(bundle.git.measurements())
    bundle.measurements.update(bundle.code.measurements())
    if not keep_workspaces:
        cleanup_workspace(ws, keep=False)
    else:
        meta.workspace = str(ws)
    meta.finished_at = time.time()
    return bundle, ws


def merge_ingest(bundle: ProjectBundle, result: IngestResult) -> None:
    """Attach agent-log ingestion results to a bundle."""
    bundle.ingest = result
    bundle.events.extend(result.events)
    bundle.measurements.update(result.measurements())


def sort_events(events: list[Event]) -> list[Event]:
    """Chronological; events without timestamps keep insertion order at end."""
    dated = sorted((e for e in events if e.ts is not None), key=lambda e: e.ts)
    undated = [e for e in events if e.ts is None]
    return dated + undated
