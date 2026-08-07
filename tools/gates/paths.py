"""Runtime and state locations.

Two areas exist and they are kept strictly apart:

* the **runtime area** inside the worktree (``.gate-runtime/``) holds raw
  logs, phase results, sanitized evidence and hook logs. It is gitignored.
* the **state area** outside the worktree holds the dedicated baseline
  worktrees and the baseline cache, so neither ever lands in tracked source.

Both are overridable through environment variables, which is what the tests
use; no user specific path is ever hard coded.
"""

from __future__ import annotations

import hashlib
import os
import platform
import stat
from pathlib import Path

RUNTIME_DIR_NAME = ".gate-runtime"
RUNTIME_ENV = "GATE_RUNTIME_DIR"
STATE_ENV = "GATE_STATE_DIR"
BASELINE_OWNER_MARKER = ".gate-baseline-owner.json"


def runtime_dir(worktree) -> Path:
    override = os.environ.get(RUNTIME_ENV)
    if override:
        return Path(override)
    return Path(worktree) / RUNTIME_DIR_NAME


def state_dir() -> Path:
    override = os.environ.get(STATE_ENV)
    if override:
        return Path(override)
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        return Path(cache_home) / "openjarvis-gate"
    return Path(os.path.expanduser("~")) / ".cache" / "openjarvis-gate"


def raw_log_dir(worktree) -> Path:
    return runtime_dir(worktree) / "raw-logs"


def results_dir(worktree) -> Path:
    return runtime_dir(worktree) / "results"


def evidence_dir(worktree) -> Path:
    return runtime_dir(worktree) / "evidence"


def hook_log_dir(worktree) -> Path:
    return runtime_dir(worktree) / "hook-logs"


def repo_id(common_git_dir) -> str:
    """Stable, non-personal identifier for a repository."""
    resolved = str(Path(common_git_dir).resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def baseline_worktree_root(common_git_dir) -> Path:
    return state_dir() / "baseline-worktrees" / repo_id(common_git_dir)


def baseline_cache_root(common_git_dir) -> Path:
    return state_dir() / "baseline-cache" / repo_id(common_git_dir)


def platform_class() -> str:
    """``system/architecture/os-version`` — distinguishes x86_64 from arm64."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        release = platform.mac_ver()[0] or platform.release()
    else:  # pragma: no cover - the block targets macOS
        release = platform.release()
    release = "".join(ch for ch in release if ch.isdigit() or ch == ".")
    return f"{system}/{machine}/{release or '0'}"


def ensure_private_dir(path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    # Rule R9: the chmod is the only enforcement of the private-dir contract
    # (mkdir keeps a pre-existing directory's mode). Its effect is verified
    # rather than assumed; only a genuinely permissionless platform is
    # excused, and there the verification is skipped openly, not silently.
    os.chmod(str(target), 0o700)
    if os.name == "posix":
        mode = stat.S_IMODE(os.stat(str(target)).st_mode)
        if mode != 0o700:
            raise OSError(f"private directory mode is {oct(mode)}, not 0o700")
    return target
