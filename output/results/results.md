# Frontier Agent Benchmark - Results

| Rank | Project | Overall | Grade | Data coverage |
|-----:|---------|--------:|:------|--------------:|
| 1 | demo-atlas | 93.11 | A+ | 92% |
| 2 | fab-self | 82.14 | B+ | 78% |
| 3 | demo-volt | 66.51 | C+ | 92% |
| 4 | demo-cascade | 53.37 | D | 86% |

| Project | Completion | Reliability | Testing | Architecture | Performance | Documentation | Autonomy | Maintainability |
|---|---|---|---|---|---|---|---|---|
| demo-atlas | 100.0 | 100.0 | 77.3 | 95.5 | 100.0 | 60.3 | 100.0 | 97.2 |
| fab-self | 80.6 | 100.0 | 99.5 | 82.3 | 88.0 | 45.4 | - | 72.6 |
| demo-volt | 70.0 | 77.8 | 68.3 | 87.2 | 100.0 | 7.8 | 22.5 | 92.8 |
| demo-cascade | 73.3 | 44.4 | 40.6 | 73.2 | 100.0 | 0.0 | 0.0 | 51.4 |

*`-` = UNAVAILABLE (no data; never treated as zero).*

## demo-atlas

- Overall engineering score: **93.11** (A+), data coverage 92%
- Git: repo, 8 commits (OBSERVED)
- Code: 106 SLOC across 9 files
- Tests executed: 7 passed / 0 failed
- Tokens: 10230 (OBSERVED)
- Failures observed: 1 (recovered 1, MTTR 500.0s)

## fab-self

- Overall engineering score: **82.14** (B+), data coverage 78%
- Git: repo, 8 commits (OBSERVED)
- Code: 5413 SLOC across 36 files
- Tests executed: 76 passed / 0 failed
- Failures observed: 0 (recovered 0, MTTR n/as)

## demo-volt

- Overall engineering score: **66.51** (C+), data coverage 92%
- Git: repo, 6 commits (OBSERVED)
- Code: 62 SLOC across 9 files
- Tests executed: 5 passed / 1 failed
- Tokens: 1250 (OBSERVED)
- Failures observed: 3 (recovered 1, MTTR 31916235.82s)

## demo-cascade

- Overall engineering score: **53.37** (D), data coverage 86%
- Git: repo, 4 commits (OBSERVED)
- Code: 63 SLOC across 5 files
- Tests executed: 1 passed / 2 failed
- Failures observed: 2 (recovered 0, MTTR n/as)

## Verdicts

- **Most Complete**: demo-atlas (100.0)
- **Most Reliable**: demo-atlas (100.0)
- **Strongest Architecture**: demo-atlas (95.5)
- **Best Tests**: fab-self (99.5)
- **Best Performance**: demo-atlas (100.0)
- **Strongest Autonomy**: demo-atlas (100.0)
- **Most Maintainable**: demo-atlas (97.2)
- **Most Efficient Compute**: unavailable
- **Most Failures**: demo-volt
- **Best Failure Recovery**: demo-atlas
