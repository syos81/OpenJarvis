"""Rule R10 absence guards in the gate checkers — the mandatory pair (RC-024).

*Sharpening.* Every repaired checker used to walk ``document.get(key, [])``:
a dropped or misspelled key skipped the whole obligation and the mode still
reported success. Each sharpening case below constructs exactly that document
— the key absent or empty — and requires the new failure code.

*Counter.* The behaviour that was already correct must survive: the same
checker with the key present and populated does not raise the new code, and
the previously recognised defects keep failing (covered by the unchanged
mode tests across this suite and by the gate runs themselves).

The fixtures are constructed, not mutated: every document below is written
fresh with the shape under test, so rule R9's effect evidence duty does not
attach to these tests.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.gates import generality  # noqa: E402
from tools.gates import paths as paths_module  # noqa: E402
from tools.gates.runners import generality_checks  # noqa: E402
from tools.gates.runners import governance_checks  # noqa: E402
from tools.gates.runners import guard_checks  # noqa: E402
from tools.gates.runners import history_checks  # noqa: E402
from tools.gates.runners import integration_checks  # noqa: E402
from tools.gates.runners import merge_readiness  # noqa: E402


class FixtureWorktree(unittest.TestCase):
    """A throwaway directory the mode under test is pointed at via cwd."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="r10-repairs-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self._previous_cwd)
        self.report = self.root / "report.json"
        patcher = mock.patch.dict(os.environ, {"GATE_REPORT": str(self.report)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, relative, document):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(document, str):
            target.write_text(document, encoding="utf-8")
        else:
            target.write_text(json.dumps(document, indent=1), encoding="utf-8")
        return target

    def copy_from_repo(self, relative):
        payload = (REPO_ROOT / relative).read_bytes()
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return target

    def report_codes(self):
        payload = json.loads(self.report.read_text(encoding="utf-8"))
        return sorted(failure["code"] for failure in payload["failures"])

    def git(self, *arguments):
        return subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()


class TestSharpening(FixtureWorktree):
    """The key is absent — the checker must fail, never walk nothing."""

    def test_rule_changes_without_a_fixture_declaration_fail(self):
        reference = "tests/ref.py::TestAnchor::test_case"
        self.write("tests/ref.py", "class TestAnchor:\n    def test_case(self):\n        pass\n")
        self.write(
            "config/guard/rule-changes.json",
            {
                "changes": [
                    {
                        "change_id": "RC-001",
                        "kind": "sharpening",
                        "summary": "fixture",
                        "sharpening_test": reference,
                        "counter_test": reference,
                        "violation_set_effect": "grows",
                    }
                ]
            },
        )
        guard_checks.mode_rule_changes(None)
        self.assertIn("fixture_declaration_missing", self.report_codes())

    def test_a_violation_corpus_without_entries_fails(self):
        self.copy_from_repo("tools/guard/rules.json")
        self.write("config/guard/violation-corpus.json", {"entries": []})
        guard_checks.mode_violation_corpus(None)
        self.assertIn("no_corpus_entries", self.report_codes())

    def test_an_acceptance_manifest_without_evidence_fails_the_r3_review(self):
        self.write(
            "config/gates/history/r3-not-applicable-review.json",
            {"rule": "R3", "findings": [], "examined_and_cleared": []},
        )
        self.write(
            "config/gates/history/some-block.acceptance.json",
            {
                "reexecution_policy": {"runtime_evidence_absent": "fail"},
            },
        )
        history_checks.mode_not_applicable_review(None)
        self.assertIn("runtime_evidence_undeclared", self.report_codes())

    def test_an_acceptance_manifest_without_artifacts_fails_integrity(self):
        self.git("init", "--quiet")
        self.git("-c", "user.email=fixture@example.invalid", "-c", "user.name=Fixture", "commit", "--allow-empty", "--quiet", "-m", "fixture")
        commit = self.git("rev-parse", "HEAD")
        self.write(
            "config/gates/history/some-block.acceptance.json",
            {
                "block_id": "some-block",
                "kind": "historical_acceptance",
                "acceptance_commit": commit,
                "reexecution_policy": {
                    "rerun_against_current_head": False,
                    "runtime_evidence_absent": "fail",
                },
            },
        )
        history_checks.mode_historical_integrity(None)
        self.assertIn("manifest_without_committed_artifacts", self.report_codes())

    def test_a_preservation_manifest_without_invariants_fails(self):
        self.write("lineage.json", {"features": []})
        self.write(
            "config/gates/preservation/calendar-line.preservation.json",
            {
                "kind": "current_preservation",
                "feature_preservation": {
                    "lineage_file": "lineage.json",
                    "expected_required_by_prefix": {},
                },
            },
        )
        history_checks.mode_preservation(None)
        self.assertIn("invariant_set_missing_or_empty", self.report_codes())

    def test_an_id_migration_without_mappings_excuses_nothing(self):
        self.git("init", "--quiet")
        self.git("-c", "user.email=fixture@example.invalid", "-c", "user.name=Fixture", "commit", "--allow-empty", "--quiet", "-m", "fixture")
        self.copy_from_repo("config/governance/decision-citations.json")
        self.write("config/governance/b0a-3-id-migration.json", {"mappings": []})
        with mock.patch.object(
            governance_checks.guardbase,
            "derive_for_repository",
            return_value={"base_commit": "HEAD"},
        ):
            failures, _diagnostics = governance_checks.mode_id_freeze(self.root)
        self.assertIn(
            "migration_without_mappings", [failure["code"] for failure in failures]
        )

    def test_a_resolved_registry_without_resolution_records_fails(self):
        for relative in (
            "config/governance/normative-sources.json",
            "config/governance/decision-collisions.json",
        ):
            self.copy_from_repo(relative)
        registry = json.loads(
            (REPO_ROOT / "config/governance/normative-sources.json").read_text(
                encoding="utf-8"
            )
        )
        document = registry["collision_and_mapping"]["normative"].partition("#")[0]
        self.copy_from_repo(document)
        collisions_path = self.root / "config/governance/decision-collisions.json"
        collisions = json.loads(collisions_path.read_text(encoding="utf-8"))
        collisions["historical_resolution"] = []
        collisions_path.write_text(json.dumps(collisions, indent=1), encoding="utf-8")
        failures, _diagnostics = integration_checks.mode_single_normative_source(
            self.root
        )
        self.assertIn(
            "resolved_registry_without_resolution_records",
            [failure["code"] for failure in failures],
        )

    def test_a_merge_policy_without_inherited_blocks_fails(self):
        failures = []
        merge_readiness._inherited_blocks(self.root, {}, failures, [])
        self.assertEqual(
            [failure["code"] for failure in failures], ["inherited_blocks_undeclared"]
        )

    def test_a_lost_activation_key_is_an_error_not_inactive(self):
        with self.assertRaises(generality.ActivationError) as caught:
            generality.process_paths_present(self.root, {"schema_globs": []})
        self.assertEqual(caught.exception.code, "process_activation_key_missing")

    def test_provider_terms_without_variants_fail_the_literal_check(self):
        scope_path = "config/governance/generality-scope.json"
        scope = json.loads((REPO_ROOT / scope_path).read_text(encoding="utf-8"))
        for term in scope["provider_terms"]:
            term["variants"] = []
        self.write(scope_path, scope)
        with mock.patch.dict(os.environ):
            # Under a gate run GATE_ENGINE_ROOT points the steering
            # configuration at the real engine; this fixture *is* the
            # steering configuration under test, so the redirect must not
            # apply here.
            os.environ.pop("GATE_ENGINE_ROOT", None)
            failures, _diagnostics = generality_checks.mode_literal_comparisons(
                self.root
            )
        self.assertIn(
            "provider_term_without_variants",
            [failure["code"] for failure in failures],
        )

    def test_a_neutered_chmod_no_longer_passes_silently(self):
        target = self.root / "private-area"
        if os.name != "posix":  # pragma: no cover - posix-only contract
            self.skipTest("directory mode contract is posix-only")
        with mock.patch.object(paths_module.os, "chmod", lambda *args: None):
            with self.assertRaises(OSError):
                paths_module.ensure_private_dir(target)


class TestCounter(FixtureWorktree):
    """Present and populated keys keep working exactly as before."""

    def test_populated_rule_changes_do_not_raise_the_new_code(self):
        reference = "tests/ref.py::TestAnchor::test_case"
        self.write("tests/ref.py", "class TestAnchor:\n    def test_case(self):\n        pass\n")
        self.write("fixture-file.json", {})
        self.write(
            "config/guard/rule-changes.json",
            {
                "changes": [
                    {
                        "change_id": "RC-001",
                        "kind": "sharpening",
                        "summary": "fixture",
                        "sharpening_test": reference,
                        "counter_test": reference,
                        "violation_set_effect": "grows",
                    }
                ],
                "fixtures": [
                    {
                        "path": "fixture-file.json",
                        "purpose": "fixture",
                        "abuse_test": reference,
                    }
                ],
            },
        )
        guard_checks.mode_rule_changes(None)
        self.assertNotIn("fixture_declaration_missing", self.report_codes())

    def test_the_real_violation_corpus_still_passes_its_walk(self):
        self.copy_from_repo("tools/guard/rules.json")
        self.copy_from_repo("config/guard/violation-corpus.json")
        exit_code = guard_checks.mode_violation_corpus(None)
        self.assertEqual(exit_code, 0)
        self.assertNotIn("no_corpus_entries", self.report_codes())

    def test_the_real_registry_still_agrees_with_its_normative_text(self):
        for relative in (
            "config/governance/normative-sources.json",
            "config/governance/decision-collisions.json",
        ):
            self.copy_from_repo(relative)
        registry = json.loads(
            (REPO_ROOT / "config/governance/normative-sources.json").read_text(
                encoding="utf-8"
            )
        )
        document = registry["collision_and_mapping"]["normative"].partition("#")[0]
        self.copy_from_repo(document)
        failures, _diagnostics = integration_checks.mode_single_normative_source(
            self.root
        )
        self.assertNotIn(
            "resolved_registry_without_resolution_records",
            [failure["code"] for failure in failures],
        )

    def test_declared_empty_globs_stay_a_legitimate_inactive_state(self):
        state, found = generality.activation_state(
            self.root,
            {"schema_globs": [], "route_globs": [], "core_globs": []},
        )
        self.assertEqual(state, "inactive")
        self.assertEqual(found, [])

    def test_the_private_dir_contract_is_enforced_and_observable(self):
        if os.name != "posix":  # pragma: no cover - posix-only contract
            self.skipTest("directory mode contract is posix-only")
        import stat as stat_module

        target = self.root / "private-area"
        target.mkdir(mode=0o755)
        self.assertEqual(
            stat_module.S_IMODE(os.stat(target).st_mode) & 0o077,
            0o055,
            "the fixture directory did not start group/other accessible",
        )
        paths_module.ensure_private_dir(target)
        self.assertEqual(stat_module.S_IMODE(os.stat(target).st_mode), 0o700)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
