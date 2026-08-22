"""Tests for the read-only git telemetry collector."""

import subprocess
import time

import pytest

from fab.models import EventType, Provenance
from fab.telemetry.git_telemetry import (collect_git_telemetry,
                                         commit_activity_series)


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture()
def mini_repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@t.io")
    git(r, "config", "user.name", "tester")
    (r / "a.py").write_text("x = 1\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "feat: initial implementation")
    time.sleep(1.1)  # distinct timestamps
    (r / "a.py").write_text("x = 2\n# fixed\n")
    (r / "b.py").write_text("y = 3\n" * 20)
    git(r, "add", "-A")
    git(r, "commit", "-qm", "fix: correct off-by-one bug in parser")
    return r


def test_collects_commits_and_stats(mini_repo):
    tel = collect_git_telemetry(mini_repo)
    assert tel.is_git_repo
    assert tel.total_commits == 2
    assert tel.commits[0].subject.startswith("fix:")
    assert tel.commits[-1].subject.startswith("feat:")
    assert tel.commits[0].insertions >= 21  # b.py added + a.py changed
    assert tel.head_sha and len(tel.head_sha) == 40


def test_events_from_history(mini_repo):
    tel = collect_git_telemetry(mini_repo)
    evs = tel.events("proj", "sess1")
    types = {e.type for e in evs}
    assert EventType.COMMIT_CREATED in types
    # 'fix:' commit classified as bug fix but tagged ESTIMATED
    fixes = [e for e in evs if e.type == EventType.BUG_FIXED]
    assert fixes and fixes[0].provenance is Provenance.ESTIMATED
    # commits themselves are OBSERVED
    commits = [e for e in evs if e.type == EventType.COMMIT_CREATED]
    assert all(e.provenance is Provenance.OBSERVED for e in commits)
    # chronological ordering oldest first
    ts_list = [e.ts for e in commits]
    assert ts_list == sorted(ts_list)


def test_measurements_provenance(mini_repo):
    tel = collect_git_telemetry(mini_repo)
    m = tel.measurements()
    assert m["commits_total"].provenance.value == "OBSERVED"
    assert m["commits_total"].value == 2
    assert m["commit_last_time"].available


def test_non_repo_directory_is_all_unavailable(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    tel = collect_git_telemetry(plain)
    assert not tel.is_git_repo
    m = tel.measurements()
    for key in ("commits_total", "head_sha"):
        assert not m[key].available
        assert m[key].provenance.value == "UNAVAILABLE"


def test_activity_series_buckets_by_day(mini_repo):
    tel = collect_git_telemetry(mini_repo)
    series = commit_activity_series(tel.commits)
    assert series and series[0]["commits"] >= 1
    assert {"day", "commits", "insertions", "deletions"} <= set(series[0])


def test_collector_does_not_mutate_subject(mini_repo):
    """The collector must leave the subject tree content-identical.

    (git itself may refresh its index stat-cache on read, so we compare
    file sets and content hashes, not mtimes.)
    """
    def snapshot():
        return {
            str(p.relative_to(mini_repo)): p.read_bytes()
            for p in mini_repo.rglob("*")
            if p.is_file() and ".git" not in p.parts
        }
    before = snapshot()
    collect_git_telemetry(mini_repo)
    assert snapshot() == before
    # and the working-tree git state is unchanged
    st = subprocess.run(["git", "-C", str(mini_repo), "status", "--porcelain"],
                        capture_output=True, text=True).stdout
    assert st == ""
