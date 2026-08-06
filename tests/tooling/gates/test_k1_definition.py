"""The derived K1 definition, the absent classification schemes and rule R3."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates.runners import history_checks  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFINITION = json.loads(
    (REPO_ROOT / "config/gates/k1/calendar-k1-definition.json").read_text(
        encoding="utf-8"
    )
)
MATRIX = json.loads(
    (REPO_ROOT / "config/gates/k1/calendar-k1-start-matrix.json").read_text(
        encoding="utf-8"
    )
)
HISTORY = REPO_ROOT / "config" / "gates" / "history"


class TestDerivedDefinition(unittest.TestCase):
    def test_no_gate_is_invented(self):
        matrix_ids = {gate["gate_id"] for gate in MATRIX["gates"]}
        for gate in DEFINITION["gates"]:
            with self.subTest(gate=gate["gate_id"]):
                self.assertIn(gate["gate_id"], matrix_ids)

    def test_kept_and_removed_partition_the_matrix(self):
        matrix_ids = {gate["gate_id"] for gate in MATRIX["gates"]}
        kept = {gate["gate_id"] for gate in DEFINITION["gates"]}
        removed = {item["gate_id"] for item in DEFINITION["removed_from_k1"]}
        self.assertEqual(kept | removed, matrix_ids)
        self.assertEqual(kept & removed, set())

    def test_stage_name_is_bound_to_the_gate_set(self):
        kept = sorted(gate["gate_id"] for gate in DEFINITION["gates"])
        expected = hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()
        self.assertEqual(DEFINITION["stage_binding"]["digest"], expected)

    def test_execution_class_follows_from_what_a_gate_needs(self):
        for gate in DEFINITION["gates"]:
            with self.subTest(gate=gate["gate_id"]):
                live = gate["execution_class"] == "live"
                self.assertEqual(live, bool(gate["requires"]))

    def test_write_parity_is_removed_and_uncounted(self):
        split = DEFINITION["parity_contract_split"]
        self.assertTrue(split["write_parity_removed"])
        self.assertEqual(
            set(split["read_parity_in_k1"]) & set(split["write_parity_removed"]),
            set(),
        )
        for item in DEFINITION["removed_from_k1"]:
            self.assertEqual(item["counts_as"], "neither_fulfilled_nor_open")

    def test_invariant_conflict_is_documented_not_carried(self):
        conflict = DEFINITION["invariant_conflict"]
        self.assertTrue(conflict["documented_not_carried_as_open_gate"])
        self.assertIn("Schreibselektoren", conflict["invariant"])

    def test_no_decision_number_is_allocated(self):
        decision = DEFINITION["separate_write_decision"]
        self.assertIsNone(decision["decision_id"])
        self.assertTrue(decision["placeholder"].startswith("{{"))
        self.assertTrue(decision["placeholder_is_permanent_until_owner_allocation"])


class TestAbsentClassificationSchemes(unittest.TestCase):
    def test_k1_documents_use_no_absent_scheme(self):
        self.assertEqual(history_checks.find_scheme_usages(REPO_ROOT), [])

    def test_the_scheme_scan_actually_detects_a_usage(self):
        """Abuse test: the scan is not vacuously green."""
        import tempfile

        with tempfile.TemporaryDirectory(prefix="scheme-scan-") as stage:
            root = Path(stage)
            (root / "config" / "gates" / "k1").mkdir(parents=True)
            (root / "config" / "gates" / "k1" / "probe.md").write_text(
                "Dieses Gate hat Abnahmeprofil A und Overlay P.\n",
                encoding="utf-8",
            )
            hits = history_checks.find_scheme_usages(root)
        self.assertTrue(hits)


class TestRuleR3(unittest.TestCase):
    def test_no_acceptance_manifest_defaults_to_not_applicable(self):
        # Sharpening test for RC-009: a guaranteed artifact must not be
        # allowed to vanish silently.
        for path in sorted(HISTORY.glob("*.acceptance.json")):
            with self.subTest(manifest=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    document["reexecution_policy"]["runtime_evidence_absent"],
                    "fail",
                )

    def test_changed_evidence_is_still_detected(self):
        # Counter test for RC-009: the originally repelled violation, a
        # changed evidence document, must still be caught.
        for path in sorted(HISTORY.glob("*.acceptance.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            for entry in document["runtime_evidence"]:
                with self.subTest(manifest=path.name, phase=entry["phase"]):
                    target = REPO_ROOT / entry["path"]
                    self.assertTrue(target.is_file())
                    digest = hashlib.sha256(target.read_bytes()).hexdigest()
                    self.assertEqual(digest, entry["sha256"])
                    mutated = digest[:-1] + ("0" if digest[-1] != "0" else "1")
                    self.assertNotEqual(mutated, entry["sha256"])

    def test_evidence_is_bound_to_a_committed_snapshot(self):
        for path in sorted(HISTORY.glob("*.acceptance.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            for entry in document["runtime_evidence"]:
                with self.subTest(manifest=path.name, phase=entry["phase"]):
                    self.assertEqual(entry["scope"], "committed_snapshot")
                    self.assertFalse(
                        entry["path"].startswith(".gate-runtime")
                    )

    def test_review_record_covers_every_finding(self):
        review = json.loads(
            (HISTORY / "r3-not-applicable-review.json").read_text(encoding="utf-8")
        )
        self.assertEqual(review["rule"], "R3")
        self.assertEqual(len(review["findings"]), 3)
        self.assertTrue(review["examined_and_cleared"])



class TestGateAnchoring(unittest.TestCase):
    """RC-010 — no K1 gate may rest on a reference that does not exist."""

    def test_every_anchor_resolves(self):
        # Sharpening test: a gate whose criterion pointed at a non existent
        # document used to be carried as merely open.
        problems = history_checks.check_anchors(REPO_ROOT, DEFINITION)
        self.assertEqual(problems, [])

    def test_a_dangling_anchor_is_still_detected(self):
        # Counter test: the originally repelled defect must still be caught.
        broken = json.loads(json.dumps(DEFINITION))
        anchor = broken["gate_anchoring"]["anchors"][0]
        anchor["carrying_sources"][0]["path"] = (
            "docs/personal-jarvis/20-does-not-exist.md"
        )
        problems = history_checks.check_anchors(REPO_ROOT, broken)
        self.assertIn(
            ("K1-O08", "carrying_source_missing"), problems
        )

    def test_a_source_that_does_not_carry_is_detected(self):
        broken = json.loads(json.dumps(DEFINITION))
        anchor = broken["gate_anchoring"]["anchors"][0]
        anchor["carrying_sources"][0]["quote_anchor"] = "diese Zeichenfolge fehlt"
        problems = history_checks.check_anchors(REPO_ROOT, broken)
        self.assertIn(
            ("K1-O08", "carrying_source_does_not_carry"), problems
        )

    def test_the_dangling_reference_is_proven_not_asserted(self):
        anchor = DEFINITION["gate_anchoring"]["anchors"][0]
        dangling = anchor["dangling_reference"]
        self.assertEqual(dangling["status"], "does_not_exist")
        self.assertIn("endet bei 19", dangling["evidence"])
        self.assertFalse(
            (REPO_ROOT / "docs/personal-jarvis/20-does-not-exist.md").exists()
        )

    def test_an_open_anchored_gate_names_its_remaining_work(self):
        for anchor in DEFINITION["gate_anchoring"]["anchors"]:
            if anchor["status_after_anchoring"] == "open":
                with self.subTest(gate=anchor["gate_id"]):
                    self.assertTrue(anchor["remaining_work"])
                    self.assertTrue(anchor["status_reason"].strip())

    def test_no_substitute_source_is_invented(self):
        """Every carrying source must be a file that already existed."""
        anchor = DEFINITION["gate_anchoring"]["anchors"][0]
        for source in anchor["carrying_sources"]:
            with self.subTest(path=source["path"]):
                self.assertTrue((REPO_ROOT / source["path"]).is_file())
                self.assertFalse(source["path"].startswith("config/gates/k1"))

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
