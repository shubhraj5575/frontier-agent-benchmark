"""Agent session-log ingestion adapter.

Turns heterogeneous agent run logs (JSONL transcripts, OpenHands-style event
files, generic agent logs) into the canonical FAB event stream plus token /
tool-call / retry accounting.

Honesty rules
-------------
* Fields read directly from the log (timestamps, tool names, usage counts)
  -> OBSERVED.
* Classifications produced by our keyword heuristics (e.g. deciding that an
  assistant turn "fixed a bug") -> ESTIMATED.
* Anything the log does not contain (tokens, tool calls, ...) stays
  UNAVAILABLE - never inferred into existence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..models import Event, EventType, Measurement, Provenance

SOURCE = "log_ingest"

# ---------------------------------------------------------------------------
# Classification heuristics (ESTIMATED provenance for derived labels)
# ---------------------------------------------------------------------------

_RAW_TYPE_MAP: dict[str, tuple[EventType, str]] = {
    "agent_started": (EventType.AGENT_STARTED, "info"),
    "start": (EventType.AGENT_STARTED, "info"),
    "task_completed": (EventType.TASK_COMPLETED, "success"),
    "task_complete": (EventType.TASK_COMPLETED, "success"),
    "finish": (EventType.TASK_COMPLETED, "success"),
    "test_failed": (EventType.TEST_FAILED, "error"),
    "test_failure": (EventType.TEST_FAILED, "error"),
    "test_passed": (EventType.TEST_PASSED, "success"),
    "bug_discovered": (EventType.BUG_DISCOVERED, "warn"),
    "bug_found": (EventType.BUG_DISCOVERED, "warn"),
    "bug_fixed": (EventType.BUG_FIXED, "success"),
    "commit": (EventType.COMMIT_CREATED, "info"),
    "commit_created": (EventType.COMMIT_CREATED, "info"),
    "git_commit": (EventType.COMMIT_CREATED, "info"),
    "benchmark_completed": (EventType.BENCHMARK_COMPLETED, "success"),
    "build_failed": (EventType.BUILD_FAILED, "error"),
    "build_succeeded": (EventType.BUILD_SUCCEEDED, "success"),
    "milestone": (EventType.MILESTONE_REACHED, "success"),
    "milestone_reached": (EventType.MILESTONE_REACHED, "success"),
    "error": (EventType.ERROR_OBSERVED, "error"),
    "exception": (EventType.ERROR_OBSERVED, "error"),
    "retry": (EventType.RETRY_ATTEMPTED, "warn"),
    "tool_call": (EventType.TOOL_CALL, "info"),
    "tool_use": (EventType.TOOL_CALL, "info"),
    "intervention_requested": (EventType.INTERVENTION_REQUESTED, "critical"),
    "human_intervention": (EventType.INTERVENTION_REQUESTED, "critical"),
}

_FIX_MSG_RE = re.compile(
    r"\b(fixed|fixes|fix(?:ing)?\s+(?:the\s+)?(?:bug|issue|error|failure)|"
    r"resolved|patched|repair)\b", re.I)
_BUG_MSG_RE = re.compile(
    r"\b(bug|defect|broken|failing|fails|crash|stack ?trace|traceback|"
    r"exception|error found)\b", re.I)
_DONE_MSG_RE = re.compile(
    r"\b(completed|complete|finished|done|implemented|delivered|task "
    r"(?:is )?(?:done|complete))\b", re.I)
_RETRY_MSG_RE = re.compile(r"\b(retr(y|ies|ying)|attempt \d+|try again|again)\b",
                           re.I)

# token usage fields seen across frameworks
_TOKEN_FIELD_CANDIDATES = [
    ("usage", "input_tokens"), ("usage", "prompt_tokens"),
    ("usage", "output_tokens"), ("usage", "completion_tokens"),
    ("usage", "total_tokens"), ("usage", "cache_read_input_tokens"),
    ("token_usage", "prompt_tokens"), ("token_usage", "completion_tokens"),
    ("token_usage", "total_tokens"),
    ("message", "usage"),  # nested dict handled specially below
]


@dataclass
class IngestResult:
    events: list[Event] = field(default_factory=list)
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_total_observed: int | None = None
    tokens_total_estimated: int | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    retries: int = 0
    errors: int = 0
    lines_seen: int = 0
    lines_parsed: int = 0

    def measurements(self) -> dict[str, Measurement]:
        m: dict[str, Measurement] = {}
        if self.tokens_total_observed is not None:
            m["tokens.total"] = Measurement.observed(
                self.tokens_total_observed, SOURCE, note="from agent usage records")
            m["tokens.provenance"] = Measurement.observed("OBSERVED", SOURCE)
        elif self.tokens_total_estimated is not None:
            m["tokens.total"] = Measurement.estimated(
                self.tokens_total_estimated, SOURCE,
                note="chars/4 heuristic over observed transcript volume")
            m["tokens.provenance"] = Measurement.estimated("ESTIMATED", SOURCE)
        else:
            m["tokens.total"] = Measurement.unavailable(
                SOURCE, "no usage fields and no raw text volume in logs")
            m["tokens.provenance"] = Measurement.observed("UNAVAILABLE", SOURCE,
                                                          note="honest absence")
        if self.tokens_in is not None or self.tokens_out is not None:
            m["tokens.input"] = Measurement.observed(self.tokens_in or 0, SOURCE) \
                if self.tokens_in is not None else Measurement.unavailable(SOURCE)
            m["tokens.output"] = Measurement.observed(self.tokens_out or 0, SOURCE) \
                if self.tokens_out is not None else Measurement.unavailable(SOURCE)
        m["tools.calls"] = (Measurement.observed(len(self.tool_calls), SOURCE)
                            if self.tool_calls
                            else Measurement.unavailable(SOURCE, "no tool-call records"))
        if self.tool_calls:
            named_ok = [t for t in self.tool_calls if t.get("ok") is True]
            m["tools.success_rate"] = Measurement.estimated(
                round(len(named_ok) / len(self.tool_calls), 4), SOURCE,
                note="only calls with explicit success flags counted")
        m["retries"] = (Measurement.observed(self.retries, SOURCE)
                        if self.retries else Measurement.unavailable(
                            SOURCE, "no retry signals in log"))
        return m


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_TS_KEYS = ("timestamp", "ts", "time", "created_at", "datetime")
_TYPE_KEYS = ("type", "event", "event_type", "kind", "action", "role")
_MSG_KEYS = ("message", "msg", "content", "text", "summary", "detail")


def _first(d: dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _norm_ts(v: Any) -> float | None:
    import datetime as _dt
    if v is None:
        return None
    if isinstance(v, (int, float)):
        # heuristics: seconds vs ms epoch
        ts = float(v)
        if ts > 1e12:
            ts /= 1000.0
        return ts if 1e9 < ts < 4e10 else None
    if isinstance(v, str):
        s = v.strip()
        try:
            return float(s)
        except ValueError:
            pass
        iso = s.replace("Z", "+00:00")
        try:
            dt = _dt.datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
            return dt.timestamp()
        except ValueError:
            return None
    return None


def _extract_usage(obj: dict[str, Any]) -> dict[str, int] | None:
    """Find a usage record anywhere shallowly in the object."""
    candidates = [obj]
    for key in ("usage", "token_usage", "response"):
        v = obj.get(key)
        if isinstance(v, dict):
            candidates.append(v)
    msg = obj.get("message")
    if isinstance(msg, dict):
        candidates.append(msg)
        u = msg.get("usage")
        if isinstance(u, dict):
            candidates.append(u)
    for cand in candidates:
        tin = _sum_fields(cand, ("input_tokens", "prompt_tokens"))
        tout = _sum_fields(cand, ("output_tokens", "completion_tokens"))
        tot = cand.get("total_tokens")
        if tin or tout or isinstance(tot, (int, float)):
            out = {"in": int(tin or 0), "out": int(tout or 0)}
            if isinstance(tot, (int, float)) and not (tin or tout):
                out["in"], out["out"] = int(tot), 0
            return out
    return None


def _sum_fields(d: dict[str, Any], keys: Iterable[str]) -> int | None:
    total = 0
    hit = False
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            total += int(v)
            hit = True
    return total if hit else None


_TOOL_KEYS = ("tool", "tool_name", "name", "function")


def _extract_tool(obj: dict[str, Any]) -> dict[str, Any] | None:
    name = _first(obj, _TOOL_KEYS)
    if isinstance(name, dict):
        name = name.get("name")
    if not isinstance(name, str):
        return None
    ok = obj.get("success", obj.get("ok"))
    return {"tool": name, "ok": ok if isinstance(ok, bool) else None}


def classify_line(obj: dict[str, Any]) -> tuple[EventType | None, str, bool]:
    """Return (canonical_type_or_None, severity, classification_is_heuristic).

    ``None`` type means we could not map the line; callers keep it as OTHER.
    """
    raw = _first(obj, _TYPE_KEYS)
    raw_s = str(raw).strip().lower().replace("-", "_") if raw is not None else ""
    msg = _first(obj, _MSG_KEYS)
    msg_s = ""
    if isinstance(msg, (dict, list)):
        try:
            msg_s = json.dumps(msg)[:400]
        except Exception:
            msg_s = ""
    elif msg is not None:
        msg_s = str(msg)

    # role-based fallbacks (assistant turns etc.)
    if raw_s in {"assistant", "user", "system"}:
        raw_s = ""

    if raw_s in _RAW_TYPE_MAP:
        etype, sev = _RAW_TYPE_MAP[raw_s]
        return etype, sev, False

    text = f"{raw_s} {msg_s}"
    heuristic = True
    if re.search(r"\b(traceback|unhandled exception)\b", text, re.I):
        return EventType.ERROR_OBSERVED, "error", heuristic
    if _RETRY_MSG_RE.search(raw_s):
        return EventType.RETRY_ATTEMPTED, "warn", heuristic
    if _FIX_MSG_RE.search(text) and raw_s != "":
        pass  # fall through to message scan below
    if _FIX_MSG_RE.search(msg_s):
        return EventType.BUG_FIXED, "success", heuristic
    if _BUG_MSG_RE.search(text):
        return EventType.BUG_DISCOVERED, "warn", heuristic
    if _DONE_MSG_RE.search(text):
        return EventType.TASK_COMPLETED, "success", heuristic
    return None, "info", heuristic


class JsonlAdapter:
    """Generic JSONL adapter with flexible field mapping."""

    def __init__(self, project: str, session_id: str,
                 estimate_tokens_from_chars: bool = False):
        self.project = project
        self.session_id = session_id
        self.estimate_tokens_from_chars = estimate_tokens_from_chars

    def ingest_lines(self, lines: Iterable[str]) -> IngestResult:
        res = IngestResult()
        prev_error_idx: int | None = None
        char_volume = 0
        for i, line in enumerate(lines):
            res.lines_seen += 1
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # plain-text log line: count volume, mine obvious signals
                char_volume += len(line)
                if re.search(r"\b(traceback|error)\b", line, re.I):
                    res.errors += 1
                    res.events.append(Event(
                        type=EventType.ERROR_OBSERVED, project=self.project,
                        session_id=self.session_id, severity="warn",
                        message=line[:200], raw_type="plaintext",
                        provenance=Provenance.OBSERVED, source=SOURCE))
                continue
            if not isinstance(obj, dict):
                continue
            res.lines_parsed += 1

            ts = _norm_ts(_first(obj, _TS_KEYS))
            usage = _extract_usage(obj)
            if usage:
                res.tokens_in = (res.tokens_in or 0) + usage.get("in", 0)
                res.tokens_out = (res.tokens_out or 0) + usage.get("out", 0)
                res.events.append(Event(
                    type=EventType.TOKENS_REPORTED, project=self.project,
                    session_id=self.session_id, ts=ts, message="usage record",
                    data={"in": usage.get("in", 0), "out": usage.get("out", 0)},
                    provenance=Provenance.OBSERVED, source=SOURCE))
            tool = _extract_tool(obj)
            if tool:
                res.tool_calls.append(tool)
                res.events.append(Event(
                    type=EventType.TOOL_CALL, project=self.project,
                    session_id=self.session_id, ts=ts,
                    message=f"tool: {tool['tool']}", data=dict(tool),
                    provenance=Provenance.OBSERVED, source=SOURCE))

            etype, sev, heuristic = classify_line(obj)
            msg = _first(obj, _MSG_KEYS)
            msg_text = msg if isinstance(msg, str) else json.dumps(msg)[:300] if msg else ""
            char_volume += len(line)
            if etype is not None:
                if etype == EventType.ERROR_OBSERVED:
                    res.errors += 1
                if etype == EventType.RETRY_ATTEMPTED:
                    res.retries += 1
                prov = Provenance.ESTIMATED if heuristic else Provenance.OBSERVED
                ev = Event(type=etype, project=self.project,
                           session_id=self.session_id, ts=ts, severity=sev,
                           message=msg_text[:200],
                           raw_type=str(_first(obj, _TYPE_KEYS)),
                           provenance=prov,
                           note=None if not heuristic else
                           "classified by keyword heuristic",
                           source=SOURCE)
                res.events.append(ev)
                # naive consecutive-error -> retry detection
                if etype == EventType.ERROR_OBSERVED:
                    prev_error_idx = len(res.events) - 1
                elif etype == EventType.RETRY_ATTEMPTED and prev_error_idx is not None:
                    res.events[prev_error_idx].data["retried_after"] = True
                    prev_error_idx = None
        if res.tokens_total_observed is None:
            ti = res.tokens_in or 0
            to_ = res.tokens_out or 0
            if ti or to_:
                res.tokens_total_observed = ti + to_
        if self.estimate_tokens_from_chars and char_volume:
            est = max(char_volume // 4, 0)
            res.tokens_total_estimated = est
        return res

    def ingest_file(self, path: str | Path) -> IngestResult:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return self.ingest_lines(fh)


def detect_log_format(path: str | Path) -> str:
    """Best-effort sniffing: 'jsonl' | 'text'."""
    p = Path(path)
    with open(p, encoding="utf-8", errors="replace") as fh:
        sample = [fh.readline() for _ in range(5)]
    for ln in sample:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("{"):
            try:
                json.loads(s)
                return "jsonl"
            except json.JSONDecodeError:
                return "text"
        return "text"
    return "text"


def ingest(path: str | Path, project: str, session_id: str,
           estimate_tokens_from_chars: bool = False) -> IngestResult:
    fmt = detect_log_format(path)
    adapter = JsonlAdapter(project, session_id,
                           estimate_tokens_from_chars=(
                               estimate_tokens_from_chars or fmt == "text"))
    return adapter.ingest_file(path)
