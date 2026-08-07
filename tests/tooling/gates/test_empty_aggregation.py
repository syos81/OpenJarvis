"""Rule R10 — an aggregation over an empty set never reports ``pass``.

The mandatory pair for RC-023.

*Sharpening.* The newly recognised case: a phase whose evidence record declares
raw log digests while the stored result that would let them be verified is
gone. Before the change the walk over that phase's checks iterated zero times,
contributed no issue, and the check reported ``evidence_complete``. It now ends
in ``blocked`` with its own reason code.

*Counter.* The behaviour that was already correct must survive: a complete run
still passes, a genuinely broken raw log still fails, and a failure still
outranks a non evidence state.

The exception is tested in both directions too, because a rule with an
exception that is never exercised is a rule with an untested escape hatch: a
phase whose record declares no raw logs at all passes with ``derived_empty_set``,
and that is not the same verdict as ``aggregated``.

Rule R9 applies to every test below that removes something: the withdrawal is
established before anything is asserted about the engine.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.gates import emptyset  # noqa: E402
from tools.gates import evidence as evidence_module  # noqa: E402
from tools.gates import statuses  # noqa: E402


class TestTheRuleItself(unittest.TestCase):
    """:mod:`tools.gates.emptyset`, in isolation."""

    def test_an_expected_element_that_was_never_examined_blocks(self):
        status, reason = emptyset.verdict(examined=0, derived_expected=3)
        self.assertEqual(status, statuses.BLOCKED)
        self.assertEqual(reason, emptyset.AGGREGATION_SET_EMPTY)

    def test_a_predicted_emptiness_is_a_result_and_passes(self):
        status, reason = emptyset.verdict(examined=0, derived_expected=0)
        self.assertEqual(status, statuses.PASS)
        self.assertEqual(reason, emptyset.DERIVED_EMPTY_SET)

    def test_the_exception_is_distinguishable_from_an_ordinary_pass(self):
        """Both pass, and a reader must still be able to tell them apart."""
        _s1, predicted = emptyset.verdict(examined=0, derived_expected=0)
        _s2, ordinary = emptyset.verdict(examined=2, derived_expected=2)
        self.assertNotEqual(predicted, ordinary)

    def test_an_ordinary_aggregation_passes(self):
        status, reason = emptyset.verdict(examined=2, derived_expected=2)
        self.assertEqual(status, statuses.PASS)
        self.assertEqual(reason, emptyset.AGGREGATED)

    def test_finding_more_than_was_derived_is_refused_rather_than_smoothed(self):
        with self.assertRaises(emptyset.EmptySetError):
            emptyset.verdict(examined=1, derived_expected=0)

    def test_a_set_whose_emptiness_can_never_be_the_property_blocks(self):
        status, reason = emptyset.require_non_empty(0)
        self.assertEqual(status, statuses.BLOCKED)
        self.assertEqual(reason, emptyset.AGGREGATION_SET_EMPTY)
        self.assertEqual(emptyset.require_non_empty(1)[0], statuses.PASS)

    def test_the_non_evidence_state_can_never_be_absorbed_into_a_pass(self):
        """The reason ``blocked`` was chosen rather than a new enum value."""
        self.assertEqual(
            statuses.aggregate([statuses.PASS, statuses.BLOCKED]), statuses.BLOCKED
        )
        self.assertEqual(
            statuses.aggregate([statuses.FAIL, statuses.BLOCKED]), statuses.FAIL
        )
        self.assertEqual(statuses.exit_code(statuses.BLOCKED), statuses.EXIT_BLOCKED)


class EngineFixture(unittest.TestCase):
    """A throwaway runtime area, shaped like a real one."""

    BLOCK = "fixture-block"
    PHASES = ("preflight", "offline-final")

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="empty-aggregation-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.results = self.root / "results"
        self.evidence = self.root / "evidence"
        self.raw = self.root / "raw-logs"
        for directory in (self.results, self.evidence, self.raw):
            directory.mkdir(parents=True)
        for phase in self.PHASES:
            self._write_phase(phase, raw_logs=2)

    def _write_phase(self, phase, *, raw_logs):
        digests = []
        checks = []
        for index in range(raw_logs):
            name = f"{phase}-{index}.log"
            payload = f"{phase}:{index}".encode("utf-8")
            (self.raw / name).write_bytes(payload)
            import hashlib

            digest = hashlib.sha256(payload).hexdigest()
            digests.append(digest)
            checks.append({"raw_log_name": name, "raw_log_sha256": digest})
        (self.results / f"{self.BLOCK}.{phase}.json").write_text(
            json.dumps({"status": "pass", "checks": checks}), encoding="utf-8"
        )
        (self.evidence / f"{self.BLOCK}.{phase}.json").write_text(
            json.dumps({"raw_log_sha256": digests}), encoding="utf-8"
        )

    def aggregate_evidence(self):
        """The engine's own walk over this fixture — not a re-implementation.

        The per phase counting is tools.gates.evidence.phase_evidence_counts,
        the same function the engine calls, so a drift between engine and test
        is impossible by construction. Only the fold over phases is local, and
        it is the same three line precedence the engine applies.
        """
        overall = statuses.PASS
        issues = []
        hard = False
        declared_total = 0
        verified_total = 0
        for phase in self.PHASES:
            record = json.loads(
                (self.evidence / f"{self.BLOCK}.{phase}.json").read_text(encoding="utf-8")
            )
            result_path = self.results / f"{self.BLOCK}.{phase}.json"
            result = (
                json.loads(result_path.read_text(encoding="utf-8"))
                if result_path.is_file()
                else None
            )
            counts = evidence_module.phase_evidence_counts(
                phase, record=record, result=result, raw_dir=self.raw
            )
            declared_total += counts.declared
            verified_total += counts.verified
            for reason in counts.issues:
                issues.append((phase, reason))
                hard = True
            status, reason = emptyset.verdict(counts.verified, counts.declared)
            if status != statuses.PASS:
                issues.append((phase, reason))
                overall = emptyset.worse(overall, status)
        if hard:
            return statuses.FAIL, issues, declared_total, verified_total
        return overall, issues, declared_total, verified_total


class TestSharpening(EngineFixture):
    """The case that used to report ``evidence_complete`` while establishing nothing."""

    def test_a_withdrawn_result_no_longer_passes(self):
        target = self.results / f"{self.BLOCK}.offline-final.json"
        self.assertTrue(target.is_file())
        target.unlink()
        # Rule R9: the withdrawal is established before the engine is asked.
        self.assertFalse(target.is_file(), "the stored result was not removed")

        status, issues, declared, verified = self.aggregate_evidence()
        self.assertEqual(status, statuses.BLOCKED)
        self.assertIn(
            ("offline-final", emptyset.AGGREGATION_SET_EMPTY), issues
        )
        # The declared expectation survived the withdrawal — which is exactly
        # why the emptiness is detectable at all.
        self.assertEqual(declared, 4)
        self.assertEqual(verified, 2)

    def test_the_counts_make_a_vacuous_run_visible_in_the_report(self):
        """An empty issue list is what a clean and a vacuous run share."""
        target = self.results / f"{self.BLOCK}.offline-final.json"
        target.write_text(json.dumps({"status": "pass", "checks": []}), encoding="utf-8")
        self.assertEqual(
            json.loads(target.read_text(encoding="utf-8"))["checks"],
            [],
            "the result was not emptied",
        )
        status, _issues, declared, verified = self.aggregate_evidence()
        self.assertEqual(status, statuses.BLOCKED)
        self.assertLess(verified, declared)


class TestCounter(EngineFixture):
    """What was already correct must stay correct."""

    def test_a_complete_run_still_passes(self):
        status, issues, declared, verified = self.aggregate_evidence()
        self.assertEqual(status, statuses.PASS)
        self.assertEqual(issues, [])
        self.assertEqual(declared, verified)
        self.assertEqual(declared, 4)

    def test_a_tampered_raw_log_still_fails(self):
        target = self.raw / "preflight-0.log"
        before = target.read_bytes()
        target.write_bytes(before + b"x")
        self.assertNotEqual(target.read_bytes(), before, "the tampering had no effect")
        status, issues, _declared, _verified = self.aggregate_evidence()
        self.assertEqual(status, statuses.FAIL)
        self.assertIn(("preflight", "raw_log_digest_mismatch"), issues)

    def test_a_failure_outranks_a_non_evidence_state(self):
        """Both conditions at once must not soften the failure."""
        tampered = self.raw / "preflight-0.log"
        before = tampered.read_bytes()
        tampered.write_bytes(before + b"x")
        self.assertNotEqual(tampered.read_bytes(), before, "the tampering had no effect")
        withdrawn = self.results / f"{self.BLOCK}.offline-final.json"
        withdrawn.unlink()
        self.assertFalse(withdrawn.is_file(), "the stored result was not removed")

        status, _issues, _declared, _verified = self.aggregate_evidence()
        self.assertEqual(status, statuses.FAIL)


class TestTheExceptionIsNarrow(EngineFixture):
    """A phase that really declares nothing is allowed to verify nothing."""

    def test_a_phase_without_declared_raw_logs_passes_as_derived_empty(self):
        self._write_phase("offline-final", raw_logs=0)
        record = json.loads(
            (self.evidence / f"{self.BLOCK}.offline-final.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["raw_log_sha256"], [], "the phase still declares logs")
        status, issues, declared, verified = self.aggregate_evidence()
        self.assertEqual(status, statuses.PASS)
        self.assertEqual(issues, [])
        self.assertEqual(declared, 2)
        self.assertEqual(verified, 2)

    def test_the_exception_does_not_extend_to_a_phase_that_declares_logs(self):
        self._write_phase("offline-final", raw_logs=1)
        (self.results / f"{self.BLOCK}.offline-final.json").write_text(
            json.dumps({"status": "pass", "checks": []}), encoding="utf-8"
        )
        self.assertEqual(
            json.loads(
                (self.results / f"{self.BLOCK}.offline-final.json").read_text(encoding="utf-8")
            )["checks"],
            [],
            "the result was not emptied",
        )
        status, _issues, _declared, _verified = self.aggregate_evidence()
        self.assertEqual(status, statuses.BLOCKED)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
