# Frontier Agent Benchmark - Final Report

*Generated 2026-08-22T19:41:23Z - FAB v0.1.0*

Session logs ingested as evidence: `examples/demo_logs/demo-atlas-session.jsonl` -> demo-atlas (15 records), `examples/demo_logs/demo-volt-session.jsonl` -> demo-volt (10 records)

*Fixture transcripts included in the demo config are synthetic examples of agent logs, ingested to exercise the pipeline; their contents are tagged by the provenance system like any other source.*

---

## Provenance legend

| Label | Meaning | Trust level |
|-------|---------|-------------|
| **OBSERVED** | directly measured by a collector (git log, process samples, test-runner exit codes) | reproducible evidence |
| **ESTIMATED** | derived via a documented heuristic from observed raw material | directional; heuristic named inline |
| **UNAVAILABLE** | not present in any source provided | reported as `n/a`; never treated as zero |

Across this run: **208** observed, **34** estimated, **4** unavailable measurements/events (85% observed).

## Leaderboard

| Rank | Project | Overall Engineering Score | Grade | Backed by data |
|-----:|---------|--------------------------:|:------|---------------:|
| 1 | **demo-atlas** | 92.62 | A | 92% |
| 2 | **fab-self** | 82.59 | B+ | 78% |
| 3 | **demo-volt** | 66.51 | C+ | 92% |
| 4 | **demo-cascade** | 53.37 | D | 86% |

> The overall score is a weighted mean of available dimension scores (weights in docs/METRICS.md). Dimensions with no backing data are excluded rather than zeroed, so `Backed by data` shows how much of the weight was actually evidenced.

## Dimension scores

| Project | Completion | Reliability | Testing | Architecture | Performance | Documentation | Autonomy | Maintainability |
|---|---|---|---|---|---|---|---|---|
| demo-atlas | 100.0 | 100.0 (75%) | 77.3 (75%) | 95.5 | 94.0 | 60.3 | 100.0 | 97.2 |
| fab-self | 81.0 | 100.0 (60%) | 99.6 (75%) | 82.3 | 88.0 | 49.3 | n/a | 72.3 |
| demo-volt | 70.0 | 77.8 (75%) | 68.3 (75%) | 87.2 | 100.0 | 7.8 | 22.5 | 92.8 |
| demo-cascade | 73.3 | 44.4 (75%) | 40.6 (75%) | 73.2 | 100.0 | 0.0 | 0.0 (35%) | 51.4 |

`n/a` = UNAVAILABLE. `(xx%)` after a value = share of that dimension's weight backed by collected data.

## Answers to the nine questions

- **Which project is most complete?** -> `demo-atlas` (score 100.0, OBSERVED from collected telemetry). Evidence: behavior delivered=100; build succeeds=100.
- **Which project is most reliable?** -> `demo-atlas` (score 100.0, OBSERVED from collected telemetry). Evidence: test pass rate=100; stability across runs=100.
- **Which has the strongest architecture?** -> `demo-atlas` (score 95.5, OBSERVED from collected telemetry). Evidence: module size discipline=100; coupling control=100.
- **Which has the best tests?** -> `fab-self` (score 99.6, OBSERVED from collected telemetry). Evidence: pass rate=100; suite scale=99.
- **Which has the best performance?** -> `demo-cascade` (score 100.0, OBSERVED from collected telemetry). Evidence: suite wall time=100; memory efficiency=100.
- **Which demonstrates the strongest autonomy?** -> `demo-atlas` (score 100.0, OBSERVED from collected telemetry). Evidence: self correction ratio=100; unattended completion=100.
- **Which uses compute most efficiently?** -> **UNAVAILABLE**: no CPU sampling data was captured for any subject.
- **Which encounters the most failures?** -> `demo-volt` (3 failure events, OBSERVED).
- **Which recovers from failures most effectively?** -> `demo-atlas` (100% recovery rate, MTTR 500.0s, OBSERVED).

## Project detail - demo-atlas

- Overall: **92.62** (A) - 92% of scoring weight backed by data

**Telemetry**

| Metric | Value |
|--------|-------|
| Session start | 2026-08-22T19:41:23Z |
| Runtime (collection session) | 9.1s |
| Git commits | 8 *(OBSERVED)* |
| First commit | 2026-08-20T17:35:46Z *(OBSERVED)* |
| Last commit | 2026-08-21T19:29:46Z *(OBSERVED)* |
| Files | 9 |
| Lines of code (SLOC) | 106 *(OBSERVED)* |
| Test SLOC | 39 *(OBSERVED)* |
| Tests executed | 7 passed / 0 failed / 0 errors (OBSERVED) |
| Test coverage | n/a *(UNAVAILABLE: no machine-readable coverage report found)* |
| Build result | success (OBSERVED) |
| Peak RAM across phases | 32 MB (OBSERVED) |
| Token usage | 10230 *(OBSERVED; from agent usage records)* |
| Tool calls | 2 *(OBSERVED)* |
| Errors observed | 0 (OBSERVED event count) |
| Retries | 1 (OBSERVED) |
| Failure/recovery | 1 failures, 1 recovered, MTTR 500.0s |
| Feature manifest | none declared |

**Score components**

- Completion: **100.0** (data coverage 100%)
  - build_succeeds: 100 [OBSERVED] - exit code of build/compile phase
  - entrypoint_runs: 100 [OBSERVED] - entrypoint: python3 -c "import sys; from atlas.queue import Queue; q=Queue(); q.push('job'); t=q.pop(); assert t.name=='job'; print('atlas ok')"
  - behavior_delivered: 100 [ESTIMATED] - declared features with matching passing tests
- Reliability: **100.0** (data coverage 75%)
  - test_pass_rate: 100 [OBSERVED] - 2 test run(s)
  - stability_across_runs: 100 [OBSERVED] - 2 repeated runs
  - error_density: - [OBSERVED] - no error/build-failure events observed
  - recovery_after_failures: 100 [OBSERVED] - 1/1 failures followed by a later success event
- Testing: **77.3** (data coverage 75%)
  - suite_scale: 32 [OBSERVED] - 7 tests executed
  - pass_rate: 100 [OBSERVED]
  - line_coverage: - [OBSERVED] - no machine-readable coverage report found
  - test_to_code_balance: 100 [OBSERVED] - ratio=0.582
- Architecture: **95.5** (data coverage 100%)
  - module_size_discipline: 100 [OBSERVED] - avg file 12 sloc; 0 file(s) >500
  - coupling_control: 100 [OBSERVED] - 0 circular cycle(s); avg fan-out 0.5
  - layering_and_layout: 100 [OBSERVED] - src/tests/config separated
  - dependency_hygiene: 70 [OBSERVED] - manifest(s) present but no unpinned deps detected
  - complexity_ceiling: 100 [OBSERVED] - max cyclomatic complexity 6
- Performance: **94.0** (data coverage 100%)
  - suite_wall_time: 85 [OBSERVED] - tests finished in 2.53s
  - memory_efficiency: 100 [OBSERVED] - peak RSS 32MB (absolute; project below 10kLOC)
  - startup_latency: 100 [OBSERVED] - entrypoint responded in 0.06s
- Documentation: **60.3** (data coverage 100%)
  - readme_quality: 79 [OBSERVED] - 46 words, 4/6 core sections
  - docstring_coverage: 57 [OBSERVED] - 57% of public functions documented
  - changelog_versioning: 50 [OBSERVED] - changelog
  - supporting_docs: 40 [OBSERVED] - 1 extra markdown file(s)
- Autonomy: **100.0** (data coverage 100%)
  - self_correction_ratio: 100 [ESTIMATED] - 2 fix(es) vs 1 discovered bug(s) (some labels derived heuristically)
  - unattended_completion: 100 [OBSERVED] - 3 task completion(s), 0 intervention request(s)
  - retry_effectiveness: 100 [ESTIMATED] - 1/1 retry(ies) followed by success within 15min window
  - tool_success_rate: 100 [ESTIMATED] - 2/2 tool calls with explicit success flag
- Maintainability: **97.2** (data coverage 100%)
  - avg_complexity: 100 [OBSERVED] - avg cyclomatic complexity 2.43
  - low_duplication: 100 [ESTIMATED] - no duplicated blocks detected
  - file_size_distribution: 100 [OBSERVED] - 0/9 files exceed 500 sloc
  - todo_debt: 100 [OBSERVED] - 0 TODO/FIXME (0.0/kLOC)
  - code_smell_count: 72 [ESTIMATED] - 0 mutable-default args, 0 bare excepts, ~3 unused imports (est.)

## Project detail - fab-self

- Overall: **82.59** (B+) - 78% of scoring weight backed by data

**Telemetry**

| Metric | Value |
|--------|-------|
| Session start | 2026-08-22T19:41:41Z |
| Runtime (collection session) | 54.2s |
| Git commits | 10 *(OBSERVED)* |
| First commit | 2026-08-22T17:38:32Z *(OBSERVED)* |
| Last commit | 2026-08-22T19:37:00Z *(OBSERVED)* |
| Files | 37 |
| Lines of code (SLOC) | 5596 *(OBSERVED)* |
| Test SLOC | 1049 *(OBSERVED)* |
| Tests executed | 79 passed / 0 failed / 0 errors (OBSERVED) |
| Test coverage | n/a *(UNAVAILABLE: no machine-readable coverage report found)* |
| Build result | success (OBSERVED) |
| Peak RAM across phases | 84 MB (OBSERVED) |
| Token usage | n/a *(UNAVAILABLE)* |
| Tool calls | n/a *(UNAVAILABLE)* |
| Errors observed | 0 (OBSERVED event count) |
| Retries | none observed (distinct from unknown) |
| Failure/recovery | 0 failures, 0 recovered |
| Feature manifest | none declared |

**Score components**

- Completion: **81.0** (data coverage 100%)
  - build_succeeds: 100 [OBSERVED] - exit code of build/compile phase
  - entrypoint_runs: 100 [OBSERVED] - entrypoint: python3 -m fab.cli --help
  - behavior_delivered: 52 [ESTIMATED] - public functions referenced by test files
- Reliability: **100.0** (data coverage 60%)
  - test_pass_rate: 100 [OBSERVED] - 2 test run(s)
  - stability_across_runs: 100 [OBSERVED] - 2 repeated runs
  - error_density: - [OBSERVED] - no error/build-failure events observed
  - recovery_after_failures: - [OBSERVED] - no failure events to assess recovery from
- Testing: **99.6** (data coverage 75%)
  - suite_scale: 99 [OBSERVED] - 79 tests executed
  - pass_rate: 100 [OBSERVED]
  - line_coverage: - [OBSERVED] - no machine-readable coverage report found
  - test_to_code_balance: 100 [OBSERVED] - ratio=0.231
- Architecture: **82.3** (data coverage 100%)
  - module_size_discipline: 88 [OBSERVED] - avg file 151 sloc; 2 file(s) >500
  - coupling_control: 100 [OBSERVED] - 0 circular cycle(s); avg fan-out 2.2
  - layering_and_layout: 100 [OBSERVED] - src/tests/config separated
  - dependency_hygiene: 70 [OBSERVED] - manifest(s) present but no unpinned deps detected
  - complexity_ceiling: 5 [OBSERVED] - max cyclomatic complexity 51
- Performance: **88.0** (data coverage 100%)
  - suite_wall_time: 70 [OBSERVED] - tests finished in 14.27s
  - memory_efficiency: 100 [OBSERVED] - peak RSS 81MB (absolute; project below 10kLOC)
  - startup_latency: 100 [OBSERVED] - entrypoint responded in 0.12s
- Documentation: **49.3** (data coverage 100%)
  - readme_quality: 68 [OBSERVED] - 863 words, 3/6 core sections
  - docstring_coverage: 20 [OBSERVED] - 20% of public functions documented
  - changelog_versioning: 50 [OBSERVED] - no changelog + version declared
  - supporting_docs: 60 [OBSERVED] - 0 extra markdown file(s), docs/, CI
- Autonomy: **n/a** (data coverage 0%)
  - self_correction_ratio: - [OBSERVED] - no bug lifecycle events observed
  - unattended_completion: - [OBSERVED] - no task lifecycle events observed
  - retry_effectiveness: - [OBSERVED] - no retry signals observed
  - tool_success_rate: - [OBSERVED] - no tool-call records ingested
- Maintainability: **72.3** (data coverage 100%)
  - avg_complexity: 52 [OBSERVED] - avg cyclomatic complexity 6.92
  - low_duplication: 99 [ESTIMATED] - 0.8% duplicated SLOC (shingle estimate)
  - file_size_distribution: 78 [OBSERVED] - 2/37 files exceed 500 sloc
  - todo_debt: 100 [OBSERVED] - 7 TODO/FIXME (1.3/kLOC)
  - code_smell_count: 12 [ESTIMATED] - 0 mutable-default args, 0 bare excepts, ~19 unused imports (est.)

## Project detail - demo-volt

- Overall: **66.51** (C+) - 92% of scoring weight backed by data

**Telemetry**

| Metric | Value |
|--------|-------|
| Session start | 2026-08-22T19:41:32Z |
| Runtime (collection session) | 4.5s |
| Git commits | 6 *(OBSERVED)* |
| First commit | 2026-08-20T17:35:46Z *(OBSERVED)* |
| Last commit | 2026-08-21T12:05:46Z *(OBSERVED)* |
| Files | 9 |
| Lines of code (SLOC) | 62 *(OBSERVED)* |
| Test SLOC | 17 *(OBSERVED)* |
| Tests executed | 5 passed / 1 failed / 0 errors (OBSERVED) |
| Test coverage | n/a *(UNAVAILABLE: no machine-readable coverage report found)* |
| Build result | success (OBSERVED) |
| Peak RAM across phases | 35 MB (OBSERVED) |
| Token usage | 1250 *(OBSERVED; from agent usage records)* |
| Tool calls | 2 *(OBSERVED)* |
| Errors observed | 0 (OBSERVED event count) |
| Retries | 1 (OBSERVED) |
| Failure/recovery | 3 failures, 1 recovered, MTTR 31916592.74s |
| Feature manifest | none declared |

**Score components**

- Completion: **70.0** (data coverage 100%)
  - build_succeeds: 100 [OBSERVED] - exit code of build/compile phase
  - entrypoint_runs: 100 [OBSERVED] - entrypoint: python3 -m volt.cli --help
  - behavior_delivered: 25 [ESTIMATED] - declared features with matching passing tests
- Reliability: **77.8** (data coverage 75%)
  - test_pass_rate: 83 [OBSERVED] - 2 test run(s)
  - stability_across_runs: 100 [OBSERVED] - 2 repeated runs
  - error_density: - [OBSERVED] - no error/build-failure events observed
  - recovery_after_failures: 33 [OBSERVED] - 1/3 failures followed by a later success event
- Testing: **68.3** (data coverage 75%)
  - suite_scale: 28 [OBSERVED] - 6 tests executed
  - pass_rate: 83 [OBSERVED]
  - line_coverage: - [OBSERVED] - no machine-readable coverage report found
  - test_to_code_balance: 100 [OBSERVED] - ratio=0.378
- Architecture: **87.2** (data coverage 100%)
  - module_size_discipline: 100 [OBSERVED] - avg file 7 sloc; 0 file(s) >500
  - coupling_control: 100 [OBSERVED] - 0 circular cycle(s); avg fan-out 0.4
  - layering_and_layout: 70 [OBSERVED] - no dependency manifest / CI config
  - dependency_hygiene: 55 [OBSERVED] - no dependency manifest; treated as minimal-dependency project
  - complexity_ceiling: 100 [OBSERVED] - max cyclomatic complexity 5
- Performance: **100.0** (data coverage 100%)
  - suite_wall_time: 100 [OBSERVED] - tests finished in 0.83s
  - memory_efficiency: 100 [OBSERVED] - peak RSS 34MB (absolute; project below 10kLOC)
  - startup_latency: 100 [OBSERVED] - entrypoint responded in 0.06s
- Documentation: **7.8** (data coverage 100%)
  - readme_quality: 5 [OBSERVED] - 5 words, 0/6 core sections
  - docstring_coverage: 20 [OBSERVED] - 20% of public functions documented
  - changelog_versioning: 0 [OBSERVED] - no changelog
  - supporting_docs: 0 [OBSERVED] - 0 extra markdown file(s)
- Autonomy: **22.5** (data coverage 100%)
  - self_correction_ratio: 0 [ESTIMATED] - 0 fix(es) vs 7 discovered bug(s) (some labels derived heuristically)
  - unattended_completion: 50 [OBSERVED] - 1 task completion(s), 1 intervention request(s)
  - retry_effectiveness: 0 [ESTIMATED] - 0/1 retry(ies) followed by success within 15min window
  - tool_success_rate: 50 [ESTIMATED] - 1/2 tool calls with explicit success flag
- Maintainability: **92.8** (data coverage 100%)
  - avg_complexity: 100 [OBSERVED] - avg cyclomatic complexity 3.2
  - low_duplication: 100 [ESTIMATED] - no duplicated blocks detected
  - file_size_distribution: 100 [OBSERVED] - 0/9 files exceed 500 sloc
  - todo_debt: 52 [OBSERVED] - 1 TODO/FIXME (16.1/kLOC)
  - code_smell_count: 100 [ESTIMATED] - 0 mutable-default args, 0 bare excepts, ~0 unused imports (est.)

## Project detail - demo-cascade

- Overall: **53.37** (D) - 86% of scoring weight backed by data

**Telemetry**

| Metric | Value |
|--------|-------|
| Session start | 2026-08-22T19:41:37Z |
| Runtime (collection session) | 4.7s |
| Git commits | 4 *(OBSERVED)* |
| First commit | 2026-08-20T17:35:46Z *(OBSERVED)* |
| Last commit | 2026-08-21T04:41:46Z *(OBSERVED)* |
| Files | 5 |
| Lines of code (SLOC) | 63 *(OBSERVED)* |
| Test SLOC | 13 *(OBSERVED)* |
| Tests executed | 1 passed / 2 failed / 0 errors (OBSERVED) |
| Test coverage | n/a *(UNAVAILABLE: no machine-readable coverage report found)* |
| Build result | success (OBSERVED) |
| Peak RAM across phases | 35 MB (OBSERVED) |
| Token usage | n/a *(UNAVAILABLE)* |
| Tool calls | n/a *(UNAVAILABLE)* |
| Errors observed | 0 (OBSERVED event count) |
| Retries | none observed (distinct from unknown) |
| Failure/recovery | 2 failures, 0 recovered |
| Feature manifest | none declared |

**Score components**

- Completion: **73.3** (data coverage 100%)
  - build_succeeds: 100 [OBSERVED] - exit code of build/compile phase
  - entrypoint_runs: 100 [OBSERVED] - entrypoint: python3 -c "import processor; print('cascade loads')"
  - behavior_delivered: 33 [ESTIMATED] - public functions referenced by test files
- Reliability: **44.4** (data coverage 75%)
  - test_pass_rate: 33 [OBSERVED] - 2 test run(s)
  - stability_across_runs: 100 [OBSERVED] - 2 repeated runs
  - error_density: - [OBSERVED] - no error/build-failure events observed
  - recovery_after_failures: 0 [OBSERVED] - 0/2 failures followed by a later success event
- Testing: **40.6** (data coverage 75%)
  - suite_scale: 15 [OBSERVED] - 3 tests executed
  - pass_rate: 33 [OBSERVED]
  - line_coverage: - [OBSERVED] - no machine-readable coverage report found
  - test_to_code_balance: 100 [OBSERVED] - ratio=0.260
- Architecture: **73.2** (data coverage 100%)
  - module_size_discipline: 100 [OBSERVED] - avg file 13 sloc; 0 file(s) >500
  - coupling_control: 100 [OBSERVED] - 0 circular cycle(s); avg fan-out 0.0
  - layering_and_layout: 0 [OBSERVED] - no src/package layout; no separate tests dir; no dependency manifest / CI config
  - dependency_hygiene: 55 [OBSERVED] - no dependency manifest; treated as minimal-dependency project
  - complexity_ceiling: 100 [OBSERVED] - max cyclomatic complexity 7
- Performance: **100.0** (data coverage 100%)
  - suite_wall_time: 100 [OBSERVED] - tests finished in 0.57s
  - memory_efficiency: 100 [OBSERVED] - peak RSS 35MB (absolute; project below 10kLOC)
  - startup_latency: 100 [OBSERVED] - entrypoint responded in 0.06s
- Documentation: **0.0** (data coverage 100%)
  - readme_quality: 0 [OBSERVED] - no README file
  - docstring_coverage: 0 [OBSERVED] - 0% of public functions documented
  - changelog_versioning: 0 [OBSERVED] - no changelog
  - supporting_docs: 0 [OBSERVED] - 0 extra markdown file(s)
- Autonomy: **0.0** (data coverage 35%)
  - self_correction_ratio: 0 [ESTIMATED] - 0 fix(es) vs 10 discovered bug(s) (some labels derived heuristically)
  - unattended_completion: - [OBSERVED] - no task lifecycle events observed
  - retry_effectiveness: - [OBSERVED] - no retry signals observed
  - tool_success_rate: - [OBSERVED] - no tool-call records ingested
- Maintainability: **51.4** (data coverage 100%)
  - avg_complexity: 100 [OBSERVED] - avg cyclomatic complexity 4.6
  - low_duplication: 0 [ESTIMATED] - 100.0% duplicated SLOC (shingle estimate)
  - file_size_distribution: 100 [OBSERVED] - 0/5 files exceed 500 sloc
  - todo_debt: 5 [OBSERVED] - 2 TODO/FIXME (31.7/kLOC)
  - code_smell_count: 6 [ESTIMATED] - 5 mutable-default args, 0 bare excepts, ~0 unused imports (est.)

## Event stream highlights

| Time (UTC) | Project | Event | Detail | Provenance |
|------------|---------|-------|--------|------------|
| 2025-08-18T06:53:20Z | demo-atlas | agent_started |  | OBSERVED |
| 2025-08-18T06:58:20Z | demo-atlas | task_completed | Implemented core queue with push/pop semantics. | ESTIMATED |
| 2025-08-18T07:25:00Z | demo-atlas | test_failed | FAILED tests/test_queue.py::test_pop_attempts - assert 2 == 1 | OBSERVED |
| 2025-08-18T07:25:10Z | demo-atlas | bug_discovered | Found bug: pop() increments attempts twice, breaking retry budget. | ESTIMATED |
| 2025-08-18T07:26:40Z | demo-atlas | retry_attempted | re-running suite after edit | OBSERVED |
| 2025-08-18T07:33:20Z | demo-atlas | bug_fixed | Patched attempt accounting; extracted priority pick to queue_prio. | ESTIMATED |
| 2025-08-18T07:35:00Z | demo-atlas | bug_fixed | attempts off-by-one fixed | OBSERVED |
| 2025-08-18T07:38:20Z | demo-atlas | commit_created | fix: restore attempt accounting in pop() | OBSERVED |
| 2025-08-18T07:43:20Z | demo-atlas | task_completed | Task complete: queue, retry policy and worker delivered with green suite. | ESTIMATED |
| 2025-08-18T07:43:30Z | demo-atlas | task_completed |  | OBSERVED |
| 2025-08-18T07:45:00Z | demo-atlas | milestone_reached | v0.1.0 tagged | OBSERVED |
| 2026-08-22T19:41:23Z | demo-atlas | build_succeeded | build ok (0.3s) | OBSERVED |
| 2026-08-22T19:41:37Z | demo-cascade | build_succeeded | build ok (0.1s) | OBSERVED |
| 2026-08-22T19:41:37Z | demo-cascade | test_failed | 2 failed / 0 errors | OBSERVED |
| 2026-08-22T19:41:37Z | demo-cascade | bug_discovered | E       NotImplementedError: soon | ESTIMATED |
| 2026-08-22T19:41:37Z | demo-cascade | bug_discovered | E       assert 27 == (9 * 2) | ESTIMATED |
| 2026-08-22T19:41:37Z | demo-cascade | bug_discovered | E        +  where 9 = len('{"id": 2}') | ESTIMATED |
| 2026-08-22T19:41:37Z | demo-cascade | bug_discovered | FAILED ../../../../../../../../var/folders/z1/qnmb5zdn32s1lvgp5bk6q4m40000gn/T/fab-workspa | ESTIMATED |
| 2026-08-22T19:41:37Z | demo-cascade | bug_discovered | FAILED ../../../../../../../../var/folders/z1/qnmb5zdn32s1lvgp5bk6q4m40000gn/T/fab-workspa | ESTIMATED |
| 2026-08-22T19:41:40Z | demo-cascade | test_failed | 2 failed / 0 errors | OBSERVED |
| 2026-08-22T19:41:40Z | demo-cascade | bug_discovered | E       NotImplementedError: soon | ESTIMATED |
| 2026-08-22T19:41:40Z | demo-cascade | bug_discovered | E       assert 27 == (9 * 2) | ESTIMATED |
| 2026-08-22T19:41:40Z | demo-cascade | bug_discovered | E        +  where 9 = len('{"id": 2}') | ESTIMATED |
| 2026-08-22T19:41:40Z | demo-cascade | bug_discovered | FAILED ../../../../../../../../var/folders/z1/qnmb5zdn32s1lvgp5bk6q4m40000gn/T/fab-workspa | ESTIMATED |
| 2026-08-22T19:41:40Z | demo-cascade | bug_discovered | FAILED ../../../../../../../../var/folders/z1/qnmb5zdn32s1lvgp5bk6q4m40000gn/T/fab-workspa | ESTIMATED |
| 2025-08-18T09:40:00Z | demo-volt | agent_started |  | OBSERVED |
| 2025-08-18T09:40:50Z | demo-volt | retry_attempted | retrying after fixing imports | OBSERVED |
| 2025-08-18T09:56:40Z | demo-volt | bug_discovered | Stats implemented; median edge case still failing, deferring. | ESTIMATED |
| 2025-08-18T09:58:20Z | demo-volt | test_failed | FAILED tests/test_median_edge.py - expected None | OBSERVED |
| 2025-08-18T10:06:40Z | demo-volt | intervention_requested | clarify spec for empty-input median | OBSERVED |
| 2025-08-18T10:13:20Z | demo-volt | commit_created | wip: column filter | OBSERVED |
| 2025-08-18T10:21:40Z | demo-volt | task_completed | cli usable for basic mean reporting | OBSERVED |
| 2026-08-22T19:41:32Z | demo-volt | build_succeeded | build ok (0.1s) | OBSERVED |
| 2026-08-22T19:41:33Z | demo-volt | test_failed | 1 failed / 0 errors | OBSERVED |
| 2026-08-22T19:41:33Z | demo-volt | bug_discovered | E       assert 0.0 is None | ESTIMATED |
| 2026-08-22T19:41:33Z | demo-volt | bug_discovered | E        +  where 0.0 = median([]) | ESTIMATED |
| 2026-08-22T19:41:33Z | demo-volt | bug_discovered | FAILED ../../../../../../../../var/folders/z1/qnmb5zdn32s1lvgp5bk6q4m40000gn/T/fab-workspa | ESTIMATED |
| 2026-08-22T19:41:35Z | demo-volt | test_failed | 1 failed / 0 errors | OBSERVED |
| 2026-08-22T19:41:35Z | demo-volt | bug_discovered | E       assert 0.0 is None | ESTIMATED |
| 2026-08-22T19:41:35Z | demo-volt | bug_discovered | E        +  where 0.0 = median([]) | ESTIMATED |
| 2026-08-22T19:41:35Z | demo-volt | bug_discovered | FAILED ../../../../../../../../var/folders/z1/qnmb5zdn32s1lvgp5bk6q4m40000gn/T/fab-workspa | ESTIMATED |
| 2026-08-22T19:41:42Z | fab-self | build_succeeded | build ok (0.2s) | OBSERVED |

---

## Reproducibility notes

- Subjects were analysed read-only; dynamic phases executed inside isolated workspace copies under the system temp directory.
- Scores are deterministic functions of telemetry: same inputs, same scores. Formulas per component are embedded in each scorecard above and specified in docs/METRICS.md.
- Anything marked UNAVAILABLE can be made available by supplying the missing source (agent session logs, coverage tooling, entrypoint config) and re-running `fab run`.
