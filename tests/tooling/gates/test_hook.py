"""PreToolUse guard matrix.

Everything runs in throwaway temporary repositories and disposable worktrees;
no real Jarvis worktree is touched, and no destructive command is executed —
only the guard's decision is evaluated.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import hookguard  # noqa: E402
from tools.gates import paths as gate_paths  # noqa: E402

SETTINGS = _support.REPO_ROOT / ".claude" / "settings.json"

REQUIRED_DENY_RULES = (
    "Read(**/.env*)",
    "Bash(git push:*)",
    "Bash(git reset --hard:*)",
    "Bash(git rebase:*)",
    "Bash(git clean:*)",
    "Bash(git stash drop:*)",
    "Bash(rm -rf:*)",
)


class HookTestBase(_support.TempEnvMixin):
    def setUp(self):
        super().setUp()
        self.repo = _support.make_repo(self.tmp_path / "current")
        self.foreign = self.tmp_path / "foreign"
        _support.git(
            ["worktree", "add", "--quiet", "-b", "side", str(self.foreign)],
            cwd=self.repo,
        )

    def bash(self, command, cwd=None):
        return hookguard.decide(
            {
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(cwd or self.repo),
            }
        )

    def write(self, file_path, cwd=None, tool="Write"):
        return hookguard.decide(
            {
                "tool_name": tool,
                "tool_input": {"file_path": str(file_path)},
                "cwd": str(cwd or self.repo),
            }
        )

    def read(self, file_path, cwd=None):
        return hookguard.decide(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": str(file_path)},
                "cwd": str(cwd or self.repo),
            }
        )


class TestHardDenies(HookTestBase):
    def test_git_push_is_denied(self):
        decision, reason, _ = self.bash("git push origin tooling/gates-v1")
        self.assertEqual(decision, hookguard.DECISION_DENY)
        self.assertEqual(reason, "git_push")

    def test_git_reset_hard_is_denied(self):
        decision, reason, _ = self.bash("git reset --hard HEAD~1")
        self.assertEqual(decision, hookguard.DECISION_DENY)
        self.assertEqual(reason, "git_reset_hard")

    def test_git_rebase_is_denied(self):
        decision, reason, _ = self.bash("git rebase main")
        self.assertEqual(decision, hookguard.DECISION_DENY)
        self.assertEqual(reason, "git_rebase")

    def test_git_clean_is_denied(self):
        decision, reason, _ = self.bash("git clean -fd")
        self.assertEqual(decision, hookguard.DECISION_DENY)
        self.assertEqual(reason, "git_clean")

    def test_git_stash_drop_is_denied(self):
        decision, reason, _ = self.bash("git stash drop stash@{0}")
        self.assertEqual(decision, hookguard.DECISION_DENY)
        self.assertEqual(reason, "git_stash_drop")

    def test_recursive_rm_is_denied(self):
        for command in ("rm -rf build", "rm -fr build", "rm -r -f build"):
            with self.subTest(command=command):
                decision, reason, _ = self.bash(command)
                self.assertEqual(decision, hookguard.DECISION_DENY)
                self.assertEqual(reason, "rm_rf")

    def test_reading_an_env_file_is_denied(self):
        for name in (".env", ".env.local", "config/.env.production"):
            with self.subTest(name=name):
                decision, reason, _ = self.read(self.repo / name)
                self.assertEqual(decision, hookguard.DECISION_DENY)
                self.assertEqual(reason, "env_file_access")

    def test_reading_an_env_file_through_bash_is_denied(self):
        decision, reason, _ = self.bash("cat .env.local")
        self.assertEqual(decision, hookguard.DECISION_DENY)
        self.assertEqual(reason, "env_file_access")

    def test_writing_an_env_file_is_denied(self):
        decision, reason, _ = self.write(self.repo / ".env")
        self.assertEqual(decision, hookguard.DECISION_DENY)
        self.assertEqual(reason, "env_file_access")

    def test_hard_denies_are_never_downgraded_to_ask(self):
        # Even a foreign worktree target keeps the hard deny.
        decision, reason, _ = self.bash(f"rm -rf {self.foreign}/src")
        self.assertEqual(decision, hookguard.DECISION_DENY)
        self.assertEqual(reason, "rm_rf")
        decision, reason, _ = self.bash(f"git -C {self.foreign} push origin side")
        self.assertEqual(decision, hookguard.DECISION_DENY)
        self.assertEqual(reason, "git_push")

    def test_settings_keep_the_existing_deny_list(self):
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        deny = settings["permissions"]["deny"]
        for rule in REQUIRED_DENY_RULES:
            self.assertIn(rule, deny)

    def test_settings_register_the_pretooluse_hook(self):
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        groups = settings["hooks"]["PreToolUse"]
        commands = [
            hook["command"]
            for group in groups
            for hook in group["hooks"]
            if hook["type"] == "command"
        ]
        self.assertTrue(commands)
        for command in commands:
            relative = command.replace("$CLAUDE_PROJECT_DIR/", "")
            self.assertTrue((_support.REPO_ROOT / relative).is_file())

    def test_guard_rules_and_settings_deny_list_stay_in_sync(self):
        # Counter test for rule change RC-001: the B0a-1 deny set must remain
        # complete. The set may grow — it may never shrink.
        codes = {code for code, _ in hookguard.HARD_DENY_COMMAND_RULES}
        self.assertTrue(
            {
                "git_push",
                "git_reset_hard",
                "git_rebase",
                "git_clean",
                "git_stash_drop",
                "rm_rf",
            }.issubset(codes)
        )

    def test_commit_amend_is_a_hard_deny(self):
        # Sharpening test for rule change RC-001.
        self.assertIn(
            "git_commit_amend",
            {code for code, _ in hookguard.HARD_DENY_COMMAND_RULES},
        )
        decision, reason, _ = self.bash("git commit --am" "end")
        self.assertEqual(decision, hookguard.DECISION_DENY)
        self.assertEqual(reason, "git_commit_amend")


class TestWorktreeProtection(HookTestBase):
    def test_target_in_the_current_worktree_is_allowed(self):
        decision, reason, _ = self.write(self.repo / "notes.md")
        self.assertEqual(decision, hookguard.DECISION_ALLOW)
        self.assertEqual(reason, "current_worktree_mutation")

    def test_normalised_equivalent_path_is_allowed(self):
        decision, _, record = self.write(
            self.repo / "sub" / ".." / "./notes.md"
        )
        self.assertEqual(decision, hookguard.DECISION_ALLOW)
        self.assertTrue(record["canonical_target"].endswith("/notes.md"))
        self.assertNotIn("..", record["canonical_target"])

    def test_relative_target_is_allowed(self):
        decision, _, _ = self.write("notes.md")
        self.assertEqual(decision, hookguard.DECISION_ALLOW)

    def test_direct_foreign_worktree_path_asks(self):
        decision, reason, record = self.write(self.foreign / "notes.md")
        self.assertEqual(decision, hookguard.DECISION_ASK)
        self.assertEqual(reason, "foreign_worktree_mutation")
        self.assertEqual(record["foreign_worktree"], str(self.foreign.resolve()))

    def test_foreign_worktree_through_dot_dot_asks(self):
        decision, reason, _ = self.write("../foreign/notes.md")
        self.assertEqual(decision, hookguard.DECISION_ASK)
        self.assertEqual(reason, "foreign_worktree_mutation")

    def test_foreign_worktree_through_a_symlink_asks(self):
        link = self.repo / "link-to-foreign"
        link.symlink_to(self.foreign)
        decision, reason, _ = self.write(link / "notes.md")
        self.assertEqual(decision, hookguard.DECISION_ASK)
        self.assertEqual(reason, "foreign_worktree_mutation")

    def test_not_yet_existing_foreign_target_asks(self):
        decision, reason, _ = self.write(self.foreign / "deep" / "new" / "file.md")
        self.assertEqual(decision, hookguard.DECISION_ASK)
        self.assertEqual(reason, "foreign_worktree_mutation")

    def test_mutating_bash_into_a_foreign_worktree_asks(self):
        decision, reason, _ = self.bash(f"touch {self.foreign}/notes.md")
        self.assertEqual(decision, hookguard.DECISION_ASK)
        self.assertEqual(reason, "foreign_worktree_mutation")

    def test_git_c_into_a_foreign_worktree_asks(self):
        decision, reason, _ = self.bash(f"git -C {self.foreign} add -A")
        self.assertEqual(decision, hookguard.DECISION_ASK)
        self.assertEqual(reason, "foreign_worktree_mutation")

    def test_ambiguous_mutating_command_asks(self):
        decision, reason, _ = self.bash("touch a.txt && mv a.txt $TARGET/b.txt")
        self.assertEqual(decision, hookguard.DECISION_ASK)
        self.assertEqual(reason, "ambiguous_mutating_command")

    def test_non_mutating_command_is_left_to_the_normal_rules(self):
        decision, reason, _ = self.bash("git status --short")
        self.assertIsNone(decision)
        self.assertEqual(reason, "non_mutating")

    def test_undetermined_worktree_blocks(self):
        # Sharpening test for rule change RC-002: an undeterminable repository
        # state used to escalate to ask; a mutating request now blocks.
        decision, reason, _ = self.write(
            self.tmp_path / "loose.txt", cwd=self.tmp_path
        )
        self.assertEqual(decision, hookguard.DECISION_DENY)
        self.assertEqual(reason, "worktree_undetermined")

    def test_undetermined_worktree_is_still_detected(self):
        # Counter test for rule change RC-002: the condition itself must still
        # be recognised, not silently dropped.
        _decision, reason, _ = self.write(
            self.tmp_path / "loose.txt", cwd=self.tmp_path
        )
        self.assertEqual(reason, "worktree_undetermined")

    def test_canonicalisation_handles_missing_parents(self):
        canonical = hookguard.canonicalize("a/../b/c/d.txt", self.repo)
        self.assertTrue(str(canonical).endswith("/b/c/d.txt"))
        self.assertNotIn("..", str(canonical))


class TestAskLogging(HookTestBase):
    def test_ask_is_recorded_with_the_observable_request(self):
        decision, reason, record = self.write(self.foreign / "notes.md")
        target = hookguard.log_decision(
            decision, reason, record, worktree=self.repo
        )
        self.assertIsNotNone(target)
        entry = json.loads(target.read_text(encoding="utf-8").splitlines()[-1])
        for field in (
            "timestamp",
            "current_worktree",
            "tool",
            "original_target",
            "canonical_target",
            "foreign_worktree",
            "decision",
            "reason_code",
        ):
            self.assertIn(field, entry)
        self.assertEqual(entry["decision"], hookguard.DECISION_ASK)
        self.assertEqual(entry["reason_code"], "foreign_worktree_mutation")
        self.assertEqual(entry["tool"], "Write")

    def test_detail_log_lives_in_the_gitignored_runtime_area(self):
        decision, reason, record = self.write(self.foreign / "notes.md")
        target = hookguard.log_decision(decision, reason, record, worktree=self.repo)
        self.assertTrue(
            str(target).startswith(str(gate_paths.hook_log_dir(self.repo)))
        )
        self.assertTrue(str(target).startswith(str(self.runtime_dir)))

    def test_sanitized_summary_contains_no_path(self):
        decision, reason, record = self.write(self.foreign / "notes.md")
        hookguard.log_decision(decision, reason, record, worktree=self.repo)
        summary = json.loads(
            (gate_paths.hook_log_dir(self.repo) / "summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(summary, {"ask.foreign_worktree_mutation": 1})

    def test_only_the_observed_decision_is_recorded(self):
        decision, reason, record = self.bash("git push origin main")
        hookguard.log_decision(decision, reason, record, worktree=self.repo)
        summary = json.loads(
            (gate_paths.hook_log_dir(self.repo) / "summary.json").read_text(
                encoding="utf-8"
            )
        )
        # No approval is invented: only the deny the hook actually observed.
        self.assertEqual(summary, {"deny.git_push": 1})

    def test_hook_entry_point_emits_the_installed_response_schema(self):
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(self.foreign / "notes.md")},
            "cwd": str(self.repo),
        }
        stdout = io.StringIO()
        code = hookguard.main(stdin=io.StringIO(json.dumps(payload)), stdout=stdout)
        self.assertEqual(code, 0)
        response = json.loads(stdout.getvalue())
        specific = response["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "PreToolUse")
        self.assertEqual(specific["permissionDecision"], "ask")
        self.assertIn("permissionDecisionReason", specific)

    def test_hook_entry_point_states_that_it_has_no_opinion(self):
        # Sharpening test for rule change RC-003: silence and a crashed guard
        # are indistinguishable, so abstention is now stated positively and
        # the wrapper blocks on anything else.
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git status --short"},
            "cwd": str(self.repo),
        }
        stdout = io.StringIO()
        code = hookguard.main(stdin=io.StringIO(json.dumps(payload)), stdout=stdout)
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()), {"guardOutcome": "no_opinion"}
        )

    def test_no_opinion_carries_no_permission_decision(self):
        # Counter test for rule change RC-003: abstention must never look like
        # a permission decision.
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git status --short"},
            "cwd": str(self.repo),
        }
        stdout = io.StringIO()
        hookguard.main(stdin=io.StringIO(json.dumps(payload)), stdout=stdout)
        self.assertNotIn("permissionDecision", stdout.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
