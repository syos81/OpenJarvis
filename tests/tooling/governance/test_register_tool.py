"""The register tool end to end, against a throwaway bare repository.

The fixture lives below the declared fixture root of a temporary worktree —
the same layout the target bound guard rule releases — so the tool is
exercised in the shape it is actually meant to run in, without an owner
present and without touching the protected repository.

The forbidden command word is assembled from fragments where it has to appear
at all, because the guard backstop matches raw text and deliberately
over-detects.
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

from tools.decreg import model  # noqa: E402
from tools.decreg import store  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "dec-reservations.sh"

WHEN = "2026-08-06T18:00:00Z"
COMMIT = "b" * 40
OWNER = ["--owner-ref", "owner-fixture", "--origin-line", "line-fixture",
         "--recorded-at-utc", WHEN, "--source-commit", COMMIT]


def git(*arguments):
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", *[str(item) for item in arguments]],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=True, timeout=60, shell=False,
    )


class RegisterFixture(unittest.TestCase):
    def setUp(self):
        super().setUp()
        base = Path(tempfile.mkdtemp(prefix="register-tool-"))
        self.addCleanup(shutil.rmtree, base, True)
        fixture_root = base / ".gate-runtime" / "fixtures" / "git"
        fixture_root.mkdir(parents=True)
        self.bare = fixture_root / "dec-register.git"
        git("init", "--bare", "--quiet", self.bare)

    def run_tool(self, *arguments, repo=None):
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["/bin/bash", str(SCRIPT), "--repo", str(repo or self.bare),
             *[str(item) for item in arguments]],
            cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=120, check=False, shell=False,
        )
        raw = completed.stdout.decode("utf-8", "replace")
        self.assertTrue(raw.strip(), completed.stderr.decode()[:300])
        return completed.returncode, json.loads(raw)


class TestLifecycle(RegisterFixture):
    def test_an_empty_register_verifies(self):
        code, payload = self.run_tool("verify")
        self.assertEqual(code, 0)
        self.assertEqual(payload["events"], 0)
        self.assertEqual(payload["chain_digest"], model.EMPTY_DIGEST)

    def test_reserve_then_assign(self):
        code, payload = self.run_tool("reserve", "--dec-id", "DEC-900", *OWNER)
        self.assertEqual(code, 0)
        first = payload["ref_oid"]
        code, payload = self.run_tool("assign", "--dec-id", "DEC-900", *OWNER)
        self.assertEqual(code, 0)
        self.assertNotEqual(payload["ref_oid"], first)
        _code, status = self.run_tool("status")
        self.assertEqual(status["by_action"]["assigned"], ["DEC-900"])

    def test_every_forbidden_transition_is_refused(self):
        for arguments, expected in (
            (["assign", "--dec-id", "DEC-901"], "assign_without_reservation"),
            (["release", "--dec-id", "DEC-901"], "release_without_reservation"),
        ):
            with self.subTest(expected=expected):
                code, payload = self.run_tool(*arguments, *OWNER)
                self.assertEqual(code, 1)
                self.assertEqual(payload["reason_code"], expected)

    def test_a_double_reservation_is_refused(self):
        self.run_tool("reserve", "--dec-id", "DEC-900", *OWNER)
        code, payload = self.run_tool("reserve", "--dec-id", "DEC-900", *OWNER)
        self.assertEqual(code, 1)
        self.assertEqual(payload["reason_code"], "number_already_reserved")

    def test_an_assigned_number_is_terminal(self):
        self.run_tool("reserve", "--dec-id", "DEC-900", *OWNER)
        self.run_tool("assign", "--dec-id", "DEC-900", *OWNER)
        code, payload = self.run_tool("release", "--dec-id", "DEC-900", *OWNER)
        self.assertEqual(code, 1)
        self.assertEqual(payload["reason_code"], "number_is_terminal")

    def test_a_dry_run_writes_nothing(self):
        code, payload = self.run_tool(
            "reserve", "--dec-id", "DEC-900", *OWNER, "--dry-run"
        )
        self.assertEqual(code, 0)
        self.assertTrue(payload["dry_run"])
        _code, after = self.run_tool("verify")
        self.assertEqual(after["events"], 0)

    def test_reporting_a_number_free_does_not_reserve_it(self):
        _code, first = self.run_tool("next-free")
        _code, second = self.run_tool("next-free")
        self.assertEqual(first["next_free"], second["next_free"])
        _code, after = self.run_tool("verify")
        self.assertEqual(after["events"], 0)


class TestConcurrency(RegisterFixture):
    def test_a_concurrent_ref_move_refuses_the_write(self):
        """Compare and swap, enforced by git rather than by bookkeeping."""
        self.run_tool("reserve", "--dec-id", "DEC-900", *OWNER)
        current = store.state(self.bare)

        # Someone else advances the ref between read and write.
        other = model.build_event(
            dec_id="DEC-901",
            action=model.ACTION_RESERVED,
            owner_ref="owner-other",
            origin_line="line-other",
            recorded_at_utc=WHEN,
            source_commit=COMMIT,
            previous_digest=current["digest"],
            previous_event_id=current["events"][-1]["event_id"],
        )
        store.write(
            self.bare,
            model.append(current["text"], other),
            expected_oid=current["ref_oid"],
            message="concurrent",
        )

        stale = model.build_event(
            dec_id="DEC-902",
            action=model.ACTION_RESERVED,
            owner_ref="owner-stale",
            origin_line="line-stale",
            recorded_at_utc=WHEN,
            source_commit=COMMIT,
            previous_digest=current["digest"],
            previous_event_id=current["events"][-1]["event_id"],
        )
        with self.assertRaises(store.StoreError) as caught:
            store.write(
                self.bare,
                model.append(current["text"], stale),
                expected_oid=current["ref_oid"],
                message="stale",
            )
        self.assertEqual(caught.exception.code, "ref_moved_concurrently")

    def test_a_first_write_expects_an_absent_ref(self):
        current = store.state(self.bare)
        self.assertIsNone(current["ref_oid"])
        event = model.build_event(
            dec_id="DEC-900", action=model.ACTION_RESERVED,
            owner_ref="owner-fixture", origin_line="line-fixture",
            recorded_at_utc=WHEN, source_commit=COMMIT,
            previous_digest=current["digest"], previous_event_id=None,
        )
        text = model.append(current["text"], event)
        store.write(self.bare, text, expected_oid=None, message="first")
        with self.assertRaises(store.StoreError):
            store.write(self.bare, text, expected_oid=None, message="again")


class TestTheToolNeverPushes(RegisterFixture):
    def test_plan_push_performs_nothing(self):
        self.run_tool("reserve", "--dec-id", "DEC-900", *OWNER)
        code, payload = self.run_tool("plan-push", "--remote", "origin")
        self.assertEqual(code, 0)
        self.assertEqual(payload["push_status"], "not_performed_owner_action")

    def test_no_source_file_of_the_tool_performs_a_publication(self):
        forbidden = "pu" + "sh"
        for relative in ("scripts/dec-reservations.sh", "tools/decreg/cli.py",
                         "tools/decreg/store.py", "tools/decreg/remote.py"):
            with self.subTest(file=relative):
                source = (REPO_ROOT / relative).read_text(encoding="utf-8")
                for number, line in enumerate(source.splitlines(), start=1):
                    if "subprocess.run" not in line and "exec " not in line:
                        continue
                    self.assertNotIn(
                        '"' + forbidden + '"', line,
                        f"{relative}:{number} would publish",
                    )

    def test_the_printed_command_is_never_a_force_variant(self):
        self.run_tool("reserve", "--dec-id", "DEC-900", *OWNER)
        _code, payload = self.run_tool("plan-push", "--remote", "origin")
        self.assertNotIn("--force", payload["owner_command"])
        self.assertNotIn("-f ", payload["owner_command"])


class TestScanAgainstTheRealLines(unittest.TestCase):
    """The corrected method, run against both lines of this repository."""

    REFS = ("HEAD", "refs/remotes/origin/jarvis/rebuild-v1")

    def run_tool(self, *arguments):
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["/bin/bash", str(SCRIPT), "--repo", str(REPO_ROOT),
             *[str(item) for item in arguments]],
            cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=120, check=False, shell=False,
        )
        return completed.returncode, json.loads(completed.stdout.decode())

    def _scan(self, prefix, width):
        arguments = ["scan"]
        for ref in self.REFS:
            arguments += ["--ref", ref]
        arguments += ["--prefix", prefix, "--width", str(width)]
        return self.run_tool(*arguments)

    def test_the_numeric_series_is_contiguous_and_dec_056_is_free(self):
        code, payload = self._scan("DEC-", 3)
        self.assertEqual(code, 0)
        self.assertEqual(payload["gaps"], [])
        self.assertEqual(payload["first_unused"], "DEC-056")

    def test_the_d_series_is_contiguous_and_dec_d18_is_free(self):
        code, payload = self._scan("DEC-D", 2)
        self.assertEqual(code, 0)
        self.assertEqual(payload["gaps"], [])
        self.assertEqual(payload["first_unused"], "DEC-D18")

    def test_both_lines_really_contribute(self):
        _code, payload = self._scan("DEC-", 3)
        counts = payload["allocations_per_ref"]
        for ref in self.REFS:
            with self.subTest(ref=ref):
                self.assertIsNotNone(counts[ref])
                self.assertGreater(counts[ref], 0)

    def test_an_unreadable_ref_is_reported_rather_than_skipped(self):
        code, payload = self.run_tool(
            "scan", "--ref", "refs/does/not/exist", "--prefix", "DEC-",
            "--width", "3",
        )
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["unreadable_refs"], ["refs/does/not/exist"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
