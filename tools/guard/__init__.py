"""Canonical development source of the external PreToolUse guard.

This package is the *only* implementation of the guard decision. It is
deliberately standalone:

* it imports nothing from ``tools.gates`` and nothing from product code,
* it never reads a file from the worktree it is protecting,
* it runs on the system interpreter ``/usr/bin/python3`` (3.9+),
* every failure path ends in a deny, never in a silent release.

A concrete committed state of this package is built into an installable
package with a deterministic hash (``tools/guardpkg/build.py``) and installed
by the owner into a root owned location. The repository copy is the
development source and the installation candidate — it is never the active
guard.
"""

from __future__ import annotations

#: Version of the guard implementation. Bumped by the owner together with a
#: reinstallation; the active installation is pinned to this value.
GUARD_VERSION = "1.0.0"

#: Schema identifier of ``rules.json``. A mismatch is a hard block.
CONFIG_SCHEMA = "guard-config-1"

#: Schema identifier of the active installation manifest ``active.json``.
ACTIVE_MANIFEST_SCHEMA = "guard-active-1"

#: Schema identifier of a single owner exception object.
EXCEPTION_SCHEMA = "guard-exception-1"

__all__ = [
    "ACTIVE_MANIFEST_SCHEMA",
    "CONFIG_SCHEMA",
    "EXCEPTION_SCHEMA",
    "GUARD_VERSION",
]
