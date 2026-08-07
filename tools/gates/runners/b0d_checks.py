#!/usr/bin/env python3
"""Deterministic checks of the B0d guard hardening block.

Modes, one per declared check:

``manipulation-matrix``  every declared manipulation, applied and judged
``collect-tool``         the owner tool cannot collect, and cannot write
``observed-wiring``      the recording of ignored objects is wired end to end
``effect-evidence``      rule R9: an induced effect is evidenced (declared set)
``historical-objects``   the two objects of the production finding, re-derived
``guard-candidate``      the candidate package and the active installation

Every mode is read only with one exception: ``manipulation-matrix`` and
``collect-tool`` write into throwaway directories below the declared fixture
root inside the gitignored runtime area, and nowhere else. No mode needs a
present owner, no mode runs ``sudo``, no mode touches the protected
installation, and no mode moves, edits or deletes an exception object.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import effectevidence  # noqa: E402
from tools.gates.runners import _report  # noqa: E402
from tools.guard import EXCEPTION_SCHEMA  # noqa: E402
from tools.guard import GUARD_VERSION  # noqa: E402
from tools.guard import owner_exception  # noqa: E402
from tools.guard import rules as rules_module  # noqa: E402
from tools.guardops import collect as collect_module  # noqa: E402
from tools.guardops import matrix as matrix_module  # noqa: E402

HISTORICAL_RECORD = Path("config") / "gates" / "history" / (
    "b0d-historical-exception-objects.json"
)
NOW = 1_800_000_000
COMMAND = "rm -r /private/tmp/jarvis-b0d-gate-fixture"


def _fail(identifier, code):
    return _report.failure(identifier, category="b0d", code=code)


def _emit(failures, diagnostics=()):
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def _policy(root):
    return rules_module.load_rules(str(root / "tools" / "guard" / "rules.json")).exception_policy


def _fresh(area):
    """A throwaway directory below the declared fixture root."""
    if area.exists():
        shutil.rmtree(str(area))
    area.mkdir(parents=True)
    return area


class _Candidate:
    """The repository copy, in the shape the collection tool expects."""

    def __init__(self, root):
        self.source = collect_module.SOURCE_WORKTREE
        self.root = root / "tools" / "guard"
        self.version = GUARD_VERSION
        self.schema = EXCEPTION_SCHEMA
        self.policy = _policy(root)
        self.module = owner_exception

    def describe(self):
        return {"guard_source": self.source, "guard_version": self.version}


# -- the manipulation matrix ------------------------------------------------


def mode_manipulation_matrix(args):
    """Every row applied to a real object, and rule R9 asserted first."""
    root = Path.cwd()
    failures = []
    diagnostics = []
    try:
        document = matrix_module.load_matrix(root)
    except matrix_module.MatrixError as error:
        return _emit([_fail(str(matrix_module.MATRIX_PATH), error.code)])

    base = root / document["fixtures"]["root"] / "gate"
    _fresh(base)
    guard = _Candidate(root)
    diagnostics.append(f"entries={len(document['entries'])}")

    for entry in document["entries"]:
        identifier = str(entry["entry_id"])
        row = _fresh(base / identifier)
        (row / "pending").mkdir()
        (row / "spent").mkdir()
        worktree = row / "worktree"
        worktree.mkdir()
        payload = owner_exception.build(
            nonce="a" * 32,
            worktree=str(worktree),
            command=COMMAND,
            reason="B0d gate fixture object",
            created_at=NOW,
            ttl_seconds=600,
            guard_version=GUARD_VERSION,
        )
        applied = matrix_module.apply(
            entry,
            payload,
            integrity_digest=owner_exception.integrity_digest,
            now=NOW,
            stem="a" * 32,
        )
        # Rule R9. The manipulation is established before anything about the
        # guard is asserted; a row whose manipulation did nothing fails here.
        if not applied.probe_holds:
            failures.append(_fail(identifier, "manipulation_had_no_effect"))
            continue

        target = row / "pending" / (applied.stem + ".json")
        target.write_bytes(applied.raw)
        record = collect_module.inspect_object(
            target,
            guard,
            now=NOW,
            worktree_id=owner_exception.worktree_id(str(worktree)),
        )
        for field, declared in (
            ("structure", entry["expected_structure"]),
            ("corruption_code", entry["expected_corruption_code"]),
            ("classification", entry["expected_classification"]),
            ("decision_effect_possible", entry["expected_decision_effect"]),
        ):
            if record[field] != declared:
                failures.append(_fail(identifier, f"{field}_is_{record[field]}"))

        expected = (
            [record["object_id"]]
            if entry["expected_collection"] == "collected"
            else []
        )
        if collect_module.collectable([record]) != expected:
            failures.append(_fail(identifier, "collection_disagrees_with_the_matrix"))

        failures.extend(_consumption(identifier, entry, row, worktree, guard))

    shutil.rmtree(str(base), ignore_errors=True)
    return _emit(failures, diagnostics)


def _consumption(identifier, entry, row, worktree, guard):
    """What the decision path really does with the manipulated object."""
    try:
        outcome = owner_exception.consume(
            pending_dir=row / "pending",
            spent_dir=row / "spent",
            worktree=str(worktree),
            command=COMMAND,
            now=NOW,
            policy=guard.policy,
            guard_version=GUARD_VERSION,
            schema=EXCEPTION_SCHEMA,
        )
    except owner_exception.ExceptionCorrupt as error:
        code = error.args[0] if error.args else ""
        if entry["expected_structure"] != "structurally_corrupt":
            return [_fail(identifier, "unexpectedly_blocked_as_corrupt")]
        if code != entry["expected_corruption_code"]:
            return [_fail(identifier, f"blocked_as_{code}")]
        return []

    if entry["expected_structure"] == "structurally_corrupt":
        return [_fail(identifier, "corrupt_object_did_not_block")]
    if entry["expected_decision_effect"]:
        return [] if outcome.granted else [_fail(identifier, "candidate_not_granted")]
    problems = []
    if outcome.granted:
        problems.append(_fail(identifier, "non_candidate_was_granted"))
    # Byte identical to an empty area: no reason of its own, no nonce digest.
    if outcome.reason_code != "no_exception":
        problems.append(_fail(identifier, f"reason_code_is_{outcome.reason_code}"))
    if outcome.nonce_digest:
        problems.append(_fail(identifier, "non_candidate_contributed_a_nonce_digest"))
    seen = [item.classification for item in outcome.observations]
    if seen != [entry["expected_classification"]]:
        problems.append(_fail(identifier, "observation_missing_or_wrong"))
    return problems


# -- the owner collection tool ----------------------------------------------


def mode_collect_tool(args):
    """It reports, it plans, and it cannot collect from this session."""
    root = Path.cwd()
    failures = []
    diagnostics = []
    document = matrix_module.load_matrix(root)
    base = _fresh(root / document["fixtures"]["root"] / "gate-tool")
    pending = base / "var" / "exceptions" / "pending"
    collected = base / "var" / "exceptions" / "collected"
    pending.mkdir(parents=True)
    collected.mkdir(parents=True)
    worktree = base / "worktree"
    worktree.mkdir()

    for stem, version, created in (
        ("a" * 32, GUARD_VERSION, NOW),
        ("b" * 32, "0.9.0", NOW),
        ("c" * 32, GUARD_VERSION, NOW - 601),
    ):
        payload = owner_exception.build(
            nonce=stem,
            worktree=str(worktree),
            command=COMMAND,
            reason="B0d gate fixture object",
            created_at=created,
            ttl_seconds=600,
            guard_version=version,
        )
        (pending / (stem + ".json")).write_text(
            json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
        )

    before = _digests(pending) | _digests(collected)

    def run(*arguments):
        stream = io.StringIO()
        code = collect_module.main(
            list(arguments)
            + ["--target", str(base), "--worktree", str(worktree),
               "--guard-source", "worktree", "--now", str(NOW)],
            stdout=stream,
        )
        return code, json.loads(stream.getvalue())

    for subcommand in collect_module.READ_ONLY_COMMANDS:
        _code, report = run(subcommand)
        if report.get("wrote_anything"):
            failures.append(_fail(subcommand, "read_only_subcommand_reported_a_write"))
        # Rule R7: the report schema is compared to the format it names.
        if report.get("schema") != collect_module.REPORT_SCHEMA:
            failures.append(_fail(subcommand, "report_does_not_carry_its_schema"))
        declared = set(collect_module.REPORT_KEYS[subcommand])
        found = set(report)
        if found != declared:
            added = ",".join(sorted(found - declared)) or "-"
            dropped = ",".join(sorted(declared - found)) or "-"
            failures.append(
                _fail(subcommand, f"report_format_drift_added_{added}_dropped_{dropped}")
            )

    _code, status = run("status")
    if status.get("candidates_present") != ["a" * 32]:
        failures.append(_fail("status", "candidate_set_wrong"))
    if status.get("collectable") != ["b" * 32, "c" * 32]:
        failures.append(_fail("status", "collectable_set_wrong"))

    _code, plan = run("plan-collect")
    if plan.get("executed"):
        failures.append(_fail("plan-collect", "plan_reported_an_execution"))
    if plan.get("would_move") != ["b" * 32, "c" * 32]:
        failures.append(_fail("plan-collect", "plan_set_wrong"))
    command = str(plan.get("owner_command", ""))
    if not command.startswith("sudo ") or "--confirm" not in command:
        failures.append(_fail("plan-collect", "owner_command_incomplete"))
    for placeholder in ("<", ">", "${"):
        if placeholder in command:
            failures.append(_fail("plan-collect", "owner_command_not_literal"))

    code, refusal = run("collect", "--confirm")
    if code != collect_module.EXIT_REFUSED or not refusal.get("refused"):
        failures.append(_fail("collect", "collect_did_not_refuse"))
    if refusal.get("reason_code") != "collect_requires_root":
        failures.append(_fail("collect", "refusal_reason_wrong"))

    after = _digests(pending) | _digests(collected)
    if before != after:
        # The one statement everything else rests on.
        failures.append(_fail("areas", "an_area_changed_during_a_session_run"))
    diagnostics.append(f"objects={len(before)}")

    failures.extend(_no_writes_outside_the_writing_functions(root))
    shutil.rmtree(str(base), ignore_errors=True)
    return _emit(failures, diagnostics)


def _digests(directory):
    import hashlib

    base = Path(directory)
    if not base.is_dir():
        return {}
    return {
        str(item): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(base.glob("*"))
        if item.is_file()
    }


WRITING_FUNCTIONS = ("_move_object", "command_collect")
WRITING_CALLS = ("open", "write_bytes", "write_text", "unlink", "mkdir",
                 "rename", "replace", "rmtree", "chown", "chmod", "touch")


def _no_writes_outside_the_writing_functions(root):
    """From the syntax tree, not from the module's own description of itself."""
    source = (root / "tools" / "guardops" / "collect.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    failures = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name in WRITING_FUNCTIONS:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            name = getattr(inner.func, "id", "") or getattr(inner.func, "attr", "")
            if name in WRITING_CALLS:
                failures.append(_fail(node.name, f"write_call_{name}_outside_collect"))
    # And the refusal really is the first statement of the writing function.
    function = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "command_collect"
    ]
    if not function:
        return failures + [_fail("command_collect", "writing_function_absent")]
    body = function[0].body
    first = body[1] if isinstance(body[0], ast.Expr) else body[0]
    if not isinstance(first, ast.If) or "geteuid" not in ast.dump(first.test):
        failures.append(_fail("command_collect", "root_refusal_is_not_the_first_statement"))
    return failures


# -- the recording of ignored objects ---------------------------------------


def mode_observed_wiring(args):
    """The diagnosis path exists in the installed guard, not only in the library.

    Checked at the two joints where it was actually missing: the process entry
    has to accept a directory, and the bootstrap has to name one. A parameter
    only the library entry point accepts is a parameter the running guard
    never uses.
    """
    root = Path.cwd()
    failures = []
    diagnostics = []

    entry_source = (root / "tools" / "guard" / "entry.py").read_text(encoding="utf-8")
    tree = ast.parse(entry_source)
    for name in ("run", "main"):
        function = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == name
        ]
        if not function:
            failures.append(_fail(f"entry.{name}", "function_absent"))
            continue
        arguments = [item.arg for item in function[0].args.kwonlyargs + function[0].args.args]
        if "observed_dir" not in arguments:
            failures.append(_fail(f"entry.{name}", "does_not_accept_observed_dir"))

    boot = (root / "tools" / "guardpkg" / "bootstrap.py").read_text(encoding="utf-8")
    if "observed_dir=" not in boot:
        failures.append(_fail("bootstrap", "does_not_name_an_observed_directory"))

    installer = (root / "scripts" / "guard-install.sh").read_text(encoding="utf-8")
    for needed in ("var/observed", "var/exceptions/collected"):
        if needed not in installer:
            failures.append(_fail("guard-install", f"does_not_create_{needed}"))

    # And the behaviour: a missing directory disables recording and changes
    # no decision, which is what makes the wiring safe to add at all.
    base = _fresh(root / ".gate-runtime" / "fixtures" / "exceptions" / "gate-observed")
    from tools.guard import observed as observed_module

    written = observed_module.record_all(str(base / "absent"), [])
    if written != 0:
        failures.append(_fail("observed", "missing_directory_was_not_a_no_op"))
    diagnostics.append("missing_observed_directory=no_op")
    shutil.rmtree(str(base), ignore_errors=True)
    return _emit(failures, diagnostics)


# -- rule R9 ----------------------------------------------------------------


def mode_effect_evidence(args):
    root = Path.cwd()
    found, diagnostics = effectevidence.check(root)
    return _emit(
        [_fail(identifier, code) for identifier, code in found], diagnostics
    )


# -- the two objects of the production finding ------------------------------


def mode_historical_objects(args):
    """Re-derived from the record, for every supported guard version.

    The record is what a gate can check: it is committed, it is machine
    independent, and it deliberately omits everything that would let the
    objects be reassembled into something the guard would read.
    """
    root = Path.cwd()
    failures = []
    diagnostics = []
    target = root / HISTORICAL_RECORD
    if not target.is_file():
        return _emit([_fail(str(HISTORICAL_RECORD), "record_missing")])
    document = json.loads(target.read_text(encoding="utf-8"))
    policy = _policy(root)
    now = int(time.time())

    excluded = set(document["recorded_fields"]["excluded"])
    for required in ("command_canonical", "reason", "integrity_sha256"):
        if required not in excluded:
            failures.append(_fail(required, "reconstructible_field_is_recorded"))

    for record in document["objects"]:
        identifier = str(record["nonce"])
        present = set(record)
        for forbidden in ("command_canonical", "reason", "integrity_sha256"):
            if forbidden in present:
                failures.append(_fail(identifier, f"record_carries_{forbidden}"))
        for version in document["checked_against_guard_versions"]:
            payload = {
                "created_at": int(record["created_at"]),
                "expires_at": int(record["expires_at"]),
                "guard_version": str(record["guard_version"]),
                "schema": str(record["schema"]),
            }
            qualification = owner_exception.classify(
                payload,
                now=now,
                policy=policy,
                guard_version=version,
                schema=EXCEPTION_SCHEMA,
            )
            declared = record["expected_classification_by_version"].get(version)
            if qualification.primary != declared:
                failures.append(
                    _fail(f"{identifier}@{version}", f"classified_{qualification.primary}")
                )
            if qualification.is_candidate:
                # The invariant of the whole block.
                failures.append(_fail(f"{identifier}@{version}", "became_a_candidate"))
        diagnostics.append(f"{identifier[:8]}=non_candidate_under_every_version")

    diagnostics.append(f"objects={len(document['objects'])}")
    return _emit(failures, diagnostics)


# -- candidate and active installation --------------------------------------


def mode_guard_candidate(args):
    """Report the relation, require no particular version.

    Activation is a consequence of acceptance, not its condition. This mode
    therefore states what is installed and what the candidate is, and fails
    only if the candidate cannot be described at all.
    """
    root = Path.cwd()
    failures = []
    diagnostics = [f"candidate_version={GUARD_VERSION}"]

    from tools.guardpkg import build as build_module

    present = sorted(
        item.name
        for item in (root / "tools" / "guard").iterdir()
        if item.is_file() and not item.name.endswith((".pyc", ".pyo"))
    )
    if present != sorted(build_module.PACKAGE_MEMBERS):
        failures.append(_fail("package", "source_does_not_match_declared_members"))

    # The owner side tooling must never become part of the runtime package.
    for name in ("collect.py", "matrix.py"):
        if name in build_module.PACKAGE_MEMBERS:
            failures.append(_fail(name, "owner_tool_declared_as_a_runtime_member"))

    active = Path("/usr/local/jarvis-guard/active.json")
    if active.is_file():
        try:
            manifest = json.loads(active.read_text(encoding="utf-8"))
            diagnostics.append(f"active_version={manifest.get('guard_version')}")
            diagnostics.append(
                "activation_state="
                + (
                    "candidate_active"
                    if manifest.get("guard_version") == GUARD_VERSION
                    else "candidate_not_active"
                )
            )
        except (OSError, ValueError):
            diagnostics.append("active_version=unreadable")
    else:
        diagnostics.append("active_version=absent")
    return _emit(failures, diagnostics)


MODES = {
    "manipulation-matrix": mode_manipulation_matrix,
    "collect-tool": mode_collect_tool,
    "observed-wiring": mode_observed_wiring,
    "effect-evidence": mode_effect_evidence,
    "historical-objects": mode_historical_objects,
    "guard-candidate": mode_guard_candidate,
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    args = parser.parse_args(argv)
    return MODES[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())
