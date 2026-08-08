"""B1 gate runner: the visible x86_64 calendar path.

Five modes, all mechanical:

``path``
    The functional chain exists in this tree: the /calendar route, exactly
    one sidebar entry, the HTTP client prefix, the x86_64 sidecar at the
    Tauri path, the reseal procedure covering the calendar identifier and
    both entitlement layers.

``readonly``
    The read-only invariant: the bridge protocol declares no mutating
    operation, the source build script still carries the mutation-symbol
    lock, and the shipped sidecar binary contains none of the forbidden
    EventKit write selectors.

``bundle``
    The packed app: native x86_64 app binary, embedded x86_64 calendar
    sidecar, strict deep codesign verification, a real (non ad-hoc)
    signature, the calendars entitlement on the responsible process and a
    minimal single-entitlement contract on the sidecar. Blocked while no
    bundle exists.

``remote-ancestor``
    The published branch tip read fresh from origin must be an ancestor
    of (or equal to) the local HEAD. Real network state.

``live-data``
    The PII-poor live record against the productive database: calendar
    tables exist, the recorded counts re-derive from the database, the
    authorization is authorized and the sync run is recorded as ok. The
    record never carries titles, notes or attendees; its loader rejects
    unknown fields.
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
SIDEBAR = "frontend/src/components/Sidebar/Sidebar.tsx"
APP_TSX = "frontend/src/App.tsx"
CLIENT = "frontend/src/personal/calendar/api.ts"
SIDECAR = "frontend/src-tauri/binaries/jarvis-calendar-x86_64-apple-darwin"
RESEAL = "frontend/src-tauri/scripts/reseal-contacts-sidecar.sh"
APP_ENTITLEMENTS = "frontend/src-tauri/Entitlements.plist"
SIDECAR_ENTITLEMENTS = "frontend/src-tauri/CalendarSidecar.entitlements"
BUILD_LOCK = "native/calendar-bridge/build.sh"
TAURI_CONF = "frontend/src-tauri/tauri.conf.json"
BUNDLE_APP = (
    "frontend/src-tauri/target/x86_64-apple-darwin/release/bundle/macos/"
    "Jarvis.app"
)
LIVE_RECORD = "config/gates/history/b1-live-record.json"
DB_PATH = Path.home() / ".openjarvis" / "personal" / "jarvis.db"
CALENDARS_KEY = "com.apple.security.personal-information.calendars"
FORBIDDEN_SELECTORS = (
    "saveEvent", "removeEvent", "commit", "saveCalendar", "removeCalendar"
)
LIVE_RECORD_KEYS = {
    "schema_version", "kind", "statement", "recorded_at_utc",
    "app_bundle_sha256_main_binary", "embedded_calendar_sidecar_sha256",
    "authorization_status", "sync_outcome", "calendars_count",
    "events_count", "sync_runs_count", "window_start_utc", "window_end_utc",
    "functional_commit",
}


def _fail(identifier, code):
    return _report.failure(identifier, category="b1", code=code)


def _text(relative):
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _run(argv, timeout=120):
    return subprocess.run(  # noqa: S603 - fixed argv, read-only queries
        argv, capture_output=True, text=True, timeout=timeout, check=False,
    )


def _is_x86_64(path):
    completed = _run(["file", str(path)])
    return "x86_64" in completed.stdout and "Mach-O" in completed.stdout


def load_live_record(path):
    """R4 loader of the PII-poor live record; rejects unknown fields."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("record must be an object")
    if document.get("schema_version") != 1:
        raise ValueError("unknown schema_version")
    if document.get("kind") != "b1_live_record":
        raise ValueError("unknown kind")
    unknown = set(document) - LIVE_RECORD_KEYS
    if unknown:
        raise ValueError(f"unknown record fields: {sorted(unknown)}")
    for field in ("calendars_count", "events_count", "sync_runs_count"):
        if not isinstance(document.get(field), int):
            raise ValueError(f"{field} must be an integer")
    if len(document.get("functional_commit", "")) != 40:
        raise ValueError("functional_commit must be a full oid")
    return document


def mode_path(args):
    failures = []
    sidebar = _text(SIDEBAR)
    if len(re.findall(r"path: '/calendar'", sidebar)) != 1:
        failures.append(_fail(SIDEBAR, "sidebar_entry_not_exactly_once"))
    if len(re.findall(r'path="calendar"', _text(APP_TSX))) != 1:
        failures.append(_fail(APP_TSX, "route_not_exactly_once"))
    if "/v1/personal/calendar" not in _text(CLIENT):
        failures.append(_fail(CLIENT, "client_prefix_missing"))
    sidecar = REPO_ROOT / SIDECAR
    if not sidecar.is_file():
        failures.append(_fail(SIDECAR, "sidecar_binary_missing"))
    elif not _is_x86_64(sidecar):
        failures.append(_fail(SIDECAR, "sidecar_not_x86_64"))
    reseal = _text(RESEAL)
    for needle in ("de.kluender.jarvis.calendar-bridge",
                   "CalendarSidecar.entitlements"):
        if needle not in reseal:
            failures.append(_fail(RESEAL, f"reseal_missing:{needle}"))
    if CALENDARS_KEY not in _text(APP_ENTITLEMENTS):
        failures.append(_fail(APP_ENTITLEMENTS, "app_calendars_entitlement_missing"))
    sidecar_ent = _text(SIDECAR_ENTITLEMENTS)
    if sidecar_ent.count("com.apple.security.") != 1 or CALENDARS_KEY not in sidecar_ent:
        failures.append(
            _fail(SIDECAR_ENTITLEMENTS, "sidecar_entitlements_not_minimal")
        )
    conf = json.loads(_text(TAURI_CONF))
    if "binaries/jarvis-calendar" not in conf["bundle"]["externalBin"]:
        failures.append(_fail(TAURI_CONF, "external_bin_missing"))
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures,
        [f"checks=8"],
    )


def _selector_findings(binary):
    findings = []
    names = _run(["nm", "-u", str(binary)]).stdout.lower()
    dumped = _run(["strings", str(binary)]).stdout.splitlines()
    for selector in FORBIDDEN_SELECTORS:
        if selector.lower() in names:
            findings.append(selector)
            continue
        if f"{selector}:withSpan:error:" in dumped:
            findings.append(selector)
    return findings


def mode_readonly(args):
    failures = []
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from personaljarvis.calendar.bridge import protocol  # noqa: PLC0415
    if len(protocol.MUTATING_OPERATIONS) != 0:
        failures.append(_fail("protocol", "mutating_operations_declared"))
    lock = _text(BUILD_LOCK)
    if 'VERBOTEN="saveEvent removeEvent commit saveCalendar removeCalendar"' not in lock:
        failures.append(_fail(BUILD_LOCK, "mutation_symbol_lock_missing"))
    binary = REPO_ROOT / SIDECAR
    if not binary.is_file():
        return _report.emit(
            _report.BLOCKED, [_fail(SIDECAR, "sidecar_binary_missing")],
            reason_code="sidecar_binary_missing",
        )
    for selector in _selector_findings(binary):
        failures.append(_fail(SIDECAR, f"write_selector_in_binary:{selector}"))
    diagnostics = [f"selectors_checked={len(FORBIDDEN_SELECTORS)}"]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def _entitlements_of(path):
    completed = _run(["codesign", "-d", "--entitlements", ":-", str(path)])
    return completed.stdout


def mode_bundle(args):
    app = REPO_ROOT / BUNDLE_APP
    if not app.is_dir():
        return _report.emit(
            _report.BLOCKED, [_fail(BUNDLE_APP, "bundle_missing")],
            reason_code="bundle_missing",
        )
    failures = []
    main_binary = app / "Contents" / "MacOS" / "openjarvis-desktop"
    embedded = app / "Contents" / "MacOS" / "jarvis-calendar"
    if not main_binary.is_file():
        failures.append(_fail(str(main_binary), "app_binary_missing"))
    elif not _is_x86_64(main_binary):
        failures.append(_fail(str(main_binary), "app_binary_not_x86_64"))
    if not embedded.is_file():
        failures.append(_fail(str(embedded), "embedded_sidecar_missing"))
    else:
        if not _is_x86_64(embedded):
            failures.append(_fail(str(embedded), "embedded_sidecar_not_x86_64"))
        if _selector_findings(embedded):
            failures.append(_fail(str(embedded), "write_selector_in_embedded_sidecar"))
    verify = _run(["codesign", "--verify", "--strict", "--deep",
                   "--verbose=2", str(app)], timeout=300)
    if verify.returncode != 0:
        failures.append(_fail(str(app), "codesign_verification_failed"))
    detail = _run(["codesign", "-dvv", str(app)]).stderr
    if "Signature=adhoc" in detail:
        failures.append(_fail(str(app), "app_signature_adhoc"))
    if 'Identifier=de.kluender.jarvis' not in detail:
        failures.append(_fail(str(app), "app_identifier_unexpected"))
    if CALENDARS_KEY not in _entitlements_of(app):
        failures.append(_fail(str(app), "app_calendars_entitlement_missing"))
    info_plist = (app / "Contents" / "Info.plist")
    if info_plist.is_file():
        info = _run(["plutil", "-convert", "xml1", "-o", "-",
                     str(info_plist)]).stdout
        if "NSCalendarsUsageDescription" not in info:
            # Without the usage description macOS aborts instead of asking;
            # from outside that is indistinguishable from a user's no.
            failures.append(_fail(str(info_plist), "calendars_usage_description_missing"))
    else:
        failures.append(_fail(str(info_plist), "info_plist_missing"))
    if embedded.is_file():
        sidecar_detail = _run(["codesign", "-dvv", str(embedded)]).stderr
        if "de.kluender.jarvis.calendar-bridge" not in sidecar_detail:
            failures.append(_fail(str(embedded), "sidecar_identifier_unexpected"))
        if "Signature=adhoc" in sidecar_detail:
            failures.append(_fail(str(embedded), "sidecar_signature_adhoc"))
        entitlements = _entitlements_of(embedded)
        if CALENDARS_KEY not in entitlements:
            failures.append(_fail(str(embedded), "sidecar_calendars_entitlement_missing"))
        for relaxation in ("allow-jit", "allow-unsigned-executable-memory",
                           "disable-library-validation", "network.client",
                           "network.server"):
            if relaxation in entitlements:
                failures.append(
                    _fail(str(embedded), f"sidecar_relaxation_present:{relaxation}")
                )
    diagnostics = [f"app={app.name}"]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_remote_ancestor(args):
    branch = "spike/calendar-foundation-intel-2026-08-04"
    completed = _run(["git", "-C", str(REPO_ROOT), "ls-remote", "origin",
                      f"refs/heads/{branch}"], timeout=120)
    if completed.returncode != 0:
        return _report.emit(
            _report.BLOCKED, [_fail("origin", "remote_unreachable")],
            reason_code="remote_unreachable",
        )
    line = completed.stdout.strip()
    remote_oid = line.split()[0] if line else ""
    if not remote_oid:
        return _report.emit(
            _report.FAILED, [_fail(branch, "remote_branch_absent")]
        )
    head = _run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"]).stdout.strip()
    ancestor = _run(["git", "-C", str(REPO_ROOT), "merge-base",
                     "--is-ancestor", remote_oid, head])
    failures = []
    if ancestor.returncode != 0:
        failures.append(_fail(remote_oid, "remote_not_ancestor_of_local_head"))
    diagnostics = [f"remote_oid={remote_oid}", f"local_head={head}"]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_live_data(args):
    record_path = REPO_ROOT / LIVE_RECORD
    if not record_path.is_file():
        return _report.emit(
            _report.BLOCKED, [_fail(LIVE_RECORD, "live_record_missing")],
            reason_code="live_record_missing",
        )
    try:
        record = load_live_record(record_path)
    except ValueError as error:
        return _report.emit(
            _report.FAILED, [_fail(LIVE_RECORD, str(error)[:120])]
        )
    failures = []
    if record["authorization_status"] != "authorized":
        failures.append(_fail(LIVE_RECORD, "authorization_not_authorized"))
    if record["sync_outcome"] != "ok":
        failures.append(_fail(LIVE_RECORD, "sync_outcome_not_ok"))
    if record["calendars_count"] < 1 or record["events_count"] < 1:
        failures.append(_fail(LIVE_RECORD, "no_real_data_recorded"))
    if not DB_PATH.is_file():
        return _report.emit(
            _report.BLOCKED, [_fail(str(DB_PATH), "productive_db_missing")],
            reason_code="productive_db_missing",
        )
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in connection.execute(
            "select name from sqlite_master where type='table'"
        )}
        for table in ("calendars", "events", "calendar_sync_runs"):
            if table not in tables:
                failures.append(_fail(table, "calendar_table_missing"))
        if not failures:
            derived = {
                "calendars_count": connection.execute(
                    "select count(*) from calendars").fetchone()[0],
                "events_count": connection.execute(
                    "select count(*) from events").fetchone()[0],
                "sync_runs_count": connection.execute(
                    "select count(*) from calendar_sync_runs").fetchone()[0],
            }
            for field, value in derived.items():
                if record[field] != value:
                    failures.append(_fail(field, "recorded_count_not_rederivable"))
            if derived["calendars_count"] < 1 or derived["events_count"] < 1:
                failures.append(_fail(str(DB_PATH), "database_has_no_real_rows"))
    finally:
        connection.close()
    diagnostics = [f"db={DB_PATH.name}"]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_frontend_tests(args):
    """The calendar frontend tests, run where vitest lives."""
    completed = subprocess.run(  # noqa: S603 - fixed argv
        ["npx", "vitest", "run", "src/personal/calendar"],
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


MODES = {
    "path": mode_path,
    "readonly": mode_readonly,
    "bundle": mode_bundle,
    "remote-ancestor": mode_remote_ancestor,
    "live-data": mode_live_data,
    "frontend-tests": mode_frontend_tests,
}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="b1_checks")
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    args = parser.parse_args(argv)
    return MODES[args.mode](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
