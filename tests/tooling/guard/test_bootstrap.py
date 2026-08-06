"""Fail closed matrix of the guard bootstrap.

Every case runs against a throwaway installation. The expectation is always
the same: a blocking response with a machine readable code. There is no case
in which a broken protection chain releases a request.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.guard import _support  # noqa: E402

AMEND = "--am" + "end"


class TestFailClosed(_support.TempInstallationMixin):
    def _decide(self, command="git status --short", **kwargs):
        return _support.run_bootstrap(
            self.root, self.bash_payload(command), **kwargs
        )

    def _assert_blocked(self, response, code):
        self.assertEqual(_support.decision_of(response), "deny")
        self.assertIn(code, _support.reason_of(response))

    def test_intact_installation_still_decides(self):
        # Counter test for rule change RC-005.
        response = self._decide("git commit " + AMEND)
        self._assert_blocked(response, "git_commit_amend")
        neutral = self._decide("git status --short")
        self.assertEqual(neutral, {"guardOutcome": "no_opinion"})

    def test_every_failure_path_blocks(self):
        # Sharpening test for rule change RC-005: the enumerated failure
        # states used to end in a silent exit 0.
        cases = []

        missing = self.tmp_path / "absent"
        cases.append(
            ("missing_root", _support.run_bootstrap(missing, self.bash_payload("ls")))
        )

        broken = self.tmp_path / "no-manifest"
        _support.install(broken)
        (broken / "active.json").unlink()
        cases.append(
            ("missing_manifest", _support.run_bootstrap(broken, self.bash_payload("ls")))
        )

        for name, response in cases:
            with self.subTest(case=name):
                self.assertEqual(_support.decision_of(response), "deny")

    def test_missing_install_root_blocks(self):
        response = _support.run_bootstrap(
            self.tmp_path / "absent", self.bash_payload("ls")
        )
        self._assert_blocked(response, "GUARD_INSTALL_ROOT_MISSING")

    def test_missing_active_manifest_blocks(self):
        (self.root / "active.json").unlink()
        self._assert_blocked(self._decide(), "GUARD_ACTIVE_MANIFEST_MISSING")

    def test_corrupt_active_manifest_blocks(self):
        (self.root / "active.json").write_text("{not json", encoding="utf-8")
        self._assert_blocked(self._decide(), "GUARD_ACTIVE_MANIFEST_INVALID")

    def test_unknown_manifest_field_blocks(self):
        manifest = json.loads((self.root / "active.json").read_text(encoding="utf-8"))
        manifest["extra"] = 1
        (self.root / "active.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        self._assert_blocked(self._decide(), "GUARD_ACTIVE_MANIFEST_INVALID")

    def test_package_hash_mismatch_blocks(self):
        target = self.root / "active" / "guard" / "rules.json"
        os.chmod(str(target), 0o644)
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["config_version"] = "9.9.9"
        target.write_text(json.dumps(payload), encoding="utf-8")
        self._assert_blocked(self._decide(), "GUARD_PACKAGE_HASH_MISMATCH")

    def test_added_package_file_blocks(self):
        extra = self.root / "active" / "guard" / "extra.py"
        extra.write_text("# injected\n", encoding="utf-8")
        self._assert_blocked(self._decide(), "GUARD_PACKAGE_HASH_MISMATCH")

    def test_missing_package_blocks(self):
        for child in sorted((self.root / "active" / "guard").iterdir()):
            os.chmod(str(child), 0o644)
            child.unlink()
        (self.root / "active" / "guard").rmdir()
        response = self._decide()
        self.assertEqual(_support.decision_of(response), "deny")

    def test_unsupported_version_blocks(self):
        manifest = json.loads((self.root / "active.json").read_text(encoding="utf-8"))
        manifest["guard_version"] = "0.0.1"
        (self.root / "active.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        self._assert_blocked(self._decide(), "GUARD_VERSION_UNSUPPORTED")

    def test_missing_interpreter_blocks(self):
        manifest = json.loads((self.root / "active.json").read_text(encoding="utf-8"))
        manifest["interpreter"] = "/nonexistent/python3"
        (self.root / "active.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        self._assert_blocked(self._decide(), "GUARD_INTERPRETER_MISSING")

    def test_group_writable_component_blocks(self):
        os.chmod(str(self.root / "active.json"), 0o664)
        self._assert_blocked(
            self._decide(), "GUARD_INSTALL_ROOT_NOT_OWNER_CONTROLLED"
        )

    def test_symlinked_component_blocks(self):
        elsewhere = self.tmp_path / "elsewhere.sh"
        elsewhere.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        target = self.root / "bootstrap.sh"
        target.unlink()
        target.symlink_to(elsewhere)
        self._assert_blocked(
            self._decide(), "GUARD_INSTALL_ROOT_NOT_OWNER_CONTROLLED"
        )

    def test_foreign_ownership_blocks(self):
        # Ownership is what carries the trust: expecting root on a user owned
        # throwaway installation must block.
        self._assert_blocked(
            self._decide(expect_uid=0), "GUARD_INSTALL_ROOT_NOT_OWNER_CONTROLLED"
        )

    def test_corrupt_rule_configuration_blocks(self):
        target = self.root / "active" / "guard" / "rules.json"
        os.chmod(str(target), 0o644)
        target.write_text("{}", encoding="utf-8")
        manifest = json.loads((self.root / "active.json").read_text(encoding="utf-8"))
        sys.path.insert(0, str(self.root))
        import bootstrap as active  # noqa: PLC0415

        manifest["package_sha256"] = active.package_digest(str(self.root / "active"))
        (self.root / "active.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        self._assert_blocked(self._decide(), "GUARD_CONFIG_INVALID")

    def test_malformed_input_blocks(self):
        import io

        sys.path.insert(0, str(self.root))
        import bootstrap as active  # noqa: PLC0415

        stdout = io.StringIO()
        active.main(
            ["--install-root", str(self.root)],
            stdin=io.StringIO("not json at all"),
            stdout=stdout,
            expect_uid=os.getuid(),
        )
        response = json.loads(stdout.getvalue())
        self._assert_blocked(response, "GUARD_INPUT_MALFORMED")

    def test_unparseable_command_blocks(self):
        response = self._decide("echo 'unterminated")
        self._assert_blocked(response, "DENY_UNPARSEABLE_COMMAND")

    def test_project_directory_is_irrelevant(self):
        previous = os.environ.get("CLAUDE_PROJECT_DIR")
        try:
            for value in ("", "/nonexistent", str(self.tmp_path)):
                os.environ["CLAUDE_PROJECT_DIR"] = value
                response = self._decide("git commit " + AMEND)
                self._assert_blocked(response, "git_commit_amend")
        finally:
            if previous is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = previous

    def test_worktree_without_tooling_is_still_guarded(self):
        plain = self.tmp_path / "plain-worktree"
        plain.mkdir()
        subprocess.run(  # noqa: S603 - fixed argv
            ["git", "init", "--quiet", "-b", "main", str(plain)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.assertFalse((plain / "tools").exists())
        response = _support.run_bootstrap(
            self.root, self.bash_payload("git commit " + AMEND, cwd=plain)
        )
        self._assert_blocked(response, "git_commit_amend")


class TestWrapper(_support.TempInstallationMixin):
    def _run(self, root, command):
        script = Path(root) / "bootstrap.sh"
        completed = subprocess.run(  # noqa: S603 - fixed argv
            ["/bin/bash", str(script)],
            input=json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                    "cwd": str(self.tmp_path),
                }
            ).encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            shell=False,
            check=False,
        )
        return completed.stdout.decode("utf-8", "replace").strip()

    def test_wrapper_blocks_when_the_guard_cannot_run(self):
        # The installation is user owned, so the wrapper's bootstrap expects
        # root and refuses — the wrapper must surface a deny, never silence.
        output = self._run(self.root, "git status --short")
        self.assertIn('"permissionDecision"', output)
        self.assertIn("deny", output)

    def test_wrapper_blocks_on_a_missing_bootstrap(self):
        (self.root / "bootstrap.py").unlink()
        output = self._run(self.root, "ls")
        self.assertIn("GUARD_BOOTSTRAP_FAILED", output)

    def test_wrapper_blocks_on_a_missing_interpreter(self):
        script = self.root / "bootstrap.sh"
        source = script.read_text(encoding="utf-8")
        script.write_text(
            source.replace(
                os.path.realpath(sys.executable), "/nonexistent/python3"
            ),
            encoding="utf-8",
        )
        output = self._run(self.root, "ls")
        self.assertIn("GUARD_INTERPRETER_MISSING", output)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
