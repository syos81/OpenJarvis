"""Rule R4 — schema before data.

Two things are tested here and they are not the same thing:

* the **loader** side: a declared optional field is accepted, an undeclared
  field is still rejected. That is the change to an existing check rule, so
  it carries a sharpening test and a counter test.
* the **gate** side: every configuration file below a coverage root is bound
  to exactly one reader, that reader really runs, and the check has teeth —
  an unbound file, a stale binding and a field the reader does not accept
  each fail.

The teeth tests operate on a copy in a temporary directory. Nothing here
writes into the worktree, and no test ever leaves a repository in a state
where the guard could not decide.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import configload  # noqa: E402
from tools.guard import rules as guard_rules  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_JSON = REPO_ROOT / "tools" / "guard" / "rules.json"


class TestLoaderAcceptsWhatIsDeclared(unittest.TestCase):
    """The change to the existing unknown-field rule of ``load_rules``."""

    def _write(self, document):
        directory = Path(tempfile.mkdtemp(prefix="rules-config-"))
        self.addCleanup(shutil.rmtree, directory, True)
        target = directory / "rules.json"
        target.write_text(json.dumps(document), encoding="utf-8")
        return target

    def _document(self):
        return json.loads(RULES_JSON.read_text(encoding="utf-8"))

    def test_a_declared_optional_field_is_accepted(self):
        """Sharpening test for RC-012. Fails before the loader knows it."""
        rules = guard_rules.load_rules(str(RULES_JSON))
        self.assertIn("declared_roots", rules.fixture_targets)

    def test_an_absent_optional_field_is_still_accepted(self):
        document = self._document()
        document.pop("fixture_targets", None)
        rules = guard_rules.load_rules(str(self._write(document)))
        self.assertEqual(rules.fixture_targets, {})

    def test_an_undeclared_field_is_still_rejected(self):
        """Counter test for RC-012. The exemption is not a general opening."""
        document = self._document()
        document["something_the_loader_does_not_know"] = True
        with self.assertRaises(guard_rules.ConfigError) as caught:
            guard_rules.load_rules(str(self._write(document)))
        self.assertIn("rules_unknown_fields", str(caught.exception))

    def test_a_missing_required_field_is_still_rejected(self):
        document = self._document()
        document.pop("git_denies")
        with self.assertRaises(guard_rules.ConfigError) as caught:
            guard_rules.load_rules(str(self._write(document)))
        self.assertIn("rules_missing_fields", str(caught.exception))


class TestBindingsHoldForTheWorktree(unittest.TestCase):
    def test_every_configuration_file_has_exactly_one_declared_reader(self):
        document = configload.load_bindings(REPO_ROOT)
        assignment, uncovered, ambiguous = configload.assign(REPO_ROOT, document)
        self.assertEqual(uncovered, [])
        self.assertEqual(ambiguous, {})
        self.assertTrue(assignment)

    def test_the_full_check_passes(self):
        failures, diagnostics = configload.check(REPO_ROOT)
        self.assertEqual(failures, [])
        self.assertTrue(diagnostics)

    def test_the_binding_document_binds_itself(self):
        """R4 has no exception for its own declaration."""
        document = configload.load_bindings(REPO_ROOT)
        assignment, _uncovered, _ambiguous = configload.assign(REPO_ROOT, document)
        self.assertIn(configload.BINDINGS_PATH, assignment)


class TestTheCheckHasTeeth(unittest.TestCase):
    """Without these the check would only ever confirm itself."""

    def setUp(self):
        super().setUp()
        self.copy = Path(tempfile.mkdtemp(prefix="config-loaders-"))
        self.addCleanup(shutil.rmtree, self.copy, True)
        # ``docs`` is part of the copy because the errata reader binds itself
        # by digest to the frozen document it corrects; without the document
        # the reader would rightly reject, and the teeth tests would measure
        # a missing file instead of the defect they are about.
        for relative in ("config", "docs", "tools"):
            shutil.copytree(
                REPO_ROOT / relative,
                self.copy / relative,
                ignore=shutil.ignore_patterns("__pycache__"),
            )

    def _codes(self):
        failures, _diagnostics = configload.check(self.copy)
        return {code for _path, code in failures}

    def test_a_clean_copy_still_passes(self):
        self.assertEqual(self._codes(), set())

    def test_a_field_the_declared_reader_does_not_accept_fails(self):
        """Exactly the defect R4 exists for."""
        target = self.copy / "config" / "governance" / "delivery-order.json"
        document = json.loads(target.read_text(encoding="utf-8"))
        document["a_field_no_reader_declares"] = True
        target.write_text(json.dumps(document, indent=2), encoding="utf-8")
        codes = self._codes()
        self.assertTrue(
            any(code.startswith("field_not_accepted_by_the_declared_reader")
                for code in codes),
            codes,
        )

    def test_a_configuration_file_without_a_binding_fails(self):
        new = self.copy / "config" / "governance" / "unbound-example.json"
        new.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        self.assertIn("no_declared_loader", self._codes())

    def test_a_binding_that_matches_nothing_fails(self):
        target = self.copy / configload.BINDINGS_PATH
        document = json.loads(target.read_text(encoding="utf-8"))
        document["bindings"].append(
            {
                "binding_id": "stale-example",
                "pattern": "config/governance/does-not-exist-*.json",
                "kind": "structural",
                "expectation": "accepted",
                "required_fields": [],
                "optional_fields": [],
                "reason": "A stale binding must not hide a gap.",
            }
        )
        target.write_text(json.dumps(document, indent=2), encoding="utf-8")
        self.assertIn("binding_matches_nothing", self._codes())

    def test_two_bindings_for_one_file_fail(self):
        target = self.copy / configload.BINDINGS_PATH
        document = json.loads(target.read_text(encoding="utf-8"))
        document["bindings"].append(
            {
                "binding_id": "overlapping-example",
                "pattern": "config/governance/delivery-order.json",
                "kind": "structural",
                "expectation": "accepted",
                "required_fields": [],
                "optional_fields": ["*"],
                "reason": "Two readers mean no reader is authoritative.",
            }
        )
        target.write_text(json.dumps(document, indent=2), encoding="utf-8")
        codes = self._codes()
        self.assertTrue(
            any(code.startswith("several_declared_loaders") for code in codes),
            codes,
        )

    def test_a_real_loader_rejection_fails_the_check(self):
        target = self.copy / "tools" / "guard" / "rules.json"
        document = json.loads(target.read_text(encoding="utf-8"))
        document["still_unknown_to_the_loader"] = True
        target.write_text(json.dumps(document, indent=2), encoding="utf-8")
        self.assertIn("loader_rejected_the_file", self._codes())

    def test_an_invalid_fixture_that_starts_being_accepted_fails(self):
        """The inverted expectation is not decoration."""
        source = self.copy / "config/gates/fixtures/manifests/valid/minimal.json"
        target = self.copy / "config/gates/fixtures/manifests/invalid/unknown_field.json"
        shutil.copyfile(source, target)
        self.assertIn("loader_accepted_a_rejected_file", self._codes())

    def test_an_unusable_binding_document_is_a_failure_not_a_pass(self):
        target = self.copy / configload.BINDINGS_PATH
        target.write_text("{ not json", encoding="utf-8")
        failures, _diagnostics = configload.check(self.copy)
        self.assertEqual([code for _path, code in failures], ["bindings_not_json"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
