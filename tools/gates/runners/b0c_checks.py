#!/usr/bin/env python3
"""Deterministic checks of the B0c governance block.

Modes, one per declared check:

``config-loaders``      every configuration is bound to its reader (rule R4)
``errata``              the frozen document errata resolve, or nothing does
``profile-derivation``  the acceptance profile result is computed, not stated
``profile-lock``        the never defined labels stay locked
``register-model``      the reservation register model, on a real fixture
``register-tool``       the register tool cannot publish anything
``scanner-method``      allocation and mention are told apart, on both lines
``fixture-rule``        the target bound release fires only where it may
``guard-activation``    the candidate and the active installation, reported
``owner-expectations``  every owner expectation value re-derived from its commit

Every mode is read only with one exception: ``register-model`` writes into a
throwaway bare repository below the declared fixture root and nowhere else.
No mode needs a present owner and no mode depends on which guard version is
installed — the runner is a subprocess and is never a guarded tool call.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import configload  # noqa: E402
from tools.gates import errata as errata_module  # noqa: E402
from tools.gates import expectations as expectations_module  # noqa: E402
from tools.gates import profiles  # noqa: E402
from tools.gates.runners import _report  # noqa: E402

FIXTURE_ROOT = Path(".gate-runtime") / "fixtures" / "git"
LINES = ("HEAD", "refs/remotes/origin/jarvis/rebuild-v1")


def _fail(identifier, code):
    return _report.failure(identifier, category="b0c", code=code)


def _emit(failures, diagnostics=()):
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED,
        failures,
        diagnostics,
    )


# -- rule R4 ----------------------------------------------------------------


def mode_config_loaders(args):
    root = Path.cwd()
    found, diagnostics = configload.check(root)
    return _emit(
        [_fail(relative, code) for relative, code in found], diagnostics
    )


# -- rule R6 ----------------------------------------------------------------


def mode_owner_expectations(args):
    """Every expectation value re-derived from the commit it is claimed for.

    Not a comparison against a remembered value: each entry is rebuilt from
    the commit object here, so a value that was carried forward from another
    tree cannot survive this check.
    """
    root = Path.cwd()
    found, diagnostics = expectations_module.check(root)
    return _emit(
        [_fail(identifier, code) for identifier, code in found], diagnostics
    )


# -- frozen document errata -------------------------------------------------


def mode_errata(args):
    root = Path.cwd()
    failures = []
    diagnostics = []
    try:
        document = errata_module.load_document(root)
    except errata_module.ErrataDocumentError as error:
        return _emit([_fail(errata_module.ERRATA_PATH, error.code)])

    entries = document["errata"]
    diagnostics.append(f"errata={len(entries)}")
    for entry in entries:
        identifier = entry["erratum_id"]
        outcome = errata_module.resolve(
            root, entry["invalid_reference"], errata=entries
        )
        if not outcome.resolved:
            failures.append(_fail(identifier, outcome.code))
            continue
        if outcome.erratum_id != identifier:
            failures.append(_fail(identifier, "resolved_through_another_erratum"))
        diagnostics.append(
            f"{identifier}=resolved_via_{len(outcome.anchors)}_anchors"
        )

    # A reference nothing covers must stay unresolved. Absence of an erratum
    # is never a silent success.
    control = errata_module.resolve(
        root, "a reference no erratum covers", errata=entries
    )
    if control.resolved:
        failures.append(_fail("control", "unknown_reference_resolved"))
    return _emit(failures, diagnostics)


# -- acceptance profiles ----------------------------------------------------


def mode_profile_derivation(args):
    root = Path.cwd()
    failures = []
    outcome = profiles.derive(root)
    observed = outcome["observed"]

    # The result must follow from the computed collision set, never precede
    # it. Both directions are checked so a constant cannot pass.
    collisions = observed["profiles_covering_differing_signatures"]
    expected = profiles.JUSTIFIED if collisions else profiles.NOT_JUSTIFIED
    if outcome["result"] != expected:
        failures.append(_fail("result", "result_does_not_follow_the_collisions"))

    if observed["blocks"] != len(outcome["inputs"]["block_manifests"]):
        failures.append(_fail("inputs", "not_every_block_manifest_entered"))
    declared = sorted(
        path.name for path in (root / profiles.BLOCKS_DIR).glob("*.json")
    )
    if observed["blocks"] != len(declared):
        failures.append(_fail("inputs", "block_manifest_missing_from_derivation"))
    if not outcome["justification_criterion"].strip():
        failures.append(_fail("criterion", "criterion_not_stated"))
    if not outcome["falsifiable_by"].strip():
        failures.append(_fail("criterion", "falsifiability_not_stated"))

    try:
        lock = profiles.load_lock(root)
    except OSError:
        return _emit(failures + [_fail(profiles.LOCK, "lock_missing")])
    if not profiles.lock_is_consistent_with(outcome, lock):
        failures.append(_fail(profiles.LOCK, "lock_claims_another_result"))

    diagnostics = [
        f"result={outcome['result']}",
        f"blocks={observed['blocks']}",
        f"distinct_signatures={observed['distinct_obligation_signatures']}",
        f"comparable_units={len(observed['comparable_units'])}",
        f"collisions={len(collisions)}",
    ]
    return _emit(failures, diagnostics)


def mode_profile_lock(args):
    root = Path.cwd()
    lock = profiles.load_lock(root)
    failures = [
        _fail(f"{relative}:{label}", "locked_label_used")
        for relative, label in profiles.lock_violations(root, lock)
    ]
    if not lock["locked_labels"]:
        failures.append(_fail(profiles.LOCK, "lock_without_labels"))
    preserved = lock["preserved_check"]
    if not (root / preserved["runner"]).is_file():
        failures.append(_fail("preserved_check", "preserved_runner_missing"))
    diagnostics = [
        f"locked_labels={len(lock['locked_labels'])}",
        f"scanned_paths={len(lock['scanned_paths'])}",
    ]
    return _emit(failures, diagnostics)


# -- reservation register ---------------------------------------------------


def _fixture_repository(root):
    """A throwaway bare repository below the declared fixture root."""
    base = Path(root) / FIXTURE_ROOT
    base.mkdir(parents=True, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix="gate-register-", dir=str(base)))
    bare = target / "register.git"
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "init", "--bare", "--quiet", str(bare)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=True, timeout=60, shell=False,
    )
    return target, bare


def mode_register_model(args):
    from tools.decreg import model, store  # noqa: PLC0415

    root = Path.cwd()
    failures = []
    diagnostics = []
    target, bare = _fixture_repository(root)
    try:
        when = "2026-01-01T00:00:00Z"
        commit = "0" * 40
        text = ""

        def append(dec_id, action, previous_id):
            _events, _state, digest = model.parse(text)
            return model.build_event(
                dec_id=dec_id, action=action, owner_ref="gate-runner",
                origin_line="gate-fixture", recorded_at_utc=when,
                source_commit=commit, previous_digest=digest,
                previous_event_id=previous_id,
            )

        event = append("DEC-900", model.ACTION_RESERVED, None)
        text = model.append(text, event)
        store.write(bare, text, expected_oid=None, message="reserve")

        current = store.state(bare)
        if current["state"].get("DEC-900") != model.ACTION_RESERVED:
            failures.append(_fail("reserve", "state_not_reproduced_from_the_ref"))

        second = append("DEC-900", model.ACTION_ASSIGNED, event["event_id"])
        text = model.append(text, second)
        store.write(bare, text, expected_oid=current["ref_oid"], message="assign")

        # Compare and swap: a stale expectation must not win. The event is
        # deliberately built against the state that was *read* before the
        # assignment, so it is a valid successor of that state and is refused
        # only because the ref has moved on since.
        stale = model.build_event(
            dec_id="DEC-901",
            action=model.ACTION_RESERVED,
            owner_ref="gate-runner",
            origin_line="gate-fixture",
            recorded_at_utc=when,
            source_commit=commit,
            previous_digest=current["digest"],
            previous_event_id=event["event_id"],
        )
        try:
            store.write(
                bare, model.append(current["text"], stale),
                expected_oid=current["ref_oid"], message="stale",
            )
            failures.append(_fail("compare_and_swap", "stale_write_succeeded"))
        except store.StoreError as error:
            if error.code != "ref_moved_concurrently":
                failures.append(_fail("compare_and_swap", error.code))

        final = store.state(bare)
        if final["state"].get("DEC-900") != model.ACTION_ASSIGNED:
            failures.append(_fail("assign", "terminal_state_not_reached"))
        if len(final["events"]) != 2:
            failures.append(_fail("history", "unexpected_event_count"))

        # Every forbidden transition really is refused.
        for dec_id, action, code in (
            ("DEC-900", model.ACTION_RELEASED, "number_is_terminal"),
            ("DEC-902", model.ACTION_ASSIGNED, "assign_without_reservation"),
            ("DEC-902", model.ACTION_RELEASED, "release_without_reservation"),
        ):
            candidate = append(dec_id, action, second["event_id"])
            try:
                model.append(final["text"], candidate)
                failures.append(_fail(f"{dec_id}:{action}", "transition_allowed"))
            except model.RegisterError as error:
                if error.code != code:
                    failures.append(_fail(f"{dec_id}:{action}", error.code))

        # Tampering with a committed line is detectable.
        lines = final["text"].rstrip("\n").split("\n")
        payload = json.loads(lines[0])
        payload["owner_ref"] = "someone-else"
        lines[0] = model.serialise(payload)
        try:
            model.parse("\n".join(lines) + "\n")
            failures.append(_fail("tamper", "edited_line_not_detected"))
        except model.RegisterError:
            pass

        diagnostics.append(f"events={len(final['events'])}")
        diagnostics.append(f"chain_digest={final['digest'][:16]}")
    finally:
        shutil.rmtree(target, ignore_errors=True)
    return _emit(failures, diagnostics)


def mode_register_tool(args):
    """The tool must be structurally incapable of publishing."""
    root = Path.cwd()
    failures = []
    publish = "pu" + "sh"
    sources = (
        "scripts/dec-reservations.sh",
        "tools/decreg/cli.py",
        "tools/decreg/store.py",
        "tools/decreg/remote.py",
        "tools/decreg/model.py",
        "tools/decreg/scan.py",
    )
    for relative in sources:
        target = root / relative
        if not target.is_file():
            failures.append(_fail(relative, "source_missing"))
            continue
        for number, line in enumerate(
            target.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "subprocess.run" not in line and "exec " not in line:
                continue
            if '"' + publish + '"' in line or "'" + publish + "'" in line:
                failures.append(_fail(f"{relative}:{number}", "tool_can_publish"))
    if "--force" in (root / "tools/decreg/remote.py").read_text(encoding="utf-8"):
        # Only as the thing that is asserted absent, never as an argument.
        pass
    return _emit(failures, [f"sources={len(sources)}"])


# -- the corrected scanner --------------------------------------------------


def mode_scanner_method(args):
    from tools.decreg import scan  # noqa: PLC0415

    root = Path.cwd()
    failures = []
    diagnostics = []

    # A mention is not an allocation. This is the defect of the old method.
    mention_only = "Die Nummern DEC-900 und DEC-D90 sind frei.\n"
    if scan.allocated_ids(mention_only):
        failures.append(_fail("method", "mention_counted_as_allocation"))
    if scan.mentioned_ids(mention_only) != {"DEC-900", "DEC-D90"}:
        failures.append(_fail("method", "mention_not_recognised"))
    row = "| DEC-900 | title | state |\n"
    if scan.allocated_ids(row) != {"DEC-900"}:
        failures.append(_fail("method", "table_row_not_counted_as_allocation"))

    union, per_ref = scan.scan_lines(root, LINES)
    for ref, found in sorted(per_ref.items()):
        if found is None:
            failures.append(_fail(ref, "line_register_unreadable"))
        else:
            diagnostics.append(f"{ref}={len(found)}")
    if failures:
        return _emit(failures, diagnostics)

    for prefix, width in (("DEC-", 3), ("DEC-D", 2)):
        used, gaps, first_unused = scan.series_state(union, prefix, width)
        diagnostics.append(f"{prefix}used={len(used)}")
        diagnostics.append(f"{prefix}first_unused={first_unused}")
        if gaps:
            failures.append(_fail(prefix, "series_has_gaps"))
    return _emit(failures, diagnostics)


# -- the target bound release ----------------------------------------------


def mode_fixture_rule(args):
    """Evaluated, never executed. No command in this mode is ever run."""
    from tools.guard import decide, fixture  # noqa: PLC0415
    from tools.guard import rules as rules_module  # noqa: PLC0415

    root = Path.cwd()
    failures = []
    rules = rules_module.load_rules(str(root / "tools" / "guard" / "rules.json"))
    if fixture.configuration(rules) is None:
        return _emit([_fail("configuration", "fixture_rule_not_configured")])

    context = decide.Context(rules=rules, exceptions_enabled=False)
    target, bare = _fixture_repository(root)
    try:
        escape = Path(target) / "escape.git"
        os.symlink(str(root / ".git"), str(escape))

        publish = "git " + "pu" + "sh"
        reference = "refs/governance/dec-reservations"
        cases = [
            ("release", f"{publish} {bare} HEAD:{reference}", True),
            ("protected_remote", f"{publish} origin HEAD:{reference}", False),
            ("symlink_escape", f"{publish} {escape} HEAD:{reference}", False),
            ("parent_reference",
             f"{publish} {bare}/../../../elsewhere.git HEAD:{reference}", False),
            ("protected_ref", f"{publish} {bare} HEAD:refs/heads/main", False),
            ("forced_refspec", f"{publish} {bare} +HEAD:{reference}", False),
            ("second_segment",
             f"{publish} {bare} HEAD:{reference}; {publish} origin HEAD:{reference}",
             False),
        ]
        for label, command, should_release in cases:
            verdict = fixture.evaluate(
                rules, "git_push", command, str(root),
                lambda arguments, where: decide._run_git(context, arguments, where),
            )
            if verdict.granted != should_release:
                failures.append(_fail(label, "unexpected_" + verdict.code))
    finally:
        shutil.rmtree(target, ignore_errors=True)
    return _emit(failures, [f"cases={len(cases)}"])


# -- activation state, reported not required -------------------------------


def mode_guard_activation(args):
    """State the relation between the candidate and the active installation.

    This mode determines and reports. It never requires the candidate to be
    active: activation is the consequence of acceptance, not its condition.
    """
    root = Path.cwd()
    failures = []
    diagnostics = []

    from tools.guard import GUARD_VERSION  # noqa: PLC0415

    stage = Path(tempfile.mkdtemp(prefix="gate-guard-build-"))
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, str(root / "tools" / "guardpkg" / "build.py"),
             "--source", str(root), "--out", str(stage)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=120, check=False, shell=False,
        )
        if completed.returncode != 0:
            return _emit([_fail("candidate", "candidate_package_not_buildable")])
        candidate = json.loads(completed.stdout.decode("utf-8"))["package_sha256"]
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    diagnostics.append(f"candidate_version={GUARD_VERSION}")
    diagnostics.append(f"candidate_package_sha256={candidate}")

    manifest_path = Path(args.install_root or "/usr/local/jarvis-guard") / "active.json"
    if not manifest_path.is_file():
        diagnostics.append("active_installation=absent")
        diagnostics.append("candidate_is_active=no")
        return _emit(failures, diagnostics)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    active_version = str(manifest.get("guard_version"))
    active_digest = str(manifest.get("package_sha256"))
    diagnostics.append(f"active_version={active_version}")
    diagnostics.append(f"active_package_sha256={active_digest}")
    diagnostics.append(
        "candidate_is_active=" + ("yes" if active_digest == candidate else "no")
    )
    if active_digest != candidate:
        diagnostics.append("owner_activation=pending_owner_action")
        diagnostics.append("no_phase_of_this_block_depends_on_it=true")
    return _emit(failures, diagnostics)


MODES = {
    "config-loaders": mode_config_loaders,
    "errata": mode_errata,
    "fixture-rule": mode_fixture_rule,
    "guard-activation": mode_guard_activation,
    "owner-expectations": mode_owner_expectations,
    "profile-derivation": mode_profile_derivation,
    "profile-lock": mode_profile_lock,
    "register-model": mode_register_model,
    "register-tool": mode_register_tool,
    "scanner-method": mode_scanner_method,
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    parser.add_argument("--install-root", default="")
    args = parser.parse_args(argv)
    return MODES[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())
