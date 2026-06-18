import subprocess
from pathlib import Path

import pytest

from services.git_worktrees import GitWorktreeService, WorktreeSafetyError, parse_worktree_porcelain


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_parse_worktree_porcelain_handles_branch_detached_locked_and_prunable():
    output = """worktree /repo
HEAD abc123
branch refs/heads/main

worktree /repo-feature
HEAD def456
detached
locked in use
prunable stale admin dir

"""

    worktrees = parse_worktree_porcelain(output)

    assert worktrees[0].path == "/repo"
    assert worktrees[0].branch == "main"
    assert worktrees[0].detached is False
    assert worktrees[1].path == "/repo-feature"
    assert worktrees[1].detached is True
    assert worktrees[1].locked == "in use"
    assert worktrees[1].prunable == "stale admin dir"


def test_add_constructs_git_worktree_add_with_new_branch(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    target = tmp_path / "project-feature"
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[-2:] == ["rev-parse", "--show-toplevel"]:
            return _completed(stdout=str(root))
        if argv[-3:] == ["worktree", "list", "--porcelain"]:
            return _completed(stdout=f"worktree {target}\nHEAD abc\nbranch refs/heads/feature\n\n")
        return _completed()

    service = GitWorktreeService(allowed_worktree_parents=[tmp_path], runner=runner)

    created = service.add(root, target, new_branch="feature", start_point="main")

    assert created.path == str(target)
    assert created.branch == "feature"
    assert calls[1] == [
        "git",
        "-C",
        str(root),
        "worktree",
        "add",
        "-b",
        "feature",
        str(target),
        "main",
    ]


def test_remove_constructs_git_worktree_remove_without_force(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    target = tmp_path / "project-feature"
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[-2:] == ["rev-parse", "--show-toplevel"]:
            return _completed(stdout=str(root))
        if argv[-3:] == ["worktree", "list", "--porcelain"]:
            return _completed(stdout=f"worktree {root}\nHEAD abc\nbranch refs/heads/main\n\nworktree {target}\nHEAD def\nbranch refs/heads/feature\n\n")
        return _completed()

    service = GitWorktreeService(allowed_worktree_parents=[tmp_path], runner=runner)

    service.remove(root, target)

    assert calls[-1] == ["git", "-C", str(root), "worktree", "remove", str(target)]
    assert "--force" not in calls[-1]


def test_rejects_worktree_path_outside_allowed_parent(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path.parent / "elsewhere"

    def runner(argv, **kwargs):
        if argv[-2:] == ["rev-parse", "--show-toplevel"]:
            return _completed(stdout=str(root))
        return _completed()

    service = GitWorktreeService(allowed_worktree_parents=[root.parent], runner=runner)

    with pytest.raises(WorktreeSafetyError):
        service.add(root, outside, branch="main")


def test_remove_rejects_unattached_worktree_path(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    target = tmp_path / "project-feature"

    def runner(argv, **kwargs):
        if argv[-2:] == ["rev-parse", "--show-toplevel"]:
            return _completed(stdout=str(root))
        if argv[-3:] == ["worktree", "list", "--porcelain"]:
            return _completed(stdout=f"worktree {root}\nHEAD abc\nbranch refs/heads/main\n\n")
        return _completed()

    service = GitWorktreeService(allowed_worktree_parents=[tmp_path], runner=runner)

    with pytest.raises(WorktreeSafetyError):
        service.remove(root, target)
