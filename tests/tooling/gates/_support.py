"""Shared helpers for the B0a-1 tooling tests.

Everything destructive happens in throwaway temporary repositories; no test
ever touches a real Jarvis worktree. The module name deliberately starts with
an underscore so ``unittest discover`` does not collect it.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_MANIFEST = (
    REPO_ROOT / "config" / "gates" / "fixtures" / "manifests" / "valid" / "minimal.json"
)
BLOCK_MANIFEST = REPO_ROOT / "config" / "gates" / "blocks" / "b0a-1-tooling.json"


def git(args, cwd, check=True):
    completed = subprocess.run(
        ["git"] + [str(arg) for arg in args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"git {' '.join(str(a) for a in args)} failed: "
            f"{completed.stderr.decode('utf-8', 'replace')}"
        )
    return completed.returncode, completed.stdout.decode("utf-8", "replace")


def make_repo(root, *, files=None, message="initial"):
    """Create a throwaway git repository and return its path."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    git(["init", "--quiet", "-b", "main"], cwd=root)
    git(["config", "user.email", "tooling-tests@example.invalid"], cwd=root)
    git(["config", "user.name", "Tooling Tests"], cwd=root)
    git(["config", "commit.gpgsign", "false"], cwd=root)
    for name, content in (files or {"README.md": "temporary test repository\n"}).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(["add", "-A"], cwd=root)
    git(["commit", "--quiet", "-m", message], cwd=root)
    return root


def load_fixture_manifest():
    return json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))


def load_block_manifest():
    return json.loads(BLOCK_MANIFEST.read_text(encoding="utf-8"))


def mutate(data, mutation):
    clone = copy.deepcopy(data)
    mutation(clone)
    return clone


class TempEnvMixin(unittest.TestCase):
    """Isolate runtime and state directories for every test."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="gate-tests-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.runtime_dir = self.tmp_path / "runtime"
        self.state_dir = self.tmp_path / "state"
        self._env_backup = {
            key: os.environ.get(key)
            for key in ("GATE_RUNTIME_DIR", "GATE_STATE_DIR", "GATE_REPORT")
        }
        os.environ["GATE_RUNTIME_DIR"] = str(self.runtime_dir)
        os.environ["GATE_STATE_DIR"] = str(self.state_dir)
        os.environ.pop("GATE_REPORT", None)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeCheck:
    """Minimal stand-in for a manifest check in unit level tests."""

    def __init__(
        self,
        check_id="fake-check",
        *,
        phase="offline-final",
        parser="gate_json",
        baseline_eligible=True,
        runner=None,
        timeout_seconds=60,
        required=True,
        evidence_profile="tooling",
    ):
        self.check_id = check_id
        self.phase = phase
        self.parser = parser
        self.baseline_eligible = baseline_eligible
        self.runner = runner or {"type": "argv", "cwd": "target", "argv": ["true"]}
        self.timeout_seconds = timeout_seconds
        self.required = required
        self.evidence_profile = evidence_profile

    def as_definition(self):
        return {
            "check_id": self.check_id,
            "phase": self.phase,
            "required": self.required,
            "runner": self.runner,
            "parser": self.parser,
            "timeout_seconds": self.timeout_seconds,
            "baseline_eligible": self.baseline_eligible,
            "evidence_profile": self.evidence_profile,
        }


def structured(outcome, failures=(), diagnostics=(), structural=True):
    return {
        "outcome": outcome,
        "structural": structural,
        "failures": [dict(item) for item in failures],
        "diagnostics": list(diagnostics),
    }


def failure(identifier, *, category="test_failure", error_class="AssertionError",
            code="", frames=()):
    return {
        "id": identifier,
        "category": category,
        "class": error_class,
        "code": code,
        "frames": list(frames),
    }
