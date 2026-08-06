"""Reference resolution against frozen documents.

A frozen document is never edited. When it cites a reference that does not
exist, the citation stays exactly as it is and an erratum resolves it. The
three properties this file exists for:

*no chaining*     an erratum may not point at a reference that is itself only
                  resolvable through another erratum
*no ambiguity*    two errata for one reference are an error, not a choice
*no drift*        an erratum is bound by digest to the document it corrects,
                  so it can never float away from the wording it repairs

Everything is built on synthetic documents. The real errata document is
checked separately, against the real frozen baseline, and is never modified
here.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import errata  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

FROZEN = "docs/synthetic/frozen-baseline.md"
ANCHOR = "docs/synthetic/really-existing-register.md"

FROZEN_TEXT = """# Synthetic frozen baseline

## §5 Replacement plan

The criterion is carried by Register 20 §5, which does not exist.
"""
ANCHOR_TEXT = """# Really existing register

## §1 Canonicity

The index is derived exclusively and can be rebuilt at any time.
"""


class ErrataRoot(unittest.TestCase):
    """A synthetic worktree with one frozen document and one anchor."""

    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="errata-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "docs" / "synthetic").mkdir(parents=True)
        (self.root / "config" / "governance").mkdir(parents=True)
        self.write_frozen(FROZEN_TEXT)
        (self.root / ANCHOR).write_text(ANCHOR_TEXT, encoding="utf-8")

    def write_frozen(self, text):
        (self.root / FROZEN).write_text(text, encoding="utf-8")
        self.digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    def erratum(self, **overrides):
        entry = {
            "erratum_id": "ERR-SYNTH-001",
            "affected_document": FROZEN,
            "affected_document_sha256": self.digest,
            "citing_section": "## §5 Replacement plan",
            "invalid_reference": "Register 20 §5",
            "reason": "The cited register does not exist; the criterion is carried elsewhere.",
            "replacement_anchors": [
                {
                    "path": ANCHOR,
                    "section": "§1 Canonicity",
                    "quote_anchor": "derived exclusively",
                }
            ],
            "recorded_at_utc": "2026-08-06T12:00:00Z",
            "source_commit": "a" * 40,
        }
        entry.update(overrides)
        return entry

    def write_document(self, entries, **overrides):
        document = {
            "schema_version": 1,
            "kind": "frozen_document_errata",
            "statement": "A frozen document is never edited.",
            "errata": entries,
        }
        document.update(overrides)
        (self.root / errata.ERRATA_PATH).write_text(
            json.dumps(document), encoding="utf-8"
        )
        return document

    def assertRejected(self, code):
        with self.assertRaises(errata.ErrataDocumentError) as caught:
            errata.load_document(self.root)
        self.assertEqual(caught.exception.code, code)


class TestResolution(ErrataRoot):
    def test_a_sound_erratum_resolves_the_reference(self):
        self.write_document([self.erratum()])
        outcome = errata.resolve(self.root, "Register 20 §5")
        self.assertTrue(outcome.resolved)
        self.assertEqual(outcome.code, "resolved_via_erratum")
        self.assertEqual(outcome.erratum_id, "ERR-SYNTH-001")
        self.assertEqual(len(outcome.anchors), 1)

    def test_a_reference_no_erratum_covers_stays_unresolved(self):
        self.write_document([self.erratum()])
        outcome = errata.resolve(self.root, "Register 21 §9")
        self.assertFalse(outcome.resolved)
        self.assertEqual(outcome.code, "unresolved_reference")

    def test_an_absent_document_resolves_nothing(self):
        outcome = errata.resolve(self.root, "Register 20 §5")
        self.assertFalse(outcome.resolved)
        self.assertEqual(outcome.code, "unresolved_reference")


class TestNoAmbiguity(ErrataRoot):
    def test_two_errata_for_one_reference_are_an_error(self):
        second = self.erratum(erratum_id="ERR-SYNTH-002")
        self.write_document([self.erratum(), second])
        outcome = errata.resolve(self.root, "Register 20 §5")
        self.assertFalse(outcome.resolved)
        self.assertEqual(outcome.code, "ambiguous_erratum")

    def test_the_document_reader_rejects_the_ambiguity_too(self):
        self.write_document(
            [self.erratum(), self.erratum(erratum_id="ERR-SYNTH-002")]
        )
        self.assertRejected("ambiguous_erratum")

    def test_a_duplicated_erratum_id_is_rejected(self):
        """Two errata that share an id are refused before anything else.

        The id is checked before the reference, so a document carrying both
        defects reports the identity collision. Deterministic and stable:
        the reader always names the first defect it can establish.
        """
        self.write_document([self.erratum(), self.erratum()])
        self.assertRejected("erratum_id_duplicated")


class TestNoChaining(ErrataRoot):
    def test_an_anchor_that_is_itself_an_invalid_reference_is_refused(self):
        """An erratum may not lean on something another erratum repairs."""
        chained = self.erratum(
            replacement_anchors=[
                {
                    "path": ANCHOR,
                    "section": "§1 Canonicity",
                    "quote_anchor": "Register 21 §9",
                }
            ]
        )
        other = self.erratum(
            erratum_id="ERR-SYNTH-002", invalid_reference="Register 21 §9"
        )
        self.write_document([chained, other])
        outcome = errata.resolve(self.root, "Register 20 §5")
        self.assertFalse(outcome.resolved)
        self.assertIn(outcome.code, ("chained_erratum", "erratum_anchor_does_not_carry"))

    def test_a_chain_is_refused_even_when_the_anchor_carries_the_wording(self):
        (self.root / ANCHOR).write_text(
            ANCHOR_TEXT + "\nRegister 21 §9 is named here.\n", encoding="utf-8"
        )
        chained = self.erratum(
            replacement_anchors=[
                {
                    "path": ANCHOR,
                    "section": "§1 Canonicity",
                    "quote_anchor": "Register 21 §9",
                }
            ]
        )
        other = self.erratum(
            erratum_id="ERR-SYNTH-002", invalid_reference="Register 21 §9"
        )
        self.write_document([chained, other])
        outcome = errata.resolve(self.root, "Register 20 §5")
        self.assertFalse(outcome.resolved)
        self.assertEqual(outcome.code, "chained_erratum")

    def test_an_erratum_may_not_repair_itself(self):
        circular = self.erratum(
            replacement_anchors=[
                {
                    "path": FROZEN,
                    "section": "§5",
                    "quote_anchor": "Replacement plan",
                }
            ]
        )
        self.write_document([circular])
        self.assertRejected("erratum_anchor_is_the_affected_document")


class TestNoDrift(ErrataRoot):
    def test_a_changed_frozen_document_invalidates_the_erratum(self):
        """The digest binding is the whole point: an erratum never floats."""
        self.write_document([self.erratum()])
        self.assertTrue(errata.resolve(self.root, "Register 20 §5").resolved)

        stale_digest = self.digest
        self.write_frozen(FROZEN_TEXT + "\nOne more sentence.\n")
        self.assertNotEqual(self.digest, stale_digest)
        self.assertRejected("erratum_document_digest_mismatch")

    def test_a_missing_frozen_document_is_detected(self):
        self.write_document([self.erratum()])
        (self.root / FROZEN).unlink()
        self.assertRejected("erratum_document_missing")

    def test_a_declared_digest_that_is_not_a_digest_is_rejected(self):
        self.write_document([self.erratum(affected_document_sha256="nope")])
        self.assertRejected("erratum_document_digest_invalid")

    def test_the_reference_must_really_be_in_the_document(self):
        self.write_document(
            [self.erratum(invalid_reference="A wording the document never carries")]
        )
        self.assertRejected("erratum_reference_not_in_document")

    def test_the_citing_section_must_really_be_in_the_document(self):
        self.write_document([self.erratum(citing_section="## §9 Nowhere")])
        self.assertRejected("erratum_citing_section_not_in_document")

    def test_an_anchor_that_does_not_carry_its_wording_is_rejected(self):
        self.write_document(
            [
                self.erratum(
                    replacement_anchors=[
                        {
                            "path": ANCHOR,
                            "section": "§1 Canonicity",
                            "quote_anchor": "wording that is simply not there",
                        }
                    ]
                )
            ]
        )
        self.assertRejected("erratum_anchor_does_not_carry")

    def test_an_erratum_without_an_anchor_is_rejected(self):
        self.write_document([self.erratum(replacement_anchors=[])])
        self.assertRejected("erratum_without_replacement_anchor")


class TestTheDocumentReader(ErrataRoot):
    def test_a_sound_document_loads(self):
        self.write_document([self.erratum()])
        document = errata.load_document(self.root)
        self.assertEqual(len(document["errata"]), 1)

    def test_an_unknown_top_level_field_is_rejected(self):
        self.write_document([self.erratum()], something_new=True)
        self.assertRejected("errata_document_unknown_field")

    def test_an_unknown_erratum_field_is_rejected(self):
        entry = self.erratum()
        entry["extra"] = True
        self.write_document([entry])
        self.assertRejected("erratum_unknown_field")

    def test_a_wrong_kind_is_rejected(self):
        self.write_document([self.erratum()], kind="something_else")
        self.assertRejected("errata_document_kind_unexpected")

    def test_a_malformed_timestamp_is_rejected(self):
        self.write_document([self.erratum(recorded_at_utc="yesterday")])
        self.assertRejected("erratum_timestamp_invalid")

    def test_a_malformed_source_commit_is_rejected(self):
        self.write_document([self.erratum(source_commit="abc")])
        self.assertRejected("erratum_source_commit_invalid")

    def test_a_missing_document_is_rejected_rather_than_treated_as_empty(self):
        self.assertRejected("errata_document_missing")


class TestTheRealDocument(unittest.TestCase):
    """The committed errata document, against the real frozen baseline."""

    def setUp(self):
        super().setUp()
        self.document = errata.load_document(REPO_ROOT)

    def test_it_loads_and_carries_at_least_one_erratum(self):
        self.assertTrue(self.document["errata"])

    def test_every_erratum_resolves_through_itself(self):
        for entry in self.document["errata"]:
            with self.subTest(erratum=entry["erratum_id"]):
                outcome = errata.resolve(
                    REPO_ROOT, entry["invalid_reference"],
                    errata=self.document["errata"],
                )
                self.assertTrue(outcome.resolved, outcome.code)
                self.assertEqual(outcome.erratum_id, entry["erratum_id"])

    def test_every_erratum_is_bound_to_the_document_it_corrects(self):
        for entry in self.document["errata"]:
            with self.subTest(erratum=entry["erratum_id"]):
                self.assertEqual(
                    errata.file_digest(REPO_ROOT, entry["affected_document"]),
                    entry["affected_document_sha256"],
                )

    def test_the_frozen_document_still_carries_the_invalid_citation(self):
        """The citation is not repaired in place. It stays exactly as it is."""
        for entry in self.document["errata"]:
            with self.subTest(erratum=entry["erratum_id"]):
                self.assertTrue(
                    errata.carries(
                        REPO_ROOT,
                        entry["affected_document"],
                        entry["invalid_reference"],
                    )
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
