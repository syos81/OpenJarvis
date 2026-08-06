"""Helpers that build throwaway guard installations.

The module name starts with an underscore so ``unittest discover`` does not
collect it. Nothing here ever touches the owner installed active guard: the
installation root is always a fresh temporary directory and the ownership
expectation is the current user, never ``root``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GUARD_SOURCE = REPO_ROOT / "tools" / "guard"
PACKAGE_SOURCE = REPO_ROOT / "tools" / "guardpkg"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(PACKAGE_SOURCE))

import bootstrap as bootstrap_module  # noqa: E402

from tools.guard import GUARD_VERSION  # noqa: E402


def build_package(destination):
    """Build the runtime package into ``destination`` and return its digest."""
    completed = subprocess.run(  # noqa: S603 - fixed argv
        [
            sys.executable,
            str(PACKAGE_SOURCE / "build.py"),
            "--source",
            str(REPO_ROOT),
            "--out",
            str(destination),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8", "replace"))
    return json.loads(completed.stdout.decode("utf-8"))["package_sha256"]


def install(root, *, digest=None, source_commit=None, interpreter=None):
    """Create a complete throwaway installation below ``root``."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    built = build_package(root)
    (root / "bootstrap.py").write_bytes(
        (PACKAGE_SOURCE / "bootstrap.py").read_bytes()
    )
    interpreter = interpreter or os.path.realpath(sys.executable)
    template = (PACKAGE_SOURCE / "bootstrap.sh").read_text(encoding="utf-8")
    (root / "bootstrap.sh").write_text(
        template.replace("@@GUARD_ROOT@@", str(root)).replace(
            "@@GUARD_PYTHON@@", interpreter
        ),
        encoding="utf-8",
    )
    os.chmod(str(root / "bootstrap.sh"), 0o755)
    manifest = {
        "activated_at": "2026-08-06T00:00:00Z",
        "config_schema": "guard-config-1",
        "guard_version": GUARD_VERSION,
        "install_target": str(root),
        "interpreter": interpreter,
        "package_sha256": digest or built,
        "schema_version": "guard-active-1",
        "source_commit": source_commit or ("a" * 40),
    }
    (root / "active.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8"
    )
    for relative in ("var/exceptions/pending", "var/exceptions/spent"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "var" / "guard.log").write_text("", encoding="utf-8")
    return manifest


def run_bootstrap(root, payload, *, expect_uid=None):
    """Run the bootstrap against ``root`` and return the parsed response."""
    import io

    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    bootstrap_module.main(
        ["--install-root", str(root)],
        stdin=stdin,
        stdout=stdout,
        expect_uid=os.getuid() if expect_uid is None else expect_uid,
    )
    raw = stdout.getvalue().strip()
    return json.loads(raw) if raw else {}


def decision_of(response):
    specific = response.get("hookSpecificOutput") or {}
    return specific.get("permissionDecision")


def reason_of(response):
    specific = response.get("hookSpecificOutput") or {}
    return specific.get("permissionDecisionReason", "")


class TempInstallationMixin(unittest.TestCase):
    """A fresh installation per test, always outside any real worktree."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="guard-tests-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.root = self.tmp_path / "install"
        self.manifest = install(self.root)

    def bash_payload(self, command, cwd=None):
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(cwd or self.tmp_path),
        }
