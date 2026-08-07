"""B0g gate runner: authority binding and real register state.

Three modes:

``authority``
    Validates the decision authority model against the working tree —
    exactly one authoritative place per codified decision, marked
    carriers, and the fragment screen proving no operative full text
    survives outside the DEC documents.

``register-local``
    Parses the canonical governance ref in this repository through the
    register tool's own model (chain, canonical form, transitions) and
    compares the resulting state against the declared stage record: the
    genesis block is a contiguous import-marked prefix, every codified
    DEC id carries the declared stage, and an ``assigned`` stage binds
    every assignment to the recorded normative branch commit.

``register-remote``
    Reads the remote ref fresh (``git ls-remote``) and requires the
    remote oid to equal both the local ref and the recorded expectation.
    Real network state; declared only for the platform-live phase.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.decreg import scan, store  # noqa: E402
from tools.gates import decauthority  # noqa: E402
from tools.gates.runners import _report  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_PATH = "config/governance/decision-authority.json"
RECORD_PATH = "config/gates/history/b0g-assignment.json"


def _fail(identifier, code):
    return _report.failure(identifier, category="b0g", code=code)


def _load():
    model = decauthority.load_model(REPO_ROOT / MODEL_PATH)
    record = decauthority.load_assignment(REPO_ROOT / RECORD_PATH)
    return model, record


def mode_authority(args):
    try:
        model, record = _load()
    except (OSError, ValueError) as error:
        return _report.emit(
            _report.BLOCKED, [_fail(MODEL_PATH, str(error)[:120])],
            reason_code="authority_model_unreadable",
        )
    register_rows = set(scan.allocated_ids(
        (REPO_ROOT / model["register_row_file"]).read_text(encoding="utf-8")
    ))
    findings, stats = decauthority.validate(model, REPO_ROOT, register_rows)
    failures = [
        _fail(f"{item['subject']}:{item['detail'][:80]}", item["code"])
        for item in findings
    ]
    model_ids = {decision["dec_id"] for decision in model["decisions"]}
    if model_ids != set(record["dec_ids"]):
        failures.append(_fail(RECORD_PATH, "record_and_model_id_sets_differ"))
    if not stats["decisions"] or not stats["scanned"]:
        failures.append(_fail("authority", "aggregation_set_empty"))
    diagnostics = [
        f"decisions={stats['decisions']}",
        f"scanned_carrier_files={stats['scanned']}",
    ]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED,
        failures, diagnostics,
    )


def _register_state(model):
    return store.state(str(REPO_ROOT), model["register_ref"])


def mode_register_local(args):
    try:
        model, record = _load()
    except (OSError, ValueError) as error:
        return _report.emit(
            _report.BLOCKED, [_fail(MODEL_PATH, str(error)[:120])],
            reason_code="authority_model_unreadable",
        )
    try:
        current = _register_state(model)
    except Exception as error:  # noqa: BLE001 - integrity failure is the finding
        return _report.emit(
            _report.BLOCKED, [_fail(model["register_ref"], str(error)[:120])],
            reason_code="register_ref_unreadable",
        )
    failures = []
    events = current["events"]
    genesis = [event for event in events if event.get("genesis")]
    prefix = events[:len(genesis)]
    if len(genesis) != record["genesis_events"]:
        failures.append(_fail("genesis", "genesis_count_mismatch"))
    if any(not event.get("genesis") for event in prefix):
        failures.append(_fail("genesis", "genesis_not_a_contiguous_prefix"))
    if any(
        not event.get("import_note") or not event.get("original_file")
        for event in genesis
    ):
        failures.append(_fail("genesis", "genesis_event_without_import_marking"))
    if not record["dec_ids"]:
        failures.append(_fail("record", "aggregation_set_empty"))
    expected_state = {
        "reserved": "reserved", "assigned": "assigned",
    }[record["stage"]]
    by_id = {}
    for event in events:
        by_id.setdefault(event["dec_id"], []).append(event)
    for dec_id in record["dec_ids"]:
        if current["state"].get(dec_id) != expected_state:
            failures.append(_fail(dec_id, f"state_not_{expected_state}"))
            continue
        if record["stage"] == "assigned":
            last = by_id[dec_id][-1]
            if last.get("source_commit") != record["normative_commit"]:
                failures.append(_fail(dec_id, "assignment_not_bound_to_commit"))
    if len(events) != record["expected_events"]:
        failures.append(_fail("events", "event_count_mismatch"))
    diagnostics = [
        f"events={len(events)}",
        f"genesis={len(genesis)}",
        f"stage={record['stage']}",
        f"chain_digest={current['digest']}",
        f"ref_oid={current['ref_oid']}",
    ]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED,
        failures, diagnostics,
    )


def mode_register_remote(args):
    try:
        model, record = _load()
    except (OSError, ValueError) as error:
        return _report.emit(
            _report.BLOCKED, [_fail(MODEL_PATH, str(error)[:120])],
            reason_code="authority_model_unreadable",
        )
    completed = subprocess.run(  # noqa: S603 - fixed argv, read-only query
        ["git", "-C", str(REPO_ROOT), "ls-remote", "origin",
         model["register_ref"]],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if completed.returncode != 0:
        return _report.emit(
            _report.BLOCKED, [_fail("origin", "remote_unreachable")],
            reason_code="remote_unreachable",
        )
    line = completed.stdout.strip()
    remote_oid = line.split()[0] if line else ""
    failures = []
    if not remote_oid:
        failures.append(_fail(model["register_ref"], "remote_ref_absent"))
    try:
        local_oid = _register_state(model)["ref_oid"]
    except Exception as error:  # noqa: BLE001
        return _report.emit(
            _report.BLOCKED, [_fail(model["register_ref"], str(error)[:120])],
            reason_code="register_ref_unreadable",
        )
    if remote_oid and remote_oid != local_oid:
        failures.append(_fail(remote_oid, "remote_and_local_oid_differ"))
    if remote_oid and remote_oid != record["expected_remote_oid"]:
        failures.append(_fail(remote_oid, "remote_oid_not_the_recorded_one"))
    diagnostics = [f"remote_oid={remote_oid}", f"local_oid={local_oid}"]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED,
        failures, diagnostics,
    )


MODES = {
    "authority": mode_authority,
    "register-local": mode_register_local,
    "register-remote": mode_register_remote,
}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="b0g_checks")
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    args = parser.parse_args(argv)
    return MODES[args.mode](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
