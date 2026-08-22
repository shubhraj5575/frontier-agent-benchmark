# FAB Architecture

```
                    bench.yaml / bench.json
                            |
                    +-------v--------+
                    |     config     |  validation, weights sum=1, complete specs
                    +-------+--------+
                            |
              +-------------v--------------+
              |         collector          |
              |  (per subject, read-only)  |
              +---+----------+---------+---+
                  |          |         |
        static    |          | dynamic |        optional
   +--------------+--+  +----v------+----+   +---------------+
   | git_telemetry   |  | workspace.py   |   | log_ingest    |
   |  log --numstat  |  | copy to temp/  |   |  JSONL/text   |
   |  status, HEAD   |  +----+------+----+   |  usage/tools  |
   +-----------------+       |               |  retries      |
   | code_analysis   |   harness.py          +-------+-------+
   |  LOC, AST CC,   |   build -> tests -> smoke     |
   |  docstrings,    |   process_monitor             |
   |  duplication,   |   CPU/RAM sampling            |
   |  import graph   |   JUnit XML parsing           |
   +--------+--------+--------+-----------+--------+
            |                 |           |
            +--------+--------+-----+-----+
                     v              v
              ProjectBundle   canonical Event stream
              (measurements   (9 required types +
               w/ provenance)  supporting signals)
                     |              |
              +------v--------------v------+
              |     scoring engine         |
              |  8 dimensions -> overall   |
              |  coverage-weighted         |
              +------+---------------------+
                     v
              +------------+     +--------------------+
              | SQLite     |     | comparison engine  |
              | store      |     | rankings, deltas,  |
              +-----+------+     | efficiency, MTTR   |
                    v            +---------+----------+
        +---------+----------+-----------+
        v         v          v           v
   results.json  CSV   final_report.md  dashboard/index.html
                                        (offline, embedded JSON)
```

## Design decisions

### Provenance at the type level
`Measurement` wraps every datum with `Provenance.OBSERVED|ESTIMATED|UNAVAILABLE`.
Aggregation helpers refuse to treat UNAVAILABLE as zero; scores carry coverage.
This makes fabrication a type error rather than a discipline problem.

### Isolation
Subjects are copied to `$TMPDIR/fab-workspaces/<project>-<hash>` before any
execution. The original tree is never written; regression tests verify byte
identity of the subject across collection. Workspaces sit outside both the
subject and FAB repos so parent configs cannot leak into tool invocations.

### Normalized invocation
Test suites run with `-o addopts=` (subject pytest addopts intentionally
ignored), `--rootdir` pinned, caches disabled, and a JUnit XML report.
Machine-readable counts make parsing immune to verbosity flags - text
summaries remain as fallback for other frameworks.

### Event taxonomy
Nine spec-required event types are first-class; supporting types
(retry/tool-call/error/intervention) enable autonomy and reliability scoring.
Heuristic classifications (e.g. "this commit message implies bug fixed") are
tagged ESTIMATED; direct observations OBSERVED.

### Scoring shape
Each dimension = weighted components; each component = value + provenance +
formula string. UNAVAILABLE components drop out of the mean and shrink
coverage. Dimensions themselves aggregate into an overall score weighted by
config (defaults in `fab/config.py:DEFAULT_WEIGHTS`, must sum to 1.0).

### Self-benchmarking (dogfooding)
The demo config includes `fab-self` pointing at FAB's own repository with
fixture trees excluded. Every pipeline run re-proves the platform against its
own code quality bar; findings (unused imports, complexity hotspots, config
leaks) were real bugs fixed during development.

## Extension points

- **New telemetry source**: implement collector -> produce Measurements/Events
  with provenance -> merge into bundle (`collector.merge_ingest` pattern).
- **New framework**: add detection in `telemetry/harness.detect_test_plan`,
  a parser in `PARSERS`, or emit JUnit XML (preferred).
- **New score dimension**: scorer function in `scoring/dimensions.py`,
  register in `DIMENSION_SCORERS`, weight in config (complete spec required).
- **Agent runs**: wrap with `fab watch` or ingest logs post-hoc; both feed the
  same event stream and measurement store.
