"""Governance registries: collisions, IDs, Ambient placeholder, order."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import governance  # noqa: E402
from tools.gates.runners import governance_checks  # noqa: E402

CONFIG = _support.REPO_ROOT / "config" / "governance"
DOCS = _support.REPO_ROOT / "docs" / "governance"
COLLISIONS = CONFIG / "decision-collisions.json"
CITATIONS = CONFIG / "decision-citations.json"
ORDER = CONFIG / "delivery-order.json"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def codes(issues):
    return {code for _, code in issues}


class TestCollisionRegistry(unittest.TestCase):
    """After B0a-3 the registry is a resolved, historical record."""

    def setUp(self):
        self.registry = load(COLLISIONS)

    def test_the_registry_is_resolved(self):
        self.assertEqual(self.registry["status"], "resolved")
        self.assertEqual(self.registry["open_collisions"], 0)
        self.assertEqual(self.registry["resolved_in_block"], "b0a-3-integration")

    def test_seven_historical_resolutions_are_recorded(self):
        records = self.registry["historical_resolution"]
        self.assertEqual(len(records), 7)
        self.assertEqual(
            {record["new_id"] for record in records},
            {"DEC-051", "DEC-052", "DEC-053", "DEC-054", "DEC-055",
             "ADR-0025", "ADR-0026"},
        )
        for record in records:
            with self.subTest(record=record["new_id"]):
                self.assertEqual(
                    record["classification"], "historical_resolution_record"
                )
                self.assertEqual(record["line"], "contacts_calendar")

    def test_no_collision_is_detected_any_more(self):
        detected, error = governance.detect_collisions(
            self.registry, _support.REPO_ROOT
        )
        self.assertIsNone(error)
        self.assertEqual(detected, set())

    def test_every_renumbered_artifact_is_verified(self):
        issues = list(governance.verify_resolution(self.registry, _support.REPO_ROOT))
        self.assertEqual(issues, [])

    def test_a_missing_renumbered_artifact_is_detected(self):
        broken = copy.deepcopy(self.registry)
        broken["historical_resolution"][0]["new_id"] = "DEC-099"
        issues = list(governance.verify_resolution(broken, _support.REPO_ROOT))
        self.assertIn("renumbered_decision_missing", codes(issues))

    def test_a_changed_title_is_detected(self):
        broken = copy.deepcopy(self.registry)
        broken["historical_resolution"][0]["title"] = "Ein anderer Titel"
        issues = list(governance.verify_resolution(broken, _support.REPO_ROOT))
        self.assertIn("renumbered_title_mismatch", codes(issues))

    def test_a_changed_canonical_id_is_detected(self):
        broken = copy.deepcopy(self.registry)
        broken["canonical_ids_unchanged"] = ["DEC-999"]
        issues = list(governance.verify_resolution(broken, _support.REPO_ROOT))
        self.assertIn("canonical_id_changed", codes(issues))

    def test_the_runner_accepts_the_resolved_state(self):
        failures, diagnostics = governance_checks.mode_collisions(_support.REPO_ROOT)
        self.assertEqual([failure["id"] for failure in failures], [])
        self.assertIn("open_collisions=0", diagnostics)
        self.assertIn("historical_resolutions=7", diagnostics)

    def test_the_normative_source_is_the_calendar_baseline(self):
        source = self.registry["normative_source"]
        self.assertEqual(
            source["document"],
            "docs/personal-jarvis/calendar-implementation-baseline-2026-08-04.md",
        )
        self.assertEqual(str(source["section"]), "6")
        self.assertEqual(source["role"], "sole_normative_source")


class TestIdFreeze(unittest.TestCase):
    def test_no_new_decision_id_and_no_new_adr_file(self):
        failures, diagnostics = governance_checks.mode_id_freeze(_support.REPO_ROOT)
        self.assertEqual([failure["id"] for failure in failures], [])
        self.assertTrue(any(item.startswith("touched_paths=") for item in diagnostics))

    def test_a_register_row_in_a_governance_document_is_forbidden(self):
        self.assertTrue(governance.DEC_ROW_RE.match("| DEC-051 | Neue Entscheidung |"))
        self.assertIsNone(governance.DEC_ROW_RE.match("DEC-051 ist keine Zeile"))

    def test_adr_directory_changes_only_by_the_declared_renumbering(self):
        from tools.gates import gitutil, guardbase

        migration = load(CONFIG / "b0a-3-id-migration.json")
        declared = set()
        for entry in migration["mappings"]:
            for key in ("old_path", "new_path"):
                if entry.get(key):
                    declared.add(entry[key])
        base = guardbase.derive_for_repository(_support.REPO_ROOT)["base_commit"]
        code, out, _ = gitutil.run_git(
            ["diff", "--name-only", base, "--", "docs/adr"],
            cwd=_support.REPO_ROOT,
        )
        self.assertEqual(code, 0)
        touched = {line.strip() for line in out.splitlines() if line.strip()}
        self.assertTrue(touched)
        self.assertEqual(touched - declared, set())


class TestAmbientPlaceholder(unittest.TestCase):
    def setUp(self):
        self.config = load(CONFIG / "ambient-placeholder.json")

    def test_placeholder_is_the_documented_one(self):
        self.assertEqual(
            self.config["placeholder"], "{{DEC_ID_AMBIENT_INTERACTION_V1}}"
        )

    def test_placeholder_present_in_every_required_location(self):
        for relative in self.config["required_locations"]:
            with self.subTest(location=relative):
                text = (_support.REPO_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(self.config["placeholder"], text)

    def test_ambient_has_no_decision_number(self):
        order = load(ORDER)
        ambient = next(
            element
            for element in order["elements"]
            if element["canonical_name"] == "Ambient Interaction V1"
        )
        ids = {source["id"] for source in ambient["normative_sources"]}
        self.assertIn(self.config["placeholder"], ids)
        for identifier in ids:
            self.assertFalse(
                identifier.startswith("DEC-0") and identifier != "DEC-047",
                f"unexpected decision number for Ambient: {identifier}",
            )

    def test_ambient_is_not_assigned_to_the_blocking_gates(self):
        order = load(ORDER)
        ambient = next(
            element
            for element in order["elements"]
            if element["canonical_name"] == "Ambient Interaction V1"
        )
        ids = {source["id"] for source in ambient["normative_sources"]}
        self.assertNotIn("DEC-050", ids)

    def test_no_ambient_adr_file_exists(self):
        for path in (_support.REPO_ROOT / "docs" / "adr").glob("*.md"):
            self.assertNotIn("ambient", path.name.lower())

    def test_the_runner_accepts_the_current_state(self):
        failures, _ = governance_checks.mode_ambient(_support.REPO_ROOT)
        self.assertEqual([failure["id"] for failure in failures], [])


class TestDeliveryOrder(unittest.TestCase):
    def setUp(self):
        self.order = load(ORDER)

    def _issues(self, mutate):
        broken = copy.deepcopy(self.order)
        mutate(broken)
        return {code for _, code in governance.check_delivery_order(broken)}

    def test_the_declared_order_is_valid(self):
        self.assertEqual(
            list(governance.check_delivery_order(self.order)), []
        )

    def test_positions_and_module_numbers_are_separate_fields(self):
        for element in self.order["elements"]:
            with self.subTest(element=element["canonical_name"]):
                self.assertIn("delivery_position", element)
                self.assertIn("fachmodul_number", element)

    def test_contacts_is_position_one_and_module_one(self):
        element = self.order["elements"][0]
        self.assertEqual(element["canonical_name"], "Kontakte")
        self.assertEqual(element["delivery_position"], 1)
        self.assertEqual(element["fachmodul_number"], 1)

    def test_calendar_is_position_two_and_module_two(self):
        element = self.order["elements"][1]
        self.assertEqual(element["canonical_name"], "Kalender")
        self.assertEqual(element["delivery_position"], 2)
        self.assertEqual(element["fachmodul_number"], 2)

    def test_ambient_is_position_three_without_module_number(self):
        element = self.order["elements"][2]
        self.assertEqual(element["canonical_name"], "Ambient Interaction V1")
        self.assertEqual(element["delivery_position"], 3)
        self.assertIsNone(element["fachmodul_number"])
        self.assertFalse(element["owns_domain_data"]["value"])

    def test_trading_is_position_four_and_module_three(self):
        element = self.order["elements"][3]
        self.assertEqual(element["canonical_name"], "Trading Intelligence T1")
        self.assertEqual(element["delivery_position"], 4)
        self.assertEqual(element["fachmodul_number"], 3)

    def test_duplicate_position_is_rejected(self):
        self.assertIn(
            "delivery_position_duplicated",
            self._issues(lambda d: d["elements"][1].__setitem__("delivery_position", 1)),
        )

    def test_position_gap_is_rejected(self):
        self.assertIn(
            "delivery_position_gap",
            self._issues(lambda d: d["elements"].pop(2)),
        )

    def test_ambient_with_a_module_number_is_rejected(self):
        self.assertIn(
            "fachmodul_number_present",
            self._issues(lambda d: d["elements"][2].__setitem__("fachmodul_number", 3)),
        )

    def test_ambient_with_domain_data_is_rejected(self):
        self.assertIn(
            "domain_data_ownership_present",
            self._issues(
                lambda d: d["elements"][2]["owns_domain_data"].__setitem__(
                    "value", True
                )
            ),
        )

    def test_trading_as_module_four_is_rejected(self):
        self.assertIn(
            "fachmodul_number_mismatch",
            self._issues(lambda d: d["elements"][3].__setitem__("fachmodul_number", 4)),
        )

    def test_trading_on_position_three_is_rejected(self):
        def mutate(document):
            document["elements"][3]["delivery_position"] = 3
            document["elements"][2]["delivery_position"] = 4

        issues = self._issues(mutate)
        self.assertTrue(
            {"element_not_at_expected_position", "delivery_position_gap"} & issues
        )

    def test_position_and_module_number_confusion_is_rejected(self):
        self.assertIn(
            "position_and_module_number_confused",
            self._issues(lambda d: d["elements"][3].__setitem__("fachmodul_number", 4)),
        )

    def test_an_additional_element_needs_an_owner_decision(self):
        def mutate(document):
            extra = copy.deepcopy(document["elements"][3])
            extra["delivery_position"] = 5
            extra["canonical_name"] = "Weiteres Element"
            extra["fachmodul_number"] = 9
            document["elements"].append(extra)

        self.assertIn(
            "additional_element_without_owner_decision", self._issues(mutate)
        )

    def test_a_missing_field_is_rejected(self):
        self.assertIn(
            "order_field_missing",
            self._issues(lambda d: d["elements"][0].pop("acceptance_profile")),
        )

    def test_the_wrong_normative_source_is_rejected(self):
        def mutate(document):
            document["elements"][0]["normative_sources"] = document[
                "forbidden_order_sources"
            ]

        self.assertIn("wrong_order_source_assigned", self._issues(mutate))

    def test_a_replaced_ambient_placeholder_is_rejected(self):
        self.assertIn(
            "ambient_placeholder_replaced",
            self._issues(lambda d: d.__setitem__("ambient_placeholder", "DEC-051")),
        )

    def test_the_document_lists_all_eighteen_failure_conditions(self):
        text = (DOCS / "b0a-2-delivery-order.md").read_text(encoding="utf-8")
        section = text.split("## §5")[1]
        numbered = [
            line for line in section.splitlines() if line.strip()[:2].rstrip(".").isdigit()
        ]
        self.assertGreaterEqual(len(numbered), 18)


class TestDocumentConsistency(unittest.TestCase):
    def test_document_and_machine_source_agree(self):
        order = load(ORDER)
        text = (DOCS / "b0a-2-delivery-order.md").read_text(encoding="utf-8")
        self.assertEqual(
            list(governance.check_document_consistency(order, text)), []
        )

    def test_a_divergent_document_is_detected(self):
        order = load(ORDER)
        text = (DOCS / "b0a-2-delivery-order.md").read_text(encoding="utf-8")
        broken = text.replace(
            "| 3 | Ambient Interaction V1 | technischer Produktblock | keine | nein |",
            "| 3 | Ambient Interaction V1 | Fachmodul | 3 | ja |",
        )
        issues = {code for _, code in governance.check_document_consistency(order, broken)}
        self.assertTrue(issues)


class TestQualifiedReferences(unittest.TestCase):
    def setUp(self):
        self.index = governance.citation_index(load(CITATIONS))

    def test_every_governance_document_is_qualified(self):
        failures, _ = governance_checks.mode_citations(_support.REPO_ROOT)
        self.assertEqual([failure["id"] for failure in failures], [])

    def test_a_bare_reference_is_rejected(self):
        issues = list(
            governance.check_document_citations("Siehe DEC-045 dazu.\n", self.index)
        )
        self.assertEqual(codes(issues), {"reference_not_qualified"})

    def test_a_wrong_title_is_rejected(self):
        text = 'DEC-045 (jarvis/rebuild-v1@c222601, „Falscher Titel")\n'
        issues = list(governance.check_document_citations(text, self.index))
        self.assertEqual(codes(issues), {"reference_not_qualified"})

    def test_a_wrong_line_is_rejected(self):
        # A contacts-line decision attributed to the canonical line.
        text = (
            'DEC-052 (jarvis/rebuild-v1@c222601, '
            '„App-Prozess-Mutationskanal eingefroren")\n'
        )
        issues = list(governance.check_document_citations(text, self.index))
        self.assertEqual(codes(issues), {"reference_not_qualified"})

    def test_an_unknown_id_is_rejected(self):
        issues = list(
            governance.check_document_citations("Neu: DEC-099 taucht auf.\n", self.index)
        )
        self.assertEqual(codes(issues), {"reference_id_unknown"})

    def test_code_spans_are_exempt(self):
        # Fixture uses the canonical line jarvis/rebuild-v1 identifier.
        issues = list(
            governance.check_document_citations(
                "Der Bezeichner `DEC-045` steht in einer Tabelle.\n", self.index
            )
        )
        self.assertEqual(issues, [])

    def test_a_correct_citation_is_accepted(self):
        text = (
            'DEC-045 (jarvis/rebuild-v1@c222601, '
            '„Verbindliche Modulreihenfolge bis Modul 3") gilt.\n'
        )
        self.assertEqual(
            list(governance.check_document_citations(text, self.index)), []
        )


class TestToolingMergeAssignment(unittest.TestCase):
    def test_dec_045_canonical_and_dec_055_contacts_are_assigned(self):
        policy = load(CONFIG / "tooling-merge.json")
        assigned = {(entry["id"], entry["line"]) for entry in policy["assigned_decisions"]}
        # After the B0a-3 renumbering the contacts side is DEC-055.
        self.assertEqual(
            assigned, {("DEC-045", "canonical"), ("DEC-055", "contacts_calendar")}
        )

    def test_dec_050_is_explicitly_not_assigned(self):
        policy = load(CONFIG / "tooling-merge.json")
        not_assigned = {entry["id"] for entry in policy["not_assigned_decisions"]}
        self.assertEqual(not_assigned, {"DEC-050"})
        order = load(ORDER)
        self.assertEqual(
            {entry["id"] for entry in order["not_assigned_to_tooling_merge"]},
            {"DEC-050"},
        )

    def test_the_addendum_states_the_non_assignment(self):
        text = (DOCS / "b0a-2-tooling-merge-addendum.md").read_text(encoding="utf-8")
        self.assertIn("**Ausdrücklich nicht zugeordnet** ist", text)


class TestClaudeMd(unittest.TestCase):
    def setUp(self):
        self.text = (_support.REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    def test_b0a_1_sections_are_preserved(self):
        for heading in (
            "## Identität",
            "## Harte Grenzen",
            "## Standard-Verhalten",
            "## Arbeitsbereich",
            "## Gates, Ergebnisse und Baseline",
            "## Evidenz und Datenschutz",
            "## Agenten-Philosophie",
            "## Erweiterbarkeit",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.text)

    def test_governance_rules_are_added(self):
        for marker in (
            "Capability-Verträge",
            "providerneutral",
            "Adaptergrenze",
            "Lieferposition",
            "{{DEC_ID_AMBIENT_INTERACTION_V1}}",
            "Merkmalsvergleich",
            ".claude/settings.local.json",
            "Eigentümerhandlung",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
