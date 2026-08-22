# FAB Metrics Specification

Every score in FAB is decomposed into **weighted components**. Each component
records its value (or UNAVAILABLE), provenance, and its formula. Components
without data are excluded from aggregation; their weight is redistributed and
the dimension reports *coverage* - the fraction of weight backed by data.

Overall Engineering Score = weighted mean over dimensions, each contributing
`weight x max(0.5, coverage)`. `overall_coverage` reports how much of the
total weight was actually evidenced.

Helper functions:

- `saturate(x, cap)` = `1 - exp(-2.2 x / cap)` - diminishing returns
- `penalty_band(v, ideal_hi, hard_hi)` = 1.0 while `v <= ideal_hi`, decaying
  linearly to a 0.05 floor at `hard_hi` (one-sided; low values are never punished)
- `band(v, lo, ilo, ihi, hi)` = trapezoid membership (two-sided metrics)

---

## 1. Completion - weight 0.20

| Component | Weight | Formula | Provenance |
|---|---|---|---|
| build_succeeds | 0.30 | 100 if build/compile phase exit == 0 else 0 | OBSERVED |
| entrypoint_runs | 0.30 | 100 if smoke-run exit == 0 else 0 | OBSERVED |
| behavior_delivered | 0.40 | see below | ESTIMATED |

`behavior_delivered`:

- With a `features.yaml/json` manifest: fraction of declared features whose
  slug words appear in test files (>=50% word overlap), times 1.0 if the suite
  passed, 0.5 otherwise.
- Without a manifest: share of unique public function names in non-test code
  referenced by any test file, halved when the executed suite has failures.

## 2. Reliability - weight 0.15

| Component | Weight | Formula | Provenance |
|---|---|---|---|
| test_pass_rate | 0.40 | mean over runs of passed / (passed+failed+errors) | OBSERVED |
| stability_across_runs | 0.20 | min(pass_rate) / max(pass_rate) across >= 2 runs | OBSERVED |
| error_density | 0.25 | exp decay of error+build-failure events per hour of runtime | OBSERVED |
| recovery_after_failures | 0.15 | failures followed by a later success event / failures | OBSERVED |

Absence of errors or failures is reported as UNAVAILABLE with an explicit
note ("nothing to recover from") - never as a perfect score.

## 3. Testing - weight 0.15

| Component | Weight | Formula | Provenance |
|---|---|---|---|
| suite_scale | 0.25 | 100 x saturate(n_tests_executed, cap=40); presence-only fallback penalised 5:1 | OBSERVED |
| pass_rate | 0.35 | passed / attempted | OBSERVED |
| line_coverage | 0.25 | coverage% scaled, small bonus at >=90% | OBSERVED (coverage.py/lcov) |
| test_to_code_balance | 0.15 | band(test_sloc/code_sloc, ideal 0.12..0.8) | OBSERVED |

## 4. Architecture - weight 0.125

| Component | Weight | Formula | Notes |
|---|---|---|---|
| module_size_discipline | 0.30 | 0.6 x (1 - SLOC-share in files >500) + 0.4 x penalty_band(avg file SLOC, 260, 700) | OBSERVED |
| coupling_control | 0.25 | (100 - 12 per circular import cycle) x (0.35 + 0.65 x penalty_band(avg fan-out, 3, 7)) | import graph via Python AST |
| layering_and_layout | 0.20 | checklist: src/package layout 40, tests dir 30, dependency manifest/CI 30 | OBSERVED |
| dependency_hygiene | 0.15 | pinned deps / total deps; neutral 55 when no manifest | OBSERVED |
| complexity_ceiling | 0.10 | penalty_band(max cyclomatic complexity, 14, 26) | AST McCabe counts |

## 5. Performance - weight 0.075

All components come from monitored runs (process-tree sampling).

| Component | Weight | Formula |
|---|---|---|
| suite_wall_time | 0.40 | step bands: <=2s=100, <=10s=85, <=30s=70, <=120s=50, <=600s=30, else 15 |
| memory_efficiency | 0.30 | MB/kLOC band (60..400) for >=10kLOC subjects; absolute MB band (400..2000) below that |
| startup_latency | 0.30 | penalty_band(smoke-run seconds, 3, 12) |

## 6. Documentation - weight 0.075

| Component | Weight | Formula |
|---|---|---|
| readme_quality | 0.35 | (35 + 11 x sections-present up to 6) x word-count band factor |
| docstring_coverage | 0.30 | documented public functions / public functions (Python AST) |
| changelog_versioning | 0.15 | changelog file 50 + version declaration 50 |
| supporting_docs | 0.20 | extra markdown 40 + docs/ dir 40 + CI config 20 |

## 7. Autonomy - weight 0.125

Requires behavioural evidence from an event stream (ingested agent logs).
Without it the dimension is UNAVAILABLE and honestly excluded.

| Component | Weight | Formula | Provenance |
|---|---|---|---|
| self_correction_ratio | 0.35 | bug_fixed / bug_discovered (capped at 1) | follows event labels (OBS or EST) |
| unattended_completion | 0.30 | tasks_completed / (tasks_completed + intervention_requests) | OBSERVED |
| retry_effectiveness | 0.20 | retries followed by success within 15min / retries | ESTIMATED window heuristic |
| tool_success_rate | 0.15 | tool calls with explicit success flag / total tool calls | ESTIMATED |

A harness smoke-run is deliberately NOT task completion evidence - it emits
RUN_FINISHED so autonomy can never be inflated by the benchmark itself.

## 8. Maintainability - weight 0.10

| Component | Weight | Formula |
|---|---|---|
| avg_complexity | 0.30 | penalty_band(mean cyclomatic complexity, 5, 9) |
| low_duplication | 0.25 | 100 x (1 - duplicated-SLOC fraction), 6-line shingle heuristic | 
| file_size_distribution | 0.20 | 100 x (1 - min(4 x share of >500-sloc files, 1)) |
| todo_debt | 0.15 | penalty_band(TODO/FIXME per kLOC, 8, 25) |
| code_smell_count | 0.10 | decay of weighted smells: mutable-default args x10, bare excepts x6, unused imports x2 (est.) |

---

## Comparative measures

- **Rankings** per dimension and overall (available scores ranked; UNAVAILABLE shown as such)
- **Pairwise delta matrix** on overall scores
- **Compute efficiency**: overall score per CPU core-second (integral of sampled CPU; ESTIMATED between samples); score per 1k tokens when token data exists
- **Failure analysis**: build/test failure counts, errors observed, recovery rate, mean time to recovery (OBSERVED)

## Threats to validity (documented honestly)

- Static heuristics (duplication, feature matching, docstring density) are
  approximations tagged ESTIMATED.
- Absolute performance bands are calibrated for typical agent-scale CLI/library
  projects; cohort-relative normalisation is reported separately in comparisons.
- Autonomy requires logs; benchmarks without them under-report autonomy by
  construction (coverage drops rather than scores being invented).
- Single-shot runs cannot measure flakiness; supply repeated runs (future:
  `--repeats`) to enable the stability component.
