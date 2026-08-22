"""FAB command line interface.

Commands
--------
init        scaffold a bench config
collect     static telemetry only (read-only, safe anywhere)
run         full benchmark pipeline for configured subjects
ingest      add an agent session log to a subject's evidence
watch       wrap an arbitrary agent command; capture runtime/CPU/RAM/events
serve       serve the dashboard directory locally
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from . import __version__
from .analysis.comparison import compare
from .collector import (ProjectBundle, collect_dynamic,
                        collect_static, merge_ingest)
from .config import BenchConfig, load_config, write_default_config
from .dashboard.generator import write_dashboard
from .models import Event, EventType, Provenance, utc_iso
from .report.exporters import write_exports
from .report.manifest import write_manifest
from .report.final_report import generate_final_report
from .scoring.engine import score_project
from .store import BenchmarkStore
from .telemetry.log_ingest import ingest as ingest_log
from .telemetry.process_monitor import HAS_PSUTIL, run_monitored

DEFAULT_OUT = Path("output")


def _load_or_exit(path: str | None) -> BenchConfig:
    try:
        return load_config(path)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


def cmd_init(args) -> int:
    """Write a starter bench config file."""
    target = Path(args.config)
    if target.exists():
        print(f"refusing to overwrite existing {target}")
        return 1
    p = write_default_config(target)
    print(f"wrote {p} - edit subjects and re-run")
    return 0


def cmd_watch(args) -> int:
    """Wrap an arbitrary command with process telemetry."""
    if not getattr(args, "command", None):
        print("usage: fab watch -- <command> [args...]", file=sys.stderr)
        return 2
    started = time.time()
    sid = f"watch-{int(started)}"
    evs = [Event(type=EventType.RUN_STARTED, project=args.project,
                 session_id=sid, ts=started,
                 message=f"watch: {' '.join(args.command)}",
                 provenance=Provenance.OBSERVED, source="watch")]
    mr = run_monitored(args.command, timeout_s=args.timeout)
    finished = time.time()
    ok = mr.exit_code == 0 and not mr.timed_out
    evs.append(Event(
        type=EventType.TASK_COMPLETED if ok else EventType.ERROR_OBSERVED,
        project=args.project, session_id=sid, ts=finished,
        severity="success" if ok else "error",
        message=(f"exit={mr.exit_code} duration={mr.duration_s:.1f}s "
                 f"peakRSS={mr.peak_rss_mb or 0:.0f}MB"),
        provenance=Provenance.OBSERVED, source="watch"))
    out = {
        "session_id": sid,
        "project": args.project,
        "started_iso": utc_iso(started),
        "finished_iso": utc_iso(finished),
        "runtime_s": round(mr.duration_s, 3),
        "exit_code": mr.exit_code,
        "timed_out": mr.timed_out,
        "peak_rss_mb": mr.peak_rss_mb,
        "peak_cpu_pct": mr.peak_cpu_pct,
        "avg_cpu_pct": mr.avg_cpu_pct,
        "cpu_core_seconds_est": mr.cpu_core_seconds_est,
        "monitor_backend": "psutil" if HAS_PSUTIL else "ps-fallback",
        "stdout_tail": mr.stdout_tail[-2000:],
        "stderr_tail": mr.stderr_tail[-2000:],
        "events": [e.to_dict() for e in evs],
    }
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"watch session written to {dest}")
    return 0 if not args.fail_on_error or ok else 1


def _run_pipeline(cfg: BenchConfig, args) -> dict:
    data_root = DEFAULT_OUT
    meta = {
        "generated_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "version": __version__,
        "host": platform.node(),
        "python": sys.version.split()[0],
        "monitor_backend": "psutil" if HAS_PSUTIL else "ps-fallback",
    }
    bundles: dict[str, ProjectBundle] = {}
    cards = {}
    for spec in cfg.subjects:
        name = spec.name
        print(f"[{name}] collecting (isolated workspace copy)...")
        bundle, ws = collect_dynamic(
            spec, data_root, cfg,
            keep_workspaces=args.keep_workspaces,
            run_build=not args.static_only,
            run_tests=not args.static_only,
            run_smoke=not args.static_only,
            repeats=getattr(args, "repeats", 1))
        bundles[name] = bundle
        cards[name] = score_project(bundle, cfg.scoring_weights)
        ov = cards[name].overall
        print(f"[{name}] overall={ov if ov is not None else 'n/a'} "
              f"(coverage {cards[name].overall_coverage:.0%})")

    comparison = compare(bundles, cards)

    # optional session log ingestion
    ingested: list[dict[str, str]] = []
    for path in (args.ingest or []):
        log_path = Path(path)
        if not log_path.exists():
            print(f"warn: log not found: {log_path}", file=sys.stderr)
            continue
        target = next((n for n in bundles if n in str(log_path)), None)
        if target is None:
            target = args.ingest_project or (
                sorted(bundles)[0] if bundles else "")
        res = ingest_log(log_path, target, f"ingest-{int(time.time())}",
                         estimate_tokens_from_chars=True)
        merge_ingest(bundles[target], res)
        cards[target] = score_project(bundles[target], cfg.scoring_weights)
        comparison = compare(bundles, cards)
        ingested.append({"path": str(log_path), "project": target,
                         "records": res.lines_parsed})
        print(f"ingested {log_path} into '{target}' "
              f"({res.lines_parsed} records)")
    if ingested:
        meta["ingested_logs"] = ingested

    report_md = generate_final_report(bundles, cards, comparison, meta)
    paths = write_exports(data_root / "results", bundles, cards,
                          comparison, meta)
    (data_root / "results" / "final_report.md").write_text(report_md,
                                                           encoding="utf-8")
    write_manifest(data_root / "results" / "manifest.json",
                   bundles, cards, meta)
    dash = write_dashboard(data_root / "dashboard" / "index.html",
                           bundles, cards, comparison, meta)

    if not args.no_store:
        store = BenchmarkStore(data_root / "fab.db")
        run_id = store.begin_run(label=meta["generated_iso"],
                                 config={"subjects": [s.to_dict()
                                                      for s in cfg.subjects]})
        for name in bundles:
            store.save_project(run_id, bundles[name], cards[name])
        store.finish()
        store.close()

    print("\n--- artifacts ---")
    for k, v in {**paths, "final_report": data_root / "results" / "final_report.md",
                 "manifest": data_root / "results" / "manifest.json",
                 "dashboard": dash}.items():
        print(f"  {k}: {v}")
    return {"bundles": bundles, "cards": cards, "comparison": comparison}


def cmd_run(args) -> int:
    """Run the full benchmark pipeline over configured subjects."""
    cfg = _load_or_exit(args.config)
    if not cfg.subjects:
        print("no subjects configured - add entries to bench.yaml/json "
              "or run `fab init`", file=sys.stderr)
        return 2
    result = _run_pipeline(cfg, args)
    ranked = sorted(result["cards"].values(),
                    key=lambda c: -(c.overall or -1))
    print("\n=== leaderboard ===")
    for i, c in enumerate(ranked, 1):
        ov = c.overall
        print(f"  {i}. {c.project:<24} "
              f"{ov if ov is not None else 'n/a':>6} ({c.to_dict()['grade']}) "
              f"data coverage {c.overall_coverage:.0%}")
    return 0


def cmd_collect(args) -> int:
    """Read-only static telemetry for configured subjects."""
    cfg = _load_or_exit(args.config)
    specs = ([s for s in cfg.subjects if s.name in set(args.names)]
             if args.names else cfg.subjects)
    data_root = DEFAULT_OUT
    for spec in specs:
        b = collect_static(spec, data_root)
        m = b.measurements
        loc = m.get("sloc_total")
        commits = m.get("commits_total")
        print(f"{spec.name}: files={b.code.n_files} "
              f"sloc={loc.value if loc and loc.available else 'n/a'} "
              f"commits={commits.value if commits and commits.available else 'n/a'} "
              f"tests_found={b.code.n_test_files}")
    return 0


def cmd_ingest(args) -> int:
    """Parse one agent session log and summarise its events."""
    cfg = _load_or_exit(args.config)
    res = ingest_log(args.logfile, args.project,
                     f"manual-{int(time.time())}",
                     estimate_tokens_from_chars=True)
    counts: dict[str, int] = {}
    for e in res.events:
        counts[e.type.value] = counts.get(e.type.value, 0) + 1
    print(f"parsed {res.lines_parsed}/{res.lines_seen} records from "
          f"{args.logfile}")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    tok = res.measurements().get("tokens.total")
    if tok:
        print(f"tokens.total: {tok.value} [{tok.provenance.value}]"
              + (f" - {tok.note}" if tok.note else ""))
    print(f"(subject '{args.project}' declared in config: "
          f"{any(s.name == args.project for s in cfg.subjects)})")
    return 0


def cmd_serve(args) -> int:
    """Serve generated dashboard/results over local HTTP."""
    d = Path(args.directory)
    if not d.exists():
        print(f"directory not found: {d}", file=sys.stderr)
        return 2
    port = args.port
    url = f"http://localhost:{port}/"
    print(f"serving {d.resolve()} at {url} (Ctrl-C to stop)")
    if args.open:
        webbrowser.open(url)
    os.chdir(d)
    subprocess.run([sys.executable, "-m", "http.server", str(port)])
    return 0


def cmd_pages(args) -> int:
    """Regenerate GitHub Pages artifacts under docs/ from latest outputs."""
    dash_src = DEFAULT_OUT / "dashboard" / "index.html"
    report_src = DEFAULT_OUT / "results" / "final_report.md"
    if not dash_src.exists():
        print("no dashboard found - run `fab run` first", file=sys.stderr)
        return 2
    docs = Path("docs")
    docs.mkdir(exist_ok=True)
    shutil.copyfile(dash_src, docs / "index.html")
    if report_src.exists():
        shutil.copyfile(report_src, docs / "final_report.md")
    print(f"published {dash_src} -> {docs/'index.html'}")
    return 0


def cmd_doctor(args) -> int:
    """Report which telemetry capabilities are available on this host."""
    import importlib.util
    import shutil as _sh

    checks = [
        ("git", _sh.which("git") is not None,
         "commit history / activity timeline"),
        ("pytest (importable)", importlib.util.find_spec("pytest") is not None,
         "python test execution + JUnit counts"),
        ("coverage", importlib.util.find_spec("coverage") is not None,
         "line/branch coverage measurement"),
        ("psutil", importlib.util.find_spec("psutil") is not None,
         "precise CPU/RAM sampling of process trees"),
        ("yaml", importlib.util.find_spec("yaml") is not None,
         "bench.yaml + features.yaml parsing (JSON fallback exists)"),
        ("node (optional)", _sh.which("npx") is not None,
         "js/ts test suites (jest/vitest)"),
        ("go (optional)", _sh.which("go") is not None, "go test suites"),
        ("cargo (optional)", _sh.which("cargo") is not None,
         "rust test suites"),
    ]
    print(f"fab {__version__} environment check")
    print("-" * 56)
    missing_important = []
    for name, ok, why in checks:
        mark = "OK  " if ok else "MISS"
        print(f"  [{mark}] {name:<20} {why}")
        if not ok and "optional" not in name:
            missing_important.append(name)
    print("-" * 56)
    if missing_important:
        print("without these, corresponding metrics stay honestly "
              "UNAVAILABLE:", ", ".join(missing_important))
        print("install with: pip install -e '.[dev]'")
        return 1
    print("all core capabilities present - full OBSERVED coverage possible")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the argparse tree of fab subcommands."""
    ap = argparse.ArgumentParser(
        prog="fab",
        description="Frontier Agent Benchmark - observability & scoring for "
                    "autonomous AI engineering agents.")
    ap.add_argument("--version", action="version",
                    version=f"fab {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="write a starter bench config")
    p.add_argument("--config", default=None,
                   help="target file (default auto: bench.yaml/bench.json)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("collect", help="read-only static telemetry")
    p.add_argument("--config", default=None)
    p.add_argument("names", nargs="*")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("run", help="full benchmark pipeline")
    p.add_argument("--config", default=None)
    p.add_argument("--static-only", action="store_true",
                   help="skip execution phases (no tests/build/smoke)")
    p.add_argument("--repeats", type=int, default=1,
                   help="run the test suite N times (>=2 enables the "
                        "stability/flakiness component)")
    p.add_argument("--keep-workspaces", action="store_true")
    p.add_argument("--no-store", action="store_true",
                   help="skip SQLite persistence")
    p.add_argument("--ingest", nargs="*", default=[],
                   help="session logs (JSONL/text) to fold into results")
    p.add_argument("--ingest-project", default=None,
                   help="project name for ingested logs")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("ingest", help="inspect one agent session log")
    p.add_argument("logfile")
    p.add_argument("--project", default="unknown")
    p.add_argument("--config", default=None)
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("watch", help="wrap a command; capture resources+events")
    p.add_argument("--project", default="agent-run")
    p.add_argument("--timeout", type=float, default=3600.0)
    p.add_argument("--out", default=str(DEFAULT_OUT / "sessions" /
                                        "last-watch.json"))
    p.add_argument("--fail-on-error", action="store_true")
    p.add_argument("command", nargs=argparse.REMAINDER,
                   help="command to run, after --")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("pages", help="refresh Pages artifacts in docs/")
    p.set_defaults(func=cmd_pages)

    p = sub.add_parser("doctor", help="check which telemetry capabilities exist")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("serve", help="serve dashboard/results locally")
    p.add_argument("--directory",
                   default=str(DEFAULT_OUT / "dashboard"))
    p.add_argument("--port", type=int, default=8737)
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_serve)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(args, "command") and args.command[:1] == ["--"]:
        args.command = args.command[1:]
    return args.func(args)


def main_entry() -> int:
    """Console-script entry point."""
    try:
        return main()
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
