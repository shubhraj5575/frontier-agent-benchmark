"""Final report: narrative answers to the benchmark's nine core questions.

Every answer cites its evidence and is labelled OBSERVED, ESTIMATED or
UNAVAILABLE.  When data does not exist for a question, the report says so
instead of guessing.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..analysis.comparison import ComparisonResult
from ..collector import ProjectBundle, sort_events
from ..models import EventType, utc_iso
from ..scoring.base import Scorecard

DIM_TITLES = {
    "completion": "Completion", "reliability": "Reliability",
    "testing": "Testing", "architecture": "Architecture",
    "performance": "Performance", "documentation": "Documentation",
    "autonomy": "Autonomy", "maintainability": "Maintainability",
}

_VERDICT_QUESTIONS = [
    ("most_complete", "Which project is most complete?", "completion"),
    ("most_reliable", "Which project is most reliable?", "reliability"),
    ("strongest_architecture", "Which has the strongest architecture?",
     "architecture"),
    ("best_tests", "Which has the best tests?", "testing"),
    ("best_performance", "Which has the best performance?", "performance"),
    ("strongest_autonomy", "Which demonstrates the strongest autonomy?",
     "autonomy"),
]


def _fmt_score(v: float | None) -> str:
    return f"{v:.1f}" if v is not None else "n/a"


def _data_quality(bundles: dict[str, ProjectBundle]) -> dict[str, int]:
    counts = {"OBSERVED": 0, "ESTIMATED": 0, "UNAVAILABLE": 0}
    for b in bundles.values():
        for m in b.measurements.values():
            counts[m.provenance.value] += 1
        for e in b.events:
            counts[e.provenance.value] += 1
    return counts


def generate_final_report(
    bundles: dict[str, ProjectBundle],
    cards: dict[str, Scorecard],
    comparison: ComparisonResult,
    meta: dict[str, Any] | None = None,
) -> str:
    meta = meta or {}
    L: list[str] = []
    ap = L.append

    ap("# Frontier Agent Benchmark - Final Report")
    ap("")
    generated = meta.get("generated_iso") or \
        time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    ap(f"*Generated {generated} - FAB v{meta.get('version', '1.0')}*")
    ap("")
    ap("---")
    ap("")
    ap("## Provenance legend")
    ap("")
    ap("| Label | Meaning | Trust level |")
    ap("|-------|---------|-------------|")
    ap("| **OBSERVED** | directly measured by a collector (git log, process "
      "samples, test-runner exit codes) | reproducible evidence |")
    ap("| **ESTIMATED** | derived via a documented heuristic from observed "
      "raw material | directional; heuristic named inline |")
    ap("| **UNAVAILABLE** | not present in any source provided | reported as "
      "`n/a`; never treated as zero |")
    ap("")
    dq = _data_quality(bundles)
    total = sum(dq.values()) or 1
    ap(f"Across this run: **{dq['OBSERVED']}** observed, "
       f"**{dq['ESTIMATED']}** estimated, **{dq['UNAVAILABLE']}** unavailable "
       f"measurements/events ({dq['OBSERVED'] / total:.0%} observed).")
    ap("")
    ap("---")
    ap("")

    # ------------------------------------------------------------------ board
    ap("## Leaderboard")
    ap("")
    ranked = sorted(cards.values(), key=lambda c: (-(c.overall or -1), c.project))
    ap("| Rank | Project | Overall Engineering Score | Grade | Backed by data |")
    ap("|-----:|---------|--------------------------:|:------|---------------:|")
    for i, c in enumerate(ranked, 1):
        d = c.to_dict()
        ov = d["overall"]
        ap(f"| {i} | **{c.project}** | "
           f"{ov if ov is not None else 'n/a'} | {d['grade']} | "
           f"{d['overall_coverage']:.0%} |")
    ap("")
    ap("> The overall score is a weighted mean of available dimension scores "
       "(weights in docs/METRICS.md). Dimensions with no backing data are "
       "excluded rather than zeroed, so `Backed by data` shows how much of "
       "the weight was actually evidenced.")
    ap("")

    # -------------------------------------------------------------- dimension
    dim_names = list(DIM_TITLES)
    ap("## Dimension scores")
    ap("")
    ap("| Project | " + " | ".join(DIM_TITLES[d] for d in dim_names) + " |")
    ap("|---" * (len(dim_names) + 1) + "|")
    for c in ranked:
        row = [c.project]
        for d in dim_names:
            v = c.dimensions[d].value
            covg = c.dimensions[d].coverage
            cell = "-" if v is None else f"{v:.1f}"
            if v is None:
                cell = "n/a"
            elif covg < 1.0:
                cell += f" ({covg:.0%})"
            row.append(cell)
        ap("| " + " | ".join(row) + " |")
    ap("")
    ap("`n/a` = UNAVAILABLE. `(xx%)` after a value = share of that "
       "dimension's weight backed by collected data.")
    ap("")

    # --------------------------------------------------------------- verdicts
    ap("## Answers to the nine questions")
    ap("")
    v = comparison.verdicts

    def cite(dim: str, project: str | None) -> str:
        if not project:
            return ""
        card = cards.get(project)
        if not card:
            return ""
        d = card.dimensions.get(dim)
        comps = [c for c in (d.components if d else []) if c.available]
        top = sorted(comps, key=lambda c: -c.weight)[:2]
        detail = "; ".join(f"{c.name.replace('_', ' ')}={c.value:.0f}"
                           for c in top)
        return f" Evidence: {detail}."

    for key, question, dim in _VERDICT_QUESTIONS:
        winner = v.get(key, {}).get("project")
        if winner and cards.get(winner):
            sc = v[key].get("score")
            ap(f"- **{question}** -> `{winner}` "
               f"(score {_fmt_score(sc)}, OBSERVED from collected telemetry)."
               + cite(dim, winner))
        else:
            ap(f"- **{question}** -> **UNAVAILABLE**: no subject had enough "
               f"{dim} data to rank.")

    eff = comparison.efficiency
    cpu_ranked = sorted(
        ((p, e.get("score_per_cpu_second", {"value": None,
                                            "provenance": "UNAVAILABLE"}))
         for p, e in eff.items()),
        key=lambda x: -(x[1].get("value") or 0))
    if any(e.get("provenance") != "UNAVAILABLE" for _, e in cpu_ranked):
        p0, e0 = next((p, e) for p, e in cpu_ranked
                      if e.get("provenance") != "UNAVAILABLE")
        prov = e0["provenance"]
        ap(f"- **Which uses compute most efficiently?** -> `{p0}` "
           f"({e0['value']:.3f} score-points per CPU core-second, {prov}).")
    else:
        ap("- **Which uses compute most efficiently?** -> **UNAVAILABLE**: no "
           "CPU sampling data was captured for any subject.")

    fa = comparison.failure_analysis
    if fa and any(x["failures_total"] > 0 for x in fa.values()):
        mf = max(fa.items(), key=lambda kv: kv[1]["failures_total"])
        ap(f"- **Which encounters the most failures?** -> `{mf[0]}` "
           f"({mf[1]['failures_total']} failure events, OBSERVED).")
        rec = [(p, x) for p, x in fa.items() if x["recovery_rate"] is not None]
        if rec:
            br = max(rec, key=lambda kv: (kv[1]["recovery_rate"],
                                          -(kv[1]["persisting"])))
            mttr = br[1]["mean_time_to_recovery_s"]
            ap(f"- **Which recovers from failures most effectively?** -> "
               f"`{br[0]}` ({br[1]['recovery_rate']:.0%} recovery rate, MTTR "
               f"{mttr if mttr is not None else 'n/a'}s, OBSERVED).")
        else:
            ap("- **Which recovers from failures most effectively?** -> "
               "**UNAVAILABLE**: failures occurred but none were followed by "
               "a recovery event.")
    else:
        ap("- **Which encounters the most failures?** -> No failure events "
           "were recorded for any subject (OBSERVED absence of failures, not "
           "an estimate).")
        ap("- **Which recovers from failures most effectively?** -> "
           "**UNAVAILABLE**: there were no failures to recover from.")
    ap("")
    ap("---")
    ap("")

    # ------------------------------------------------------------ per project
    ap("## Project detail")
    ap("")
    for c in ranked:
        b = bundles.get(c.project)
        d = c.to_dict()
        ap(f"### {c.project}")
        ap("")
        ov = d["overall"]
        ap(f"- Overall: **{ov if ov is not None else 'n/a'}** ({d['grade']}) - "
           f"{d['overall_coverage']:.0%} of scoring weight backed by data")
        if b:
            g, code = b.git, b.code
            m = b.measurements

            def mm(key: str) -> str:
                mes = m.get(key)
                if not mes:
                    return "n/a *(UNAVAILABLE)*"
                if not mes.available:
                    return f"n/a *(UNAVAILABLE: {mes.note})*"
                tag = "OBSERVED" if mes.provenance.value == "OBSERVED" \
                    else "ESTIMATED"
                note = f"; {mes.note}" if mes.note else ""
                return f"{mes.value} *({tag}{note})*"

            ap("")
            ap("**Telemetry**")
            ap("")
            ap("| Metric | Value |")
            ap("|--------|-------|")
            start = b.session.started_at if b.session else None
            runtime = b.session.runtime_seconds if b.session else None
            ap(f"| Session start | {utc_iso(start) or 'n/a'} |")
            ap(f"| Runtime (collection session) | "
               f"{f'{runtime:.1f}s' if runtime is not None else 'n/a'} |")
            commits = m.get("commits_total")
            ap(f"| Git commits | {mm('commits_total')} |")
            ap(f"| First commit | {mm('commit_first_time')} |")
            ap(f"| Last commit | {mm('commit_last_time')} |")
            ap(f"| Files | {code.n_files if code else 'n/a'} |")
            ap(f"| Lines of code (SLOC) | {mm('sloc_total')} |")
            ap(f"| Test SLOC | {mm('sloc_test')} |")
            tp = next((ph.counts for ph in b.phases if ph.phase == "tests"), None)
            ap(f"| Tests executed | "
               + (f"{tp.get('passed', 0)} passed / {tp.get('failed', 0)} failed"
                  f" / {tp.get('errors', 0)} errors (OBSERVED)" if tp
                  else "none *(no runnable suite detected)*") + " |")
            covm = m.get("coverage.percent")
            ap(f"| Test coverage | {mm('coverage.percent')} |")
            build_ok = next((ph.ok for ph in b.phases if ph.phase == "build"), None)
            ap(f"| Build result | "
               + ("success (OBSERVED)" if build_ok else
                  "failure (OBSERVED)" if build_ok is False else
                  "not attempted (UNAVAILABLE)") + " |")
            peak = [ph.run.peak_rss_mb for ph in b.phases
                    if ph.run is not None and ph.run.peak_rss_mb is not None]
            ap(f"| Peak RAM across phases | "
               + (f"{max(peak):.0f} MB (OBSERVED)" if peak
                  else "n/a *(UNAVAILABLE: not sampled)*") + " |")
            tokens = m.get("tokens.total")
            ap(f"| Token usage | {mm('tokens.total')} |")
            tools = m.get("tools.calls")
            ap(f"| Tool calls | {mm('tools.calls')} |")
            errs = sum(1 for e in b.events
                       if e.type == EventType.ERROR_OBSERVED)
            retries = sum(1 for e in b.events
                          if e.type == EventType.RETRY_ATTEMPTED)
            ap(f"| Errors observed | {errs} (OBSERVED event count) |")
            ap(f"| Retries | "
               + (f"{retries} (OBSERVED)" if retries
                  else "none observed (distinct from unknown)") + " |")
            fa = comparison.failure_analysis.get(c.project, {})
            if fa:
                ap(f"| Failure/recovery | {fa['failures_total']} failures, "
                   f"{fa['recovered']} recovered"
                   + (f", MTTR {fa['mean_time_to_recovery_s']}s"
                      if fa["mean_time_to_recovery_s"] is not None else "")
                   + " |")
            feats_file = b.spec.features_file
            has_manifest = bool(feats_file and Path(b.spec.path,
                                                    feats_file).exists())
            ap(f"| Feature manifest | "
               f"{feats_file if has_manifest else 'none declared'} |")
        ap("")
        ap("**Score components**")
        ap("")
        for name, dim in c.dimensions.items():
            val = _fmt_score(dim.value)
            ap(f"- {DIM_TITLES[name]}: **{val}** "
               f"(data coverage {dim.coverage:.0%})")
            for comp in dim.components:
                pv = comp.provenance.value
                cv = "-" if comp.value is None else f"{comp.value:.0f}"
                note = f" - {comp.note}" if comp.note else ""
                ap(f"  - {comp.name}: {cv} [{pv}]{note}")
        ap("")

    # ----------------------------------------------------------- event stream
    ap("## Event stream highlights")
    ap("")
    interesting = {
        EventType.AGENT_STARTED, EventType.TASK_COMPLETED,
        EventType.TEST_FAILED, EventType.BUG_DISCOVERED, EventType.BUG_FIXED,
        EventType.COMMIT_CREATED, EventType.BENCHMARK_COMPLETED,
        EventType.BUILD_FAILED, EventType.MILESTONE_REACHED,
        EventType.INTERVENTION_REQUESTED, EventType.RETRY_ATTEMPTED,
        EventType.BUILD_SUCCEEDED,
    }
    shown = 0
    LIMIT = 120
    ap("| Time (UTC) | Project | Event | Detail | Provenance |")
    ap("|------------|---------|-------|--------|------------|")
    for p in sorted(bundles):
        evs = sort_events([e for e in bundles[p].events
                           if e.type in interesting])
        for e in evs[:LIMIT]:
            ts = utc_iso(e.ts) or "(undated)"
            msg = (e.message or "").replace("|", "/")[:90]
            ap(f"| {ts} | {e.project} | {e.type.value} | {msg} | "
               f"{e.provenance.value} |")
            shown += 1
            if shown >= 400:
                break
        if shown >= 400:
            break
    ap("")
    ap("---")
    ap("")
    ap("## Reproducibility notes")
    ap("")
    ap("- Subjects were analysed read-only; dynamic phases executed inside "
       "isolated workspace copies under `<output>/workspaces/`.")
    ap("- Scores are deterministic functions of telemetry: same inputs, same "
       "scores. Formulas per component are embedded in each scorecard above "
       "and specified in docs/METRICS.md.")
    ap("- Anything marked UNAVAILABLE can be made available by supplying the "
       "missing source (agent session logs, coverage tooling, entrypoint "
       "config) and re-running `fab pipeline`.")
    ap("")
    return "\n".join(L)
