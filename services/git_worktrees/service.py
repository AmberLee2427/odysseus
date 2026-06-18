"""Git worktree service.

The project registry owns durable project identity and root paths. This service
only manages branch/run-specific Git worktrees attached to a supplied project
root; it deliberately does not create or model projects.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence


class WorktreeSafetyError(ValueError):
    """Raised when a worktree path fails confinement or validation."""


class GitCommandError(RuntimeError):
    """Raised when a Git command exits unsuccessfully."""

    def __init__(self, args: Sequence[str], stderr: str, returncode: int):
        self.args_list = list(args)
        self.stderr = stderr.strip()
        self.returncode = returncode
        message = self.stderr or f"git exited with status {returncode}"
        super().__init__(message)


@dataclass(frozen=True)
class GitWorktree:
    """A parsed `git worktree list --porcelain` entry."""

    path: str
    head: str | None = None
    branch: str | None = None
    detached: bool = False
    bare: bool = False
    locked: str | None = None
    prunable: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


Runner = Callable[..., subprocess.CompletedProcess[str]]


def parse_worktree_porcelain(output: str) -> list[GitWorktree]:
    """Parse `git worktree list --porcelain` output."""
    entries: list[GitWorktree] = []
    current: dict[str, object] = {}

    def flush() -> None:
        nonlocal current
        path = current.get("path")
        if isinstance(path, str) and path:
            entries.append(
                GitWorktree(
                    path=path,
                    head=current.get("head") if isinstance(current.get("head"), str) else None,
                    branch=current.get("branch") if isinstance(current.get("branch"), str) else None,
                    detached=bool(current.get("detached")),
                    bare=bool(current.get("bare")),
                    locked=current.get("locked") if isinstance(current.get("locked"), str) else None,
                    prunable=current.get("prunable") if isinstance(current.get("prunable"), str) else None,
                )
            )
        current = {}

    for raw_line in output.splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            flush()
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = value
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
        elif key in {"detached", "bare"}:
            current[key] = True
        elif key in {"locked", "prunable"}:
            current[key] = value or True
    flush()
    return entries


class GitWorktreeService:
    """Small wrapper around real Git worktree commands."""

    def __init__(
        self,
        *,
        allowed_worktree_parents: Iterable[str | os.PathLike[str]] | None = None,
        runner: Runner | None = None,
        timeout: int = 30,
    ):
        env_parents = os.environ.get("ODYSSEUS_WORKTREE_PARENTS", "")
        configured = [
            parent
            for parent in env_parents.split(os.pathsep)
            if parent.strip()
        ]
        parent_paths = list(allowed_worktree_parents or configured)
        self.allowed_worktree_parents = [
            Path(parent).expanduser().resolve(strict=False)
            for parent in parent_paths
        ]
        self.runner = runner or subprocess.run
        self.timeout = timeout

    def list(self, root_path: str | os.PathLike[str]) -> list[GitWorktree]:
        root = self._validate_git_root(root_path)
        result = self._git(root, "worktree", "list", "--porcelain")
        return parse_worktree_porcelain(result.stdout)

    def list_branches(self, root_path: str | os.PathLike[str]) -> list[str]:
        root = self._validate_git_root(root_path)
        result = self._git(root, "branch", "--format=%(refname:short)")
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def add(
        self,
        root_path: str | os.PathLike[str],
        worktree_path: str | os.PathLike[str],
        *,
        branch: str | None = None,
        new_branch: str | None = None,
        start_point: str | None = None,
    ) -> GitWorktree:
        root = self._validate_git_root(root_path)
        target = self._resolve_worktree_path(root, worktree_path)
        args = ["worktree", "add"]
        if new_branch:
            args.extend(["-b", new_branch])
        args.append(str(target))
        if branch:
            args.append(branch)
        elif start_point:
            args.append(start_point)
        self._git(root, *args)

        for worktree in self.list(root):
            if Path(worktree.path).resolve(strict=False) == target:
                return worktree
        return GitWorktree(path=str(target), branch=new_branch or branch)

    def remove(
        self,
        root_path: str | os.PathLike[str],
        worktree_path: str | os.PathLike[str],
    ) -> None:
        root = self._validate_git_root(root_path)
        target = self._resolve_worktree_path(root, worktree_path)
        known_paths = {
            Path(worktree.path).resolve(strict=False)
            for worktree in self.list(root)
        }
        if target not in known_paths:
            raise WorktreeSafetyError("Worktree path is not attached to this project")
        self._git(root, "worktree", "remove", str(target))

    def _validate_git_root(self, root_path: str | os.PathLike[str]) -> Path:
        try:
            root = Path(root_path).expanduser().resolve(strict=True)
        except FileNotFoundError as error:
            raise WorktreeSafetyError("Project root does not exist") from error
        if not root.is_dir():
            raise WorktreeSafetyError("Project root is not a directory")
        result = self._git_raw(root, "rev-parse", "--show-toplevel")
        top = Path(result.stdout.strip()).expanduser().resolve(strict=False)
        if top != root:
            raise WorktreeSafetyError("Project root must be the repository top-level")
        return root

    def _resolve_worktree_path(
        self,
        root: Path,
        worktree_path: str | os.PathLike[str],
    ) -> Path:
        raw = Path(worktree_path).expanduser()
        if not raw.is_absolute():
            raw = root.parent / raw
        target = raw.resolve(strict=False)
        allowed = self._allowed_parents_for(root)
        if not any(self._is_relative_to(target, parent) for parent in allowed):
            allowed_text = ", ".join(str(parent) for parent in allowed)
            raise WorktreeSafetyError(f"Worktree path must be under an allowed parent: {allowed_text}")
        return target

    def _allowed_parents_for(self, root: Path) -> list[Path]:
        if self.allowed_worktree_parents:
            return self.allowed_worktree_parents
        return [root.parent.resolve(strict=False)]

    def _git(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return self._git_raw(root, *args)

    def _git_raw(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        argv = ["git", "-C", str(cwd), *args]
        try:
            result = self.runner(
                argv,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as error:
            raise GitCommandError(argv, "git executable was not found", 127) from error
        if result.returncode != 0:
            stderr = result.stderr or result.stdout
            if "not a git repository" in stderr.lower():
                stderr = "Project root is not a git repository"
            raise GitCommandError(argv, stderr, result.returncode)
        return result

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False
