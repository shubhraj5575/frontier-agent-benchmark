"""Benchmark configuration loading (YAML if available, else JSON).

Default config file: ``bench.json`` / ``bench.yaml`` in the project root.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import SubjectSpec

try:  # optional dependency
    import yaml  # type: ignore
    HAS_YAML = True
except Exception:  # pragma: no cover
    yaml = None
    HAS_YAML = False

DEFAULT_WEIGHTS: dict[str, float] = {
    "completion": 0.20,
    "reliability": 0.15,
    "testing": 0.15,
    "architecture": 0.125,
    "performance": 0.075,
    "documentation": 0.075,
    "autonomy": 0.125,
    "maintainability": 0.10,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "subjects": [],
    "scoring_weights": dict(DEFAULT_WEIGHTS),
    "test_timeout_seconds": 600,
    "smoke_timeout_seconds": 60,
    "sample_interval_ms": 100,
}


class ConfigError(ValueError):
    pass


@dataclass
class BenchConfig:
    path: Path | None
    subjects: list[SubjectSpec] = field(default_factory=list)
    scoring_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    test_timeout_seconds: int = 600
    smoke_timeout_seconds: int = 60
    sample_interval_ms: int = 100

    def subject(self, name: str) -> SubjectSpec:
        for s in self.subjects:
            if s.name == name:
                return s
        raise ConfigError(f"subject '{name}' is not declared in config")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "subjects": [s.to_dict() for s in self.subjects],
            "scoring_weights": self.scoring_weights,
            "test_timeout_seconds": self.test_timeout_seconds,
            "smoke_timeout_seconds": self.smoke_timeout_seconds,
            "sample_interval_ms": self.sample_interval_ms,
        }


def _parse_subject(d: dict[str, Any]) -> SubjectSpec:
    if "name" not in d or "path" not in d:
        raise ConfigError(f"subject entry needs 'name' and 'path': {d!r}")
    return SubjectSpec(
        name=str(d["name"]),
        path=str(d["path"]),
        language=str(d.get("language", "auto")),
        build_cmd=d.get("build_cmd"),
        entrypoint=d.get("entrypoint"),
        features_file=d.get("features_file"),
        exclude=[str(x) for x in (d.get("exclude") or [])],
        notes=str(d.get("notes", "")),
    )


def load_config(path: str | Path | None = None) -> BenchConfig:
    """Load config from explicit path, or search bench.{yaml,json}."""
    candidates: list[Path]
    if path is not None:
        candidates = [Path(path)]
    else:
        candidates = [Path("bench.yaml"), Path("bench.yml"), Path("bench.json")]

    for cand in candidates:
        if cand.exists():
            raw = cand.read_text(encoding="utf-8")
            if cand.suffix in {".yaml", ".yml"} and HAS_YAML:
                data = yaml.safe_load(raw) or {}
            else:
                try:
                    data = json.loads(raw or "{}")
                except json.JSONDecodeError as e:
                    raise ConfigError(f"{cand}: invalid JSON ({e})") from e
            cfg = _from_dict(data)
            cfg.path = cand.resolve()
            return cfg

    # No file found -> empty default (subjects added programmatically).
    return BenchConfig(path=None)


def _from_dict(data: dict[str, Any]) -> BenchConfig:
    weights = DEFAULT_WEIGHTS.copy()
    custom = data.get("scoring_weights") or {}
    if custom:
        unknown = set(custom) - set(weights)
        if unknown:
            raise ConfigError(f"unknown scoring dimensions: {sorted(unknown)}")
        missing = set(weights) - set(custom)
        if missing:
            raise ConfigError(
                f"scoring_weights must be complete when overridden - "
                f"missing: {sorted(missing)}")
        # explicit replacement: every dimension specified
        weights = {k: float(v) for k, v in custom.items()}
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ConfigError(
            f"scoring_weights must sum to 1.0 (got {total:.4f})"
        )
    return BenchConfig(
        path=None,
        subjects=[_parse_subject(s) for s in (data.get("subjects") or [])],
        scoring_weights=weights,
        test_timeout_seconds=int(data.get("test_timeout_seconds", 600)),
        smoke_timeout_seconds=int(data.get("smoke_timeout_seconds", 60)),
        sample_interval_ms=int(data.get("sample_interval_ms", 100)),
    )


def write_default_config(path: str | Path) -> Path:
    path = Path(path)
    suffix = path.suffix.lower()
    payload = {
        "version": 1,
        "subjects": [
            {
                "name": "example-subject",
                "path": "./examples/subjects/example-subject",
                "language": "python",
                "build_cmd": None,
                "entrypoint": "python -m app --help",
                "features_file": "features.yaml",
                "notes": "replace with your agent-built project",
            }
        ],
        "scoring_weights": dict(DEFAULT_WEIGHTS),
        "test_timeout_seconds": 600,
        "smoke_timeout_seconds": 60,
        "sample_interval_ms": 100,
    }
    if suffix in {".yaml", ".yml"} and HAS_YAML:
        text = yaml.safe_dump(payload, sort_keys=False)
    else:
        text = json.dumps(payload, indent=2)
    path.write_text(text, encoding="utf-8")
    return path
