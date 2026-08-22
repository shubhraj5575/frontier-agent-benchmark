# Frontier Agent Benchmark (FAB)

**Independent observability and benchmarking platform for evaluating autonomous AI engineering agents on engineering quality - not volume.**

FAB answers a different question than "how much code did the agent write?".
It asks: *did the agent build something that works, is tested, is well
designed, documented, recoverable from failure, and maintainable?* Lines of
code, commits and tokens are recorded as context - never used to rank.

---

## Live results

- **Dashboard** - served on GitHub Pages once enabled, or locally:
  `fab serve` -> http://localhost:8737
- **Final report** - [`output/results/final_report.md`](output/results/final_report.md)
- **Exports** - JSON (`results.json`), CSV (`results.csv`), Markdown (`results.md`)

## Core principle: provenance discipline

Every number FAB produces carries one of three labels, enforced in the type
system:

| Label         | Meaning                                                          |
|---------------|------------------------------------------------------------------|
| `OBSERVED`    | directly measured: git log, process samples, test exit codes      |
| `ESTIMATED`   | derived via a documented heuristic (named inline wherever used)   |
| `UNAVAILABLE` | not present in any source; rendered `n/a`; **never treated as 0** |

Scores built on missing data exclude those components and redistribute their
weight; every score reports its **data coverage** so you can see exactly how
much was evidenced. FAB never fabricates telemetry.

## What is tracked per project

| Telemetry            | Source                              | Typical provenance |
|----------------------|-------------------------------------|--------------------|
| runtime, start time  | session clock                       | OBSERVED           |
| git commits/timeline | read-only `git log --numstat`       | OBSERVED           |
| files, LOC, languages| static scan                         | OBSERVED           |
| tests passed/failed  | JUnit XML / tool summaries          | OBSERVED           |
| coverage             | coverage.py JSON / lcov             | OBSERVED when produced |
| build failures       | build/compile phase exit codes      | OBSERVED           |
| CPU / RAM            | process-tree sampling (psutil/ps)   | OBSERVED samples; integrals ESTIMATED |
| errors, retries      | event stream (harness + ingested logs) | OBSERVED        |
| tool calls           | agent session logs                  | OBSERVED when logged |
| token usage          | usage records in logs               | OBSERVED; chars/4 ESTIMATED only if explicitly enabled; otherwise UNAVAILABLE |
| features delivered   | optional `features.yaml` manifest vs test evidence | ESTIMATED |

## Quality dimensions (overall = weighted mean)

Completion 20% · Reliability 15% · Testing 15% · Architecture 12.5% ·
Autonomy 12.5% · Maintainability 10% · Performance 7.5% · Documentation 7.5%

Every dimension decomposes into weighted components with formulas, notes and
provenance - fully specified in [docs/METRICS.md](docs/METRICS.md).

## Installation

Requires Python 3.10+.

```bash
git clone https://github.com/shubhraj5575/frontier-agent-benchmark.git
cd frontier-agent-benchmark
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"          # pytest, psutil, pyyaml, coverage
fab doctor                       # verify telemetry capabilities
```

Optional extras: `go` / `cargo` / `npx` on PATH unlock go/rust/js suites.

## Quickstart

```bash
python examples/build_demo_subjects.py   # real fixture repos w/ histories

# 1. build the demo subjects (real repos, real multi-commit histories)
python examples/build_demo_subjects.py

# 2. run the full pipeline (collect -> execute -> score -> compare -> report)
fab run --ingest examples/demo_logs/demo-atlas-session.jsonl \
        --ingest examples/demo_logs/demo-volt-session.jsonl

# 3. browse
fab serve --open                 # dashboard at http://localhost:8737
```

Results land in `output/results/` and `output/dashboard/index.html`
(self-contained, works offline, no CDN).

## API sketch (library use)

```python
from fab.config import load_config
from fab.collector import collect_static, collect_dynamic
from fab.scoring.engine import score_project
from fab.analysis.comparison import compare
from fab.report.final_report import generate_final_report

cfg = load_config("bench.yaml")
bundle, ws = collect_dynamic(cfg.subject("my-project"), Path("output"), cfg)
card = score_project(bundle, cfg.scoring_weights)
print(card.to_dict())            # every component + provenance + formula
```

Everything is importable; the CLI is a thin wrapper over these calls.

### Benchmark your own agent-built projects

```yaml
# bench.yaml
version: 1
subjects:
  - name: my-agent-project
    path: /path/to/project            # analysed read-only, never modified
    entrypoint: python -m myapp --help  # smoke-run proving it starts
    # build_cmd: npm run build          # optional explicit build
    # features_file: features.yaml     # optional feature manifest
```

```bash
fab run
```

### Capture telemetry while your agent works

Wrap any command - an agent CLI, a task runner, anything:

```bash
fab watch --project my-agent -- python agent.py solve-task
# -> output/sessions/last-watch.json : runtime, CPU/RAM peaks, events
```

Ingest existing session logs (JSONL transcripts with usage/tool fields,
plain-text logs):

```bash
fab run --ingest ~/.claude/projects/*/session.jsonl --ingest-project my-agent
fab ingest some-session.jsonl --project my-agent   # inspect one log
```

## Subject isolation guarantee

FAB analyses subject repositories **read-only** (porcelain git queries and
file scans). Anything executed - builds, test suites, smoke runs - happens in
an isolated copy under the system temp directory, never in the original tree,
and outside the FAB repo itself so no parent config can leak into the
subject's toolchain. A regression test enforces this.

## Event stream

Canonical taxonomy includes all nine required event types plus supporting
signals:

`agent_started · task_completed · test_failed · bug_discovered · bug_fixed ·
commit_created · benchmark_completed · build_failed · milestone_reached` +
`test_passed · build_succeeded · error_observed · retry_attempted ·
tool_call · intervention_requested …`

Events come from real observations (harness runs, git history) and ingested
agent logs. Heuristic classifications are tagged ESTIMATED.

## Repository layout

```
fab/                    the platform package
  models.py             provenance-tagged measurements & canonical events
  config.py             bench.yaml/json loading & validation
  collector.py          orchestrates static + dynamic collection
  store.py              SQLite persistence
  scoring/              8 dimension scorers + overall engine
  analysis/comparison.py rankings, efficiency, failure/recovery analysis
  report/               JSON/CSV/Markdown exporters + final report
  dashboard/generator.py self-contained offline HTML dashboard
  telemetry/            git, code analysis, harness, procmon, log ingest
examples/
  build_demo_subjects.py constructs fixture projects w/ real histories
  demo_logs.py          synthetic agent-transcript fixtures (documented)
tests/                  75+ tests incl. isolation & honesty guarantees
docs/                   METRICS.md, ARCHITECTURE.md
output/                 generated: results/, dashboard/, demo-subjects/
```

## Development

```bash
pip install -e ".[dev]"
pytest                  # full suite
python -m pyflakes fab/ # lint
fab run                 # regenerate results (includes 'fab-self' dogfooding)
```

The demo configuration benchmarks FAB **against itself** (`fab-self`
subject) - the platform eats its own cooking every run.

## Contributing

- `pytest -q` must stay green; `python -m pyflakes fab/` clean.
- New telemetry must carry provenance; new scores need a METRICS.md entry.
- Never write inside subject repositories - tests enforce this.
- PRs welcome: keep changes focused and document formulas.

## Design notes

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for system design and
[docs/METRICS.md](docs/METRICS.md) for the complete scoring specification.

## License

MIT
