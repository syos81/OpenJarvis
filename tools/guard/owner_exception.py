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

_NONCE_RE = re.compile(r"^[0-9a-f]{32,64}$")
_WHITESPACE = re.compile(r"\s+")


class ExceptionCorrupt(ValueError):
    """Raised when a stored exception object cannot be trusted."""


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


def parse(raw_text, *, policy, guard_version):
    """Parse and structurally validate one exception object.

    Raises :class:`ExceptionCorrupt` for anything that is not a complete,
    self consistent, policy conforming object.
    """
    try:
        payload = json.loads(raw_text)
    except ValueError as exc:
        raise ExceptionCorrupt("not_json") from exc
    if not isinstance(payload, dict):
        raise ExceptionCorrupt("not_object")
    if sorted(payload) != sorted(EXCEPTION_FIELDS):
        raise ExceptionCorrupt("field_set")
    if payload["schema"] != EXCEPTION_SCHEMA:
        raise ExceptionCorrupt("schema")
    if payload["guard_version"] != guard_version:
        raise ExceptionCorrupt("guard_version")
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


class ExceptionOutcome:
    """Result of an exception lookup."""

    __slots__ = ("granted", "reason_code", "nonce_digest")

    def __init__(self, granted, reason_code, nonce_digest=""):
        self.granted = granted
        self.reason_code = reason_code
        self.nonce_digest = nonce_digest


def consume(
    *,
    pending_dir,
    spent_dir,
    worktree,
    command,
    now,
    policy,
    guard_version,
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
        candidates = sorted(pending.glob("*.json"))
    except OSError:
        raise ExceptionCorrupt("pending_unreadable")

    wanted_worktree = worktree_id(worktree)
    wanted_command = command_digest(command)
    matched = None
    for candidate in candidates:
        try:
            raw = candidate.read_text(encoding="utf-8")
        except OSError as exc:
            raise ExceptionCorrupt("unreadable") from exc
        payload = parse(raw, policy=policy, guard_version=guard_version)
        if payload["worktree_id"] != wanted_worktree:
            continue
        if payload["command_sha256"] != wanted_command:
            continue
        if int(payload["expires_at"]) <= int(now):
            matched = matched or ("expired", payload)
            continue
        if int(payload["created_at"]) > int(now) + 60:
            matched = matched or ("not_yet_valid", payload)
            continue
        matched = ("valid", payload)
        break

    if matched is None:
        return ExceptionOutcome(False, "no_exception")
    state, payload = matched
    nonce_digest = hashlib.sha256(
        str(payload["nonce"]).encode("utf-8")
    ).hexdigest()[:16]
    if state != "valid":
        return ExceptionOutcome(False, "exception_" + state, nonce_digest)
    if not _claim(spent_dir, payload["nonce"]):
        return ExceptionOutcome(False, "exception_already_used", nonce_digest)
    return ExceptionOutcome(True, "exception_consumed", nonce_digest)
