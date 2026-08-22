"""Workspace isolation: copy subjects into scratch space before execution.

Guarantee: FAB never executes anything inside a subject's original directory.
Static collection is read-only; dynamic phases run against a copy under
``<data_root>/workspaces/<project>-<session>/``.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from ..models import SessionMeta, stable_id


def make_workspace(project: str, path: str | Path,
                   data_root: Path) -> tuple[Path, SessionMeta]:
    src = Path(path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"subject path does not exist: {src}")
    sid = stable_id(project, src, time.time_ns())
    ws_root = data_root / "workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)
    dest = ws_root / f"{project}-{sid[:10]}"
    if dest.exists():
        shutil.rmtree(dest)
    if src.is_dir():
        shutil.copytree(
            src, dest,
            ignore=shutil.ignore_patterns(
                ".git", "__pycache__", "*.pyc", ".venv", "node_modules",
                ".pytest_cache", ".mypy_cache", "dist", "build"),
            dirs_exist_ok=False,
        )
    else:
        dest.mkdir(parents=True)
    meta = SessionMeta(session_id=sid, project=project, started_at=time.time(),
                       workspace=str(dest))
    return dest, meta


def cleanup_workspace(ws: Path, keep: bool = False) -> None:
    """Remove scratch copy unless retention requested."""
    if keep or not ws.exists():
        return
    parent_ok = ws.parent.name == "workspaces"
    if parent_ok:
        shutil.rmtree(ws, ignore_errors=True)


def temp_workspace(prefix: str = "fab-") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))
