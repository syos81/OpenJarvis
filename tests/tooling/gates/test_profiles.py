"""The acceptance profile derivation and the lock that follows from it.

The point of these tests is not that the result is ``not_justified``. It is
that the result is *computed*. A derivation that always returns the same
value carries nothing, no matter how true that value happens to be, so the
first test builds a state in which the derivation must return the other
answer.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import profiles  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def manifest(block_id, *, required, runner):
    """A minimal block manifest, only what the signature is computed from."""
    return {
        "block_id": block_id,
        "phase_definitions": {
            "offline-final": {"applicable": True, "required": required},
            "preflight": {"applicable": True, "required": True},
        },
        "checks": [
            {"phase": "preflight", "runner": {"name": "preflight_checks.py"}},
            {"phase": "offline-final", "runner": {"name": runner}},
        ],
    }


class SyntheticRoot(unittest.TestCase):
    """A worktree shaped root built entirely from synthetic declarations."""

    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="profiles-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / profiles.BLOCKS_DIR).mkdir(parents=True)
        (self.root / "config" / "governance").mkdir(parents=True, exist_ok=True)
        self.write_order(
            [
                {"canonical_name": "Alpha", "acceptance_profile": "profile_one"},
                {"canonical_name": "Beta", "acceptance_profile": "profile_two"},
            ]
        )

    def write_order(self, elements):
        (self.root / profiles.DELIVERY_ORDER).write_text(
            json.dumps({"schema_version": 1, "elements": elements}),
            encoding="utf-8",
        )

    def write_manifest(self, document):
        target = self.root / profiles.BLOCKS_DIR / f"{document['block_id']}.json"
        target.write_text(json.dumps(document), encoding="utf-8")

    def write_attribution(self, mapping):
        (self.root / profiles.ATTRIBUTION).write_text(
            json.dumps({"schema_version": 1, "attribution": mapping}),
            encoding="utf-8",
        )


class TestTheDerivationIsComputed(SyntheticRoot):
    def test_a_profile_covering_differing_obligations_is_justified(self):
        """The falsification. A constant would fail exactly here."""
        self.write_manifest(manifest("alpha", required=True, runner="a.py"))
        self.write_manifest(manifest("beta", required=False, runner="b.py"))
        self.write_attribution({"alpha": "profile_one", "beta": "profile_one"})

        outcome = profiles.derive(self.root)
        self.assertEqual(outcome["result"], profiles.JUSTIFIED)
        collisions = outcome["observed"]["profiles_covering_differing_signatures"]
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0]["acceptance_profile"], "profile_one")
        self.assertEqual(collisions[0]["blocks"], ["alpha", "beta"])

    def test_a_profile_covering_identical_obligations_is_not_justified(self):
        self.write_manifest(manifest("alpha", required=True, runner="a.py"))
        self.write_manifest(manifest("beta", required=True, runner="a.py"))
        self.write_attribution({"alpha": "profile_one", "beta": "profile_one"})

        outcome = profiles.derive(self.root)
        self.assertEqual(outcome["result"], profiles.NOT_JUSTIFIED)
        self.assertEqual(
            outcome["observed"]["profiles_covering_differing_signatures"], []
        )
        self.assertEqual(outcome["observed"]["comparable_units"], ["alpha", "beta"])

    def test_two_profiles_never_collide_with_each_other(self):
        self.write_manifest(manifest("alpha", required=True, runner="a.py"))
        self.write_manifest(manifest("beta", required=False, runner="b.py"))
        self.write_attribution({"alpha": "profile_one", "beta": "profile_two"})
        self.assertEqual(
            profiles.derive(self.root)["result"], profiles.NOT_JUSTIFIED
        )

    def test_an_attribution_to_an_unknown_block_compares_nothing(self):
        self.write_manifest(manifest("alpha", required=True, runner="a.py"))
        self.write_attribution(
            {"alpha": "profile_one", "does-not-exist": "profile_one"}
        )
        outcome = profiles.derive(self.root)
        self.assertEqual(outcome["observed"]["comparable_units"], ["alpha"])
        self.assertEqual(outcome["result"], profiles.NOT_JUSTIFIED)

    def test_without_an_attribution_the_domain_is_empty(self):
        self.write_manifest(manifest("alpha", required=True, runner="a.py"))
        self.write_manifest(manifest("beta", required=False, runner="b.py"))
        outcome = profiles.derive(self.root)
        self.assertEqual(outcome["observed"]["comparable_units"], [])
        self.assertFalse(outcome["inputs"]["attribution_present"])
        self.assertIn("empty comparable domain", outcome["reason"])

    def test_the_signature_really_reflects_the_manifest(self):
        first = profiles.obligation_signature(
            manifest("alpha", required=True, runner="a.py")
        )
        same = profiles.obligation_signature(
            manifest("other", required=True, runner="a.py")
        )
        by_requirement = profiles.obligation_signature(
            manifest("alpha", required=False, runner="a.py")
        )
        by_runner = profiles.obligation_signature(
            manifest("alpha", required=True, runner="b.py")
        )
        self.assertEqual(first, same)
        self.assertNotEqual(first, by_requirement)
        self.assertNotEqual(first, by_runner)


class TestTheNormativeState(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.outcome = profiles.derive(REPO_ROOT)
        self.lock = profiles.load_lock(REPO_ROOT)

    def test_the_current_result_is_not_justified(self):
        self.assertEqual(self.outcome["result"], profiles.NOT_JUSTIFIED)

    def test_no_block_is_attributed_to_an_acceptance_profile_today(self):
        self.assertEqual(self.outcome["observed"]["comparable_units"], [])
        self.assertFalse(self.outcome["inputs"]["attribution_present"])

    def test_every_block_manifest_enters_the_derivation(self):
        declared = sorted(
            path.stem for path in
            (REPO_ROOT / profiles.BLOCKS_DIR).glob("*.json")
        )
        self.assertEqual(
            len(self.outcome["inputs"]["block_manifests"]), len(declared)
        )

    def test_the_existing_acceptance_profiles_are_reported_unchanged(self):
        self.assertEqual(
            sorted(self.outcome["inputs"]["existing_acceptance_profiles"]),
            sorted(self.lock["existing_acceptance_profiles_are_untouched"]["values"]),
        )

    def test_the_consequence_names_no_profile_artifact(self):
        self.assertIn("No profile artifact", self.outcome["consequence"])


class TestTheLock(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.lock = profiles.load_lock(REPO_ROOT)

    def test_the_lock_may_not_claim_a_result_the_derivation_did_not_produce(self):
        self.assertTrue(
            profiles.lock_is_consistent_with(profiles.derive(REPO_ROOT), self.lock)
        )

    def test_an_inconsistent_lock_is_detected(self):
        forged = dict(self.lock)
        forged["derivation_result"] = profiles.JUSTIFIED
        self.assertFalse(
            profiles.lock_is_consistent_with(profiles.derive(REPO_ROOT), forged)
        )

    def test_no_locked_label_is_used_anywhere_in_scope(self):
        self.assertEqual(profiles.lock_violations(REPO_ROOT), [])

    def test_the_lock_has_teeth(self):
        root = Path(tempfile.mkdtemp(prefix="profile-lock-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "docs").mkdir(parents=True)
        (root / "config" / "governance").mkdir(parents=True)
        shutil.copyfile(
            REPO_ROOT / profiles.LOCK, root / profiles.LOCK
        )
        (root / "docs" / "example.md").write_text(
            "Dieser Block laeuft unter Abnahmeprofil B.\n", encoding="utf-8"
        )
        violations = profiles.lock_violations(root)
        self.assertEqual(violations, [("docs/example.md", "Abnahmeprofil B")])

    def test_the_declaration_itself_is_exempt(self):
        """It has to name the labels in order to forbid them."""
        self.assertIn(profiles.LOCK, self.lock["exempt_paths"])
        for label in self.lock["locked_labels"]:
            self.assertIn(
                label, (REPO_ROOT / profiles.LOCK).read_text(encoding="utf-8")
            )
        self.assertEqual(profiles.lock_violations(REPO_ROOT), [])

    def test_the_preserved_k1_check_is_named_and_still_exists(self):
        preserved = self.lock["preserved_check"]
        self.assertTrue((REPO_ROOT / preserved["runner"]).is_file())
        source = (REPO_ROOT / preserved["runner"]).read_text(encoding="utf-8")
        self.assertIn("mode_classification_schemes", source)

    def test_the_lock_does_not_rewrite_historical_evidence(self):
        self.assertFalse(self.lock["historical_evidence"]["rewritten"])

    def test_the_really_existing_profiles_stay_untouched(self):
        untouched = self.lock["existing_acceptance_profiles_are_untouched"]
        self.assertTrue(untouched["value"])
        order = json.loads(
            (REPO_ROOT / profiles.DELIVERY_ORDER).read_text(encoding="utf-8")
        )
        declared = {
            element.get("acceptance_profile")
            for element in order["elements"]
            if element.get("acceptance_profile")
        }
        self.assertEqual(declared, set(untouched["values"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
