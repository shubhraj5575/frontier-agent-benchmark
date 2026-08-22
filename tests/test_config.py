"""Tests for config loading and validation."""

import json

import pytest

from fab.config import ConfigError, load_config, write_default_config


FULL_WEIGHTS = {
    "completion": 0.5, "reliability": 0.5, "testing": 0.0,
    "architecture": 0.0, "performance": 0.0, "documentation": 0.0,
    "autonomy": 0.0, "maintainability": 0.0,
}


def test_load_json_config(tmp_path):
    cfg_file = tmp_path / "bench.json"
    payload = {
        "version": 1,
        "subjects": [{"name": "alpha", "path": "./subjects/alpha",
                      "language": "python", "entrypoint": "python -m app"}],
        "scoring_weights": dict(FULL_WEIGHTS),
    }
    cfg_file.write_text(json.dumps(payload))
    cfg = load_config(cfg_file)
    assert len(cfg.subjects) == 1
    assert cfg.subject("alpha").entrypoint == "python -m app"
    assert abs(sum(cfg.scoring_weights.values()) - 1.0) < 1e-9
    assert cfg.scoring_weights["completion"] == 0.5


def test_weights_must_sum_to_one(tmp_path):
    f = tmp_path / "bench.json"
    full = {"completion": 1.0, "reliability": 0.0, "testing": 0.0,
            "architecture": 0.0, "performance": 0.0, "documentation": 0.0,
            "autonomy": 0.0, "maintainability": 0.0}
    bad = dict(full, completion=2.0)
    f.write_text(json.dumps({"subjects": [], "scoring_weights": bad}))
    with pytest.raises(ConfigError):
        load_config(f)


def test_partial_weight_override_rejected(tmp_path):
    f = tmp_path / "bench.json"
    f.write_text(json.dumps({"scoring_weights": {"completion": 0.5,
                                                 "reliability": 0.5}}))
    with pytest.raises(ConfigError, match="missing"):
        load_config(f)


def test_unknown_dimension_rejected(tmp_path):
    f = tmp_path / "bench.json"
    f.write_text(json.dumps({"scoring_weights": {"vibes": 1.0}}))
    with pytest.raises(ConfigError, match="unknown scoring dimensions"):
        load_config(f)


def test_missing_subject_lookup_raises(tmp_path):
    f = tmp_path / "bench.json"
    f.write_text(json.dumps({"subjects": []}))
    cfg = load_config(f)
    with pytest.raises(ConfigError):
        cfg.subject("nope")


def test_yaml_config_when_yaml_available(tmp_path):
    pytest.importorskip("yaml")
    f = tmp_path / "bench.yaml"
    f.write_text(
        "version: 1\n"
        "subjects:\n"
        "  - name: beta\n"
        "    path: ./b\n"
    )
    cfg = load_config(f)
    assert cfg.subject("beta").language == "auto"


def test_write_default_roundtrip(tmp_path):
    p = write_default_config(tmp_path / "bench.json")
    cfg = load_config(p)
    assert cfg.subject("example-subject").path.startswith("./examples")
