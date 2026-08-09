"""B3 gate runner: the approved calendar write path.

``offline``      — the calendar mutation contracts against fixtures (the
                   personal calendar pytest suite; non-empty, R10).
``governance``   — DEC-069 is assigned on the remote register, its document
                   exists and CLAUDE.md carries the reference.
``live``         — the staged live record (create/update/delete) re-derived:
                   backup proof verified, every executed stage carries its
                   own approval and, for update/delete, an unchanged
                   fingerprint. Blocked while stages are honestly pending.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates.runners import _report  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
LIVE_RECORD = "config/gates/history/b3-live-record.json"
BACKUP_PROOF = Path.home() / ".openjarvis" / "personal" / "backups" / "calendar" / "latest.json"
STAGES = ("create", "update", "delete")
STAGE_KEYS = {
    "stage", "executed", "approval_consumed", "outcome", "readback_status",
    "event_digest", "fingerprint_checked", "fingerprint_matched",
    "owner_confirmed_jarvis", "owner_confirmed_apple", "notes",
}
RECORD_KEYS = {
    "schema_version", "kind", "statement", "recorded_at_utc",
    "backup_sha256", "backup_entry_count", "target_calendar_digest",
    "functional_commit", "stages",
}


def _fail(identifier, code):
    return _report.failure(identifier, category="b3", code=code)


def load_live_record(path):
    """R4 loader of the PII-poor staged live record."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("kind") != "b3_live_record":
        raise ValueError("unknown record")
    if document.get("schema_version") != 1:
        raise ValueError("unknown schema_version")
    if set(document) - RECORD_KEYS:
        raise ValueError("unknown record fields")
    stages = document.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ValueError("stages must be non-empty")
    seen = [s.get("stage") for s in stages]
    if seen != list(STAGES[:len(seen)]):
        raise ValueError("stages must follow create, update, delete in order")
    for stage in stages:
        if set(stage) - STAGE_KEYS:
            raise ValueError("unknown stage fields")
    if len(document.get("functional_commit", "")) != 40:
        raise ValueError("functional_commit must be a full oid")
    return document


def mode_offline(args):
    completed = subprocess.run(  # noqa: S603 - fixed argv
        [str(REPO_ROOT / ".venv" / "bin" / "python"), "-m", "pytest",
         "tests/personal/calendar", "-q"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        timeout=1500, check=False,
    )
    tail = (completed.stdout + completed.stderr)[-1500:]
    match = re.search(r"(\d+) passed", tail)
    passed = int(match.group(1)) if match else 0
    failures = []
    if completed.returncode != 0:
        failures.append(_fail("pytest", "calendar_suite_failed"))
    if passed < 1:
        failures.append(_fail("pytest", "aggregation_set_empty"))
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED,
        failures, [f"tests_passed={passed}"],
    )


def mode_governance(args):
    failures = []
    completed = subprocess.run(  # noqa: S603 - fixed argv, read-only
        ["git", "-C", str(REPO_ROOT), "ls-remote", "origin",
         "refs/governance/dec-reservations"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if completed.returncode != 0:
        return _report.emit(
            _report.BLOCKED, [_fail("origin", "remote_unreachable")],
            reason_code="remote_unreachable",
        )
    remote_oid = completed.stdout.split()[0] if completed.stdout.strip() else ""
    sys.path.insert(0, str(REPO_ROOT))
    from tools.decreg import store  # noqa: PLC0415
    try:
        current = store.state(str(REPO_ROOT))
    except Exception as error:  # noqa: BLE001
        return _report.emit(
            _report.BLOCKED, [_fail("register", str(error)[:100])],
            reason_code="register_unreadable",
        )
    if current["ref_oid"] != remote_oid:
        failures.append(_fail(remote_oid, "remote_and_local_register_differ"))
    if current["state"].get("DEC-069") != "assigned":
        failures.append(_fail("DEC-069", "not_assigned"))
    doc = REPO_ROOT / "docs/governance/decisions/DEC-069-kalenderschreiben-einzelfreigabe.md"
    if not doc.is_file():
        failures.append(_fail(str(doc), "dec_document_missing"))
    if "DEC-069" not in (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8"):
        failures.append(_fail("CLAUDE.md", "reference_missing"))
    diagnostics = [f"remote_oid={remote_oid}"]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_live(args):
    record_path = REPO_ROOT / LIVE_RECORD
    if not record_path.is_file():
        return _report.emit(
            _report.BLOCKED, [_fail(LIVE_RECORD, "live_record_missing")],
            reason_code="live_record_missing",
        )
    try:
        record = load_live_record(record_path)
    except ValueError as error:
        return _report.emit(_report.FAILED, [_fail(LIVE_RECORD, str(error)[:100])])
    failures = []
    if not BACKUP_PROOF.is_file():
        return _report.emit(
            _report.BLOCKED, [_fail(str(BACKUP_PROOF), "backup_proof_missing")],
            reason_code="backup_proof_missing",
        )
    proof = json.loads(BACKUP_PROOF.read_text(encoding="utf-8"))
    if proof.get("verified") is not True:
        failures.append(_fail("backup", "backup_not_verified"))
    if proof.get("sha256") != record["backup_sha256"]:
        failures.append(_fail("backup", "backup_digest_mismatch"))
    if record["backup_entry_count"] != proof.get("entry_count"):
        failures.append(_fail("backup", "backup_count_mismatch"))
    executed = 0
    for stage in record["stages"]:
        name = stage["stage"]
        if not stage.get("executed"):
            return _report.emit(
                _report.BLOCKED, [_fail(name, "stage_pending")],
                reason_code="stage_pending",
            )
        executed += 1
        if not stage.get("approval_consumed"):
            failures.append(_fail(name, "stage_without_own_approval"))
        if stage.get("outcome") != "succeeded":
            failures.append(_fail(name, "stage_not_succeeded"))
        if not stage.get("owner_confirmed_jarvis") or not stage.get("owner_confirmed_apple"):
            failures.append(_fail(name, "owner_confirmation_missing"))
        if name in ("update", "delete"):
            if not stage.get("fingerprint_checked") or stage.get("fingerprint_matched") is not True:
                failures.append(_fail(name, "fingerprint_binding_missing"))
        expected_readback = "absent_confirmed" if name == "delete" else "confirmed"
        if stage.get("readback_status") != expected_readback:
            failures.append(_fail(name, "readback_not_proven"))
    if executed == 0:
        failures.append(_fail("stages", "aggregation_set_empty"))
    if len(record["stages"]) != 3:
        return _report.emit(
            _report.BLOCKED, [_fail("stages", "stages_incomplete")],
            reason_code="stage_pending",
        )
    diagnostics = [f"stages_executed={executed}"]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


MODES = {
    "offline": mode_offline,
    "governance": mode_governance,
    "live": mode_live,
}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="b3_checks")
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    args = parser.parse_args(argv)
    return MODES[args.mode](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
