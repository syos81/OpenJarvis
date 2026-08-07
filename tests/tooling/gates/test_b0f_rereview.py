"""The B0f category re-examination's repair: unreadable is not empty.

The blind review rejected the exclusion at ``governance.adr_entries``: a
per-file read failure was normalised to an empty document, and two
unreadable sides compare equal — a real title collision masked
symmetrically. The mandatory pair for RC-027:

*Sharpening.* A listing entry whose content cannot be read makes the whole
listing ``None`` — the module's existing non-evidence protocol — instead of
an entry with an empty title.

*Counter.* Readable sources parse exactly as before, and the consumers'
``None`` handling (``adr_directory_unreadable`` and friends) is already
covered by the existing governance suite, which must stay green.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.gates import governance  # noqa: E402


class TestUnreadableIsNotEmpty(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="b0f-rereview-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "docs" / "adr").mkdir(parents=True)

    def test_an_unreadable_primary_source_yields_no_listing(self):
        # A directory where a file is expected: listed, but unreadable as
        # content — the shape of a per-file read failure, constructed rather
        # than perturbed.
        (self.root / "docs" / "adr" / "ADR-0001-broken.md").mkdir()
        (self.root / "docs" / "adr" / "ADR-0002-fine.md").write_text(
            "# ADR-0002: A readable title\n", encoding="utf-8"
        )
        self.assertIsNone(governance.adr_entries(None, self.root))

    def test_two_unreadable_sides_can_no_longer_compare_equal(self):
        """The masked-collision shape: before the repair both sides parsed
        to ``(name, "")`` and compared equal."""
        (self.root / "docs" / "adr" / "ADR-0001-broken.md").mkdir()
        first = governance.adr_entries(None, self.root)
        second = governance.adr_entries(None, self.root)
        self.assertIsNone(first)
        self.assertIsNone(second)
        # ``None`` is the non-evidence protocol every consumer turns into a
        # visible failure; there is no entries dict left to compare equal.

    def test_readable_sources_parse_exactly_as_before(self):
        (self.root / "docs" / "adr" / "ADR-0002-fine.md").write_text(
            "# ADR-0002: A readable title\n", encoding="utf-8"
        )
        entries = governance.adr_entries(None, self.root)
        self.assertEqual(
            entries,
            {"ADR-0002": ("ADR-0002-fine.md", "ADR-0002: A readable title")},
        )


class TestScopeReaderValidatesEntries(unittest.TestCase):
    """RC-028: the generality scope reader rejects a declaration whose
    ``paths`` key is silently absent (found by the category re-examination:
    the old structural reader validated top-level fields only, so the
    key-deletion probe held against the wrong key)."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="b0f-scope-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        import json

        self.document = json.loads(
            (REPO_ROOT / "config" / "governance" / "generality-scope.json").read_text()
        )
        self.target = self.root / "config" / "governance"
        self.target.mkdir(parents=True)

    def _write_and_load(self):
        import json

        relative = "config/governance/generality-scope.json"
        (self.root / relative).write_text(
            json.dumps(self.document), encoding="utf-8"
        )
        from tools.gates import generality

        return generality.load_scope_document(str(self.root), relative)

    def test_a_declaration_without_paths_is_rejected(self):
        from tools.gates import generality

        del self.document["declared_identifiers"][0]["paths"]
        self.assertNotIn(
            "paths", self.document["declared_identifiers"][0],
            "the key withdrawal had no effect",
        )
        with self.assertRaises(generality.ScopeError) as caught:
            self._write_and_load()
        self.assertEqual(
            caught.exception.code, "declared_identifier_field_missing"
        )

    def test_the_real_scope_document_is_accepted_unchanged(self):
        document = self._write_and_load()
        self.assertEqual(
            len(document["declared_identifiers"]),
            len(self.document["declared_identifiers"]),
        )

    def test_an_explicitly_empty_paths_list_stays_legitimate(self):
        self.document["declared_identifiers"][0]["paths"] = []
        document = self._write_and_load()
        self.assertEqual(document["declared_identifiers"][0]["paths"], [])


class TestAnchorDeclarationIsNotOptional(unittest.TestCase):
    """RC-031: the check_anchors repair the B0e register prescribed but no
    commit implemented — found by the B0f blind review chain. An absent
    gate anchoring declaration is a problem, never an empty walk."""

    def _check(self, definition):
        import tempfile

        from tools.gates.runners import history_checks

        with tempfile.TemporaryDirectory(prefix="b0f-anchors-") as tmp:
            return history_checks.check_anchors(Path(tmp), definition)

    def test_an_absent_declaration_is_a_problem(self):
        problems = self._check({"other": 1})
        self.assertEqual(
            problems, [("gate_anchoring", "gate_anchoring_undeclared")]
        )
        problems = self._check({"gate_anchoring": {"note": "no anchors key"}})
        self.assertEqual(
            problems, [("gate_anchoring", "gate_anchoring_undeclared")]
        )

    def test_an_undeclared_empty_anchor_set_is_a_problem(self):
        problems = self._check({"gate_anchoring": {"anchors": []}})
        self.assertEqual(
            problems, [("gate_anchoring", "anchor_set_empty_without_reason")]
        )

    def test_a_declared_empty_anchor_set_stays_legitimate(self):
        problems = self._check(
            {
                "gate_anchoring": {
                    "anchors": [],
                    "declared_empty_reason": "no gate rests on a dangling reference in this definition",
                }
            }
        )
        self.assertEqual(problems, [])

    def test_the_real_definition_still_passes(self):
        import json

        definition = json.loads(
            (REPO_ROOT / "config" / "gates" / "k1" / "calendar-k1-definition.json").read_text()
        )
        from tools.gates.runners import history_checks

        problems = history_checks.check_anchors(REPO_ROOT, definition)
        self.assertEqual(problems, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
