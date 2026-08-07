"""The owner collection tool: what it may do, and what it may never do.

The tool exists because an ignored exception object stays in the protected
pending area forever and only the owner may move it. That makes exactly one
question load bearing: can the guarded session move anything? The answer has
to hold structurally, not by intention, so it is checked three ways —

* by running the read only subcommands against a real area and proving the
  area is byte identical afterwards,
* by parsing the module and proving no write call exists outside the single
  writing function,
* by calling the writing function as a non root user and proving it refuses
  before its first write.

Nothing here touches the owner installed guard. Every installation below is a
throwaway directory built from the repository copy.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tests.tooling.guard import _support  # noqa: E402
from tools.guard import GUARD_VERSION  # noqa: E402
from tools.guard import owner_exception  # noqa: E402
from tools.guardops import collect as collect_module  # noqa: E402

NOW = 1_800_000_000

#: Functions that may write. Everything else in the module is read only, and
#: the test below proves it from the syntax tree rather than from the prose.
WRITING_FUNCTIONS = ("_move_object", "command_collect")

#: Call names that write to the file system. A new one appearing outside the
#: writing functions is the defect this list exists to catch. Bare ``write``
#: is deliberately absent: it is how the report reaches stdout, and a file
#: handle can only be obtained through ``open``, which is listed.
WRITING_CALLS = ("open", "write_bytes", "write_text", "unlink", "mkdir",
                 "rename", "replace", "rmtree", "chown", "chmod", "touch")


class ToolTestBase(_support.TempInstallationMixin):
    def setUp(self):
        super().setUp()
        self.pending = self.root / "var" / "exceptions" / "pending"
        self.collected = self.root / "var" / "exceptions" / "collected"
        self.worktree = self.tmp_path / "worktree"
        self.worktree.mkdir()

    def place(self, *, stem, created_at=NOW, guard_version=None, command="rm -r /private/tmp/x"):
        payload = owner_exception.build(
            nonce=stem,
            worktree=str(self.worktree),
            command=command,
            reason="collection tool fixture",
            created_at=created_at,
            ttl_seconds=600,
            guard_version=guard_version or GUARD_VERSION,
        )
        target = self.pending / (stem + ".json")
        target.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        return target

    def snapshot(self, directory):
        """Content and names of an area, for a before and after comparison."""
        base = Path(directory)
        if not base.is_dir():
            return {}
        return {
            item.name: hashlib.sha256(item.read_bytes()).hexdigest()
            for item in sorted(base.glob("*"))
            if item.is_file()
        }

    def run_tool(self, *arguments):
        stream = io.StringIO()
        code = collect_module.main(
            list(arguments)
            + [
                "--target", str(self.root),
                "--worktree", str(self.worktree),
                "--guard-source", "worktree",
                "--now", str(NOW),
            ],
            stdout=stream,
        )
        return code, json.loads(stream.getvalue())


class TestReadOnlySubcommands(ToolTestBase):
    def test_status_verify_and_plan_change_nothing(self):
        self.place(stem="a" * 32)
        self.place(stem="b" * 32, guard_version="0.9.0")
        self.place(stem="c" * 32, created_at=NOW - 601)
        before = {
            name: self.snapshot(self.root / "var" / "exceptions" / name)
            for name in ("pending", "collected", "spent")
        }
        for subcommand in collect_module.READ_ONLY_COMMANDS:
            with self.subTest(subcommand=subcommand):
                self.run_tool(subcommand)
        after = {
            name: self.snapshot(self.root / "var" / "exceptions" / name)
            for name in ("pending", "collected", "spent")
        }
        self.assertEqual(before, after)

    def test_every_read_only_report_says_it_wrote_nothing(self):
        self.place(stem="a" * 32)
        for subcommand in collect_module.READ_ONLY_COMMANDS:
            with self.subTest(subcommand=subcommand):
                _code, report = self.run_tool(subcommand)
                self.assertFalse(report["wrote_anything"])

    def test_status_separates_the_three_kinds(self):
        self.place(stem="a" * 32)
        self.place(stem="b" * 32, guard_version="0.9.0")
        self.place(stem="c" * 32, created_at=NOW - 601)
        code, report = self.run_tool("status")
        self.assertEqual(code, collect_module.EXIT_OK)
        self.assertEqual(report["candidates_present"], ["a" * 32])
        self.assertEqual(report["collectable"], ["b" * 32, "c" * 32])
        self.assertEqual(report["corrupt_present"], [])

    def test_a_corrupt_object_is_a_finding_and_is_not_collectable(self):
        (self.pending / ("d" * 32 + ".json")).write_text("{", encoding="utf-8")
        code, report = self.run_tool("status")
        self.assertEqual(code, collect_module.EXIT_FINDING)
        self.assertEqual(report["corrupt_present"], ["d" * 32])
        self.assertEqual(report["collectable"], [])

    def test_verify_rederives_the_seal_and_catches_an_edit(self):
        target = self.place(stem="a" * 32)
        payload = json.loads(target.read_text(encoding="utf-8"))
        before = dict(payload)
        payload["reason"] = "edited after the owner sealed it"
        target.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        # Rule R9: the edit is proved before the tool is asked about it.
        self.assertNotEqual(
            json.loads(target.read_text(encoding="utf-8"))["reason"],
            before["reason"],
            "the edit did not take effect",
        )
        code, report = self.run_tool("verify")
        self.assertEqual(code, collect_module.EXIT_FINDING)
        self.assertEqual(
            [item["code"] for item in report["findings"]], ["integrity_digest"]
        )

    def test_verify_reports_a_missing_area_rather_than_passing(self):
        code, report = self.run_tool("verify", "--area", "collected")
        # The area exists in a fresh installation, so remove it to reach the
        # case, and prove the removal happened first.
        self.collected.rmdir()
        self.assertFalse(self.collected.is_dir(), "the area was not removed")
        code, report = self.run_tool("verify", "--area", "collected")
        self.assertEqual(code, collect_module.EXIT_FINDING)
        self.assertEqual([item["code"] for item in report["findings"]], ["area_absent"])


class TestPlanCollect(ToolTestBase):
    def test_it_names_exactly_what_would_move_and_runs_nothing(self):
        self.place(stem="a" * 32)
        self.place(stem="b" * 32, guard_version="0.9.0")
        code, report = self.run_tool("plan-collect")
        self.assertEqual(code, collect_module.EXIT_OK)
        self.assertFalse(report["executed"])
        self.assertEqual(report["would_move"], ["b" * 32])
        self.assertEqual(report["would_stay"], ["a" * 32])
        self.assertTrue(report["owner_action"])

    def test_the_printed_command_is_exact_and_needs_no_substitution(self):
        _code, report = self.run_tool("plan-collect")
        command = report["owner_command"]
        self.assertTrue(command.startswith("sudo /bin/bash scripts/guard-collect.sh collect"))
        self.assertIn(str(self.root), command)
        self.assertIn("--confirm", command)
        for placeholder in ("<", ">", "${", "..."):
            self.assertNotIn(placeholder, command)

    def test_the_plan_leaves_the_pending_area_untouched(self):
        self.place(stem="b" * 32, guard_version="0.9.0")
        before = self.snapshot(self.pending)
        self.run_tool("plan-collect")
        self.assertEqual(self.snapshot(self.pending), before)


class TestCollectRefusesForTheSession(ToolTestBase):
    def test_collect_refuses_without_root_and_writes_nothing(self):
        self.place(stem="b" * 32, guard_version="0.9.0")
        before = self.snapshot(self.pending)
        self.assertNotEqual(os.geteuid(), 0, "these tests must not run as root")
        code, report = self.run_tool("collect", "--confirm")
        self.assertEqual(code, collect_module.EXIT_REFUSED)
        self.assertTrue(report["refused"])
        self.assertEqual(report["reason_code"], "collect_requires_root")
        self.assertFalse(report["wrote_anything"])
        self.assertEqual(self.snapshot(self.pending), before)

    def test_the_refusal_is_the_first_statement_of_the_writing_function(self):
        """Not a promise: the position in the syntax tree."""
        source = (REPO_ROOT / "tools" / "guardops" / "collect.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        function = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "command_collect"
        ][0]
        first = function.body[1] if isinstance(function.body[0], ast.Expr) else function.body[0]
        self.assertIsInstance(first, ast.If)
        self.assertIn("geteuid", ast.dump(first.test))

    def test_no_write_call_exists_outside_the_writing_functions(self):
        source = (REPO_ROOT / "tools" / "guardops" / "collect.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name in WRITING_FUNCTIONS:
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                name = getattr(inner.func, "id", "") or getattr(inner.func, "attr", "")
                if name in WRITING_CALLS:
                    offenders.append(f"{node.name}:{name}")
        self.assertEqual(sorted(set(offenders)), [])


class TestMoveIsNeverDestructive(ToolTestBase):
    """The writing primitive itself, exercised without needing root."""

    def test_a_move_is_byte_identical_and_removes_the_source_last(self):
        source = self.place(stem="b" * 32, guard_version="0.9.0")
        raw = source.read_bytes()
        destination = self.collected / source.name
        ok, code = collect_module._move_object(source, destination)
        self.assertTrue(ok, code)
        self.assertEqual(destination.read_bytes(), raw)
        self.assertFalse(source.exists())

    def test_an_already_collected_object_is_never_overwritten(self):
        source = self.place(stem="b" * 32, guard_version="0.9.0")
        destination = self.collected / source.name
        destination.write_bytes(b"{}")
        ok, code = collect_module._move_object(source, destination)
        self.assertFalse(ok)
        self.assertEqual(code, "already_collected")
        # Both survive: nothing is destroyed on the strength of a conflict.
        self.assertTrue(source.exists())
        self.assertEqual(destination.read_bytes(), b"{}")


class TestGuardSourceIsStated(ToolTestBase):
    def test_every_report_names_the_guard_it_speaks_for(self):
        for subcommand in collect_module.READ_ONLY_COMMANDS:
            with self.subTest(subcommand=subcommand):
                _code, report = self.run_tool(subcommand)
                self.assertEqual(report["guard_source"], "worktree")
                self.assertEqual(report["guard_version"], GUARD_VERSION)

    def test_a_guard_without_the_qualification_layer_is_refused(self):
        """The tool describes a guard in that guard's own words, or not at all."""
        target = self.root / "active" / "guard" / "owner_exception.py"
        os.chmod(str(target), 0o644)
        before = target.read_text(encoding="utf-8")
        target.write_text(
            before.replace("def structural_parse(", "def _removed_structural_parse("),
            encoding="utf-8",
        )
        # Rule R9: the removal is proved before the refusal is asserted.
        self.assertNotIn(
            "\ndef structural_parse(",
            target.read_text(encoding="utf-8"),
            "the qualification function was not removed",
        )
        stream = io.StringIO()
        code = collect_module.main(
            ["status", "--target", str(self.root), "--worktree", str(self.worktree),
             "--guard-source", "active", "--now", str(NOW)],
            stdout=stream,
        )
        report = json.loads(stream.getvalue())
        self.assertEqual(code, collect_module.EXIT_UNUSABLE)
        self.assertEqual(report["reason_code"], collect_module.LACKS_API)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
