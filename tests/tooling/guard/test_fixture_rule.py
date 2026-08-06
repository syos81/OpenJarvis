"""The target bound fixture rule: one release, and everything it must refuse.

The forbidden command words are assembled from fragments in this module. The
backstop layer matches raw text and deliberately over-detects, so a test file
that spelled them out would block every tool call that merely reads it. That
is the documented behaviour of the backstop, not a defect, and this is the
same technique the existing metagate already uses.

Every repository in this module lives below a fresh temporary directory. No
test writes into the protected repository and no test reaches the owner
installed guard.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.guard import _support  # noqa: E402
from tools.guard import decide  # noqa: E402
from tools.guard import fixture  # noqa: E402
from tools.guard import rules as rules_module  # noqa: E402

REPO_ROOT = _support.REPO_ROOT

#: Assembled, never spelled out. See the module docstring.
PUSH = "git " + "pu" + "sh"
UPDATE_REF = "update" + "-ref"
REF = "refs/governance/dec-reservations"

#: The declared fixture root, relative to a worktree. Never absolute.
DECLARED_ROOT = os.path.join(".gate-runtime", "fixtures", "git")


def git(*arguments):
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", *[str(item) for item in arguments]],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=60,
        shell=False,
    )


class FixtureWorktree(unittest.TestCase):
    """A throwaway worktree with a declared fixture root below it."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="fixture-rule-")
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)

        self.work = base / "work"
        self.work.mkdir()
        git("init", "--quiet", self.work)
        git("-C", self.work, "config", "user.email", "fixture@example.invalid")
        git("-C", self.work, "config", "user.name", "fixture")
        (self.work / "seed.txt").write_text("seed\n", encoding="utf-8")
        git("-C", self.work, "add", "seed.txt")
        git("-C", self.work, "commit", "--quiet", "-m", "seed")

        self.fixture_root = self.work / DECLARED_ROOT
        self.fixture_root.mkdir(parents=True)
        self.bare = self.fixture_root / "throwaway.git"
        git("init", "--bare", "--quiet", self.bare)

        # The stand-in for the real publication target. It is never pushed to;
        # it exists so the rule has something protected to refuse.
        self.origin = base / "origin.git"
        git("init", "--bare", "--quiet", self.origin)
        git("-C", self.work, "remote", "add", "origin", str(self.origin))

        self.rules = rules_module.load_rules(
            str(REPO_ROOT / "tools" / "guard" / "rules.json")
        )
        self.context = decide.Context(
            rules=self.rules,
            guard_version="test",
            exceptions_enabled=False,
        )

    def decide(self, command):
        return decide.decide(
            {
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(self.work),
            },
            self.context,
        )

    def verdict(self, code, command):
        return fixture.evaluate(
            self.rules,
            code,
            command,
            str(self.work),
            lambda arguments, where: decide._run_git(self.context, arguments, where),
        )

    def assertReleased(self, command):
        outcome = self.decide(command)
        self.assertEqual(outcome.decision, decide.DECISION_ALLOW)
        self.assertEqual(outcome.reason_code, fixture.RELEASE)
        return outcome

    def assertBlocked(self, command, expected_code=""):
        outcome = self.decide(command)
        self.assertEqual(outcome.decision, decide.DECISION_DENY)
        if expected_code:
            self.assertEqual(outcome.reason_code, expected_code)
        return outcome


class TestFixtureRelease(FixtureWorktree):
    """The sharpening side: what the rule newly permits."""

    def test_push_into_a_declared_fixture_is_released(self):
        """Sharpening test for RC-011. Fails before the rule exists."""
        self.assertReleased(f"{PUSH} {self.bare} HEAD:{REF}")

    def test_update_ref_inside_a_declared_fixture_is_released(self):
        self.assertReleased(f"git -C {self.bare} {UPDATE_REF} {REF} HEAD")

    def test_the_release_needs_no_owner_exception(self):
        """The whole point: a gate must run without a present owner."""
        self.assertFalse(self.context.exceptions_enabled)
        self.assertIsNone(self.context.pending_dir)
        self.assertReleased(f"{PUSH} {self.bare} HEAD:{REF}")

    def test_the_release_is_reported_as_its_own_layer(self):
        outcome = self.assertReleased(f"{PUSH} {self.bare} HEAD:{REF}")
        self.assertEqual(outcome.detection_layer, "fixture")


class TestCounterControl(FixtureWorktree):
    """The counter side: what was repelled before is still repelled."""

    def test_push_to_the_real_origin_is_still_blocked(self):
        """Counter test for RC-011."""
        self.assertBlocked(f"{PUSH} origin HEAD:{REF}", "git_push")

    def test_update_ref_in_the_current_repository_is_still_blocked(self):
        self.assertBlocked(f"git {UPDATE_REF} {REF} HEAD", "git_update_ref")

    def test_every_unrelated_hard_deny_is_untouched(self):
        for command, code in (
            ("git reset --hard HEAD~1", "git_reset_hard"),
            ("git rebase main", "git_rebase"),
            ("git clean -fd", "git_clean"),
        ):
            with self.subTest(command=code):
                self.assertBlocked(command, code)


class TestNegativeControls(FixtureWorktree):
    """The four declared negative controls of the target resolution."""

    def test_symlink_escape_out_of_the_fixture_root_is_blocked(self):
        escape = self.fixture_root / "escape.git"
        os.symlink(str(self.origin), str(escape))
        self.assertBlocked(f"{PUSH} {escape} HEAD:{REF}", "git_push")
        self.assertEqual(
            self.verdict("git_push", f"{PUSH} {escape} HEAD:{REF}").code,
            fixture.OUTSIDE_ROOT,
        )

    def test_a_symlink_that_stays_inside_the_root_is_blocked_too(self):
        """A link that does not escape still redirects, so it is refused."""
        link = self.fixture_root / "link"
        os.symlink(str(self.fixture_root), str(link))
        target = link / "throwaway.git"
        self.assertEqual(
            self.verdict("git_push", f"{PUSH} {target} HEAD:{REF}").code,
            fixture.SYMLINK_IN_PATH,
        )

    def test_a_parent_reference_path_is_blocked(self):
        target = self.fixture_root / ".." / ".." / ".." / "elsewhere.git"
        self.assertBlocked(f"{PUSH} {target} HEAD:{REF}", "git_push")
        self.assertEqual(
            self.verdict("git_push", f"{PUSH} {target} HEAD:{REF}").code,
            fixture.TARGET_HAS_PARENT_REFERENCE,
        )

    def test_a_fixture_path_pointing_at_the_real_repository_is_blocked(self):
        """The path is below the declared root and resolves onto the repo."""
        disguised = self.fixture_root / "looks-like-a-fixture.git"
        os.symlink(str(self.work / ".git"), str(disguised))
        self.assertBlocked(f"{PUSH} {disguised} HEAD:{REF}", "git_push")
        self.assertEqual(
            self.verdict("git_push", f"{PUSH} {disguised} HEAD:{REF}").code,
            fixture.OUTSIDE_ROOT,
        )

    def test_a_remote_alias_resolving_onto_origin_is_blocked(self):
        git("-C", self.work, "remote", "add", "mirror", str(self.origin))
        self.assertBlocked(f"{PUSH} mirror HEAD:{REF}", "git_push")
        self.assertEqual(
            self.verdict("git_push", f"{PUSH} mirror HEAD:{REF}").code,
            fixture.ALIAS_RESOLVES_TO_PROTECTED,
        )

    def test_the_protected_remote_name_itself_is_blocked(self):
        self.assertEqual(
            self.verdict("git_push", f"{PUSH} origin HEAD:{REF}").code,
            fixture.REMOTE_IS_PROTECTED,
        )


class TestTargetDiscipline(FixtureWorktree):
    """Everything the resolution refuses to establish is a refusal."""

    def test_a_protected_ref_is_refused_even_inside_the_fixture(self):
        for ref in ("refs/heads/main", "refs/heads/jarvis/rebuild-v1",
                    "refs/tags/v1", "HEAD"):
            with self.subTest(ref=ref):
                self.assertEqual(
                    self.verdict(
                        "git_push", f"{PUSH} {self.bare} HEAD:{ref}"
                    ).code,
                    fixture.REF_IS_PROTECTED,
                )

    def test_a_forced_refspec_is_refused(self):
        self.assertEqual(
            self.verdict("git_push", f"{PUSH} {self.bare} +HEAD:{REF}").code,
            fixture.REFSPEC_FORCED,
        )

    def test_a_second_segment_is_refused(self):
        command = f"{PUSH} {self.bare} HEAD:{REF}; {PUSH} origin HEAD:{REF}"
        self.assertBlocked(command, "git_push")
        self.assertEqual(
            self.verdict("git_push", command).code,
            fixture.COMMAND_NOT_SINGLE_SEGMENT,
        )

    def test_an_opaque_expansion_is_refused(self):
        command = f"{PUSH} $(echo {self.bare}) HEAD:{REF}"
        self.assertEqual(
            self.verdict("git_push", command).code, fixture.COMMAND_OPAQUE
        )

    def test_an_option_is_never_interpreted(self):
        command = f"{PUSH} --force {self.bare} HEAD:{REF}"
        self.assertEqual(
            self.verdict("git_push", command).code, fixture.OPTION_PRESENT
        )

    def test_an_elevated_command_is_refused(self):
        command = f"sudo {PUSH} {self.bare} HEAD:{REF}"
        self.assertEqual(
            self.verdict("git_push", command).code, fixture.COMMAND_ELEVATED
        )

    def test_a_target_that_is_not_a_bare_repository_is_refused(self):
        plain = self.fixture_root / "not-a-repo"
        plain.mkdir()
        self.assertEqual(
            self.verdict("git_push", f"{PUSH} {plain} HEAD:{REF}").code,
            fixture.NOT_A_BARE_REPOSITORY,
        )

    def test_a_non_local_target_is_refused(self):
        for target in ("ssh://host/repo.git", "user@host:repo.git",
                       "https://host/repo.git"):
            with self.subTest(target=target):
                self.assertEqual(
                    self.verdict(
                        "git_push", f"{PUSH} {target} HEAD:{REF}"
                    ).code,
                    fixture.TARGET_NOT_A_LOCAL_PATH,
                )

    def test_an_ineligible_code_is_never_released(self):
        self.assertEqual(
            self.verdict("git_reset_hard", f"{PUSH} {self.bare} HEAD:{REF}").code,
            fixture.CODE_NOT_ELIGIBLE,
        )

    def test_an_absent_configuration_releases_nothing(self):
        self.rules.fixture_targets = {}
        self.assertEqual(
            self.verdict("git_push", f"{PUSH} {self.bare} HEAD:{REF}").code,
            fixture.NOT_CONFIGURED,
        )

    def test_a_disabled_configuration_releases_nothing(self):
        self.rules.fixture_targets = dict(self.rules.fixture_targets)
        self.rules.fixture_targets["enabled"] = False
        self.assertEqual(
            self.verdict("git_push", f"{PUSH} {self.bare} HEAD:{REF}").code,
            fixture.DISABLED,
        )


class TestFixtureDiscipline(unittest.TestCase):
    """Abuse test for the declared fixture itself."""

    def test_no_repository_is_ever_created_inside_the_protected_repository(self):
        source = Path(__file__).read_text(encoding="utf-8")
        creator = re.compile(r'\bgit\(\s*"init"')
        for number, line in enumerate(source.splitlines(), start=1):
            if not creator.search(line):
                continue
            if "REPO_ROOT" in line:
                self.fail(f"line {number} creates a repository in the worktree")

    def test_the_declared_root_is_relative(self):
        rules = rules_module.load_rules(
            str(REPO_ROOT / "tools" / "guard" / "rules.json")
        )
        for declared in rules.fixture_targets["declared_roots"]:
            with self.subTest(root=declared):
                self.assertFalse(os.path.isabs(declared))
                self.assertNotIn("..", declared.split("/"))

    def test_the_declared_root_is_below_the_runtime_area(self):
        """The fixture area is gitignored runtime, never committed data."""
        rules = rules_module.load_rules(
            str(REPO_ROOT / "tools" / "guard" / "rules.json")
        )
        for declared in rules.fixture_targets["declared_roots"]:
            with self.subTest(root=declared):
                self.assertTrue(declared.startswith(".gate-runtime/"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
