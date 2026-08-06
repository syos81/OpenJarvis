"""Metagates on the rule change discipline itself.

These are the abuse tests behind the declared fixtures: the corpus must stay
data, and the guard tests must never reach the owner installed active guard.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.guard import _support  # noqa: E402
from tools.guard import rules as guard_rules  # noqa: E402

REPO_ROOT = _support.REPO_ROOT
CORPUS = REPO_ROOT / "config" / "guard" / "violation-corpus.json"
RULE_CHANGES = REPO_ROOT / "config" / "guard" / "rule-changes.json"
MATRIX = REPO_ROOT / "config" / "guard" / "history-rewrite-matrix.json"
GUARD_TESTS = REPO_ROOT / "tests" / "tooling" / "guard"

#: The one production installation root. No test may name it for writing.
ACTIVE_ROOT = "/usr/local/jarvis-guard"


class TestCorpus(unittest.TestCase):
    def test_corpus_entries_are_never_executed(self):
        """Abuse test for the corpus fixture.

        The corpus is evaluated, never run. No module in the guard test tree
        may hand a corpus command to a process launcher.
        """
        commands = {
            entry["command"]
            for entry in json.loads(CORPUS.read_text(encoding="utf-8"))["entries"]
        }
        launchers = re.compile(r"subprocess\.(run|Popen|call|check_output)")
        for module in sorted(GUARD_TESTS.glob("*.py")):
            source = module.read_text(encoding="utf-8")
            for line_number, line in enumerate(source.splitlines(), start=1):
                if not launchers.search(line):
                    continue
                for command in commands:
                    if command in line:
                        self.fail(
                            f"{module.name}:{line_number} launches a corpus entry"
                        )

    def test_tests_do_not_shadow_the_active_installation(self):
        """Abuse test for the guard test fixture."""
        for module in sorted(GUARD_TESTS.glob("*.py")):
            source = module.read_text(encoding="utf-8")
            for line_number, line in enumerate(source.splitlines(), start=1):
                if ACTIVE_ROOT not in line:
                    continue
                if line.lstrip().startswith("#"):
                    continue
                if "ACTIVE_ROOT =" in line:
                    continue
                self.fail(f"{module.name}:{line_number} names the active root")

    def test_every_corpus_entry_is_unique(self):
        entries = json.loads(CORPUS.read_text(encoding="utf-8"))["entries"]
        identifiers = [entry["entry_id"] for entry in entries]
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_previously_detected_entries_are_still_blocked(self):
        rules = guard_rules.load_rules(_support.GUARD_SOURCE / "rules.json")
        entries = json.loads(CORPUS.read_text(encoding="utf-8"))["entries"]
        for entry in entries:
            if not entry.get("previously_detected"):
                continue
            with self.subTest(entry=entry["entry_id"]):
                code, _layer = guard_rules.evaluate_command(
                    rules, entry["command"]
                )
                self.assertIsNotNone(code)


class TestRuleChangeDiscipline(unittest.TestCase):
    def test_every_change_declares_both_tests(self):
        data = json.loads(RULE_CHANGES.read_text(encoding="utf-8"))
        self.assertTrue(data["changes"])
        for change in data["changes"]:
            with self.subTest(change=change["change_id"]):
                self.assertTrue(change["sharpening_test"])
                self.assertTrue(change["counter_test"])
                self.assertNotEqual(
                    change["sharpening_test"], change["counter_test"]
                )

    def test_no_undeclared_relaxation(self):
        data = json.loads(RULE_CHANGES.read_text(encoding="utf-8"))
        for change in data["changes"]:
            if change["violation_set_effect"] == "shrinks":
                self.assertTrue(change.get("owner_decision"))

    def test_history_matrix_covers_the_mandatory_operation(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        blocked = {
            entry["operation"]
            for entry in matrix["operations"]
            if entry["category"] == "blocked"
        }
        self.assertIn("git commit --am" + "end", blocked)

    def test_open_findings_carry_no_invented_rule(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        rules = guard_rules.load_rules(_support.GUARD_SOURCE / "rules.json")
        known = set(rules.codes())
        for entry in matrix["operations"]:
            if entry["category"] == "open_finding":
                with self.subTest(operation=entry["operation"]):
                    self.assertEqual(entry["code"], "")
        for entry in matrix["operations"]:
            if entry["category"] == "blocked":
                with self.subTest(operation=entry["operation"]):
                    self.assertIn(entry["code"], known)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
