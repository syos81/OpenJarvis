"""Narrow, single use owner exception.

An exception is not a switch. It releases exactly one canonicalised command
in exactly one worktree, for a few minutes, once.

Storage layout below the owner controlled installation root::

    var/exceptions/pending/<nonce>.json   root owned, 0444, session readable
    var/exceptions/spent/                 root owned, 0733 + ACL deny delete_child

An exception is consumed by atomically creating ``spent/<nonce>`` with
``O_CREAT | O_EXCL``. The first creation wins; every later attempt fails with
``EEXIST``. The session can create markers but the ACL forbids removing them,
so a consumed exception cannot be revived from inside the guarded session.

Hard limits, none of them configurable from inside the session:

* the exception object is created only by the owner helper, running as root,
* ten minutes maximum regular validity,
* no wildcard, no command pattern, no permanent release, no reuse,
* an exception never applies to a guard integrity failure,
* a corrupt exception object blocks instead of being ignored.

Three questions are kept apart, because conflating them is what made an
unrelated object able to replace an unrelated deny:

*can it be read*      structural validation. Failure is corruption and blocks.
*does it apply here*  version bindings and expiry. Failure is a classification,
                      never an error, and never touches the decision.
*does it match*       worktree and command. Only asked of an object that
                      applies.

An expired or version foreign object is therefore not corrupt and not an
override candidate. It is recorded as diagnosis and changes nothing about the
decision that would have been reached without it.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
from pathlib import Path

from . import EXCEPTION_SCHEMA

#: Deny reason returned when an exception object cannot be trusted.
GUARD_EXCEPTION_CORRUPT = "GUARD_EXCEPTION_CORRUPT"

#: Schema of one non decision bearing observation record.
OBSERVATION_SCHEMA = "guard-observation-1"

EXCEPTION_FIELDS = (
    "command_canonical",
    "command_sha256",
    "created_at",
    "expires_at",
    "guard_version",
    "integrity_sha256",
    "nonce",
    "reason",
    "schema",
    "worktree_id",
)

#: The version bindings an exception object carries. Both are checked, and
#: neither is interpreted leniently: an object that does not state exactly the
#: schema and guard version being evaluated is not this guard's object.
#: Derived from what the loader actually compares, not from a naming guess.
VERSION_BINDING_FIELDS = ("guard_version", "schema")

#: Qualification of one structurally sound object. Only ``CANDIDATE`` may ever
#: become an override; everything else is diagnosis and nothing more.
CANDIDATE = "candidate"
EXPIRED = "expired"
VERSION_MISMATCH = "version_mismatch"
NOT_YET_VALID = "not_yet_valid"

#: Precedence when several qualifications apply at once. Version comes first:
#: the temporal fields of an object that does not belong to this guard version
#: are not ours to interpret, so calling such an object merely "expired" would
#: claim an understanding we do not have.
QUALIFICATION_PRECEDENCE = (VERSION_MISMATCH, NOT_YET_VALID, EXPIRED, CANDIDATE)

_NONCE_RE = re.compile(r"^[0-9a-f]{32,64}$")
_WHITESPACE = re.compile(r"\s+")


class ExceptionCorrupt(ValueError):
    """Raised when a stored exception object cannot be trusted.

    Reserved for objects that are *structurally* unusable. An object that is
    merely expired or merely version foreign is not corrupt: it is a
    well formed statement that does not apply here, and it never becomes this
    error.
    """


class Qualification:
    """Why one structurally sound object is, or is not, an override candidate."""

    __slots__ = ("primary", "applying", "age_seconds", "version_mismatches")

    def __init__(self, primary, applying, age_seconds, version_mismatches):
        self.primary = primary
        #: every qualification that applies, in precedence order
        self.applying = list(applying)
        self.age_seconds = age_seconds
        #: ``(field, expected, found)`` for every binding that does not match
        self.version_mismatches = list(version_mismatches)

    @property
    def is_candidate(self):
        return self.primary == CANDIDATE


def canonical_command(command):
    """Whitespace normalised form the owner and the guard both hash."""
    return _WHITESPACE.sub(" ", str(command)).strip()


def command_digest(command):
    return hashlib.sha256(canonical_command(command).encode("utf-8")).hexdigest()


def worktree_id(worktree):
    """Stable, non-personal identifier of a worktree."""
    resolved = str(Path(worktree).resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:32]


def integrity_digest(payload):
    """Digest over every field except ``integrity_sha256`` itself."""
    material = {
        key: payload[key] for key in EXCEPTION_FIELDS if key != "integrity_sha256"
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build(
    *,
    nonce,
    worktree,
    command,
    reason,
    created_at,
    ttl_seconds,
    guard_version,
):
    """Build a complete exception object. Used by the owner helper only."""
    payload = {
        "schema": EXCEPTION_SCHEMA,
        "nonce": str(nonce),
        "worktree_id": worktree_id(worktree),
        "command_canonical": canonical_command(command),
        "command_sha256": command_digest(command),
        "reason": str(reason),
        "created_at": int(created_at),
        "expires_at": int(created_at) + int(ttl_seconds),
        "guard_version": str(guard_version),
        "integrity_sha256": "",
    }
    payload["integrity_sha256"] = integrity_digest(payload)
    return payload


def structural_parse(raw_text, *, policy):
    """Validate everything that makes an object *usable at all*.

    This layer knows nothing about which guard version is running and nothing
    about the current time. It answers one question: is this a complete, self
    consistent, policy conforming exception object? Anything that fails here
    is corrupt and blocks, exactly as before.

    The version bindings and the expiry are deliberately *not* checked here.
    They decide whether a sound object applies, which is a different question
    from whether it can be read at all, and conflating the two is what let a
    version foreign object replace an unrelated deny.
    """
    try:
        payload = json.loads(raw_text)
    except ValueError as exc:
        raise ExceptionCorrupt("not_json") from exc
    if not isinstance(payload, dict):
        raise ExceptionCorrupt("not_object")
    if sorted(payload) != sorted(EXCEPTION_FIELDS):
        raise ExceptionCorrupt("field_set")
    if not _NONCE_RE.match(str(payload["nonce"])):
        raise ExceptionCorrupt("nonce")
    expected_nonce_length = int(policy.get("nonce_hex_length", 32))
    if len(str(payload["nonce"])) < expected_nonce_length:
        raise ExceptionCorrupt("nonce_too_short")
    if not re.match(r"^[0-9a-f]{64}$", str(payload["command_sha256"])):
        raise ExceptionCorrupt("command_sha256")
    if not re.match(r"^[0-9a-f]{32}$", str(payload["worktree_id"])):
        raise ExceptionCorrupt("worktree_id")
    canonical = canonical_command(payload["command_canonical"])
    if not canonical:
        raise ExceptionCorrupt("command_empty")
    if "*" in canonical or "?" in canonical:
        raise ExceptionCorrupt("wildcard_command")
    if payload["command_sha256"] != command_digest(canonical):
        raise ExceptionCorrupt("command_digest_mismatch")
    reason = str(payload["reason"]).strip()
    if len(reason) < int(policy.get("reason_min_length", 8)):
        raise ExceptionCorrupt("reason_missing")
    try:
        created_at = int(payload["created_at"])
        expires_at = int(payload["expires_at"])
    except (TypeError, ValueError) as exc:
        raise ExceptionCorrupt("timestamps") from exc
    if expires_at <= created_at:
        raise ExceptionCorrupt("expiry_not_after_creation")
    if expires_at - created_at > int(policy["max_ttl_seconds"]):
        raise ExceptionCorrupt("ttl_too_long")
    if integrity_digest(payload) != payload["integrity_sha256"]:
        raise ExceptionCorrupt("integrity_digest")
    return payload


def parse(raw_text, *, policy, guard_version, schema=EXCEPTION_SCHEMA):
    """Structural validation *plus* the version bindings.

    The strict form: it accepts only an object that is both readable and
    addressed to exactly this guard. It is what the gate uses to state that an
    object is fully qualified. The decision path deliberately does not use it,
    because a version foreign object must be classified, not raised over.
    """
    payload = structural_parse(raw_text, policy=policy)
    for field, expected, _found in version_bindings(
        payload, guard_version=guard_version, schema=schema
    ):
        raise ExceptionCorrupt(field if field != "schema" else "schema")
    return payload


def version_bindings(payload, *, guard_version, schema=EXCEPTION_SCHEMA):
    """Return ``(field, expected, found)`` for every binding that differs.

    Every declared binding must match exactly. There is no tolerant reading,
    no ordering of versions and no migration: an object that names another
    version is another guard's object, whether that version is older, newer or
    unknown.
    """
    expected_by_field = {"guard_version": str(guard_version), "schema": str(schema)}
    mismatches = []
    for field in VERSION_BINDING_FIELDS:
        expected = expected_by_field[field]
        found = str(payload.get(field, ""))
        if found != expected:
            mismatches.append((field, expected, found))
    return mismatches


def classify(payload, *, now, policy, guard_version, schema=EXCEPTION_SCHEMA):
    """Qualify one structurally sound object. Never raises.

    Temporal validity is the conjunction of three bounds, so it can only ever
    be stricter than any single one of them:

    * the object may not lie in the future at all,
    * it may not have reached its own ``expires_at``,
    * its age may not have reached the policy maximum.

    With the policy maximum at 600 seconds this is exactly
    ``0 <= now - created_at < 600``: an object is expired from second 600 on.
    """
    mismatches = version_bindings(payload, guard_version=guard_version, schema=schema)
    created_at = int(payload["created_at"])
    expires_at = int(payload["expires_at"])
    age = int(now) - created_at
    maximum = int(policy["max_ttl_seconds"])

    applying = []
    if mismatches:
        applying.append(VERSION_MISMATCH)
    if age < 0:
        applying.append(NOT_YET_VALID)
    elif int(now) >= expires_at or age >= maximum:
        applying.append(EXPIRED)
    if not applying:
        applying.append(CANDIDATE)

    order = {name: index for index, name in enumerate(QUALIFICATION_PRECEDENCE)}
    applying.sort(key=lambda name: order[name])
    return Qualification(applying[0], applying, age, mismatches)


def _claim(spent_dir, nonce):
    """Atomically claim ``nonce``. Returns ``True`` exactly once."""
    target = Path(spent_dir) / str(nonce)
    try:
        handle = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            return False
        return False
    try:
        os.close(handle)
    except OSError:  # pragma: no cover - close failure is not recoverable
        return False
    return True


class Observation:
    """One structurally sound object that is not an override candidate.

    Diagnosis only. It carries no decision weight, and it deliberately holds
    no command text, no reason text and no path — a digest, a classification
    and a number.
    """

    __slots__ = (
        "object_id",
        "object_sha256",
        "classification",
        "applying",
        "age_seconds",
        "version_mismatches",
        "guard_version",
    )

    def __init__(
        self,
        *,
        object_id,
        object_sha256,
        classification,
        applying,
        age_seconds,
        version_mismatches,
        guard_version,
    ):
        self.object_id = object_id
        self.object_sha256 = object_sha256
        self.classification = classification
        self.applying = list(applying)
        self.age_seconds = age_seconds
        self.version_mismatches = list(version_mismatches)
        self.guard_version = guard_version

    def record(self, *, captured_at):
        """The PII poor record. ``decision_effect`` is always ``False``."""
        return {
            "schema": OBSERVATION_SCHEMA,
            "object_id": str(self.object_id),
            "object_sha256": str(self.object_sha256),
            "classification": str(self.classification),
            "qualifications": sorted(self.applying),
            "age_seconds": int(self.age_seconds),
            "version_mismatches": [
                {"field": field, "expected": expected, "found": found}
                for field, expected, found in sorted(self.version_mismatches)
            ],
            "captured_at_utc": str(captured_at),
            "guard_version": str(self.guard_version),
            "decision_effect": False,
        }


class ExceptionOutcome:
    """Result of an exception lookup.

    ``observations`` never influences the decision. A caller that ignores it
    entirely must reach exactly the same decision as one that reads it.
    """

    __slots__ = ("granted", "reason_code", "nonce_digest", "observations")

    def __init__(self, granted, reason_code, nonce_digest="", observations=()):
        self.granted = granted
        self.reason_code = reason_code
        self.nonce_digest = nonce_digest
        self.observations = list(observations)


def consume(
    *,
    pending_dir,
    spent_dir,
    worktree,
    command,
    now,
    policy,
    guard_version,
    schema=EXCEPTION_SCHEMA,
):
    """Look for a valid exception and consume it atomically.

    Returns an :class:`ExceptionOutcome`. ``granted`` is only ``True`` when a
    matching, unexpired, previously unused exception was claimed by this call.

    A corrupt object anywhere in ``pending_dir`` raises
    :class:`ExceptionCorrupt`: the guard must not decide while the exception
    state is unknown.
    """
    pending = Path(pending_dir)
    if not pending.is_dir():
        return ExceptionOutcome(False, "exception_area_missing")
    try:
        # Sorted, so the outcome never depends on the order the file system
        # happens to hand out entries. This is the pre-existing deterministic
        # rule and it is kept: among several applicable objects the
        # lexicographically first one wins, and the claim below then settles
        # it atomically.
        candidates = sorted(pending.glob("*.json"))
    except OSError:
        raise ExceptionCorrupt("pending_unreadable")

    wanted_worktree = worktree_id(worktree)
    wanted_command = command_digest(command)
    observations = []
    granted_payload = None

    for candidate in candidates:
        try:
            raw = candidate.read_bytes()
        except OSError as exc:
            raise ExceptionCorrupt("unreadable") from exc
        # Structural failure still blocks. An object that cannot be read at
        # all leaves the exception state unknown, and the guard must not
        # decide while that is the case.
        payload = structural_parse(raw.decode("utf-8", "replace"), policy=policy)

        qualification = classify(
            payload,
            now=now,
            policy=policy,
            guard_version=guard_version,
            schema=schema,
        )
        if not qualification.is_candidate:
            # Diagnosis, and nothing else. Not matched against the command,
            # because an object that does not apply does not get to say
            # anything about the command either.
            observations.append(
                Observation(
                    object_id=str(payload["nonce"]),
                    object_sha256=hashlib.sha256(raw).hexdigest(),
                    classification=qualification.primary,
                    applying=qualification.applying,
                    age_seconds=qualification.age_seconds,
                    version_mismatches=qualification.version_mismatches,
                    guard_version=guard_version,
                )
            )
            continue

        if payload["worktree_id"] != wanted_worktree:
            continue
        if payload["command_sha256"] != wanted_command:
            continue
        granted_payload = payload
        break

    if granted_payload is None:
        # Byte identical to the outcome with no objects present at all: a non
        # candidate contributes no nonce digest and no reason of its own.
        return ExceptionOutcome(False, "no_exception", "", observations)

    nonce_digest = hashlib.sha256(
        str(granted_payload["nonce"]).encode("utf-8")
    ).hexdigest()[:16]
    if not _claim(spent_dir, granted_payload["nonce"]):
        return ExceptionOutcome(
            False, "exception_already_used", nonce_digest, observations
        )
    return ExceptionOutcome(True, "exception_consumed", nonce_digest, observations)
