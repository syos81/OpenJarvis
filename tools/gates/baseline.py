"""Baseline engine: dedicated worktree, structural comparison, cache use.

The only code baseline is the commit declared in the manifest. It is never
replaced by a branch tip, a tag, a merge base or the current history.

Baseline runs happen in a dedicated, detached git worktree that

* lives outside the active worktree,
* is created from the current repository through git,
* carries an ownership marker of this engine,
* is locked against parallel use,
* and is verified (HEAD, cleanliness, repository origin) before every use.

Only worktrees this engine created and marked may be renewed or removed. An
unknown existing worktree is never touched.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
from pathlib import Path

from . import CAUSE_SIGNATURE_VERSION
from . import ENGINE_VERSION
from . import cache as cache_module
from . import gitutil
from . import paths as gate_paths
from . import signature as signature_module
from . import statuses

OWNER_MARKER_NAME = gate_paths.BASELINE_OWNER_MARKER
DEFAULT_OWNER = "openjarvis-gate-baseline"


class BaselineUnavailable(RuntimeError):
    """Raised when a required baseline run cannot be performed."""

    def __init__(self, reason_code, message=""):
        self.reason_code = reason_code
        super().__init__(message or reason_code)


def marker_payload(*, owner, common_git_dir, commit):
    return {
        "owner": owner,
        "engine_version": ENGINE_VERSION,
        "repo_id": gate_paths.repo_id(common_git_dir),
        "commit": commit,
    }


def is_owned(path, *, owner, common_git_dir, commit):
    """True only for a worktree this engine created for exactly this commit."""
    marker = Path(path) / OWNER_MARKER_NAME
    if not marker.is_file():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    expected = marker_payload(
        owner=owner, common_git_dir=common_git_dir, commit=commit
    )
    return (
        data.get("owner") == expected["owner"]
        and data.get("repo_id") == expected["repo_id"]
        and data.get("commit") == expected["commit"]
    )


class BaselineWorktree:
    """Lifecycle of the dedicated baseline worktree."""

    def __init__(self, *, source_worktree, commit, owner=DEFAULT_OWNER):
        self.source_worktree = Path(source_worktree)
        self.owner = owner
        self.common_git_dir = gitutil.common_dir(self.source_worktree)
        resolved = gitutil.resolve_commit(commit, cwd=self.source_worktree)
        if not resolved:
            raise BaselineUnavailable(
                "baseline_commit_missing",
                "the declared baseline commit is not available locally",
            )
        self.commit = resolved
        self.root = gate_paths.baseline_worktree_root(self.common_git_dir)
        self.path = self.root / self.commit[:12]
        self._lock_fd = None

    # -- locking -----------------------------------------------------------
    def acquire_lock(self):
        gate_paths.ensure_private_dir(self.root)
        lock_path = self.root / f"{self.commit[:12]}.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                raise BaselineUnavailable(
                    "baseline_worktree_locked",
                    "another gate run is using the baseline worktree",
                ) from exc
            raise
        self._lock_fd = fd

    def release_lock(self):
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = None

    # -- lifecycle ---------------------------------------------------------
    def _write_marker(self):
        marker = self.path / OWNER_MARKER_NAME
        marker.write_text(
            json.dumps(
                marker_payload(
                    owner=self.owner,
                    common_git_dir=self.common_git_dir,
                    commit=self.commit,
                ),
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _owned(self):
        return is_owned(
            self.path,
            owner=self.owner,
            common_git_dir=self.common_git_dir,
            commit=self.commit,
        )

    def _verify(self):
        """Return ``(ok, reason_code)`` for an existing baseline worktree."""
        if not (self.path / ".git").exists():
            return False, "baseline_worktree_incomplete"
        try:
            head = gitutil.head_commit(cwd=self.path)
        except gitutil.GitError:
            return False, "baseline_worktree_unreadable"
        if head != self.commit:
            return False, "baseline_worktree_wrong_head"
        try:
            common = gitutil.common_dir(cwd=self.path)
        except gitutil.GitError:
            return False, "baseline_worktree_unreadable"
        if common != self.common_git_dir:
            return False, "baseline_worktree_foreign_repository"
        try:
            dirty = gitutil.status_porcelain(cwd=self.path)
        except gitutil.GitError:
            return False, "baseline_worktree_unreadable"
        dirty = [
            entry
            for entry in dirty
            if Path(entry[1]).name != OWNER_MARKER_NAME
        ]
        if dirty:
            return False, "baseline_worktree_dirty"
        return True, "baseline_worktree_verified"

    def _remove(self):
        """Remove the worktree — only ever one this engine owns."""
        if not self._owned():
            raise BaselineUnavailable(
                "baseline_worktree_foreign",
                "refusing to touch a worktree this engine does not own",
            )
        code, _, err = gitutil.run_git(
            ["worktree", "remove", "--force", str(self.path)],
            cwd=self.source_worktree,
        )
        if code != 0 and self.path.exists():
            raise BaselineUnavailable(
                "baseline_worktree_removal_failed", err.strip()[:200]
            )
        gitutil.run_git(["worktree", "prune"], cwd=self.source_worktree)

    def _create(self):
        gate_paths.ensure_private_dir(self.root)
        code, _, err = gitutil.run_git(
            ["worktree", "add", "--detach", str(self.path), self.commit],
            cwd=self.source_worktree,
        )
        if code != 0:
            raise BaselineUnavailable(
                "baseline_worktree_creation_failed", err.strip()[:200]
            )
        self._write_marker()

    def prepare(self):
        """Return a verified baseline worktree path, renewing it if needed."""
        registered = {
            str(Path(record["worktree"]).resolve())
            for record in gitutil.worktree_list(cwd=self.source_worktree)
        }
        exists = self.path.exists()
        if exists and not self._owned():
            raise BaselineUnavailable(
                "baseline_worktree_foreign",
                "an unknown worktree occupies the baseline location",
            )
        if exists:
            ok, reason = self._verify()
            if not ok:
                self._remove()
                self._create()
        else:
            if str(self.path.resolve()) in registered:
                # Registered in git but gone on disk — clean the stale record.
                gitutil.run_git(["worktree", "prune"], cwd=self.source_worktree)
            self._create()
        ok, reason = self._verify()
        if not ok:
            raise BaselineUnavailable(reason, "baseline worktree not usable")
        return self.path


def compare_runs(check, candidate_structured, baseline_structured, block_id=""):
    """Structural comparison of candidate and baseline outcomes.

    Returns ``(status, reason_code, candidate_signature, baseline_signature)``.
    """
    build = signature_module.build_cause_signature
    candidate_failed = candidate_structured.get("outcome") != "passed"
    if not candidate_failed:
        return statuses.PASS, "check_passed", None, None
    if not check.baseline_eligible:
        return (
            statuses.FAIL,
            "check_failed_not_baseline_eligible",
            None,
            None,
        )
    if baseline_structured is None:
        return statuses.BLOCKED, "baseline_unavailable", None, None
    if baseline_structured.get("outcome") == "passed":
        return statuses.FAIL, "baseline_clean_candidate_failed", None, None

    candidate_signature = build(
        block_id=block_id,
        check_id=check.check_id,
        runner_kind=check.runner.get("type", ""),
        parser=check.parser,
        structured=candidate_structured,
    )
    baseline_signature = build(
        block_id=block_id,
        check_id=check.check_id,
        runner_kind=check.runner.get("type", ""),
        parser=check.parser,
        structured=baseline_structured,
    )
    if candidate_signature is None or baseline_signature is None:
        return (
            statuses.FAIL,
            "cause_signature_unavailable",
            candidate_signature,
            baseline_signature,
        )
    same, reason = signature_module.compare(candidate_signature, baseline_signature)
    if same:
        return (
            statuses.PASS_WITH_BASELINE,
            reason,
            candidate_signature,
            baseline_signature,
        )
    return statuses.FAIL, reason, candidate_signature, baseline_signature


def cache_result_from_structured(structured, exit_code, signature):
    return {
        "outcome": structured.get("outcome", "error"),
        "exit_code": exit_code,
        "reason_code": "baseline_recorded",
        "cause_signature": signature,
        "failure_count": len(structured.get("failures") or []),
    }


def structured_from_cache(result):
    """Rebuild the minimal structured view a cached baseline result carries."""
    signature = result.get("cause_signature")
    failures = []
    if signature:
        failures = signature.get("elements", {}).get("failures", [])
    return {
        "outcome": result.get("outcome", "error"),
        "structural": bool(signature),
        "failures": failures,
        "diagnostics": (
            signature.get("elements", {}).get("diagnostics", []) if signature else []
        ),
    }


def build_cache_key(
    *,
    manifest,
    check,
    phase,
    platform_class,
    toolchain,
    dependency_lock_digests,
    config_digests,
    baseline_commit,
):
    from . import ENGINE_SCHEMA_VERSION

    return cache_module.build_key(
        baseline_commit=baseline_commit,
        engine_schema_version=ENGINE_SCHEMA_VERSION,
        cause_signature_version=CAUSE_SIGNATURE_VERSION,
        block_id=manifest.block_id,
        phase=phase,
        check_id=check.check_id,
        check_definition=check.as_definition(),
        manifest_digest=manifest.digest,
        platform_class=platform_class,
        toolchain=toolchain,
        dependency_lock_digests=dependency_lock_digests,
        config_digests=config_digests,
    )
