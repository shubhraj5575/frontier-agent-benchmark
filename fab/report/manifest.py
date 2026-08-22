"""Reproducibility manifest: pins the exact conditions of a benchmark run.

Written alongside results so any run can be audited and reproduced:
tool versions, host info, per-project input checksums, and result hashes.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

from .. import __version__
from ..collector import ProjectBundle
from ..scoring.base import Scorecard


def _sha256_file(path: Path, limit_bytes: int = 2_000_000) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return "unreadable"
    return h.hexdigest()


def build_manifest(bundles: dict[str, ProjectBundle],
                   cards: dict[str, Scorecard],
                   meta: dict[str, Any]) -> dict[str, Any]:
    try:
        import psutil  # type: ignore
        psutil_ver = psutil.__version__  # type: ignore[attr-defined]
    except Exception:
        psutil_ver = None
    manifest = {
        "fab_version": __version__,
        "generated_iso": meta.get("generated_iso")
        or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "node": platform.node(),
        },
        "monitor_backend": meta.get("monitor_backend"),
        "psutil_version": psutil_ver,
        "scoring_weights": next(iter(cards.values())).weights_used
        if cards else {},
        "subjects": {},
    }
    for name in sorted(bundles):
        b = bundles[name]
        src = Path(b.spec.path)
        files: dict[str, str] = {}
        if src.is_dir():
            for p in sorted(src.rglob("*")):
                if p.is_file() and ".git" not in p.parts:
                    rel = str(p.relative_to(src))
                    files[rel] = _sha256_file(p)
        manifest["subjects"][name] = {
            "path": b.spec.path,
            "entrypoint": b.spec.entrypoint,
            "head_sha": (b.git.head_sha if b.git else None),
            "file_checksums_sha256": files,
        }
    return manifest


def write_manifest(out_path: Path, bundles, cards, meta) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_manifest(bundles, cards, meta)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path
