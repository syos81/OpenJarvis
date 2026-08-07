"""The pre-declared sample, its blindness and its consumption (block B0f).

Everything the sampling machinery promises is tested here in both
directions: the draw is a pure function of commit and register (identical
twice, visibly different under a manipulated population), the code uses no
irreproducible entropy source, the blind dataset rejects smuggled reasons
and categories, evaluations cannot change after unblinding, a withdrawn
review input blocks, an unevaluated sample never passes, and a rejected
exclusion demands the category-wide re-examination instead of a single fix.

Rule R9 applies to the register manipulation below: the manipulation is
established before the second draw is compared.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.gates import astscan, b0fsample  # noqa: E402
from tools.gates.runners import b0f_checks  # noqa: E402
from tests.tooling.gates.test_ast_corpus import MiniWorktree  # noqa: E402
from tests.tooling.gates.test_ast_dispositions import (  # noqa: E402
    effect_declaration,
    entry_for,
    register_skeleton,
)


class GitFixture(MiniWorktree):
    """The mini worktree, committed, with a schema-2 register."""

    def setUp(self):
        super().setUp()
        governance = self.root / "config" / "governance"
        governance.mkdir(parents=True, exist_ok=True)
        (governance / "effect-evidence.json").write_text(
            json.dumps(effect_declaration([])), encoding="utf-8"
        )
        import shutil

        shutil.copyfile(
            REPO_ROOT / "config" / "governance" / "b0f-sample-plan.json",
            governance / "b0f-sample-plan.json",
        )
        from tools.gates import astcorpus

        corpus = astcorpus.derive(self.root)
        candidates = astscan.scan_corpus(corpus)
        self.assertEqual(len(candidates), 1, "the fixture worktree drifted")
        self.candidate = candidates[0]
        register = register_skeleton()
        register["dispositions"] = [
            entry_for(self.root, self.candidate, "exclude_with_reason")
        ]
        (governance / "ast-dispositions.json").write_text(
            json.dumps(register), encoding="utf-8"
        )
        self.git("init", "--quiet")
        self.git("add", "-A")
        self.git(
            "-c", "user.email=fixture@example.invalid", "-c", "user.name=Fixture",
            "commit", "--quiet", "-m", "fixture",
        )
        self.commit = self.git("rev-parse", "HEAD")

    def git(self, *arguments):
        return subprocess.run(
            ["git", *arguments], cwd=self.root, capture_output=True,
            text=True, check=True,
        ).stdout.strip()


class TestTheDrawIsBound(GitFixture):
    def test_same_commit_and_register_draw_identically(self):
        first = b0fsample.draw(self.root, self.commit)
        second = b0fsample.draw(self.root, self.commit)
        self.assertEqual(first, second)

    def test_a_manipulated_population_changes_seed_and_draw_visibly(self):
        seed_before = b0fsample.derive_seed(self.root, self.commit)
        register_path = (
            self.root / "config" / "governance" / "ast-dispositions.json"
        )
        before = register_path.read_text(encoding="utf-8")
        register = json.loads(before)
        clone = dict(register["dispositions"][0])
        clone["candidate_id"] = "r9-00000000000000ff"
        register["dispositions"].append(clone)
        register_path.write_text(json.dumps(register), encoding="utf-8")
        self.assertNotEqual(
            register_path.read_text(encoding="utf-8"), before,
            "the register manipulation had no effect",
        )
        self.git("add", "-A")
        self.git(
            "-c", "user.email=fixture@example.invalid", "-c", "user.name=Fixture",
            "commit", "--quiet", "-m", "manipulated",
        )
        manipulated = self.git("rev-parse", "HEAD")
        self.assertNotEqual(
            b0fsample.derive_seed(self.root, manipulated), seed_before
        )

    def test_an_empty_population_blocks_rather_than_passing(self):
        register_path = (
            self.root / "config" / "governance" / "ast-dispositions.json"
        )
        register = json.loads(register_path.read_text(encoding="utf-8"))
        register["dispositions"] = []
        register_path.write_text(json.dumps(register), encoding="utf-8")
        with self.assertRaises(b0fsample.SampleError) as caught:
            b0fsample.draw(self.root, self.commit)
        self.assertEqual(caught.exception.code, "population_empty")

    def test_no_irreproducible_entropy_source_is_used(self):
        for relative in ("tools/gates/b0fsample.py", "tools/gates/runners/b0f_checks.py"):
            tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
            names = {
                (getattr(n, "id", "") or getattr(n, "attr", ""))
                for n in ast.walk(tree)
            }
            for forbidden in ("random", "urandom", "getpid", "time_ns", "now"):
                self.assertNotIn(forbidden, names, f"{relative} uses {forbidden}")


class TestBlindness(GitFixture):
    def _records(self):
        seed, drawn = b0fsample.draw(self.root, self.commit)
        return seed, b0fsample.build_blind(self.root, self.commit, seed, drawn)

    def test_the_blind_dataset_is_reproducible_and_clean(self):
        _seed, records = self._records()
        self.assertTrue(records)
        again = self._records()[1]
        self.assertEqual(records, again)
        self.assertEqual(b0fsample.validate_blind(self.root, records), [])

    def test_a_smuggled_original_reason_falls(self):
        _seed, records = self._records()
        register = json.loads(
            (self.root / "config" / "governance" / "ast-dispositions.json").read_text()
        )
        records[0]["task"] = register["dispositions"][0]["reason"]
        failures = b0fsample.validate_blind(self.root, records)
        self.assertIn("blind_reason_leaked", [code for _id, code in failures])

    def test_a_smuggled_category_falls(self):
        _seed, records = self._records()
        records[0]["task"] += " r9_after_state_observed"
        failures = b0fsample.validate_blind(self.root, records)
        self.assertIn("blind_category_leaked", [code for _id, code in failures])

    def test_a_field_outside_the_allowlist_falls(self):
        _seed, records = self._records()
        records[0]["b0e_reason"] = "anything"
        failures = b0fsample.validate_blind(self.root, records)
        self.assertIn("blind_field_set", [code for _id, code in failures])


class TestReviewConsumption(GitFixture):
    def _reviews(self, verdict="confirm_exclusion"):
        seed, drawn = b0fsample.draw(self.root, self.commit)
        return [
            {
                "review_id": b0fsample.review_id(seed, entry["candidate_id"]),
                "verdict": verdict,
                "justification": "fixture technical justification",
            }
            for rule in drawn
            for entry in drawn[rule]
        ]

    def _comparison(self, reviews):
        return {
            "commit": self.commit,
            "reviews_sha256": hashlib.sha256(
                json.dumps(reviews, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    def test_a_fully_evaluated_clean_sample_may_pass(self):
        reviews = self._reviews()
        failures, summary = b0fsample.consume_reviews(
            self.root, self.commit, reviews=reviews,
            comparison=self._comparison(reviews),
        )
        self.assertEqual(failures, [])
        self.assertGreater(summary["drawn"], 0)
        self.assertEqual(summary["drawn"], summary["evaluated"])
        self.assertEqual(summary["reject_exclusion"], 0)

    def test_zero_evaluations_never_pass(self):
        failures, summary = b0fsample.consume_reviews(
            self.root, self.commit, reviews=[], comparison=None
        )
        codes = [code for _id, code in failures]
        self.assertIn("review_missing", codes)
        self.assertIn("review_consumption_incomplete", codes)
        self.assertGreater(summary["drawn"], 0)
        self.assertEqual(summary["evaluated"], 0)

    def test_a_changed_evaluation_after_unblinding_falls(self):
        reviews = self._reviews()
        comparison = self._comparison(reviews)
        reviews[0]["verdict"] = "reject_exclusion"
        self.assertNotEqual(
            comparison["reviews_sha256"],
            hashlib.sha256(
                json.dumps(reviews, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "the tampering had no effect",
        )
        failures, _summary = b0fsample.consume_reviews(
            self.root, self.commit, reviews=reviews, comparison=comparison
        )
        self.assertIn(
            "reviews_changed_after_unblinding", [code for _id, code in failures]
        )

    def test_a_duplicated_review_id_falls(self):
        reviews = self._reviews()
        reviews.append(dict(reviews[0]))
        failures, _summary = b0fsample.consume_reviews(
            self.root, self.commit, reviews=reviews,
            comparison=self._comparison(reviews),
        )
        self.assertIn("review_duplicated", [code for _id, code in failures])


class TestTheBlindGate(GitFixture):
    """The runner mode: withdrawal blocks; a reject demands the category."""

    def setUp(self):
        super().setUp()
        self._previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self._previous_cwd)
        self.report = self.root / "gate-report.json"
        from unittest import mock

        patcher = mock.patch.dict(os.environ, {"GATE_REPORT": str(self.report)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.history = self.root / "config" / "gates" / "history"
        self.history.mkdir(parents=True, exist_ok=True)

    def _write_artifacts(self, verdict="confirm_exclusion"):
        seed, drawn = b0fsample.draw(self.root, self.commit)
        records = b0fsample.build_blind(self.root, self.commit, seed, drawn)
        (self.history / "b0f-blind-dataset.json").write_text(
            json.dumps({"schema_version": 1, "kind": "b0f_blind_dataset",
                        "block_id": "fixture-block", "commit": self.commit,
                        "records": records}),
            encoding="utf-8",
        )
        reviews = [
            {
                "review_id": record["review_id"],
                "verdict": verdict,
                "justification": "fixture technical justification",
            }
            for record in records
        ]
        (self.history / "b0f-blind-reviews.json").write_text(
            json.dumps({"schema_version": 1, "kind": "b0f_blind_reviews",
                        "block_id": "fixture-block", "records": reviews}),
            encoding="utf-8",
        )
        (self.history / "b0f-unblinding.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "b0f_unblinding",
                    "block_id": "fixture-block",
                    "commit": self.commit,
                    "reviews_sha256": hashlib.sha256(
                        json.dumps(reviews, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                    "comparison": [],
                }
            ),
            encoding="utf-8",
        )

    def _codes(self):
        payload = json.loads(self.report.read_text(encoding="utf-8"))
        return payload["outcome"], sorted(
            failure["code"] for failure in payload["failures"]
        )

    def test_a_clean_fully_evaluated_review_passes(self):
        self._write_artifacts()
        exit_code = b0f_checks.mode_blind(None)
        outcome, codes = self._codes()
        self.assertEqual((exit_code, outcome, codes), (0, "passed", []))

    def test_a_withdrawn_review_input_blocks(self):
        self._write_artifacts()
        target = self.history / "b0f-blind-reviews.json"
        target.unlink()
        self.assertFalse(target.is_file(), "the review input was not withdrawn")
        exit_code = b0f_checks.mode_blind(None)
        outcome, _codes = self._codes()
        self.assertEqual((exit_code, outcome), (3, "blocked"))

    def test_a_reject_without_category_rereview_falls(self):
        self._write_artifacts(verdict="reject_exclusion")
        b0f_checks.mode_blind(None)
        _outcome, codes = self._codes()
        self.assertIn("category_rereview_missing", codes)

    def test_a_partial_rereview_is_not_a_category_rereview(self):
        self._write_artifacts(verdict="reject_exclusion")
        (self.history / "b0f-category-rereview.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "b0f_category_rereview",
                    "block_id": "fixture-block",
                    "affected_categories": ["r9_after_state_observed"],
                    "candidates": [],
                }
            ),
            encoding="utf-8",
        )
        b0f_checks.mode_blind(None)
        _outcome, codes = self._codes()
        self.assertIn("category_rereview_incomplete", codes)

    def test_a_bogus_category_set_cannot_discharge_the_duty(self):
        """RC-029 sharpening: the affected set is derived from the rejected
        candidates, never trusted — a re-review naming an unrelated or
        unknown category with an empty coverage list discharges nothing."""
        self._write_artifacts(verdict="reject_exclusion")
        (self.history / "b0f-category-rereview.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "b0f_category_rereview",
                    "block_id": "fixture-block",
                    "affected_categories": ["r10_no_such_category"],
                    "candidates": [],
                }
            ),
            encoding="utf-8",
        )
        b0f_checks.mode_blind(None)
        _outcome, codes = self._codes()
        self.assertIn("affected_category_unknown", codes)
        self.assertIn("rejected_category_not_covered", codes)
        self.assertIn("category_rereview_vacuous", codes)

    def test_a_complete_category_rereview_satisfies_the_consequence(self):
        self._write_artifacts(verdict="reject_exclusion")
        register = json.loads(
            (self.root / "config" / "governance" / "ast-dispositions.json").read_text()
        )
        candidates = [
            {"candidate_id": entry["candidate_id"], "outcome": "reconfirmed"}
            for entry in register["dispositions"]
            if entry["disposition"] == "exclude_with_reason"
        ]
        (self.history / "b0f-category-rereview.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "b0f_category_rereview",
                    "block_id": "fixture-block",
                    "affected_categories": ["r9_after_state_observed"],
                    "candidates": candidates,
                }
            ),
            encoding="utf-8",
        )
        b0f_checks.mode_blind(None)
        _outcome, codes = self._codes()
        self.assertNotIn("category_rereview_missing", codes)
        self.assertNotIn("category_rereview_incomplete", codes)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
