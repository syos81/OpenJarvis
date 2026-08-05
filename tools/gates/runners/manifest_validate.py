#!/usr/bin/env python3
"""Manifest validation runner.

Validates the block manifest itself plus the positive and negative fixtures.
A negative fixture is named after the issue code it must produce, so the
expectation is part of the repository, not of this runner.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import manifest as manifest_module  # noqa: E402
from tools.gates.runners import _report  # noqa: E402

FIXTURE_ROOT = Path("config") / "gates" / "fixtures" / "manifests"


def _fail(identifier, code):
    return _report.failure(identifier, category="manifest", code=code)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--block", required=True)
    parser.add_argument("--with-fixtures", action="store_true")
    args = parser.parse_args(argv)

    root = Path.cwd()
    failures = []
    diagnostics = []

    manifest_path = manifest_module.manifest_path_for(root, args.block)
    if not manifest_path.is_file():
        failures.append(_fail("manifest.file", "manifest_missing"))
    else:
        try:
            manifest_module.load(manifest_path)
        except manifest_module.ManifestError as exc:
            for code, _ in exc.issues:
                failures.append(_fail(f"manifest.{code}", code))

    if args.with_fixtures:
        valid_dir = root / FIXTURE_ROOT / "valid"
        invalid_dir = root / FIXTURE_ROOT / "invalid"
        valid_fixtures = sorted(valid_dir.glob("*.json")) if valid_dir.is_dir() else []
        invalid_fixtures = (
            sorted(invalid_dir.glob("*.json")) if invalid_dir.is_dir() else []
        )
        if not valid_fixtures or not invalid_fixtures:
            failures.append(_fail("fixtures", "manifest_fixtures_missing"))
        for fixture in valid_fixtures:
            try:
                manifest_module.load(fixture)
            except manifest_module.ManifestError as exc:
                failures.append(
                    _fail(f"fixture.valid.{fixture.stem}", "valid_fixture_rejected")
                )
                diagnostics.append(f"{fixture.stem}:{len(exc.issues)}")
        for fixture in invalid_fixtures:
            expected = fixture.stem.split(".")[0]
            try:
                manifest_module.load(fixture)
            except manifest_module.ManifestError as exc:
                codes = {code for code, _ in exc.issues}
                if expected not in codes:
                    failures.append(
                        _fail(
                            f"fixture.invalid.{fixture.stem}",
                            "expected_issue_code_missing",
                        )
                    )
            else:
                failures.append(
                    _fail(f"fixture.invalid.{fixture.stem}", "invalid_fixture_accepted")
                )
        diagnostics.append(f"valid_fixtures={len(valid_fixtures)}")
        diagnostics.append(f"invalid_fixtures={len(invalid_fixtures)}")

    outcome = _report.PASSED if not failures else _report.FAILED
    return _report.emit(outcome, failures, diagnostics)


if __name__ == "__main__":
    sys.exit(main())
