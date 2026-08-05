"""Tooling merge readiness — it checks, it never merges."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import manifest as manifest_module  # noqa: E402
from tools.gates.runners import _report  # noqa: E402
from tools.gates.runners import merge_readiness  # noqa: E402

POLICY = _support.REPO_ROOT / "config" / "governance" / "tooling-merge.json"
MANIFEST = (
    _support.REPO_ROOT / "config" / "gates" / "blocks" / "tooling-merge-readiness.json"
)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TestPolicy(unittest.TestCase):
    def setUp(self):
        self.policy = load(POLICY)

    def test_source_and_target_are_the_intended_lines(self):
        self.assertEqual(self.policy["source_ref"], "tooling/gates-v1")
        self.assertEqual(
            self.policy["target_ref"], "spike/calendar-foundation-intel-2026-08-04"
        )

    def test_the_policy_never_declares_a_merge(self):
        self.assertFalse(self.policy["executes_merge"])
        for action in ("merge", "rebase", "cherry_pick", "tag", "release"):
            self.assertIn(action, self.policy["forbidden_actions"])

    def test_reverse_merge_is_forbidden(self):
        self.assertEqual(self.policy["direction"], "incoming_only")
        self.assertIn("reverse_merge_into_tooling", self.policy["forbidden_actions"])

    def test_product_paths_are_forbidden_in_the_merge_scope(self):
        for pattern in ("src/*", "frontend/*", "native/*", "docs/personal-jarvis/*"):
            self.assertIn(pattern, self.policy["forbidden_paths"])


class TestNoMergeExecution(unittest.TestCase):
    def test_the_runner_uses_no_merging_git_verb(self):
        source = Path(merge_readiness.__file__).read_text(encoding="utf-8")
        verbs = merge_readiness.git_verbs_used(source)
        self.assertEqual(verbs, ["diff"])
        for verb in ("merge", "rebase", "cherry-pick", "push", "reset"):
            self.assertNotIn(verb, verbs)

    def test_the_no_merge_mode_passes(self):
        failures, diagnostics = merge_readiness.mode_no_merge(_support.REPO_ROOT)
        self.assertEqual([failure["id"] for failure in failures], [])
        self.assertIn("merge_execution=never", diagnostics)

    def test_the_detector_would_catch_a_merging_verb(self):
        source = 'gitutil.run_git(["merge", "--no-ff", "other"], cwd=root)\n'
        self.assertEqual(merge_readiness.git_verbs_used(source), ["merge"])


class TestReadinessChecks(unittest.TestCase):
    def test_refs_resolve(self):
        failures, diagnostics = merge_readiness.mode_refs(_support.REPO_ROOT)
        self.assertEqual([failure["id"] for failure in failures], [])
        self.assertEqual(len(diagnostics), 2)

    def test_the_incoming_scope_stays_inside_the_allowlist(self):
        failures, diagnostics = merge_readiness.mode_scope(_support.REPO_ROOT)
        self.assertEqual([failure["id"] for failure in failures], [])
        self.assertTrue(
            any(item.startswith("incoming_paths=") for item in diagnostics)
        )

    def test_the_incoming_scope_carries_no_product_path(self):
        policy = load(POLICY)
        paths = merge_readiness.incoming_paths(_support.REPO_ROOT, policy)
        self.assertIsNotNone(paths)
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse(path.startswith("src/"))
                self.assertFalse(path.startswith("frontend/"))
                self.assertFalse(path.startswith("docs/personal-jarvis/"))

    def test_an_unresolved_collision_blocks_the_integration(self):
        result = merge_readiness.mode_collisions_blocking(_support.REPO_ROOT)
        failures, diagnostics, outcome = result
        self.assertEqual(outcome, _report.BLOCKED)
        self.assertTrue(failures)
        self.assertIn("open_collisions=7", diagnostics)
        self.assertEqual(
            {failure["code"] for failure in failures},
            {"integration_blocked_by_open_collision"},
        )

    def test_the_blocked_outcome_uses_its_own_exit_code(self):
        self.assertEqual(_report.BLOCKED, "blocked")


class TestReadinessManifest(unittest.TestCase):
    def test_the_manifest_is_valid_and_declares_no_merge(self):
        manifest = manifest_module.load(MANIFEST)
        self.assertEqual(manifest.block_id, "tooling-merge-readiness")
        for check in manifest.checks:
            with self.subTest(check=check.check_id):
                argv = check.runner.get("argv") or []
                self.assertNotIn("merge", [token.lower() for token in argv[3:]])

    def test_platform_live_is_declared_non_applicable(self):
        manifest = manifest_module.load(MANIFEST)
        self.assertFalse(manifest.is_applicable("platform-live"))
        self.assertEqual(
            manifest.phase_definition("platform-live")["declared_result"],
            "not_applicable",
        )

    def test_both_required_blocks_are_declared(self):
        policy = load(POLICY)
        self.assertEqual(
            policy["required_module_final_blocks"],
            ["b0a-1-tooling", "b0a-2-governance"],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
