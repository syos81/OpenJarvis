"""The guard trust model and the claim lint that enforces it.

The lint has three declared exclusions — the model file, the lint
implementation and this test module — because each of them must contain a
prohibited claim verbatim to do its job. The abuse tests below prove that the
exclusion is path exact and that the very same content is still detected
anywhere else.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates.runners import guard_checks  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_PATH = REPO_ROOT / "config" / "governance" / "guard-trust-model.json"
MODEL = json.loads(MODEL_PATH.read_text(encoding="utf-8"))

#: One prohibited claim, taken from the model instead of spelled out here.
FORBIDDEN = MODEL["prohibited_claims"][0]


class TestTrustModel(unittest.TestCase):
    def test_guard_is_declared_a_discipline_mechanism(self):
        self.assertIn("discipline mechanism", MODEL["purpose"].lower())

    def test_hostile_user_is_declared_out_of_scope(self):
        joined = " ".join(MODEL["not_protected_against"]).lower()
        self.assertIn("hostile actor", joined)
        self.assertIn("claude code application", joined)

    def test_application_is_an_open_trust_root(self):
        open_roots = [
            root for root in MODEL["trust_roots"] if root["closable"] is False
        ]
        self.assertTrue(open_roots)
        self.assertTrue(
            any("claude" in root["root"].lower() for root in open_roots)
        )

    def test_boundary_is_owner_authentication_not_impossibility(self):
        boundary = MODEL["owner_authentication_boundary"]
        self.assertEqual(
            boundary["value"], "requires_interactive_owner_authentication"
        )
        self.assertEqual(boundary["rejected_value"], "technically_impossible")

    def test_protocol_is_forgeable_forward(self):
        limit = MODEL["log_integrity_limit"]
        self.assertFalse(limit["truncatable_by_session"])
        self.assertFalse(limit["deletable_by_session"])
        self.assertTrue(limit["appendable_by_session"])
        self.assertTrue(limit["forgeable_forward"])
        self.assertFalse(limit["cryptographic_provenance"])

    def test_protocol_is_not_a_sole_proof(self):
        use = MODEL["evidence_use_limit"]
        self.assertFalse(use["protocol_is_sole_proof"])
        self.assertFalse(use["single_entry_proves_origin"])
        self.assertTrue(use["supporting_signal_only"])
        self.assertFalse(use["forward_appended_entries_may_override_history"])
        self.assertTrue(use["required_additional_support"])


class TestClaimLint(unittest.TestCase):
    def _sandbox(self, *, exclusions=()):
        """Build a throwaway root with one document and a matching model."""
        tmp = tempfile.TemporaryDirectory(prefix="claim-lint-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "docs" / "governance").mkdir(parents=True)
        (root / "docs" / "governance" / "probe.md").write_text(
            "Der Guard ist " + FORBIDDEN + ".\n", encoding="utf-8"
        )
        model = {
            "prohibited_claims": MODEL["prohibited_claims"],
            "claim_lint": {
                "scanned_paths": ["docs/governance"],
                "declared_exclusions": [
                    {"path": path, "reason": "test", "abuse_test": "x"}
                    for path in exclusions
                ],
            },
        }
        return root, model

    def test_same_content_is_detected_outside_the_implementation(self):
        """Abuse test: the excluded content is caught anywhere else."""
        root, model = self._sandbox()
        hits = guard_checks.find_claim_violations(root, model)
        self.assertTrue(hits)
        self.assertEqual(hits[0][0], "docs/governance/probe.md")

    def test_excluded_path_is_not_a_blanket_exemption(self):
        """Abuse test: an exclusion covers exactly one path, nothing more."""
        root, model = self._sandbox(
            exclusions=("docs/governance/probe.md",)
        )
        self.assertEqual(guard_checks.find_claim_violations(root, model), [])

        # A sibling file with the same content is still detected: the
        # exclusion did not disable the rule, only one exact path.
        (root / "docs" / "governance" / "sibling.md").write_text(
            "Der Guard ist " + FORBIDDEN + ".\n", encoding="utf-8"
        )
        hits = guard_checks.find_claim_violations(root, model)
        self.assertEqual([path for path, _ in hits],
                         ["docs/governance/sibling.md"])

    def test_repository_is_free_of_prohibited_claims(self):
        self.assertEqual(guard_checks.find_claim_violations(REPO_ROOT, MODEL), [])

    def test_every_exclusion_declares_a_reason_and_an_abuse_test(self):
        for entry in MODEL["claim_lint"]["declared_exclusions"]:
            with self.subTest(path=entry["path"]):
                self.assertTrue(entry["reason"].strip())
                self.assertTrue(entry["abuse_test"].strip())
                self.assertTrue((REPO_ROOT / entry["path"]).exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
