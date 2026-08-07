"""The exception fixture and manipulation matrix, executed.

Every row of ``config/guard/exception-manipulation-matrix.json`` is applied to
a real exception object and the declared outcome is asserted against the
guard's own functions — the structural layer, the qualification layer, the
consumption path and the owner collection tool.

**Rule R9 governs this file.** Every row's manipulation is proved to have
taken effect *before* anything is asserted about the guard. If a manipulation
turns into a no-op — because a field was renamed, a literal moved, a default
changed — the row fails on the manipulation, not on the guard, and the failure
message says so. ``TestRuleR9`` then proves the probe is not decorative: it
runs a row whose manipulation deliberately does nothing and requires the probe
to catch it.

Nothing here touches the owner installed guard, the protected areas, or the
historical evidence objects. Every object is built here, lives in a throwaway
directory below the declared fixture root, and is removed afterwards.
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.guard import EXCEPTION_SCHEMA  # noqa: E402
from tools.guard import GUARD_VERSION  # noqa: E402
from tools.guard import owner_exception  # noqa: E402
from tools.guard import rules as rules_module  # noqa: E402
from tools.guardops import collect as collect_module  # noqa: E402
from tools.guardops import matrix as matrix_module  # noqa: E402

POLICY = rules_module.load_rules(str(REPO_ROOT / "tools" / "guard" / "rules.json")).exception_policy
NOW = 1_800_000_000
COMMAND = "rm -r /private/tmp/jarvis-matrix-fixture"


def _matrix():
    return matrix_module.load_matrix(REPO_ROOT)


class MatrixTestBase(unittest.TestCase):
    """One throwaway fixture area per test, below the declared root."""

    def setUp(self):
        super().setUp()
        self.document = _matrix()
        self.fixture_root = REPO_ROOT / self.document["fixtures"]["root"]
        self.area = self.fixture_root / f"case-{self.id().rsplit('.', 1)[-1]}"
        if self.area.exists():  # pragma: no cover - only after a hard abort
            shutil.rmtree(str(self.area))
        self.area.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.area), True)
        #: Every write this test performs, so the fixture discipline can be
        #: asserted from what happened rather than from what was intended.
        self.written = []

    def write_object(self, path, data):
        """The only writer in this file. Refuses to leave the fixture area."""
        target = Path(path)
        self.assertIn(
            self.area,
            target.parents,
            f"a fixture write left the declared area: {target}",
        )
        target.write_bytes(data)
        self.written.append(target)
        return target

    def row_area(self, entry_id):
        """A fresh pending and spent pair, so rows cannot influence each other.

        Sharing one spent directory would let the control's consumed marker
        make a later row look already used — a row would then pass or fail for
        a reason that has nothing to do with its own manipulation.
        """
        area = self.area / str(entry_id)
        (area / "pending").mkdir(parents=True, exist_ok=True)
        (area / "spent").mkdir(parents=True, exist_ok=True)
        return area

    def base_payload(self, worktree):
        """A well formed object, built and sealed by the guard itself."""
        return owner_exception.build(
            nonce="a" * 32,
            worktree=str(worktree),
            command=COMMAND,
            reason="B0d manipulation matrix fixture",
            created_at=NOW,
            ttl_seconds=600,
            guard_version=GUARD_VERSION,
        )

    def applied(self, entry, worktree):
        return matrix_module.apply(
            entry,
            self.base_payload(worktree),
            integrity_digest=owner_exception.integrity_digest,
            now=NOW,
            stem="a" * 32,
        )

    def assert_effect(self, applied):
        """Rule R9, stated once and used by every row that follows."""
        self.assertTrue(
            applied.probe_holds,
            f"{applied.entry_id}: the declared manipulation had no effect "
            f"(probe {applied.probe} over {applied.probe_detail}); the row "
            f"tests nothing until this is fixed",
        )


class TestMatrixDocument(unittest.TestCase):
    """The matrix itself, before anything is executed from it."""

    def test_it_loads(self):
        document = _matrix()
        self.assertTrue(document["entries"])

    def test_exactly_one_control(self):
        controls = [
            entry
            for entry in _matrix()["entries"]
            if entry["manipulation"]["operation"] == "none"
        ]
        self.assertEqual(len(controls), 1)

    def test_only_the_control_may_have_a_decision_effect_that_is_a_candidate(self):
        for entry in _matrix()["entries"]:
            if entry["expected_decision_effect"]:
                with self.subTest(entry=entry["entry_id"]):
                    self.assertEqual(entry["expected_classification"], "candidate")

    def test_no_corrupt_row_is_ever_collected(self):
        for entry in _matrix()["entries"]:
            if entry["expected_structure"] == "structurally_corrupt":
                with self.subTest(entry=entry["entry_id"]):
                    self.assertEqual(entry["expected_collection"], "left_in_place")

    def test_every_corruption_code_is_covered_or_declared_unreachable(self):
        """The completeness claim, derived from the source, not from memory.

        Every ``ExceptionCorrupt`` code the structural layer can raise must
        either appear in a row or be declared unreachable with a reason. A new
        code added to the guard without a row fails here.
        """
        source = (REPO_ROOT / "tools" / "guard" / "owner_exception.py").read_text(
            encoding="utf-8"
        )
        raised = set()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            call = node.exc
            if not isinstance(call, ast.Call):
                continue
            name = getattr(call.func, "id", "") or getattr(call.func, "attr", "")
            if name != "ExceptionCorrupt" or not call.args:
                continue
            first = call.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                raised.add(first.value)
        self.assertTrue(raised, "no corruption codes found in the guard source")

        document = _matrix()
        covered = set(matrix_module.reachable_codes(document))
        declared = set(matrix_module.declared_unreachable(document))
        missing = sorted(raised - covered - declared)
        self.assertEqual(
            missing, [], f"corruption codes with neither a row nor a reason: {missing}"
        )

    def test_no_declared_unreachable_code_is_secretly_covered(self):
        document = _matrix()
        both = sorted(
            set(matrix_module.reachable_codes(document))
            & set(matrix_module.declared_unreachable(document))
        )
        self.assertEqual(both, [])


class TestEveryRow(MatrixTestBase):
    """Each row applied to a real object and judged by the real guard."""

    def test_every_row(self):
        for entry in self.document["entries"]:
            with self.subTest(entry=entry["entry_id"]):
                self._run_row(entry)

    def _run_row(self, entry):
        row = self.row_area(entry["entry_id"])
        worktree = row / "worktree"
        worktree.mkdir(exist_ok=True)
        applied = self.applied(entry, worktree)

        # Rule R9 first, always. Nothing below this line is meaningful until
        # the manipulation is known to have happened.
        self.assert_effect(applied)

        target = self.write_object(
            row / "pending" / (applied.stem + ".json"), applied.raw
        )

        record = collect_module.inspect_object(
            target,
            _WorktreeGuard(),
            now=NOW,
            worktree_id=owner_exception.worktree_id(str(worktree)),
        )
        self.assertEqual(record["structure"], entry["expected_structure"])
        self.assertEqual(
            record["corruption_code"], entry["expected_corruption_code"]
        )
        self.assertEqual(
            record["classification"], entry["expected_classification"]
        )
        self.assertEqual(
            record["decision_effect_possible"], entry["expected_decision_effect"]
        )

        would_collect = collect_module.collectable([record])
        expected = (
            [record["object_id"]]
            if entry["expected_collection"] == "collected"
            else []
        )
        self.assertEqual(would_collect, expected)

        self._assert_consumption(entry, row, worktree)
        target.unlink()

    def _assert_consumption(self, entry, row, worktree):
        """What the decision path really does with this object."""
        if entry["expected_structure"] == "structurally_corrupt":
            with self.assertRaises(owner_exception.ExceptionCorrupt) as caught:
                self._consume(row, worktree)
            self.assertEqual(caught.exception.args[0], entry["expected_corruption_code"])
            return

        outcome = self._consume(row, worktree)
        if entry["expected_decision_effect"]:
            self.assertTrue(outcome.granted)
            return
        # The whole point of the block: byte identical to an empty area.
        self.assertFalse(outcome.granted)
        self.assertEqual(outcome.reason_code, "no_exception")
        self.assertEqual(outcome.nonce_digest, "")
        self.assertEqual(
            [item.classification for item in outcome.observations],
            [entry["expected_classification"]],
        )

    def _consume(self, row, worktree):
        return owner_exception.consume(
            pending_dir=row / "pending",
            spent_dir=row / "spent",
            worktree=str(worktree),
            command=COMMAND,
            now=NOW,
            policy=POLICY,
            guard_version=GUARD_VERSION,
            schema=EXCEPTION_SCHEMA,
        )


class _WorktreeGuard:
    """The repository copy, wrapped in what the collection tool expects."""

    source = collect_module.SOURCE_WORKTREE
    root = REPO_ROOT / "tools" / "guard"
    version = GUARD_VERSION
    schema = EXCEPTION_SCHEMA
    policy = POLICY
    module = owner_exception

    def describe(self):
        return {"guard_source": self.source, "guard_version": self.version}


class TestRuleR9(MatrixTestBase):
    """The probe is load bearing, and this proves it.

    Without this test the whole matrix could quietly degrade into rows that
    manipulate nothing and then assert the base object's behaviour — which is
    exactly the defect rule R9 was written for.
    """

    def test_a_manipulation_that_does_nothing_is_caught_by_its_probe(self):
        entry = {
            "entry_id": "synthetic-no-op",
            # Sets the field to the value it already has. Structurally a
            # write, semantically nothing.
            "manipulation": {"operation": "set_field", "field": "guard_version",
                             "value": GUARD_VERSION},
            "effect_probe": "field_differs",
            "expected_structure": "structurally_sound",
            "expected_corruption_code": "",
            "expected_classification": "version_mismatch",
            "expected_decision_effect": False,
            "expected_collection": "collected",
            "rationale": "synthetic",
        }
        applied = self.applied(entry, self.area / "worktree")
        self.assertFalse(
            applied.probe_holds,
            "a manipulation that changed nothing was reported as effective",
        )

    def test_the_failure_lands_on_the_manipulation_not_on_the_guard(self):
        entry = {
            "entry_id": "synthetic-no-op",
            "manipulation": {"operation": "set_field", "field": "reason",
                             "value": "B0d manipulation matrix fixture"},
            "effect_probe": "field_differs",
            "expected_structure": "structurally_corrupt",
            "expected_corruption_code": "integrity_digest",
            "expected_classification": "",
            "expected_decision_effect": False,
            "expected_collection": "left_in_place",
            "rationale": "synthetic",
        }
        applied = self.applied(entry, self.area / "worktree")
        with self.assertRaises(AssertionError) as caught:
            self.assert_effect(applied)
        self.assertIn("had no effect", str(caught.exception))

    def test_the_control_proves_the_absence_of_an_effect(self):
        control = [
            entry
            for entry in self.document["entries"]
            if entry["manipulation"]["operation"] == "none"
        ][0]
        applied = self.applied(control, self.area / "worktree")
        self.assertTrue(applied.probe_holds)
        self.assertEqual(applied.raw, applied.original_raw)


class TestFixtureDiscipline(MatrixTestBase):
    """Where the matrix is allowed to write, and where it never writes."""

    def test_the_declared_root_is_relative_and_inside_the_runtime_area(self):
        root = self.document["fixtures"]["root"]
        self.assertFalse(str(root).startswith("/"))
        self.assertTrue(str(root).startswith(".gate-runtime/"))

    def test_no_entry_writes_outside_the_declared_fixture_root(self):
        """The applier is pure; the only writer here is this test itself."""
        worktree = self.area / "worktree"
        worktree.mkdir(exist_ok=True)
        for entry in self.document["entries"]:
            with self.subTest(entry=entry["entry_id"]):
                applied = self.applied(entry, worktree)
                self.assertIsInstance(applied.raw, bytes)
                # A stem that could leave the area is the one way a row could
                # escape it, so it is checked rather than assumed.
                self.assertNotIn("/", applied.stem)
                self.assertNotIn("..", applied.stem)

    def test_every_write_of_a_full_run_stayed_inside_the_fixture_area(self):
        """From what happened, not from what was intended.

        The whole matrix is executed here and every write is recorded. The
        assertion is over the recorded paths, so a row that reached a real
        area would be caught by this test even if it passed its own.
        """
        runner = TestEveryRow("test_every_row")
        runner.setUp()
        self.addCleanup(lambda: [item.doCleanups() for item in (runner,)])
        runner.test_every_row()
        self.assertTrue(runner.written)
        for target in runner.written:
            with self.subTest(path=target.name):
                self.assertIn(runner.area, target.parents)
                self.assertIn(runner.fixture_root, target.parents)

    def test_the_read_only_areas_are_declared(self):
        """Naming them is what makes a later violation nameable."""
        read_only = self.document["fixtures"]["read_only_areas"]
        self.assertTrue(read_only)
        for statement in read_only:
            with self.subTest(statement=statement[:40]):
                self.assertTrue(str(statement).strip())


class TestCollectionToolAgreesWithTheMatrix(MatrixTestBase):
    """``collectable`` is the tool's answer, and it must be the matrix's."""

    def test_pending_area_partitions_exactly_as_declared(self):
        row = self.row_area("shared")
        worktree = row / "worktree"
        worktree.mkdir(exist_ok=True)
        expected_collect = []
        records = []
        for entry in self.document["entries"]:
            applied = self.applied(entry, worktree)
            self.assert_effect(applied)
            stem = f"{applied.entry_id}"
            target = self.write_object(
                row / "pending" / (stem + ".json"), applied.raw
            )
            record = collect_module.inspect_object(
                target,
                _WorktreeGuard(),
                now=NOW,
                worktree_id=owner_exception.worktree_id(str(worktree)),
            )
            records.append(record)
            if entry["expected_collection"] == "collected":
                expected_collect.append(stem)
        self.assertEqual(
            collect_module.collectable(records), sorted(expected_collect)
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
