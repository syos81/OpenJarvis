"""Deterministic gate, baseline and evidence tooling for OpenJarvis (B0a-1).

This package contains no product code. It is the implementation behind the
single public entry point ``scripts/gate.sh``.

Version constants are deliberately kept in one place: they take part in the
baseline cache key and in the machine readable gate result, so any semantic
change here must be a visible version change.
"""

ENGINE_VERSION = "1.0.0"
ENGINE_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1
EVIDENCE_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
FEATURE_SCHEMA_VERSION = 1
CAUSE_SIGNATURE_VERSION = "cs-1"

__all__ = [
    "ENGINE_VERSION",
    "ENGINE_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "EVIDENCE_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "FEATURE_SCHEMA_VERSION",
    "CAUSE_SIGNATURE_VERSION",
]
