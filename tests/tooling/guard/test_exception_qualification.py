"""B0d — an object that does not apply may not change the decision.

The defect this covers was observed in production: a version foreign object
lying in the pending area replaced the reason of an entirely unrelated deny
with ``GUARD_EXCEPTION_CORRUPT``. It did so because one function answered
three different questions at once — can this be read, does it apply here, does
it match — and raised on all of them alike.

Everything below is exercised with an injected clock. No test waits, and no
test touches the active installation or the historical evidence objects: those
are hashed read only and copied byte identically into a throwaway fixture
below the declared runtime fixture root.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.guard import _support  # noqa: E402
from tools.guard import EXCEPTION_SCHEMA, GUARD_VERSION  # noqa: E402
from tools.guard import decide  # noqa: E402
from tools.guard import observed as observed_module  # noqa: E402
from tools.guard import owner_exception  # noqa: E402
from tools.guard import rules as rules_module  # noqa: E402

REPO_ROOT = _support.REPO_ROOT
#: Declared throwaway fixture root. Gitignored runtime, never committed.
FIXTURE_ROOT = REPO_ROOT / ".gate-runtime" / "fixtures" / "exceptions"
#: The historical objects, read only. Never written, never re-activated.
HISTORICAL = Path.home() / "jarvis-guard-evidence"

POLICY = {"max_ttl_seconds": 600, "nonce_hex_length": 32, "reason_min_length": 8}
AMEND = "--am" + "end"
COMMAND = "git commit " + AMEND
CREATED = 1_000_000


def build_object(
    *,
    nonce,
    worktree,
    command=COMMAND,
    created_at=CREATED,
    ttl=600,
    guard_version=GUARD_VERSION,
    schema=EXCEPTION_SCHEMA,
    reason="a declared fixture reason",
):
    """Build a self consistent object, with the version fields free."""
    payload = owner_exception.build(
        nonce=nonce,
        worktree=worktree,
        command=command,
        reason=reason,
        created_at=created_at,
        ttl_seconds=ttl,
        guard_version=guard_version,
    )
    payload["schema"] = schema
    payload["integrity_sha256"] = ""
    payload["integrity_sha256"] = owner_exception.integrity_digest(payload)
    return payload


class FixtureArea(unittest.TestCase):
    """A throwaway pending/spent/observed area below the declared root."""

    def setUp(self):
        super().setUp()
        FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
        self.area = Path(tempfile.mkdtemp(prefix="qual-", dir=str(FIXTURE_ROOT)))
        self.addCleanup(shutil.rmtree, self.area, True)
        self.pending = self.area / "pending"
        self.spent = self.area / "spent"
        self.observed = self.area / "observed"
        for path in (self.pending, self.spent, self.observed):
            path.mkdir()
        self.worktree = self.area / "worktree"
        self.worktree.mkdir()

    def place(self, payload, *, name=None):
        target = self.pending / ((name or payload["nonce"]) + ".json")
        target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return target

    def consume(self, *, now, command=COMMAND):
        return owner_exception.consume(
            pending_dir=self.pending,
            spent_dir=self.spent,
            worktree=self.worktree,
            command=command,
            now=now,
            policy=POLICY,
            guard_version=GUARD_VERSION,
        )

    def qualify(self, payload, *, now):
        return owner_exception.classify(
            payload,
            now=now,
            policy=POLICY,
            guard_version=GUARD_VERSION,
        )


class TestExpiryBoundary(FixtureArea):
    """0 <= now - created_at < 600. Expired from second 600 on."""

    def _at(self, age):
        payload = build_object(nonce="a" * 32, worktree=self.worktree)
        return self.qualify(payload, now=CREATED + age)

    def test_age_zero_is_a_candidate(self):
        self.assertEqual(self._at(0).primary, owner_exception.CANDIDATE)

    def test_age_599_is_still_a_candidate(self):
        self.assertEqual(self._at(599).primary, owner_exception.CANDIDATE)

    def test_age_exactly_600_is_expired(self):
        """The boundary itself. One second earlier still releases."""
        self.assertEqual(self._at(600).primary, owner_exception.EXPIRED)

    def test_age_beyond_600_is_expired(self):
        self.assertEqual(self._at(601).primary, owner_exception.EXPIRED)
        self.assertEqual(self._at(86_400).primary, owner_exception.EXPIRED)

    def test_a_future_object_is_not_yet_valid(self):
        qualification = self._at(-1)
        self.assertEqual(qualification.primary, owner_exception.NOT_YET_VALID)
        self.assertEqual(qualification.age_seconds, -1)

    def test_a_short_lived_object_expires_at_its_own_bound(self):
        """The object's own expiry binds too; the strictest bound wins."""
        payload = build_object(nonce="b" * 32, worktree=self.worktree, ttl=60)
        self.assertEqual(
            self.qualify(payload, now=CREATED + 59).primary,
            owner_exception.CANDIDATE,
        )
        self.assertEqual(
            self.qualify(payload, now=CREATED + 60).primary,
            owner_exception.EXPIRED,
        )

    def test_the_age_is_reported_for_the_diagnosis(self):
        self.assertEqual(self._at(1234).age_seconds, 1234)

    def test_a_numeric_string_timestamp_is_normalised(self):
        payload = build_object(nonce="c" * 32, worktree=self.worktree)
        payload["created_at"] = str(payload["created_at"])
        payload["expires_at"] = str(payload["expires_at"])
        payload["integrity_sha256"] = ""
        payload["integrity_sha256"] = owner_exception.integrity_digest(payload)
        parsed = owner_exception.structural_parse(
            json.dumps(payload), policy=POLICY
        )
        self.assertEqual(
            self.qualify(parsed, now=CREATED).primary, owner_exception.CANDIDATE
        )

    def test_a_non_numeric_timestamp_is_corrupt_not_expired(self):
        payload = build_object(nonce="d" * 32, worktree=self.worktree)
        payload["created_at"] = "yesterday"
        payload["integrity_sha256"] = ""
        payload["integrity_sha256"] = owner_exception.integrity_digest(payload)
        with self.assertRaises(owner_exception.ExceptionCorrupt) as caught:
            owner_exception.structural_parse(json.dumps(payload), policy=POLICY)
        self.assertEqual(caught.exception.args[0], "timestamps")

    def test_a_missing_timestamp_is_corrupt(self):
        payload = build_object(nonce="e" * 32, worktree=self.worktree)
        del payload["created_at"]
        with self.assertRaises(owner_exception.ExceptionCorrupt) as caught:
            owner_exception.structural_parse(json.dumps(payload), policy=POLICY)
        self.assertEqual(caught.exception.args[0], "field_set")


class TestVersionSemantics(FixtureArea):
    def test_a_foreign_guard_version_is_a_mismatch_not_corruption(self):
        payload = build_object(
            nonce="a" * 32, worktree=self.worktree, guard_version="1.0.0"
        )
        # It parses: it is readable, it just is not ours.
        owner_exception.structural_parse(json.dumps(payload), policy=POLICY)
        qualification = self.qualify(payload, now=CREATED)
        self.assertEqual(qualification.primary, owner_exception.VERSION_MISMATCH)
        self.assertEqual(
            qualification.version_mismatches,
            [("guard_version", GUARD_VERSION, "1.0.0")],
        )

    def test_a_foreign_schema_is_a_mismatch(self):
        payload = build_object(
            nonce="b" * 32, worktree=self.worktree, schema="guard-exception-0"
        )
        qualification = self.qualify(payload, now=CREATED)
        self.assertEqual(qualification.primary, owner_exception.VERSION_MISMATCH)
        self.assertEqual(
            [field for field, _e, _f in qualification.version_mismatches],
            ["schema"],
        )

    def test_both_bindings_are_reported(self):
        payload = build_object(
            nonce="c" * 32,
            worktree=self.worktree,
            guard_version="0.9.0",
            schema="guard-exception-0",
        )
        qualification = self.qualify(payload, now=CREATED)
        self.assertEqual(
            [field for field, _e, _f in qualification.version_mismatches],
            ["guard_version", "schema"],
        )

    def test_a_newer_version_is_no_more_acceptable_than_an_older_one(self):
        for version in ("0.9.0", "1.2.0", "9.9.9", "unknown"):
            with self.subTest(version=version):
                payload = build_object(
                    nonce="d" * 32, worktree=self.worktree, guard_version=version
                )
                self.assertEqual(
                    self.qualify(payload, now=CREATED).primary,
                    owner_exception.VERSION_MISMATCH,
                )

    def test_a_missing_version_field_is_corrupt(self):
        payload = build_object(nonce="e" * 32, worktree=self.worktree)
        del payload["guard_version"]
        with self.assertRaises(owner_exception.ExceptionCorrupt):
            owner_exception.structural_parse(json.dumps(payload), policy=POLICY)

    def test_version_takes_precedence_over_expiry_in_the_classification(self):
        """A foreign object's clock is not ours to read."""
        payload = build_object(
            nonce="f" * 32, worktree=self.worktree, guard_version="1.0.0"
        )
        qualification = self.qualify(payload, now=CREATED + 100_000)
        self.assertEqual(qualification.primary, owner_exception.VERSION_MISMATCH)
        self.assertEqual(
            qualification.applying,
            [owner_exception.VERSION_MISMATCH, owner_exception.EXPIRED],
        )

    def test_no_object_is_ever_rewritten(self):
        payload = build_object(
            nonce="a" * 32, worktree=self.worktree, guard_version="1.0.0"
        )
        target = self.place(payload)
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        stat_before = target.stat().st_mtime_ns
        self.consume(now=CREATED)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before)
        self.assertEqual(target.stat().st_mtime_ns, stat_before)


class TestDecisionInvariance(FixtureArea):
    """The point of the whole block: the base decision must not move."""

    def setUp(self):
        super().setUp()
        self.rules = rules_module.load_rules(
            str(REPO_ROOT / "tools" / "guard" / "rules.json")
        )

    def context(self):
        return decide.Context(
            rules=self.rules,
            pending_dir=self.pending,
            spent_dir=self.spent,
            observed_dir=self.observed,
            guard_version=GUARD_VERSION,
            now=CREATED,
            exceptions_enabled=True,
        )

    def judge(self, command="git reset --hard HEAD~1"):
        return decide.decide(
            {
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(self.worktree),
            },
            self.context(),
        )

    def fingerprint(self, decision):
        return (
            decision.decision,
            decision.reason_code,
            decision.message,
            decision.detection_layer,
            decision.exception_nonce_digest,
        )

    def test_the_base_deny_is_the_reference(self):
        outcome = self.judge()
        self.assertEqual(outcome.decision, decide.DECISION_DENY)
        self.assertEqual(outcome.reason_code, "git_reset_hard")

    def test_an_expired_object_changes_nothing(self):
        reference = self.fingerprint(self.judge())
        self.place(
            build_object(
                nonce="a" * 32,
                worktree=self.worktree,
                command="git reset --hard HEAD~1",
                created_at=CREATED - 100_000,
            )
        )
        self.assertEqual(self.fingerprint(self.judge()), reference)

    def test_a_version_foreign_object_changes_nothing(self):
        """This is the observed production defect, as a test."""
        reference = self.fingerprint(self.judge())
        self.place(
            build_object(
                nonce="b" * 32,
                worktree=self.worktree,
                command="git reset --hard HEAD~1",
                guard_version="1.0.0",
            )
        )
        after = self.judge()
        self.assertEqual(self.fingerprint(after), reference)
        self.assertNotEqual(after.reason_code, owner_exception.GUARD_EXCEPTION_CORRUPT)

    def test_an_unrelated_invalid_object_changes_nothing(self):
        """It does not even concern this command, and never did."""
        reference = self.fingerprint(self.judge())
        self.place(
            build_object(
                nonce="c" * 32,
                worktree=self.worktree,
                command="git clean -fd",
                guard_version="1.0.0",
            )
        )
        self.assertEqual(self.fingerprint(self.judge()), reference)

    def test_many_invalid_objects_change_nothing_in_any_file_order(self):
        reference = self.fingerprint(self.judge())
        for index, name in enumerate(("zzz", "aaa", "mmm")):
            self.place(
                build_object(
                    nonce=f"{index}" * 32,
                    worktree=self.worktree,
                    command="git reset --hard HEAD~1",
                    guard_version="1.0.0" if index % 2 else GUARD_VERSION,
                    created_at=CREATED - 100_000,
                ),
                name=name,
            )
        self.assertEqual(self.fingerprint(self.judge()), reference)

    def test_a_valid_exception_still_releases(self):
        command = "git reset --hard HEAD~1"
        self.place(
            build_object(nonce="a" * 32, worktree=self.worktree, command=command)
        )
        outcome = self.judge(command)
        self.assertEqual(outcome.decision, decide.DECISION_ALLOW)
        self.assertEqual(outcome.reason_code, "owner_exception_consumed")

    def test_a_valid_exception_survives_an_expired_neighbour(self):
        command = "git reset --hard HEAD~1"
        self.place(
            build_object(
                nonce="0" * 32,
                worktree=self.worktree,
                command=command,
                created_at=CREATED - 100_000,
            ),
            name="aaa",
        )
        self.place(
            build_object(nonce="9" * 32, worktree=self.worktree, command=command),
            name="zzz",
        )
        self.assertEqual(self.judge(command).decision, decide.DECISION_ALLOW)

    def test_a_valid_exception_survives_a_version_foreign_neighbour(self):
        command = "git reset --hard HEAD~1"
        self.place(
            build_object(
                nonce="0" * 32,
                worktree=self.worktree,
                command=command,
                guard_version="1.0.0",
            ),
            name="aaa",
        )
        self.place(
            build_object(nonce="9" * 32, worktree=self.worktree, command=command),
            name="zzz",
        )
        self.assertEqual(self.judge(command).decision, decide.DECISION_ALLOW)

    def test_a_structurally_corrupt_object_still_blocks(self):
        """Counter test: the corrupt contract is not relaxed."""
        (self.pending / "broken.json").write_text("{ not json", encoding="utf-8")
        with self.assertRaises(owner_exception.ExceptionCorrupt):
            self.judge()

    def test_an_unwritable_diagnosis_area_changes_nothing(self):
        reference = self.fingerprint(self.judge())
        self.place(
            build_object(
                nonce="a" * 32,
                worktree=self.worktree,
                command="git reset --hard HEAD~1",
                guard_version="1.0.0",
            )
        )
        os.chmod(str(self.observed), 0o500)
        self.addCleanup(os.chmod, str(self.observed), 0o700)
        self.assertEqual(self.fingerprint(self.judge()), reference)


class TestObservationRecords(FixtureArea):
    def _observe(self, **overrides):
        self.place(build_object(nonce="a" * 32, worktree=self.worktree, **overrides))
        outcome = self.consume(now=CREATED + 100_000)
        observed_module.record_all(self.observed, outcome.observations)
        return outcome

    def test_the_record_states_that_it_carries_no_decision(self):
        self._observe(guard_version="1.0.0")
        records = observed_module.load_records(self.observed)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertIs(record["decision_effect"], False)
        self.assertEqual(record["classification"], owner_exception.VERSION_MISMATCH)
        self.assertEqual(record["guard_version"], GUARD_VERSION)
        self.assertIn("captured_at_utc", record)
        self.assertTrue(record["captured_at_utc"].endswith("Z"))

    def test_the_record_carries_the_digest_of_the_unmodified_object(self):
        self._observe(guard_version="1.0.0")
        record = observed_module.load_records(self.observed)[0]
        source = self.pending / ("a" * 32 + ".json")
        self.assertEqual(
            record["object_sha256"],
            hashlib.sha256(source.read_bytes()).hexdigest(),
        )

    def test_the_record_holds_no_command_and_no_reason_text(self):
        self._observe(guard_version="1.0.0")
        serialised = json.dumps(observed_module.load_records(self.observed))
        self.assertNotIn(AMEND, serialised)
        self.assertNotIn("declared fixture reason", serialised)

    def test_the_age_or_version_delta_is_recorded(self):
        self._observe(guard_version="1.0.0")
        record = observed_module.load_records(self.observed)[0]
        self.assertEqual(record["age_seconds"], 100_000)
        self.assertEqual(
            record["version_mismatches"],
            [{"field": "guard_version", "expected": GUARD_VERSION, "found": "1.0.0"}],
        )

    def test_seeing_the_same_object_again_writes_nothing_new(self):
        outcome = self._observe(guard_version="1.0.0")
        source = self.pending / ("a" * 32 + ".json")
        before = source.stat().st_mtime_ns
        written = observed_module.record_all(self.observed, outcome.observations)
        self.assertEqual(written, 0)
        self.assertEqual(len(observed_module.load_records(self.observed)), 1)
        self.assertEqual(source.stat().st_mtime_ns, before)

    def test_recording_never_removes_or_moves_the_object(self):
        self._observe(guard_version="1.0.0")
        self.assertTrue((self.pending / ("a" * 32 + ".json")).is_file())
        self.assertEqual(len(list(self.pending.glob("*.json"))), 1)

    def test_a_missing_area_records_nothing_and_raises_nothing(self):
        self.place(
            build_object(
                nonce="a" * 32, worktree=self.worktree, guard_version="1.0.0"
            )
        )
        outcome = self.consume(now=CREATED)
        self.assertEqual(
            observed_module.record_all(self.area / "nowhere", outcome.observations),
            0,
        )


class TestHistoricalObjects(FixtureArea):
    """The two real objects, copied byte identically. Originals untouched."""

    def setUp(self):
        super().setUp()
        if not HISTORICAL.is_dir():
            self.skipTest("historical evidence directory is not present")
        self.originals = sorted(HISTORICAL.glob("*.json"))
        if not self.originals:
            self.skipTest("no historical evidence objects present")
        self.before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.originals
        }

    def test_the_copies_are_byte_identical(self):
        for original in self.originals:
            target = self.pending / original.name
            shutil.copyfile(original, target)
            self.assertEqual(
                hashlib.sha256(target.read_bytes()).hexdigest(),
                self.before[original.name],
            )

    def test_they_are_version_foreign_and_expired_but_not_corrupt(self):
        for original in self.originals:
            with self.subTest(object=original.name):
                payload = owner_exception.structural_parse(
                    original.read_text(encoding="utf-8"), policy=POLICY
                )
                # The clock is derived from the object itself, so the test
                # neither waits nor depends on the wall clock.
                qualification = self.qualify(
                    payload, now=int(payload["created_at"]) + 100_000
                )
                self.assertEqual(
                    qualification.primary, owner_exception.VERSION_MISMATCH
                )
                self.assertIn(owner_exception.EXPIRED, qualification.applying)

    def test_they_release_nothing_and_change_no_decision(self):
        for original in self.originals:
            shutil.copyfile(original, self.pending / original.name)
        latest = max(
            int(owner_exception.structural_parse(
                original.read_text(encoding="utf-8"), policy=POLICY
            )["created_at"])
            for original in self.originals
        )
        outcome = self.consume(now=latest + 100_000)
        self.assertFalse(outcome.granted)
        self.assertEqual(outcome.reason_code, "no_exception")
        self.assertEqual(outcome.nonce_digest, "")
        self.assertEqual(len(outcome.observations), len(self.originals))

    def test_no_test_writes_into_the_historical_area(self):
        for original in self.originals:
            with self.subTest(object=original.name):
                self.assertEqual(
                    hashlib.sha256(original.read_bytes()).hexdigest(),
                    self.before[original.name],
                )

    def test_no_symlink_into_the_historical_area_is_used(self):
        source = Path(__file__).read_text(encoding="utf-8")
        # Assembled, so the assertion cannot match itself.
        forbidden = "os." + "sym" + "link"
        self.assertNotIn(forbidden, source)
        self.assertIn("shutil.copyfile", source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
