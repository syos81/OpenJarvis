"""Rules R7 and R8, and the deference this block found to be incomplete.

R7 — a normative, decision, version or integrity relevant field must be bound
to its subject or checked against it. If it is neither it is removed rather
than maintained, because a statement that checks nothing and is checked by
nothing is worse than none: it feigns reliability.

R8 — widen, migrate, narrow. A format change to a configuration the active
guard loads happens in three steps, and every intermediate state is valid
whichever file is written first.

The deference finding — the repository side layer declares itself non
authoritative and abstains whenever the owner installed guard is active, but
it used to read its own rule configuration while being imported. An unusable
configuration therefore made it block every request before it could abstain.
"""

from __future__ import annotations

import ast
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import hookguard  # noqa: E402
from tools.guard import rules as guard_rules  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_JSON = REPO_ROOT / "tools" / "guard" / "rules.json"
RULES_PY = REPO_ROOT / "tools" / "guard" / "rules.py"


def write_document(overrides):
    directory = Path(tempfile.mkdtemp(prefix="field-binding-"))
    document = json.loads(RULES_JSON.read_text(encoding="utf-8"))
    document.update(overrides)
    target = directory / "rules.json"
    target.write_text(json.dumps(document), encoding="utf-8")
    return directory, target


class TestConfigVersionIsBound(unittest.TestCase):
    """R7 applied to config_version. Binding, not maintenance."""

    def addCleanupDirectory(self, directory):
        self.addCleanup(shutil.rmtree, directory, True)

    def test_the_declared_version_is_the_format_version(self):
        """Counter test for RC-014: the consistent state still loads."""
        rules = guard_rules.load_rules(str(RULES_JSON))
        self.assertEqual(
            rules.raw["config_version"], guard_rules.CONFIG_FORMAT_VERSION
        )

    def test_a_version_that_does_not_name_the_format_is_rejected(self):
        """Sharpening test for RC-014."""
        directory, target = write_document({"config_version": "1.0.0"})
        self.addCleanupDirectory(directory)
        with self.assertRaises(guard_rules.ConfigError) as caught:
            guard_rules.load_rules(str(target))
        self.assertIn("rules_config_version_mismatch", str(caught.exception))

    def test_a_format_change_without_a_version_change_fails(self):
        """The defect the rule exists for, reproduced directly.

        The signature is computed from the loader's own field sets. Adding a
        field without moving the version makes the loader refuse to run.
        """
        frozen = guard_rules.CONFIG_FORMAT_SIGNATURE
        widened = guard_rules.format_signature(
            optional=guard_rules._OPTIONAL_CONFIG_FIELDS + ("a_new_field",)
        )
        self.assertNotEqual(widened, frozen)

    def test_the_signature_really_covers_both_field_sets(self):
        base = guard_rules.format_signature()
        self.assertNotEqual(
            base,
            guard_rules.format_signature(
                required=guard_rules._REQUIRED_CONFIG_FIELDS + ("another",)
            ),
        )
        self.assertNotEqual(
            base,
            guard_rules.format_signature(
                optional=guard_rules._OPTIONAL_CONFIG_FIELDS + ("another",)
            ),
        )

    def test_the_binding_would_have_caught_the_historical_miss(self):
        """Retroactive evidence: this is why binding carries over removal.

        Between the commit before B0c and the commit that added
        ``fixture_targets`` the format changed while the declared version did
        not. The signature differs across exactly that pair.
        """
        def field_sets(commit):
            source = subprocess.run(  # noqa: S603 - fixed argv
                ["git", "-C", str(REPO_ROOT), "show",
                 f"{commit}:tools/guard/rules.py"],
                stdout=subprocess.PIPE, check=True, timeout=60, shell=False,
            ).stdout.decode()
            required, optional = (), ()
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id == "_REQUIRED_CONFIG_FIELDS":
                        required = tuple(e.value for e in node.value.elts)
                    elif target.id == "_OPTIONAL_CONFIG_FIELDS":
                        optional = tuple(e.value for e in node.value.elts)
            return required, optional

        def declared_version(commit):
            raw = subprocess.run(  # noqa: S603 - fixed argv
                ["git", "-C", str(REPO_ROOT), "show",
                 f"{commit}:tools/guard/rules.json"],
                stdout=subprocess.PIPE, check=True, timeout=60, shell=False,
            ).stdout
            return json.loads(raw)["config_version"]

        before = "06b7d7e"
        after = "6feb7ce"
        self.assertNotEqual(
            guard_rules.format_signature(*field_sets(before)),
            guard_rules.format_signature(*field_sets(after)),
        )
        self.assertEqual(declared_version(before), declared_version(after))


class TestR8Migration(unittest.TestCase):
    """Widen, migrate, narrow — every intermediate state valid."""

    def test_the_reader_currently_accepts_exactly_one_form(self):
        """Outside a migration the accepted set is not widened."""
        self.assertEqual(
            guard_rules.ACCEPTED_CONFIG_VERSIONS,
            (guard_rules.CONFIG_FORMAT_VERSION,),
        )

    def test_a_widened_reader_accepts_both_forms(self):
        """Sharpening test for RC-015: the intermediate state is valid.

        Step one of a migration widens the accepted set. While it is widened,
        both the outgoing and the incoming data form must load, which is
        exactly what makes the write order irrelevant.
        """
        original = guard_rules.ACCEPTED_CONFIG_VERSIONS
        guard_rules.ACCEPTED_CONFIG_VERSIONS = ("1.0.0", "1.1.0")
        self.addCleanup(
            setattr, guard_rules, "ACCEPTED_CONFIG_VERSIONS", original
        )
        for version in ("1.0.0", "1.1.0"):
            with self.subTest(version=version):
                directory, target = write_document({"config_version": version})
                self.addCleanup(shutil.rmtree, directory, True)
                rules = guard_rules.load_rules(str(target))
                self.assertEqual(rules.raw["config_version"], version)

    def test_a_narrowed_reader_rejects_the_outgoing_form(self):
        """Counter test for RC-015: narrowing really removes the old form."""
        directory, target = write_document({"config_version": "1.0.0"})
        self.addCleanup(shutil.rmtree, directory, True)
        with self.assertRaises(guard_rules.ConfigError):
            guard_rules.load_rules(str(target))

    def test_the_accepted_set_is_a_membership_test_not_a_constant(self):
        source = RULES_PY.read_text(encoding="utf-8")
        self.assertIn("ACCEPTED_CONFIG_VERSIONS", source)
        self.assertIn("not in ACCEPTED_CONFIG_VERSIONS", source)


class TestDeferenceIsComplete(unittest.TestCase):
    """A deference that first loads what it renounces is not a deference."""

    def _candidate_root(self, *, break_config):
        scratch = Path(tempfile.mkdtemp(prefix="deference-"))
        self.addCleanup(shutil.rmtree, scratch, True)
        for relative in ("tools", "config"):
            shutil.copytree(
                REPO_ROOT / relative, scratch / relative,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        if break_config:
            target = scratch / "tools" / "guard" / "rules.json"
            document = json.loads(target.read_text(encoding="utf-8"))
            document["a_field_no_reader_accepts"] = True
            target.write_text(json.dumps(document), encoding="utf-8")
        return scratch

    def _run(self, scratch, *, authoritative, command="echo hello"):
        original = list(sys.path)
        removed = {
            name: sys.modules.pop(name)
            for name in [key for key in sys.modules if key.startswith("tools.")]
        }
        sys.path.insert(0, str(scratch))
        try:
            from tools.gates import hookguard as candidate  # noqa: PLC0415

            payload = json.dumps({
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(scratch),
            })
            out = io.StringIO()
            candidate.main(
                stdin=io.StringIO(payload),
                stdout=out,
                authoritative=lambda: authoritative,
            )
            return json.loads(out.getvalue())
        finally:
            sys.path[:] = original
            for name in [key for key in sys.modules if key.startswith("tools.")]:
                del sys.modules[name]
            sys.modules.update(removed)

    def test_a_broken_configuration_still_abstains(self):
        """Sharpening test for RC-016. Fails before the fix: it blocked."""
        scratch = self._candidate_root(break_config=True)
        response = self._run(scratch, authoritative=True)
        self.assertEqual(response.get("guardOutcome"), "no_opinion")
        self.assertEqual(response.get("deferredTo"), "authoritative_guard")

    def test_a_broken_configuration_still_blocks_without_a_guard(self):
        """Counter test for RC-016. Fail closed is preserved where it counts.

        The deference is what moved, not the blocking. With no authoritative
        guard to defer to, an unusable configuration still denies.
        """
        scratch = self._candidate_root(break_config=True)
        response = self._run(scratch, authoritative=False)
        specific = response.get("hookSpecificOutput", {})
        self.assertEqual(specific.get("permissionDecision"), "deny")

    def test_a_sound_configuration_still_denies_without_a_guard(self):
        """The layer keeps deciding when it is the only one there."""
        scratch = self._candidate_root(break_config=False)
        response = self._run(
            scratch, authoritative=False, command="git reset --hard HEAD~1"
        )
        specific = response.get("hookSpecificOutput", {})
        self.assertEqual(specific.get("permissionDecision"), "deny")

    def test_the_configuration_is_not_read_while_importing(self):
        """The mechanical property, stated directly on the source."""
        source = (REPO_ROOT / "tools" / "gates" / "hookguard.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            rendered = ast.dump(node)
            self.assertNotIn(
                "'_rules'", rendered,
                "module level assignment reads the configuration at import",
            )

    def test_the_previous_attributes_still_resolve(self):
        self.assertTrue(hookguard.HARD_DENY_COMMAND_RULES)
        self.assertTrue(hookguard.REWRITE_CLASSES)
        self.assertTrue(hookguard.REASON_TEXT)


class TestR7Sweep(unittest.TestCase):
    """The declared outcome of the sweep, including its exemptions."""

    DECLARATION = REPO_ROOT / "config" / "governance" / "field-binding.json"

    def test_the_declaration_exists(self):
        self.assertTrue(self.DECLARATION.is_file())

    def test_every_examined_field_has_a_verdict(self):
        document = json.loads(self.DECLARATION.read_text(encoding="utf-8"))
        for entry in document["examined"]:
            with self.subTest(field=entry["field"]):
                self.assertIn(
                    entry["verdict"],
                    ("bound", "checked", "exempt_descriptive", "open_finding"),
                )
                self.assertTrue(str(entry["evidence"]).strip())

    def test_the_exemptions_are_stated_and_reasoned(self):
        """So they are never later read as an omission."""
        document = json.loads(self.DECLARATION.read_text(encoding="utf-8"))
        exempt = [
            entry for entry in document["examined"]
            if entry["verdict"] == "exempt_descriptive"
        ]
        self.assertTrue(exempt)
        for entry in exempt:
            with self.subTest(field=entry["field"]):
                self.assertTrue(str(entry["reason"]).strip())
                self.assertFalse(entry["carries_reliability_claim"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
