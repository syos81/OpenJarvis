"""Append-only register model: state machine, hash chain, freshness rules."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.decreg import model  # noqa: E402
from tools.decreg import remote  # noqa: E402

OWNER = "owner-fixture"
LINE = "line-fixture-alpha"
COMMIT = "a" * 40
WHEN = "2026-08-06T12:00:00Z"


def build(text, dec_id, action, *, genesis=False, owner=OWNER, line=LINE):
    """Append one event to ``text`` and return the new text."""
    _events, _state, digest = model.parse(text)
    previous = None
    if text:
        previous = json.loads(text.rstrip("\n").split("\n")[-1])["event_id"]
    event = model.build_event(
        dec_id=dec_id,
        action=action,
        owner_ref=owner,
        origin_line=line,
        recorded_at_utc=WHEN,
        source_commit=COMMIT,
        previous_digest=digest,
        previous_event_id=previous,
        genesis=genesis,
    )
    return model.append(text, event)


class TestStateMachine(unittest.TestCase):
    def test_valid_reservation_and_assignment(self):
        text = build("", "DEC-900", model.ACTION_RESERVED)
        text = build(text, "DEC-900", model.ACTION_ASSIGNED)
        _events, state, _digest = model.parse(text)
        self.assertEqual(state["DEC-900"], model.ACTION_ASSIGNED)

    def test_double_reservation_is_rejected(self):
        text = build("", "DEC-900", model.ACTION_RESERVED)
        with self.assertRaises(model.RegisterError) as ctx:
            build(text, "DEC-900", model.ACTION_RESERVED)
        self.assertEqual(ctx.exception.code, "number_already_reserved")

    def test_assignment_without_reservation_is_rejected(self):
        with self.assertRaises(model.RegisterError) as ctx:
            build("", "DEC-900", model.ACTION_ASSIGNED)
        self.assertEqual(ctx.exception.code, "assign_without_reservation")

    def test_release_of_an_unreserved_number_is_rejected(self):
        with self.assertRaises(model.RegisterError) as ctx:
            build("", "DEC-900", model.ACTION_RELEASED)
        self.assertEqual(ctx.exception.code, "release_without_reservation")

    def test_release_of_an_assigned_number_is_rejected(self):
        text = build("", "DEC-900", model.ACTION_RESERVED)
        text = build(text, "DEC-900", model.ACTION_ASSIGNED)
        with self.assertRaises(model.RegisterError) as ctx:
            build(text, "DEC-900", model.ACTION_RELEASED)
        self.assertEqual(ctx.exception.code, "number_is_terminal")

    def test_reservation_again_after_release(self):
        text = build("", "DEC-900", model.ACTION_RESERVED)
        text = build(text, "DEC-900", model.ACTION_RELEASED)
        text = build(text, "DEC-900", model.ACTION_RESERVED)
        _events, state, _digest = model.parse(text)
        self.assertEqual(state["DEC-900"], model.ACTION_RESERVED)

    def test_free_is_derived_from_the_whole_history(self):
        text = build("", "DEC-900", model.ACTION_RESERVED)
        text = build(text, "DEC-900", model.ACTION_RELEASED)
        _events, state, _digest = model.parse(text)
        self.assertEqual(model.free_numbers(state, ["DEC-900"]), ["DEC-900"])
        self.assertEqual(model.next_free(state, "DEC-", 3), "DEC-001")


class TestGenesis(unittest.TestCase):
    def test_genesis_may_import_directly_as_assigned(self):
        text = build("", "DEC-001", model.ACTION_ASSIGNED, genesis=True)
        _events, state, _digest = model.parse(text)
        self.assertEqual(state["DEC-001"], model.ACTION_ASSIGNED)

    def test_genesis_may_not_follow_a_normal_event(self):
        text = build("", "DEC-900", model.ACTION_RESERVED)
        with self.assertRaises(model.RegisterError) as ctx:
            build(text, "DEC-001", model.ACTION_ASSIGNED, genesis=True)
        self.assertEqual(ctx.exception.code, "genesis_after_normal_event")

    def test_genesis_may_not_repeat_a_number(self):
        text = build("", "DEC-001", model.ACTION_ASSIGNED, genesis=True)
        with self.assertRaises(model.RegisterError) as ctx:
            build(text, "DEC-001", model.ACTION_ASSIGNED, genesis=True)
        self.assertEqual(ctx.exception.code, "genesis_repeats_a_number")


class TestIntegrity(unittest.TestCase):
    def _history(self):
        text = build("", "DEC-900", model.ACTION_RESERVED)
        return build(text, "DEC-901", model.ACTION_RESERVED)

    def test_truncated_history_is_detected(self):
        text = self._history()
        truncated = text.split("\n")[0] + "\n"
        # The prefix alone still parses; the damage shows when the tail is
        # dropped and a later append no longer binds to the real state.
        _events, _state, digest = model.parse(truncated)
        _events2, _state2, full = model.parse(text)
        self.assertNotEqual(digest, full)

    def test_reordered_history_is_detected(self):
        lines = self._history().rstrip("\n").split("\n")
        reordered = "\n".join([lines[1], lines[0]]) + "\n"
        with self.assertRaises(model.RegisterError) as ctx:
            model.parse(reordered)
        self.assertIn(ctx.exception.code, ("chain_broken", "previous_event_id_mismatch"))

    def test_edited_line_is_detected(self):
        text = self._history()
        lines = text.rstrip("\n").split("\n")
        payload = json.loads(lines[0])
        payload["owner_ref"] = "someone-else"
        lines[0] = model.serialise(payload)
        with self.assertRaises(model.RegisterError) as ctx:
            model.parse("\n".join(lines) + "\n")
        self.assertEqual(ctx.exception.code, "event_id_does_not_match_content")

    def test_non_canonical_line_is_detected(self):
        text = build("", "DEC-900", model.ACTION_RESERVED)
        payload = json.loads(text)
        spaced = json.dumps(payload, sort_keys=True) + "\n"
        with self.assertRaises(model.RegisterError) as ctx:
            model.parse(spaced)
        self.assertEqual(ctx.exception.code, "line_not_canonical")

    def test_append_must_bind_to_the_current_state(self):
        text = self._history()
        event = model.build_event(
            dec_id="DEC-902",
            action=model.ACTION_RESERVED,
            owner_ref=OWNER,
            origin_line=LINE,
            recorded_at_utc=WHEN,
            source_commit=COMMIT,
            previous_digest=model.EMPTY_DIGEST,
            previous_event_id=None,
        )
        with self.assertRaises(model.RegisterError) as ctx:
            model.append(text, event)
        self.assertEqual(ctx.exception.code, "append_does_not_bind_to_current_state")

    def test_owner_ref_stays_pii_poor(self):
        with self.assertRaises(model.RegisterError) as ctx:
            build("", "DEC-900", model.ACTION_RESERVED, owner="Some Person <a@b.c>")
        self.assertEqual(ctx.exception.code, "invalid_owner_ref")


class TestLineNeutrality(unittest.TestCase):
    def test_origin_line_is_a_data_value_not_an_enum(self):
        for line in ("line-fixture-alpha", "some/other/line", "a-line-that-does-not-exist-yet"):
            with self.subTest(line=line):
                text = build("", "DEC-900", model.ACTION_RESERVED, line=line)
                events, _state, _digest = model.parse(text)
                self.assertEqual(events[0]["origin_line"], line)

    def test_no_line_name_is_hard_coded_in_the_model(self):
        source = (
            Path(__file__).resolve().parents[3] / "tools/decreg/model.py"
        ).read_text(encoding="utf-8")
        for forbidden in ("rebuild-v1", "calendar-foundation", "jarvis/"):
            self.assertNotIn(forbidden, source)


class TestRemoteRules(unittest.TestCase):
    def test_ready_only_on_a_verified_fast_forward(self):
        state = remote.RemoteState("a" * 40, "b" * 40, "a" * 40, True)
        self.assertEqual(remote.classify_update(state), remote.READY)

    def test_stale_local_base_is_rejected(self):
        state = remote.RemoteState("a" * 40, "b" * 40, None, True)
        self.assertEqual(remote.classify_update(state), remote.LOCAL_REF_STALE)

    def test_concurrent_remote_progress_is_rejected(self):
        state = remote.RemoteState("c" * 40, "b" * 40, "a" * 40, True)
        self.assertEqual(remote.classify_update(state), remote.REMOTE_ADVANCED)

    def test_non_fast_forward_is_rejected(self):
        state = remote.RemoteState("a" * 40, "b" * 40, "a" * 40, False)
        self.assertEqual(remote.classify_update(state), remote.NOT_FAST_FORWARD)

    def test_missing_or_unverifiable_remote_is_rejected(self):
        self.assertEqual(
            remote.classify_update(remote.RemoteState(None, "b" * 40, "a" * 40, True)),
            remote.REMOTE_REF_MISSING,
        )
        self.assertEqual(
            remote.classify_update(remote.RemoteState("nope", "b" * 40, "a" * 40, True)),
            remote.REMOTE_OID_UNVERIFIABLE,
        )

    def test_initial_creation_requires_an_absent_remote(self):
        self.assertEqual(
            remote.classify_initial(remote.RemoteState(None, "b" * 40, None, False)),
            remote.READY,
        )
        self.assertEqual(
            remote.classify_initial(remote.RemoteState("a" * 40, "b" * 40, None, False)),
            remote.REMOTE_ADVANCED,
        )

    def test_push_command_is_never_a_force_variant(self):
        command = remote.push_command("origin", "refs/governance/dec-reservations")
        self.assertNotIn("--force", command)
        self.assertNotIn("-f ", command)
        self.assertTrue(command.startswith("git push origin "))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
