"""Strict manifest schema validation, with positive and negative fixtures."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import manifest as manifest_module  # noqa: E402

FIXTURE_DIR = _support.REPO_ROOT / "config" / "gates" / "fixtures" / "manifests"


def issue_codes(exc):
    return {code for code, _ in exc.issues}


class TestManifestValidation(_support.TempEnvMixin):
    def setUp(self):
        super().setUp()
        self.base = _support.load_fixture_manifest()

    def _expect(self, mutation, code):
        data = _support.mutate(self.base, mutation)
        with self.assertRaises(manifest_module.ManifestError) as ctx:
            manifest_module.validate(data, digest="0" * 64)
        self.assertIn(code, issue_codes(ctx.exception))

    def test_valid_fixture_is_accepted(self):
        parsed = manifest_module.validate(self.base, digest="0" * 64)
        self.assertEqual(parsed.block_id, "fixture-valid")
        self.assertEqual(len(parsed.checks), 4)

    def test_real_block_manifest_is_valid(self):
        parsed = manifest_module.load(_support.BLOCK_MANIFEST)
        self.assertEqual(parsed.block_id, "b0a-1-tooling")
        self.assertFalse(parsed.is_applicable("platform-live"))
        self.assertTrue(parsed.is_applicable("module-final"))

    def test_unknown_top_level_field(self):
        self._expect(lambda d: d.update({"surprise": 1}), "unknown_field")

    def test_unknown_check_field(self):
        self._expect(
            lambda d: d["checks"][0].update({"expected": "pass"}), "unknown_field"
        )

    def test_duplicate_check_id(self):
        def mutation(data):
            clone = json.loads(json.dumps(data["checks"][0]))
            data["checks"].insert(1, clone)

        self._expect(mutation, "duplicate_check_id")

    def test_invalid_phase(self):
        self._expect(lambda d: d["checks"][0].update({"phase": "smoke"}), "invalid_phase")

    def test_invalid_result_value_declared(self):
        self._expect(
            lambda d: d["phase_definitions"]["platform-live"].update(
                {"declared_result": "pass"}
            ),
            "declared_result_not_allowed",
        )

    def test_success_result_must_not_be_predeclared(self):
        self._expect(
            lambda d: d["checks"][0].update({"description": "pass"}),
            "predeclared_result",
        )

    def test_contradictory_baseline_declaration(self):
        self._expect(
            lambda d: d["checks"][3].update({"baseline_eligible": True}),
            "baseline_contradiction",
        )

    def test_baseline_eligible_requires_structured_parser(self):
        def mutation(data):
            data["checks"][2]["parser"] = "exit_only"

        self._expect(mutation, "baseline_contradiction")

    def test_unsafe_shell_string(self):
        self._expect(
            lambda d: d["checks"][0]["runner"].update(
                {"argv": ["${GATE_PYTHON}", "-c", "import os; os.system('id')"]}
            ),
            "runner_unsafe_shell_string",
        )

    def test_missing_required_check(self):
        self._expect(
            lambda d: d.update(
                {"checks": [c for c in d["checks"] if c["phase"] != "offline-final"]}
            ),
            "missing_required_check",
        )

    def test_absolute_user_specific_path(self):
        self._expect(
            lambda d: d["checks"][0]["runner"].update(
                {"argv": ["${GATE_PYTHON}", "/Users/someone/run.py"]}  # gate-allow: absolute_user_path
            ),
            "absolute_user_path",
        )

    def test_non_applicable_phase_must_not_declare_checks(self):
        def mutation(data):
            clone = json.loads(json.dumps(data["checks"][0]))
            clone["check_id"] = "pl-extra"
            clone["phase"] = "platform-live"
            data["checks"].append(clone)

        self._expect(mutation, "phase_contradiction")

    def test_unstable_check_order_is_rejected(self):
        self._expect(
            lambda d: d["checks"].reverse(),
            "unstable_order",
        )

    def test_module_final_must_be_applicable(self):
        self._expect(
            lambda d: d["phase_definitions"]["module-final"].update(
                {"applicable": False, "declared_result": "not_applicable"}
            ),
            "invalid_phase",
        )

    def test_invalid_block_base_commit_is_rejected(self):
        self._expect(
            lambda d: d["product_guard"].update({"block_base_commit": "HEAD~1"}),
            "invalid_block_base_commit",
        )

    def test_secret_in_manifest_is_rejected(self):
        self._expect(
            lambda d: d.update({"title": "token=abc123secretvalue"}),
            "manifest_leak",
        )


class TestFixtures(unittest.TestCase):
    def test_every_negative_fixture_produces_its_named_issue(self):
        invalid = sorted((FIXTURE_DIR / "invalid").glob("*.json"))
        self.assertGreaterEqual(len(invalid), 8)
        for fixture in invalid:
            expected = fixture.stem.split(".")[0]
            with self.subTest(fixture=fixture.name):
                with self.assertRaises(manifest_module.ManifestError) as ctx:
                    manifest_module.load(fixture)
                self.assertIn(expected, issue_codes(ctx.exception))

    def test_every_positive_fixture_is_accepted(self):
        valid = sorted((FIXTURE_DIR / "valid").glob("*.json"))
        self.assertTrue(valid)
        for fixture in valid:
            with self.subTest(fixture=fixture.name):
                manifest_module.load(fixture)

    def test_required_negative_cases_are_present(self):
        present = {
            path.stem.split(".")[0]
            for path in (FIXTURE_DIR / "invalid").glob("*.json")
        }
        for expected in (
            "unknown_field",
            "duplicate_check_id",
            "invalid_phase",
            "declared_result_not_allowed",
            "baseline_contradiction",
            "runner_unsafe_shell_string",
            "missing_required_check",
            "absolute_user_path",
        ):
            self.assertIn(expected, present)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
