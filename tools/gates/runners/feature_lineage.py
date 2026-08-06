#!/usr/bin/env python3
"""Feature completeness runner.

Validates the block's feature lineage against the *predecessor's* feature
list. A missing or unmapped mandatory feature is always a failure; a missing
predecessor list is reported as a blocking diagnostic instead of a silent
pass.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import features as features_module  # noqa: E402
from tools.gates import manifest as manifest_module  # noqa: E402
from tools.gates import statuses  # noqa: E402
from tools.gates.runners import _report  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--block", required=True)
    args = parser.parse_args(argv)

    root = Path.cwd()
    manifest_path = manifest_module.manifest_path_for(root, args.block)
    if not manifest_path.is_file():
        return _report.emit(
            _report.FAILED,
            [_report.failure("manifest", category="feature", code="manifest_missing")],
        )
    try:
        manifest = manifest_module.load(manifest_path)
    except manifest_module.ManifestError:
        return _report.emit(
            _report.FAILED,
            [_report.failure("manifest", category="feature", code="manifest_invalid")],
        )

    lineage = manifest.data["feature_lineage"]
    report = features_module.validate_lineage(
        lineage_path=root / lineage["lineage_file"],
        predecessor_path=root / lineage["predecessor_file"],
        worktree=root,
        manifest=manifest,
        own_prefix=lineage.get("own_prefix"),
    )
    counts = report["counts"]
    diagnostics = [
        f"expected={counts['expected']}",
        f"mapped={counts['mapped']}",
        f"changed={counts['changed']}",
        f"missing={counts['missing']}",
        f"lineage_status={report['status']}",
    ]
    own = report.get("own_counts")
    declared_expected = lineage.get("own_expected")
    count_mismatch = own is not None and own["expected"] != declared_expected
    if own:
        diagnostics.append(f"own_expected={own['expected']}")
        diagnostics.append(f"own_verified={own['verified']}")
        diagnostics.append(f"own_missing={own['missing']}")
    if count_mismatch:
        diagnostics.append(f"own_declared={declared_expected}")
        return _report.emit(
            _report.FAILED,
            [
                _report.failure(
                    "own_feature_count",
                    category="feature",
                    code="own_feature_count_mismatch",
                )
            ],
            diagnostics,
        )
    if report["status"] == statuses.PASS:
        return _report.emit(_report.PASSED, [], diagnostics)
    failures = [
        _report.failure(
            entry["feature_id"], category="feature", code=entry["reason_code"]
        )
        for entry in report["features"]
        if entry["status"] != statuses.PASS
    ] or [
        _report.failure(
            "feature_lineage", category="feature", code=report["reason_code"]
        )
    ]
    return _report.emit(_report.FAILED, failures, diagnostics)


if __name__ == "__main__":
    sys.exit(main())
