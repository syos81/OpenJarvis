"""Small, deterministic git helpers used by the gate engine.

Every call goes through :func:`run_git` with a fixed locale and a reduced
environment, so output parsing is stable. Nothing here ever hard codes a
repository or user path — the worktree is always discovered at runtime.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

GIT_TIMEOUT_SECONDS = 120


class GitError(RuntimeError):
    """Raised when a git invocation fails in a way the caller cannot handle."""


def deterministic_env(extra=None):
    """Return a reduced, deterministic environment for child processes."""
    base = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "HOME": os.environ.get("HOME", ""),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "NO_COLOR": "1",
    }
    if extra:
        base.update({k: v for k, v in extra.items() if v is not None})
    return base


def run_git(args, cwd=None, timeout=GIT_TIMEOUT_SECONDS):
    """Run ``git`` with the given argv list. Returns ``(code, out, err)``."""
    argv = ["git"] + [str(arg) for arg in args]
    completed = subprocess.run(  # noqa: S603 - fixed argv, never a shell string
        argv,
        cwd=str(cwd) if cwd else None,
        env=deterministic_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return (
        completed.returncode,
        completed.stdout.decode("utf-8", "replace"),
        completed.stderr.decode("utf-8", "replace"),
    )


def git_text(args, cwd=None):
    code, out, err = run_git(args, cwd=cwd)
    if code != 0:
        raise GitError(f"git {' '.join(str(a) for a in args)} failed: {err.strip()}")
    return out.strip()


def toplevel(cwd=None) -> Path:
    return Path(git_text(["rev-parse", "--show-toplevel"], cwd=cwd))


def common_dir(cwd=None) -> Path:
    path = Path(git_text(["rev-parse", "--git-common-dir"], cwd=cwd))
    if not path.is_absolute():
        path = (Path(cwd) if cwd else Path.cwd()) / path
    return path.resolve()


def current_branch(cwd=None) -> str:
    code, out, _ = run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=cwd)
    return out.strip() if code == 0 else ""


def head_commit(cwd=None) -> str:
    return git_text(["rev-parse", "HEAD"], cwd=cwd)


def resolve_commit(rev, cwd=None):
    code, out, _ = run_git(["rev-parse", "--verify", f"{rev}^{{commit}}"], cwd=cwd)
    return out.strip() if code == 0 else None


def commit_exists(rev, cwd=None) -> bool:
    code, _, _ = run_git(["cat-file", "-e", f"{rev}^{{commit}}"], cwd=cwd)
    return code == 0


def status_porcelain(cwd=None):
    """Return the porcelain status as a sorted list of ``(xy, path)``."""
    out = git_text(["status", "--porcelain=v1", "--untracked-files=all"], cwd=cwd)
    entries = []
    for line in out.splitlines():
        if not line.strip():
            continue
        entries.append((line[:2].strip(), line[3:].strip()))
    return sorted(entries, key=lambda item: (item[1], item[0]))


def is_tracked(path, cwd=None) -> bool:
    code, out, _ = run_git(["ls-files", "--error-unmatch", str(path)], cwd=cwd)
    return code == 0 and bool(out.strip())


def tracked_files(cwd=None):
    return sorted(git_text(["ls-files"], cwd=cwd).splitlines())


def check_ignore(path, cwd=None) -> bool:
    code, _, _ = run_git(["check-ignore", "--quiet", str(path)], cwd=cwd)
    return code == 0


def worktree_list(cwd=None):
    """Parse ``git worktree list --porcelain`` into sorted records."""
    out = git_text(["worktree", "list", "--porcelain"], cwd=cwd)
    records = []
    current = {}
    for line in out.splitlines():
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            if current:
                records.append(current)
            current = {"worktree": value, "detached": False, "branch": ""}
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = value
        elif key == "detached":
            current["detached"] = True
        elif key == "bare":
            current["bare"] = True
    if current:
        records.append(current)
    return sorted(records, key=lambda item: item["worktree"])


def changed_files(base_ref=None, cwd=None):
    """Files changed in the working tree and, if resolvable, since ``base_ref``.

    Returns ``(files, base_resolved)``; ``base_resolved`` is ``None`` when the
    declared base ref does not exist locally.
    """
    files = set()
    for args in (
        ["diff", "--name-only", "HEAD"],
        ["diff", "--name-only", "--cached", "HEAD"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        code, out, _ = run_git(args, cwd=cwd)
        if code == 0:
            files.update(line.strip() for line in out.splitlines() if line.strip())
    base_resolved = None
    if base_ref:
        code, out, _ = run_git(["merge-base", base_ref, "HEAD"], cwd=cwd)
        if code == 0 and out.strip():
            base_resolved = out.strip()
            code, out, _ = run_git(
                ["diff", "--name-only", f"{base_resolved}..HEAD"], cwd=cwd
            )
            if code == 0:
                files.update(
                    line.strip() for line in out.splitlines() if line.strip()
                )
    return sorted(files), base_resolved
