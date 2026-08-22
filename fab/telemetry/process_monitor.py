"""Process resource monitoring: CPU / RAM sampling of a command's process tree.

Primary implementation uses ``psutil`` when installed.  Fallback (stdlib only)
polls the OS ``ps`` table and walks parent/child links to find descendants.

Sampling is direct observation of the OS scheduler -> provenance OBSERVED.
Aggregates computed between samples (e.g. avg CPU) note the sampling interval.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import psutil  # type: ignore
    HAS_PSUTIL = True
except Exception:  # pragma: no cover
    psutil = None
    HAS_PSUTIL = False

SOURCE = "procmon"


@dataclass
class ResourceSample:
    t: float          # seconds since run start
    cpu_pct: float    # summed %%cpu across tree (100 == one full core)
    rss_mb: float     # summed resident MB across tree


@dataclass
class MonitoredRun:
    cmd: list[str]
    cwd: str | None
    exit_code: int | None = None
    duration_s: float = 0.0
    started_at: float = 0.0
    finished_at: float | None = None
    timed_out: bool = False
    stdout_tail: str = ""
    stderr_tail: str = ""
    samples: list[ResourceSample] = field(default_factory=list)

    @property
    def peak_rss_mb(self) -> float | None:
        return max((s.rss_mb for s in self.samples), default=None)

    @property
    def peak_cpu_pct(self) -> float | None:
        return max((s.cpu_pct for s in self.samples), default=None)

    @property
    def avg_cpu_pct(self) -> float | None:
        if not self.samples:
            return None
        return sum(s.cpu_pct for s in self.samples) / len(self.samples)

    @property
    def cpu_core_seconds_est(self) -> float | None:
        """Integral of cpu%% over wall time - an estimate between samples."""
        if len(self.samples) < 2 or self.duration_s <= 0:
            return None
        total = 0.0
        for a, b in zip(self.samples, self.samples[1:]):
            dt = b.t - a.t
            total += max(0.0, (a.cpu_pct + b.cpu_pct) / 2.0) * dt / 100.0
        return total

    def summary(self) -> dict[str, Any]:
        return {
            "cmd": " ".join(self.cmd),
            "exit_code": self.exit_code,
            "duration_s": round(self.duration_s, 3),
            "timed_out": self.timed_out,
            "peak_rss_mb": round(self.peak_rss_mb, 2) if self.peak_rss_mb is not None else None,
            "peak_cpu_pct": round(self.peak_cpu_pct, 1) if self.peak_cpu_pct is not None else None,
            "avg_cpu_pct": round(self.avg_cpu_pct, 1) if self.avg_cpu_pct is not None else None,
            "cpu_core_seconds_est": (
                round(v, 3) if (v := self.cpu_core_seconds_est) is not None else None),
            "n_samples": len(self.samples),
            "monitor_backend": "psutil" if HAS_PSUTIL else "ps-fallback",
        }


def _descendants_psutil(root_pid: int):
    try:
        parent = psutil.Process(root_pid)
    except psutil.Error:
        return []
    procs = [parent]
    try:
        procs.extend(parent.children(recursive=True))
    except psutil.Error:
        pass
    return procs


_PS_PATH = shutil.which("ps")


def _sample_tree_ps(root_pid: int) -> tuple[float, float] | None:
    """CPU%% + RSS(MB) of the process tree via the ps table."""
    if not _PS_PATH:
        return None
    try:
        out = subprocess.run(
            [_PS_PATH, "-axo", "pid=,ppid=,%cpu=,rss="],
            capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    rows: dict[int, tuple[int, float, float]] = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
            cpu, rss_kb = float(parts[2]), float(parts[3])
        except ValueError:
            continue
        rows[pid] = (ppid, cpu, rss_kb)
    wanted = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (ppid, _c, _r) in rows.items():
            if ppid in wanted and pid not in wanted:
                wanted.add(pid)
                changed = True
    cpu = rss = 0.0
    found = False
    for pid in wanted:
        if pid in rows:
            _, c, r = rows[pid]
            cpu += c
            rss += r
            found = True
    return (cpu, rss / 1024.0) if found else None


class TreeMonitor(threading.Thread):
    """Samples a live process tree until stopped."""

    def __init__(self, root_pid: int, interval_s: float = 0.15,
                 start_time: float | None = None):
        super().__init__(daemon=True, name=f"fab-procmon-{root_pid}")
        self.root_pid = root_pid
        self.interval_s = max(0.05, interval_s)
        self.t0 = start_time if start_time is not None else time.time()
        self.samples: list[ResourceSample] = []
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            cpu = rss = None
            if HAS_PSUTIL:
                procs = _descendants_psutil(self.root_pid)
                cpu_val = rss_val = 0.0
                alive = False
                for p in procs:
                    try:
                        with p.oneshot():
                            cpu_val += p.cpu_percent() or 0.0
                            mem = p.memory_info().rss
                            rss_val += mem
                            alive = True
                    except psutil.Error:
                        continue
                if alive:
                    cpu, rss = cpu_val, rss_val / (1024 * 1024)
            else:
                got = _sample_tree_ps(self.root_pid)
                if got is not None:
                    cpu, rss = got
            if cpu is not None and rss is not None:
                self.samples.append(ResourceSample(
                    t=round(time.time() - self.t0, 4), cpu_pct=cpu, rss_mb=rss))
            self._stop.wait(max(0.0, self.interval_s - (time.time() - started)))


def run_monitored(cmd: list[str], cwd: str | Path | None = None,
                  timeout_s: float = 600, sample_interval_s: float = 0.15,
                  env: dict[str, str] | None = None) -> MonitoredRun:
    """Run ``cmd`` with process-tree monitoring; capture outcome + resources."""
    mr = MonitoredRun(cmd=list(cmd), cwd=str(cwd) if cwd else None)
    started = time.time()
    mr.started_at = started
    proc = subprocess.Popen(
        cmd, cwd=mr.cwd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env={**os.environ, **(env or {})},
        start_new_session=True,
    )
    mon = TreeMonitor(proc.pid, sample_interval_s, start_time=started)
    mon.start()
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            proc.kill()
        except OSError:
            pass
        out, err = proc.communicate()
    finally:
        mon.stop()
        mon.join(timeout=2.0)
    mr.finished_at = time.time()
    mr.duration_s = mr.finished_at - started
    mr.exit_code = proc.returncode
    mr.timed_out = timed_out
    mr.stdout_tail = (out or "")[-8000:]
    mr.stderr_tail = (err or "")[-8000:]
    mr.samples = mon.samples
    return mr


def measurements_from_run(mr: MonitoredRun, label: str) -> dict[str, Any]:
    """Provenance-tagged measurement dict from a monitored run."""
    from ..models import Measurement, Provenance

    m: dict[str, Any] = {}
    m[f"{label}.exit_code"] = Measurement.observed(mr.exit_code, SOURCE)
    m[f"{label}.duration_s"] = Measurement.observed(round(mr.duration_s, 3), SOURCE)
    m[f"{label}.timed_out"] = Measurement.observed(mr.timed_out, SOURCE)
    if mr.peak_rss_mb is not None:
        m[f"{label}.peak_rss_mb"] = Measurement.observed(round(mr.peak_rss_mb, 2), SOURCE)
    else:
        m[f"{label}.peak_rss_mb"] = Measurement.unavailable(SOURCE, "no samples collected")
    if mr.avg_cpu_pct is not None:
        m[f"{label}.avg_cpu_pct"] = Measurement.observed(round(mr.avg_cpu_pct, 2), SOURCE)
    else:
        m[f"{label}.avg_cpu_pct"] = Measurement.unavailable(SOURCE, "no samples collected")
    core_s = mr.cpu_core_seconds_est
    if core_s is not None:
        m[f"{label}.cpu_core_seconds"] = Measurement.estimated(
            round(core_s, 3), SOURCE, note="integral between samples")
    return m
