"""Recording of exception objects that carry no decision weight.

Why record at all, and why never clean up. A guard that removed the objects it
decided to ignore would destroy exactly the traces needed to understand its
own decision later. So the running guard does one thing with an expired or
version foreign object: it writes down that it saw it, and leaves the object
completely alone. It never deletes, moves, renames or edits it.

Two properties matter more than completeness here:

*it never decides*
    Every function below returns a boolean and swallows its own failures. A
    diagnosis that cannot be written must never turn an established deny into
    a different one, and must never release one.

*it deduplicates without touching the source*
    The record file is named after the digest of the unmodified object, and it
    is created with ``O_CREAT | O_EXCL``. Seeing the same object again is a
    no-op: no second record, no write to the object, no change to its mtime.

Nothing personal is written. A record holds a nonce, a digest, a
classification, an age and a version — no command text, no reason text, no
path.
"""

from __future__ import annotations

import datetime
import errno
import json
import os
from pathlib import Path

#: Directory below the owner controlled runtime area. Created by the owner
#: installer; a missing directory disables recording and nothing else.
OBSERVED_DIRNAME = "observed"

_SAFE_NAME = "0123456789abcdef"


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def stamp(now=None):
    return (now or utc_now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_stem(digest):
    """A file name that can only ever be a digest."""
    text = str(digest).lower()
    if len(text) != 64 or any(character not in _SAFE_NAME for character in text):
        return ""
    return text


def record_path(observed_dir, digest):
    stem = _safe_stem(digest)
    if not stem:
        return None
    return Path(observed_dir) / (stem + ".json")


def write_record(observed_dir, record):
    """Write one record if it is not already there. Never raises.

    Returns ``True`` when a new record was created, ``False`` when it already
    existed or could not be written. Both are acceptable outcomes: the caller
    must not behave differently either way.
    """
    try:
        target = record_path(observed_dir, record.get("object_sha256", ""))
        if target is None:
            return False
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        handle = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    except OSError as exc:
        # EEXIST is the deduplication case: the same unmodified object was
        # already recorded. It is not an error and it is not a new record, so
        # it reports exactly like a failed write — the caller may not tell
        # them apart, because neither may change anything.
        del exc
        return False
    except Exception:  # noqa: BLE001 - a diagnosis never propagates
        return False
    try:
        os.write(handle, payload.encode("utf-8"))
    except OSError:
        return False
    finally:
        try:
            os.close(handle)
        except OSError:  # pragma: no cover - close failure is not recoverable
            pass
    return True


def record_all(observed_dir, observations, *, now=None):
    """Record every observation. Returns the number newly written.

    A missing directory, a read only directory or a failing write all end in
    zero. None of them is reported upwards as a problem, because none of them
    is allowed to change a decision.
    """
    if not observed_dir:
        return 0
    directory = Path(observed_dir)
    if not directory.is_dir():
        return 0
    captured_at = stamp(now)
    written = 0
    for observation in observations or ():
        try:
            record = observation.record(captured_at=captured_at)
        except Exception:  # noqa: BLE001 - a diagnosis never propagates
            continue
        if write_record(directory, record):
            written += 1
    return written


def load_records(observed_dir):
    """Every record currently present, sorted by object digest."""
    directory = Path(observed_dir)
    if not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.glob("*.json")):
        try:
            found.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return found
