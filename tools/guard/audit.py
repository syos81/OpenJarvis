"""Protected, PII safe guard protocol.

The guard runs with the privileges of the guarded session, so the log can
never be made unforgeable. What it *can* be — and what the owner installer
establishes — is append only:

* the log file is created by the owner installer and owned by ``root``,
* an ACL grants the session ``append`` and denies ``write``, ``delete``,
  ``writeattr``, ``writeextattr``, ``writesecurity`` and ``chown``,
* the session can therefore add entries but can neither remove, truncate,
  reorder nor rewrite them, and cannot lift the ACL because it does not own
  the file.

That property is verified mechanically after installation. It is stated here
because the difference matters: entries cannot be destroyed, but a session
could still append a misleading entry of its own.

Nothing secret is written. Nonces, exception payloads and absolute user
paths never enter the protocol; only digests and short, scrubbed excerpts.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re

#: Absolute home prefixes are replaced before anything is written.
_HOME_PREFIXES = ("/Users/", "/home/")  # gate-allow: absolute_user_path

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{24,}\b")
_BEARER = re.compile(r"(?i)\b(?:bearer|token|secret|password|passwd|api[_-]?key)\b\S*")

MAX_EXCERPT = 160


def digest(value):
    """Stable, non-reversible identifier for a value."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def short_digest(value, length=16):
    return digest(value)[:length]


def scrub(text, max_length=MAX_EXCERPT):
    """Remove personal and secret material from a free text excerpt."""
    value = str(text)
    for prefix in _HOME_PREFIXES:
        pattern = re.compile(re.escape(prefix) + r"[^/\s:]*")
        value = pattern.sub("<home>", value)
    value = _EMAIL.sub("<email>", value)
    value = _BEARER.sub("<secret>", value)
    value = _LONG_HEX.sub("<hex>", value)
    value = value.replace("\n", " ").replace("\r", " ")
    if len(value) > max_length:
        value = value[: max_length - 1] + "…"
    return value


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def stamp(now=None):
    return (now or utc_now()).strftime("%Y-%m-%dT%H:%M:%SZ")


ENTRY_FIELDS = (
    "command_digest",
    "decision",
    "detection_layer",
    "event",
    "exception_nonce_digest",
    "guard_version",
    "reason_code",
    "request_excerpt",
    "timestamp",
    "tool",
    "worktree_id",
)


def build_entry(
    *,
    event,
    decision,
    reason_code,
    tool="",
    worktree_id="",
    command_digest="",
    detection_layer="",
    request_excerpt="",
    exception_nonce_digest="",
    guard_version="",
    now=None,
):
    """Build one protocol entry. Only allowlisted fields ever appear."""
    entry = {
        "timestamp": stamp(now),
        "event": str(event),
        "decision": str(decision),
        "reason_code": str(reason_code),
        "tool": str(tool),
        "worktree_id": str(worktree_id),
        "command_digest": str(command_digest),
        "detection_layer": str(detection_layer),
        "request_excerpt": scrub(request_excerpt) if request_excerpt else "",
        "exception_nonce_digest": str(exception_nonce_digest),
        "guard_version": str(guard_version),
    }
    return {key: entry[key] for key in ENTRY_FIELDS}


def append_entry(path, entry):
    """Append one JSON line. Returns ``True`` on success.

    The file is opened append only. It is never truncated and never rewritten,
    so a protected log keeps every earlier entry even if this call fails.
    """
    line = json.dumps(entry, sort_keys=True) + "\n"
    try:
        handle = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    except OSError:
        return False
    try:
        os.write(handle, line.encode("utf-8"))
    except OSError:
        return False
    finally:
        try:
            os.close(handle)
        except OSError:  # pragma: no cover - close failure is not recoverable
            pass
    return True


def assert_clean(entry):
    """Raise when an entry still carries personal or secret material."""
    payload = json.dumps(entry, sort_keys=True)
    for prefix in _HOME_PREFIXES:
        if prefix in payload:
            raise ValueError("protocol entry contains an absolute user path")
    if _EMAIL.search(payload):
        raise ValueError("protocol entry contains an address")
    return True
