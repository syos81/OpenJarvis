"""The closed exclusion vocabulary: every category confirms and refutes.

A category exists only through its mechanical criterion. For each category
this suite drives one positive fixture the validator must confirm and one
negative fixture it must refute — a vocabulary whose refutation path is
untested would be free text with extra steps. Register-level discipline
(unknown category, missing category, free text alone, orphaned assignment)
is tested against the schema-2 reader.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.gates import astcat, astscan  # noqa: E402


def entry_from_source(root, relative, source, *, category, proof,
                      candidate_index=0):
    """Write the source, scan it, and build a schema-2 exclusion entry."""
    target = Path(root) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(source), encoding="utf-8")
    candidates = astscan.scan_source(relative, textwrap.dedent(source))
    candidate = candidates[candidate_index]
    entry = dict(candidate.as_dict())
    entry["disposition"] = "exclude_with_reason"
    entry["category"] = category
    entry["category_proof"] = proof
    entry["reason"] = "fixture annotation, long enough to satisfy the floor."
    entry["repair_note"] = ""
    entry["resolved_by_removal"] = False
    entry["source_digest"] = hashlib.sha256(target.read_bytes()).hexdigest()
    return entry


class CategoryFixture(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="b0f-categories-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def check(self, relative, source, category, proof=None, candidate_index=0):
        entry = entry_from_source(
            self.root, relative, source,
            category=category, proof=proof or {},
            candidate_index=candidate_index,
        )
        return astcat.validate_entry(self.root, entry)


class TestVocabularyShape(unittest.TestCase):
    def test_every_category_declares_claim_criterion_and_rule(self):
        self.assertTrue(astcat.CATEGORIES)
        for name, category in astcat.CATEGORIES.items():
            self.assertIn(category["rule"], ("R9", "R10"), name)
            self.assertTrue(category["claim"].strip(), name)
            self.assertTrue(category["criterion"].strip(), name)
            self.assertIn(name, astcat._VALIDATORS)

    def test_no_catch_all_category_exists(self):
        for forbidden in ("other", "false_positive", "harmless", "equivalent"):
            self.assertNotIn(forbidden, astcat.CATEGORIES)

    def test_category_names_carry_their_rule(self):
        for name, category in astcat.CATEGORIES.items():
            self.assertTrue(
                name.startswith(category["rule"].lower() + "_"),
                f"{name} does not carry its rule class",
            )


class TestR9Categories(CategoryFixture):
    def test_post_judgment_position_confirms_and_refutes(self):
        positive = """
            def mode(failures):
                failures.append(check())
                _emit(failures)
                shutil.rmtree(area, ignore_errors=True)
            """
        self.assertEqual(
            self.check("tools/fx.py", positive, "r9_post_judgment_position"), ""
        )
        negative = """
            def mode(failures):
                shutil.rmtree(area, ignore_errors=True)
                failures.append(check())
                _emit(failures)
            """
        self.assertEqual(
            self.check("tools/fx.py", negative, "r9_post_judgment_position"),
            "judgment_after_anchor",
        )

    def test_after_state_observed_confirms_and_refutes(self):
        positive = """
            def test_withdrawn(area):
                if area.exists():
                    shutil.rmtree(str(area))
                area.mkdir(parents=True)
                assert run(area) == "ok"
            """
        self.assertEqual(
            self.check("tests/fx.py", positive, "r9_after_state_observed"), ""
        )
        negative = """
            def test_withdrawn(area):
                if area.exists():
                    shutil.rmtree(str(area))
                assert run() == "ok"
            """
        self.assertEqual(
            self.check("tests/fx.py", negative, "r9_after_state_observed"),
            "no_observation_after_anchor",
        )

    def test_target_unconsumed_confirms_and_refutes(self):
        positive = """
            def mode(stage):
                digest = parse(stage)
                shutil.rmtree(stage, ignore_errors=True)
                return digest
            """
        self.assertEqual(
            self.check("tools/fx.py", positive, "r9_target_unconsumed_after"), ""
        )
        negative = """
            def mode(stage):
                shutil.rmtree(stage, ignore_errors=True)
                return parse(stage)
            """
        self.assertEqual(
            self.check("tools/fx.py", negative, "r9_target_unconsumed_after"),
            "target_consumed_after_anchor",
        )

    def test_loud_guarded_removal_confirms_and_refutes(self):
        positive = """
            def test_stale(report):
                if report.exists():
                    report.unlink()
                assert consume(report) == "fresh"
            """
        self.assertEqual(
            self.check("tests/fx.py", positive, "r9_loud_guarded_removal"), ""
        )
        negative = """
            def test_stale(report, other):
                if other.exists():
                    report.unlink()
                assert consume(report) == "fresh"
            """
        self.assertEqual(
            self.check("tests/fx.py", negative, "r9_loud_guarded_removal"),
            "guard_does_not_check_target",
        )

    def test_conditional_import_target_confirms_and_refutes(self):
        module = """
            try:
                from vendor import Harness
            except ImportError:
                Harness = None
            """
        (self.root / "src").mkdir()
        (self.root / "src" / "vendorish.py").write_text(
            textwrap.dedent(module), encoding="utf-8"
        )
        source = """
            def test_masked(monkeypatch, fake):
                monkeypatch.setattr(backend, "Harness", fake, raising=False)
                assert run() == "ok"
            """
        self.assertEqual(
            self.check(
                "tests/fx.py", source, "r9_conditional_import_target",
                proof={"module": "src/vendorish.py", "attribute": "Harness"},
            ),
            "",
        )
        (self.root / "src" / "vendorish.py").write_text(
            "from vendor import Harness\n", encoding="utf-8"
        )
        self.assertEqual(
            self.check(
                "tests/fx.py", source, "r9_conditional_import_target",
                proof={"module": "src/vendorish.py", "attribute": "Harness"},
            ),
            "attribute_not_conditionally_bound",
        )


class TestInjectionLoadBearing(CategoryFixture):
    """The execution probe, in both directions, in a throwaway project."""

    def _probe(self, body):
        source = f"""
            from unittest.mock import Mock

            def test_probe():
{textwrap.indent(textwrap.dedent(body), '                ')}
            """
        return self.check(
            "tests/test_b0f_probe_fixture.py",
            source,
            "r9_injection_load_bearing",
            proof={"test": "tests/test_b0f_probe_fixture.py::test_probe"},
        )

    def test_a_load_bearing_injection_confirms(self):
        self.assertEqual(
            self._probe(
                """
                broken = Mock(side_effect=RuntimeError("boom"))
                errors = 0
                try:
                    broken()
                except RuntimeError:
                    errors = 1
                assert errors == 1
                """
            ),
            "",
        )

    def test_an_injection_the_test_never_needs_is_refuted(self):
        self.assertEqual(
            self._probe(
                """
                broken = Mock(side_effect=RuntimeError("boom"))
                assert 1 + 1 == 2
                """
            ),
            "test_green_without_injection",
        )


class TestR10Categories(CategoryFixture):
    def test_required_key_prevalidated_confirms_and_refutes(self):
        (self.root / "config" / "governance").mkdir(parents=True)
        (self.root / "config" / "governance" / "config-loaders.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "loader_bindings",
                    "rule": "R4",
                    "statement": "fixture",
                    "coverage_roots": ["config"],
                    "bindings": [
                        {
                            "binding_id": "config-loader-bindings",
                            "expectation": "accepted",
                            "kind": "structural",
                            "optional_fields": ["*"],
                            "pattern": "config/governance/config-loaders.json",
                            "reason": "fixture self binding",
                            "required_fields": ["bindings"],
                        },
                        {
                            "binding_id": "fixture-doc",
                            "expectation": "accepted",
                            "kind": "structural",
                            "optional_fields": [],
                            "pattern": "config/fixture.json",
                            "reason": "fixture document binding",
                            "required_fields": ["entries", "kind"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        (self.root / "config" / "fixture.json").write_text(
            json.dumps({"entries": [1], "kind": "fixture"}), encoding="utf-8"
        )
        source = """
            def check(document):
                findings = []
                for item in document.get("entries", []):
                    findings.append(item)
                return findings
            """
        self.assertEqual(
            self.check(
                "tools/fx.py", source, "r10_required_key_prevalidated",
                proof={"document": "config/fixture.json", "key_path": ["entries"]},
            ),
            "",
        )
        # The same probe refutes when the key is not actually required.
        self.assertEqual(
            self.check(
                "tools/fx.py", source, "r10_required_key_prevalidated",
                proof={"document": "config/fixture.json", "key_path": ["kind"]},
                candidate_index=0,
            ),
            "",
        )
        bindings = json.loads(
            (self.root / "config" / "governance" / "config-loaders.json").read_text()
        )
        bindings["bindings"][1]["required_fields"] = ["kind"]
        bindings["bindings"][1]["optional_fields"] = ["entries"]
        (self.root / "config" / "governance" / "config-loaders.json").write_text(
            json.dumps(bindings), encoding="utf-8"
        )
        self.assertEqual(
            self.check(
                "tools/fx.py", source, "r10_required_key_prevalidated",
                proof={"document": "config/fixture.json", "key_path": ["entries"]},
            ),
            "reader_accepts_absent_key",
        )

    def test_emptiness_fails_closed_confirms_and_refutes(self):
        positive = """
            def mode(data, failures):
                changes = data.get("changes", [])
                if not changes:
                    failures.append(fail("empty"))
                for change in changes:
                    judge(change, failures)
                _emit(failures)
            """
        self.assertEqual(
            self.check(
                "tools/fx.py", positive, "r10_emptiness_fails_closed",
                proof={"mechanism": "guard", "names": ["changes"]},
            ),
            "",
        )
        negative = """
            def mode(data, failures):
                changes = data.get("changes", [])
                for change in changes:
                    judge(change, failures)
                _emit(failures)
            """
        self.assertEqual(
            self.check(
                "tools/fx.py", negative, "r10_emptiness_fails_closed",
                proof={"mechanism": "guard", "names": ["changes"]},
            ),
            "guard_not_found",
        )

    def test_excusal_only_flow_confirms_and_refutes(self):
        positive = """
            def scan(scope, findings, failures):
                exceptions = {entry for entry in scope.get("exceptions", [])}
                for finding in findings:
                    if finding in exceptions:
                        continue
                    failures.append(finding)
            """
        self.assertEqual(
            self.check(
                "tools/fx.py", positive, "r10_excusal_only_flow",
                proof={
                    "names": ["exceptions"],
                    "consumers": [{"file": "tools/fx.py", "unit": "scan"}],
                },
                candidate_index=0,
            ),
            "",
        )
        negative = """
            def scan(scope, failures):
                allowed = [entry for entry in scope.get("exceptions", [])]
                for entry in allowed:
                    failures.remove(entry)
                return failures == []
            """
        self.assertEqual(
            self.check(
                "tools/fx.py", negative, "r10_excusal_only_flow",
                proof={
                    "names": ["allowed"],
                    "consumers": [{"file": "tools/fx.py", "unit": "scan"}],
                },
            ),
            "non_excusal_use_found",
        )

    def test_diagnostics_only_flow_confirms_and_refutes(self):
        positive = """
            def mode(entries, failures):
                diagnostics = []
                for entry in entries.get("rows", []):
                    diagnostics.append(f"row={entry}")
                _emit(_PASSED, failures, diagnostics)
            """
        self.assertEqual(
            self.check(
                "tools/fx.py", positive, "r10_diagnostics_only_flow",
                proof={"mechanism": "emit_diagnostics_arg", "names": ["diagnostics"]},
            ),
            "",
        )
        negative = """
            def mode(entries, diagnostics):
                for entry in entries.get("rows", []):
                    diagnostics.append(entry)
                _emit(_PASSED, diagnostics, [])
            """
        self.assertEqual(
            self.check(
                "tools/fx.py", negative, "r10_diagnostics_only_flow",
                proof={"mechanism": "emit_diagnostics_arg", "names": ["diagnostics"]},
            ),
            "diagnostics_name_in_failure_position",
        )


class TestRegisterDiscipline(unittest.TestCase):
    """Schema 2: category duties enforced by the reader itself."""

    def _register_with(self, entry_overrides):
        from tests.tooling.gates.test_ast_dispositions import register_skeleton

        entry = {
            "candidate_id": "r9-0000000000000001",
            "rule": "R9",
            "file": "tests/fx.py",
            "unit": "test_x",
            "candidate_class": "silent_substitution",
            "ast_class": "Call",
            "lineno": 3,
            "fingerprint": "0" * 24,
            "occurrence": 0,
            "disposition": "exclude_with_reason",
            "category": "r9_after_state_observed",
            "category_proof": {},
            "reason": "fixture annotation, long enough to satisfy the floor.",
            "repair_note": "",
            "resolved_by_removal": False,
            "source_digest": "0" * 64,
        }
        entry.update(entry_overrides)
        register = register_skeleton()
        register["dispositions"] = [entry]
        return register

    def _load(self, register):
        with tempfile.TemporaryDirectory(prefix="b0f-register-") as tmp:
            root = Path(tmp)
            target = root / "config" / "governance" / "ast-dispositions.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(register), encoding="utf-8")
            return astscan.load_register(root)

    def test_an_unknown_category_falls(self):
        with self.assertRaises(astscan.RegisterError) as caught:
            self._load(self._register_with({"category": "r9_totally_new"}))
        self.assertEqual(caught.exception.code, "entry_category_unknown")

    def test_free_text_without_category_falls(self):
        with self.assertRaises(astscan.RegisterError) as caught:
            self._load(self._register_with({"category": ""}))
        self.assertEqual(caught.exception.code, "entry_category_missing")

    def test_a_category_on_the_wrong_rule_falls(self):
        with self.assertRaises(astscan.RegisterError) as caught:
            self._load(
                self._register_with({"category": "r10_emptiness_fails_closed"})
            )
        self.assertEqual(caught.exception.code, "entry_category_rule_mismatch")

    def test_a_category_on_a_non_exclusion_falls(self):
        with self.assertRaises(astscan.RegisterError) as caught:
            self._load(
                self._register_with(
                    {
                        "disposition": "mark_and_fix",
                        "repair_note": "fixture repair note",
                    }
                )
            )
        self.assertEqual(caught.exception.code, "entry_category_unexpected")

    def test_schema_one_is_refused_by_the_reader(self):
        register = self._register_with({})
        register["schema_version"] = 1
        with self.assertRaises(astscan.RegisterError) as caught:
            self._load(register)
        self.assertEqual(caught.exception.code, "register_schema_unsupported")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
