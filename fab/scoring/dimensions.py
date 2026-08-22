"""The eight quality dimensions.

Each scorer is a pure function of a :class:`~fab.collector.ProjectBundle`.
Formulas are deliberately simple, deterministic and documented inline; the
full rationale lives in docs/METRICS.md.

Provenance policy inside scores
-------------------------------
* values measured by collectors -> OBSERVED components
* heuristic derivations (duplication, feature-name matching) -> ESTIMATED
* inputs that were never collected -> UNAVAILABLE component (weight dropped)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..collector import ProjectBundle
from ..models import (EventType, Measurement, Provenance, band_score,
                      clamp, penalty_band, saturate)
from .base import Component, DimensionScore, aggregate

O = Provenance.OBSERVED
E = Provenance.ESTIMATED


def _phase(bundle: ProjectBundle, name: str):
    for p in bundle.phases:
        if p.phase == name:
            return p
    return None


def _m(bundle: ProjectBundle, key: str) -> Measurement | None:
    return bundle.measurements.get(key)


def _val(bundle: ProjectBundle, key: str) -> float | None:
    m = bundle.measurements.get(key)
    return m.value if (m and m.available) else None


# ---------------------------------------------------------------------------
# 1. Completion
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _feature_manifest(path: Path) -> list[dict[str, Any]] | None:
    """features.yaml / features.json - list of {name, description?}."""
    import yaml  # local optional dep
    for cand in ("features.yaml", "features.yml", "features.json"):
        f = path / cand
        if f.exists():
            try:
                if cand.endswith(".json"):
                    data = json.loads(f.read_text(encoding="utf-8"))
                else:
                    data = yaml.safe_load(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict):
                data = data.get("features", [])
            if isinstance(data, list) and data and all(
                    isinstance(x, (str, dict)) for x in data):
                feats = []
                for x in data:
                    if isinstance(x, str):
                        feats.append({"name": x})
                    elif "name" in x:
                        feats.append(x)
                return feats or None
    return None


def _is_test_function(f) -> bool:
    return f.name.startswith(("test_", "Test")) or f.name.endswith("_test")


def score_completion(bundle: ProjectBundle) -> DimensionScore:
    comps: list[Component] = []
    build = _phase(bundle, "build")
    if build is not None:
        comps.append(Component(
            "build_succeeds", 0.30, 100.0 if build.ok else 0.0, O,
            note="exit code of build/compile phase",
            formula="100 if build exit==0 else 0"))
    else:
        comps.append(Component("build_succeeds", 0.30, None, O,
                               note="no build phase executed"))

    smoke = _phase(bundle, "smoke")
    if smoke is not None and smoke.run is not None:
        comps.append(Component(
            "entrypoint_runs", 0.30,
            100.0 if smoke.ok else 0.0, O,
            note=f"entrypoint: {bundle.spec.entrypoint}",
            formula="100 if entrypoint exit==0 else 0"))
    else:
        comps.append(Component("entrypoint_runs", 0.30, None, O,
                               note="no entrypoint configured"))

    # behaviour surface: share of public functions exercised by any test text
    delivered: float | None = None
    prov = E
    note = "public functions referenced by test files"
    code = bundle.code
    manifest_dir = Path(bundle.spec.path)
    feats = _feature_manifest(manifest_dir)
    if feats:
        note = "declared features with matching passing tests"
        test_text = ""
        if code:
            for fi in code.files:
                if fi.is_test:
                    try:
                        test_text += Path(fi.path).read_text(encoding="utf-8").lower()
                    except OSError:
                        pass
        tests_ok = True
        tp = _phase(bundle, "tests")
        if tp is not None and (tp.counts.get("failed") or tp.counts.get("errors")):
            tests_ok = False
        hits = 0
        for feat in feats:
            slug = _SLUG_RE.sub("_", str(feat["name"]).lower()).strip("_")
            words = [w for w in slug.split("_") if len(w) > 2]
            if not words:
                continue
            overlap = sum(1 for w in words if w in test_text)
            if overlap / len(words) >= 0.5:
                hits += 1
        delivered = 100.0 * (hits / len(feats)) * (1.0 if tests_ok else 0.5)
    elif code and code.python_functions:
        public_names = sorted({f.name.lower() for f in code.python_functions
                               if f.is_public and not f.file.startswith("tests")
                               and not _is_test_function(f)})
        if public_names:
            test_blob = ""
            for fi in code.files:
                if fi.is_test:
                    try:
                        test_blob += Path(fi.path).read_text(encoding="utf-8").lower()
                    except OSError:
                        pass
            covered = sum(1 for n in public_names if n in test_blob)
            delivered = 100.0 * covered / len(public_names)
            # shipping a red suite undermines any delivery claim
            tp = _phase(bundle, "tests")
            if tp is not None and (tp.counts.get("failed")
                                   or tp.counts.get("errors")):
                delivered *= 0.5
    if delivered is not None:
        comps.append(Component("behavior_delivered", 0.40, delivered, prov,
                               note=note,
                               formula="matched references / declared-or-public surface"))
    else:
        comps.append(Component("behavior_delivered", 0.40, None, O,
                               note="no functions or feature manifest to assess"))

    value, cov = aggregate(comps)
    return DimensionScore("completion", "Completion", value, cov, comps)


# ---------------------------------------------------------------------------
# 2. Reliability
# ---------------------------------------------------------------------------

def _pass_rates(bundle: ProjectBundle) -> list[float]:
    rates: list[float] = []
    for p in bundle.phases:
        if p.phase != "tests":
            continue
        c = p.counts
        denom = c.get("passed", 0) + c.get("failed", 0) + c.get("errors", 0)
        if denom:
            rates.append(c.get("passed", 0) / denom)
    return rates


def score_reliability(bundle: ProjectBundle) -> DimensionScore:
    comps: list[Component] = []
    rates = _pass_rates(bundle)
    if rates:
        pr = sum(rates) / len(rates)
        comps.append(Component("test_pass_rate", 0.40, pr * 100.0, O,
                               note=f"{len(rates)} test run(s)",
                               formula="passed / (passed+failed+errors)"))
    else:
        comps.append(Component("test_pass_rate", 0.40, None, O,
                               note="no test runs recorded"))

    if len(rates) >= 2:
        spread = max(min(rates), 0.0) / max(max(rates), 1e-9)
        comps.append(Component("stability_across_runs", 0.20, spread * 100.0, O,
                               note=f"{len(rates)} repeated runs",
                               formula="min(pass_rate)/max(pass_rate)"))
    else:
        comps.append(Component("stability_across_runs", 0.20, None, O,
                               note="needs >=2 test runs"))

    errors = sum(1 for e in bundle.events
                 if e.type in {EventType.ERROR_OBSERVED, EventType.BUILD_FAILED})
    runtime = bundle.session.runtime_seconds if bundle.session else None
    if errors == 0:
        comps.append(Component("error_density", 0.25, None, O,
                               note="no error/build-failure events observed"))
    elif runtime and runtime > 0.5:
        density = errors / (runtime / 3600.0)
        comps.append(Component("error_density", 0.25,
                               100.0 * (1.0 - saturate(density, cap=60)), O,
                               note=f"{errors} errors over {runtime:.0f}s",
                               formula="exp decay of errors/hour"))
    else:
        comps.append(Component("error_density", 0.25, None, O,
                               note="runtime too short to normalise density"))

    fails = [e for e in bundle.events
             if e.type in {EventType.TEST_FAILED, EventType.BUILD_FAILED}
             and e.ts is not None]
    fixes = [e for e in bundle.events
             if e.type in {EventType.TEST_PASSED, EventType.BUILD_SUCCEEDED,
                           EventType.TASK_COMPLETED}
             and e.ts is not None]
    if fails:
        recovered = sum(1 for f in fails if any(x.ts >= f.ts for x in fixes))
        comps.append(Component("recovery_after_failures", 0.15,
                               100.0 * recovered / len(fails), O,
                               note=f"{recovered}/{len(fails)} failures followed "
                                    f"by a later success event",
                               formula="failures followed by success / failures"))
    else:
        comps.append(Component("recovery_after_failures", 0.15, None, O,
                               note="no failure events to assess recovery from"))

    value, cov = aggregate(comps)
    return DimensionScore("reliability", "Reliability", value, cov, comps)


# ---------------------------------------------------------------------------
# 3. Testing
# ---------------------------------------------------------------------------

def score_testing(bundle: ProjectBundle) -> DimensionScore:
    comps: list[Component] = []
    tp = _phase(bundle, "tests")
    n_tests: int | None = None
    if tp is not None:
        c = tp.counts
        n_tests = sum(c.get(k, 0) for k in ("passed", "failed", "errors", "skipped"))
        comps.append(Component("suite_scale", 0.25,
                               100.0 * saturate(n_tests, cap=40), O,
                               note=f"{n_tests} tests executed",
                               formula="saturating(n_tests, cap=40)"))
    elif bundle.code and bundle.code.n_test_files:
        comps.append(Component("suite_scale", 0.25,
                               20.0 * min(bundle.code.n_test_files, 5), O,
                               note="tests present but never executed",
                               formula="penalised presence-only signal"))
    else:
        comps.append(Component("suite_scale", 0.25, 0.0, O,
                               note="no tests found in repository",
                               formula="observed absence => 0"))

    rates = _pass_rates(bundle)
    if rates:
        comps.append(Component("pass_rate", 0.35,
                               100.0 * sum(rates) / len(rates), O,
                               formula="passed / attempted"))
    else:
        comps.append(Component("pass_rate", 0.35, None, O,
                               note="no test execution recorded"))

    cov_pct = _val(bundle, "coverage.percent")
    if cov_pct is not None:
        comps.append(Component("line_coverage", 0.25,
                               clamp(cov_pct * 0.85 + 15 * (cov_pct >= 90), 0, 100),
                               O, note=f"{cov_pct}% line+branch coverage",
                               formula="coverage% scaled; bonus at >=90%"))
    else:
        comps.append(Component("line_coverage", 0.25, None, O,
                               note=_m(bundle, "coverage.percent").note
                               if _m(bundle, "coverage.percent") else
                               "no coverage tooling produced a report"))

    ratio = _val(bundle, "test_to_code_ratio")
    if ratio is not None:
        comps.append(Component("test_to_code_balance", 0.15,
                               100.0 * band_score(ratio, 0.01, 0.12, 0.8, 2.5),
                               O, note=f"ratio={ratio:.3f}",
                               formula="trapezoid band [0.12..0.8 ideal]"))
    else:
        comps.append(Component("test_to_code_balance", 0.15, None, O,
                               note="no source lines to compare against"))

    value, cov = aggregate(comps)
    return DimensionScore("testing", "Testing", value, cov, comps)


# ---------------------------------------------------------------------------
# 4. Architecture
# ---------------------------------------------------------------------------

def score_architecture(bundle: ProjectBundle) -> DimensionScore:
    comps: list[Component] = []
    code = bundle.code
    if code is None or code.n_files == 0:
        comps.append(Component("modularity", 0.30, None, O,
                               note="no source files"))
        value, cov = aggregate(comps)
        return DimensionScore("architecture", "Architecture", value, cov, comps)

    big_share = 0.0
    if code.total_sloc:
        big_sloc = sum(f.sloc for f in code.files if f.sloc > 500)
        big_share = big_sloc / code.total_sloc
    avg_file = code.total_sloc / max(1, code.n_files)
    mod = 100.0 * (0.6 * (1.0 - min(big_share, 1.0)) +
                   0.4 * penalty_band(avg_file, 260, 700))
    comps.append(Component("module_size_discipline", 0.30, mod, O,
                           note=(f"avg file {avg_file:.0f} sloc; "
                                 f"{code.long_file_count} file(s) >500"),
                           formula="0.6*(1-big-file share)+0.4*band(avg size)"))

    if code.import_graph and len(code.import_graph) >= 2:
        cycles = len(code.circular_imports)
        fan = code.avg_fanout
        cyc_score = max(0.0, 100.0 - 12.0 * cycles)
        fan_factor = 0.35 + 0.65 * penalty_band(fan, 3.0, 7.0)
        comps.append(Component("coupling_control", 0.25, cyc_score * fan_factor, O,
                               note=(f"{cycles} circular cycle(s); "
                                     f"avg fan-out {fan:.1f}"),
                               formula="(100-12*cycles) * fanout-band-factor"))
    else:
        comps.append(Component("coupling_control", 0.25, None, O,
                               note="import graph too small to evaluate"))

    pts = 0
    layer_notes = []
    if code.has_src_layout:
        pts += 40
    else:
        layer_notes.append("no src/package layout")
    if code.has_tests_dir:
        pts += 30
    else:
        layer_notes.append("no separate tests dir")
    if code.dependency_manifests or code.has_ci_config:
        pts += 30
    else:
        layer_notes.append("no dependency manifest / CI config")
    comps.append(Component("layering_and_layout", 0.20, float(pts), O,
                           note="; ".join(layer_notes) or "src/tests/config separated",
                           formula="checklist 40+30+30"))

    pinned, total = code.pinned_deps
    if total:
        comps.append(Component("dependency_hygiene", 0.15,
                               100.0 * pinned / total, O,
                               note=f"{pinned}/{total} deps pinned"))
    elif code.dependency_manifests:
        comps.append(Component("dependency_hygiene", 0.15, 70.0, O,
                               note="manifest(s) present but no unpinned deps detected"))
    else:
        comps.append(Component("dependency_hygiene", 0.15, 55.0, O,
                               note="no dependency manifest; treated as "
                                    "minimal-dependency project"))

    max_cc = _val(bundle, "max_complexity")
    if max_cc is not None:
        comps.append(Component("complexity_ceiling", 0.10,
                               100.0 * penalty_band(max_cc, 14, 26), O,
                               note=f"max cyclomatic complexity {max_cc}",
                               formula="penalty above 14, floor at 26"))
    else:
        comps.append(Component("complexity_ceiling", 0.10, None, O,
                               note="not a python codebase (or no functions)"))

    value, cov = aggregate(comps)
    return DimensionScore("architecture", "Architecture", value, cov, comps)


# ---------------------------------------------------------------------------
# 5. Performance
# ---------------------------------------------------------------------------

_SUITE_BANDS_S = [(2, 100), (10, 85), (30, 70), (120, 50), (600, 30)]


def _speed_score(seconds: float) -> float:
    for limit, sc in _SUITE_BANDS_S:
        if seconds <= limit:
            return float(sc)
    return 15.0


def score_performance(bundle: ProjectBundle) -> DimensionScore:
    comps: list[Component] = []
    tp = _phase(bundle, "tests")
    if tp is not None and tp.run is not None:
        secs = tp.run.duration_s
        comps.append(Component("suite_wall_time", 0.40,
                               _speed_score(secs), O,
                               note=f"tests finished in {secs:.2f}s",
                               formula="threshold bands 2/10/30/120/600s"))

        rss = tp.run.peak_rss_mb
        kloc = (bundle.code.total_sloc / 1000.0
                if bundle.code and bundle.code.total_sloc else None)
        # per-kLOC normalisation only makes sense once the interpreter
        # baseline is amortised; tiny projects are judged on absolute RSS.
        if rss is not None and kloc and kloc >= 10:
            rss_per_kloc = rss / kloc
            comps.append(Component("memory_efficiency", 0.30,
                                   100.0 * penalty_band(rss_per_kloc, 60, 400), O,
                                   note=f"peak {rss:.0f}MB / {kloc:.1f}kLOC "
                                        f"= {rss_per_kloc:.0f}MB/kLOC",
                                   formula="band on MB per kLOC"))
        elif rss is not None:
            comps.append(Component("memory_efficiency", 0.30,
                                   100.0 * penalty_band(rss, 400, 2000), O,
                                   note=f"peak RSS {rss:.0f}MB (absolute; "
                                        f"project below 10kLOC)",
                                   formula="absolute MB band"))
        else:
            comps.append(Component("memory_efficiency", 0.30, None, O,
                                   note="process sampler collected no memory data"))
    else:
        comps.append(Component("suite_wall_time", 0.40, None, O,
                               note="tests never executed under monitor"))
        comps.append(Component("memory_efficiency", 0.30, None, O,
                               note="tests never executed under monitor"))

    smoke = _phase(bundle, "smoke")
    if smoke is not None and smoke.run is not None:
        secs = smoke.run.duration_s
        comps.append(Component("startup_latency", 0.30,
                               100.0 * penalty_band(secs, 3.0, 12.0), O,
                               note=f"entrypoint responded in {secs:.2f}s",
                               formula="band on startup wall time"))
    else:
        comps.append(Component("startup_latency", 0.30, None, O,
                               note="no entrypoint smoke-run configured"))

    value, cov = aggregate(comps)
    return DimensionScore("performance", "Performance", value, cov, comps)


# ---------------------------------------------------------------------------
# 6. Documentation
# ---------------------------------------------------------------------------

_README_SECTIONS = {
    "install": re.compile(r"\b(installation|installing|getting started|setup)\b", re.I),
    "usage": re.compile(r"\b(usage|quick ?start|how to use|examples?)\b", re.I),
    "architecture": re.compile(r"\b(architecture|design|structure|how it works)\b", re.I),
    "api": re.compile(r"\b(api|cli reference|commands)\b", re.I),
    "license": re.compile(r"\blicen[sc]e\b", re.I),
    "contributing": re.compile(r"\bcontribut", re.I),
}


def score_documentation(bundle: ProjectBundle) -> DimensionScore:
    comps: list[Component] = []
    readme_txt = ""
    readme_present = False
    root = Path(bundle.spec.path)
    if bundle.code and bundle.code.readme_path:
        rp = root / bundle.code.readme_path
        try:
            readme_txt = rp.read_text(encoding="utf-8")
            readme_present = True
        except OSError:
            pass
    if readme_present:
        words = len(readme_txt.split())
        sections = sum(1 for rx in _README_SECTIONS.values()
                       if rx.search(readme_txt))
        base = 35.0 + 11.0 * min(sections, 5)
        length_factor = band_score(words, 15, 40, 2500, 9000)
        comps.append(Component("readme_quality", 0.35, base * max(0.15, length_factor),
                               O,
                               note=f"{words} words, {sections}/6 core sections",
                               formula="(35 + 11*sections) * word-band factor"))
    else:
        comps.append(Component("readme_quality", 0.35, 0.0, O,
                               note="no README file"))

    doc_cov = _val(bundle, "docstring_coverage")
    if doc_cov is not None:
        comps.append(Component("docstring_coverage", 0.30,
                               100.0 * doc_cov, O,
                               note=f"{doc_cov:.0%} of public functions documented"))
    else:
        comps.append(Component("docstring_coverage", 0.30, None, O,
                               note="non-python project (heuristic unavailable)"))

    changelog = bool(bundle.code and bundle.code.changelog_path)
    version_declared = False
    for mf in ("pyproject.toml", "package.json"):
        f = root / mf
        if f.exists():
            version_declared = True
            break
    docscore = (50.0 if changelog else 0.0) + (50.0 if version_declared else 0.0)
    comps.append(Component("changelog_versioning", 0.15, docscore, O,
                           note=("changelog" if changelog else "no changelog") +
                                (" + version declared" if version_declared else "")))

    extra = 0.0
    md_files = [f.name for f in root.glob("*.md")
                if f.name.lower() not in {"readme.md"}]
    docs_dir = (root / "docs").is_dir()
    extra += 40.0 if md_files else 0.0
    extra += 40.0 if docs_dir else 0.0
    extra += 20.0 if bundle.code and bundle.code.has_ci_config else 0.0
    comps.append(Component("supporting_docs", 0.20, min(extra, 100.0), O,
                           note=(f"{len(md_files)} extra markdown file(s)"
                                 f"{', docs/' if docs_dir else ''}"
                                 f"{', CI' if bundle.code and bundle.code.has_ci_config else ''}")))

    value, cov = aggregate(comps)
    return DimensionScore("documentation", "Documentation", value, cov, comps)


# ---------------------------------------------------------------------------
# 7. Autonomy
# ---------------------------------------------------------------------------

_SUCCESS_TYPES = {EventType.TASK_COMPLETED, EventType.TEST_PASSED,
                  EventType.BUILD_SUCCEEDED, EventType.BUG_FIXED}


def score_autonomy(bundle: ProjectBundle) -> DimensionScore:
    comps: list[Component] = []
    evs = bundle.events

    discovered = [e for e in evs if e.type == EventType.BUG_DISCOVERED]
    fixed = [e for e in evs if e.type == EventType.BUG_FIXED]
    if discovered or fixed:
        ratio = (len(fixed) / len(discovered)) if discovered else \
            (1.0 if fixed else 0.0)
        prov = O if all(e.provenance is Provenance.OBSERVED
                        for e in discovered + fixed) else E
        note = f"{len(fixed)} fix(es) vs {len(discovered)} discovered bug(s)"
        if any(e.provenance is Provenance.ESTIMATED for e in discovered + fixed):
            note += " (some labels derived heuristically)"
        comps.append(Component("self_correction_ratio", 0.35,
                               100.0 * min(1.0, ratio), prov, note=note,
                               formula="bug_fixed / bug_discovered, capped at 1"))
    else:
        comps.append(Component("self_correction_ratio", 0.35, None, O,
                               note="no bug lifecycle events observed"))

    tasks = [e for e in evs if e.type == EventType.TASK_COMPLETED]
    interventions = [e for e in evs if e.type == EventType.INTERVENTION_REQUESTED]
    if tasks or interventions:
        score = 100.0
        if interventions:
            score = 100.0 * len(tasks) / max(1, len(tasks) + len(interventions))
        comps.append(Component("unattended_completion", 0.30, score, O,
                               note=(f"{len(tasks)} task completion(s), "
                                     f"{len(interventions)} intervention request(s)")))
    else:
        comps.append(Component("unattended_completion", 0.30, None, O,
                               note="no task lifecycle events observed"))

    retries = [e for e in evs if e.type == EventType.RETRY_ATTEMPTED
               and e.ts is not None]
    if retries:
        effective = 0
        for r in retries:
            window_end = r.ts + 900
            if any(e.ts is not None and r.ts <= e.ts <= window_end
                   for e in evs if e.type in _SUCCESS_TYPES):
                effective += 1
        comps.append(Component("retry_effectiveness", 0.20,
                               100.0 * effective / len(retries), E,
                               note=f"{effective}/{len(retries)} retry(ies) followed "
                                    f"by success within 15min window",
                               formula="retries followed by success / retries"))
    else:
        comps.append(Component("retry_effectiveness", 0.20, None, O,
                               note="no retry signals observed"))

    tools_rate = None
    ing = bundle.ingest
    if ing is not None and ing.tool_calls:
        named_ok = [t for t in ing.tool_calls if t.get("ok") is True]
        tools_rate = 100.0 * len(named_ok) / len(ing.tool_calls)
        comps.append(Component("tool_success_rate", 0.15, tools_rate, E,
                               note=f"{len(named_ok)}/{len(ing.tool_calls)} tool calls "
                                    f"with explicit success flag"))
    else:
        comps.append(Component("tool_success_rate", 0.15, None, O,
                               note="no tool-call records ingested"))

    value, cov = aggregate(comps)
    notes = []
    if value is None:
        notes.append("Autonomy requires behavioural evidence from an event "
                     "stream; none was available for this subject.")
    return DimensionScore("autonomy", "Autonomy", value, cov, comps, notes)


# ---------------------------------------------------------------------------
# 8. Maintainability
# ---------------------------------------------------------------------------

def score_maintainability(bundle: ProjectBundle) -> DimensionScore:
    comps: list[Component] = []
    code = bundle.code
    if code is None or code.n_files == 0:
        comps.append(Component("no_code", 1.0, None, O,
                               note="no source files to assess"))
        value, cov = aggregate(comps)
        return DimensionScore("maintainability", "Maintainability", value, cov, comps)

    avg_cc = _val(bundle, "avg_complexity")
    if avg_cc is not None:
        comps.append(Component("avg_complexity", 0.30,
                               100.0 * penalty_band(avg_cc, 5.0, 9.0), O,
                               note=f"avg cyclomatic complexity {avg_cc}",
                               formula="band [ideal 2..5]"))
    else:
        comps.append(Component("avg_complexity", 0.30, None, O,
                               note="python complexity unavailable"))

    dup = code.duplicate_sloc_fraction
    comps.append(Component("low_duplication", 0.25,
                           100.0 * (1.0 - dup), E,
                           note=(f"{dup:.1%} duplicated SLOC (shingle estimate)"
                                 if dup > 0 else "no duplicated blocks detected"),
                           formula="1 - duplication fraction"))

    if code.n_files:
        share_long = code.long_file_count / code.n_files
        comps.append(Component("file_size_distribution", 0.20,
                               100.0 * (1.0 - min(share_long * 4, 1.0)), O,
                               note=f"{code.long_file_count}/{code.n_files} "
                                    f"files exceed 500 sloc"))
    todo_density = None
    if code.total_sloc:
        todo_density = 1000.0 * code.todo_count / code.total_sloc
    if todo_density is not None:
        comps.append(Component("todo_debt", 0.15,
                               100.0 * penalty_band(todo_density, 8.0, 25.0), O,
                               note=f"{code.todo_count} TODO/FIXME "
                                    f"({todo_density:.1f}/kLOC)"))

    suspects = (code.mutable_default_args * 10 + code.bare_excepts * 6 +
                code.unused_imports_est * 2)
    comps.append(Component("code_smell_count", 0.10,
                           100.0 * (1.0 - saturate(suspects, cap=40)), E,
                           note=(f"{code.mutable_default_args} mutable-default args, "
                                 f"{code.bare_excepts} bare excepts, "
                                 f"~{code.unused_imports_est} unused imports (est.)"),
                           formula="decay of weighted smell count"))

    value, cov = aggregate(comps)
    return DimensionScore("maintainability", "Maintainability", value, cov, comps)


DIMENSION_SCORERS = {
    "completion": score_completion,
    "reliability": score_reliability,
    "testing": score_testing,
    "architecture": score_architecture,
    "performance": score_performance,
    "documentation": score_documentation,
    "autonomy": score_autonomy,
    "maintainability": score_maintainability,
}

DIMENSION_TITLES = {
    "completion": "Completion", "reliability": "Reliability",
    "testing": "Testing", "architecture": "Architecture",
    "performance": "Performance", "documentation": "Documentation",
    "autonomy": "Autonomy", "maintainability": "Maintainability",
}
