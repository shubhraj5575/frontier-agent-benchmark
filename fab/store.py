"""SQLite persistence for benchmark runs.

Schema keeps provenance columns alongside values so no query can accidentally
treat UNAVAILABLE as a number.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    label TEXT,
    config_json TEXT
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    name TEXT NOT NULL,
    path TEXT,
    session_id TEXT,
    started_at REAL,
    finished_at REAL,
    runtime_seconds REAL,
    overall_score REAL,
    overall_grade TEXT,
    coverage REAL,
    bundle_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    project TEXT NOT NULL,
    dimension TEXT NOT NULL,
    value REAL,
    coverage REAL,
    components_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    project TEXT NOT NULL,
    ts REAL,
    type TEXT NOT NULL,
    severity TEXT,
    message TEXT,
    provenance TEXT NOT NULL,
    source TEXT,
    data_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_scores_run ON scores(run_id);
"""


class BenchmarkStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.executescript(SCHEMA)

    # -- writes --------------------------------------------------------------

    def begin_run(self, label: str, config: dict[str, Any] | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (created_at, label, config_json) VALUES (?,?,?)",
            (time.time(), label, json.dumps(config or {})))
        self.conn.commit()
        return int(cur.lastrowid)

    def save_project(self, run_id: int, bundle, scorecard) -> None:
        s = bundle.session
        self.conn.execute(
            """INSERT INTO projects (run_id, name, path, session_id, started_at,
               finished_at, runtime_seconds, overall_score, overall_grade,
               coverage, bundle_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, bundle.spec.name, bundle.spec.path,
             s.session_id if s else None,
             s.started_at if s else None,
             s.finished_at if s else None,
             s.runtime_seconds if s else None,
             scorecard.overall, scorecard.to_dict()["grade"],
             scorecard.overall_coverage,
             json.dumps(bundle.to_dict())))
        for name, dim in scorecard.dimensions.items():
            self.conn.execute(
                """INSERT INTO scores (run_id, project, dimension, value,
                   coverage, components_json) VALUES (?,?,?,?,?,?)""",
                (run_id, bundle.spec.name, name, dim.value, dim.coverage,
                 json.dumps(dim.to_dict())))
        for ev in bundle.events:
            self.conn.execute(
                """INSERT INTO events (run_id, project, ts, type, severity,
                   message, provenance, source, data_json)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (run_id, ev.project, ev.ts, ev.type.value, ev.severity,
                 ev.message, ev.provenance.value, ev.source,
                 json.dumps(ev.data)))
        self.conn.commit()

    def finish(self) -> None:
        self.conn.commit()

    # -- reads -----------------------------------------------------------------

    def latest_run_projects(self) -> list[dict[str, Any]]:
        row = self.conn.execute("SELECT MAX(id) FROM runs").fetchone()
        if not row or row[0] is None:
            return []
        run_id = row[0]
        out = []
        for r in self.conn.execute(
                "SELECT name, overall_score, overall_grade, coverage,"
                " runtime_seconds FROM projects WHERE run_id=? ORDER BY name",
                (run_id,)):
            out.append(dict(zip(
                ("name", "overall", "grade", "coverage", "runtime_s"), r)))
        return out

    def close(self) -> None:
        self.conn.close()
