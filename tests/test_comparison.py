"""Comparative analysis tests."""

import time

from fab.analysis.comparison import compare
from fab.models import Event, EventType, Provenance
from fab.scoring.engine import score_project

WEIGHTS = {
    "completion": 0.20, "reliability": 0.15, "testing": 0.15,
    "architecture": 0.125, "performance": 0.075, "documentation": 0.075,
    "autonomy": 0.125, "maintainability": 0.10,
}


def _mk_card(name, overall=None, dims=None):
    from fab.scoring.base import DimensionScore, Scorecard
    card = Scorecard(project=name, weights_used=WEIGHTS)
    for dname in WEIGHTS:
        val = (dims or {}).get(dname)
        card.dimensions[dname] = DimensionScore(dname, dname.title(), val,
                                                1.0 if val is not None else 0.0)
    card.overall = overall
    return card


def test_ranking_orders_and_preserves_unavailable():
    cards = {
        "alpha": _mk_card("alpha", 80.0, {"completion": 90.0}),
        "beta": _mk_card("beta", 60.0, {"completion": None}),
        "gamma": _mk_card("gamma", 70.0, {"completion": 75.0}),
    }
    res = compare({}, cards)
    comp = res.rankings["completion"]
    assert [p for p, _ in comp] == ["alpha", "gamma", "beta"]
    assert comp[-1][1] is None          # unavailable stays visible as None
    assert res.rankings["overall"][0][0] == "alpha"


def test_failure_analysis_recovery_and_mttr():
    now = time.time()
    events = [
        Event(type=EventType.TEST_FAILED, project="r", session_id="s",
              ts=now - 300),
        Event(type=EventType.BUG_FIXED, project="r", session_id="s",
              ts=now - 240),   # +60s recovery
        Event(type=EventType.TEST_FAILED, project="r", session_id="s",
              ts=now - 120),
        Event(type=EventType.TEST_PASSED, project="r", session_id="s",
              ts=now - 30),    # +90s recovery
    ]

    from types import SimpleNamespace
    fake = SimpleNamespace(events=events, phases=[])

    res = compare({"r": fake}, {"r": _mk_card("r")})
    fa = res.failure_analysis["r"]
    assert fa["test_failures"] == 2
    assert fa["recovered"] == 2
    assert fa["recovery_rate"] == 1.0
    assert abs(fa["mean_time_to_recovery_s"] - 75.0) < 1e-6


def test_efficiency_requires_observed_compute():
    cards = {"x": _mk_card("x", 50.0)}

    from types import SimpleNamespace
    fake = SimpleNamespace(events=[], phases=[])

    res = compare({"x": fake}, cards)
    eff = res.efficiency["x"]
    assert eff["score_per_cpu_second"]["provenance"] == "UNAVAILABLE"
    assert eff["score_per_1k_tokens"]["provenance"] == "UNAVAILABLE"


def test_verdicts_handle_all_unavailable():
    cards = {p: _mk_card(p) for p in ("a", "b")}
    res = compare({}, cards)
    v = res.verdicts
    assert v["most_complete"]["project"] is None
    assert v["most_efficient_compute"]["project"] is None


def test_cohort_relative_speed_percentile():
    from types import SimpleNamespace

    def run(dur):
        return SimpleNamespace(duration_s=dur, exit_code=0,
                               peak_rss_mb=None, samples=[])

    def phase(dur):
        return SimpleNamespace(phase="tests", run=run(dur), counts={},
                               coverage_pct=None, coverage_source="", ok=True)

    bundles = {
        "slow": SimpleNamespace(events=[], phases=[phase(30.0)],
                                measurements={}),
        "mid": SimpleNamespace(events=[], phases=[phase(10.0)],
                               measurements={}),
        "fast": SimpleNamespace(events=[], phases=[phase(2.0)],
                                measurements={}),
    }
    cards = {k: _mk_card(k) for k in bundles}
    res = compare(bundles, cards)
    eff = res.efficiency
    assert eff["fast"]["suite_speed_percentile"]["value"] == 1.0
    assert eff["slow"]["suite_speed_percentile"]["value"] == 0.0
    assert abs(eff["mid"]["suite_speed_percentile"]["value"] - 0.5) < 1e-9


def test_no_percentile_for_single_subject():
    from types import SimpleNamespace

    def phase():
        return SimpleNamespace(phase="tests",
                               run=SimpleNamespace(duration_s=5.0, exit_code=0,
                                                   peak_rss_mb=None, samples=[]),
                               counts={}, coverage_pct=None,
                               coverage_source="", ok=True)

    bundles = {"solo": SimpleNamespace(events=[], phases=[phase()],
                                       measurements={})}
    res = compare(bundles, {"solo": _mk_card("solo")})
    assert "suite_speed_percentile" not in res.efficiency["solo"]
