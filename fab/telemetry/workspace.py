"""Workspace isolation: copy subjects into scratch space before execution.

Guarantee: FAB never executes anything inside a subject's original directory.
Static collection is read-only; dynamic phases run against a copy.

Workspaces deliberately live OUTSIDE the FAB repository tree (system temp)
so that FAB's own packaging/config files can never leak into a subject's
toolchain (e.g. pytest picking up FAB's pyproject.toml).
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from ..models import SessionMeta, stable_id

_WS_ROOT = Path(tempfile.gettempdir()) / "fab-workspaces"

_BASE_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", ".venv", "node_modules",
    ".pytest_cache", ".mypy_cache", ".DS_Store")


def make_workspace(project: str, path: str | Path,
                   data_root: Path | None = None,
                   exclude: list[str] | None = None) -> tuple[Path, SessionMeta]:
    """Copy ``path`` into an isolated workspace and return (path, session).

    ``exclude`` names top-level directories to omit from the copy (used for
    subjects whose repo contains unrelated fixture trees).
    """
    src = Path(path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"subject path does not exist: {src}")
    sid = stable_id(project, src, time.time_ns())
    ws_root = _WS_ROOT
    ws_root.mkdir(parents=True, exist_ok=True)
    dest = ws_root / f"{project}-{sid[:10]}"
    if dest.exists():
        shutil.rmtree(dest)

    if src.is_dir():
        if exclude:
            extra = shutil.ignore_patterns(*exclude)

            def ignore(directory: str, entries: list[str]) -> set[str]:
                return _BASE_IGNORE(directory, entries) | extra(directory,
                                                                entries)
        else:
            ignore = _BASE_IGNORE
        shutil.copytree(src, dest, ignore=ignore, dirs_exist_ok=False)
    else:
        dest.mkdir(parents=True)

    meta = SessionMeta(session_id=sid, project=project, started_at=time.time(),
                       workspace=str(dest))
    return dest, meta


def cleanup_workspace(ws: Path, keep: bool = False) -> None:
    """Remove scratch copy unless retention requested."""
    if keep or not ws.exists():
        return
    if ws.parent.name == _WS_ROOT.name:
        shutil.rmtree(ws, ignore_errors=True)


def temp_workspace(prefix: str = "fab-") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))
