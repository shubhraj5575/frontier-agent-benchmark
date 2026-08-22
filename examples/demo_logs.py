"""Illustrative agent-transcript fixtures for the demo benchmark.

These JSONL files are SYNTHETIC EXAMPLES of what an autonomous coding
agent's session log looks like (tool calls, usage records, retries,
bug discovery/fix narration).  They exist so the ingestion path and the
autonomy dimension can be exercised end-to-end without shipping real
proprietary agent logs.

Honesty note: FAB never pretends these are live captures.  When ingested,
fields read from the files are provenance-tagged OBSERVED *as log contents*;
classifications derived by heuristics are tagged ESTIMATED.  The demo
config passes them via `fab run --ingest` and marks them as fixtures in
the run meta.
"""

ATLAS_SESSION = [
    {"type": "agent_started", "ts": 1755500000, "task": "build atlas task-queue"},
    {"type": "tool_call", "tool_name": "bash", "success": True,
     "message": "python -m venv .venv"},
    {"type": "tool_call", "tool_name": "write_file", "success": True,
     "message": "atlas/queue.py"},
    {"role": "assistant",
     "content": "Implemented core queue with push/pop semantics.",
     "usage": {"input_tokens": 1840, "output_tokens": 640},
     "timestamp": 1755500300},
    {"role": "assistant",
     "content": "Adding priority scheduling.",
     "usage": {"input_tokens": 1210, "output_tokens": 430},
     "timestamp": 1755501200},
    {"type": "test_failed", "ts": 1755501900,
     "message": "FAILED tests/test_queue.py::test_pop_attempts - assert 2 == 1"},
    {"role": "assistant",
     "content": "Found bug: pop() increments attempts twice, breaking retry budget.",
     "usage": {"input_tokens": 980, "output_tokens": 210},
     "timestamp": 1755501910},
    {"type": "retry", "ts": 1755502000, "message": "re-running suite after edit"},
    {"role": "assistant",
     "content": "Patched attempt accounting; extracted priority pick to queue_prio.",
     "usage": {"input_tokens": 1520, "output_tokens": 520},
     "timestamp": 1755502400},
    {"type": "bug_fixed", "ts": 1755502500, "message": "attempts off-by-one fixed"},
    {"type": "test_passed", "ts": 1755502600, "message": "7 passed"},
    {"type": "commit_created", "ts": 1755502700, "sha": "abc1234",
     "message": "fix: restore attempt accounting in pop()"},
    {"role": "assistant",
     "content": "Task complete: queue, retry policy and worker delivered with green suite.",
     "usage": {"input_tokens": 2100, "output_tokens": 780},
     "timestamp": 1755503000},
    {"type": "task_completed", "ts": 1755503010},
    {"type": "milestone_reached", "ts": 1755503100, "message": "v0.1.0 tagged"},
]

VOLT_SESSION = [
    {"type": "agent_started", "ts": 1755510000, "task": "build volt csv stats cli"},
    {"type": "tool_call", "tool_name": "bash", "success": False,
     "message": "pytest -q (collection error)"},
    {"type": "retry", "ts": 1755510050, "message": "retrying after fixing imports"},
    {"type": "tool_call", "tool_name": "bash", "success": True,
     "message": "pytest -q"},
    {"role": "assistant",
     "content": "Stats implemented; median edge case still failing, deferring.",
     "usage": {"prompt_tokens": 900, "completion_tokens": 350},
     "timestamp": 1755511000},
    {"type": "test_failed", "ts": 1755511100,
     "message": "FAILED tests/test_median_edge.py - expected None"},
    {"role": "user",
     "content": "please also handle empty-file input before finishing",
     "timestamp": 1755511500},
    {"type": "intervention_requested", "ts": 1755511600,
     "message": "clarify spec for empty-input median"},
    {"type": "commit_created", "ts": 1755512000, "sha": "def5678",
     "message": "wip: column filter"},
    {"type": "task_completed", "ts": 1755512500,
     "message": "cli usable for basic mean reporting"},
]
