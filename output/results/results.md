# Frontier Agent Benchmark - Results

| Rank | Project | Overall | Grade | Data coverage |
|-----:|---------|--------:|:------|--------------:|
| 1 | demo-atlas | 92.88 | A | 90% |
| 2 | fab-self | 81.07 | B+ | 76% |
| 3 | demo-volt | 65.8 | C+ | 90% |
| 4 | demo-cascade | 51.69 | D | 83% |

| Project | Completion | Reliability | Testing | Architecture | Performance | Documentation | Autonomy | Maintainability |
|---|---|---|---|---|---|---|---|---|
| demo-atlas | 100.0 | 100.0 | 77.3 | 95.5 | 100.0 | 60.3 | 100.0 | 97.2 |
| fab-self | 80.8 | 100.0 | 99.5 | 82.3 | 88.0 | 37.5 | - | 72.6 |
| demo-volt | 70.0 | 74.2 | 68.3 | 87.2 | 100.0 | 7.8 | 22.5 | 92.8 |
| demo-cascade | 73.3 | 24.2 | 40.6 | 73.2 | 100.0 | 0.0 | 0.0 | 51.4 |

*`-` = UNAVAILABLE (no data; never treated as zero).*

## demo-atlas

- Overall engineering score: **92.88** (A), data coverage 90%
- Git: repo, 8 commits (OBSERVED)
- Code: 106 SLOC across 9 files
- Tests executed: 7 passed / 0 failed
- Tokens: 10230 (OBSERVED)
- Failures observed: 1 (recovered 1, MTTR 500.0s)

## fab-self

- Overall engineering score: **81.07** (B+), data coverage 76%
- Git: repo, 5 commits (OBSERVED)
- Code: 5335 SLOC across 36 files
- Tests executed: 75 passed / 0 failed
- Failures observed: 0 (recovered 0, MTTR n/as)

## demo-volt

- Overall engineering score: **65.8** (C+), data coverage 90%
- Git: repo, 6 commits (OBSERVED)
- Code: 62 SLOC across 9 files
- Tests executed: 5 passed / 1 failed
- Tokens: 1250 (OBSERVED)
- Failures observed: 2 (recovered 1, MTTR 31915279.78s)

## demo-cascade

- Overall engineering score: **51.69** (D), data coverage 83%
- Git: repo, 4 commits (OBSERVED)
- Code: 63 SLOC across 5 files
- Tests executed: 1 passed / 2 failed
- Failures observed: 1 (recovered 0, MTTR n/as)

## Verdicts

- **Most Complete**: demo-atlas (100.0)
- **Most Reliable**: fab-self (100.0)
- **Strongest Architecture**: demo-atlas (95.5)
- **Best Tests**: fab-self (99.5)
- **Best Performance**: demo-atlas (100.0)
- **Strongest Autonomy**: demo-atlas (100.0)
- **Most Maintainable**: demo-atlas (97.2)
- **Most Efficient Compute**: unavailable
- **Most Failures**: demo-volt
- **Best Failure Recovery**: demo-atlas
