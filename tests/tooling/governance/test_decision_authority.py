"""B0g: the authority binding model refuses every duplicated truth.

Each negative fixture mutates exactly one aspect of a valid model and the
validator must name the defect. The positive fixture proves the checks are
non-vacuous: the same tree with the mutation removed validates cleanly.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.gates import decauthority  # noqa: E402

FRAGMENT = "OPERATIVER SATZ EINS DER FIXTURE-ENTSCHEIDUNG"
DOC = (
    "---\n"
    "DEC-ID: DEC-001\n"
    "Titel: Fixture\n"
    "Status: accepted\n"
    "Regel-Alias: R1\n"
    "---\n\n"
    f"## Entscheidung (normativ)\n\n{FRAGMENT}\n"
)


def base_model():
    return {
        "schema_version": 1,
        "kind": "decision_authority_model",
        "statement": "fixture",
        "register_ref": "refs/governance/dec-reservations",
        "register_row_file": "register.md",
        "roles": ["authoritative", "derived_enforcement", "reference_only"],
        "fragment_scan": {
            "roots": ["config", "ref.md"],
            "exempt_paths": [],
            "exempt_with_reason": [],
        },
        "decisions": [{
            "alias": "R1",
            "dec_id": "DEC-001",
            "authoritative_path": "docs/DEC-001-fixture.md",
            "carriers": [
                {"path": "config/carrier.json", "role": "derived_enforcement",
                 "validation": "read by the fixture checker"},
                {"path": "ref.md", "role": "reference_only", "validation": ""},
            ],
            "forbidden_fragments": [FRAGMENT],
        }],
    }


class AuthorityFixture(unittest.TestCase):
    def setUp(self):
        super().setUp()
        import shutil

        self.root = Path(tempfile.mkdtemp(prefix="b0g-authority-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "docs").mkdir()
        (self.root / "config").mkdir()
        (self.root / "docs" / "DEC-001-fixture.md").write_text(
            DOC, encoding="utf-8"
        )
        (self.root / "config" / "carrier.json").write_text(
            json.dumps({"statement": "Normative Quelle: DEC-001"}),
            encoding="utf-8",
        )
        (self.root / "ref.md").write_text(
            "Normativ: DEC-001 — Fixture.\n", encoding="utf-8"
        )
        (self.root / "register.md").write_text(
            "| DEC-001 | Fixture | accepted | q | d |\n", encoding="utf-8"
        )

    def run_validate(self, model, register_ids=frozenset({"DEC-001"})):
        findings, stats = decauthority.validate(
            model, self.root, set(register_ids)
        )
        return [item["code"] for item in findings], stats


class TestPositive(AuthorityFixture):
    def test_the_untouched_fixture_validates_cleanly(self):
        codes, stats = self.run_validate(base_model())
        self.assertEqual(codes, [])
        self.assertEqual(stats["decisions"], 1)
        self.assertGreater(stats["scanned"], 0)


class TestNegativeFixtures(AuthorityFixture):
    def test_a_second_authoritative_carrier_is_refused(self):
        model = base_model()
        model["decisions"][0]["carriers"].append(
            {"path": "ref.md", "role": "authoritative", "validation": ""}
        )
        codes, _ = self.run_validate(model)
        self.assertIn("second_authoritative_carrier", codes)

    def test_a_decision_without_an_authority_is_refused(self):
        model = base_model()
        model["decisions"][0]["authoritative_path"] = ""
        codes, _ = self.run_validate(model)
        self.assertIn("authoritative_missing", codes)

    def test_operative_text_in_a_reference_carrier_is_refused(self):
        (self.root / "ref.md").write_text(
            f"Normativ: DEC-001.\n\n{FRAGMENT}\n", encoding="utf-8"
        )
        codes, _ = self.run_validate(base_model())
        self.assertIn("operative_text_outside_authority", codes)

    def test_enforcement_without_validation_is_refused(self):
        model = base_model()
        model["decisions"][0]["carriers"][0]["validation"] = "  "
        codes, _ = self.run_validate(model)
        self.assertIn("enforcement_without_validation", codes)

    def test_an_alias_without_a_dec_id_is_refused(self):
        model = base_model()
        model["decisions"][0]["dec_id"] = ""
        codes, _ = self.run_validate(model)
        self.assertIn("dec_id_missing", codes)

    def test_a_frontmatter_id_mismatch_is_refused(self):
        wrong_document = (
            "---\n"
            "DEC-ID: DEC-999\n"
            "Titel: Fixture\n"
            "Status: accepted\n"
            "Regel-Alias: R1\n"
            "---\n\n"
            f"## Entscheidung (normativ)\n\n{FRAGMENT}\n"
        )
        (self.root / "docs" / "DEC-001-fixture.md").write_text(
            wrong_document, encoding="utf-8"
        )
        codes, _ = self.run_validate(base_model())
        self.assertIn("frontmatter_dec_id_mismatch", codes)

    def test_two_aliases_on_one_dec_id_are_refused(self):
        model = base_model()
        second = copy.deepcopy(model["decisions"][0])
        second["alias"] = "R2"
        model["decisions"].append(second)
        codes, _ = self.run_validate(model)
        self.assertIn("dec_id_bound_twice", codes)

    def test_a_missing_register_row_is_refused(self):
        codes, _ = self.run_validate(base_model(), register_ids=frozenset())
        self.assertIn("register_row_missing", codes)

    def test_a_fragment_missing_from_its_own_document_is_refused(self):
        model = base_model()
        model["decisions"][0]["forbidden_fragments"] = ["NIE IM DOKUMENT"]
        codes, _ = self.run_validate(model)
        self.assertIn("fragment_not_in_authoritative", codes)

    def test_an_empty_scan_set_never_passes(self):
        (self.root / "leer").mkdir()
        model = base_model()
        model["fragment_scan"]["roots"] = ["leer"]
        codes, _ = self.run_validate(model)
        self.assertIn("scan_set_empty", codes)

    def test_a_carrier_without_the_marker_is_refused(self):
        (self.root / "config" / "carrier.json").write_text(
            json.dumps({"statement": "kein marker"}), encoding="utf-8"
        )
        codes, _ = self.run_validate(base_model())
        self.assertIn("carrier_without_marker", codes)

    def test_an_exemption_without_a_reason_is_refused(self):
        model = base_model()
        model["fragment_scan"]["exempt_with_reason"] = [
            {"path": "ref.md", "reason": " "}
        ]
        codes, _ = self.run_validate(model)
        self.assertIn("exemption_without_reason", codes)


class TestLoaders(unittest.TestCase):
    def write(self, document):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(document, handle)
        handle.close()
        self.addCleanup(Path(handle.name).unlink, True)
        return handle.name

    def test_the_model_loader_refuses_an_unknown_field(self):
        model = base_model()
        model["extra"] = 1
        with self.assertRaises(decauthority.AuthorityError):
            decauthority.load_model(self.write(model))

    def test_the_model_loader_refuses_an_open_role_set(self):
        model = base_model()
        model["roles"] = ["authoritative", "irgendwas"]
        with self.assertRaises(decauthority.AuthorityError):
            decauthority.load_model(self.write(model))

    def test_an_assigned_record_without_a_commit_is_refused(self):
        with self.assertRaises(decauthority.AuthorityError):
            decauthority.load_assignment(self.write({
                "schema_version": 1, "kind": "b0g_assignment_record",
                "statement": "s", "stage": "assigned",
                "register_ref": "r", "expected_remote_oid": "x",
                "expected_events": 1, "genesis_events": 0,
                "dec_ids": ["DEC-001"], "normative_commit": None,
            }))

    def test_a_reserved_record_with_a_commit_is_refused(self):
        with self.assertRaises(decauthority.AuthorityError):
            decauthority.load_assignment(self.write({
                "schema_version": 1, "kind": "b0g_assignment_record",
                "statement": "s", "stage": "reserved",
                "register_ref": "r", "expected_remote_oid": "x",
                "expected_events": 1, "genesis_events": 0,
                "dec_ids": ["DEC-001"], "normative_commit": "a" * 40,
            }))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
