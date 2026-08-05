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
    def setUp(self):
        self.registry = load(COLLISIONS)

    def test_all_seven_known_collisions_are_registered(self):
        registered = {collision["id"] for collision in self.registry["collisions"]}
        self.assertEqual(
            registered,
            {
                "DEC-044",
                "DEC-045",
                "DEC-046",
                "DEC-047",
                "DEC-048",
                "ADR-0019",
                "ADR-0020",
            },
        )

    def test_every_collision_declares_both_lines(self):
        for collision in self.registry["collisions"]:
            with self.subTest(collision=collision["id"]):
                lines = {side["line"] for side in collision["sides"]}
                self.assertEqual(lines, {"canonical", "contacts_calendar"})

    def test_every_side_matches_its_primary_source(self):
        issues = list(
            governance.verify_collision_sides(self.registry, _support.REPO_ROOT)
        )
        self.assertEqual(issues, [])

    def test_a_missing_side_is_detected(self):
        broken = copy.deepcopy(self.registry)
        broken["collisions"][0]["sides"] = broken["collisions"][0]["sides"][:1]
        issues = list(governance.verify_collision_sides(broken, _support.REPO_ROOT))
        self.assertIn("collision_side_missing", codes(issues))

    def test_a_swapped_title_is_detected(self):
        broken = copy.deepcopy(self.registry)
        first, second = broken["collisions"][0]["sides"]
        first["title"], second["title"] = second["title"], first["title"]
        issues = list(governance.verify_collision_sides(broken, _support.REPO_ROOT))
        self.assertIn("collision_title_mismatch", codes(issues))

    def test_a_swapped_line_is_detected(self):
        broken = copy.deepcopy(self.registry)
        first, second = broken["collisions"][0]["sides"]
        first["line"], second["line"] = second["line"], first["line"]
        issues = list(governance.verify_collision_sides(broken, _support.REPO_ROOT))
        self.assertIn("collision_title_mismatch", codes(issues))

    def test_a_wrong_primary_source_is_detected(self):
        broken = copy.deepcopy(self.registry)
        adr = next(c for c in broken["collisions"] if c["kind"] == "ADR")
        adr["sides"][0]["primary_source"] = "docs/adr/ADR-0001-personal-runtime-facade.md"
        issues = list(governance.verify_collision_sides(broken, _support.REPO_ROOT))
        self.assertIn("collision_primary_source_mismatch", codes(issues))

    def test_detection_finds_exactly_the_registered_collisions(self):
        detected, error = governance.detect_collisions(
            self.registry, _support.REPO_ROOT
        )
        self.assertIsNone(error)
        registered = {collision["id"] for collision in self.registry["collisions"]}
        self.assertEqual(detected, registered)

    def test_an_unregistered_collision_would_be_reported(self):
        shortened = copy.deepcopy(self.registry)
        shortened["collisions"] = shortened["collisions"][:-1]
        failures, _ = self._run_with(shortened)
        self.assertIn("collision_unregistered", {f["code"] for f in failures})

    def test_a_silently_resolved_collision_would_be_reported(self):
        extended = copy.deepcopy(self.registry)
        extended["collisions"].append(
            {
                "id": "DEC-030",
                "kind": "DEC",
                "sides": [
                    {
                        "line": "canonical",
                        "title": "Erstes Fachmodul: Kontakte",
                        "primary_source": governance.REGISTER_PATH,
                    },
                    {
                        "line": "contacts_calendar",
                        "title": "Erstes Fachmodul: Kontakte",
                        "primary_source": governance.REGISTER_PATH,
                    },
                ],
            }
        )
        failures, _ = self._run_with(extended)
        self.assertIn("collision_silently_resolved", {f["code"] for f in failures})

    def _run_with(self, registry):
        import tempfile

        with tempfile.TemporaryDirectory(prefix="collisions-") as tmp:
            root = Path(tmp)
            (root / "config" / "governance").mkdir(parents=True)
            (root / "config" / "governance" / "decision-collisions.json").write_text(
                json.dumps(registry), encoding="utf-8"
            )
            # git operations still run against the real repository
            original = governance.load_json
            try:
                governance.load_json = lambda path: registry  # noqa: E731
                return governance_checks.mode_collisions(_support.REPO_ROOT)
            finally:
                governance.load_json = original

    def test_b0a_2_accepts_documented_collisions(self):
        failures, diagnostics = governance_checks.mode_collisions(_support.REPO_ROOT)
        self.assertEqual([failure["id"] for failure in failures], [])
        self.assertIn("registered_collisions=7", diagnostics)

    def test_the_registry_declares_the_collisions_as_unresolved(self):
        self.assertFalse(self.registry["resolution"]["resolved_in_b0a_2"])
        self.assertEqual(self.registry["resolution"]["resolution_context"], "integration")


class TestIdFreeze(unittest.TestCase):
    def test_no_new_decision_id_and_no_new_adr_file(self):
        failures, diagnostics = governance_checks.mode_id_freeze(_support.REPO_ROOT)
        self.assertEqual([failure["id"] for failure in failures], [])
        self.assertTrue(any(item.startswith("touched_paths=") for item in diagnostics))

    def test_a_register_row_in_a_governance_document_is_forbidden(self):
        self.assertTrue(governance.DEC_ROW_RE.match("| DEC-051 | Neue Entscheidung |"))
        self.assertIsNone(governance.DEC_ROW_RE.match("DEC-051 ist keine Zeile"))

    def test_no_adr_directory_change_in_the_guarded_range(self):
        from tools.gates import gitutil, guardbase

        base = guardbase.derive_for_repository(_support.REPO_ROOT)["base_commit"]
        code, out, _ = gitutil.run_git(
            ["diff", "--name-only", base, "HEAD", "--", "docs/adr"],
            cwd=_support.REPO_ROOT,
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")


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
        text = (
            'DEC-045 (handoff/contacts-read-flow-2026-07-29@1f03bfa, '
            '„Verbindliche Modulreihenfolge bis Modul 3")\n'
        )
        issues = list(governance.check_document_citations(text, self.index))
        self.assertEqual(codes(issues), {"reference_not_qualified"})

    def test_an_unknown_id_is_rejected(self):
        issues = list(
            governance.check_document_citations("Neu: DEC-099 taucht auf.\n", self.index)
        )
        self.assertEqual(codes(issues), {"reference_id_unknown"})

    def test_code_spans_are_exempt(self):
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
    def test_dec_045_and_dec_048_are_assigned(self):
        policy = load(CONFIG / "tooling-merge.json")
        assigned = {(entry["id"], entry["line"]) for entry in policy["assigned_decisions"]}
        self.assertEqual(
            assigned, {("DEC-045", "canonical"), ("DEC-048", "contacts_calendar")}
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
