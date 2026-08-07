"""The derived corpus of executable check paths.

The derivation must find every file that a real discovery would execute, must
say for each file *why* it is executable, and must never turn a missing
discovery input into an empty, clean-looking sweep. Rule R9 applies to the
withdrawal tests below: the withdrawal is established before anything is
asserted about the derivation.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.gates import astcorpus  # noqa: E402

MANIFEST_FIXTURE = (
    REPO_ROOT / "config" / "gates" / "fixtures" / "manifests" / "valid" / "minimal.json"
)


def build_mini_worktree(root):
    """A smallest complete worktree the derivation accepts."""
    root = Path(root)
    (root / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n', encoding="utf-8"
    )
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_alpha.py").write_text(
        textwrap.dedent(
            """
            import tools.helper

            def test_breaks_the_package(target):
                target.write_text(target.read_text().replace("1.0.0", "1.0.1"))
                assert tools.helper.decide(target) == "deny"
            """
        ),
        encoding="utf-8",
    )
    blocks = root / "config" / "gates" / "blocks"
    blocks.mkdir(parents=True)
    shutil.copyfile(MANIFEST_FIXTURE, blocks / "fixture-valid.json")
    runners = root / "tools" / "gates" / "runners"
    runners.mkdir(parents=True)
    (runners / "shell_syntax.py").write_text(
        "def main():\n    return 0\n", encoding="utf-8"
    )
    (root / "tools" / "helper.py").write_text(
        "def decide(target):\n    return 'deny'\n", encoding="utf-8"
    )
    (root / "scripts").mkdir()
    (root / "scripts" / "run-alpha.sh").write_text(
        "#!/bin/sh\nexec python3 -m tools.helper\n", encoding="utf-8"
    )
    return root


class MiniWorktree(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="ast-corpus-")
        self.addCleanup(self._tmp.cleanup)
        self.root = build_mini_worktree(self._tmp.name)


class TestDerivation(MiniWorktree):
    def test_every_source_kind_contributes_and_is_recorded(self):
        corpus = astcorpus.derive(self.root)
        by_source = {}
        for record in corpus.files.values():
            self.assertTrue(record.derivations, f"{record.path} has no derivation")
            for derivation in record.derivations:
                by_source.setdefault(derivation["source"], set()).add(record.path)
        self.assertIn("tests/test_alpha.py", by_source["pytest_testpaths"])
        self.assertIn("tools/gates/runners/shell_syntax.py", by_source["manifest_runner"])
        self.assertIn("tools/helper.py", by_source["entry_script"])
        self.assertIn("tools/helper.py", by_source["import_closure"])

    def test_the_counts_are_derived_and_non_zero(self):
        corpus = astcorpus.derive(self.root)
        self.assertGreater(corpus.counts["files"], 0)
        self.assertGreater(corpus.counts["units"], 0)
        self.assertGreater(corpus.counts["ast_nodes"], 0)
        self.assertEqual(corpus.counts["test_units"], 1)

    def test_a_withdrawn_discovery_input_blocks_instead_of_reporting_empty(self):
        astcorpus.derive(self.root)
        (self.root / "pyproject.toml").unlink()
        self.assertFalse(
            (self.root / "pyproject.toml").is_file(),
            "the discovery input was not withdrawn",
        )
        with self.assertRaises(astcorpus.CorpusError) as caught:
            astcorpus.derive(self.root)
        self.assertEqual(caught.exception.code, "corpus_source_missing")

    def test_a_withdrawn_test_tree_blocks_instead_of_reporting_empty(self):
        astcorpus.derive(self.root)
        shutil.rmtree(self.root / "tests")
        self.assertFalse(
            (self.root / "tests").is_dir(), "the test tree was not withdrawn"
        )
        with self.assertRaises(astcorpus.CorpusError) as caught:
            astcorpus.derive(self.root)
        self.assertEqual(caught.exception.code, "corpus_source_missing")

    def test_a_unitless_corpus_is_an_error_not_a_clean_sweep(self):
        for path in (
            self.root / "tests" / "test_alpha.py",
            self.root / "tools" / "helper.py",
        ):
            path.write_text("CONSTANT = 1\n", encoding="utf-8")
        (self.root / "tools" / "gates" / "runners" / "shell_syntax.py").write_text(
            "CONSTANT = 2\n", encoding="utf-8"
        )
        with self.assertRaises(astcorpus.CorpusError) as caught:
            astcorpus.derive(self.root)
        self.assertEqual(caught.exception.code, "corpus_empty")
        self.assertEqual(caught.exception.detail, "units")

    def test_an_overridden_discovery_convention_is_refused(self):
        """If ``python_files`` were overridden, the derivation would silently
        diverge from what pytest actually runs — refusing is the honest move."""
        (self.root / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\n"
            'testpaths = ["tests"]\n'
            'python_files = ["check_*.py"]\n',
            encoding="utf-8",
        )
        with self.assertRaises(astcorpus.CorpusError) as caught:
            astcorpus.derive(self.root)
        self.assertEqual(caught.exception.code, "corpus_convention_overridden")

    def test_an_unparseable_corpus_member_is_an_error(self):
        (self.root / "tests" / "test_alpha.py").write_text(
            "def broken(:\n", encoding="utf-8"
        )
        with self.assertRaises(astcorpus.CorpusError) as caught:
            astcorpus.derive(self.root)
        self.assertEqual(caught.exception.code, "corpus_file_unparseable")


class TestRealWorktree(unittest.TestCase):
    """The derivation over this repository itself."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = astcorpus.derive(REPO_ROOT)

    def test_the_real_corpus_is_substantial(self):
        self.assertGreater(self.corpus.counts["files"], 100)
        self.assertGreater(self.corpus.counts["units"], 1000)
        self.assertGreater(self.corpus.counts["ast_nodes"], 100000)

    def test_known_check_paths_are_derived_not_assumed(self):
        expected = {
            "tests/tooling/gates/test_cli.py": "unittest_discovery",
            "tools/gates/runners/b0d_checks.py": "manifest_runner",
            "tools/gates/cli.py": "entry_script",
            "tools/guard/entry.py": "import_closure",
            "tools/gates/emptyset.py": "import_closure",
        }
        for path, source in expected.items():
            record = self.corpus.files.get(path)
            self.assertIsNotNone(record, f"{path} missing from the corpus")
            self.assertIn(
                source,
                {derivation["source"] for derivation in record.derivations},
                f"{path} lacks the {source} derivation",
            )

    def test_a_check_path_outside_test_directories_is_still_found(self):
        """Executability comes from wiring, not from a directory name."""
        record = self.corpus.files.get("tools/guardops/collect.py")
        self.assertIsNotNone(record)
        sources = {derivation["source"] for derivation in record.derivations}
        self.assertIn("entry_script", sources)

    def test_the_derivation_evidence_is_serialisable(self):
        payload = {
            record.path: record.derivations for record in self.corpus.files.values()
        }
        parsed = json.loads(json.dumps(payload))
        self.assertEqual(len(parsed), self.corpus.counts["files"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
