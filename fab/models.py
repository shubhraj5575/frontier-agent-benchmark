"""Core data models: provenance-tagged measurements, events, projects, sessions.

The entire platform is built around one rule: a number without provenance is
worthless.  Every metric that enters the pipeline is wrapped in a
:class:`Measurement` carrying one of three provenance labels:

* ``OBSERVED``   - directly measured by a collector (git log, process sample,
                   test-runner exit codes, ...).  Reproducible evidence.
* ``ESTIMATED``  - derived from observed raw material through a documented
                   heuristic (e.g. tokens from character volume, duplication
                   ratio from shingling).  The heuristic name is recorded.
* ``UNAVAILABLE``- the datum simply does not exist in any source we were given.
                   Rendered as "n/a" everywhere; never treated as zero.

Scores derived from UNAVAILABLE inputs are excluded from aggregates (weight is
redistributed) and the aggregate carries an explicit ``coverage`` fraction.
"""

from __future__ import annotations

import enum
import hashlib
import math
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class Provenance(str, enum.Enum):
    OBSERVED = "OBSERVED"
    ESTIMATED = "ESTIMATED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class Measurement:
    """A single datum plus its provenance."""

    value: Any = None
    provenance: Provenance = Provenance.UNAVAILABLE
    source: str = ""
    note: str | None = None

    @staticmethod
    def observed(value: Any, source: str, note: str | None = None) -> "Measurement":
        """Build an OBSERVED measurement."""
        return Measurement(value=value, provenance=Provenance.OBSERVED, source=source, note=note)

    @staticmethod
    def estimated(value: Any, source: str, note: str | None = None) -> "Measurement":
        """Build an ESTIMATED measurement."""
        return Measurement(value=value, provenance=Provenance.ESTIMATED, source=source, note=note)

    @staticmethod
    def unavailable(source: str = "", note: str | None = None) -> "Measurement":
        """Build an UNAVAILABLE measurement (no fabricated value)."""
        return Measurement(value=None, provenance=Provenance.UNAVAILABLE, source=source, note=note)

    @property
    def available(self) -> bool:
        return self.provenance is not Provenance.UNAVAILABLE and self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "provenance": self.provenance.value,
            "source": self.source,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Measurement":
        prov = d.get("provenance", "UNAVAILABLE")
        try:
            provenance = Provenance(prov)
        except ValueError:
            provenance = Provenance.UNAVAILABLE
        return cls(
            value=d.get("value"),
            provenance=provenance,
            source=d.get("source", ""),
            note=d.get("note"),
        )


# ---------------------------------------------------------------------------
# Canonical event taxonomy
# ---------------------------------------------------------------------------

class EventType(enum.Enum):
    """Canonical event types for the benchmark event stream.

    The nine types required by the spec are first-class citizens; supporting
    types make the stream useful for scoring autonomy / reliability.
    """

    # --- required nine -----------------------------------------------------
    AGENT_STARTED = "agent_started"
    TASK_COMPLETED = "task_completed"
    TEST_FAILED = "test_failed"
    BUG_DISCOVERED = "bug_discovered"
    BUG_FIXED = "bug_fixed"
    COMMIT_CREATED = "commit_created"
    BENCHMARK_COMPLETED = "benchmark_completed"
    BUILD_FAILED = "build_failed"
    MILESTONE_REACHED = "milestone_reached"

    # --- supporting ---------------------------------------------------------
    BUILD_SUCCEEDED = "build_succeeded"
    TEST_PASSED = "test_passed"
    TEST_RUN = "test_run"
    ERROR_OBSERVED = "error_observed"
    RETRY_ATTEMPTED = "retry_attempted"
    TOOL_CALL = "tool_call"
    INTERVENTION_REQUESTED = "intervention_requested"
    FILE_EDITED = "file_edited"
    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    COVERAGE_REPORTED = "coverage_reported"
    TOKENS_REPORTED = "tokens_reported"
    OTHER = "other"


@dataclass
class Event:
    """One canonical event in a project's benchmark timeline."""

    type: EventType
    project: str
    session_id: str
    ts: float | None = None          # epoch seconds; None => timing unknown
    severity: str = "info"           # info|success|warn|error|critical
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    raw_type: str | None = None      # original label before normalisation
    provenance: Provenance = Provenance.OBSERVED
    source: str = ""                 # adapter/collector name
    note: str | None = None          # heuristic/method annotation when derived
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        d["provenance"] = self.provenance.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Event":
        return cls(
            type=EventType(d.get("type", EventType.OTHER.value)),
            project=d.get("project", ""),
            session_id=d.get("session_id", ""),
            ts=d.get("ts"),
            severity=d.get("severity", "info"),
            message=d.get("message", ""),
            data=d.get("data") or {},
            raw_type=d.get("raw_type"),
            provenance=Provenance(d.get("provenance", "OBSERVED")),
            source=d.get("source", ""),
            note=d.get("note"),
            id=d.get("id") or uuid.uuid4().hex[:16],
        )


SEVERITY_ORDER = {"info": 0, "success": 1, "warn": 2, "error": 3, "critical": 4}


# ---------------------------------------------------------------------------
# Projects / sessions / telemetry bundles
# ---------------------------------------------------------------------------

@dataclass
class SubjectSpec:
    """A benchmark subject declared in the bench config."""

    name: str
    path: str                       # path to the subject repo (read-only)
    language: str = "auto"          # python|javascript|go|rust|auto
    build_cmd: str | None = None
    entrypoint: str | None = None   # smoke-run command proving it works
    features_file: str | None = None  # optional manifest of declared features
    exclude: list[str] = field(default_factory=list)  # top-level dirs to skip
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionMeta:
    """Metadata about one observation session over a subject."""

    session_id: str
    project: str
    started_at: float
    finished_at: float | None = None
    collector_versions: dict[str, str] = field(default_factory=dict)
    workspace: str | None = None    # scratch copy used for execution
    host: str = ""

    @property
    def runtime_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        return max(0.0, self.finished_at - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stable_id(*parts: Any) -> str:
    """Deterministic id from parts (for reproducible artifacts)."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return h[:16]


def utc_iso(ts: float | None) -> str | None:
    """Format an epoch timestamp as UTC ISO-8601 (None-safe)."""
    if ts is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    """Division that survives a zero denominator."""
    return a / b if b else default


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Constrain value to [lo, hi]."""
    return max(lo, min(hi, value))


def saturate(x: float, cap: float) -> float:
    """Map [0, cap] -> [0, 1] with diminishing returns."""
    if cap <= 0:
        return 0.0
    x = max(0.0, float(x))
    return 1.0 - math.exp(-2.2 * x / cap)


def band_score(value: float, low: float, ideal_low: float, ideal_high: float,
               high: float) -> float:
    """Trapezoid membership: 1 inside [ideal_low, ideal_high], falling to 0 at
    ``low`` / ``high``.  Values outside [low, high] score 0.05 floor.
    Use only for genuinely two-sided metrics."""
    v = value
    if v <= low or v >= high:
        return 0.05
    if ideal_low <= v <= ideal_high:
        return 1.0
    if v < ideal_low:
        frac = (v - low) / max(1e-9, ideal_low - low)
    else:
        frac = (high - v) / max(1e-9, high - ideal_high)
    return max(0.05, min(1.0, frac))


def penalty_band(value: float, ideal_hi: float, hard_hi: float) -> float:
    """One-sided penalty: 1.0 while value <= ideal_hi, decaying linearly to a
    0.05 floor at hard_hi.  'Lower is better' metrics use this - low values
    must never be punished."""
    v = float(value)
    if v <= ideal_hi:
        return 1.0
    if v >= hard_hi:
        return 0.05
    frac = (hard_hi - v) / max(1e-9, hard_hi - ideal_hi)
    return max(0.05, min(1.0, frac))
