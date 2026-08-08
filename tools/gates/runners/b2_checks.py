"""B2 gate runner: the month view in Apple parity.

Modes:

``matrix``
    The block-local comparison matrix is structurally valid: closed field
    set, every feature carries a proof mode, every automated feature names
    resolvable evidence (a test in the named file or a check declared by
    the b2 manifest), and no live feature is pre-filled as pass without an
    owner note. Offline-checkable at any stage.

``frontend-tests``
    The personal frontend suites (calendar including the B2 features,
    contacts as shared-component regression) run where vitest lives.

``live-matrix``
    The owner acceptance is complete: every live_owner/both feature is
    decided pass or fail — pending blocks, any fail fails. Declared only
    for platform-live and module-final.

``regression``
    B1 function is still there: the packed x86_64 bundle exists and the
    productive database still holds real calendars, events and at least
    one completed sync run (structural non-emptiness, no PII).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates.runners import _report  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = "config/gates/history/b2-parity-matrix.json"
MANIFEST_PATH = "config/gates/blocks/b2-month-parity.json"
DB_PATH = Path.home() / ".openjarvis" / "personal" / "jarvis.db"
BUNDLE_APP = (
    "frontend/src-tauri/target/x86_64-apple-darwin/release/bundle/macos/"
    "Jarvis.app"
)

MATRIX_KEYS = {"schema_version", "kind", "statement", "reference", "features"}
FEATURE_KEYS = {
    "feature_id", "title", "proof", "automated_evidence", "live_result",
    "live_note",
}
PROOFS = ("automated", "live_owner", "both")
LIVE_RESULTS = ("pending", "pass", "fail", "not_applicable_automated_only")


def _fail(identifier, code):
    return _report.failure(identifier, category="b2", code=code)


def load_matrix(path):
    """R4 loader of the comparison matrix; rejects unknown structure."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("matrix must be an object")
    if document.get("schema_version") != 1:
        raise ValueError("unknown schema_version")
    if document.get("kind") != "b2_parity_matrix":
        raise ValueError("unknown kind")
    unknown = set(document) - MATRIX_KEYS
    if unknown:
        raise ValueError(f"unknown matrix fields: {sorted(unknown)}")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("features must be a non-empty list")
    for feature in features:
        if set(feature) - FEATURE_KEYS:
            raise ValueError("unknown feature fields")
        if feature.get("proof") not in PROOFS:
            raise ValueError("unknown proof mode")
        if feature.get("live_result") not in LIVE_RESULTS:
            raise ValueError("unknown live_result")
    return document


def _evidence_resolves(evidence):
    """A test reference ``path::name`` or a check id of the b2 manifest."""
    if "::" in evidence:
        rel, _, name = evidence.partition("::")
        target = REPO_ROOT / rel
        return target.is_file() and name in target.read_text(encoding="utf-8")
    manifest = json.loads((REPO_ROOT / MANIFEST_PATH).read_text(encoding="utf-8"))
    return any(check["check_id"] == evidence for check in manifest["checks"])


def mode_matrix(args):
    try:
        matrix = load_matrix(REPO_ROOT / MATRIX_PATH)
    except (OSError, ValueError) as error:
        return _report.emit(
            _report.BLOCKED, [_fail(MATRIX_PATH, str(error)[:120])],
            reason_code="matrix_unreadable",
        )
    failures = []
    seen = set()
    for feature in matrix["features"]:
        fid = feature["feature_id"]
        if fid in seen:
            failures.append(_fail(fid, "feature_id_duplicated"))
        seen.add(fid)
        proof = feature["proof"]
        evidence = str(feature.get("automated_evidence", "")).strip()
        if proof in ("automated", "both"):
            if not evidence:
                failures.append(_fail(fid, "automated_without_evidence"))
            elif not _evidence_resolves(evidence):
                failures.append(_fail(fid, "automated_evidence_unresolvable"))
        if proof == "automated" and feature["live_result"] not in (
            "not_applicable_automated_only",
        ):
            failures.append(_fail(fid, "automated_feature_with_live_result"))
        if proof in ("live_owner", "both"):
            if feature["live_result"] == "not_applicable_automated_only":
                failures.append(_fail(fid, "live_feature_marked_automated_only"))
            if feature["live_result"] in ("pass", "fail") and not str(
                feature.get("live_note", "")
            ).strip():
                # Ein Eigentümerurteil ohne Notiz ist nicht nachvollziehbar.
                failures.append(_fail(fid, "live_result_without_note"))
    if not matrix["features"]:
        failures.append(_fail("matrix", "aggregation_set_empty"))
    diagnostics = [f"features={len(matrix['features'])}"]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_live_matrix(args):
    try:
        matrix = load_matrix(REPO_ROOT / MATRIX_PATH)
    except (OSError, ValueError) as error:
        return _report.emit(
            _report.BLOCKED, [_fail(MATRIX_PATH, str(error)[:120])],
            reason_code="matrix_unreadable",
        )
    failures = []
    decided = 0
    for feature in matrix["features"]:
        if feature["proof"] not in ("live_owner", "both"):
            continue
        result = feature["live_result"]
        if result == "pending":
            return _report.emit(
                _report.BLOCKED,
                [_fail(feature["feature_id"], "owner_acceptance_pending")],
                reason_code="owner_acceptance_pending",
            )
        if result == "fail":
            failures.append(_fail(feature["feature_id"], "owner_reported_deviation"))
        decided += 1
    if decided == 0:
        failures.append(_fail("matrix", "aggregation_set_empty"))
    diagnostics = [f"live_features_decided={decided}"]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_frontend_tests(args):
    completed = subprocess.run(  # noqa: S603 - fixed argv
        ["npx", "vitest", "run", "src/personal"],
        cwd=str(REPO_ROOT / "frontend"),
        capture_output=True, text=True, timeout=1500, check=False,
    )
    tail = (completed.stdout + completed.stderr)[-2000:]
    match = re.search(r"Tests\s+(\d+) passed", tail)
    passed = int(match.group(1)) if match else 0
    failures = []
    if completed.returncode != 0:
        failures.append(_fail("vitest", "frontend_tests_failed"))
    if passed < 1:
        failures.append(_fail("vitest", "aggregation_set_empty"))
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED,
        failures, [f"tests_passed={passed}"],
    )


def mode_regression(args):
    failures = []
    app = REPO_ROOT / BUNDLE_APP
    if not app.is_dir():
        return _report.emit(
            _report.BLOCKED, [_fail(BUNDLE_APP, "bundle_missing")],
            reason_code="bundle_missing",
        )
    if not DB_PATH.is_file():
        return _report.emit(
            _report.BLOCKED, [_fail(str(DB_PATH), "productive_db_missing")],
            reason_code="productive_db_missing",
        )
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        counts = {
            table: connection.execute(
                f"select count(*) from {table}").fetchone()[0]  # noqa: S608
            for table in ("calendars", "events", "calendar_sync_runs")
        }
    finally:
        connection.close()
    for table, count in counts.items():
        if count < 1:
            failures.append(_fail(table, "b1_data_gone"))
    diagnostics = [f"{table}={count}" for table, count in counts.items()]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


MODES = {
    "matrix": mode_matrix,
    "live-matrix": mode_live_matrix,
    "frontend-tests": mode_frontend_tests,
    "regression": mode_regression,
}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="b2_checks")
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    args = parser.parse_args(argv)
    return MODES[args.mode](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
