"""Public gate interface: argument handling, exit codes, phase execution."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import cli as cli_module  # noqa: E402
from tools.gates import engine as engine_module  # noqa: E402
from tools.gates import manifest as manifest_module  # noqa: E402
from tools.gates import statuses  # noqa: E402

GATE_SCRIPT = _support.REPO_ROOT / "scripts" / "gate.sh"

OK_RUNNER = '''#!/usr/bin/env python3
import json
import os
import sys

report = os.environ.get("GATE_REPORT")
if report:
    with open(report, "w", encoding="utf-8") as handle:
        json.dump(
            {"outcome": "passed", "failures": [], "diagnostics": [], "detail_count": 0},
            handle,
        )
print(json.dumps({"outcome": "passed"}))
sys.exit(0)
'''


def phase_definition(applicable, reason, declared=None, required=True):
    definition = {"applicable": applicable, "required": required, "reason": reason}
    if declared:
        definition["declared_result"] = declared
    return definition


def argv_check(check_id, phase):
    return {
        "check_id": check_id,
        "phase": phase,
        "required": True,
        "description": f"Synthetic {phase} check.",
        "runner": {
            "type": "argv",
            "cwd": "worktree",
            "argv": ["${GATE_PYTHON}", "${GATE_WORKTREE}/ok_runner.py"],
        },
        "parser": "gate_json",
        "timeout_seconds": 60,
        "baseline_eligible": False,
        "evidence_profile": "tooling",
    }


def internal_check(check_id, name):
    return {
        "check_id": check_id,
        "phase": "module-final",
        "required": True,
        "description": f"Synthetic closing check {name}.",
        "runner": {"type": "internal", "name": name},
        "parser": "gate_json",
        "timeout_seconds": 60,
        "baseline_eligible": False,
        "evidence_profile": "tooling",
    }


SYNTHETIC_MANIFEST = {
    "schema_version": 1,
    "block_id": "synthetic-block",
    "title": "Synthetic phase execution block",
    "engine_min_version": "1.0.0",
    "required_phases": list(manifest_module.PHASES),
    "phase_definitions": {
        "preflight": phase_definition(True, "Prerequisites of the synthetic block."),
        "targeted": phase_definition(True, "Limited synthetic checks."),
        "offline-final": phase_definition(True, "All offline synthetic checks."),
        "platform-live": phase_definition(
            False,
            "The synthetic block performs no platform or live acceptance at all.",
            declared="not_applicable",
        ),
        "module-final": phase_definition(True, "Closing aggregation."),
    },
    "targeted_selection": {
        "base_ref": "main",
        "always": ["tg-synthetic"],
        "rules": [],
    },
    "checks": [
        argv_check("pf-synthetic", "preflight"),
        argv_check("tg-synthetic", "targeted"),
        argv_check("of-synthetic", "offline-final"),
        internal_check("mf-evidence", "module_final_evidence"),
        internal_check("mf-phase-results", "module_final_phase_results"),
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


class TestArgumentParsing(_support.TempEnvMixin):
    def setUp(self):
        super().setUp()
        self.repo = _support.make_repo(self.tmp_path / "cli-repo")

    def _run(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = cli_module.main(argv, stdout=stdout, stderr=stderr, cwd=self.repo)
        document = json.loads(stdout.getvalue())
        return code, document, stderr.getvalue()

    def test_missing_block(self):
        code, document, _ = self._run(["--phase", "preflight"])
        self.assertEqual(code, statuses.EXIT_USAGE)
        self.assertEqual(document["reason_code"], "missing_parameter")

    def test_missing_phase(self):
        code, document, _ = self._run(["--block", "b0a-1-tooling"])
        self.assertEqual(code, statuses.EXIT_USAGE)
        self.assertEqual(document["reason_code"], "missing_parameter")

    def test_no_arguments_at_all(self):
        code, document, stderr = self._run([])
        self.assertEqual(code, statuses.EXIT_USAGE)
        self.assertEqual(document["reason_code"], "missing_parameter")
        self.assertIn("--block", stderr)

    def test_duplicate_parameter(self):
        code, document, _ = self._run(
            ["--block", "a", "--block", "b", "--phase", "preflight"]
        )
        self.assertEqual(code, statuses.EXIT_USAGE)
        self.assertEqual(document["reason_code"], "duplicate_parameter")

    def test_unknown_parameter(self):
        code, document, _ = self._run(
            ["--block", "a", "--phase", "preflight", "--force"]
        )
        self.assertEqual(code, statuses.EXIT_USAGE)
        self.assertEqual(document["reason_code"], "unknown_parameter")

    def test_missing_value(self):
        code, document, _ = self._run(["--block", "--phase", "preflight"])
        self.assertEqual(code, statuses.EXIT_USAGE)
        self.assertEqual(document["reason_code"], "missing_value")

    def test_unknown_phase(self):
        code, document, _ = self._run(["--block", "b0a-1-tooling", "--phase", "smoke"])
        self.assertEqual(code, statuses.EXIT_USAGE)
        self.assertEqual(document["reason_code"], "unknown_phase")

    def test_unknown_block(self):
        code, document, _ = self._run(
            ["--block", "does-not-exist", "--phase", "preflight"]
        )
        self.assertEqual(code, statuses.EXIT_USAGE)
        self.assertEqual(document["reason_code"], "unknown_block")

    def test_no_silent_defaults(self):
        # Neither block nor phase may be inferred.
        with self.assertRaises(cli_module.UsageError):
            cli_module.parse_args(["--block", "b0a-1-tooling"])
        with self.assertRaises(cli_module.UsageError):
            cli_module.parse_args(["--phase", "preflight"])

    def test_inline_value_form_is_supported(self):
        parsed = cli_module.parse_args(["--block=x", "--phase=preflight"])
        self.assertEqual(parsed, {"block": "x", "phase": "preflight"})


class TestGateScript(_support.TempEnvMixin):
    """The public interface is scripts/gate.sh, exercised as a real process."""

    def _run(self, args):
        env = dict(os.environ)
        env.setdefault("GATE_PYTHON", sys.executable)
        completed = subprocess.run(
            [str(GATE_SCRIPT)] + args,
            cwd=str(_support.REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=900,
            check=False,
        )
        return (
            completed.returncode,
            completed.stdout.decode("utf-8"),
            completed.stderr.decode("utf-8"),
        )

    def test_script_is_executable(self):
        self.assertTrue(os.access(GATE_SCRIPT, os.X_OK))

    def test_block_and_phase_are_mandatory(self):
        code, stdout, stderr = self._run([])
        self.assertEqual(code, statuses.EXIT_USAGE)
        self.assertEqual(json.loads(stdout)["reason_code"], "missing_parameter")
        self.assertIn("--block", stderr)

    def test_valid_block_and_phase_produce_one_json_document(self):
        code, stdout, stderr = self._run(
            ["--block", "b0a-1-tooling", "--phase", "platform-live"]
        )
        document = json.loads(stdout)
        self.assertEqual(code, statuses.EXIT_OK)
        self.assertEqual(document["status"], statuses.NOT_APPLICABLE)
        self.assertEqual(document["block"], "b0a-1-tooling")
        self.assertEqual(document["phase"], "platform-live")
        self.assertNotIn("--- stdout ---", stdout)
        self.assertNotIn("--- stderr ---", stdout)
        for line in stderr.splitlines():
            self.assertTrue(line.startswith("[gate] "), line)

    def test_stdout_is_stable_and_sorted(self):
        _, stdout, _ = self._run(
            ["--block", "b0a-1-tooling", "--phase", "platform-live"]
        )
        document = json.loads(stdout)
        # The engine emits deterministically sorted JSON.
        self.assertEqual(
            stdout.strip(), json.dumps(document, sort_keys=True, indent=2).strip()
        )

    def test_unknown_phase_exits_with_the_usage_code(self):
        code, stdout, _ = self._run(["--block", "b0a-1-tooling", "--phase", "nope"])
        self.assertEqual(code, statuses.EXIT_USAGE)
        self.assertEqual(json.loads(stdout)["reason_code"], "unknown_phase")


class TestPhaseExecution(_support.TempEnvMixin):
    def setUp(self):
        super().setUp()
        self.repo = _support.make_repo(self.tmp_path / "phase-repo")
        (self.repo / "ok_runner.py").write_text(OK_RUNNER, encoding="utf-8")
        manifest_dir = self.repo / "config" / "gates" / "blocks"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "synthetic-block.json").write_text(
            json.dumps(SYNTHETIC_MANIFEST, indent=2), encoding="utf-8"
        )
        _support.git(["add", "-A"], cwd=self.repo)
        _support.git(["commit", "--quiet", "-m", "synthetic block"], cwd=self.repo)
        self.manifest = manifest_module.load(manifest_dir / "synthetic-block.json")

    def _engine(self):
        return engine_module.GateEngine(
            worktree=self.repo, manifest=self.manifest, progress=io.StringIO()
        )

    def test_the_five_phases_exist_and_are_the_only_ones(self):
        self.assertEqual(
            manifest_module.PHASES,
            (
                "preflight",
                "targeted",
                "offline-final",
                "platform-live",
                "module-final",
            ),
        )
        with self.assertRaises(ValueError):
            self._engine().run_phase("smoke")

    def test_each_phase_produces_exactly_one_enum_status(self):
        for phase in ("preflight", "targeted", "offline-final", "platform-live"):
            with self.subTest(phase=phase):
                result = self._engine().run_phase(phase)
                self.assertIn(result["status"], statuses.ALL_STATUSES)
                self.assertIsInstance(result["status"], str)
                self.assertEqual(
                    result["exit_code"], statuses.exit_code(result["status"])
                )

    def test_platform_live_is_declared_non_applicable(self):
        result = self._engine().run_phase("platform-live")
        self.assertEqual(result["status"], statuses.NOT_APPLICABLE)
        self.assertEqual(
            [entry["reason_code"] for entry in result["checks"]],
            ["phase_not_applicable_by_manifest"],
        )

    def test_module_final_refuses_missing_previous_phases(self):
        result = self._engine().run_phase("module-final")
        self.assertEqual(result["status"], statuses.FAIL)
        reasons = {entry["reason_code"] for entry in result["checks"]}
        self.assertIn("phase_result_missing", reasons)

    def test_module_final_accepts_a_complete_and_current_run(self):
        for phase in ("preflight", "targeted", "offline-final", "platform-live"):
            self.assertIn(
                self._engine().run_phase(phase)["status"],
                (statuses.PASS, statuses.NOT_APPLICABLE),
            )
        result = self._engine().run_phase("module-final")
        self.assertEqual(result["status"], statuses.PASS)

    def test_module_final_rejects_stale_results(self):
        for phase in ("preflight", "targeted", "offline-final", "platform-live"):
            self._engine().run_phase(phase)
        # Any change of the working tree invalidates the recorded phases.
        (self.repo / "new_file.txt").write_text("later change\n", encoding="utf-8")
        result = self._engine().run_phase("module-final")
        self.assertEqual(result["status"], statuses.FAIL)
        self.assertIn(
            "phase_result_stale",
            {entry["reason_code"] for entry in result["checks"]},
        )

    def test_results_and_evidence_are_persisted_in_the_runtime_area(self):
        self._engine().run_phase("preflight")
        result_file = self.runtime_dir / "results" / "synthetic-block.preflight.json"
        evidence_file = self.runtime_dir / "evidence" / "synthetic-block.preflight.json"
        self.assertTrue(result_file.is_file())
        self.assertTrue(evidence_file.is_file())
        self.assertTrue(
            str(self.runtime_dir).startswith(str(self.tmp_path)),
            "runtime area must be redirectable for tests",
        )

    def test_raw_output_never_reaches_the_machine_result(self):
        result = self._engine().run_phase("preflight")
        serialised = json.dumps(result)
        self.assertNotIn("--- stdout ---", serialised)
        self.assertNotIn("--- stderr ---", serialised)
        for entry in result["checks"]:
            self.assertRegex(entry["raw_log_sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("/", entry["raw_log_name"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
