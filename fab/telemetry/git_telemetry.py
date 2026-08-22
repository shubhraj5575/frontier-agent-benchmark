"""Read-only git telemetry collector.

Safety: every command here is a read-only porcelain query (`log`, `status`,
`branch`, `rev-parse`).  The collector NEVER mutates the subject repository -
no checkout, no config writes, no index refresh.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import Event, EventType, Measurement, Provenance, utc_iso

SOURCE = "git"

_FIX_RE = re.compile(
    r"\b(fix(?:ed|es)?|bugfix|hotfix|patch|repair|resolve[ds]?|correct(ed)?)\b", re.I)
_BUG_RE = re.compile(r"\b(bug|defect|issue|broken|fails?|failing|error|regression)\b", re.I)
_FEAT_RE = re.compile(r"\b(feature|implement|add[s]?\s+\w+ support|introduce)\b", re.I)
_MILESTONE_RE = re.compile(r"\b(milestone|v\d+\.\d+|version\s+\d+|release)\b", re.I)


@dataclass
class CommitRecord:
    sha: str
    ts: float | None
    author: str
    subject: str
    files_changed: int
    insertions: int
    deletions: int
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sha": self.sha,
            "ts": self.ts,
            "iso": utc_iso(self.ts),
            "author": self.author,
            "subject": self.subject,
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "files": self.files,
        }


@dataclass
class GitTelemetry:
    is_git_repo: bool = False
    head_sha: str | None = None
    branch: str | None = None
    dirty_files: int = 0
    commits: list[CommitRecord] = field(default_factory=list)

    @property
    def total_commits(self) -> int:
        return len(self.commits)

    @property
    def first_commit_ts(self) -> float | None:
        return self.commits[-1].ts if self.commits else None

    @property
    def last_commit_ts(self) -> float | None:
        return self.commits[0].ts if self.commits else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_git_repo": self.is_git_repo,
            "head_sha": self.head_sha,
            "branch": self.branch,
            "dirty_files": self.dirty_files,
            "total_commits": self.total_commits,
            "first_commit_iso": utc_iso(self.first_commit_ts),
            "last_commit_iso": utc_iso(self.last_commit_ts),
            "commits": [c.to_dict() for c in self.commits],
        }

    # -- derived measurements -------------------------------------------------

    def measurements(self) -> dict[str, Measurement]:
        out: dict[str, Measurement] = {}
        if not self.is_git_repo:
            note = "directory is not a git repository"
            for key in ("commits_total", "commit_first_time", "commit_last_time",
                        "head_sha", "branch"):
                out[key] = Measurement.unavailable(SOURCE, note)
            return out
        out["commits_total"] = Measurement.observed(self.total_commits, SOURCE)
        out["head_sha"] = Measurement.observed(self.head_sha, SOURCE)
        out["branch"] = Measurement.observed(self.branch, SOURCE)
        out["dirty_files"] = Measurement.observed(self.dirty_files, SOURCE)
        out["commit_first_time"] = (
            Measurement.observed(utc_iso(self.first_commit_ts), SOURCE)
            if self.first_commit_ts is not None
            else Measurement.unavailable(SOURCE))
        out["commit_last_time"] = (
            Measurement.observed(utc_iso(self.last_commit_ts), SOURCE)
            if self.last_commit_ts is not None
            else Measurement.unavailable(SOURCE))
        return out

    def events(self, project: str, session_id: str) -> list[Event]:
        """Derive canonical events from the real history.

        ``commit_created`` events are OBSERVED directly.  ``bug_fixed`` /
        ``milestone_reached`` classifications come from a keyword heuristic on
        the commit message, so they are tagged ESTIMATED.
        """
        evs: list[Event] = []
        for c in reversed(self.commits):  # oldest first
            base = dict(project=project, session_id=session_id, source=SOURCE)
            evs.append(Event(type=EventType.COMMIT_CREATED, ts=c.ts,
                             message=c.subject,
                             data={"sha": c.sha, "insertions": c.insertions,
                                   "deletions": c.deletions,
                                   "files_changed": c.files_changed},
                             provenance=Provenance.OBSERVED, **base))
            text = f"{c.subject}"
            if _MILESTONE_RE.search(text):
                evs.append(Event(type=EventType.MILESTONE_REACHED, ts=c.ts,
                                 severity="success", message=f"milestone-ish commit: {c.subject}",
                                 data={"sha": c.sha},
                                 provenance=Provenance.ESTIMATED, **base))
            elif _FIX_RE.search(text):
                evs.append(Event(type=EventType.BUG_FIXED, ts=c.ts,
                                 severity="success", message=f"fix commit: {c.subject}",
                                 data={"sha": c.sha},
                                 provenance=Provenance.ESTIMATED, **base))
        return evs


def _run(args: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, timeout=timeout, check=False,
    )


def collect_git_telemetry(path: str | Path) -> GitTelemetry:
    """Collect read-only git telemetry.  Non-repo -> empty telemetry."""
    path = Path(path).resolve()
    tel = GitTelemetry()
    probe = _run(["rev-parse", "--is-inside-work-tree"], path)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return tel

    tel.is_git_repo = True
    head = _run(["rev-parse", "HEAD"], path)
    tel.head_sha = head.stdout.strip() if head.returncode == 0 else None
    br = _run(["rev-parse", "--abbrev-ref", "HEAD"], path)
    tel.branch = br.stdout.strip() if br.returncode == 0 else None
    st = _run(["status", "--porcelain"], path)
    if st.returncode == 0:
        tel.dirty_files = len([ln for ln in st.stdout.splitlines() if ln.strip()])

    log = _run([
        "log", "--date=unix",
        "--pretty=format:%x01%H%x02%at%x03%an%x04%s",
        "--numstat",
    ], path)
    if log.returncode != 0:
        return tel

    cur: CommitRecord | None = None
    for line in log.stdout.splitlines():
        if line.startswith("\x01"):
            # format: \x01<sha>\x02<epoch>\x03<author>\x04<subject>
            body = line[1:]
            try:
                sha_part, rest = body.split("\x02", 1)
                ts_part, remainder = rest.split("\x03", 1)
                author, subject = remainder.split("\x04", 1)
                ts = float(ts_part) if ts_part.strip() else None
            except ValueError:
                continue
            cur = CommitRecord(sha=sha_part, ts=ts, author=author,
                               subject=subject, files_changed=0,
                               insertions=0, deletions=0)
            tel.commits.append(cur)
        elif line.strip() and cur is not None:
            cols = line.split("\t")
            if len(cols) >= 3:
                add, dele, fname = cols[0], cols[1], "\t".join(cols[2:])
                if add != "-" and dele != "-":
                    try:
                        cur.insertions += int(add)
                        cur.deletions += int(dele)
                    except ValueError:
                        pass
                cur.files.append(fname)
                cur.files_changed += 1
    return tel


def commit_activity_series(commits: list[CommitRecord]) -> list[dict[str, Any]]:
    """Commits bucketed per day for dashboard charts."""
    buckets: dict[str, dict[str, int]] = {}
    for c in commits:
        if c.ts is None:
            continue
        day = time.strftime("%Y-%m-%d", time.gmtime(c.ts))
        b = buckets.setdefault(day, {"commits": 0, "insertions": 0, "deletions": 0})
        b["commits"] += 1
        b["insertions"] += c.insertions
        b["deletions"] += c.deletions
    return [{"day": d, **v} for d, v in sorted(buckets.items())]
