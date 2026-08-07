"""The B0f method findings: unit locality and the Slack isolation proof.

The unit-locality record claims an ``open_gap``. That claim is held to two
mechanical facts re-derived here, never quoted: the sweep really does lose a
perturbation the moment it moves into a called helper (the minimal case),
and connecting call edges between corpus units really exist, so the boundary
matters. The classification vocabulary itself is enforced through the gate
mode: a made-up classification falls, and ``explicitly_out_of_contract``
without an owner decision falls — the tooling cannot create that decision.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.gates import astscan  # noqa: E402
from tools.gates.runners import b0f_checks  # noqa: E402

HELPER_FORM = """
    def _prepare(mock):
        mock.side_effect = OSError("boom")

    def test_fallback(mock, agent_factory):
        _prepare(mock)
        agent = agent_factory()
        assert agent.temperature == 0.7
    """

INLINE_FORM = """
    def test_fallback(mock, agent_factory):
        mock.side_effect = OSError("boom")
        agent = agent_factory()
        assert agent.temperature == 0.7
    """


class TestTheGapIsReal(unittest.TestCase):
    def test_the_unit_locality_gap_is_mechanically_real(self):
        helper = astscan.scan_source("tests/fx.py", textwrap.dedent(HELPER_FORM))
        inline = astscan.scan_source("tests/fx.py", textwrap.dedent(INLINE_FORM))
        self.assertEqual(
            [candidate.candidate_class for candidate in inline],
            ["unobserved_error_injection"],
        )
        self.assertEqual(helper, [], "the sweep now crosses unit boundaries; "
                                     "re-classify the unit-locality finding")

    def test_connecting_call_edges_exist_in_the_real_corpus(self):
        from tools.gates import astcorpus

        corpus = astcorpus.derive(REPO_ROOT)
        edges = 0
        for key, units in corpus.units.items():
            names = {unit.qualname.rsplit(".", 1)[-1]: unit for unit in units}
            for unit in units:
                for node in ast.walk(unit.node):
                    if isinstance(node, ast.Call):
                        name = getattr(node.func, "id", "") or getattr(
                            node.func, "attr", ""
                        )
                        target = names.get(name)
                        if target is not None and target is not unit:
                            edges += 1
            if edges:
                break
        self.assertGreater(edges, 0, "no connecting unit-to-unit call edges")

    def test_the_committed_record_classifies_the_gap_it_proves(self):
        record = json.loads(
            (REPO_ROOT / "config" / "governance" / "b0f-unit-locality.json").read_text()
        )
        self.assertEqual(record["classification"], "open_gap")
        demo = record["minimal_case"]["demonstration"]
        file_part, _, fragment = demo.partition("::")
        source = (REPO_ROOT / file_part).read_text(encoding="utf-8")
        self.assertIn(fragment, source)


class ClassificationFixture(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="b0f-method-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "config" / "governance").mkdir(parents=True)
        self._previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self._previous_cwd)
        self.report = self.root / "gate-report.json"
        patcher = mock.patch.dict(os.environ, {"GATE_REPORT": str(self.report)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_mode(self, finding):
        (self.root / "config" / "governance" / "b0f-unit-locality.json").write_text(
            json.dumps(finding), encoding="utf-8"
        )
        b0f_checks.mode_method(None)
        payload = json.loads(self.report.read_text(encoding="utf-8"))
        return sorted(failure["code"] for failure in payload["failures"])

    def test_an_unknown_classification_falls(self):
        codes = self.run_mode({"classification": "quietly_accepted"})
        self.assertIn("classification_unknown", codes)

    def test_out_of_contract_without_an_owner_decision_falls(self):
        codes = self.run_mode({"classification": "explicitly_out_of_contract"})
        self.assertIn("owner_decision_missing", codes)

    def test_covered_elsewhere_needs_resolvable_proof_tests(self):
        codes = self.run_mode(
            {
                "classification": "covered_elsewhere",
                "covering_check": {
                    "positive_test": "tests/nonexistent.py::test_x",
                    "negative_test": "tests/nonexistent.py::test_y",
                },
            }
        )
        self.assertIn("covering_proof_missing", codes)

    def test_an_open_gap_needs_its_minimal_case(self):
        codes = self.run_mode(
            {
                "classification": "open_gap",
                "minimal_case": {"demonstration": "tests/gone.py::test_gone"},
            }
        )
        self.assertIn("minimal_case_unresolved", codes)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
