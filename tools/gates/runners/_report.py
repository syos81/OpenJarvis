"""Shared reporting helper for gate runners."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PASSED = "passed"
FAILED = "failed"
ERROR = "error"


def failure(identifier, *, category, error_class="", code="", frames=()):
    return {
        "id": str(identifier),
        "category": category,
        "class": error_class,
        "code": code,
        "frames": sorted(str(frame) for frame in frames),
    }


def emit(outcome, failures=(), diagnostics=(), *, stream=None):
    """Write the structured report and return the process exit code."""
    payload = {
        "outcome": outcome,
        "failures": sorted(
            (dict(item) for item in failures),
            key=lambda item: (item.get("id", ""), item.get("category", "")),
        ),
        "diagnostics": sorted(str(item) for item in diagnostics),
        "detail_count": len(list(failures)),
    }
    report_path = os.environ.get("GATE_REPORT")
    if report_path:
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
        )
    stream = stream or sys.stdout
    stream.write(json.dumps({"outcome": outcome}, sort_keys=True) + "\n")
    return 0 if outcome == PASSED else 1
