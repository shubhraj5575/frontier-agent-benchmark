"""Scoring engine entry point."""

from __future__ import annotations

from ..collector import ProjectBundle
from .base import Scorecard, compute_overall, grade
from .dimensions import DIMENSION_SCORERS


def score_project(bundle: ProjectBundle,
                  weights: dict[str, float]) -> Scorecard:
    card = Scorecard(project=bundle.spec.name,
                     weights_used=dict(weights))
    for name, scorer in DIMENSION_SCORERS.items():
        card.dimensions[name] = scorer(bundle)
    overall, coverage = compute_overall(card.dimensions, weights)
    card.overall = overall
    card.overall_coverage = coverage
    return card


__all__ = ["score_project", "Scorecard", "grade", "compute_overall"]
