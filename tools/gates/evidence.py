"""Allowlist based, PII safe evidence and raw log integrity.

There are exactly two evidence classes:

* **Raw logs** may contain the complete tool output. They live only in the
  gitignored runtime area, get restrictive file permissions and are never
  echoed, quoted or committed.
* **Sanitized evidence** is built field by field from a closed allowlist.
  There is no free text and no automatic "rest" area; an unknown field is an
  error, not a warning.

The SHA-256 of a raw log is the only bridge between the two: it proves local
raw log identity without making the raw log itself shareable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from . import EVIDENCE_SCHEMA_VERSION
from . import sanitize
from . import statuses

#: Closed allowlist. Every field is mandatory; unknown fields are rejected.
ALLOWED_FIELDS = (
    "schema_version",
    "run_id",
    "block",
    "phase",
    "commit",
    "manifest_digest",
    "engine_version",
    "status",
    "check_ids",
    "reason_codes",
    "baseline_commit",
    "cause_signature_digest",
    "cache_state",
    "platform_class",
    "raw_log_sha256",
    "started_at",
    "finished_at",
)

CACHE_STATES = ("not_used", "hit", "miss", "mixed")

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_PLATFORM_RE = re.compile(r"^[a-z0-9]+/[a-z0-9_]+/[0-9.]+$")


class EvidenceSchemaError(ValueError):
    """Raised for a field outside the allowlist or with an invalid value."""


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_raw_log(path, content: str) -> str:
    """Write a raw log with restrictive permissions and return its SHA-256."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(
        str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
    )
    try:
        os.write(handle, content.encode("utf-8", "replace"))
    finally:
        os.close(handle)
    try:
        os.chmod(str(target), 0o600)
    except OSError:  # pragma: no cover - platform without permission support
        pass
    return sha256_file(target)


def verify_raw_log(path, expected_digest):
    """Check a raw log against its recorded digest.

    Returns ``(ok, reason_code)``. Detects a missing digest, a malformed
    digest, a missing raw log and any later manipulation.
    """
    if expected_digest is None or expected_digest == "":
        return False, "raw_log_digest_missing"
    if not isinstance(expected_digest, str) or not _HEX64_RE.match(
        expected_digest
    ):
        return False, "raw_log_digest_malformed"
    target = Path(path)
    if not target.is_file():
        return False, "raw_log_absent"
    if sha256_file(target) != expected_digest:
        return False, "raw_log_digest_mismatch"
    return True, "raw_log_verified"


def _require(condition, message):
    if not condition:
        raise EvidenceSchemaError(message)


def _check_str_list(name, value, pattern=None):
    _require(isinstance(value, list), f"{name} must be a list")
    for item in value:
        _require(isinstance(item, str), f"{name} must contain strings")
        if pattern is not None:
            _require(bool(pattern.match(item)), f"{name} entry invalid: {item}")
    _require(value == sorted(value), f"{name} must be sorted")
    _require(len(value) == len(set(value)), f"{name} must not repeat entries")


def validate_evidence(evidence):
    """Validate a sanitized evidence record against the closed allowlist."""
    _require(isinstance(evidence, dict), "evidence must be an object")
    unknown = sorted(set(evidence) - set(ALLOWED_FIELDS))
    _require(not unknown, f"unknown evidence field(s): {', '.join(unknown)}")
    missing = sorted(set(ALLOWED_FIELDS) - set(evidence))
    _require(not missing, f"missing evidence field(s): {', '.join(missing)}")

    _require(
        evidence["schema_version"] == EVIDENCE_SCHEMA_VERSION,
        "unsupported evidence schema_version",
    )
    _require(
        isinstance(evidence["run_id"], str)
        and re.match(r"^[0-9a-f]{32,64}$", evidence["run_id"]),
        "run_id must be a hex token of at least 32 characters",
    )
    for name in ("block", "phase"):
        _require(
            isinstance(evidence[name], str) and _ID_RE.match(evidence[name]),
            f"{name} must be a plain identifier",
        )
    _require(
        isinstance(evidence["commit"], str)
        and _HEX40_RE.match(evidence["commit"]),
        "commit must be a full hex commit id",
    )
    _require(
        isinstance(evidence["manifest_digest"], str)
        and _HEX64_RE.match(evidence["manifest_digest"]),
        "manifest_digest must be a sha256 hex digest",
    )
    _require(
        isinstance(evidence["engine_version"], str)
        and re.match(r"^\d+\.\d+\.\d+$", evidence["engine_version"]),
        "engine_version must be semantic",
    )
    _require(
        evidence["status"] in statuses.ALL_STATUSES,
        "status must be one of the five gate results",
    )
    _check_str_list("check_ids", evidence["check_ids"], _ID_RE)
    _check_str_list("reason_codes", evidence["reason_codes"], _ID_RE)
    baseline_commit = evidence["baseline_commit"]
    _require(
        baseline_commit is None
        or (
            isinstance(baseline_commit, str)
            and _HEX40_RE.match(baseline_commit)
        ),
        "baseline_commit must be null or a full hex commit id",
    )
    _check_str_list(
        "cause_signature_digest", evidence["cause_signature_digest"], _HEX64_RE
    )
    _require(
        evidence["cache_state"] in CACHE_STATES,
        f"cache_state must be one of {CACHE_STATES}",
    )
    _require(
        isinstance(evidence["platform_class"], str)
        and _PLATFORM_RE.match(evidence["platform_class"]),
        "platform_class must be system/arch/os-version",
    )
    _check_str_list("raw_log_sha256", evidence["raw_log_sha256"], _HEX64_RE)
    for name in ("started_at", "finished_at"):
        _require(
            isinstance(evidence[name], str) and _ISO_RE.match(evidence[name]),
            f"{name} must be an UTC ISO-8601 second-precision timestamp",
        )

    sanitize.assert_clean(evidence, "$evidence")
    return evidence


def build_evidence(**fields):
    """Build evidence from the allowlist only, then validate it."""
    unknown = sorted(set(fields) - set(ALLOWED_FIELDS))
    if unknown:
        raise EvidenceSchemaError(
            f"unknown evidence field(s): {', '.join(unknown)}"
        )
    record = {"schema_version": EVIDENCE_SCHEMA_VERSION}
    record.update(fields)
    return validate_evidence(record)


def dump_evidence(evidence) -> str:
    """Serialise evidence deterministically."""
    return json.dumps(
        validate_evidence(evidence), sort_keys=True, indent=2, ensure_ascii=True
    )


class PhaseEvidence:
    """What one phase's evidence establishes, and how much of it.

    ``declared`` comes from the evidence record — the run wrote down which raw
    logs it produced. ``verified`` comes from walking the stored result and
    re-hashing each log. The two are deliberately read from different files:
    rule R10 needs an expectation that does not come from the collection being
    walked, or it cannot tell an empty walk from a clean one.
    """

    __slots__ = ("phase", "declared", "verified", "issues")

    def __init__(self, phase, declared, verified, issues):
        self.phase = phase
        self.declared = declared
        self.verified = verified
        #: Defects that were found, as opposed to a walk that found nothing.
        self.issues = list(issues)


def phase_evidence_counts(phase, *, record, result, raw_dir):
    """Count what one phase declared and what could actually be verified."""
    declared = [digest for digest in (record or {}).get("raw_log_sha256", []) if digest]
    issues = []
    verified = 0
    for entry in (result or {}).get("checks", []):
        name = entry.get("raw_log_name")
        digest = entry.get("raw_log_sha256")
        if not name:
            continue
        ok, reason = verify_raw_log(Path(raw_dir) / name, digest)
        if not ok:
            issues.append(reason)
            continue
        verified += 1
    return PhaseEvidence(phase, len(declared), verified, issues)
