"""Static code analysis collector.

Everything here is computed from the files on disk - no execution, no network,
no mutation of the subject tree.

Provenance rules
----------------
* raw counts (LOC, functions, TODOs, complexity) -> OBSERVED
* derived approximations (duplication ratio via line shingling) -> ESTIMATED
"""

from __future__ import annotations

import ast
import hashlib
import json as _json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..models import Measurement

SOURCE = "code"

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "dist", "build_out", ".tox", ".idea",
    ".vscode", "coverage", ".next", ".nuxt", "target", "vendor", "htmlcov",
}

CODE_EXTS = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mjs": "javascript",
    ".cjs": "javascript", ".go": "go", ".rs": "rust", ".java": "java",
    ".rb": "ruby", ".php": "php", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".cc": "cpp", ".hpp": "cpp", ".cs": "csharp", ".swift": "swift",
    ".kt": "kotlin", ".sh": "shell", ".bash": "shell",
}

TEST_FILE_RE = re.compile(
    r"(^|[/\\])(tests?|spec)([/\\])|(^|[_\-.])(test|spec)[_\-.]*[\w./-]*$|_test\.py$|-test\.js$", re.I)

DOC_FILES = ("readme.md", "readme.rst", "readme.txt", "readme")
CHANGELOG_FILES = ("changelog.md", "changes.md", "changelog.rst", "history.md")
TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
MAX_CYCLE_LEN = 8
MAX_CYCLES_REPORTED = 10


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass
class FileInfo:
    path: str                 # absolute
    rel_display: str          # repo-relative posix
    language: str
    loc: int = 0              # non-blank lines
    sloc: int = 0             # source lines excluding pure comment lines
    comment_lines: int = 0
    blank_lines: int = 0
    max_len: int = 0
    is_test: bool = False
    bytes: int = 0


@dataclass
class FunctionInfo:
    name: str
    file: str
    lineno: int
    complexity: int = 1
    has_docstring: bool = False
    is_public: bool = True
    params: int = 0


@dataclass
class CodeTelemetry:
    root: str = ""
    files: list[FileInfo] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    total_sloc: int = 0
    test_sloc: int = 0
    n_files: int = 0
    n_test_files: int = 0
    python_functions: list[FunctionInfo] = field(default_factory=list)
    js_function_count: int = 0
    todo_count: int = 0
    max_line_length: int = 0
    long_file_count: int = 0
    duplicate_sloc_fraction: float = 0.0
    import_graph: dict[str, set[str]] = field(default_factory=dict)
    circular_imports: list[list[str]] = field(default_factory=list)
    avg_fanout: float = 0.0
    has_tests_dir: bool = False
    has_src_layout: bool = False
    has_ci_config: bool = False
    readme_path: str | None = None
    changelog_path: str | None = None
    license_present: bool = False
    dependency_manifests: list[str] = field(default_factory=list)
    pinned_deps: tuple[int, int] = (0, 0)
    # precise AST checks -> OBSERVED
    mutable_default_args: int = 0
    bare_excepts: int = 0
    # approximate check -> ESTIMATED
    unused_imports_est: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "n_files": self.n_files,
            "total_sloc": self.total_sloc,
            "test_sloc": self.test_sloc,
            "languages": dict(sorted(self.languages.items(), key=lambda kv: -kv[1])),
            "n_test_files": self.n_test_files,
            "todo_count": self.todo_count,
            "long_file_count": self.long_file_count,
            "duplicate_sloc_fraction_est": round(self.duplicate_sloc_fraction, 4),
            "avg_internal_fanout": round(self.avg_fanout, 3),
            "circular_imports": [list(c) for c in self.circular_imports],
            "n_circular_import_cycles": len(self.circular_imports),
            "has_tests_dir": self.has_tests_dir,
            "has_src_layout": self.has_src_layout,
            "has_ci_config": self.has_ci_config,
            "readme": self.readme_path,
            "changelog": self.changelog_path,
            "license_present": self.license_present,
            "dependency_manifests": self.dependency_manifests,
            "pinned_deps": {"pinned": self.pinned_deps[0], "total": self.pinned_deps[1]},
            "mutable_default_args": self.mutable_default_args,
            "bare_excepts": self.bare_excepts,
            "unused_imports_est": self.unused_imports_est,
        }

    def measurements(self) -> dict[str, Measurement]:
        m: dict[str, Measurement] = {}
        m["files_total"] = Measurement.observed(self.n_files, SOURCE)
        m["sloc_total"] = Measurement.observed(self.total_sloc, SOURCE)
        m["sloc_test"] = Measurement.observed(self.test_sloc, SOURCE)
        m["todo_count"] = Measurement.observed(self.todo_count, SOURCE)
        if self.total_sloc > self.test_sloc:
            m["test_to_code_ratio"] = Measurement.observed(
                round(self.test_sloc / (self.total_sloc - self.test_sloc), 4), SOURCE)
        else:
            m["test_to_code_ratio"] = Measurement.unavailable(SOURCE)
        pyfuncs = self.python_functions
        if pyfuncs:
            comps = [f.complexity for f in pyfuncs]
            m["max_complexity"] = Measurement.observed(max(comps), SOURCE)
            m["avg_complexity"] = Measurement.observed(
                round(sum(comps) / len(comps), 2), SOURCE)
            public = [f for f in pyfuncs if f.is_public]
            if public:
                doc = sum(1 for f in public if f.has_docstring)
                m["docstring_coverage"] = Measurement.observed(
                    round(doc / len(public), 4), SOURCE)
            else:
                m["docstring_coverage"] = Measurement.unavailable(SOURCE)
        else:
            note = "no python functions found"
            for k in ("max_complexity", "avg_complexity", "docstring_coverage"):
                m[k] = Measurement.unavailable(SOURCE, note)
        if self.n_files >= 2:
            m["duplication_ratio"] = Measurement.estimated(
                round(self.duplicate_sloc_fraction, 4), SOURCE,
                note="6-line shingle heuristic")
        return m


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def _iter_code_files(root: Path) -> Iterable[Path]:
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part.endswith(".egg-info") or part.endswith(".dSYM")
               for part in rel.parts):
            continue
        yield p


def analyze_file(path: Path, root: Path) -> FileInfo | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError, OSError):
        return None
    lang = CODE_EXTS.get(path.suffix.lower())
    if lang is None:
        return None
    lines = text.splitlines()
    fi = FileInfo(path=str(path),
                  rel_display=str(path.relative_to(root).as_posix()),
                  language=lang, bytes=len(text.encode("utf-8")))
    fi.blank_lines = sum(1 for ln in lines if not ln.strip())
    prefixes = ("#",) if lang == "python" else ("//",)
    if lang not in ("python",):
        prefixes = ("#", "//") if lang != "shell" else ("#",)
    fi.comment_lines = sum(1 for ln in lines if ln.strip().startswith(prefixes))
    fi.loc = len(lines) - fi.blank_lines
    fi.sloc = max(0, fi.loc - fi.comment_lines)
    fi.max_len = max((len(ln) for ln in lines), default=0)
    name = path.name.lower()
    parent = path.parent.name.lower()
    fi.is_test = (
        parent in {"tests", "test", "spec"}
        or name.startswith("test_") or name.endswith("_test.py")
        or ".test." in name or ".spec." in name
        or name.endswith("_test.go") or re.match(r"test.*\.rs$", name) is not None
    )
    return fi


# -- python AST --------------------------------------------------------------

_BRANCH_NODES = (ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler,
                 ast.With, ast.BoolOp, ast.IfExp, ast.Assert)


def _branch_complexity(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, _BRANCH_NODES):
            score += 1
        elif isinstance(child, ast.comprehension):
            score += 1
    return min(score, 60)


def analyze_python_module(path: Path, rel: str, tel: CodeTelemetry) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, ValueError, OSError):
        return

    raw_imports: list[tuple[int, str | None, list[str]]] = []
    import_names: list[tuple[str, int]] = []  # (bound name, lineno)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            raw_imports.append((node.level, node.module,
                                [a.name for a in node.names]))
            for a in node.names:
                if a.name != "*":
                    import_names.append((a.asname or a.name, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                raw_imports.append((0, alias.name, []))
                root_name = alias.name.split(".")[0]
                import_names.append((alias.asname or root_name, node.lineno))

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = getattr(getattr(node, "args", None), "args", []) or []
            tel.python_functions.append(FunctionInfo(
                name=node.name, file=rel, lineno=node.lineno,
                complexity=_branch_complexity(node),
                has_docstring=ast.get_docstring(node) is not None,
                is_public=not node.name.startswith("_"),
                params=len(args)))
            defaults = list(node.args.defaults or [])
            defaults += [d for d in (node.args.kw_defaults or []) if d is not None]
            for d in defaults:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)) or (
                        isinstance(d, ast.Call)
                        and isinstance(d.func, ast.Name)
                        and d.func.id in {"list", "dict", "set"}):
                    tel.mutable_default_args += 1
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            tel.bare_excepts += 1

    # unused-import estimate: bound name never appears again after its import
    try:
        all_text = path.read_text(encoding="utf-8")
    except OSError:
        all_text = ""
    used_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used_names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for bound, _ln in import_names:
        if bound not in used_names and all_text.count(bound) <= 1:
            tel.unused_imports_est += 1

    # record raw import requests; resolved into a graph after all files scanned
    tel.import_graph.setdefault(rel, set())
    pkg_parts = rel[:-len(".py")].split("/") if rel.endswith(".py") else rel.split("/")
    for level, module, names in raw_imports:
        cands: list[str] = []
        modpath = ""
        if level > 0:
            base = pkg_parts[: len(pkg_parts) - level]
            if module:
                base = base + module.split(".")
            modpath = "/".join(base)
        elif module:
            modpath = module.replace(".", "/")
        if modpath:
            cands.append(modpath + ".py")
            cands.append(modpath + "/__init__.py")
        # `from pkg import submodule` / `from . import sibling`
        for n in names:
            if n and n != "*" and modpath:
                cands.append(f"{modpath}/{n}.py")
        tel.import_graph[rel].update(cands)


# -- duplication -------------------------------------------------------------

def _duplication_fraction(files: list[FileInfo]) -> float:
    shingles: dict[str, int] = defaultdict(int)
    total_shingled = 0
    win = 6
    for fi in files:
        if fi.sloc < win * 2:
            continue
        try:
            lines = Path(fi.path).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        norm = [ln.strip() for ln in lines if ln.strip()
                and not ln.strip().startswith(("#", "//"))]
        seen_in_file: set[str] = set()
        for i in range(len(norm) - win + 1):
            block = "\n".join(norm[i:i + win])
            h = hashlib.sha1(block.encode()).hexdigest()
            shingles[h] += 1
            seen_in_file.add(h)
            total_shingled += 1
        # count repeated blocks within one file too
        total_shingled += 0
    dup_extra = sum(n - 1 for n in shingles.values() if n > 1)
    if not total_shingled:
        return 0.0
    return min(1.0, (win * dup_extra) / total_shingled)


# -- import graph post-processing ---------------------------------------------

def _resolve_graph(tel: CodeTelemetry, file_set: set[str]) -> dict[str, set[str]]:
    """Resolve requested module paths to actual repo files.

    Exact hits win; otherwise a unique path-suffix match; otherwise nothing
    (external / stdlib imports simply resolve away).
    """
    resolved: dict[str, set[str]] = {}
    for src, reqs in tel.import_graph.items():
        out: set[str] = set()
        for req in sorted(reqs):
            if req in file_set:
                out.add(req)
                continue
            hits_suffix = {f for f in file_set
                           if f.endswith("/" + req) or f.endswith(req)}
            if len(hits_suffix) == 1:
                out |= hits_suffix
        resolved[src] = out - {src}
    return resolved


def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    cycles: set[tuple[str, ...]] = set()

    def dfs(node: str, stack: tuple[str, ...]) -> None:
        if len(stack) > MAX_CYCLE_LEN or len(cycles) >= 200:
            return
        for nxt in graph.get(node, ()):  # deterministic iteration order
            if nxt == stack[0]:
                if len(stack) >= 2:
                    rot = min(tuple(stack[i:] + stack[:i])
                              for i in range(len(stack)))
                    cycles.add(rot)
            elif nxt not in stack:
                dfs(nxt, (*stack, nxt))

    for start in sorted(graph):
        dfs(start, (start,))
    out = [list(c) for c in sorted(cycles)[:MAX_CYCLES_REPORTED]]
    return out


# -- dependency manifests -------------------------------------------------------

def _pinned_deps(root: Path) -> tuple[int, int]:
    pinned = total = 0
    req = root / "requirements.txt"
    if req.exists():
        try:
            for ln in req.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln or ln.startswith(("#", "-")):
                    continue
                total += 1
                if re.search(r"(==|~=|>=|<=)\s*\d", ln):
                    pinned += 1
        except OSError:
            pass
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = _json.loads(pkg.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        for section in ("dependencies", "devDependencies"):
            for ver in (data.get(section) or {}).values():
                total += 1
                v = str(ver)
                if v and (v[0].isdigit()):
                    pinned += 1
    return pinned, total


# -- main entry -----------------------------------------------------------------

def collect_code_telemetry(path: str | Path,
                           exclude: list[str] | None = None) -> CodeTelemetry:
    root = Path(path).resolve()
    tel = CodeTelemetry(root=str(root))
    if not root.exists():
        return tel
    excl = set(exclude or [])

    entries = list(root.iterdir()) if root.is_dir() else []
    names = {e.name.lower() for e in entries}
    tel.has_tests_dir = bool(names & {"tests", "test", "spec"}) or any(
        e.is_dir() and e.name.lower() in {"tests", "test", "spec"} for e in entries)
    tel.has_src_layout = any(
        e.is_dir() and (e.name.lower() in {"src", "lib"}
                        or (e / "__init__.py").exists())
        for e in entries)
    tel.has_ci_config = any(root.joinpath(*p).exists() for p in (
        (".github", "workflows"), (".gitlab-ci.yml",),
        (".circleci", "config.yml"), ("Jenkinsfile",)))
    for df in DOC_FILES:
        cand = next((e for e in entries if e.name.lower() == df), None)
        if cand is not None:
            tel.readme_path = cand.name
            break
    for cf in CHANGELOG_FILES:
        cand = next((e for e in entries if e.name.lower() == cf), None)
        if cand is not None:
            tel.changelog_path = cand.name
            break
    tel.license_present = any(e.is_file() and e.name.upper().startswith("LICENSE")
                              for e in entries)
    tel.dependency_manifests = [m for m in (
        "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg",
        "package.json", "go.mod", "Cargo.toml", "Gemfile") if root.joinpath(m).exists()]

    for fpath in _iter_code_files(root):
        rel_parts = fpath.relative_to(root).parts
        if excl and rel_parts and rel_parts[0] in excl:
            continue
        fi = analyze_file(fpath, root)
        if fi is None:
            continue
        tel.files.append(fi)
        tel.languages[fi.language] = tel.languages.get(fi.language, 0) + fi.sloc
        tel.total_sloc += fi.sloc
        if fi.is_test:
            tel.test_sloc += fi.sloc
            tel.n_test_files += 1
        if fi.sloc > 500:
            tel.long_file_count += 1
        tel.max_line_length = max(tel.max_line_length, fi.max_len)
        try:
            text = Path(fi.path).read_text(encoding="utf-8")
        except OSError:
            continue
        tel.todo_count += len(TODO_RE.findall(text))
        if fi.language == "python" and not fi.is_test:
            analyze_python_module(fpath, fi.rel_display, tel)
        elif fi.language in {"javascript", "typescript"}:
            tel.js_function_count += sum(
                len(rx.findall(text)) for rx in _JS_FUNC_RES)

    tel.n_files = len(tel.files)
    tel.duplicate_sloc_fraction = _duplication_fraction(tel.files)

    file_set = {fi.rel_display for fi in tel.files}
    graph = _resolve_graph(tel, file_set)
    tel.circular_imports = _find_cycles(graph)
    fanouts = [len(t) for t in graph.values()]
    tel.avg_fanout = round(sum(fanouts) / len(fanouts), 3) if fanouts else 0.0
    tel.pinned_deps = _pinned_deps(root)
    return tel


_JS_FUNC_RES = [re.compile(p) for p in (
    r"\bfunction\s+\w+\s*\(",
    r"\b\w+\s*:\s*function\s*\(",
    r"\b(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?(?:function\s*)?\([^)]*\)\s*(?:=>|{)",
)]
