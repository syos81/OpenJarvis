"""Owner side operations on a guard installation.

This package is deliberately **not** part of the guard runtime package. It is
never installed, never imported by the decision path and never appears in
``tools/guardpkg/build.py``'s member list. A change here cannot change what
the active guard decides — which is the only reason a tool that touches the
protected exception area may exist at all.

What lives here reads a guard installation and reports on it. Exactly one
function in this package writes, and it refuses to run unless it is root.
"""

from __future__ import annotations

#: Schema of the reports this package emits.
REPORT_SCHEMA = "guardops-report-1"

__all__ = ["REPORT_SCHEMA"]
