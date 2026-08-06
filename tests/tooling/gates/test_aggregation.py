"""Result aggregation and exit code mapping."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import statuses  # noqa: E402

PASS = statuses.PASS
PWB = statuses.PASS_WITH_BASELINE
FAIL = statuses.FAIL
BLOCKED = statuses.BLOCKED
NA = statuses.NOT_APPLICABLE


class TestAggregation(unittest.TestCase):
    def test_exactly_five_results_exist(self):
        self.assertEqual(
            statuses.ALL_STATUSES,
            (
                "pass",
                "pass_with_baseline",
                "fail",
                "blocked",
                "not_applicable",
            ),
        )

    def test_unknown_result_is_rejected(self):
        with self.assertRaises(statuses.GateStatusError):
            statuses.validate("green")
        with self.assertRaises(statuses.GateStatusError):
            statuses.aggregate([PASS, "skipped"])

    def test_only_pass(self):
        self.assertEqual(statuses.aggregate([PASS, PASS, PASS]), PASS)

    def test_pass_mixed_with_not_applicable(self):
        self.assertEqual(statuses.aggregate([PASS, NA, PASS]), PASS)

    def test_only_not_applicable(self):
        self.assertEqual(statuses.aggregate([NA, NA]), NA)

    def test_pass_with_baseline_beats_pass(self):
        self.assertEqual(statuses.aggregate([PASS, PWB, NA]), PWB)

    def test_blocked_beats_every_green_result(self):
        self.assertEqual(statuses.aggregate([PASS, PWB, NA, BLOCKED]), BLOCKED)

    def test_fail_beats_blocked(self):
        self.assertEqual(statuses.aggregate([BLOCKED, FAIL, PASS]), FAIL)

    def test_empty_checklist_is_not_a_success(self):
        self.assertEqual(statuses.aggregate([]), FAIL)

    def test_module_final_never_ends_not_applicable(self):
        self.assertEqual(statuses.aggregate_module_final([NA, NA]), FAIL)
        self.assertEqual(statuses.aggregate_module_final([PASS, NA]), PASS)
        self.assertEqual(statuses.aggregate_module_final([PWB, PASS]), PWB)
        self.assertEqual(statuses.aggregate_module_final([BLOCKED, PASS]), BLOCKED)
        self.assertEqual(statuses.aggregate_module_final([FAIL, BLOCKED]), FAIL)

    def test_missing_required_check_entry_forces_fail(self):
        # The engine injects a fail entry for a declared but unexecuted
        # mandatory check; aggregation must then never be green.
        self.assertEqual(statuses.aggregate([PASS, PASS, FAIL]), FAIL)


class TestExitCodes(unittest.TestCase):
    def test_documented_mapping(self):
        self.assertEqual(statuses.exit_code(PASS), 0)
        self.assertEqual(statuses.exit_code(PWB), 0)
        self.assertEqual(statuses.exit_code(NA), 0)
        self.assertEqual(statuses.exit_code(FAIL), 20)
        self.assertEqual(statuses.exit_code(BLOCKED), 30)

    def test_green_results_are_non_failed_runs(self):
        for status in (PASS, PWB, NA):
            self.assertEqual(statuses.exit_code(status), 0, status)

    def test_fail_and_blocked_have_different_non_zero_codes(self):
        self.assertNotEqual(statuses.exit_code(FAIL), statuses.exit_code(BLOCKED))
        self.assertNotEqual(statuses.exit_code(FAIL), 0)
        self.assertNotEqual(statuses.exit_code(BLOCKED), 0)

    def test_usage_and_internal_codes_are_distinct(self):
        codes = {
            statuses.EXIT_OK,
            statuses.EXIT_FAIL,
            statuses.EXIT_BLOCKED,
            statuses.EXIT_USAGE,
            statuses.EXIT_INTERNAL,
        }
        self.assertEqual(len(codes), 5)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
