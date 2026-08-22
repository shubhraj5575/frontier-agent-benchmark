"""Tests for core models: provenance, measurements, events."""

import json

from fab.models import (Event, EventType, Measurement, Provenance, band_score,
                        saturate)


def test_measurement_provenance_states():
    o = Measurement.observed(5, "git")
    e = Measurement.estimated(3.2, "code", note="shingle")
    u = Measurement.unavailable("procmon", "no samples")
    assert o.provenance is Provenance.OBSERVED and o.available
    assert e.provenance is Provenance.ESTIMATED and e.available
    assert u.provenance is Provenance.UNAVAILABLE and not u.available
    assert u.value is None


def test_measurement_roundtrip():
    m = Measurement.estimated(0.42, "src", note="heuristic x")
    d = m.to_dict()
    m2 = Measurement.from_dict(json.loads(json.dumps(d)))
    assert m2.value == 0.42
    assert m2.provenance is Provenance.ESTIMATED
    assert m2.note == "heuristic x"


def test_event_roundtrip_all_nine_required_types():
    required = [
        EventType.AGENT_STARTED, EventType.TASK_COMPLETED,
        EventType.TEST_FAILED, EventType.BUG_DISCOVERED,
        EventType.BUG_FIXED, EventType.COMMIT_CREATED,
        EventType.BENCHMARK_COMPLETED, EventType.BUILD_FAILED,
        EventType.MILESTONE_REACHED,
    ]
    for t in required:
        ev = Event(type=t, project="p", session_id="s", ts=1234.0,
                   message="m", provenance=Provenance.OBSERVED)
        d = ev.to_dict()
        assert d["type"] == t.value
        ev2 = Event.from_dict(d)
        assert ev2.type is t
        assert ev2.ts == 1234.0


def test_saturate_and_band():
    assert saturate(0, cap=100) == 0.0
    assert abs(saturate(100, cap=100) - (1 - pow(2.718281828, -2.2))) < 1e-3
    assert saturate(1000, cap=100) <= 1.0
    # trapezoid: inside ideal -> 1.0; outside range -> floor
    assert band_score(50, 10, 30, 60, 90) == 1.0
    assert band_score(5, 10, 30, 60, 90) == 0.05
    assert band_score(95, 10, 30, 60, 90) == 0.05
    assert 0.05 < band_score(20, 10, 30, 60, 90) < 1.0


def test_unavailable_never_equals_zero_semantics():
    """A missing value must stay distinguishable from a measured zero."""
    zero = Measurement.observed(0, "harness")
    none = Measurement.unavailable("harness")
    assert zero.value == 0 and zero.available
    assert none.value is None and not none.available
