"""Baseline worktree lifecycle and structural baseline comparison."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import baseline as baseline_module  # noqa: E402
from tools.gates import gitutil  # noqa: E402
from tools.gates import manifest as manifest_module  # noqa: E402
from tools.gates import paths as gate_paths  # noqa: E402
from tools.gates import statuses  # noqa: E402


class TestBaselineWorktree(_support.TempEnvMixin):
    def setUp(self):
        super().setUp()
        self.repo = _support.make_repo(
            self.tmp_path / "repo", files={"scripts/a.sh": "echo baseline\n"}
        )
        self.baseline_commit = gitutil.head_commit(cwd=self.repo)
        (self.repo / "scripts" / "b.sh").write_text("echo later\n", encoding="utf-8")
        _support.git(["add", "-A"], cwd=self.repo)
        _support.git(["commit", "--quiet", "-m", "second"], cwd=self.repo)
        self.head_commit = gitutil.head_commit(cwd=self.repo)
        self.worktrees = []

    def tearDown(self):
        for worktree in self.worktrees:
            worktree.release_lock()
        super().tearDown()

    def _worktree(self, commit=None):
        worktree = baseline_module.BaselineWorktree(
            source_worktree=self.repo, commit=commit or self.baseline_commit
        )
        self.worktrees.append(worktree)
        return worktree

    def test_worktree_is_detached_on_exactly_the_declared_commit(self):
        worktree = self._worktree()
        worktree.acquire_lock()
        path = worktree.prepare()
        self.assertEqual(gitutil.head_commit(cwd=path), self.baseline_commit)
        self.assertNotEqual(gitutil.head_commit(cwd=path), self.head_commit)
        self.assertEqual(gitutil.current_branch(cwd=path), "")

    def test_worktree_lives_outside_the_active_worktree(self):
        worktree = self._worktree()
        worktree.acquire_lock()
        path = worktree.prepare().resolve()
        self.assertFalse(str(path).startswith(str(self.repo.resolve()) + "/"))
        self.assertTrue(
            str(path).startswith(str(self.state_dir.resolve())),
            f"baseline worktree outside the controlled state area: {path}",
        )

    def test_worktree_carries_the_engine_ownership_marker(self):
        worktree = self._worktree()
        worktree.acquire_lock()
        path = worktree.prepare()
        self.assertTrue((path / gate_paths.BASELINE_OWNER_MARKER).is_file())
        self.assertTrue(
            baseline_module.is_owned(
                path,
                owner=worktree.owner,
                common_git_dir=worktree.common_git_dir,
                commit=self.baseline_commit,
            )
        )

    def test_second_preparation_reuses_the_verified_worktree(self):
        worktree = self._worktree()
        worktree.acquire_lock()
        first = worktree.prepare()
        marker = first / gate_paths.BASELINE_OWNER_MARKER
        stamp = marker.stat().st_mtime_ns
        second = worktree.prepare()
        self.assertEqual(first, second)
        self.assertEqual(marker.stat().st_mtime_ns, stamp)

    def test_wrong_baseline_head_is_rejected_and_renewed(self):
        worktree = self._worktree()
        worktree.acquire_lock()
        path = worktree.prepare()
        _support.git(["checkout", "--detach", self.head_commit], cwd=path)
        self.assertEqual(worktree._verify(), (False, "baseline_worktree_wrong_head"))
        renewed = worktree.prepare()
        self.assertEqual(gitutil.head_commit(cwd=renewed), self.baseline_commit)

    def test_dirty_baseline_worktree_is_renewed_safely(self):
        worktree = self._worktree()
        worktree.acquire_lock()
        path = worktree.prepare()
        (path / "scratch.txt").write_text("dirt\n", encoding="utf-8")
        self.assertEqual(worktree._verify(), (False, "baseline_worktree_dirty"))
        renewed = worktree.prepare()
        self.assertFalse((renewed / "scratch.txt").exists())
        self.assertEqual(gitutil.status_porcelain(cwd=renewed), [
            ("??", gate_paths.BASELINE_OWNER_MARKER)
        ])

    def test_a_foreign_worktree_is_never_removed(self):
        worktree = self._worktree()
        worktree.acquire_lock()
        foreign = worktree.path
        foreign.mkdir(parents=True, exist_ok=True)
        precious = foreign / "someone-elses-work.txt"
        precious.write_text("do not touch\n", encoding="utf-8")
        with self.assertRaises(baseline_module.BaselineUnavailable) as ctx:
            worktree.prepare()
        self.assertEqual(ctx.exception.reason_code, "baseline_worktree_foreign")
        self.assertTrue(precious.is_file())

    def test_parallel_access_is_locked_out(self):
        first = self._worktree()
        first.acquire_lock()
        second = self._worktree()
        with self.assertRaises(baseline_module.BaselineUnavailable) as ctx:
            second.acquire_lock()
        self.assertEqual(ctx.exception.reason_code, "baseline_worktree_locked")

    def test_missing_commit_object_is_reported(self):
        with self.assertRaises(baseline_module.BaselineUnavailable) as ctx:
            baseline_module.BaselineWorktree(
                source_worktree=self.repo, commit="0" * 40
            )
        self.assertEqual(ctx.exception.reason_code, "baseline_commit_missing")


class TestDeclaredBaseline(unittest.TestCase):
    def test_block_declares_exactly_7986bee(self):
        manifest = manifest_module.load(_support.BLOCK_MANIFEST)
        self.assertEqual(manifest.baseline_commit, "7986bee")

    def test_declared_baseline_resolves_in_this_repository(self):
        resolved = gitutil.resolve_commit("7986bee", cwd=_support.REPO_ROOT)
        if resolved is None:  # pragma: no cover - depends on the local clone
            self.skipTest("baseline commit object is not available locally")
        self.assertTrue(resolved.startswith("7986bee"))


class TestBaselineComparison(unittest.TestCase):
    def _compare(self, candidate, baseline, *, eligible=True):
        check = _support.FakeCheck(baseline_eligible=eligible)
        return baseline_module.compare_runs(
            check, candidate, baseline, block_id="b0a-1-tooling"
        )

    def test_clean_candidate_passes_despite_an_old_baseline_failure(self):
        status, reason, _, _ = self._compare(
            _support.structured("passed"),
            _support.structured("failed", [_support.failure("scripts/a.sh")]),
        )
        self.assertEqual(status, statuses.PASS)
        self.assertEqual(reason, "check_passed")

    def test_failing_candidate_with_clean_baseline_fails(self):
        status, reason, _, _ = self._compare(
            _support.structured("failed", [_support.failure("scripts/a.sh")]),
            _support.structured("passed"),
        )
        self.assertEqual(status, statuses.FAIL)
        self.assertEqual(reason, "baseline_clean_candidate_failed")

    def test_structurally_identical_failure_is_excused(self):
        failing = _support.structured("failed", [_support.failure("scripts/a.sh")])
        status, reason, candidate_signature, _ = self._compare(failing, failing)
        self.assertEqual(status, statuses.PASS_WITH_BASELINE)
        self.assertEqual(reason, "baseline_match_structural")
        self.assertIsNotNone(candidate_signature)

    def test_only_textually_similar_failure_is_not_excused(self):
        status, reason, _, _ = self._compare(
            _support.structured("failed", [_support.failure("scripts/a.sh")]),
            _support.structured("failed", [_support.failure("scripts/b.sh")]),
        )
        self.assertEqual(status, statuses.FAIL)
        self.assertEqual(reason, "baseline_new_cause")

    def test_additional_candidate_cause_is_not_excused(self):
        status, reason, _, _ = self._compare(
            _support.structured(
                "failed",
                [_support.failure("scripts/a.sh"), _support.failure("scripts/b.sh")],
            ),
            _support.structured("failed", [_support.failure("scripts/a.sh")]),
        )
        self.assertEqual(status, statuses.FAIL)
        self.assertEqual(reason, "baseline_additional_candidate_failures")

    def test_check_without_baseline_eligibility_always_fails(self):
        failing = _support.structured("failed", [_support.failure("scripts/a.sh")])
        status, reason, _, _ = self._compare(failing, failing, eligible=False)
        self.assertEqual(status, statuses.FAIL)
        self.assertEqual(reason, "check_failed_not_baseline_eligible")

    def test_unavailable_baseline_run_is_blocked(self):
        status, reason, _, _ = self._compare(
            _support.structured("failed", [_support.failure("scripts/a.sh")]), None
        )
        self.assertEqual(status, statuses.BLOCKED)
        self.assertEqual(reason, "baseline_unavailable")

    def test_exit_code_only_failure_cannot_be_excused(self):
        opaque = _support.structured(
            "failed", diagnostics=["non_zero_exit_code"], structural=False
        )
        status, reason, _, _ = self._compare(opaque, opaque)
        self.assertEqual(status, statuses.FAIL)
        self.assertEqual(reason, "cause_signature_unavailable")

    def test_cached_baseline_result_round_trips_structurally(self):
        failing = _support.structured("failed", [_support.failure("scripts/a.sh")])
        signature = baseline_module.signature_module.build_cause_signature(
            block_id="b0a-1-tooling",
            check_id="fake-check",
            runner_kind="argv",
            parser="gate_json",
            structured=failing,
        )
        cached = baseline_module.cache_result_from_structured(failing, 1, signature)
        restored = baseline_module.structured_from_cache(cached)
        status, reason, _, _ = self._compare(failing, restored)
        self.assertEqual(status, statuses.PASS_WITH_BASELINE)
        self.assertEqual(reason, "baseline_match_structural")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
