"""The B0e syntax tree sweeps: what they find, what they leave alone.

Every fixture below is a *source text*, never executed, and scanned through
the same entry point the gate uses (:func:`tools.gates.astscan.scan_source`).
The required cases from the block contract are all here:

* a genuine R9 case — a substitution that runs but can silently do nothing,
* harmless preparation that is correctly not a candidate,
* an injection whose effect nothing observes, and both observations that
  legitimately silence it,
* a genuine R10 case — absence normalised to emptiness and then walked,
* a harmless empty default that feeds no judgement,
* the mechanical suppressor: a unit that judges the length of the value,
* a non-empty sweep with zero findings staying zero findings,
* and the stability of the candidate binding under line movement.
"""

from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.gates import astscan  # noqa: E402


def scan_test_source(source):
    return astscan.scan_source("tests/fixture_module.py", textwrap.dedent(source))


def scan_tool_source(source):
    return astscan.scan_source("tools/fixture_module.py", textwrap.dedent(source))


def classes(candidates):
    return sorted(candidate.candidate_class for candidate in candidates)


class TestR9Detection(unittest.TestCase):
    """Rule R9 candidates: perturbations whose effect is not guaranteed."""

    def test_a_substitution_written_back_is_a_candidate(self):
        found = scan_test_source(
            """
            def test_breaks_the_package(target):
                target.write_text(target.read_text().replace("1.0.0", "1.0.1"))
                assert run(target) == "deny"
            """
        )
        self.assertEqual(classes(found), ["silent_substitution"])
        self.assertEqual(found[0].rule, astscan.RULE_R9)
        self.assertEqual(found[0].unit, "test_breaks_the_package")

    def test_the_model_defect_shape_is_found_even_though_it_runs(self):
        """The B0D-N1 shape: syntactically fine, semantically a possible no-op."""
        found = scan_test_source(
            """
            def test_migrated_literal(target):
                before = target.read_text()
                target.write_text(before.replace("gone-literal", "x", 1))
                assert decide(target) == "deny"
            """
        )
        self.assertEqual(classes(found), ["silent_substitution"])

    def test_plain_preparation_writes_are_not_candidates(self):
        found = scan_test_source(
            """
            def test_prepares_and_checks(target):
                target.write_text("fresh content")
                target.chmod(0o600)
                assert read_back(target) == "fresh content"
            """
        )
        self.assertEqual(found, [])

    def test_tolerant_ensure_absent_operations_are_a_stated_boundary(self):
        """``delenv(raising=False)`` and ``unlink(missing_ok=True)`` guarantee
        their after-state; they are excluded as a class, not per candidate."""
        found = scan_test_source(
            """
            def test_clean_environment(monkeypatch, path):
                monkeypatch.delenv("PROXY", raising=False)
                path.unlink(missing_ok=True)
                assert build() == "ok"
            """
        )
        self.assertEqual(found, [])

    def test_an_unobserved_error_injection_is_a_candidate(self):
        found = scan_test_source(
            """
            def test_fallback(monkeypatch):
                loader = Mock(side_effect=OSError("boom"))
                with patch("pkg.load_config", loader):
                    agent = Agent()
                assert agent.temperature == 0.7
            """
        )
        self.assertEqual(classes(found), ["unobserved_error_injection"])

    def test_a_raises_expectation_observes_the_injection(self):
        found = scan_test_source(
            """
            def test_error_propagates(monkeypatch):
                loader = Mock(side_effect=OSError("boom"))
                with patch("pkg.load_config", loader):
                    with pytest.raises(OSError):
                        Agent()
            """
        )
        self.assertEqual(found, [])

    def test_a_mock_observation_observes_the_injection(self):
        found = scan_test_source(
            """
            def test_fallback(monkeypatch):
                loader = Mock(side_effect=OSError("boom"))
                with patch("pkg.load_config", loader):
                    agent = Agent()
                loader.assert_called()
                assert agent.temperature == 0.7
            """
        )
        self.assertEqual(found, [])

    def test_a_masking_patch_is_a_candidate(self):
        found = scan_test_source(
            """
            def test_masked(monkeypatch):
                monkeypatch.setattr(pkg, "helper", fake, raising=False)
                assert pkg.run() == "ok"
            """
        )
        self.assertEqual(classes(found), ["masking_patch"])

    def test_an_ignored_removal_error_is_a_candidate(self):
        found = scan_tool_source(
            """
            def prepare(area):
                shutil.rmtree(area, ignore_errors=True)
                return run_in(area)
            """
        )
        self.assertEqual(classes(found), ["tolerant_removal_unverified"])

    def test_a_guarded_removal_in_a_test_is_a_candidate(self):
        found = scan_test_source(
            """
            def test_missing_artifact(path):
                if path.exists():
                    path.unlink()
                assert consume(path) == "blocked"
            """
        )
        self.assertEqual(classes(found), ["guarded_perturbation"])

    def test_a_swallowed_perturbation_is_a_candidate(self):
        found = scan_test_source(
            """
            def test_withdrawn(path):
                try:
                    path.unlink()
                except OSError:
                    pass
                assert consume(path) == "blocked"
            """
        )
        self.assertEqual(classes(found), ["swallowed_perturbation"])

    def test_a_read_permission_withdrawal_is_a_candidate(self):
        found = scan_test_source(
            """
            def test_unreadable(path):
                os.chmod(path, 0o000)
                assert consume(path) == "blocked"
            """
        )
        self.assertEqual(classes(found), ["permission_withdrawal"])


class TestR10Detection(unittest.TestCase):
    """Rule R10 candidates: absence normalised into a walkable emptiness."""

    def test_the_model_defect_shape_is_a_candidate(self):
        """``stored.get(phase) or {}`` walked for a verdict — the mf-evidence
        defect, reduced to its structure."""
        found = scan_tool_source(
            """
            def check(stored, phase):
                result = stored.get(phase) or {}
                issues = []
                for entry in result.get("checks", []):
                    if bad(entry):
                        issues.append(entry)
                return issues
            """
        )
        self.assertEqual(classes(found), ["empty_default_iteration"])
        self.assertEqual(found[0].ast_class, "For")

    def test_a_quantifier_over_the_default_is_a_candidate(self):
        found = scan_tool_source(
            """
            def check(document):
                entries = document.get("entries", [])
                return all(entry.get("ok") for entry in entries)
            """
        )
        self.assertIn("vacuous_quantifier", classes(found))

    def test_a_default_that_feeds_no_judgement_is_not_a_candidate(self):
        found = scan_tool_source(
            """
            def label(document):
                extras = document.get("extras", [])
                return "extras: " + repr(extras)
            """
        )
        self.assertEqual(found, [])

    def test_a_judged_length_suppresses_the_iteration(self):
        """A unit that compares ``len(...)`` of the value judges its
        emptiness; the walk cannot be silently vacuous."""
        found = scan_tool_source(
            """
            def check(document, expected):
                entries = document.get("entries", [])
                if len(entries) != expected:
                    raise ValueError("count mismatch")
                results = []
                for entry in entries:
                    results.append(entry)
                return results
            """
        )
        self.assertEqual(found, [])

    def test_a_loop_asserting_in_a_test_is_a_candidate(self):
        found = scan_test_source(
            """
            def test_every_entry(payload):
                rows = payload.get("rows", [])
                for row in rows:
                    assert row.total >= 0
            """
        )
        self.assertEqual(classes(found), ["vacuous_loop_assertion"])

    def test_a_clean_unit_yields_zero_findings_over_real_nodes(self):
        """Zero findings from a non-empty sweep is a result, not an accident:
        the unit demonstrably contains statements and none is a candidate."""
        source = textwrap.dedent(
            """
            def check(entries, expected):
                if len(entries) != expected:
                    raise ValueError("count mismatch")
                return [entry for entry in entries if entry.ok]
            """
        )
        found = astscan.scan_source("tools/fixture_module.py", source)
        self.assertEqual(found, [])
        import ast

        self.assertGreater(sum(1 for _ in ast.walk(ast.parse(source))), 10)


class TestCandidateBinding(unittest.TestCase):
    """The disposition binds to the node, not to a line number."""

    SOURCE = """
        def test_breaks_the_package(target):
            target.write_text(target.read_text().replace("1.0.0", "1.0.1"))
            assert run(target) == "deny"
        """

    def test_the_candidate_id_is_deterministic(self):
        first = scan_test_source(self.SOURCE)
        second = scan_test_source(self.SOURCE)
        self.assertEqual(
            [candidate.candidate_id for candidate in first],
            [candidate.candidate_id for candidate in second],
        )

    def test_line_movement_does_not_break_the_binding(self):
        moved = "\n\n\n" + textwrap.dedent(self.SOURCE)
        first = scan_test_source(self.SOURCE)
        second = astscan.scan_source("tests/fixture_module.py", moved)
        self.assertNotEqual(first[0].lineno, second[0].lineno)
        self.assertEqual(first[0].candidate_id, second[0].candidate_id)

    def test_changing_the_node_breaks_the_binding(self):
        changed = textwrap.dedent(self.SOURCE).replace('"1.0.1"', '"2.0.0"')
        self.assertIn('"2.0.0"', changed, "the fixture edit had no effect")
        first = scan_test_source(self.SOURCE)
        second = astscan.scan_source("tests/fixture_module.py", changed)
        self.assertNotEqual(first[0].candidate_id, second[0].candidate_id)

    def test_identical_twins_are_distinguished_by_occurrence(self):
        twinned = """
            def test_twice(target):
                target.write_text(target.read_text().replace("a", "b"))
                target.write_text(target.read_text().replace("a", "b"))
                assert run(target) == "deny"
            """
        found = scan_test_source(twinned)
        self.assertEqual(len(found), 2)
        self.assertNotEqual(found[0].candidate_id, found[1].candidate_id)
        self.assertEqual(
            sorted({found[0].occurrence, found[1].occurrence}), [0, 1]
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
