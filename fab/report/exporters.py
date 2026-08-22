"""Exporters: JSON, CSV, Markdown.

CSV rows flatten to (project, metric, value, provenance, source, note) so the
provenance discipline survives into spreadsheets.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from ..analysis.comparison import ComparisonResult
from ..collector import ProjectBundle
from ..scoring.base import Scorecard


def export_json(bundles: dict[str, ProjectBundle],
                cards: dict[str, Scorecard],
                comparison: ComparisonResult,
                meta: dict[str, Any]) -> str:
    payload = {
        "meta": meta,
        "leaderboard": [
            {"project": p,
             "overall": cards[p].to_dict()["overall"],
             "grade": cards[p].to_dict()["grade"],
             "coverage": cards[p].to_dict()["overall_coverage"]}
            for p in sorted(cards,
                            key=lambda x: (-(cards[x].overall or 0), x))
        ],
        "projects": {p: {
            "scorecard": cards[p].to_dict(),
            "telemetry": bundles[p].to_dict(),
        } for p in sorted(bundles)},
        "comparison": comparison.to_dict(),
    }
    return json.dumps(payload, indent=2)


def export_csv(bundles: dict[str, ProjectBundle],
               cards: dict[str, Scorecard],
               comparison: ComparisonResult) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["project", "section", "metric", "value",
                "provenance", "source", "note"])
    for p in sorted(cards):
        card = cards[p]
        for name, dim in card.dimensions.items():
            if dim.value is not None:
                w.writerow([p, "dimension", f"score.{name}",
                            round(dim.value, 2), "OBSERVED", "scoring-engine",
                            f"coverage={dim.coverage:.0%}"])
            else:
                w.writerow([p, "dimension", f"score.{name}", "",
                            "UNAVAILABLE", "scoring-engine",
                            "no data backed this dimension"])
        w.writerow([p, "overall", "engineering_score",
                    "" if card.overall is None else round(card.overall, 2),
                    "OBSERVED" if card.overall is not None else "UNAVAILABLE",
                    "scoring-engine",
                    f"data coverage={card.overall_coverage:.0%}"])
        bundle = bundles.get(p)
        if bundle:
            for key, m in sorted(bundle.measurements.items()):
                w.writerow([p, "metric", key,
                            "" if m.value is None else m.value,
                            m.provenance.value, m.source, m.note or ""])
            for e in bundle.events:
                w.writerow([p, "event", e.type.value,
                            "" if e.ts is None else round(e.ts, 3),
                            e.provenance.value, e.source,
                            (e.message or "")[:120]])
        fa = comparison.failure_analysis.get(p, {})
        for k, v in fa.items():
            w.writerow([p, "failure_analysis", k,
                        "" if v is None else v,
                        "OBSERVED", "comparison", ""])
    return buf.getvalue()


def export_markdown(bundles: dict[str, ProjectBundle],
                    cards: dict[str, Scorecard],
                    comparison: ComparisonResult) -> str:
    lines: list[str] = []
    ap = lines.append
    ap("# Frontier Agent Benchmark - Results")
    ap("")
    ap("| Rank | Project | Overall | Grade | Data coverage |")
    ap("|-----:|---------|--------:|:------|--------------:|")
    ranked = sorted(cards.values(),
                    key=lambda c: (-(c.overall or 0), c.project))
    for i, c in enumerate(ranked, 1):
        d = c.to_dict()
        overall = d["overall"]
        ap(f"| {i} | {c.project} | "
           f"{overall if overall is not None else 'n/a'} | {d['grade']} | "
           f"{d['overall_coverage']:.0%} |")
    ap("")

    dim_names = list(next(iter(cards.values())).dimensions) if cards else []
    header = "| Project | " + " | ".join(d.replace("_", " ").title()
                                         for d in dim_names) + " |"
    sep = "|---" * (len(dim_names) + 1) + "|"
    ap(header)
    ap(sep)
    for c in ranked:
        row = [c.project]
        for d in dim_names:
            v = c.dimensions[d].value
            row.append("-" if v is None else f"{v:.1f}")
        ap("| " + " | ".join(str(x) for x in row) + " |")
    ap("")
    ap("*`-` = UNAVAILABLE (no data; never treated as zero).*")
    ap("")

    # per-project provenance summaries
    for c in ranked:
        b = bundles.get(c.project)
        d = c.to_dict()
        ap(f"## {c.project}")
        ap("")
        ov = d["overall"]
        ap(f"- Overall engineering score: **{ov if ov is not None else 'n/a'}** "
           f"({d['grade']}), data coverage {d['overall_coverage']:.0%}")
        if b:
            g = b.git
            m = b.measurements
            commits = m.get("commits_total")
            loc = m.get("sloc_total")
            tests_run = next((ph.counts for ph in b.phases
                              if ph.phase == "tests"), None)
            ap(f"- Git: {'repo' if g and g.is_git_repo else 'not a git repo'}"
               + (f", {commits.value} commits ({commits.provenance.value})"
                  if commits and commits.available else ""))
            ap(f"- Code: {loc.value if loc and loc.available else 'n/a'} SLOC "
               f"across {b.code.n_files if b.code else 0} files")
            ap("- Tests executed: "
               + (f"{tests_run.get('passed', 0)} passed / "
                  f"{tests_run.get('failed', 0)} failed"
                  if tests_run else "none executed"))
            tokens = m.get("tokens.total")
            if tokens:
                ap(f"- Tokens: {tokens.value if tokens.available else 'n/a'} "
                   f"({tokens.provenance.value})")
        fa = comparison.failure_analysis.get(c.project, {})
        if fa:
            ap(f"- Failures observed: {fa['failures_total']} "
               f"(recovered {fa['recovered']}, MTTR "
               f"{fa['mean_time_to_recovery_s'] if fa['mean_time_to_recovery_s'] is not None else 'n/a'}s)")
        ap("")

    ap("## Verdicts")
    ap("")
    for q, a in comparison.verdicts.items():
        proj = a.get("project") if isinstance(a, dict) else a
        score = a.get("score") if isinstance(a, dict) else None
        ap(f"- **{q.replace('_', ' ').title()}**: "
           f"{proj if proj else 'unavailable'}"
           + (f" ({score:.1f})" if score is not None and proj else ""))
    ap("")
    return "\n".join(lines)


def write_exports(out_dir: Path, bundles, cards, comparison, meta) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    j = out_dir / "results.json"
    j.write_text(export_json(bundles, cards, comparison, meta), encoding="utf-8")
    paths["json"] = j
    c = out_dir / "results.csv"
    c.write_text(export_csv(bundles, cards, comparison), encoding="utf-8")
    paths["csv"] = c
    m = out_dir / "results.md"
    m.write_text(export_markdown(bundles, cards, comparison), encoding="utf-8")
    paths["markdown"] = m
    return paths
