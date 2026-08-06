"""Rule R6 — an expectation value belongs to the commit it is claimed for.

The defect this rule comes from is not hypothetical: a guard package hash was
derived once from an uncommitted worktree state and then published twice, for
two different commits, without being derived again from either. The owner's
dry run refused it. ``--expect-hash`` exists so the owner checks against an
independently derived value; a value that is merely repeated is not one.

The sharpening test therefore builds exactly that situation — a declared value
that belongs to a different tree than the declared commit — and requires it to
fail. The counter test requires a correctly derived value to still pass, so
the rule cannot be satisfied by rejecting everything.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import expectations  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def git(repository, *arguments):
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(repository), *[str(item) for item in arguments]],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        check=True, timeout=120, shell=False,
    ).stdout.decode("utf-8", "replace").strip()


class SyntheticRepository(unittest.TestCase):
    """A throwaway repository with two commits that differ in the package.

    Nothing here touches the protected repository: the guard sources are
    copied into a fresh temporary repository and changed only there.
    """

    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="expectations-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        for relative in ("tools/guard", "tools/guardpkg"):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                REPO_ROOT / relative, destination,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        (self.root / "config" / "governance").mkdir(parents=True)
        git(self.root, "init", "--quiet", ".")
        git(self.root, "config", "user.email", "expectation@example.invalid")
        git(self.root, "config", "user.name", "expectation")
        git(self.root, "add", "-A")
        git(self.root, "commit", "--quiet", "-m", "first")
        self.first = git(self.root, "rev-parse", "HEAD")

        # A change inside the runtime package, so the digest really differs.
        rules = self.root / "tools" / "guard" / "rules.json"
        document = json.loads(rules.read_text(encoding="utf-8"))
        document["config_version"] = "9.9.9"
        rules.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "--quiet", "-m", "second")
        self.second = git(self.root, "rev-parse", "HEAD")

    def entry(self, commit, value, **overrides):
        entry = {
            "expectation_id": "EXP-TEST-001",
            "owner_action": "a synthetic owner action",
            "artifact": expectations.GUARD_RUNTIME_PACKAGE,
            "commit": commit,
            "value": value,
            "derivation": "built from the commit object",
            "published_at_commit": commit,
        }
        entry.update(overrides)
        return entry

    def write(self, entries, **overrides):
        document = {
            "schema_version": 1,
            "kind": "owner_expectation_values",
            "rule": "R6",
            "statement": "Synthetic declaration.",
            "expectations": entries,
        }
        document.update(overrides)
        (self.root / expectations.DECLARATION).write_text(
            json.dumps(document), encoding="utf-8"
        )

    def derived(self, commit):
        value, code = expectations.derive_guard_package(self.root, commit)
        self.assertIsNotNone(value, code)
        return value


class TestTheRule(SyntheticRepository):
    def test_a_value_from_another_commit_is_rejected(self):
        """Sharpening test for RC-013. This is the defect that occurred."""
        wrong = self.derived(self.first)
        self.assertNotEqual(wrong, self.derived(self.second))
        self.write([self.entry(self.second, wrong)])
        failures, _diagnostics = expectations.check(self.root)
        self.assertEqual(
            failures,
            [("EXP-TEST-001", "value_does_not_belong_to_the_declared_commit")],
        )

    def test_a_correctly_derived_value_still_passes(self):
        """Counter test for RC-013. The rule is not satisfied by refusing."""
        self.write([self.entry(self.second, self.derived(self.second))])
        failures, diagnostics = expectations.check(self.root)
        self.assertEqual(failures, [])
        self.assertTrue(diagnostics)

    def test_the_two_commits_really_differ(self):
        """Without this the sharpening test could pass on a tie."""
        self.assertNotEqual(self.derived(self.first), self.derived(self.second))

    def test_a_worktree_only_change_never_becomes_an_expectation(self):
        """The whole origin of the defect: an uncommitted state."""
        declared = self.derived(self.second)
        rules = self.root / "tools" / "guard" / "rules.json"
        document = json.loads(rules.read_text(encoding="utf-8"))
        document["config_version"] = "7.7.7"
        rules.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        # The worktree now differs, but the derivation reads the commit.
        self.write([self.entry(self.second, declared)])
        failures, _diagnostics = expectations.check(self.root)
        self.assertEqual(failures, [])


class TestNegativeControls(SyntheticRepository):
    def test_an_unknown_artifact_kind_is_rejected_not_skipped(self):
        self.write([self.entry(self.second, self.derived(self.second),
                               artifact="something_undeclared")])
        failures, _diagnostics = expectations.check(self.root)
        self.assertEqual(
            [code for _identifier, code in failures], ["artifact_kind_unknown"]
        )

    def test_a_commit_that_does_not_exist_is_rejected(self):
        self.write([self.entry("f" * 40, self.derived(self.second))])
        failures, _diagnostics = expectations.check(self.root)
        self.assertEqual(
            [code for _identifier, code in failures], ["commit_not_extractable"]
        )

    def test_an_abbreviated_commit_is_rejected(self):
        self.write([self.entry(self.second[:7], self.derived(self.second))])
        failures, _diagnostics = expectations.check(self.root)
        self.assertEqual(
            [code for _identifier, code in failures],
            ["commit_not_a_full_object_id"],
        )

    def test_a_value_that_is_not_a_digest_is_rejected(self):
        self.write([self.entry(self.second, "not-a-digest")])
        failures, _diagnostics = expectations.check(self.root)
        self.assertEqual(
            [code for _identifier, code in failures], ["value_not_a_digest"]
        )

    def test_a_declaration_without_a_stated_derivation_is_rejected(self):
        self.write([self.entry(self.second, self.derived(self.second),
                               derivation="  ")])
        failures, _diagnostics = expectations.check(self.root)
        self.assertEqual(
            [code for _identifier, code in failures], ["derivation_not_stated"]
        )

    def test_a_duplicated_expectation_id_is_rejected(self):
        value = self.derived(self.second)
        self.write([self.entry(self.second, value), self.entry(self.second, value)])
        failures, _diagnostics = expectations.check(self.root)
        self.assertEqual(
            [code for _identifier, code in failures], ["expectation_id_duplicated"]
        )

    def test_a_missing_declaration_is_a_failure_not_a_pass(self):
        failures, _diagnostics = expectations.check(self.root)
        self.assertEqual(
            [code for _identifier, code in failures], ["declaration_missing"]
        )


class TestTheRealDeclaration(unittest.TestCase):
    def test_every_declared_expectation_re_derives(self):
        failures, diagnostics = expectations.check(REPO_ROOT)
        self.assertEqual(failures, [])
        self.assertTrue(diagnostics)

    def test_the_declaration_carries_at_least_the_guard_package(self):
        document = expectations.load(REPO_ROOT)
        kinds = {entry["artifact"] for entry in document["expectations"]}
        self.assertIn(expectations.GUARD_RUNTIME_PACKAGE, kinds)

    def test_every_declared_commit_is_reachable(self):
        document = expectations.load(REPO_ROOT)
        for entry in document["expectations"]:
            with self.subTest(expectation=entry["expectation_id"]):
                kind = subprocess.run(  # noqa: S603 - fixed argv
                    ["git", "-C", str(REPO_ROOT), "cat-file", "-t",
                     entry["commit"]],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    check=False, timeout=60, shell=False,
                )
                self.assertEqual(
                    kind.stdout.decode("utf-8", "replace").strip(), "commit"
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
