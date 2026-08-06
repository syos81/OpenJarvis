"""Argument based parsing: wrappers, operators, git options, aliases."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.guard import _support  # noqa: E402
from tools.guard import cmdparse  # noqa: E402
from tools.guard import rules as guard_rules  # noqa: E402

AMEND = "--am" + "end"
RULES = guard_rules.load_rules(_support.GUARD_SOURCE / "rules.json")


class TestSegments(unittest.TestCase):
    def test_operators_split_segments(self):
        parsed = cmdparse.segments("git add -A && git commit -m x ; ls")
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0][0][:2], ["git", "add"])
        self.assertEqual(parsed[2][0], ["ls"])

    def test_subshell_is_a_segment(self):
        parsed = cmdparse.segments("(git commit " + AMEND + ")")
        self.assertEqual(parsed[0][0], ["git", "commit", AMEND])

    def test_redirection_marks_the_segment(self):
        parsed = cmdparse.segments("printf x > out.txt")
        self.assertTrue(parsed[0][1])

    def test_unbalanced_quotes_are_unparseable(self):
        with self.assertRaises(cmdparse.UnparseableCommand):
            cmdparse.segments("echo 'unterminated")

    def test_heredoc_body_is_not_tokenised_as_a_command(self):
        command = "cat <<'DOC'\ngit commit " + AMEND + "\nDOC\n"
        parsed = cmdparse.segments(command)
        heads = [segment[0][0] for segment in parsed if segment[0]]
        self.assertEqual(heads, ["cat"])

    def test_opaque_expansion_is_visible(self):
        self.assertTrue(cmdparse.has_opaque_expansion("git $(printf commit)"))
        self.assertFalse(cmdparse.has_opaque_expansion("git commit -m x"))


class TestPrefixes(unittest.TestCase):
    def test_environment_assignments_are_stripped(self):
        tokens, elevated = cmdparse.strip_prefixes(
            ["FOO=1", "BAR=2", "git", "status"], RULES.wrappers
        )
        self.assertEqual(tokens[0], "git")
        self.assertFalse(elevated)

    def test_env_wrapper_is_stripped(self):
        tokens, _ = cmdparse.strip_prefixes(
            ["env", "GIT_EDITOR=true", "git", "commit"], RULES.wrappers
        )
        self.assertEqual(tokens[:2], ["git", "commit"])

    def test_privilege_wrapper_is_reported(self):
        tokens, elevated = cmdparse.strip_prefixes(
            ["sudo", "git", "status"], RULES.wrappers
        )
        self.assertEqual(tokens[0], "git")
        self.assertTrue(elevated)


class TestGitParsing(unittest.TestCase):
    def test_dash_c_directory_is_extracted(self):
        git = cmdparse.parse_git(["git", "-C", "/tmp/other", "commit", AMEND])
        self.assertEqual(git.subcommand, "commit")
        self.assertEqual(git.directories, ["/tmp/other"])
        self.assertTrue(git.has_option(AMEND))

    def test_git_dir_option_is_extracted(self):
        git = cmdparse.parse_git(
            ["git", "--git-dir=/tmp/other/.git", "commit", AMEND]
        )
        self.assertEqual(git.directories, ["/tmp/other/.git"])

    def test_option_with_attached_value_still_matches(self):
        git = cmdparse.parse_git(["git", "commit", AMEND + "=yes"])
        self.assertTrue(git.has_option(AMEND))

    def test_missing_subcommand_is_unparseable(self):
        with self.assertRaises(cmdparse.UnparseableCommand):
            cmdparse.parse_git(["git", "-C"])

    def test_opaque_subcommand_is_unparseable(self):
        with self.assertRaises(cmdparse.UnparseableCommand):
            cmdparse.parse_git(["git", "$SUB", AMEND])


class TestAliasResolution(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = _support.tempfile.TemporaryDirectory(prefix="guard-alias-")
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        for args in (
            ["init", "--quiet", "-b", "main"],
            ["config", "user.email", "guard-tests@example.invalid"],
            ["config", "user.name", "Guard Tests"],
        ):
            subprocess.run(  # noqa: S603 - fixed argv
                ["git"] + args, cwd=str(self.repo), check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    def _alias(self, name, value):
        subprocess.run(  # noqa: S603 - fixed argv
            ["git", "config", "alias." + name, value],
            cwd=str(self.repo),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def test_alias_to_a_forbidden_operation_is_detected(self):
        self._alias("fixup", "commit " + AMEND + " --no-edit")
        code, layer = guard_rules.evaluate_command(
            RULES, "git fixup", cwd=str(self.repo)
        )
        self.assertEqual(code, "git_commit_amend")
        self.assertEqual(layer, "argv")

    def test_shell_alias_is_unparseable_and_blocks(self):
        self._alias("danger", "!git commit " + AMEND)
        code, layer = guard_rules.evaluate_command(
            RULES, "git danger", cwd=str(self.repo)
        )
        self.assertIn(layer, ("backstop", "unparseable"))
        self.assertIsNotNone(code or layer == "unparseable")

    def test_harmless_alias_stays_harmless(self):
        self._alias("st", "status --short")
        code, _layer = guard_rules.evaluate_command(
            RULES, "git st", cwd=str(self.repo)
        )
        self.assertIsNone(code)


class TestTargets(unittest.TestCase):
    def test_wrapped_mutation_still_exposes_its_target(self):
        # Sharpening test for rule change RC-004.
        targets, _ambiguous, mutating = guard_rules.command_targets(
            RULES, "env FOO=1 touch /tmp/other/notes.md"
        )
        self.assertTrue(mutating)
        self.assertIn("/tmp/other/notes.md", targets)

    def test_chained_segment_target_is_seen(self):
        targets, ambiguous, mutating = guard_rules.command_targets(
            RULES, "ls -la && mv a/b.txt /tmp/other/b.txt"
        )
        self.assertTrue(mutating)
        self.assertTrue(ambiguous)
        self.assertIn("/tmp/other/b.txt", targets)

    def test_git_c_directory_is_a_target(self):
        targets, _ambiguous, mutating = guard_rules.command_targets(
            RULES, "git -C /tmp/other add -A"
        )
        self.assertTrue(mutating)
        self.assertIn("/tmp/other", targets)

    def test_read_only_command_is_not_mutating(self):
        _targets, _ambiguous, mutating = guard_rules.command_targets(
            RULES, "git status --short"
        )
        self.assertFalse(mutating)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
