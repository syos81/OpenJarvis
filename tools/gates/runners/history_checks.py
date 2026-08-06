#!/usr/bin/env python3
"""Historical acceptance, current preservation and commit integrity.

The two are strictly separated:

``historical-integrity``
    A historical acceptance manifest is bound to a concrete commit and to
    immutable reference object ids. It is **not** re-executed against the
    current branch tip. Only presence, hash integrity, correct binding and
    unchanged statement are verified.

``preservation``
    The current preservation manifest is line independent. It is evaluated
    against whatever HEAD the run sees and uses no branch name, no remote
    tip, no branch topology and no branch specific path allowlist.

``base-commit-unchanged``
    The published B0a-3 commit keeps its tree and parents, stays an ancestor
    of HEAD, and no local amend happened after it.

``errata``
    The B0a-3 erratum states the complete local history of that commit.

``commit-plan``
    The declared commit plan of this block is honoured.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates.runners import _report  # noqa: E402
from tools.guard import rules as guard_rules  # noqa: E402

HISTORY_DIR = Path("config/gates/history")
PRESERVATION = Path("config/gates/preservation/calendar-line.preservation.json")
ERRATA = Path("docs/governance/b0a-3-errata.md")
COMMIT_PLAN = HISTORY_DIR / "b0a-4-commit-plan.json"

#: Tokens the B0a-3 erratum must state. Each one is a finding the closing
#: report of that block did not name.
ERRATA_TOKENS = (
    "d2bce8f",
    "b872f91",
    "ad84559",
    "a093687",
    "8e6e206",
    "4e47144",
    "commit --amend",
    "origin",
    "Merge-Commit",
    "Entstehungsgeschichte",
    "tools/gates",
    "fail-open",
)

#: A preservation manifest must not smuggle a moving reference back in.
FORBIDDEN_PRESERVATION_TOKENS = (
    "origin/",
    "refs/remotes",
    "spike/calendar-foundation",
    "jarvis/rebuild-v1",
    "tooling/gates-v1",
)


def _fail(identifier, code):
    return _report.failure(identifier, category="history", code=code)


def _git(args):
    completed = subprocess.run(  # noqa: S603 - fixed argv
        ["git"] + list(args),
        cwd=str(Path.cwd()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        shell=False,
        check=False,
    )
    return completed.returncode, completed.stdout


def mode_historical_integrity(args):
    root = Path.cwd()
    failures = []
    diagnostics = []
    directory = root / HISTORY_DIR
    manifests = sorted(directory.glob("*.acceptance.json"))
    if not manifests:
        return _report.emit(
            _report.FAILED, [_fail("history", "no_acceptance_manifest")]
        )
    for path in manifests:
        document = json.loads(path.read_text(encoding="utf-8"))
        block = document.get("block_id", path.stem)
        if document.get("kind") != "historical_acceptance":
            failures.append(_fail(block, "not_a_historical_manifest"))
            continue
        if document.get("reexecution_policy", {}).get(
            "rerun_against_current_head"
        ) is not False:
            failures.append(_fail(block, "historical_manifest_reruns_against_head"))
        commit = document.get("acceptance_commit", "")
        if not re.match(r"^[0-9a-f]{40}$", commit):
            failures.append(_fail(block, "acceptance_commit_not_full_oid"))
            continue
        code, _out = _git(["cat-file", "-e", commit + "^{commit}"])
        if code != 0:
            failures.append(_fail(block, "acceptance_commit_missing"))
            continue
        for artifact in document.get("committed_artifacts", []):
            relative = artifact["path"]
            code, blob = _git(["cat-file", "blob", f"{commit}:{relative}"])
            if code != 0:
                failures.append(
                    _fail(f"{block}:{relative}", "historical_artifact_missing")
                )
                continue
            if hashlib.sha256(blob).hexdigest() != artifact["blob_sha256"]:
                failures.append(
                    _fail(f"{block}:{relative}", "historical_artifact_changed")
                )
        present = 0
        absent = 0
        for evidence in document.get("runtime_evidence", []):
            target = root / evidence["path"]
            if not target.is_file():
                absent += 1
                continue
            present += 1
            raw = target.read_bytes()
            if hashlib.sha256(raw).hexdigest() != evidence["sha256"]:
                failures.append(
                    _fail(f"{block}:{evidence['phase']}", "evidence_hash_mismatch")
                )
                continue
            payload = json.loads(raw.decode("utf-8"))
            for field, recorded in (
                ("status", evidence["recorded_status"]),
                ("commit", evidence["recorded_commit"]),
                ("manifest_digest", evidence["recorded_manifest_digest"]),
                ("engine_version", evidence["recorded_engine_version"]),
                ("platform_class", evidence["recorded_platform_class"]),
            ):
                if payload.get(field) != recorded:
                    failures.append(
                        _fail(
                            f"{block}:{evidence['phase']}:{field}",
                            "evidence_statement_changed",
                        )
                    )
        diagnostics.append(
            f"{block}: artifacts={len(document.get('committed_artifacts', []))} "
            f"evidence_present={present} evidence_absent={absent}"
        )
        if absent and document["reexecution_policy"].get(
            "runtime_evidence_absent"
        ) != "not_applicable":
            failures.append(_fail(block, "absent_evidence_without_declared_rule"))
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def _check_invariant(root, invariant):
    kind = invariant["kind"]
    if kind == "file_present":
        return (root / invariant["path"]).exists()
    if kind == "files_contain":
        needle = invariant["needle"]
        for relative in invariant["paths"]:
            target = root / relative
            if not target.is_file():
                return False
            if needle not in target.read_text(encoding="utf-8", errors="replace"):
                return False
        return True
    if kind in ("python_sequence", "python_set"):
        module = importlib.import_module(invariant["module"])
        value = getattr(module, invariant["attribute"])
        if kind == "python_sequence":
            return list(value) == list(invariant["expected"])
        return sorted(set(value)) == sorted(invariant["expected"])
    if kind == "guard_codes_superset":
        rules = guard_rules.load_rules(root / "tools" / "guard" / "rules.json")
        return set(invariant["expected"]).issubset(set(rules.codes()))
    return False


def mode_preservation(args):
    root = Path.cwd()
    failures = []
    diagnostics = []
    document = json.loads((root / PRESERVATION).read_text(encoding="utf-8"))
    if document.get("kind") != "current_preservation":
        failures.append(_fail("preservation", "not_a_preservation_manifest"))
    raw = (root / PRESERVATION).read_text(encoding="utf-8")
    for token in FORBIDDEN_PRESERVATION_TOKENS:
        if token in raw:
            failures.append(_fail("preservation", "line_dependent_input"))

    lineage_path = root / document["feature_preservation"]["lineage_file"]
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    expected = document["feature_preservation"]["expected_required_by_prefix"]
    for prefix, count in sorted(expected.items()):
        present = [
            feature
            for feature in lineage["features"]
            if str(feature["feature_id"]).startswith(prefix)
        ]
        required = [feature for feature in present if feature.get("required")]
        passing = [
            feature for feature in required if feature.get("status") == "pass"
        ]
        diagnostics.append(
            f"{prefix} required={len(required)} passing={len(passing)} "
            f"expected={count}"
        )
        if len(required) != count:
            failures.append(_fail(f"preserve.{prefix}", "required_count_mismatch"))
        if len(passing) != count:
            failures.append(_fail(f"preserve.{prefix}", "preserved_feature_not_passing"))
        for feature in required:
            if not str(feature.get("current_location", "")).strip():
                failures.append(
                    _fail(feature["feature_id"], "feature_location_missing")
                )

    for invariant in document.get("invariants", []):
        identifier = invariant["invariant_id"]
        try:
            ok = _check_invariant(root, invariant)
        except Exception:  # noqa: BLE001 - an unverifiable invariant is a failure
            ok = False
        if not ok:
            failures.append(_fail(identifier, "invariant_violated"))
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_base_commit_unchanged(args):
    root = Path.cwd()
    failures = []
    diagnostics = []
    plan = json.loads((root / COMMIT_PLAN).read_text(encoding="utf-8"))
    binding = plan["base_commit_binding"]
    commit = binding["commit"]

    code, _out = _git(["cat-file", "-e", commit + "^{commit}"])
    if code != 0:
        return _report.emit(
            _report.FAILED, [_fail("base_commit", "base_commit_missing")]
        )
    code, out = _git(["rev-parse", commit + "^{tree}"])
    tree = out.decode().strip()
    if tree != binding["tree"]:
        failures.append(_fail("base_commit", "base_commit_tree_changed"))
    code, out = _git(["rev-list", "--parents", "-n", "1", commit])
    parts = out.decode().split()
    if parts[1:] != binding["parents"]:
        failures.append(_fail("base_commit", "base_commit_parents_changed"))
    code, out = _git(["show", "-s", "--format=%aI|%cI", commit])
    author_date, _, committer_date = out.decode().strip().partition("|")
    if author_date != binding["author_date"]:
        failures.append(_fail("base_commit", "base_commit_author_date_changed"))
    if committer_date != binding["committer_date"]:
        failures.append(_fail("base_commit", "base_commit_committer_date_changed"))
    code, _out = _git(["merge-base", "--is-ancestor", commit, "HEAD"])
    if code != 0:
        failures.append(_fail("base_commit", "base_commit_not_ancestor_of_head"))

    code, out = _git(["rev-list", "--count", commit + "..HEAD"])
    try:
        ahead = int(out.decode().strip() or "0")
    except ValueError:
        ahead = -1
    diagnostics.append(f"commits_since_base={ahead}")
    if ahead > int(plan["max_commits"]):
        failures.append(_fail("commit_plan", "more_commits_than_declared"))
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_commit_plan(args):
    root = Path.cwd()
    failures = []
    diagnostics = []
    plan = json.loads((root / COMMIT_PLAN).read_text(encoding="utf-8"))
    start = plan["start_commit"]

    code, out = _git(["reflog", "show", "--format=%H %gs", "-n", "80"])
    if code != 0:
        return _report.emit(
            _report.BLOCKED, [_fail("reflog", "reflog_unavailable")]
        )
    lines = out.decode("utf-8", "replace").splitlines()
    seen_start = False
    amends_after_start = 0
    for line in lines:
        object_id, _, subject = line.partition(" ")
        if object_id.startswith(start[:7]) or object_id == start:
            seen_start = True
            break
        if "commit (amend)" in subject:
            amends_after_start += 1
        for forbidden in ("rebase", "cherry-pick", "reset: moving to"):
            if forbidden in subject and "reset: moving to HEAD" not in subject:
                failures.append(_fail("reflog", "forbidden_history_operation"))
    diagnostics.append(f"amends_after_start={amends_after_start}")
    diagnostics.append(f"start_commit_seen_in_reflog={seen_start}")
    if amends_after_start:
        failures.append(_fail("commit_plan", "amend_inside_the_block"))
    if plan.get("third_binding_commit_required") is not False:
        failures.append(_fail("commit_plan", "undeclared_third_commit"))
    if plan.get("push_status") != "not_performed_owner_action":
        failures.append(_fail("commit_plan", "push_status_not_owner_action"))
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_errata(args):
    root = Path.cwd()
    failures = []
    path = root / ERRATA
    if not path.is_file():
        return _report.emit(_report.FAILED, [_fail("errata", "errata_missing")])
    text = path.read_text(encoding="utf-8")
    for token in ERRATA_TOKENS:
        if token not in text:
            failures.append(_fail(f"errata.{token}", "errata_statement_missing"))
    if "Addendum" not in text and "Errata" not in text:
        failures.append(_fail("errata", "errata_not_marked"))
    # The erratum documents; it must not claim to rewrite the historical record.
    for forbidden in ("umgeschrieben", "rewritten", "ersetzt die urspr"):
        if forbidden in text:
            failures.append(_fail("errata", "errata_claims_rewrite"))
    return _report.emit(_report.PASSED if not failures else _report.FAILED, failures)


MODES = {
    "base-commit-unchanged": mode_base_commit_unchanged,
    "commit-plan": mode_commit_plan,
    "errata": mode_errata,
    "historical-integrity": mode_historical_integrity,
    "preservation": mode_preservation,
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    args = parser.parse_args(argv)
    try:
        return MODES[args.mode](args)
    except (OSError, ValueError, KeyError) as exc:
        return _report.emit(
            _report.ERROR,
            [_fail(args.mode, "runner_error")],
            [re.sub(r"/[^\s]*", "<path>", str(exc))[:200]],
        )


if __name__ == "__main__":
    sys.exit(main())
