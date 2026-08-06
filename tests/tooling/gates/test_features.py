"""Feature completeness against the immediate predecessor's feature list."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import features as features_module  # noqa: E402
from tools.gates import manifest as manifest_module  # noqa: E402
from tools.gates import statuses  # noqa: E402

PREDECESSOR = {
    "artifact_id": "prompt-fixture",
    "artifact_version": "1",
    "features": [
        {"feature_id": "FIX-001", "required": True, "description": "first"},
        {"feature_id": "FIX-002", "required": True, "description": "second"},
        {"feature_id": "FIX-003", "required": False, "description": "optional"},
    ],
}


def lineage_feature(feature_id, **overrides):
    feature = {
        "feature_id": feature_id,
        "required": True,
        "description": "mapped feature",
        "current_location": "tools/gates/features.py",
        "verification": {"type": "file", "ref": "tools/gates/features.py"},
        "status": "pass",
    }
    feature.update(overrides)
    return feature


class TestFeatureLineage(_support.TempEnvMixin):
    def setUp(self):
        super().setUp()
        self.workdir = self.tmp_path / "artifacts"
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.predecessor_path = self.workdir / "predecessor.json"
        self.lineage_path = self.workdir / "lineage.json"
        self._write_predecessor(PREDECESSOR)

    def _write_predecessor(self, data):
        payload = json.dumps(data, indent=2) + "\n"
        self.predecessor_path.write_text(payload, encoding="utf-8")
        self.digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _write_lineage(self, features, **overrides):
        lineage = {
            "schema_version": 1,
            "artifact_id": "block-fixture",
            "artifact_version": "1.0.0",
            "predecessor_artifact_id": "prompt-fixture",
            "predecessor_feature_list_sha256": self.digest,
            "features": features,
        }
        lineage.update(overrides)
        self.lineage_path.write_text(
            json.dumps(lineage, indent=2) + "\n", encoding="utf-8"
        )

    def _validate(self):
        return features_module.validate_lineage(
            lineage_path=self.lineage_path,
            predecessor_path=self.predecessor_path,
            worktree=_support.REPO_ROOT,
        )

    def test_complete_mapping_passes(self):
        self._write_lineage([lineage_feature("FIX-001"), lineage_feature("FIX-002")])
        report = self._validate()
        self.assertEqual(report["status"], statuses.PASS)
        self.assertEqual(report["counts"]["expected"], 2)
        self.assertEqual(report["counts"]["mapped"], 2)
        self.assertEqual(report["counts"]["missing"], 0)

    def test_missing_required_feature_fails(self):
        self._write_lineage([lineage_feature("FIX-001")])
        report = self._validate()
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertEqual(report["counts"]["missing"], 1)
        self.assertIn(
            "required_feature_unmapped",
            {entry["reason_code"] for entry in report["features"]},
        )

    def test_unmapped_rename_fails(self):
        self._write_lineage(
            [lineage_feature("FIX-001"), lineage_feature("FIX-002B")]
        )
        report = self._validate()
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertEqual(report["counts"]["missing"], 1)

    def test_declared_rename_is_accepted_and_counted_as_changed(self):
        self._write_lineage(
            [
                lineage_feature("FIX-001"),
                lineage_feature("FIX-002B", predecessor_feature_id="FIX-002"),
            ]
        )
        report = self._validate()
        self.assertEqual(report["status"], statuses.PASS)
        self.assertEqual(report["counts"]["mapped"], 2)
        self.assertEqual(report["counts"]["changed"], 1)

    def test_wrong_predecessor_hash_fails(self):
        self._write_lineage([lineage_feature("FIX-001"), lineage_feature("FIX-002")])
        lineage = json.loads(self.lineage_path.read_text(encoding="utf-8"))
        lineage["predecessor_feature_list_sha256"] = "f" * 64
        self.lineage_path.write_text(json.dumps(lineage, indent=2), encoding="utf-8")
        report = self._validate()
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertEqual(report["reason_code"], "predecessor_feature_list_hash_mismatch")

    def test_missing_predecessor_list_is_blocked(self):
        self._write_lineage([lineage_feature("FIX-001"), lineage_feature("FIX-002")])
        self.predecessor_path.unlink()
        report = self._validate()
        self.assertEqual(report["status"], statuses.BLOCKED)
        self.assertEqual(report["reason_code"], "predecessor_feature_list_missing")
        # Completeness must not be claimed in that case.
        self.assertEqual(report["counts"]["mapped"], 0)

    def test_wrong_predecessor_artifact_fails(self):
        self._write_lineage(
            [lineage_feature("FIX-001"), lineage_feature("FIX-002")],
            predecessor_artifact_id="prompt-somewhere-else",
        )
        report = self._validate()
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertEqual(report["reason_code"], "predecessor_artifact_mismatch")

    def test_required_feature_must_not_be_not_applicable(self):
        self._write_lineage(
            [
                lineage_feature("FIX-001"),
                lineage_feature("FIX-002", status="not_applicable"),
            ]
        )
        report = self._validate()
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertIn(
            "required_feature_declared_not_applicable",
            {entry["reason_code"] for entry in report["features"]},
        )

    def test_dropped_requirement_needs_an_owner_decision(self):
        self._write_lineage(
            [
                lineage_feature("FIX-001"),
                lineage_feature("FIX-002", required=False),
            ]
        )
        report = self._validate()
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertIn(
            "requirement_dropped_without_owner_decision",
            {entry["reason_code"] for entry in report["features"]},
        )

    def test_dropped_requirement_with_owner_decision_is_changed(self):
        self._write_lineage(
            [
                lineage_feature("FIX-001"),
                lineage_feature(
                    "FIX-002",
                    required=False,
                    owner_decision="Lukas 2026-08-05: moved to the follow-up block.",
                ),
            ]
        )
        report = self._validate()
        self.assertEqual(report["status"], statuses.PASS)
        self.assertEqual(report["counts"]["changed"], 1)

    def test_unresolvable_verification_fails(self):
        self._write_lineage(
            [
                lineage_feature("FIX-001"),
                lineage_feature(
                    "FIX-002",
                    verification={"type": "file", "ref": "tools/gates/nope.py"},
                ),
            ]
        )
        report = self._validate()
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertIn(
            "feature_verification_unresolved",
            {entry["reason_code"] for entry in report["features"]},
        )

    def test_free_text_cannot_claim_completeness(self):
        # A "complete" claim in a description changes nothing about the counts.
        self._write_lineage(
            [
                lineage_feature(
                    "FIX-001", description="all mandatory features are complete"
                )
            ]
        )
        report = self._validate()
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertGreater(report["counts"]["missing"], 0)

    def test_declared_failure_status_propagates(self):
        self._write_lineage(
            [lineage_feature("FIX-001"), lineage_feature("FIX-002", status="fail")]
        )
        self.assertEqual(self._validate()["status"], statuses.FAIL)

    def test_unknown_feature_field_fails(self):
        feature = lineage_feature("FIX-001")
        feature["surprise"] = True
        self._write_lineage([feature, lineage_feature("FIX-002")])
        report = self._validate()
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertEqual(report["reason_code"], "feature_lineage_invalid")


class TestBlockLineage(unittest.TestCase):
    def test_all_24_mandatory_block_features_are_evidenced(self):
        manifest = manifest_module.load(_support.BLOCK_MANIFEST)
        lineage = manifest.data["feature_lineage"]
        report = features_module.validate_lineage(
            lineage_path=_support.REPO_ROOT / lineage["lineage_file"],
            predecessor_path=_support.REPO_ROOT / lineage["predecessor_file"],
            worktree=_support.REPO_ROOT,
            manifest=manifest,
        )
        self.assertEqual(report["counts"]["expected"], 24)
        self.assertEqual(report["counts"]["mapped"], 24)
        self.assertEqual(report["counts"]["missing"], 0)
        self.assertEqual(report["status"], statuses.PASS)

    def test_predecessor_digest_matches_the_lineage_pin(self):
        manifest = manifest_module.load(_support.BLOCK_MANIFEST)
        lineage_path = (
            _support.REPO_ROOT / manifest.data["feature_lineage"]["lineage_file"]
        )
        predecessor_path = (
            _support.REPO_ROOT / manifest.data["feature_lineage"]["predecessor_file"]
        )
        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        self.assertEqual(
            lineage["predecessor_feature_list_sha256"],
            features_module.predecessor_digest(predecessor_path),
        )

    def test_a_removed_mandatory_feature_is_detected(self):
        manifest = manifest_module.load(_support.BLOCK_MANIFEST)
        lineage_path = (
            _support.REPO_ROOT / manifest.data["feature_lineage"]["lineage_file"]
        )
        predecessor_path = (
            _support.REPO_ROOT / manifest.data["feature_lineage"]["predecessor_file"]
        )
        lineage = copy.deepcopy(json.loads(lineage_path.read_text(encoding="utf-8")))
        lineage["features"] = [
            entry for entry in lineage["features"] if entry["feature_id"] != "B0A1-012"
        ]
        import tempfile

        with tempfile.TemporaryDirectory(prefix="lineage-") as tmp:
            broken = Path(tmp) / "lineage.json"
            broken.write_text(json.dumps(lineage, indent=2), encoding="utf-8")
            report = features_module.validate_lineage(
                lineage_path=broken,
                predecessor_path=predecessor_path,
                worktree=_support.REPO_ROOT,
                manifest=manifest,
            )
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertEqual(report["counts"]["missing"], 1)


class TestGovernanceLineage(unittest.TestCase):
    """B0a-2 keeps all 24 predecessor features and evidences its own 38."""

    def setUp(self):
        self.manifest = manifest_module.load(
            _support.REPO_ROOT
            / "config"
            / "gates"
            / "blocks"
            / "b0a-2-governance.json"
        )
        lineage = self.manifest.data["feature_lineage"]
        self.lineage_path = _support.REPO_ROOT / lineage["lineage_file"]
        self.predecessor_path = _support.REPO_ROOT / lineage["predecessor_file"]

    def _validate(self, lineage=None):
        import tempfile

        if lineage is None:
            return features_module.validate_lineage(
                lineage_path=self.lineage_path,
                predecessor_path=self.predecessor_path,
                worktree=_support.REPO_ROOT,
                manifest=self.manifest,
                own_prefix="B0A2-",
            )
        with tempfile.TemporaryDirectory(prefix="lineage-b0a2-") as tmp:
            broken = Path(tmp) / "lineage.json"
            broken.write_text(json.dumps(lineage, indent=2), encoding="utf-8")
            return features_module.validate_lineage(
                lineage_path=broken,
                predecessor_path=self.predecessor_path,
                worktree=_support.REPO_ROOT,
                manifest=self.manifest,
                own_prefix="B0A2-",
            )

    def _lineage(self):
        return json.loads(self.lineage_path.read_text(encoding="utf-8"))

    def test_the_predecessor_is_the_b0a_1_feature_manifest(self):
        lineage = self._lineage()
        self.assertEqual(lineage["predecessor_artifact_id"], "block-b0a-1-tooling")
        self.assertEqual(
            lineage["predecessor_feature_list_sha256"],
            features_module.predecessor_digest(self.predecessor_path),
        )

    def test_counts_are_24_and_38_with_nothing_missing(self):
        report = self._validate()
        self.assertEqual(report["status"], statuses.PASS)
        self.assertEqual(report["counts"]["expected"], 24)
        self.assertEqual(report["counts"]["mapped"], 24)
        self.assertEqual(report["counts"]["missing"], 0)
        self.assertEqual(report["own_counts"]["expected"], 38)
        self.assertEqual(report["own_counts"]["verified"], 38)
        self.assertEqual(report["own_counts"]["missing"], 0)

    def test_all_38_b0a2_ids_are_present(self):
        ids = {
            entry["feature_id"]
            for entry in self._lineage()["features"]
            if entry["feature_id"].startswith("B0A2-")
        }
        self.assertEqual(
            ids, {f"B0A2-{number:03d}" for number in range(1, 39)}
        )

    def test_a_removed_b0a1_feature_fails(self):
        lineage = self._lineage()
        lineage["features"] = [
            entry
            for entry in lineage["features"]
            if entry["feature_id"] != "B0A1-012"
        ]
        report = self._validate(lineage)
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertEqual(report["counts"]["missing"], 1)

    def test_a_removed_b0a2_feature_is_detected_by_the_declared_count(self):
        lineage = self._lineage()
        lineage["features"] = [
            entry
            for entry in lineage["features"]
            if entry["feature_id"] != "B0A2-023"
        ]
        report = self._validate(lineage)
        declared = self.manifest.data["feature_lineage"]["own_expected"]
        self.assertEqual(declared, 38)
        self.assertEqual(report["own_counts"]["expected"], 37)
        self.assertNotEqual(report["own_counts"]["expected"], declared)

    def test_a_renamed_feature_without_mapping_fails(self):
        lineage = self._lineage()
        for entry in lineage["features"]:
            if entry["feature_id"] == "B0A1-018":
                entry["feature_id"] = "B0A1-018B"
        report = self._validate(lineage)
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertIn(
            "required_feature_unmapped",
            {entry["reason_code"] for entry in report["features"]},
        )

    def test_an_own_feature_declared_not_applicable_fails(self):
        lineage = self._lineage()
        for entry in lineage["features"]:
            if entry["feature_id"] == "B0A2-031":
                entry["status"] = "not_applicable"
        report = self._validate(lineage)
        self.assertEqual(report["status"], statuses.FAIL)
        self.assertIn(
            "required_feature_declared_not_applicable",
            {entry["reason_code"] for entry in report["features"]},
        )

    def test_an_own_feature_with_an_unresolvable_proof_fails(self):
        lineage = self._lineage()
        for entry in lineage["features"]:
            if entry["feature_id"] == "B0A2-021":
                entry["verification"] = {"type": "gate_check", "ref": "of-nonexistent"}
        report = self._validate(lineage)
        self.assertEqual(report["status"], statuses.FAIL)

    def test_free_text_cannot_replace_a_missing_feature(self):
        lineage = self._lineage()
        lineage["features"] = [
            entry
            for entry in lineage["features"]
            if entry["feature_id"] != "B0A2-036"
        ]
        for entry in lineage["features"]:
            if entry["feature_id"] == "B0A2-001":
                entry["description"] = "alle Merkmale sind vollstaendig nachgewiesen"
        report = self._validate(lineage)
        declared = self.manifest.data["feature_lineage"]["own_expected"]
        self.assertNotEqual(report["own_counts"]["expected"], declared)
        self.assertEqual(report["own_counts"]["expected"], 37)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
