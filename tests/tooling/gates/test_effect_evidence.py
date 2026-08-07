"""Rule R9, and whether its enforcement has teeth.

The declaration alone would be a list of good intentions. What matters is that
the check fails when an effect assertion disappears, when it moves below the
expectation, or when the declared function is gone — and that it does not fail
for a test that simply prepares its fixtures.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.gates import effectevidence  # noqa: E402

EVIDENCED = '''
import unittest


class T(unittest.TestCase):
    def test_case(self):
        before = read()
        mutate()
        self.assertNotEqual(read(), before, "mutation had no effect")
        self.assertEqual(guard(), "deny")
'''

MOVED_BELOW = '''
import unittest


class T(unittest.TestCase):
    def test_case(self):
        before = read()
        mutate()
        self.assertEqual(guard(), "deny")
        self.assertNotEqual(read(), before, "mutation had no effect")
'''

REMOVED = '''
import unittest


class T(unittest.TestCase):
    def test_case(self):
        before = read()
        mutate()
        self.assertEqual(guard(), "deny")
'''


class TestDeclaration(unittest.TestCase):
    def test_the_real_declaration_loads(self):
        document = effectevidence.load(REPO_ROOT)
        self.assertEqual(document["rule"], "R9")
        self.assertTrue(document["examined"])

    def test_the_real_declaration_holds(self):
        failures, diagnostics = effectevidence.check(REPO_ROOT)
        self.assertEqual(failures, [])
        self.assertTrue(diagnostics)

    def test_the_deferral_is_reported_on_every_run(self):
        """The scope is limited, and the report says so rather than implying coverage."""
        _failures, diagnostics = effectevidence.check(REPO_ROOT)
        self.assertIn("corpus_sweep=deferred_to_a_separate_step", diagnostics)

    def test_the_scope_states_what_is_not_claimed(self):
        scope = effectevidence.load(REPO_ROOT)["scope"]
        self.assertTrue(scope["deferred"].strip())
        self.assertTrue(scope["not_claimed"].strip())

    def test_an_effect_assertion_that_is_not_an_assertion_is_rejected(self):
        document = effectevidence.load(REPO_ROOT)
        document["examined"][0]["effect_assertion"] = "prepare"
        with tempfile.TemporaryDirectory() as scratch:
            root = self._materialise(scratch, document)
            with self.assertRaises(effectevidence.EffectEvidenceError) as caught:
                effectevidence.load(root)
        self.assertEqual(
            caught.exception.code, "effect_assertion_is_not_an_assertion"
        )

    def _materialise(self, scratch, document):
        import json

        root = Path(scratch)
        target = root / effectevidence.DECLARATION
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return root


class TestTheCheckHasTeeth(unittest.TestCase):
    """The three ways R9 is really violated, each of which still passes CI."""

    def _verify(self, source):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            (root / "t.py").write_text(source, encoding="utf-8")
            return effectevidence.verify(
                root,
                {
                    "file": "t.py",
                    "function": "test_case",
                    "effect_assertion": "assertNotEqual",
                },
            )

    def test_the_evidenced_form_passes(self):
        self.assertEqual(self._verify(EVIDENCED), "")

    def test_an_effect_assertion_below_the_expectation_fails(self):
        """The subtle case: it is still there, and it no longer protects anything."""
        code = self._verify(MOVED_BELOW)
        self.assertEqual(code, "first_assertion_is_assertEqual_not_assertNotEqual")

    def test_a_removed_effect_assertion_fails(self):
        code = self._verify(REMOVED)
        self.assertEqual(code, "first_assertion_is_assertEqual_not_assertNotEqual")

    def test_a_missing_function_fails_rather_than_being_skipped(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            (root / "t.py").write_text("x = 1\n", encoding="utf-8")
            code = effectevidence.verify(
                root,
                {"file": "t.py", "function": "test_case", "effect_assertion": "assertNotEqual"},
            )
        self.assertEqual(code, "declared_function_absent")

    def test_a_missing_file_fails_rather_than_being_skipped(self):
        with tempfile.TemporaryDirectory() as scratch:
            code = effectevidence.verify(
                Path(scratch),
                {"file": "t.py", "function": "test_case", "effect_assertion": "assertNotEqual"},
            )
        self.assertEqual(code, "declared_file_absent")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
