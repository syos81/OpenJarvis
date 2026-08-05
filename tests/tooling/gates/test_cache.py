"""Baseline cache: complete key, invalidation, atomicity, locking."""

from __future__ import annotations

import fcntl
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.tooling.gates import _support  # noqa: E402
from tools.gates import cache as cache_module  # noqa: E402
from tools.gates import paths as gate_paths  # noqa: E402
from tools.gates import sanitize  # noqa: E402

BASE_COMPONENTS = {
    "baseline_commit": "7986bee" + "0" * 33,
    "engine_schema_version": 1,
    "cause_signature_version": "cs-1",
    "block_id": "b0a-1-tooling",
    "phase": "offline-final",
    "check_id": "of-shell-syntax",
    "check_definition": {"parser": "gate_json", "timeout_seconds": 300},
    "manifest_digest": "a" * 64,
    "platform_class": "darwin/x86_64/12.7.6",
    "toolchain": {"python": "3.12.13", "git": "2.37.1"},
    "dependency_lock_digests": {"uv.lock": "b" * 40},
    "config_digests": {".claude/settings.json": "c" * 64},
}

RESULT = {
    "outcome": "passed",
    "exit_code": 0,
    "reason_code": "baseline_recorded",
    "cause_signature": None,
    "failure_count": 0,
}


def key(**overrides):
    components = dict(BASE_COMPONENTS)
    components.update(overrides)
    return cache_module.build_key(**components)


class TestCacheKey(_support.TempEnvMixin):
    def test_incomplete_key_is_rejected(self):
        partial = dict(BASE_COMPONENTS)
        partial.pop("platform_class")
        with self.assertRaises(cache_module.CacheContentError):
            cache_module.build_key(**partial)

    def test_unknown_key_field_is_rejected(self):
        with self.assertRaises(cache_module.CacheContentError):
            key(unexpected="x")

    def test_secret_in_key_is_rejected(self):
        with self.assertRaises(sanitize.EvidenceLeakError):
            key(config_digests={"env": "token=supersecretvalue"})

    def test_unknown_result_field_is_rejected(self):
        cache = cache_module.BaselineCache(self.state_dir / "cache")
        with self.assertRaises(cache_module.CacheContentError):
            cache.store(key(), dict(RESULT, raw_log="everything"))


class TestCacheInvalidation(_support.TempEnvMixin):
    def setUp(self):
        super().setUp()
        self.cache = cache_module.BaselineCache(self.state_dir / "cache")
        gate_paths.ensure_private_dir(self.cache.root)
        self.cache.store(key(), RESULT)

    def test_valid_cache_hit(self):
        result, state = self.cache.load(key())
        self.assertEqual(state, cache_module.STATE_HIT)
        self.assertEqual(result["outcome"], "passed")

    def _assert_miss(self, **overrides):
        result, state = self.cache.load(key(**overrides))
        self.assertIsNone(result)
        self.assertEqual(state, cache_module.STATE_MISS)

    def test_baseline_commit_change_invalidates(self):
        self._assert_miss(baseline_commit="1234567" + "0" * 33)

    def test_manifest_change_invalidates(self):
        self._assert_miss(manifest_digest="d" * 64)

    def test_engine_schema_change_invalidates(self):
        self._assert_miss(engine_schema_version=2)

    def test_signature_version_change_invalidates(self):
        self._assert_miss(cause_signature_version="cs-2")

    def test_toolchain_change_invalidates(self):
        self._assert_miss(toolchain={"python": "3.13.0", "git": "2.37.1"})

    def test_dependency_lock_change_invalidates(self):
        self._assert_miss(dependency_lock_digests={"uv.lock": "e" * 40})

    def test_architecture_change_invalidates(self):
        # An Intel result must never be reused on arm64.
        self._assert_miss(platform_class="darwin/arm64/12.7.6")

    def test_platform_change_invalidates(self):
        self._assert_miss(platform_class="linux/x86_64/6.1")

    def test_check_definition_change_invalidates(self):
        self._assert_miss(check_definition={"parser": "unittest"})

    def test_corrupted_entry_is_a_miss(self):
        path = self.cache.entry_path(key())
        path.write_text("{not json", encoding="utf-8")
        result, state = self.cache.load(key())
        self.assertIsNone(result)
        self.assertEqual(state, cache_module.STATE_CORRUPT)

    def test_tampered_key_digest_is_rejected(self):
        path = self.cache.entry_path(key())
        entry = json.loads(path.read_text(encoding="utf-8"))
        entry["key"]["platform_class"] = "darwin/arm64/12.7.6"
        path.write_text(json.dumps(entry), encoding="utf-8")
        result, state = self.cache.load(key())
        self.assertIsNone(result)
        self.assertEqual(state, cache_module.STATE_KEY_MISMATCH)

    def test_parallel_write_is_locked_out(self):
        lock_path = self.cache.root / f"{cache_module.key_digest(key())}.lock"
        handle = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(cache_module.CacheBusyError):
                self.cache.store(key(), RESULT)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)

    def test_store_is_atomic_and_leaves_no_temporary_file(self):
        self.cache.store(key(), RESULT)
        leftovers = [p.name for p in self.cache.root.glob(".cache-*")]
        self.assertEqual(leftovers, [])

    def test_disabled_cache_never_reports_a_hit(self):
        disabled = cache_module.BaselineCache(self.cache.root, enabled=False)
        result, state = disabled.load(key())
        self.assertIsNone(result)
        self.assertEqual(state, cache_module.STATE_DISABLED)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
