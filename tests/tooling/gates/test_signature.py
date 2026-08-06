"""Versioned structural cause signatures."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import CAUSE_SIGNATURE_VERSION  # noqa: E402
from tools.gates import signature as signature_module  # noqa: E402


def build(structured, *, check_id="of-shell-syntax", parser="gate_json"):
    return signature_module.build_cause_signature(
        block_id="b0a-1-tooling",
        check_id=check_id,
        runner_kind="argv",
        parser=parser,
        structured=structured,
    )


class TestCauseSignature(unittest.TestCase):
    def test_signature_is_versioned_and_digested(self):
        result = build(
            _support.structured(
                "failed", [_support.failure("scripts/a.sh", code="exit_2")]
            )
        )
        self.assertEqual(result["signature_version"], CAUSE_SIGNATURE_VERSION)
        self.assertRegex(result["digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(result["elements"]["failure_count"], 1)

    def test_noise_is_normalised_away(self):
        noisy = _support.structured(
            "failed",
            [
                _support.failure(
                    "scripts/a.sh",
                    code="exit_2",
                    frames=[
                        "/Users/someone/Jarvis-Next/tools/gates/x.py:118 in run",  # gate-allow: absolute_user_path
                        "run at 2026-08-05T10:11:12Z pid 4711 0xdeadbeef",
                    ],
                )
            ],
        )
        clean = _support.structured(
            "failed",
            [
                _support.failure(
                    "scripts/a.sh",
                    code="exit_2",
                    frames=[
                        "/Users/other/Elsewhere/tools/gates/x.py:9931 in run",  # gate-allow: absolute_user_path
                        "run at 2024-01-02T03:04:05Z pid 12 0xfeed",
                    ],
                )
            ],
        )
        self.assertEqual(build(noisy)["digest"], build(clean)["digest"])

    def test_order_noise_does_not_change_the_digest(self):
        first = _support.structured(
            "failed",
            [_support.failure("test_a[1]"), _support.failure("test_b[2]")],
        )
        second = _support.structured(
            "failed",
            [_support.failure("test_b[7]"), _support.failure("test_a[3]")],
        )
        self.assertEqual(build(first)["digest"], build(second)["digest"])

    def test_passing_run_has_no_signature(self):
        self.assertIsNone(build(_support.structured("passed")))

    def test_exit_code_only_is_not_a_structural_cause(self):
        self.assertIsNone(
            build(
                _support.structured(
                    "failed", diagnostics=["non_zero_exit_code"], structural=False
                )
            )
        )

    def test_timeout_has_no_signature(self):
        self.assertIsNone(
            build(
                {
                    "outcome": "timeout",
                    "structural": False,
                    "failures": [],
                    "diagnostics": ["check_timeout"],
                }
            )
        )

    def test_failure_without_structural_identity_is_refused(self):
        self.assertIsNone(
            build(_support.structured("failed", [{"category": "unknown"}]))
        )

    def test_identical_structure_matches(self):
        left = build(_support.structured("failed", [_support.failure("scripts/a.sh")]))
        right = build(_support.structured("failed", [_support.failure("scripts/a.sh")]))
        same, reason = signature_module.compare(left, right)
        self.assertTrue(same)
        self.assertEqual(reason, "baseline_match_structural")

    def test_textual_similarity_is_not_enough(self):
        candidate = build(
            _support.structured("failed", [_support.failure("scripts/a.sh")])
        )
        baseline = build(
            _support.structured("failed", [_support.failure("scripts/b.sh")])
        )
        same, reason = signature_module.compare(candidate, baseline)
        self.assertFalse(same)
        self.assertEqual(reason, "baseline_new_cause")

    def test_additional_candidate_failure_is_detected(self):
        candidate = build(
            _support.structured(
                "failed",
                [_support.failure("scripts/a.sh"), _support.failure("scripts/b.sh")],
            )
        )
        baseline = build(
            _support.structured("failed", [_support.failure("scripts/a.sh")])
        )
        same, reason = signature_module.compare(candidate, baseline)
        self.assertFalse(same)
        self.assertEqual(reason, "baseline_additional_candidate_failures")

    def test_new_failure_category_is_detected(self):
        candidate = build(
            _support.structured(
                "failed", [_support.failure("scripts/a.sh", category="test_error")]
            )
        )
        baseline = build(
            _support.structured(
                "failed", [_support.failure("scripts/a.sh", category="test_failure")]
            )
        )
        same, reason = signature_module.compare(candidate, baseline)
        self.assertFalse(same)
        self.assertEqual(reason, "baseline_new_failure_category")

    def test_missing_signature_never_matches(self):
        signature = build(
            _support.structured("failed", [_support.failure("scripts/a.sh")])
        )
        self.assertEqual(
            signature_module.compare(signature, None),
            (False, "cause_signature_unavailable"),
        )
        self.assertEqual(
            signature_module.compare(None, signature),
            (False, "cause_signature_unavailable"),
        )

    def test_signature_version_mismatch_never_matches(self):
        left = build(_support.structured("failed", [_support.failure("scripts/a.sh")]))
        right = dict(left)
        right["signature_version"] = "cs-0"
        same, reason = signature_module.compare(left, right)
        self.assertFalse(same)
        self.assertEqual(reason, "cause_signature_version_mismatch")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
