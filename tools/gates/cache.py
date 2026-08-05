"""Cache for reproducible baseline results.

The cache lives outside the tracked source tree. A cache entry is only usable
when the *complete* key matches — baseline commit, engine schema version,
cause signature version, block, phase, check, normalised check definition,
manifest digest, platform (x86_64 is never confused with arm64), OS version,
toolchain versions, dependency lock digests and config digests.

Writes are atomic and locked; a partially written or corrupted entry is a
miss, never a silent reuse. A cache hit does not skip the cause signature or
evidence checks — it only skips re-running the baseline command.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path

from . import sanitize

CACHE_SCHEMA_VERSION = 1

#: The closed set of key components. All of them must be present.
KEY_FIELDS = (
    "cache_schema_version",
    "baseline_commit",
    "engine_schema_version",
    "cause_signature_version",
    "block_id",
    "phase",
    "check_id",
    "check_definition",
    "manifest_digest",
    "platform_class",
    "toolchain",
    "dependency_lock_digests",
    "config_digests",
)

#: The closed set of cacheable result fields — never raw output.
RESULT_FIELDS = (
    "outcome",
    "exit_code",
    "reason_code",
    "cause_signature",
    "failure_count",
)

STATE_HIT = "hit"
STATE_MISS = "miss"
STATE_CORRUPT = "corrupt"
STATE_KEY_MISMATCH = "key_mismatch"
STATE_DISABLED = "disabled"


class CacheBusyError(RuntimeError):
    """Raised when another process holds the cache lock for this key."""


class CacheContentError(ValueError):
    """Raised when a cache payload violates the closed result schema."""


def build_key(**components):
    unknown = sorted(set(components) - set(KEY_FIELDS))
    if unknown:
        raise CacheContentError(f"unknown cache key field(s): {unknown}")
    key = {"cache_schema_version": CACHE_SCHEMA_VERSION}
    key.update(components)
    missing = sorted(set(KEY_FIELDS) - set(key))
    if missing:
        raise CacheContentError(f"incomplete cache key: {missing}")
    sanitize.assert_clean(key, "$cache_key")
    return key


def key_digest(key) -> str:
    canonical = json.dumps(key, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_result(result):
    if not isinstance(result, dict):
        raise CacheContentError("cache result must be an object")
    unknown = sorted(set(result) - set(RESULT_FIELDS))
    if unknown:
        raise CacheContentError(f"unknown cache result field(s): {unknown}")
    missing = sorted(set(RESULT_FIELDS) - set(result))
    if missing:
        raise CacheContentError(f"incomplete cache result: {missing}")
    sanitize.assert_clean(result, "$cache_result")
    return result


class BaselineCache:
    def __init__(self, root, enabled=True):
        self.root = Path(root)
        self.enabled = bool(enabled)

    def entry_path(self, key) -> Path:
        return self.root / f"{key_digest(key)}.json"

    def _lock_path(self, key) -> Path:
        return self.root / f"{key_digest(key)}.lock"

    def load(self, key):
        """Return ``(result, state)``; ``result`` is ``None`` unless hit."""
        if not self.enabled:
            return None, STATE_DISABLED
        path = self.entry_path(key)
        if not path.is_file():
            return None, STATE_MISS
        try:
            with open(path, "r", encoding="utf-8") as handle:
                entry = json.load(handle)
        except (OSError, ValueError):
            return None, STATE_CORRUPT
        if not isinstance(entry, dict):
            return None, STATE_CORRUPT
        if entry.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
            return None, STATE_KEY_MISMATCH
        if entry.get("key_digest") != key_digest(key):
            return None, STATE_KEY_MISMATCH
        # Full key verification, not just the digest.
        if entry.get("key") != key:
            return None, STATE_KEY_MISMATCH
        try:
            result = _validate_result(entry.get("result"))
        except (CacheContentError, sanitize.EvidenceLeakError):
            return None, STATE_CORRUPT
        return result, STATE_HIT

    def store(self, key, result):
        """Atomically write a cache entry while holding an exclusive lock."""
        if not self.enabled:
            return None
        _validate_result(result)
        from . import paths as _paths

        _paths.ensure_private_dir(self.root)
        lock_path = self._lock_path(key)
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                    raise CacheBusyError(
                        "baseline cache entry is locked by another run"
                    ) from exc
                raise
            entry = {
                "cache_schema_version": CACHE_SCHEMA_VERSION,
                "key": key,
                "key_digest": key_digest(key),
                "result": result,
            }
            sanitize.assert_clean(entry, "$cache_entry")
            target = self.entry_path(key)
            handle, tmp_name = tempfile.mkstemp(
                dir=str(self.root), prefix=".cache-", suffix=".tmp"
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(entry, stream, sort_keys=True, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(tmp_name, 0o600)
                os.replace(tmp_name, str(target))
            except BaseException:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
                raise
            return target
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
