#!/usr/bin/env python3
"""Build demo benchmark subjects with REAL git histories.

Each subject is constructed through a sequence of actual commits (backdated
for a realistic timeline), so every datum FAB later collects - commits,
insertions/deletions, file inventories, test outcomes - is genuinely observed,
never fabricated.

Subjects have deliberately different engineering quality profiles:

* ``demo-atlas``   high quality: package layout, docs, manifest, green suite
                   plus an honest bug-introduction -> fix cycle in history
* ``demo-volt``    medium quality: works, but ships with one failing test
* ``demo-cascade`` poor quality: duplication, god-file, TODO debt, red suite

Usage:
    python examples/build_demo_subjects.py [--force]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "examples" / "subjects"

T0 = time.time() - 48 * 3600  # start two days ago


def _env(offset_h: float) -> dict[str, str]:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(T0 + offset_h * 3600))
    return {**os.environ,
            "GIT_AUTHOR_DATE": ts, "GIT_COMMITTER_DATE": ts}


def run(cmd: list[str], cwd: Path, offset_h: float = 0) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True,
                   env=_env(offset_h))


class Builder:
    def __init__(self, name: str):
        self.dir = DEST / name
        self.h = 0.0

    def commit(self, msg: str, files: dict[str, str]) -> None:
        self.h += 3.7
        for rel, content in files.items():
            p = self.dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        run(["git", "add", "-A"], self.dir, self.h)
        run(["git", "commit", "--allow-empty", "-qm", msg], self.dir, self.h)

    def init(self) -> None:
        if self.dir.exists():
            subprocess.run(["rm", "-rf", str(self.dir)], check=True)
        self.dir.mkdir(parents=True)
        run(["git", "init", "-q"], self.dir)
        run(["git", "config", "user.email", "agent@example.com"], self.dir)
        run(["git", "config", "user.name", "Demo Agent"], self.dir)


# ---------------------------------------------------------------------------
# atlas - high quality
# ---------------------------------------------------------------------------

ATLAS_INIT = '''"""Atlas: an in-memory task queue with retries."""

__version__ = "0.1.0"
'''

ATLAS_QUEUE_V1 = '''"""Core queue implementation."""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field


@dataclass
class Task:
    name: str
    payload: dict
    attempts: int = 0
    max_attempts: int = 3
    done: bool = False


@dataclass
class Queue:
    tasks: list = field(default_factory=list)
    _ids = itertools.count()

    def push(self, name: str, payload: dict | None = None) -> int:
        t = Task(name=name, payload=payload or {})
        self.tasks.append(t)
        return id(t)

    def pop(self):
        for t in self.tasks:
            if not t.done:
                t.attempts += 1
                return t
        return None

    def mark_done(self, task) -> None:
        task.done = True
'''


def build_atlas() -> Builder:
    b = Builder("demo-atlas")
    b.init()
    b.commit("feat: scaffold package skeleton", {
        "atlas/__init__.py": ATLAS_INIT,
        "README.md": "# atlas\n",
    })
    b.commit("feat: implement core queue with push/pop", {
        "atlas/queue.py": ATLAS_QUEUE_V1,
        "atlas/retry.py": '"""Retry policy helpers."""\n\n\ndef should_retry(task, exc):\n'
                          '    """Decide whether a failed task deserves another attempt."""\n'
                          '    return task.attempts < task.max_attempts\n',
    })
    # introduce a real bug...
    b.commit("feat: priority scheduling", {
        "atlas/queue.py": ATLAS_QUEUE_V1.replace(
            "    def pop(self):\n        for t in self.tasks:\n"
            "            if not t.done:\n                t.attempts += 1\n"
            "                return t\n        return None\n",
            "    def pop(self):\n        candidates = [t for t in self.tasks if not t.done]\n"
            "        if not candidates:\n            return None\n"
            "        best = min(candidates, key=lambda t: len(t.name))\n"
            "        best.attempts += 2  # FIXME off-by-one vs retry budget\n"
            "        return best\n"),
    })
    b.commit("feat: worker loop and stats module", {
        "atlas/worker.py": '"""Simple synchronous worker."""\n'
                           'from atlas.queue import Queue\n'
                           'from atlas.retry import should_retry\n\n\n'
                           'def run_all(queue: Queue, handler) -> dict:\n'
                           '    """Execute every pending task via handler."""\n'
                           '    stats = {"done": 0, "failed": 0}\n'
                           '    while True:\n'
                           '        task = queue.pop()\n'
                           '        if task is None:\n'
                           '            break\n'
                           '        try:\n'
                           '            handler(task)\n'
                           '            queue.mark_done(task)\n'
                           '            stats["done"] += 1\n'
                           '        except Exception:\n'
                           '            if not should_retry(task, None):\n'
                           '                stats["failed"] += 1\n'
                           '    return stats\n',
        "atlas/stats.py": '"""Queue statistics."""\n\n\n'
                          'def summarize(queue) -> dict:\n'
                          '    """Return done/pending counts."""\n'
                          '    done = sum(1 for t in queue.tasks if t.done)\n'
                          '    return {"done": done,\n'
                          '            "pending": len(queue.tasks) - done}\n',
    })
    # ...and fix it honestly
    b.commit("fix: restore attempt accounting in pop()", {
        "atlas/queue.py": ATLAS_QUEUE_V1.replace(
            "        t = Task(name=name, payload=payload or {})",
            "        t = Task(name=name, payload=payload or {})").replace(
            "    def pop(self):", "    def pop(self):"),
        "atlas/queue_prio.py": '"""Priority-aware selection (bug-free)."""\n'
                               'from atlas.queue import Task\n\n\n'
                               'def pick(candidates):\n'
                               '    """Choose shortest name; count exactly one attempt."""\n'
                               '    if not candidates:\n'
                               '        return None\n'
                               '    best = min(candidates, key=lambda t: len(t.name))\n'
                               '    best.attempts += 1\n'
                               '    return best\n',
    })
    b.commit("feat: comprehensive test suite", {
        "tests/test_queue.py": "from atlas.queue import Queue\n\n\n"
                               "def test_push_and_pop():\n"
                               "    q = Queue()\n"
                               "    q.push('a')\n"
                               "    t = q.pop()\n"
                               "    assert t is not None and t.name == 'a'\n\n\n"
                               "def test_pop_empty_returns_none():\n"
                               "    q = Queue()\n"
                               "    assert q.pop() is None\n\n\n"
                               "def test_mark_done_excludes_from_pop():\n"
                               "    q = Queue()\n"
                               "    q.push('only')\n"
                               "    t = q.pop()\n"
                               "    q.mark_done(t)\n"
                               "    assert q.pop() is None\n",
        "tests/test_retry.py": "from atlas.retry import should_retry\n"
                               "from atlas.queue import Task\n\n\n"
                               "def test_retry_under_budget():\n"
                               "    t = Task(name='x', payload={})\n"
                               "    t.attempts = 1\n"
                               "    assert should_retry(t, ValueError())\n\n\n"
                               "def test_no_retry_over_budget():\n"
                               "    t = Task(name='x', payload={}, max_attempts=2)\n"
                               "    t.attempts = 5\n"
                               "    assert not should_retry(t, ValueError())\n",
        "tests/test_worker.py": "from atlas.queue import Queue\n"
                                "from atlas.worker import run_all\n\n\n"
                                "def test_run_all_executes_every_task():\n"
                                "    q = Queue()\n"
                                "    q.push('one'); q.push('two')\n"
                                "    seen = []\n"
                                "    stats = run_all(q, lambda t: seen.append(t.name))\n"
                                "    assert sorted(seen) == ['one', 'two']\n"
                                "    assert stats['done'] == 2\n\n\n"
                                "def test_stats_counts_pending():\n"
                                "    from atlas.stats import summarize\n"
                                "    q = Queue()\n"
                                "    q.push('p1'); q.push('p2')\n"
                                "    assert summarize(q)['pending'] == 2\n",
        "features.yaml": "- name: queue-push-pop\n  description: enqueue and dequeue tasks\n"
                         "- name: retry-policy\n  description: bounded retries with budget\n"
                         "- name: worker-loop\n  description: drain queue through handler\n",
    })
    b.commit("docs: full readme, changelog and pinned requirements", {
        "README.md": ("# Atlas\n\nAn in-memory task queue with bounded "
                      "retries.\n\n## Installation\n\n`pip install -r "
                      "requirements.txt`\n\n## Usage\n\n```python\n"
                      "from atlas.queue import Queue\nq = Queue()\nq.push('job')\n"
                      "```\n\n## Architecture\n\n- `atlas/queue.py`: core FIFO "
                      "queue\n- `atlas/retry.py`: retry policy\n"
                      "- `atlas/worker.py`: synchronous worker loop\n\n"
                      "## License\nMIT\n"),
        "CHANGELOG.md": "# Changelog\n\n## 0.1.0\n- initial release\n",
        "requirements.txt": "",
    })
    b.commit("chore: release v0.1.0 milestone", {})
    return b


# ---------------------------------------------------------------------------
# volt - medium quality
# ---------------------------------------------------------------------------

def build_volt() -> Builder:
    b = Builder("demo-volt")
    b.init()
    b.commit("initial csv reader", {
        "volt/__init__.py": '"""Volt: tiny CSV statistics."""\n',
        "volt/reader.py": ('import csv\n\n\n'
                           'def load(path):\n'
                           '    with open(path) as fh:\n'
                           '        rows = list(csv.DictReader(fh))\n'
                           '    return rows\n'),
        "README.md": "# volt\nreads csv files\n",
    })
    b.commit("add mean and median stats", {
        "volt/stats.py": ('def mean(values):\n'
                          '    values = [v for v in values if v is not None]\n'
                          '    return sum(values) / len(values) if values else 0.0\n\n\n'
                          'def median(values):\n'
                          '    vals = sorted(v for v in values if v is not None)\n'
                          '    n = len(vals)\n'
                          '    if n == 0:\n'
                          '        return 0.0\n'
                          '    mid = n // 2\n'
                          '    if n % 2:\n'
                          '        return float(vals[mid])\n'
                          '    return (vals[mid - 1] + vals[mid]) / 2.0\n'),
    })
    b.commit("cli entrypoint", {
        "volt/cli.py": ('import argparse\n'
                        'from volt.reader import load\n'
                        'from volt.stats import mean\n\n\n'
                        'def main(argv=None):\n'
                        '    ap = argparse.ArgumentParser(prog="volt")\n'
                        '    ap.add_argument("path")\n'
                        '    ap.add_argument("--column", required=True)\n'
                        '    ns = ap.parse_args(argv)\n'
                        '    rows = load(ns.path)\n'
                        '    col = [float(r[ns.column]) for r in rows]\n'
                        '    print(f"mean({ns.column}) = {mean(col):.3f}")\n'
                        '    return 0\n\n\n'
                        'if __name__ == "__main__":\n'
                        '    raise SystemExit(main())\n'),
    })
    b.commit("tests for stats and cli", {
        "tests/test_stats.py": ("from volt.stats import mean, median\n\n\n"
                                "def test_mean():\n    assert mean([1, 2, 3]) == 2\n\n\n"
                                "def test_median_odd():\n    assert median([3, 1, 2]) == 2\n\n\n"
                                "def test_median_even():\n    assert median([1, 2, 3, 4]) == 2.5\n"),
        "tests/test_reader.py": ("from volt.stats import mean\n\n\n"
                                 "def test_mean_skips_none():\n"
                                 "    assert mean([None, 2, 4]) == 3\n"),
        "features.yaml": ("- name: csv-load\n- name: mean-median\n"
                          "- name: cli-entrypoint\n- name: column-filter\n"),
    })
    b.commit("wip: column filter (broken comparison)", {
        "volt/filter.py": ('def filter_rows(rows, column, op, value):\n'
                           '    """Filter rows by numeric predicate."""\n'
                           '    ops = {"gt": lambda a, b: a > b,\n'
                           '           "lt": lambda a, b: a < b}\n'
                           '    fn = ops[op]\n'
                           '    out = []\n'
                           '    for r in rows:\n'
                           '        try:\n'
                           '            if fn(float(r[column]), value):\n'
                           '                out.append(r)\n'
                           '        # TODO handle missing columns gracefully\n'
                           '        except Exception:\n'
                           '            pass\n'
                           '    return out\n'),
        "tests/test_filter.py": ("from volt.filter import filter_rows\n\n\n"
                                 "def test_gt_filters():\n"
                                 "    rows = [{'v': '1'}, {'v': '5'}]\n"
                                 "    assert len(filter_rows(rows, 'v', 'gt', 2)) == 1\n"),
    })
    # leave a genuinely failing test behind (the shipped bug)
    b.commit("test: median edge case expectation", {
        "tests/test_median_edge.py": ("from volt.stats import median\n\n\n"
                                      "def test_median_empty_should_be_none():\n"
                                      "    # spec says empty input -> None, impl returns 0.0\n"
                                      "    assert median([]) is None\n"),
    })
    return b


# ---------------------------------------------------------------------------
# cascade - poor quality
# ---------------------------------------------------------------------------

CASCADE_CORE = (
    "import json\n"
    "\n"
    "\n"
    "def process_record(rec, cache={}):  # mutable default!\n"
    "    try:\n"
    "        data = json.loads(rec)\n"
    "        key = data.get('id')\n"
    "        if key in cache:\n"
    "            return cache[key]\n"
    "        result = {'id': key, 'score': len(str(data)) * 3}\n"
    "        if result['score'] > 10:\n"
    "            for k in data:\n"
    "                if str(k).startswith('x_'):\n"
    "                    result['score'] += 7\n"
    "        cache[key] = result\n"
    "        return result\n"
    "    except Exception:\n"
    "        return {'id': None, 'score': -1}\n"
    "\n"
    "\n"
)


def build_cascade() -> Builder:
    b = Builder("demo-cascade")
    b.init()
    body = CASCADE_CORE
    b.commit("first version of processor", {
        "processor.py": body +
                        "def process_batch(records, cache={}):\n"
                        "    out = []\n"
                        "    try:\n"
                        "        for r in records:\n"
                        "            out.append(process_record(r))\n"
                        "    except Exception:\n"
                        "        pass\n"
                        "    return out\n",
    })
    b.commit("add second processor variant (copy)", {
        "processor_v2.py": body.replace("len(str(data)) * 3",
                                        "len(str(data)) * 4") +
                            "def process_batch(records, cache={}):\n"
                            "    out = []\n"
                            "    try:\n"
                            "        for r in records:\n"
                            "            out.append(process_record(r))\n"
                            "    except Exception:\n"
                            "        pass\n"
                            "    return out\n",
    })
    b.commit("quick tests", {
        "test_processor.py": ("from processor import process_record\n\n\n"
                              "def test_basic():\n"
                              "    r = process_record('{\"id\": 1}')\n"
                              "    assert r['id'] == 1\n\n\n"
                              "def test_score_multiplier_spec():\n"
                              "    # spec says multiplier is 2; impl uses 3\n"
                              "    r = process_record('{\"id\": 2}', cache={})\n"
                              "    assert r['score'] == len('{\"id\": 2}') * 2\n"),
    })
    b.commit("wip: exporter stub", {
        "exporter.py": ("# TODO implement real export\n"
                        "# FIXME format is wrong\n"
                        "def export(records, path='out.json', opts={}):\n"
                        "    raise NotImplementedError('soon')\n"),
        "test_exporter.py": ("import pytest\n"
                             "from exporter import export\n\n\n"
                             "def test_export_writes_file(tmp_path):\n"
                             "    out = tmp_path / 'o.json'\n"
                             "    export([{'id': 1}], str(out))\n"
                             "    assert out.exists()\n"),
    })
    return b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if DEST.exists() and any(DEST.iterdir()) and not args.force:
        print(f"{DEST} already populated; use --force to rebuild")
        return 1
    for builder in (build_atlas(), build_volt(), build_cascade()):
        span_min = builder.h * 60
        print(f"built {builder.dir.relative_to(ROOT)} "
              f"({int(round(builder.h))}h span, last={builder.dir and ''}"
              f"{builder.h:.1f}h offset)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
