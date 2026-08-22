"""Comparative analysis across subjects.

Produces dimension-by-dimension rankings, pairwise deltas, compute-efficiency
measures and failure/recovery statistics.  Every answer distinguishes whether
it rests on OBSERVED data or is UNAVAILABLE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..collector import ProjectBundle
from ..models import EventType, Measurement, Provenance
from ..scoring.base import Scorecard


@dataclass
class ComparisonResult:
    projects: list[str]
    rankings: dict[str, list[tuple[str, float | None]]] = field(default_factory=dict)
    matrix: dict[str, dict[str, Any]] = field(default_factory=dict)
    efficiency: dict[str, dict[str, Any]] = field(default_factory=dict)
    failure_analysis: dict[str, dict[str, Any]] = field(default_factory=dict)
    verdicts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "projects": self.projects,
            "rankings": {k: [{"project": p, "score": s} for p, s in v]
                         for k, v in self.rankings.items()},
            "matrix": self.matrix,
            "efficiency": self.efficiency,
            "failure_analysis": self.failure_analysis,
            "verdicts": self.verdicts,
        }


def _rank(dims: dict[str, Scorecard], name: str) -> list[tuple[str, float | None]]:
    rows = []
    for project, card in dims.items():
        dim = card.dimensions.get(name)
        rows.append((project, dim.value if dim else None))
    # available scores first (descending), then unavailable by name
    available = sorted(((p, v) for p, v in rows if v is not None),
                       key=lambda x: (-x[1], x[0]))
    missing = sorted((p, v) for p, v in rows if v is None)
    return available + missing


def compare(bundles: dict[str, ProjectBundle],
            cards: dict[str, Scorecard]) -> ComparisonResult:
    res = ComparisonResult(projects=sorted(cards))
    names = ["completion", "reliability", "testing", "architecture",
             "performance", "documentation", "autonomy", "maintainability"]
    for n in names:
        res.rankings[n] = _rank(cards, n)
    res.rankings["overall"] = sorted(
        ((p, c.overall) for p, c in cards.items() if c.overall is not None),
        key=lambda x: (-x[1], x[0]))

    # ---- pairwise delta matrix on overall ---------------------------------
    for a in cards:
        res.matrix[a] = {}
        for b in cards:
            oa, ob = cards[a].overall, cards[b].overall
            res.matrix[a][b] = (
                {"delta": round(oa - ob, 2)} if (oa is not None and ob is not None)
                else {"delta": None})

    # ---- compute efficiency ------------------------------------------------
    for p, bundle in bundles.items():
        entry: dict[str, Any] = {}
        cpu_s = _sum_cpu(bundle, "cpu_core_seconds")
        wall = _sum_cpu(bundle, "duration_s")
        score = cards[p].overall
        entry["cpu_core_seconds"] = cpu_s.to_dict()
        entry["wall_seconds"] = wall.to_dict()
        if score is not None and cpu_s.available and cpu_s.value > 0:
            entry["score_per_cpu_second"] = Measurement.estimated(
                round(score / cpu_s.value, 3), "comparison",
                note="overall score / integrated CPU core-seconds").to_dict()
        elif score is not None:
            entry["score_per_cpu_second"] = Measurement.unavailable(
                "comparison", "no CPU sampling available for this subject").to_dict()
        tokens = getattr(bundle, "measurements", {}).get("tokens.total")
        if tokens and tokens.available and score is not None and tokens.value > 0:
            entry["score_per_1k_tokens"] = Measurement.estimated(
                round(score / (tokens.value / 1000.0), 3), "comparison",
                note=f"token provenance: {tokens.provenance.value}").to_dict()
        else:
            note = tokens.note if tokens else "not ingested"
            entry["score_per_1k_tokens"] = Measurement.unavailable(
                "comparison", f"token usage unavailable ({note})").to_dict()
        res.efficiency[p] = entry

    # ---- failure & recovery -------------------------------------------------
    for p, bundle in bundles.items():
        fails = [e for e in bundle.events
                 if e.type in {EventType.TEST_FAILED, EventType.BUILD_FAILED}]
        errors = [e for e in bundle.events if e.type == EventType.ERROR_OBSERVED]
        fixes = [e for e in bundle.events
                 if e.type in {EventType.BUG_FIXED, EventType.TEST_PASSED,
                               EventType.BUILD_SUCCEEDED}
                 and e.ts is not None]
        recovered, mttrs = 0, []
        for f in fails:
            if f.ts is None:
                continue
            later = [x.ts - f.ts for x in fixes if x.ts >= f.ts]
            if later:
                recovered += 1
                mttrs.append(min(later))
        res.failure_analysis[p] = {
            "build_failures": sum(1 for e in fails if e.type == EventType.BUILD_FAILED),
            "test_failures": sum(1 for e in fails if e.type == EventType.TEST_FAILED),
            "errors_observed": len(errors),
            "failures_total": len(fails),
            "recovered": recovered,
            "persisting": max(0, len([f for f in fails if f.ts is not None]) - recovered),
            "recovery_rate": round(recovered / len(fails), 4) if fails else None,
            "mean_time_to_recovery_s": round(sum(mttrs) / len(mttrs), 2) if mttrs else None,
        }

    # ---- verdicts -------------------------------------------------------------
    def best(dim: str):
        r = res.rankings.get(dim) or []
        return ({"project": r[0][0], "score": r[0][1]}
                if r and r[0][1] is not None
                else {"project": None, "score": None})

    fa = res.failure_analysis
    most_failures = min(fa, key=lambda p: -(fa[p]["failures_total"])) \
        if fa and any(fa[p]["failures_total"] > 0 for p in fa) else None
    recov = {p: v for p, v in fa.items() if v["recovery_rate"] is not None}
    best_recoverer = (max(recov, key=lambda p: (recov[p]["recovery_rate"],
                                                -recov[p]["persisting"]))
                      if recov else None)

    eff_cpu = {}
    for p, e in res.efficiency.items():
        v = e.get("score_per_cpu_second", {}).get("value")
        if v is not None:
            eff_cpu[p] = v
    most_efficient = (max(eff_cpu, key=eff_cpu.get) if eff_cpu else None)

    res.verdicts = {
        "most_complete": best("completion"),
        "most_reliable": best("reliability"),
        "strongest_architecture": best("architecture"),
        "best_tests": best("testing"),
        "best_performance": best("performance"),
        "strongest_autonomy": best("autonomy"),
        "most_maintainable": best("maintainable" if False else "maintainability"),
        "most_efficient_compute": (
            {"project": most_efficient} if most_efficient
            else {"project": None}),
        "most_failures": ({"project": most_failures}
                          if most_failures else {"project": None}),
        "best_failure_recovery": ({"project": best_recoverer}
                                  if best_recoverer else {"project": None}),
    }
    return res


def _sum_cpu(bundle: ProjectBundle, key_suffix: str) -> Measurement:
    """Sum an observed measurement across harness phases."""
    total = 0.0
    any_observed = False
    all_estimated = True
    for ph in bundle.phases:
        m = bundle.measurements.get(f"{ph.phase}.{key_suffix}")
        if m and m.available:
            total += float(m.value)
            any_observed = True
            if m.provenance is not Provenance.ESTIMATED:
                all_estimated = False
    if any_observed:
        prov = Provenance.ESTIMATED if all_estimated and key_suffix == "cpu_core_seconds" \
            else Provenance.OBSERVED
        return Measurement(round(total, 3), prov, "harness",
                           note=f"sum over phases of {key_suffix}")
    return Measurement.unavailable("harness", "phase never executed under monitor")
