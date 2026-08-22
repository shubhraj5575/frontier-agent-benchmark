# Frontier Agent Benchmark (FAB)

Independent observability and benchmarking platform for evaluating
**autonomous AI engineering agents** on *engineering quality* - not volume.

FAB measures what actually matters:

- **Completion** - did it build something that builds and runs?
- **Reliability** - do tests pass consistently? how does it recover?
- **Testing** - real test suites with real coverage
- **Architecture** - modularity, coupling, layering, dependency hygiene
- **Performance** - measured wall time, CPU and memory of build/test/smoke runs
- **Documentation** - READMEs, docstrings, changelogs
- **Autonomy** - self-correction cycles, unattended completion, retries that work
- **Maintainability** - complexity, duplication, TODO debt

Lines of code, commit counts and token consumption are recorded as *context*,
never used to rank agents.

## Core principle: provenance discipline

Every number in FAB carries one of three labels, enforced at the type level:

| Label         | Meaning                                                        |
|---------------|----------------------------------------------------------------|
| `OBSERVED`    | Directly measured (git log, process samples, tool exit codes)  |
| `ESTIMATED`   | Derived via documented heuristic (e.g. duplication shingling)  |
| `UNAVAILABLE` | Not present in any source; rendered as n/a, never treated as 0 |

FAB never fabricates telemetry.

## Status

Work in progress - see `docs/` for design notes.
