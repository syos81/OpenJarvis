"""Evidence allowlist, raw log integrity and the PII canary matrix.

Only synthetic canary values are used (see ``tools/gates/canaries.py``). No
real contact, calendar, mail, banking or tenant data appears anywhere.
"""

from __future__ import annotations

import base64
import io
import json
import sys
import unittest
import unicodedata
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import EVIDENCE_SCHEMA_VERSION  # noqa: E402
from tools.gates import canaries  # noqa: E402
from tools.gates import engine as engine_module  # noqa: E402
from tools.gates import evidence as evidence_module  # noqa: E402
from tools.gates import gitutil  # noqa: E402
from tools.gates import manifest as manifest_module  # noqa: E402
from tools.gates import runner as runner_module  # noqa: E402
from tools.gates import sanitize  # noqa: E402
from tools.gates import signature as signature_module  # noqa: E402

VALID_EVIDENCE = {
    "run_id": "a" * 32,
    "block": "b0a-1-tooling",
    "phase": "preflight",
    "commit": "b" * 40,
    "manifest_digest": "c" * 64,
    "engine_version": "1.0.0",
    "status": "pass",
    "check_ids": ["pf-manifest", "pf-platform"],
    "reason_codes": ["check_passed"],
    "baseline_commit": None,
    "cause_signature_digest": [],
    "cache_state": "not_used",
    "platform_class": "darwin/x86_64/12.7.6",
    "raw_log_sha256": ["d" * 64],
    "started_at": "2026-08-05T10:00:00Z",
    "finished_at": "2026-08-05T10:00:05Z",
}

CANARY_RUNNER = '''#!/usr/bin/env python3
"""Synthetic runner that floods its output with canary values."""
import sys

VALUES = {values!r}

print("test_example (canary.Suite) ... FAIL")
for name, value in sorted(VALUES.items()):
    print(f"noise {{name}}: {{value}}")
    sys.stderr.write(f"stderr noise {{name}}: {{value}}\\n")
print("FAIL: test_example (canary.Suite)")
print("AssertionError: unexpected value")
print("Ran 1 test in 0.001s")
print("FAILED (failures=1)")
sys.exit(1)
'''

CANARY_MANIFEST = {
    "schema_version": 1,
    "block_id": "canary-block",
    "title": "Canary matrix block",
    "engine_min_version": "1.0.0",
    "required_phases": list(manifest_module.PHASES),
    "phase_definitions": {
        "preflight": {
            "applicable": True,
            "required": True,
            "reason": "Runs the synthetic canary runner.",
        },
        "targeted": {
            "applicable": False,
            "required": False,
            "declared_result": "not_applicable",
            "reason": "The canary block declares no targeted checks.",
        },
        "offline-final": {
            "applicable": False,
            "required": False,
            "declared_result": "not_applicable",
            "reason": "The canary block declares no offline checks.",
        },
        "platform-live": {
            "applicable": False,
            "required": False,
            "declared_result": "not_applicable",
            "reason": "The canary block performs no live acceptance.",
        },
        "module-final": {
            "applicable": True,
            "required": True,
            "reason": "Closing aggregation of the canary block.",
        },
    },
    "targeted_selection": {
        "base_ref": "main",
        "always": ["pf-canary"],
        "rules": [],
    },
    "checks": [
        {
            "check_id": "pf-canary",
            "phase": "preflight",
            "required": True,
            "description": "Synthetic runner emitting canary values.",
            "runner": {
                "type": "argv",
                "cwd": "worktree",
                "argv": ["${GATE_PYTHON}", "${GATE_WORKTREE}/canary_runner.py"],
            },
            "parser": "unittest",
            "timeout_seconds": 60,
            "baseline_eligible": False,
            "evidence_profile": "tooling",
        },
        {
            "check_id": "mf-canary",
            "phase": "module-final",
            "required": True,
            "description": "Closing check of the canary block.",
            "runner": {"type": "internal", "name": "module_final_phase_results"},
            "parser": "gate_json",
            "timeout_seconds": 60,
            "baseline_eligible": False,
            "evidence_profile": "tooling",
        },
    ],
    "baseline_policy": {
        "baseline_commit": "7986bee",
        "cause_signature_version": "cs-1",
        "owner_marker": "openjarvis-gate-baseline",
        "cache_enabled": False,
        "dependency_lock_paths": [],
        "config_digest_paths": [],
    },
    "platform_requirements": {
        "systems": ["Darwin"],
        "architectures": ["x86_64"],
        "min_python": "3.10",
    },
    "evidence_policy": {"sanitized_evidence": True, "raw_log_area": "runtime_only"},
    "feature_lineage": {
        "lineage_file": "features.lineage.json",
        "predecessor_file": "features.predecessor.json",
    },
    "product_guard": {
        "block_base_commit": "0" * 40,
        "allowed_paths": ["*"],
        "forbidden_paths": [],
    },
}


def assert_no_canary(testcase, value, label):
    hits = sanitize.find_canaries(value, canaries.CANARIES)
    testcase.assertEqual(hits, [], f"canary leaked into {label}: {hits}")


class TestEvidenceAllowlist(unittest.TestCase):
    def test_valid_evidence_is_accepted(self):
        record = evidence_module.build_evidence(**VALID_EVIDENCE)
        self.assertEqual(record["schema_version"], EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(sorted(record), sorted(evidence_module.ALLOWED_FIELDS))

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(evidence_module.EvidenceSchemaError):
            evidence_module.build_evidence(**VALID_EVIDENCE, note="looks fine")

    def test_missing_field_is_rejected(self):
        partial = dict(VALID_EVIDENCE)
        partial.pop("platform_class")
        with self.assertRaises(evidence_module.EvidenceSchemaError):
            evidence_module.build_evidence(**partial)

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(evidence_module.EvidenceSchemaError):
            evidence_module.build_evidence(**dict(VALID_EVIDENCE, status="green"))

    def test_unsorted_list_is_rejected(self):
        with self.assertRaises(evidence_module.EvidenceSchemaError):
            evidence_module.build_evidence(
                **dict(VALID_EVIDENCE, check_ids=["pf-platform", "pf-manifest"])
            )

    def test_free_text_has_no_home_in_evidence(self):
        # There is no "rest" area: every field is named and typed.
        self.assertNotIn("message", evidence_module.ALLOWED_FIELDS)
        self.assertNotIn("output", evidence_module.ALLOWED_FIELDS)
        self.assertNotIn("log", evidence_module.ALLOWED_FIELDS)

    def test_personal_data_in_a_valid_field_is_rejected(self):
        leaking = dict(VALID_EVIDENCE, block="b0a-1-tooling")
        leaking["reason_codes"] = ["check_passed"]
        record = dict(leaking)
        record["schema_version"] = EVIDENCE_SCHEMA_VERSION
        record["platform_class"] = "darwin/x86_64/12.7.6"
        record["check_ids"] = ["pf-manifest"]
        # Injecting an address-like value must be refused by the leak guard.
        record["reason_codes"] = ["check_passed"]
        record["cause_signature_digest"] = []
        with self.assertRaises(sanitize.EvidenceLeakError):
            sanitize.assert_clean(
                dict(record, run_id="a" * 32, block="mail@example.com")
            )


class TestRawLogIntegrity(_support.TempEnvMixin):
    def setUp(self):
        super().setUp()
        self.raw_log = self.runtime_dir / "raw-logs" / "sample.log"

    def test_digest_matches_written_content(self):
        digest = evidence_module.write_raw_log(self.raw_log, "complete tool output\n")
        self.assertEqual(digest, evidence_module.sha256_file(self.raw_log))
        ok, reason = evidence_module.verify_raw_log(self.raw_log, digest)
        self.assertTrue(ok)
        self.assertEqual(reason, "raw_log_verified")

    def test_missing_digest_is_detected(self):
        evidence_module.write_raw_log(self.raw_log, "x")
        self.assertEqual(
            evidence_module.verify_raw_log(self.raw_log, None),
            (False, "raw_log_digest_missing"),
        )

    def test_malformed_digest_is_detected(self):
        evidence_module.write_raw_log(self.raw_log, "x")
        for bad in ("abc", "z" * 64, "A" * 64):
            with self.subTest(digest=bad):
                ok, reason = evidence_module.verify_raw_log(self.raw_log, bad)
                self.assertFalse(ok)
                self.assertEqual(reason, "raw_log_digest_malformed")

    def test_absent_raw_log_is_detected(self):
        ok, reason = evidence_module.verify_raw_log(self.raw_log, "d" * 64)
        self.assertFalse(ok)
        self.assertEqual(reason, "raw_log_absent")

    def test_manipulation_is_detected(self):
        digest = evidence_module.write_raw_log(self.raw_log, "original output\n")
        self.raw_log.write_text("tampered output\n", encoding="utf-8")
        ok, reason = evidence_module.verify_raw_log(self.raw_log, digest)
        self.assertFalse(ok)
        self.assertEqual(reason, "raw_log_digest_mismatch")

    def test_raw_log_permissions_are_restrictive(self):
        evidence_module.write_raw_log(self.raw_log, "x")
        self.assertEqual(self.raw_log.stat().st_mode & 0o777, 0o600)

    def test_runtime_area_is_ignored_and_untracked(self):
        root = _support.REPO_ROOT
        self.assertTrue(gitutil.check_ignore(".gate-runtime/raw-logs/x.log", cwd=root))
        tracked = gitutil.tracked_files(cwd=root)
        self.assertEqual(
            [path for path in tracked if path.startswith(".gate-runtime/")], []
        )

    def test_evidence_never_stores_an_absolute_raw_log_path(self):
        record = evidence_module.build_evidence(**VALID_EVIDENCE)
        self.assertTrue(
            all(len(item) == 64 for item in record["raw_log_sha256"]),
        )


class TestCanaryMatrix(_support.TempEnvMixin):
    def setUp(self):
        super().setUp()
        self.repo = _support.make_repo(self.tmp_path / "canary-repo")
        (self.repo / "canary_runner.py").write_text(
            CANARY_RUNNER.format(values=canaries.CANARIES), encoding="utf-8"
        )
        manifest_dir = self.repo / "config" / "gates" / "blocks"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "canary-block.json").write_text(
            json.dumps(CANARY_MANIFEST, indent=2), encoding="utf-8"
        )
        _support.git(["add", "-A"], cwd=self.repo)
        _support.git(["commit", "--quiet", "-m", "canary fixture"], cwd=self.repo)
        self.manifest = manifest_module.load(manifest_dir / "canary-block.json")

    def _run(self):
        stderr = io.StringIO()
        gate = engine_module.GateEngine(
            worktree=self.repo, manifest=self.manifest, progress=stderr
        )
        result = gate.run_phase("preflight")
        return result, stderr.getvalue()

    def test_all_canary_classes_are_present_in_the_matrix(self):
        for expected in (
            "person_name",
            "email_address",
            "phone_number",
            "absolute_user_path",
            "document_subject",
            "external_object_id",
            "secret_token",
            "unicode_spelling",
        ):
            self.assertIn(expected, canaries.CANARIES)

    def test_raw_log_may_contain_the_canaries(self):
        result, _ = self._run()
        raw_name = result["checks"][0]["raw_log_name"]
        raw_log = (self.runtime_dir / "raw-logs" / raw_name).read_text(
            encoding="utf-8"
        )
        hits = {canary_id for canary_id, _ in sanitize.find_canaries(raw_log, canaries.CANARIES)}
        self.assertEqual(hits, set(canaries.CANARIES))

    def test_machine_json_carries_no_canary(self):
        result, _ = self._run()
        assert_no_canary(self, result, "result json")
        assert_no_canary(self, json.dumps(result), "serialised result json")

    def test_progress_output_carries_no_canary(self):
        _, progress = self._run()
        assert_no_canary(self, progress, "stderr progress")

    def test_sanitized_evidence_carries_no_canary(self):
        result, _ = self._run()
        evidence_path = (
            self.runtime_dir / "evidence" / "canary-block.preflight.json"
        )
        record = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence_module.validate_evidence(record)
        assert_no_canary(self, record, "sanitized evidence")
        assert_no_canary(self, result["evidence"], "embedded evidence")

    def test_handoff_material_carries_no_canary(self):
        result, _ = self._run()
        handoff = evidence_module.dump_evidence(result["evidence"])
        assert_no_canary(self, handoff, "handoff report material")

    def test_cause_signature_and_its_inputs_carry_no_canary(self):
        result, _ = self._run()
        raw_name = result["checks"][0]["raw_log_name"]
        raw_log = (self.runtime_dir / "raw-logs" / raw_name).read_text(
            encoding="utf-8"
        )
        stdout = raw_log.split("--- stdout ---", 1)[1]
        structured = runner_module.parse_unittest(stdout, "", 1)
        assert_no_canary(self, structured, "structured parser output")
        signature = signature_module.build_cause_signature(
            block_id="canary-block",
            check_id="pf-canary",
            runner_kind="argv",
            parser="unittest",
            structured=structured,
        )
        self.assertIsNotNone(signature)
        assert_no_canary(self, signature, "cause signature")

    def test_cache_metadata_carries_no_canary(self):
        from tools.gates import baseline as baseline_module

        structured = runner_module.parse_unittest(
            "\n".join(f"noise {value}" for value in canaries.CANARIES.values())
            + "\nFAIL: test_example (canary.Suite)\nRan 1 test in 0.0s\n",
            "",
            1,
        )
        signature = signature_module.build_cause_signature(
            block_id="canary-block",
            check_id="pf-canary",
            runner_kind="argv",
            parser="unittest",
            structured=structured,
        )
        payload = baseline_module.cache_result_from_structured(structured, 1, signature)
        assert_no_canary(self, payload, "cache metadata")

    def test_no_canary_file_is_tracked_in_this_repository(self):
        root = _support.REPO_ROOT
        for path in gitutil.tracked_files(cwd=root):
            candidate = root / path
            if not candidate.is_file() or candidate.suffix in {".png", ".pdf", ".lock"}:
                continue
            if candidate.stat().st_size > 1_000_000:
                continue
            content = candidate.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn(canaries.MARKER, content, f"canary marker in {path}")

    def test_encoded_and_normalised_variants_are_detected(self):
        value = canaries.CANARIES["person_name"]
        variants = {
            "plain": value,
            "base64": base64.b64encode(value.encode("utf-8")).decode("ascii"),
            "percent": urllib.parse.quote(value),
            "nfd": unicodedata.normalize("NFD", value),
            "case": value.upper(),
        }
        for kind, variant in sorted(variants.items()):
            with self.subTest(kind=kind):
                self.assertTrue(
                    sanitize.contains_canary(f"prefix {variant} suffix", value),
                    f"variant {kind} not detected",
                )

    def test_unrelated_text_is_not_reported_as_a_canary(self):
        self.assertEqual(
            sanitize.find_canaries(
                {"reason_code": "check_passed", "status": "pass"}, canaries.CANARIES
            ),
            [],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
