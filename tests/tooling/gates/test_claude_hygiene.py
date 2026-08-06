"""Gitignore convention and file hygiene of the versioned project rules.

Every credential, key and machine path in this module is synthetic. The user
name variants used for the macOS negative cases are generated generically, not
taken from the real machine.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import hygiene  # noqa: E402
from tools.gates.runners import claude_hygiene  # noqa: E402

RELEASED_CLASSES = (
    "CLAUDE.md",
    ".claude/settings.json",
    ".claude/hooks/guard.sh",
    ".claude/skills/gate/SKILL.md",
)

#: Generic, synthetic macOS account name variants — never the real account.
GENERIC_MACOS_USERS = ("vornamenachname", "vorname.nachname")


def rules(text):
    return {rule_id for rule_id, _ in hygiene.scan_text(text)}


class TestReleasedPathClassification(unittest.TestCase):
    def test_exactly_four_release_patterns(self):
        self.assertEqual(
            hygiene.RELEASED_PATTERNS,
            (
                "CLAUDE.md",
                ".claude/settings.json",
                ".claude/hooks/**",
                ".claude/skills/**",
            ),
        )

    def test_released_paths_are_recognised(self):
        for path in RELEASED_CLASSES:
            with self.subTest(path=path):
                self.assertTrue(hygiene.released(path))

    def test_unreleased_paths_are_rejected(self):
        for path in (
            ".claude/settings.local.json",
            ".claude/agents/mail-agent.md",
            ".claude/state/cache.json",
            ".claude/launch.json",
            "docs/governance/b0a-2-module-map.md",
        ):
            with self.subTest(path=path):
                self.assertFalse(hygiene.released(path))


class TestGitignoreConvention(unittest.TestCase):
    def test_released_paths_are_not_ignored(self):
        for path in hygiene.MUST_BE_TRACKABLE:
            with self.subTest(path=path):
                self.assertFalse(
                    claude_hygiene.check_ignore_no_index(path, _support.REPO_ROOT),
                    f"{path} must stay versionable",
                )

    def test_unreleased_paths_are_ignored(self):
        for path in hygiene.MUST_BE_IGNORED:
            with self.subTest(path=path):
                self.assertTrue(
                    claude_hygiene.check_ignore_no_index(path, _support.REPO_ROOT),
                    f"{path} must stay ignored",
                )

    def test_local_settings_are_ignored_and_untracked(self):
        self.assertTrue(
            claude_hygiene.check_ignore_no_index(
                ".claude/settings.local.json", _support.REPO_ROOT
            )
        )
        from tools.gates import gitutil

        self.assertNotIn(
            ".claude/settings.local.json",
            gitutil.tracked_files(cwd=_support.REPO_ROOT),
        )

    def test_only_released_claude_paths_are_tracked(self):
        from tools.gates import gitutil

        tracked = [
            path
            for path in gitutil.tracked_files(cwd=_support.REPO_ROOT)
            if path.startswith(".claude/")
        ]
        self.assertTrue(tracked)
        for path in tracked:
            with self.subTest(path=path):
                self.assertTrue(hygiene.released(path))

    def test_a_blanket_exception_is_detected(self):
        for line in ("!.claude/**", "!.claude/", "! .claude/*"):
            with self.subTest(line=line):
                self.assertTrue(
                    hygiene.blanket_exception_lines(f"# comment\n{line}\n"),
                    line,
                )

    def test_the_repository_gitignore_has_no_blanket_exception(self):
        text = (_support.REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertEqual(hygiene.blanket_exception_lines(text), [])


class TestSecretDetection(unittest.TestCase):
    def test_credentials_in_every_released_path_class(self):
        payload = 'password = "hunter2example"\n'
        for path in RELEASED_CLASSES:
            with self.subTest(path=path):
                self.assertTrue(hygiene.released(path))
                self.assertIn("credential_assignment", rules(payload))

    def test_private_key_is_detected(self):
        text = "-----BEGIN OPENSSH PRIVATE KEY-----\nc3ludGhldGlj\n"
        self.assertIn("private_key", rules(text))

    def test_token_is_detected(self):
        self.assertIn("known_token", rules("value: ghp_synthetic0123456789\n"))
        self.assertIn("known_token", rules("key = sk-synthetic0123456789\n"))

    def test_uri_with_embedded_credentials_is_detected(self):
        self.assertIn(
            "uri_with_embedded_credentials",
            rules("url = https://user:secretvalue@example.invalid/repo.git\n"),
        )

    def test_the_finding_never_carries_the_value(self):
        findings = list(hygiene.scan_text('token = "ghp_synthetic0123456789"\n'))
        self.assertTrue(findings)
        for rule_id, line_number in findings:
            self.assertIsInstance(rule_id, str)
            self.assertIsInstance(line_number, int)
            self.assertNotIn("ghp_", rule_id)


class TestMachinePathDetection(unittest.TestCase):
    def test_both_generic_macos_account_variants_are_detected(self):
        for name in GENERIC_MACOS_USERS:
            with self.subTest(name=name):
                text = f"path = /Users/{name}/Jarvis-Next/tools\n"  # gate-allow: absolute_user_path
                self.assertIn("machine_path_macos", rules(text))

    def test_linux_home_path_is_detected(self):
        self.assertIn("machine_path_linux", rules("dir = /home/someaccount/work\n"))  # gate-allow: absolute_user_path

    def test_windows_paths_are_detected(self):
        for text in (
            r"dir = C:\Users\someaccount\project",
            "dir = %USERPROFILE%\\project",
            r"share = \\host\Users\someaccount",
        ):
            with self.subTest(text=text):
                self.assertIn("machine_path_windows", rules(text + "\n"))

    def test_temporary_and_volume_paths_are_detected(self):
        for text in (
            "tmp = /private/var/folders/ab/cdef/T/scratch",
            "tmp = /tmp/session-cache",
            "vol = /Volumes/External/backup",
        ):
            with self.subTest(text=text):
                self.assertIn("machine_path_volume_or_temp", rules(text + "\n"))

    def test_file_uri_forms_are_detected(self):
        self.assertIn(
            "machine_path_macos", rules("uri = file:///Users/someaccount/x\n")  # gate-allow: absolute_user_path
        )
        self.assertIn(
            "machine_path_volume_or_temp", rules("uri = file:///Volumes/Ext/x\n")
        )

    def test_repository_relative_paths_are_valid(self):
        text = (
            "engine = tools/gates/cli.py\n"
            "runtime = .gate-runtime/results/block.phase.json\n"
            "root = $(git rev-parse --show-toplevel)\n"
        )
        self.assertEqual(rules(text), set())

    def test_the_project_dir_placeholder_is_valid(self):
        text = 'command = "$CLAUDE_PROJECT_DIR/.claude/hooks/pretooluse_guard.sh"\n'
        self.assertEqual(rules(text), set())


class TestRepositoryState(_support.TempEnvMixin):
    def test_the_repository_passes_the_hygiene_check(self):
        import io
        import json
        import os

        report = self.tmp_path / "hygiene.json"
        backup = os.environ.get("GATE_REPORT")
        os.environ["GATE_REPORT"] = str(report)
        cwd = Path.cwd()
        os.chdir(_support.REPO_ROOT)
        try:
            code = claude_hygiene.main([], )
        finally:
            os.chdir(cwd)
            if backup is None:
                os.environ.pop("GATE_REPORT", None)
            else:
                os.environ["GATE_REPORT"] = backup
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(code, 0, payload["failures"])
        self.assertEqual(payload["outcome"], "passed")
        del io

    def test_a_raw_log_in_the_index_is_reported(self):
        # The rule is evaluated on the path classification, not on content.
        from tools.gates import paths as gate_paths

        path = f"{gate_paths.RUNTIME_DIR_NAME}/raw-logs/run.log"
        self.assertTrue(path.startswith(f"{gate_paths.RUNTIME_DIR_NAME}/"))
        self.assertFalse(hygiene.released(path))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
