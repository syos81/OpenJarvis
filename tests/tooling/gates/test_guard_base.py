"""Mechanical guard base derivation and the full examined range (B0a-2 §0).

All topology fixtures are throwaway temporary repositories. No real Jarvis
worktree is touched.
"""

from __future__ import annotations

import inspect
import io
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import cli as cli_module  # noqa: E402
from tools.gates import gitutil  # noqa: E402
from tools.gates import guardbase  # noqa: E402
from tools.gates import statuses  # noqa: E402
from tools.gates.runners import repo_guard  # noqa: E402

CANONICAL = "line-canonical"
CALENDAR = "line-calendar"


class TopologyMixin(_support.TempEnvMixin):
    """Builds the three-line topology the derivation expects."""

    def setUp(self):
        super().setUp()
        self.repo = _support.make_repo(
            self.tmp_path / "lines", files={"product/core.py": "value = 1\n"}
        )
        self.base_oid = gitutil.head_commit(cwd=self.repo)
        self._branch_with_commit(CANONICAL, "canonical.md", "canonical line\n")
        self._branch_with_commit(CALENDAR, "calendar.md", "calendar line\n")
        _support.git(["checkout", "--quiet", "main"], cwd=self.repo)
        self._commit_file("tooling.md", "tooling work\n", "tooling commit")
        self.head_oid = gitutil.head_commit(cwd=self.repo)

    def _commit_file(self, name, content, message):
        target = self.repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        _support.git(["add", "-A"], cwd=self.repo)
        _support.git(["commit", "--quiet", "-m", message], cwd=self.repo)
        return gitutil.head_commit(cwd=self.repo)

    def _branch_with_commit(self, branch, name, content):
        _support.git(["checkout", "--quiet", "-b", branch, self.base_oid], cwd=self.repo)
        oid = self._commit_file(name, content, f"{branch} commit")
        _support.git(["checkout", "--quiet", "main"], cwd=self.repo)
        return oid

    def derive(self, **overrides):
        options = {
            "canonical_line": CANONICAL,
            "calendar_line": CALENDAR,
            "origin_rev": self.base_oid,
        }
        options.update(overrides)
        return guardbase.derive(self.repo, **options)


class TestGuardBaseDerivation(TopologyMixin):
    def test_base_is_derived_from_the_merge_base(self):
        derivation = self.derive()
        self.assertEqual(derivation["base_commit"], self.base_oid)
        self.assertEqual(derivation["derivation"], "git_merge_base_all")
        self.assertEqual(derivation["head_commit"], self.head_oid)

    def test_derivation_fails_when_the_origin_line_moved(self):
        # A later commit on both lines shifts the merge base away from the
        # owner verified origin.
        _support.git(["checkout", "--quiet", CANONICAL], cwd=self.repo)
        moved = self._commit_file("shared.md", "shared\n", "shared commit")
        _support.git(["checkout", "--quiet", CALENDAR], cwd=self.repo)
        _support.git(["merge", "--quiet", "--no-edit", moved], cwd=self.repo)
        _support.git(["checkout", "--quiet", "main"], cwd=self.repo)
        with self.assertRaises(guardbase.GuardBaseError) as ctx:
            self.derive()
        self.assertEqual(ctx.exception.reason_code, "guard_base_origin_mismatch")

    def test_missing_merge_base_fails_closed(self):
        unrelated = _support.make_repo(self.tmp_path / "unrelated")
        _support.git(
            ["remote", "add", "unrelated", str(unrelated)], cwd=self.repo
        )
        _support.git(["fetch", "--quiet", "unrelated"], cwd=self.repo)
        _support.git(
            ["branch", "orphan-line", "unrelated/main"], cwd=self.repo, check=False
        )
        with self.assertRaises(guardbase.GuardBaseError) as ctx:
            self.derive(calendar_line="orphan-line")
        self.assertEqual(ctx.exception.reason_code, "guard_base_merge_base_missing")

    def test_ambiguous_merge_base_fails_closed(self):
        # Criss-cross merges produce two merge bases.
        _support.git(["checkout", "--quiet", "-b", "cross-x", self.base_oid], cwd=self.repo)
        x = self._commit_file("x.md", "x\n", "x")
        _support.git(["checkout", "--quiet", "-b", "cross-y", self.base_oid], cwd=self.repo)
        y = self._commit_file("y.md", "y\n", "y")
        _support.git(["checkout", "--quiet", "-b", "cross-a", x], cwd=self.repo)
        _support.git(["merge", "--quiet", "--no-edit", y], cwd=self.repo)
        _support.git(["checkout", "--quiet", "-b", "cross-b", y], cwd=self.repo)
        _support.git(["merge", "--quiet", "--no-edit", x], cwd=self.repo)
        _support.git(["checkout", "--quiet", "main"], cwd=self.repo)
        with self.assertRaises(guardbase.GuardBaseError) as ctx:
            self.derive(canonical_line="cross-a", calendar_line="cross-b")
        self.assertEqual(ctx.exception.reason_code, "guard_base_merge_base_ambiguous")

    def test_unresolvable_reference_fails_closed(self):
        with self.assertRaises(guardbase.GuardBaseError) as ctx:
            self.derive(canonical_line="line-does-not-exist")
        self.assertEqual(ctx.exception.reason_code, "guard_base_reference_unresolved")

    def test_unresolvable_origin_fails_closed(self):
        with self.assertRaises(guardbase.GuardBaseError) as ctx:
            self.derive(origin_rev="0" * 40)
        self.assertEqual(ctx.exception.reason_code, "guard_base_origin_unresolved")

    def test_head_that_does_not_descend_from_the_origin_fails(self):
        unrelated = _support.make_repo(self.tmp_path / "detached-head")
        with self.assertRaises(guardbase.GuardBaseError) as ctx:
            guardbase.derive(
                unrelated,
                canonical_line="main",
                calendar_line="main",
                origin_rev=gitutil.head_commit(cwd=self.repo),
            )
        self.assertIn(
            ctx.exception.reason_code,
            ("guard_base_origin_unresolved", "guard_base_origin_mismatch"),
        )


class TestDeclaredBaseIsOnlyValidated(TopologyMixin):
    def test_correct_full_declaration_is_accepted(self):
        status, reason = guardbase.validate_declared_base(self.base_oid, self.base_oid)
        self.assertEqual(status, statuses.PASS)
        self.assertEqual(reason, "declared_guard_base_matches_derivation")

    def test_later_existing_commit_is_rejected(self):
        status, reason = guardbase.validate_declared_base(self.head_oid, self.base_oid)
        self.assertEqual(status, statuses.FAIL)
        self.assertEqual(reason, "declared_guard_base_mismatch")

    def test_foreign_or_nonexistent_commit_is_rejected(self):
        for declared in ("f" * 40, "0" * 40):
            with self.subTest(declared=declared):
                status, reason = guardbase.validate_declared_base(
                    declared, self.base_oid
                )
                self.assertEqual(status, statuses.FAIL)
                self.assertEqual(reason, "declared_guard_base_mismatch")

    def test_abbreviated_declaration_is_rejected(self):
        status, reason = guardbase.validate_declared_base(
            self.base_oid[:7], self.base_oid
        )
        self.assertEqual(status, statuses.FAIL)
        self.assertEqual(reason, "declared_guard_base_not_full_oid")

    def test_missing_declaration_is_rejected(self):
        for declared in (None, ""):
            with self.subTest(declared=declared):
                status, reason = guardbase.validate_declared_base(
                    declared, self.base_oid
                )
                self.assertEqual(status, statuses.FAIL)
                self.assertEqual(reason, "declared_guard_base_missing")

    def test_declaration_never_feeds_the_derivation(self):
        # derive() has no parameter through which a base could be supplied.
        parameters = set(inspect.signature(guardbase.derive).parameters)
        self.assertEqual(
            parameters, {"worktree", "canonical_line", "calendar_line", "origin_rev"}
        )
        self.assertEqual(
            set(inspect.signature(guardbase.derive_for_repository).parameters),
            {"worktree"},
        )
        source = inspect.getsource(repo_guard.check_product_changes)
        self.assertIn("guardbase.derive_for_repository(root)", source)
        self.assertNotIn("block_base_commit\"])", source)


class TestNoRuntimeOverride(TopologyMixin):
    def test_environment_variables_cannot_move_the_base(self):
        expected = self.derive()["base_commit"]
        for name in (
            "GATE_GUARD_BASE",
            "GATE_BASE_COMMIT",
            "GATE_PRODUCT_GUARD_BASE",
            "BLOCK_BASE_COMMIT",
        ):
            os.environ[name] = self.head_oid
            self.addCleanup(os.environ.pop, name, None)
        self.assertEqual(self.derive()["base_commit"], expected)

    def test_the_cli_offers_no_base_parameter(self):
        with self.assertRaises(cli_module.UsageError) as ctx:
            cli_module.parse_args(
                ["--block", "b0a-2-governance", "--phase", "preflight", "--base", "x"]
            )
        self.assertEqual(ctx.exception.reason_code, "unknown_parameter")

    def test_production_derivation_takes_the_frozen_constants(self):
        self.assertEqual(guardbase.CANONICAL_LINE, "jarvis/rebuild-v1")
        self.assertEqual(
            guardbase.CALENDAR_LINE, "spike/calendar-foundation-intel-2026-08-04"
        )
        self.assertEqual(guardbase.TOOLING_BRANCH, "tooling/gates-v1")
        self.assertEqual(guardbase.OWNER_VERIFIED_ORIGIN, "d037cb6")


class TestExaminedRange(TopologyMixin):
    def _examined(self):
        cwd = Path.cwd()
        os.chdir(self.repo)
        try:
            return repo_guard.collect_examined_paths(self.repo, self.base_oid)
        finally:
            os.chdir(cwd)

    def test_range_covers_every_commit_since_the_base(self):
        self._commit_file("product/core.py", "value = 2\n", "product change")
        examined = self._examined()
        self.assertIn("product/core.py", examined)
        self.assertIn("commit_history", examined["product/core.py"])

    def test_a_reverted_product_change_stays_visible(self):
        self._commit_file("product/core.py", "value = 99\n", "product change")
        self._commit_file("product/core.py", "value = 1\n", "revert the change")
        examined = self._examined()
        self.assertIn(
            "product/core.py",
            examined,
            "a change that was reverted later must remain in the range",
        )
        self.assertIn("commit_history", examined["product/core.py"])
        # The cumulative tree diff alone would no longer show it.
        code, out, _ = gitutil.run_git(
            ["diff", "--name-only", self.base_oid, "HEAD"], cwd=self.repo
        )
        self.assertEqual(code, 0)
        self.assertNotIn("product/core.py", out.split())

    def test_index_worktree_and_untracked_are_part_of_the_range(self):
        (self.repo / "product" / "staged.py").write_text("x = 1\n", encoding="utf-8")
        _support.git(["add", "product/staged.py"], cwd=self.repo)
        (self.repo / "product" / "core.py").write_text("value = 3\n", encoding="utf-8")
        (self.repo / "product" / "untracked.py").write_text("y = 1\n", encoding="utf-8")
        examined = self._examined()
        self.assertIn("index", examined.get("product/staged.py", set()))
        self.assertIn("worktree", examined.get("product/core.py", set()))
        self.assertIn("untracked", examined.get("product/untracked.py", set()))

    def test_a_later_declared_base_cannot_shorten_the_range(self):
        first = self._commit_file("product/core.py", "value = 2\n", "product change")
        self._commit_file("tooling/extra.md", "later\n", "tooling change")
        # Even if a manifest claimed `first` as the base, the guard derives the
        # real base and still sees the product change.
        examined = self._examined()
        self.assertIn("product/core.py", examined)
        self.assertNotEqual(first, self.base_oid)


class TestRealRepositoryRange(unittest.TestCase):
    def test_the_range_starts_at_the_owner_verified_origin(self):
        derivation = guardbase.derive_for_repository(_support.REPO_ROOT)
        expected = gitutil.resolve_commit("d037cb6", cwd=_support.REPO_ROOT)
        self.assertEqual(derivation["base_commit"], expected)

    def test_the_range_contains_b0a_1_and_b0a_2_artifacts(self):
        derivation = guardbase.derive_for_repository(_support.REPO_ROOT)
        examined = repo_guard.collect_examined_paths(
            _support.REPO_ROOT, derivation["base_commit"]
        )
        self.assertIn("tools/gates/statuses.py", examined, "B0a-1 must stay in range")
        self.assertIn(
            "tools/gates/guardbase.py", examined, "B0a-2 must be in range"
        )

    def test_the_declared_base_of_every_block_matches_the_derivation(self):
        from tools.gates import manifest as manifest_module

        derivation = guardbase.derive_for_repository(_support.REPO_ROOT)
        blocks = manifest_module.known_block_ids(_support.REPO_ROOT)
        self.assertTrue(blocks)
        for block_id in blocks:
            with self.subTest(block=block_id):
                manifest = manifest_module.load(
                    manifest_module.manifest_path_for(_support.REPO_ROOT, block_id)
                )
                status, reason = guardbase.validate_declared_base(
                    manifest.data["product_guard"]["block_base_commit"],
                    derivation["base_commit"],
                )
                self.assertEqual(status, statuses.PASS, reason)


class TestGuardReportsTheDerivation(unittest.TestCase):
    def test_guard_output_names_the_derivation_and_the_range(self):
        report_path = Path(os.environ.get("TMPDIR", "/tmp")) / "guard-probe.json"
        env_backup = os.environ.get("GATE_REPORT")
        os.environ["GATE_REPORT"] = str(report_path)
        cwd = Path.cwd()
        os.chdir(_support.REPO_ROOT)
        try:
            stream = io.StringIO()
            repo_guard._report.emit  # noqa: B018 - keep the helper imported
            code = repo_guard.main(["--mode", "final", "--block", "b0a-3-integration"])
            del stream
        finally:
            os.chdir(cwd)
            if env_backup is None:
                os.environ.pop("GATE_REPORT", None)
            else:
                os.environ["GATE_REPORT"] = env_backup
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report_path.unlink(missing_ok=True)
        self.assertEqual(code, 0, report["failures"])
        self.assertIn("guard_base_derivation=git_merge_base_all", report["diagnostics"])
        self.assertIn(
            "declared_guard_base_matches_derivation", report["diagnostics"]
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
