"""The disposition register: detected candidates == disposed candidates.

The first class exercises the comparison on a miniature worktree whose single
candidate is fully under the test's control: a candidate without a
disposition fails, a disposition without a candidate fails, a resolved
candidate that reappears fails, and an R9 ``mark_and_fix`` that is not
declared under the effect evidence convention fails. The second class is the
durable sweep: it derives the real corpus, runs both sweeps and holds this
repository to its own committed register — a new candidate anywhere in the
executable corpus fails this test until it is disposed.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.gates import astcorpus, astscan  # noqa: E402
from tests.tooling.gates.test_ast_corpus import MiniWorktree  # noqa: E402

LONG_REASON = (
    "The substitution needle is asserted present immediately before the "
    "write, so a silent no-op is impossible at this site."
)
LONG_NOTE = (
    "Assert the mutated bytes differ from the previous content before the "
    "expectation, as the first assertion of the test."
)


def register_skeleton():
    boundary = (
        "Operations that guarantee their after-state by their own semantics "
        "are excluded as a class; the exclusion is fixture tested."
    )
    rules = {}
    for rule, class_names in (
        (astscan.RULE_R9, astscan.R9_CLASSES),
        (astscan.RULE_R10, astscan.R10_CLASSES),
    ):
        rules[rule] = {
            "statement": f"Rule {rule} candidate register for the fixture worktree.",
            "candidate_classes": {name: f"fixture description of {name}" for name in class_names},
            "class_boundaries": {"stated_boundary": boundary},
        }
    return {
        "schema_version": astscan.REGISTER_SCHEMA_VERSION,
        "kind": "ast_disposition_register",
        "block_id": "fixture-block",
        "corpus_note": "derived by tools.gates.astcorpus over the fixture worktree",
        "rules": rules,
        "dispositions": [],
    }


def entry_for(root, candidate, disposition, *, reason=LONG_REASON, repair_note="",
              resolved_by_removal=False, category=None, category_proof=None):
    digest = hashlib.sha256((Path(root) / candidate.file).read_bytes()).hexdigest()
    entry = dict(candidate.as_dict())
    entry["disposition"] = disposition
    entry["reason"] = reason
    entry["repair_note"] = repair_note
    entry["resolved_by_removal"] = resolved_by_removal
    entry["source_digest"] = digest
    if disposition == "exclude_with_reason":
        # Schema 2: an exclusion is carried by a category, never by text.
        # The fixture candidate's write is followed by an assert that reads
        # the target, which the after-state category confirms structurally.
        entry["category"] = (
            "r9_after_state_observed" if category is None else category
        )
        entry["category_proof"] = {} if category_proof is None else category_proof
    else:
        entry["category"] = ""
        entry["category_proof"] = {}
    return entry


def effect_declaration(functions):
    return {
        "schema_version": 1,
        "kind": "effect_evidence_review",
        "rule": "R9",
        "statement": "fixture statement",
        "method": "fixture method",
        "scope": {
            "block_id": "fixture-block",
            "covers": "the fixture worktree",
            "deferred": "nothing",
            "not_claimed": "everything else",
        },
        "examined": [
            {
                "file": file,
                "function": function,
                "induced_effect": "fixture effect",
                "effect_assertion": "assert",
                "verdict": "evidenced",
                "evidence": "fixture evidence",
                "reason": "fixture reason",
            }
            for file, function in functions
        ],
        "open_findings": [],
    }


class RegisterFixture(MiniWorktree):
    def setUp(self):
        super().setUp()
        governance = self.root / "config" / "governance"
        governance.mkdir(parents=True)
        self.declaration_path = governance / "effect-evidence.json"
        self.register_path = governance / "ast-dispositions.json"
        self.write_declaration([("tests/test_alpha.py", "test_breaks_the_package")])
        corpus = astcorpus.derive(self.root)
        candidates = astscan.scan_corpus(corpus)
        self.assertEqual(len(candidates), 1, "the fixture worktree drifted")
        self.candidate = candidates[0]
        self.assertEqual(self.candidate.candidate_class, "silent_substitution")

    def write_declaration(self, functions):
        self.declaration_path.write_text(
            json.dumps(effect_declaration(functions), indent=2), encoding="utf-8"
        )

    def write_register(self, entries):
        register = register_skeleton()
        register["dispositions"] = list(entries)
        self.register_path.write_text(json.dumps(register, indent=2), encoding="utf-8")

    def validate(self):
        return astscan.validate(self.root)


class TestTheComparison(RegisterFixture):
    def test_a_disposed_candidate_set_passes_and_reports_its_counts(self):
        self.write_register(
            [entry_for(self.root, self.candidate, "exclude_with_reason")]
        )
        failures, diagnostics = self.validate()
        self.assertEqual(failures, [])
        self.assertIn("r9_candidates=1", diagnostics)
        self.assertIn("dispositions=1", diagnostics)
        self.assertIn("corpus_files=3", diagnostics)

    def test_a_candidate_without_a_disposition_fails(self):
        self.write_register([])
        failures, _diagnostics = self.validate()
        self.assertEqual([code for _id, code in failures], ["candidate_undisposed"])

    def test_a_disposition_without_a_candidate_fails(self):
        stray = dict(entry_for(self.root, self.candidate, "exclude_with_reason"))
        stray["candidate_id"] = "r9-0000000000000000"
        self.write_register(
            [entry_for(self.root, self.candidate, "exclude_with_reason"), stray]
        )
        failures, _diagnostics = self.validate()
        self.assertEqual([code for _id, code in failures], ["disposition_orphaned"])

    def test_an_edited_candidate_breaks_its_binding_in_both_directions(self):
        """Editing the anchoring node makes the old disposition orphaned and
        the new candidate undisposed — a silent carry-over is impossible."""
        self.write_register(
            [entry_for(self.root, self.candidate, "exclude_with_reason")]
        )
        target = self.root / "tests" / "test_alpha.py"
        before = target.read_text(encoding="utf-8")
        target.write_text(before.replace('"1.0.1"', '"9.9.9"'), encoding="utf-8")
        self.assertNotEqual(
            target.read_text(encoding="utf-8"), before, "the edit had no effect"
        )
        failures, _diagnostics = self.validate()
        self.assertEqual(
            sorted(code for _id, code in failures),
            [
                "candidate_undisposed",
                "category_unconfirmed:anchor_not_found",
                "disposition_orphaned",
            ],
        )

    def test_a_resolved_candidate_that_reappears_fails(self):
        self.write_register(
            [
                entry_for(
                    self.root,
                    self.candidate,
                    "mark_and_fix",
                    repair_note=LONG_NOTE,
                    resolved_by_removal=True,
                )
            ]
        )
        failures, _diagnostics = self.validate()
        self.assertEqual(
            [code for _id, code in failures], ["resolved_candidate_reappeared"]
        )

    def test_a_mark_and_fix_without_the_declaration_fails(self):
        self.write_declaration([("tests/test_alpha.py", "some_other_function")])
        self.write_register(
            [
                entry_for(
                    self.root, self.candidate, "mark_and_fix", repair_note=LONG_NOTE
                )
            ]
        )
        failures, _diagnostics = self.validate()
        self.assertEqual(
            [code for _id, code in failures], ["mark_without_declaration"]
        )

    def test_a_declared_mark_and_fix_passes(self):
        self.write_register(
            [
                entry_for(
                    self.root, self.candidate, "mark_and_fix", repair_note=LONG_NOTE
                )
            ]
        )
        failures, _diagnostics = self.validate()
        self.assertEqual(failures, [])

    def test_a_withdrawn_scan_input_is_blocked_not_an_empty_success(self):
        self.write_register(
            [entry_for(self.root, self.candidate, "exclude_with_reason")]
        )
        (self.root / "pyproject.toml").unlink()
        self.assertFalse(
            (self.root / "pyproject.toml").is_file(),
            "the scan input was not withdrawn",
        )
        failures, diagnostics = self.validate()
        self.assertEqual(failures, [("corpus", "corpus_source_missing")])
        self.assertEqual(diagnostics, [])

    def test_a_lazy_reason_is_refused_by_the_register_reader(self):
        entry = entry_for(
            self.root, self.candidate, "exclude_with_reason", reason="false positive"
        )
        self.write_register([entry])
        with self.assertRaises(astscan.RegisterError) as caught:
            astscan.load_register(self.root)
        self.assertEqual(caught.exception.code, "entry_reason_insufficient")

    def test_an_excluded_candidate_cannot_claim_removal(self):
        entry = entry_for(
            self.root, self.candidate, "exclude_with_reason", resolved_by_removal=True
        )
        self.write_register([entry])
        with self.assertRaises(astscan.RegisterError) as caught:
            astscan.load_register(self.root)
        self.assertEqual(
            caught.exception.code, "entry_resolution_contradicts_disposition"
        )


class TestTheRealRegister(unittest.TestCase):
    """This repository against its own committed register — the durable gate."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = astcorpus.derive(REPO_ROOT)
        cls.failures, cls.diagnostics = astscan.validate(REPO_ROOT, corpus=cls.corpus)

    def test_the_register_is_loadable_and_bound_to_this_block(self):
        register = astscan.load_register(REPO_ROOT)
        self.assertEqual(register["kind"], "ast_disposition_register")
        self.assertTrue(register["dispositions"])

    def test_the_sweep_ran_over_a_non_empty_corpus(self):
        """The zero-findings exception may only ever rest on this evidence."""
        self.assertGreater(self.corpus.counts["files"], 0)
        self.assertGreater(self.corpus.counts["units"], 0)
        self.assertGreater(self.corpus.counts["ast_nodes"], 0)

    def test_detected_candidates_equal_disposed_candidates(self):
        self.assertEqual(
            self.failures,
            [],
            "undisposed or orphaned candidates: " + repr(self.failures[:10]),
        )

    def test_every_disposition_still_binds_to_its_source_digest(self):
        """The recorded digest names the analysed state; a drifted file must
        have been re-decided (the fingerprint comparison enforces the
        re-decision, the digest documents the provenance)."""
        register = astscan.load_register(REPO_ROOT)
        for entry in register["dispositions"]:
            self.assertEqual(len(entry["source_digest"]), 64)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
