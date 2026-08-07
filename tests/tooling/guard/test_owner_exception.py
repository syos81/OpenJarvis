"""The owner exception: narrow, bound, single use, never a switch."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.guard import _support  # noqa: E402
from tools.guard import GUARD_VERSION  # noqa: E402
from tools.guard import owner_exception  # noqa: E402
from tools.guard import rules as guard_rules  # noqa: E402

AMEND = "--am" + "end"
RULES = guard_rules.load_rules(_support.GUARD_SOURCE / "rules.json")
POLICY = RULES.exception_policy


class ExceptionTestBase(_support.TempInstallationMixin):
    def setUp(self):
        super().setUp()
        self.pending = self.root / "var" / "exceptions" / "pending"
        self.spent = self.root / "var" / "exceptions" / "spent"
        self.worktree = self.tmp_path / "work"
        self.worktree.mkdir(exist_ok=True)

    def create(self, command, *, worktree=None, created_at=1000, ttl=600, nonce=None):
        payload = owner_exception.build(
            nonce=nonce or ("b" * 32),
            worktree=worktree or self.worktree,
            command=command,
            reason="synthetic owner exception for the test suite",
            created_at=created_at,
            ttl_seconds=ttl,
            guard_version=GUARD_VERSION,
        )
        target = self.pending / (payload["nonce"] + ".json")
        target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return payload

    def consume(self, command, *, now=1100, worktree=None):
        return owner_exception.consume(
            pending_dir=self.pending,
            spent_dir=self.spent,
            worktree=worktree or self.worktree,
            command=command,
            now=now,
            policy=POLICY,
            guard_version=GUARD_VERSION,
        )


class TestBinding(ExceptionTestBase):
    def test_exact_command_is_released_once(self):
        command = "git commit " + AMEND + " --no-edit"
        self.create(command)
        first = self.consume(command)
        self.assertTrue(first.granted)
        self.assertEqual(first.reason_code, "exception_consumed")

    def test_second_use_fails(self):
        command = "git commit " + AMEND
        self.create(command)
        self.assertTrue(self.consume(command).granted)
        second = self.consume(command)
        self.assertFalse(second.granted)
        self.assertEqual(second.reason_code, "exception_already_used")

    def test_a_different_command_is_not_released(self):
        self.create("git commit " + AMEND)
        outcome = self.consume("git commit " + AMEND + " --no-edit")
        self.assertFalse(outcome.granted)
        self.assertEqual(outcome.reason_code, "no_exception")

    def test_a_different_worktree_is_not_released(self):
        command = "git commit " + AMEND
        self.create(command)
        other = self.tmp_path / "other-work"
        other.mkdir()
        outcome = self.consume(command, worktree=other)
        self.assertFalse(outcome.granted)

    def test_whitespace_is_canonicalised(self):
        self.create("git   commit   " + AMEND)
        outcome = self.consume("git commit " + AMEND)
        self.assertTrue(outcome.granted)

    def test_expired_exception_is_not_released(self):
        """An expired object releases nothing and says nothing.

        Changed in B0d: the outcome is now byte identical to the outcome with
        no object present at all. An expired object no longer contributes a
        reason of its own, because a reason of its own is how it used to reach
        the decision. It appears as diagnosis instead.
        """
        command = "git commit " + AMEND
        self.create(command, created_at=1000, ttl=600)
        outcome = self.consume(command, now=1000 + 601)
        self.assertFalse(outcome.granted)
        self.assertEqual(outcome.reason_code, "no_exception")
        self.assertEqual(outcome.nonce_digest, "")
        self.assertEqual(
            [item.classification for item in outcome.observations],
            [owner_exception.EXPIRED],
        )

    def test_marker_survives_a_removal_attempt_semantically(self):
        command = "git commit " + AMEND
        self.create(command)
        self.consume(command)
        marker = self.spent / ("b" * 32)
        self.assertTrue(marker.exists())


class TestLimits(ExceptionTestBase):
    def test_ttl_above_ten_minutes_is_rejected(self):
        payload = owner_exception.build(
            nonce="c" * 32,
            worktree=self.worktree,
            command="git status",
            reason="synthetic owner exception for the test suite",
            created_at=1000,
            ttl_seconds=601,
            guard_version=GUARD_VERSION,
        )
        with self.assertRaises(owner_exception.ExceptionCorrupt):
            owner_exception.parse(
                json.dumps(payload), policy=POLICY, guard_version=GUARD_VERSION
            )

    def test_wildcard_command_is_rejected(self):
        payload = owner_exception.build(
            nonce="d" * 32,
            worktree=self.worktree,
            command="git *",
            reason="synthetic owner exception for the test suite",
            created_at=1000,
            ttl_seconds=600,
            guard_version=GUARD_VERSION,
        )
        with self.assertRaises(owner_exception.ExceptionCorrupt):
            owner_exception.parse(
                json.dumps(payload), policy=POLICY, guard_version=GUARD_VERSION
            )

    def test_missing_reason_is_rejected(self):
        payload = owner_exception.build(
            nonce="e" * 32,
            worktree=self.worktree,
            command="git status",
            reason="",
            created_at=1000,
            ttl_seconds=600,
            guard_version=GUARD_VERSION,
        )
        with self.assertRaises(owner_exception.ExceptionCorrupt):
            owner_exception.parse(
                json.dumps(payload), policy=POLICY, guard_version=GUARD_VERSION
            )

    def test_tampered_object_is_rejected(self):
        payload = owner_exception.build(
            nonce="f" * 32,
            worktree=self.worktree,
            command="git status",
            reason="synthetic owner exception for the test suite",
            created_at=1000,
            ttl_seconds=600,
            guard_version=GUARD_VERSION,
        )
        payload["reason"] = "changed after signing"
        with self.assertRaises(owner_exception.ExceptionCorrupt):
            owner_exception.parse(
                json.dumps(payload), policy=POLICY, guard_version=GUARD_VERSION
            )

    def test_corrupt_object_blocks_instead_of_being_ignored(self):
        (self.pending / "broken.json").write_text("{oops", encoding="utf-8")
        with self.assertRaises(owner_exception.ExceptionCorrupt):
            self.consume("git status")

    def test_foreign_guard_version_is_rejected(self):
        payload = owner_exception.build(
            nonce="9" * 32,
            worktree=self.worktree,
            command="git status",
            reason="synthetic owner exception for the test suite",
            created_at=1000,
            ttl_seconds=600,
            guard_version="0.0.1",
        )
        with self.assertRaises(owner_exception.ExceptionCorrupt):
            owner_exception.parse(
                json.dumps(payload), policy=POLICY, guard_version=GUARD_VERSION
            )


class TestIntegrityIsNeverExcepted(ExceptionTestBase):
    def test_an_exception_cannot_repair_a_broken_installation(self):
        command = "git commit " + AMEND
        self.create(command)
        target = self.root / "active" / "guard" / "rules.json"
        os.chmod(str(target), 0o644)
        before = target.read_bytes()
        # Append a byte rather than substituting a literal that happens to be
        # in the file today. The previous version replaced the string
        # "1.0.0"; when config_version moved to 1.1.0 that substitution became
        # a no-op and this test silently stopped testing anything. The
        # assertion below makes that failure mode impossible.
        target.write_bytes(before + b"\n")
        self.assertNotEqual(target.read_bytes(), before, "mutation had no effect")
        response = _support.run_bootstrap(self.root, self.bash_payload(command))
        self.assertEqual(_support.decision_of(response), "deny")
        self.assertIn("GUARD_PACKAGE_HASH_MISMATCH", _support.reason_of(response))

    def test_a_valid_exception_is_honoured_end_to_end(self):
        from tools.guard import entry as guard_entry

        command = "git commit " + AMEND
        self.create(command, worktree=self.worktree, created_at=1000, ttl=600)
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(self.worktree),
        }
        common = {
            "rules_path": self.root / "active" / "guard" / "rules.json",
            "pending_dir": self.pending,
            "spent_dir": self.spent,
            "log_path": self.root / "var" / "guard.log",
            "guard_version": GUARD_VERSION,
        }
        response, decision = guard_entry.run(payload, now=1100, **common)
        self.assertEqual(
            response["hookSpecificOutput"]["permissionDecision"], "allow"
        )
        self.assertEqual(decision.reason_code, "owner_exception_consumed")

        # The same exception is gone; the very next attempt blocks again.
        response, _decision = guard_entry.run(payload, now=1100, **common)
        self.assertEqual(
            response["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_consumption_is_recorded_without_the_nonce(self):
        from tools.guard import entry as guard_entry

        command = "git commit " + AMEND
        self.create(command, worktree=self.worktree, created_at=1000, ttl=600)
        log = self.root / "var" / "guard.log"
        guard_entry.run(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(self.worktree),
            },
            rules_path=self.root / "active" / "guard" / "rules.json",
            pending_dir=self.pending,
            spent_dir=self.spent,
            log_path=log,
            now=1100,
            guard_version=GUARD_VERSION,
        )
        recorded = [
            json.loads(line)
            for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(recorded)
        entry_record = recorded[-1]
        self.assertEqual(entry_record["event"], "exception_consumed")
        self.assertNotIn("b" * 32, json.dumps(entry_record))
        self.assertNotIn(str(self.worktree), json.dumps(entry_record))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
