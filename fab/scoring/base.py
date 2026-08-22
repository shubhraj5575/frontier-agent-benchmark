"""Scoring primitives: components, dimension results, weighted aggregation.

Every score is decomposed into named components with explicit weights,
provenance and human-readable notes.  UNAVAILABLE components are excluded
from aggregation (weight redistributed) and the resulting ``coverage``
records how much of the dimension was actually backed by data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import Measurement, Provenance, clamp


@dataclass
class Component:
    name: str
    weight: float
    value: float | None              # 0..100 or None if unavailable
    provenance: Provenance = Provenance.OBSERVED
    note: str = ""
    formula: str = ""

    @property
    def available(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": self.weight,
            "value": None if self.value is None else round(self.value, 2),
            "provenance": self.provenance.value,
            "note": self.note,
            "formula": self.formula,
        }


@dataclass
class DimensionScore:
    name: str
    title: str
    value: float | None              # 0..100 or None when fully unavailable
    coverage: float                  # fraction of weight backed by data
    components: list[Component] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "value": None if self.value is None else round(self.value, 2),
            "coverage": round(self.coverage, 4),
            "components": [c.to_dict() for c in self.components],
            "notes": self.notes,
        }


def aggregate(components: list[Component]) -> tuple[float | None, float]:
    """Weighted mean over available components + coverage fraction."""
    total_w = sum(c.weight for c in components)
    used_w = sum(c.weight for c in components if c.available)
    if used_w <= 0:
        return None, 0.0
    score = sum(c.weight * c.value for c in components if c.available) / used_w
    return clamp(score), used_w / total_w


def grade(value: float | None) -> str:
    if value is None:
        return "n/a"
    bands = [(93, "A+"), (85, "A"), (78, "B+"), (70, "B"),
             (62, "C+"), (55, "C"), (45, "D"), (0, "F")]
    for floor, letter in bands:
        if value >= floor:
            return letter
    return "F"


@dataclass
class Scorecard:
    project: str
    dimensions: dict[str, DimensionScore] = field(default_factory=dict)
    overall: float | None = None
    overall_coverage: float = 0.0     # weight fraction backed by data
    weights_used: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
            "overall": None if self.overall is None else round(self.overall, 2),
            "grade": grade(self.overall),
            "overall_coverage": round(self.overall_coverage, 4),
            "weights": self.weights_used,
        }

    def dimension(self, name: str) -> DimensionScore:
        return self.dimensions[name]

    def summary_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {"project": self.project}
        for name, dim in self.dimensions.items():
            row[name] = None if dim.value is None else round(dim.value, 1)
        row["overall"] = None if self.overall is None else round(self.overall, 1)
        row["grade"] = grade(self.overall)
        row["coverage"] = round(self.overall_coverage, 3)
        return row


def compute_overall(dims: dict[str, DimensionScore],
                    weights: dict[str, float]) -> tuple[float | None, float]:
    num = den = 0.0
    for name, w in weights.items():
        dim = dims.get(name)
        if dim is not None and dim.value is not None:
            # scale by the dimension's own data coverage - partially observed
            # dimensions contribute proportionally to what they observed
            effective = w * max(0.5, dim.coverage)
            num += effective * dim.value
            den += effective
        # unavailable dimensions simply do not contribute; their weight is
        # dropped from `den`, which lowers overall_coverage accordingly.
    if den <= 0:
        return None, 0.0
    return clamp(num / den), min(1.0, den / sum(weights.values()))
