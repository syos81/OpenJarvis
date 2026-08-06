"""The three mechanical generality checks (B0a-2 §10).

The positive configuration test uses two completely invented organisations.
No real organisation, provider account or personal data appears here.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import generality  # noqa: E402
from tools.gates.runners import generality_checks  # noqa: E402

SCOPE_PATH = _support.REPO_ROOT / "config" / "governance" / "generality-scope.json"
FIXTURE_DIR = (
    _support.REPO_ROOT / "config" / "governance" / "generality-fixtures"
)


def load_scope():
    return json.loads(SCOPE_PATH.read_text(encoding="utf-8"))


def load_fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The data driven evaluator under test: identical code for every organisation
# --------------------------------------------------------------------------
def due_actions(configuration, process_type_id, state_id, days_in_state):
    """Derive due actions purely from configuration values.

    This function is the *identical unchanged core* of the positive
    configuration test. It contains no organisation, workspace, process type,
    state or provider literal — everything comes from the configuration.
    """
    process_type = next(
        entry
        for entry in configuration["process_types"]
        if entry["process_type_id"] == process_type_id
    )
    known_states = {state["state_id"] for state in process_type["states"]}
    if state_id not in known_states:
        raise KeyError(state_id)
    due = []
    for action in process_type["due_actions"]:
        if action["state_id"] != state_id:
            continue
        if days_in_state >= action["offset_days"]:
            due.append((action["action_id"], action["role_id"]))
    return sorted(due)


def deadline_for(configuration, process_type_id, state_id):
    process_type = next(
        entry
        for entry in configuration["process_types"]
        if entry["process_type_id"] == process_type_id
    )
    for deadline in process_type["deadlines"]:
        if deadline["state_id"] == state_id:
            return deadline["days"]
    return None


class TestOrganizationScan(_support.TempEnvMixin):
    def setUp(self):
        super().setUp()
        self.scope = load_scope()
        self.terms = self.scope["organization_terms"]

    def _scan(self, files, root=None, declared=None):
        return generality.scan_terms(
            root or _support.REPO_ROOT, files, self.terms, declared=declared
        )

    def _write(self, relative, content):
        target = self.tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return relative

    def test_spelling_variants_are_normalised(self):
        for spelling in ("Klünder", "Kluender", "KLUNDER", "klünder"):
            with self.subTest(spelling=spelling):
                path = self._write("schema.py", f'TABLE = "{spelling}_contacts"\n')
                findings = self._scan([path], root=self.tmp_path)
                self.assertEqual(len(findings), 1, spelling)
                self.assertEqual(findings[0]["term_id"], "kluender")

    def test_scan_is_not_a_naive_substring_test(self):
        path = self._write(
            "core.py",
            "STANDARD = 'standard'\nDARTBOARD = 'dartboard'\nclass Kluenderman: pass\n",
        )
        self.assertEqual(self._scan([path], root=self.tmp_path), [])

    def test_token_bounded_organization_is_found(self):
        path = self._write("core.py", "WORKSPACE = 'DART'\n")
        findings = self._scan([path], root=self.tmp_path)
        self.assertEqual([finding["term_id"] for finding in findings], ["dart"])

    def test_organization_in_a_path_is_found(self):
        path = self._write("modules/dart/service.py", "value = 1\n")
        findings = self._scan([path], root=self.tmp_path)
        self.assertTrue(any(finding["location"] == "path" for finding in findings))

    def test_declared_bundle_identifier_is_pinned(self):
        declared = self.scope["declared_identifiers"]
        self.assertEqual(len(declared), 1)
        entry = declared[0]
        self.assertEqual(entry["value"], "de.kluender.jarvis.contacts-bridge")
        # B0a-3 moved the open point into the canonical deferred decision
        # register; the exception itself stays value and path exact.
        self.assertEqual(entry["owner"], "deferred_decision_register")
        self.assertIn("17-deferred-decisions.md", entry["owner_reference"])
        self.assertIn("Kontakte M2", entry["due"])
        for path in entry["paths"]:
            with self.subTest(path=path):
                self.assertTrue((_support.REPO_ROOT / path).is_file())
        findings = generality.scan_terms(
            _support.REPO_ROOT, entry["paths"], self.terms, declared=declared
        )
        self.assertEqual(findings, [], "declared identifier must silence exactly itself")

    def test_declaration_does_not_exempt_other_occurrences_in_the_same_file(self):
        declared = [
            {
                "identifier_id": "app-bundle",
                "value": "de.kluender.jarvis.contacts-bridge",
                "paths": ["core.py"],
            }
        ]
        path = self._write(
            "core.py",
            'AUTHOR = "de.kluender.jarvis.contacts-bridge"\n'
            'TABLE = "kluender_invoices"\n',
        )
        findings = self._scan([path], root=self.tmp_path, declared=declared)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["count"], 1)

    def test_declaration_on_another_path_does_not_apply(self):
        declared = [
            {
                "identifier_id": "app-bundle",
                "value": "de.kluender.jarvis.contacts-bridge",
                "paths": ["allowed.py"],
            }
        ]
        path = self._write("other.py", 'AUTHOR = "de.kluender.jarvis.contacts-bridge"\n')
        findings = self._scan([path], root=self.tmp_path, declared=declared)
        self.assertEqual(len(findings), 1)

    def test_stale_declaration_is_reported(self):
        declared = [
            {
                "identifier_id": "app-bundle",
                "value": "de.kluender.jarvis.contacts-bridge",
                "paths": ["gone.py"],
            }
        ]
        issues = list(generality.check_declared_identifiers(self.tmp_path, declared))
        self.assertEqual(
            [code for _, _, code in issues], ["declared_identifier_path_absent"]
        )

    def test_no_term_waits_for_owner_input_any_more(self):
        # B0a-3 retired the placeholder: the scan runs over evidenced
        # organisation names only.
        self.assertEqual(generality.pending_terms(self.terms), [])
        self.assertTrue(all(term.get("canonical") for term in self.terms))

    def test_the_repository_scan_is_clean(self):
        failures, diagnostics = generality_checks.mode_organization_scan(
            _support.REPO_ROOT
        )
        self.assertEqual([failure["id"] for failure in failures], [])
        self.assertTrue(
            any(item.startswith("scanned_files=") for item in diagnostics)
        )


class TestProviderGate(_support.TempEnvMixin):
    def setUp(self):
        super().setUp()
        self.scope = load_scope()

    def test_provider_in_a_released_adapter_path_is_allowed(self):
        findings = [{"path": "src/openjarvis/connectors/oura.py", "term_id": "oura"}]
        self.assertEqual(
            generality.provider_violations(
                findings, self.scope["provider_allowed_paths"]
            ),
            [],
        )

    def test_provider_in_the_core_is_a_violation(self):
        findings = [
            {"path": "src/personaljarvis/contacts/domain/models.py", "term_id": "oura"},
            {"path": "src/personaljarvis/processes/state.py", "term_id": "immoware24"},
        ]
        self.assertEqual(
            len(
                generality.provider_violations(
                    findings, self.scope["provider_allowed_paths"]
                )
            ),
            2,
        )

    def test_there_is_no_blanket_allowlist(self):
        for pattern in self.scope["provider_allowed_paths"]:
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, ("*", "**", "**/*"))
                self.assertTrue(pattern.count("/") >= 1, pattern)

    def test_a_too_broad_allowlist_would_be_rejected_by_the_test_contract(self):
        broad = ["*"]
        findings = [{"path": "src/personaljarvis/core.py", "term_id": "oura"}]
        self.assertEqual(generality.provider_violations(findings, broad), [])
        self.assertNotIn("*", self.scope["provider_allowed_paths"])

    def test_the_repository_provider_gate_is_clean(self):
        failures, _ = generality_checks.mode_provider_gate(_support.REPO_ROOT)
        self.assertEqual([failure["id"] for failure in failures], [])


class TestLiteralComparisons(unittest.TestCase):
    def setUp(self):
        self.sensitive = [
            marker.lower() for marker in load_scope()["sensitive_identifiers"]
        ]

    def _find(self, source):
        scope = load_scope()
        provider_values = []
        for term in scope["provider_terms"]:
            provider_values.extend(term.get("variants") or [])
        return generality.find_literal_comparisons(
            source, self.sensitive, provider_values=provider_values
        )

    def test_hard_coded_organization_comparison_is_detected(self):
        self.assertTrue(self._find('if organization_id == "org-alpha": pass\n'))

    def test_hard_coded_workspace_comparison_is_detected(self):
        self.assertTrue(self._find('if item.workspace_id == "ws-alpha": pass\n'))

    def test_hard_coded_process_type_comparison_is_detected(self):
        self.assertTrue(
            self._find('if record["process_type_id"] in ("pt-a", "pt-b"): pass\n')
        )

    def test_hard_coded_provider_comparison_is_detected(self):
        self.assertTrue(self._find('if provider == "nextcloud": pass\n'))

    def test_a_provider_field_compared_to_a_non_provider_value_is_clean(self):
        # `provider_domain == "timeout"` is an error class, not a provider
        # decision, and stays allowed outside the adapter boundary.
        self.assertEqual(self._find('if exc.provider_domain == "timeout": pass\n'), [])

    def test_configuration_driven_comparison_is_clean(self):
        self.assertEqual(
            self._find(
                "if organization_id == configuration['organization']['organization_id']:\n"
                "    pass\n"
            ),
            [],
        )

    def test_unrelated_comparison_is_clean(self):
        self.assertEqual(self._find('if status == "ready": pass\n'), [])

    def test_the_repository_core_is_clean(self):
        failures, _ = generality_checks.mode_literal_comparisons(_support.REPO_ROOT)
        self.assertEqual([failure["id"] for failure in failures], [])


class TestPositiveConfigurationMechanism(unittest.TestCase):
    """Two invented organisations, two process types, one unchanged core."""

    def setUp(self):
        self.alpha = load_fixture("organization-alpha.json")
        self.beta = load_fixture("organization-beta.json")
        self.contract = load_fixture("contract.json")

    def test_both_fixtures_are_marked_synthetic(self):
        for fixture in (self.alpha, self.beta):
            self.assertTrue(fixture["synthetic"])

    def test_the_two_organisations_are_distinct(self):
        self.assertNotEqual(
            self.alpha["organization"]["organization_id"],
            self.beta["organization"]["organization_id"],
        )
        self.assertNotEqual(
            self.alpha["organization"]["workspace_id"],
            self.beta["organization"]["workspace_id"],
        )

    def test_the_two_process_types_differ_in_every_required_dimension(self):
        alpha = self.alpha["process_types"][0]
        beta = self.beta["process_types"][0]
        self.assertNotEqual(alpha["process_type_id"], beta["process_type_id"])
        self.assertNotEqual(
            [state["state_id"] for state in alpha["states"]],
            [state["state_id"] for state in beta["states"]],
        )
        self.assertNotEqual(
            [role["role_id"] for role in self.alpha["roles"]],
            [role["role_id"] for role in self.beta["roles"]],
        )
        self.assertNotEqual(
            [deadline["days"] for deadline in alpha["deadlines"]],
            [deadline["days"] for deadline in beta["deadlines"]],
        )
        self.assertNotEqual(
            [action["action_id"] for action in alpha["due_actions"]],
            [action["action_id"] for action in beta["due_actions"]],
        )

    def test_identical_core_processes_both_configurations(self):
        alpha_due = due_actions(
            self.alpha, "pt-alpha-formularlauf", "st-entwurf", days_in_state=12
        )
        beta_due = due_actions(
            self.beta, "pt-beta-vorgangskette", "st-gemeldet", days_in_state=1
        )
        self.assertEqual(alpha_due, [("act-erinnern", "role-antragsteller")])
        self.assertEqual(
            beta_due, [("act-zuweisung-mahnen", "role-koordination")]
        )
        self.assertEqual(
            deadline_for(self.alpha, "pt-alpha-formularlauf", "st-entwurf"), 14
        )
        self.assertEqual(
            deadline_for(self.beta, "pt-beta-vorgangskette", "st-gemeldet"), 2
        )

    def test_nothing_is_due_before_the_configured_offset(self):
        self.assertEqual(
            due_actions(self.alpha, "pt-alpha-formularlauf", "st-entwurf", 1), []
        )
        self.assertEqual(
            due_actions(self.beta, "pt-beta-vorgangskette", "st-gemeldet", 0), []
        )

    def test_an_unknown_state_is_rejected_by_configuration_not_by_code(self):
        with self.assertRaises(KeyError):
            due_actions(self.alpha, "pt-alpha-formularlauf", "st-gemeldet", 5)

    def test_the_core_contains_no_organisation_or_provider_literal(self):
        sensitive = [
            marker.lower() for marker in load_scope()["sensitive_identifiers"]
        ]
        for function in (due_actions, deadline_for):
            source = inspect.getsource(function)
            with self.subTest(function=function.__name__):
                self.assertEqual(
                    generality.find_literal_comparisons(source, sensitive), []
                )
                tree = ast.parse(source)
                literals = {
                    node.value
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                }
                for fixture in (self.alpha, self.beta):
                    self.assertNotIn(
                        fixture["organization"]["organization_id"], literals
                    )
                    self.assertNotIn(
                        fixture["process_types"][0]["process_type_id"], literals
                    )

    def test_the_contract_declares_what_must_not_be_required(self):
        self.assertEqual(
            sorted(self.contract["must_not_require"]),
            [
                "additional_route",
                "code_change",
                "new_enum_value",
                "organization_specific_branch",
                "provider_specific_core_logic",
            ],
        )


class TestActivationRule(_support.TempEnvMixin):
    def test_without_a_process_path_the_product_test_is_not_applicable(self):
        activation = load_scope()["process_activation"]
        state, paths = generality.activation_state(_support.REPO_ROOT, activation)
        self.assertEqual(state, "inactive")
        self.assertEqual(paths, [])

    def test_a_process_path_activates_the_positive_test(self):
        activation = load_scope()["process_activation"]
        target = (
            self.tmp_path
            / "src"
            / "personaljarvis"
            / "processes"
            / "api"
            / "routes.py"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("ROUTES = []\n", encoding="utf-8")
        state, paths = generality.activation_state(self.tmp_path, activation)
        self.assertEqual(state, "active")
        self.assertTrue(paths)

    def test_an_active_path_without_the_product_test_fails(self):
        engine_backup = os.environ.get("GATE_ENGINE_ROOT")
        os.environ["GATE_ENGINE_ROOT"] = str(self.tmp_path)
        self.addCleanup(
            lambda: os.environ.__setitem__("GATE_ENGINE_ROOT", engine_backup)
            if engine_backup
            else os.environ.pop("GATE_ENGINE_ROOT", None)
        )
        # Mirror the steering configuration into the temporary engine root.
        for relative in (
            "config/governance/generality-scope.json",
            "config/governance/generality-fixtures/contract.json",
            "config/governance/generality-fixtures/organization-alpha.json",
            "config/governance/generality-fixtures/organization-beta.json",
            "tests/tooling/gates/test_generality.py",
        ):
            source = _support.REPO_ROOT / relative
            target = self.tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        process = self.tmp_path / "src" / "personaljarvis" / "processes" / "api"
        process.mkdir(parents=True, exist_ok=True)
        (process / "routes.py").write_text("ROUTES = []\n", encoding="utf-8")

        failures, diagnostics = generality_checks.mode_configuration_test(self.tmp_path)
        self.assertIn("process_activation=active", diagnostics)
        self.assertIn(
            "positive_test_required_but_absent",
            {failure["code"] for failure in failures},
        )

    def test_the_mechanism_test_is_mandatory_even_while_inactive(self):
        failures, diagnostics = generality_checks.mode_configuration_test(
            _support.REPO_ROOT
        )
        self.assertEqual([failure["id"] for failure in failures], [])
        self.assertIn("process_activation=inactive", diagnostics)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
