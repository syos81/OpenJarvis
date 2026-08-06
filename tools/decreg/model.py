"""Append-only event model of the decision number register.

One line is one event. The file is only ever appended to; an existing line is
never edited, reordered or removed. Every line binds itself to the complete
preceding state through a hash chain, so truncation, reordering and silent
edits are detectable without trusting the transport.

State machine, evaluated exclusively from the full history:

    free | released  -> reserved
    reserved         -> assigned
    reserved         -> released
    assigned         -> terminal

A direct ``assigned`` without a preceding ``reserved`` is rejected. The only
exception is the genesis block, the contiguous prefix of events that imports
the mechanically proven existing allocations of both lines; those numbers
were allocated long before this register existed and are marked as imports
rather than given invented owners or timestamps.

``origin_line`` is a **data value**, never a schema enum: the checker must
stay usable for any line, including ones that do not exist yet.
"""

from __future__ import annotations

import hashlib
import json
import re

from . import SCHEMA_VERSION

ACTION_RESERVED = "reserved"
ACTION_ASSIGNED = "assigned"
ACTION_RELEASED = "released"
ACTIONS = (ACTION_RESERVED, ACTION_ASSIGNED, ACTION_RELEASED)

#: Terminal states. A terminal number never leaves its state again.
TERMINAL_STATES = (ACTION_ASSIGNED,)

EVENT_FIELDS = (
    "action",
    "dec_id",
    "event_id",
    "genesis",
    "origin_line",
    "owner_ref",
    "previous_digest",
    "previous_event_id",
    "recorded_at_utc",
    "schema_version",
    "source_commit",
)
GENESIS_OPTIONAL_FIELDS = ("import_note", "original_file")

_DEC_ID_RE = re.compile(r"^DEC-(?:\d{3}|D\d{2})$")
_EVENT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
#: A stable, PII poor owner identifier. No address, no personal name.
_OWNER_RE = re.compile(r"^[a-z][a-z0-9-]{2,31}$")

#: The empty register state, before the first line.
EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


class RegisterError(ValueError):
    """Raised with a machine readable code for every rejected register."""

    def __init__(self, code, detail="", line_number=None):
        self.code = code
        self.detail = detail
        self.line_number = line_number
        location = f" (line {line_number})" if line_number else ""
        super().__init__(f"{code}{location}: {detail}" if detail else code)


def chain_digest(previous_digest, line):
    """Digest binding one serialised line to the complete preceding state."""
    material = previous_digest.encode("ascii") + b"\n" + line.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def serialise(event):
    """Canonical one line serialisation. Sorted keys, no spaces."""
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def event_identity(event):
    """Deterministic event id derived from the event's own content."""
    material = {key: event[key] for key in EVENT_FIELDS if key != "event_id"}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _validate_shape(event, line_number):
    if not isinstance(event, dict):
        raise RegisterError("event_not_an_object", line_number=line_number)
    known = set(EVENT_FIELDS) | set(GENESIS_OPTIONAL_FIELDS)
    unknown = sorted(set(event) - known)
    if unknown:
        raise RegisterError("unknown_field", ",".join(unknown), line_number)
    missing = sorted(set(EVENT_FIELDS) - set(event))
    if missing:
        raise RegisterError("missing_field", ",".join(missing), line_number)
    if event["schema_version"] != SCHEMA_VERSION:
        raise RegisterError("unsupported_schema_version", line_number=line_number)
    if not _DEC_ID_RE.match(str(event["dec_id"])):
        raise RegisterError("invalid_dec_id", str(event["dec_id"]), line_number)
    if event["action"] not in ACTIONS:
        raise RegisterError("invalid_action", str(event["action"]), line_number)
    if not _EVENT_ID_RE.match(str(event["event_id"])):
        raise RegisterError("invalid_event_id", line_number=line_number)
    if not _OWNER_RE.match(str(event["owner_ref"])):
        raise RegisterError("invalid_owner_ref", line_number=line_number)
    if not str(event["origin_line"]).strip():
        raise RegisterError("origin_line_missing", line_number=line_number)
    if not _UTC_RE.match(str(event["recorded_at_utc"])):
        raise RegisterError("invalid_timestamp", line_number=line_number)
    if not isinstance(event["genesis"], bool):
        raise RegisterError("genesis_not_boolean", line_number=line_number)
    if not _DIGEST_RE.match(str(event["previous_digest"])):
        raise RegisterError("invalid_previous_digest", line_number=line_number)
    source = str(event["source_commit"])
    if not _COMMIT_RE.match(source):
        raise RegisterError("invalid_source_commit", source, line_number)
    if not event["genesis"] and set(event) & set(GENESIS_OPTIONAL_FIELDS):
        raise RegisterError("genesis_field_on_normal_event", line_number=line_number)
    if event["event_id"] != event_identity(event):
        raise RegisterError("event_id_does_not_match_content", line_number=line_number)


def _validate_transition(state, event, line_number):
    dec_id = event["dec_id"]
    action = event["action"]
    current = state.get(dec_id)

    if event["genesis"]:
        # The genesis block imports numbers that were allocated before this
        # register existed. It may only ever add, never re-state.
        if current is not None:
            raise RegisterError("genesis_repeats_a_number", dec_id, line_number)
        if action != ACTION_ASSIGNED:
            raise RegisterError("genesis_action_not_assigned", dec_id, line_number)
        return

    if current in TERMINAL_STATES:
        raise RegisterError("number_is_terminal", dec_id, line_number)
    if action == ACTION_RESERVED:
        if current not in (None, ACTION_RELEASED):
            raise RegisterError("number_already_reserved", dec_id, line_number)
        return
    if action == ACTION_ASSIGNED:
        if current != ACTION_RESERVED:
            raise RegisterError("assign_without_reservation", dec_id, line_number)
        return
    if current != ACTION_RESERVED:
        raise RegisterError("release_without_reservation", dec_id, line_number)


def parse(text):
    """Parse and fully validate a register file.

    Returns ``(events, state, digest)``. ``state`` maps a decision id to its
    current action; ``digest`` is the chain digest of the whole file and is
    what a later append must bind to.
    """
    events = []
    state = {}
    digest = EMPTY_DIGEST
    genesis_open = True

    raw_lines = text.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines = raw_lines[:-1]

    previous_event_id = None
    for index, line in enumerate(raw_lines, start=1):
        if not line.strip():
            raise RegisterError("blank_line", line_number=index)
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise RegisterError("line_not_json", str(exc)[:60], index) from exc
        _validate_shape(event, index)

        if serialise(event) != line:
            raise RegisterError("line_not_canonical", line_number=index)
        if event["previous_digest"] != digest:
            raise RegisterError("chain_broken", line_number=index)
        if event["previous_event_id"] != previous_event_id:
            raise RegisterError("previous_event_id_mismatch", line_number=index)

        if not event["genesis"]:
            genesis_open = False
        elif not genesis_open:
            raise RegisterError("genesis_after_normal_event", line_number=index)

        _validate_transition(state, event, index)
        state[event["dec_id"]] = event["action"]
        digest = chain_digest(digest, line)
        previous_event_id = event["event_id"]
        events.append(event)

    return events, state, digest


def build_event(
    *,
    dec_id,
    action,
    owner_ref,
    origin_line,
    recorded_at_utc,
    source_commit,
    previous_digest,
    previous_event_id,
    genesis=False,
    original_file=None,
    import_note=None,
):
    """Build one complete, self consistent event."""
    event = {
        "action": action,
        "dec_id": dec_id,
        "event_id": "",
        "genesis": bool(genesis),
        "origin_line": origin_line,
        "owner_ref": owner_ref,
        "previous_digest": previous_digest,
        "previous_event_id": previous_event_id,
        "recorded_at_utc": recorded_at_utc,
        "schema_version": SCHEMA_VERSION,
        "source_commit": source_commit,
    }
    if genesis:
        if original_file is not None:
            event["original_file"] = original_file
        if import_note is not None:
            event["import_note"] = import_note
    event["event_id"] = event_identity(event)
    return event


def append(text, event):
    """Return the register text with ``event`` appended. Never rewrites.

    The result is fully validated before it is returned: an event that would
    make the register invalid — a forbidden transition, a malformed field, a
    broken chain — is refused here rather than discovered on a later read.
    """
    _, _, digest = parse(text)
    if event["previous_digest"] != digest:
        raise RegisterError("append_does_not_bind_to_current_state")
    line = serialise(event)
    candidate = (text + line + "\n") if text else (line + "\n")
    parse(candidate)
    return candidate


def free_numbers(state, candidates):
    """Numbers from ``candidates`` that are free per the full history."""
    return sorted(
        dec_id
        for dec_id in candidates
        if state.get(dec_id) in (None, ACTION_RELEASED)
    )


def next_free(state, prefix, width, limit=999):
    """Lowest unused number of a series, derived from the history alone."""
    for number in range(1, limit + 1):
        dec_id = f"{prefix}{number:0{width}d}"
        if state.get(dec_id) in (None, ACTION_RELEASED):
            return dec_id
    return None
