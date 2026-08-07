"""B0g: the genesis import contract is writable through the tool (RC-032).

The register model has always carried and validated the genesis import
fields (``import_note``, ``original_file``) and rejected them on normal
events — but the CLI could not emit what its own reader demands, so a
genesis import could not mark unprovable historical metadata as the
contract requires. The mandatory pair:

*Sharpening.* A genesis assign through the public wrapper carries both
fields into the stored event, canonically serialised and chain-bound.

*Counter.* A normal assign that smuggles an import note is refused by the
model (``genesis_field_on_normal_event``), and a plain genesis without the
fields still works exactly as before.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.decreg import model  # noqa: E402

SCRIPT = REPO_ROOT / "scripts" / "dec-reservations.sh"
OWNER = (
    "--owner-ref", "owner-fixture",
    "--origin-line", "line-fixture-alpha",
    "--recorded-at-utc", "2026-08-07T00:00:00Z",
    "--source-commit", "a" * 40,
)


def git(*arguments):
    return subprocess.run(
        ["git", *[str(a) for a in arguments]],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


class RegisterFixture(unittest.TestCase):
    def setUp(self):
        super().setUp()
        import shutil

        base = Path(tempfile.mkdtemp(prefix="b0g-register-"))
        self.addCleanup(shutil.rmtree, base, True)
        fixture_root = base / ".gate-runtime" / "fixtures" / "git"
        fixture_root.mkdir(parents=True)
        self.bare = fixture_root / "dec-register.git"
        subprocess.run(
            ["git", "init", "--bare", "--quiet", str(self.bare)], check=True
        )

    def run_tool(self, *arguments):
        completed = subprocess.run(
            ["/bin/bash", str(SCRIPT), "--repo", str(self.bare),
             *[str(item) for item in arguments]],
            cwd=str(REPO_ROOT), capture_output=True, timeout=120, check=False,
        )
        raw = completed.stdout.decode("utf-8", "replace")
        self.assertTrue(raw.strip(), completed.stderr.decode()[:300])
        return completed.returncode, json.loads(raw)

    def register_text(self):
        blob = subprocess.run(
            ["git", "-C", str(self.bare), "cat-file", "blob",
             "refs/governance/dec-reservations:dec-reservations.jsonl"],
            capture_output=True, check=True,
        ).stdout.decode("utf-8")
        return blob


class TestGenesisImportContract(RegisterFixture):
    def test_a_genesis_assign_carries_the_import_marking(self):
        code, payload = self.run_tool(
            "assign", "--genesis", "--dec-id", "DEC-001", *OWNER,
            "--import-note",
            "historical allocation imported from both immutable register states; original owner and time not provable",
            "--original-file", "docs/personal-jarvis/decisions-register.md",
        )
        self.assertEqual(code, 0, payload)
        events, _state, _digest = model.parse(self.register_text())
        event = events[-1]
        self.assertTrue(event["genesis"])
        self.assertEqual(
            event["original_file"], "docs/personal-jarvis/decisions-register.md"
        )
        self.assertIn("not provable", event["import_note"])

    def test_a_normal_event_cannot_smuggle_the_import_fields(self):
        code, payload = self.run_tool(
            "reserve", "--dec-id", "DEC-900", *OWNER
        )
        self.assertEqual(code, 0, payload)
        code, payload = self.run_tool(
            "assign", "--dec-id", "DEC-900", *OWNER,
            "--import-note", "smuggled",
        )
        self.assertEqual(code, 1)
        self.assertEqual(payload["reason_code"], "genesis_field_on_normal_event")

    def test_a_plain_genesis_without_the_fields_still_works(self):
        code, _payload = self.run_tool(
            "assign", "--genesis", "--dec-id", "DEC-002", *OWNER
        )
        self.assertEqual(code, 0)
        events, _state, _digest = model.parse(self.register_text())
        event = events[-1]
        self.assertTrue(event["genesis"])
        self.assertNotIn("import_note", event)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
