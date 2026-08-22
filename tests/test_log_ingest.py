"""Tests for agent log ingestion adapter."""

import json

from fab.models import EventType, Provenance
from fab.telemetry.log_ingest import (JsonlAdapter, classify_line,
                                      detect_log_format, ingest)


def test_direct_type_mapping_is_observed():
    lines = [
        json.dumps({"type": "agent_started", "ts": 1700000000}),
        json.dumps({"event": "build_failed", "timestamp": "2023-11-14T22:13:20Z"}),
        json.dumps({"kind": "commit_created", "time": 1700000005}),
    ]
    res = JsonlAdapter("p", "s").ingest_lines(lines)
    types = {e.type for e in res.events}
    assert {EventType.AGENT_STARTED, EventType.BUILD_FAILED,
            EventType.COMMIT_CREATED} <= types
    for e in res.events:
        assert e.provenance is Provenance.OBSERVED


def test_message_heuristics_are_estimated():
    obj = {"role": "assistant", "content": "I found the bug: off-by-one in parser"}
    etype, sev, heuristic = classify_line(obj)
    assert etype is EventType.BUG_DISCOVERED and heuristic


def test_fix_message_classified():
    etype, _, heuristic = classify_line({"msg": "patched the failing test"})
    assert etype is EventType.BUG_FIXED and heuristic


def test_token_usage_observed():
    lines = [
        json.dumps({"usage": {"input_tokens": 1000, "output_tokens": 200}}),
        json.dumps({"token_usage": {"prompt_tokens": 50, "completion_tokens": 25}}),
    ]
    res = JsonlAdapter("p", "s").ingest_lines(lines)
    m = res.measurements()
    assert res.tokens_total_observed == 1000 + 200 + 50 + 25
    assert m["tokens.total"].provenance.value == "OBSERVED"


def test_tokens_unavailable_when_absent():
    lines = [json.dumps({"role": "assistant", "content": "working..."})]
    res = JsonlAdapter("p", "s").ingest_lines(lines)
    m = res.measurements()
    assert not m["tokens.total"].available
    assert m["tokens.total"].provenance.value == "UNAVAILABLE"
    # estimation only happens when explicitly enabled
    res2 = JsonlAdapter("p", "s", estimate_tokens_from_chars=True).ingest_lines(lines)
    m2 = res2.measurements()
    assert m2["tokens.total"].provenance.value == "ESTIMATED"
    assert m2["tokens.total"].value > 0


def test_nested_claude_style_usage():
    line = json.dumps({
        "type": "assistant",
        "message": {"usage": {"input_tokens": 42, "output_tokens": 7}},
        "timestamp": "2026-01-01T00:00:00Z",
    })
    res = JsonlAdapter("p", "s").ingest_lines([line])
    assert res.tokens_total_observed == 49


def test_tool_call_extraction():
    lines = [
        json.dumps({"tool_name": "bash", "success": True}),
        json.dumps({"tool_name": "edit", "success": False}),
        json.dumps({"role": "user", "text": "no tools here"}),
    ]
    res = JsonlAdapter("p", "s").ingest_lines(lines)
    assert len(res.tool_calls) == 2
    m = res.measurements()
    assert m["tools.calls"].value == 2
    assert m["tools.calls"].provenance.value == "OBSERVED"


def test_plaintext_error_lines_observed():
    lines = [
        "2026-01-01 ERROR something exploded",
        "Traceback (most recent call last):",
    ]
    res = JsonlAdapter("p", "s").ingest_lines(lines)
    errs = [e for e in res.events if e.type is EventType.ERROR_OBSERVED]
    assert len(errs) >= 1
    assert all(e.provenance is Provenance.OBSERVED for e in errs)


def test_detect_format(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text('{"type":"start"}\n')
    assert detect_log_format(f) == "jsonl"
    t = tmp_path / "b.log"
    t.write_text("plain text\n")
    assert detect_log_format(t) == "text"


def test_ingest_file_roundtrip(tmp_path):
    f = tmp_path / "session.jsonl"
    rows = [
        {"type": "agent_started", "ts": 1},
        {"type": "test_failed", "ts": 2, "message": "AssertionError"},
        {"type": "bug_fixed", "ts": 3},
        {"type": "task_completed", "ts": 4},
        {"type": "benchmark_completed", "ts": 5},
    ]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    res = ingest(f, "proj", "sess")
    names = sorted({e.type.name for e in res.events})
    assert {"AGENT_STARTED", "TEST_FAILED", "BUG_FIXED", "TASK_COMPLETED",
            "BENCHMARK_COMPLETED"} <= set(names)


def test_malformed_json_does_not_crash():
    lines = ["{not json at all", '{"type":"milestone_reached"}', ""]
    res = JsonlAdapter("p", "s").ingest_lines(lines)
    assert any(e.type is EventType.MILESTONE_REACHED for e in res.events)
