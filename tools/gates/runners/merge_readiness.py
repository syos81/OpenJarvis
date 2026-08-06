#!/usr/bin/env python3
"""Tooling merge readiness — checks only, never a merge.

Modes:

``refs``      source and target are exactly the intended lines
``scope``     the complete incoming diff stays inside the tooling/governance
              allowlist: no product code, no product configuration, no
              migration, no binary, no real evidence, no raw log
``blocks``    the module closing gates of the required blocks are valid,
              current and green
``evidence``  feature lists and sanitized evidence are complete
``no-merge``  this runner provably performs no merging git operation

The runner never calls ``git merge``, ``git rebase`` or ``git cherry-pick``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import evidence as evidence_module  # noqa: E402
from tools.gates import features as features_module  # noqa: E402
from tools.gates import gitutil  # noqa: E402
from tools.gates import manifest as manifest_module  # noqa: E402
from tools.gates import paths as gate_paths  # noqa: E402
from tools.gates import statuses  # noqa: E402
from tools.gates.runners import _report  # noqa: E402

POLICY = Path("config/governance/tooling-merge.json")
FORBIDDEN_GIT_VERBS = ("merge", "rebase", "cherry-pick", "reset", "push")
GREEN = (statuses.PASS, statuses.PASS_WITH_BASELINE)


def _fail(identifier, code):
    return _report.failure(identifier, category="merge_readiness", code=code)


def load_policy(root):
    return json.loads((root / POLICY).read_text(encoding="utf-8"))


def mode_refs(root):
    policy = load_policy(root)
    failures = []
    diagnostics = []
    if policy["executes_merge"] is not False:
        failures.append(_fail("policy", "policy_would_execute_merge"))
    for key in ("source_ref", "target_ref"):
        oid = gitutil.resolve_commit(policy[key], cwd=root)
        if not oid:
            failures.append(_fail(policy[key], f"{key}_unresolved"))
        else:
            diagnostics.append(f"{key}={policy[key]}@{oid[:12]}")
    if policy["source_ref"] != "tooling/gates-v1":
        failures.append(_fail("source_ref", "source_ref_not_the_intended_line"))
    if policy["target_ref"] != "spike/calendar-foundation-intel-2026-08-04":
        failures.append(_fail("target_ref", "target_ref_not_the_intended_line"))
    if policy.get("direction") != "incoming_only":
        failures.append(_fail("direction", "reverse_merge_allowed"))
    return failures, diagnostics


def incoming_paths(root, policy):
    """Paths the source would bring into the target — read only."""
    code, out, _ = gitutil.run_git(
        [
            "diff",
            "--name-only",
            "--no-renames",
            f"{policy['target_ref']}...{policy['source_ref']}",
        ],
        cwd=root,
    )
    if code != 0:
        return None
    return sorted(line.strip() for line in out.splitlines() if line.strip())


def mode_scope(root):
    import fnmatch

    policy = load_policy(root)
    failures = []
    paths = incoming_paths(root, policy)
    if paths is None:
        return [_fail("diff", "incoming_diff_unavailable")], []
    for path in paths:
        if any(
            fnmatch.fnmatch(path, pattern) for pattern in policy["forbidden_paths"]
        ):
            failures.append(_fail(path, "product_path_in_merge_scope"))
            continue
        if not any(
            fnmatch.fnmatch(path, pattern) for pattern in policy["allowed_paths"]
        ):
            failures.append(_fail(path, "path_outside_allowlist"))
        if Path(path).suffix.lower() in policy["forbidden_suffixes"]:
            failures.append(_fail(path, "binary_or_evidence_in_merge_scope"))
        if path.startswith(f"{gate_paths.RUNTIME_DIR_NAME}/"):
            failures.append(_fail(path, "raw_log_in_merge_scope"))
    return failures, [f"incoming_paths={len(paths)}"]


def mode_blocks(root):
    policy = load_policy(root)
    failures = []
    diagnostics = []
    head = gitutil.head_commit(cwd=root)
    results_dir = gate_paths.results_dir(root)
    for block_id in policy["required_module_final_blocks"]:
        manifest_path = manifest_module.manifest_path_for(root, block_id)
        if not manifest_path.is_file():
            failures.append(_fail(block_id, "block_manifest_missing"))
            continue
        try:
            manifest = manifest_module.load(manifest_path)
        except manifest_module.ManifestError:
            failures.append(_fail(block_id, "block_manifest_invalid"))
            continue
        result_path = results_dir / f"{block_id}.module-final.json"
        if not result_path.is_file():
            failures.append(_fail(block_id, "module_final_result_missing"))
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except ValueError:
            failures.append(_fail(block_id, "module_final_result_unreadable"))
            continue
        if result.get("commit") != head:
            failures.append(_fail(block_id, "module_final_result_stale"))
        if result.get("manifest_digest") != manifest.digest:
            failures.append(_fail(block_id, "module_final_manifest_changed"))
        if result.get("status") not in GREEN:
            failures.append(_fail(block_id, "module_final_not_green"))
        diagnostics.append(f"{block_id}={result.get('status')}")
    return failures, diagnostics


def _inherited_blocks(root, policy, failures, diagnostics):
    """Inherited blocks are proved by content, not by foreign runtime results."""
    for entry in policy.get("inherited_blocks", []):
        block_id = entry["block_id"]
        manifest_path = manifest_module.manifest_path_for(root, block_id)
        if not manifest_path.is_file():
            failures.append(_fail(block_id, "inherited_manifest_missing"))
            continue
        manifest = manifest_module.load(manifest_path)
        lineage = manifest.data["feature_lineage"]
        report = features_module.validate_lineage(
            lineage_path=root / lineage["lineage_file"],
            predecessor_path=root / lineage["predecessor_file"],
            worktree=root,
            manifest=manifest,
            own_prefix=lineage.get("own_prefix"),
        )
        own = report.get("own_counts") or {}
        if report["status"] != statuses.PASS:
            failures.append(_fail(block_id, "inherited_feature_lineage_incomplete"))
        if own.get("expected") != lineage.get("own_expected"):
            failures.append(_fail(block_id, "inherited_feature_count_mismatch"))
        code, _, _ = gitutil.run_git(
            ["cat-file", "-e", f"{entry['bound_commit']}^{{commit}}"], cwd=root
        )
        if code != 0:
            failures.append(_fail(block_id, "bound_commit_unavailable"))
        diagnostics.append(
            f"{block_id}@{entry['bound_commit'][:12]}="
            f"{own.get('verified')}/{own.get('expected')}"
        )


def mode_evidence(root):
    policy = load_policy(root)
    failures = []
    diagnostics = []
    evidence_dir = gate_paths.evidence_dir(root)
    _inherited_blocks(root, policy, failures, diagnostics)
    for block_id in policy["required_module_final_blocks"]:
        manifest_path = manifest_module.manifest_path_for(root, block_id)
        if not manifest_path.is_file():
            failures.append(_fail(block_id, "block_manifest_missing"))
            continue
        manifest = manifest_module.load(manifest_path)
        lineage = manifest.data["feature_lineage"]
        report = features_module.validate_lineage(
            lineage_path=root / lineage["lineage_file"],
            predecessor_path=root / lineage["predecessor_file"],
            worktree=root,
            manifest=manifest,
        )
        if report["status"] != statuses.PASS:
            failures.append(_fail(block_id, "feature_lineage_not_complete"))
        diagnostics.append(
            f"{block_id}_features={report['counts']['mapped']}/"
            f"{report['counts']['expected']}"
        )
        for phase in manifest_module.PHASES:
            if not manifest.phase_definition(phase)["required"]:
                continue
            record_path = evidence_dir / f"{block_id}.{phase}.json"
            if not record_path.is_file():
                failures.append(_fail(f"{block_id}.{phase}", "evidence_missing"))
                continue
            try:
                evidence_module.validate_evidence(
                    json.loads(record_path.read_text(encoding="utf-8"))
                )
            except (ValueError, evidence_module.EvidenceSchemaError):
                failures.append(_fail(f"{block_id}.{phase}", "evidence_invalid"))
    return failures, diagnostics


def git_verbs_used(source, filename="<runner>"):
    """Every git subcommand this source actually invokes."""
    import ast

    verbs = set()
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name not in ("run_git", "git_text"):
            continue
        if not node.args:
            continue
        argument = node.args[0]
        if isinstance(argument, (ast.List, ast.Tuple)) and argument.elts:
            first = argument.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                verbs.add(first.value)
    return sorted(verbs)


def mode_no_merge(root):
    """The readiness runner may never invoke a merging git operation."""
    failures = []
    source = Path(__file__).read_text(encoding="utf-8")
    used = git_verbs_used(source, filename=Path(__file__).name)
    for verb in used:
        if verb in FORBIDDEN_GIT_VERBS:
            failures.append(_fail(verb, "merging_git_verb_in_runner"))
    policy = load_policy(root)
    for action in ("merge", "rebase", "cherry_pick"):
        if action not in policy["forbidden_actions"]:
            failures.append(_fail(action, "forbidden_action_not_declared"))
    return failures, ["merge_execution=never", f"git_verbs={','.join(used)}"]


def mode_collisions_blocking(root):
    """Integration context: an unresolved collision blocks the integration.

    The same collision that B0a-2 may close over — because it is completely
    documented — must stop the later integration until the renumbering has
    actually been carried out.
    """
    from tools.gates import governance

    failures = []
    registry = governance.load_json(
        root / "config" / "governance" / "decision-collisions.json"
    )
    detected, error = governance.detect_collisions(registry, root)
    if error:
        return [_fail("collision_detection", error)], [], _report.FAILED
    for identifier in sorted(detected):
        failures.append(_fail(identifier, "integration_blocked_by_open_collision"))
    diagnostics = [f"open_collisions={len(detected)}"]
    if registry.get("status") == "resolved":
        diagnostics.append("collision_registry=resolved")
        if registry.get("open_collisions") != 0:
            failures.append(_fail("registry", "open_collision_count_not_zero"))
    elif registry.get("resolution", {}).get("resolved_in_b0a_2") is not False:
        failures.append(_fail("resolution", "collision_resolved_outside_integration"))
    if failures:
        # Documented, deliberately deferred external precondition: the
        # integration is not ready. That is `blocked`, never a green result and
        # never a `fail` of the governance block that documented it.
        return failures, diagnostics, _report.BLOCKED
    return failures, diagnostics, _report.PASSED


MODES = {
    "collisions-blocking": mode_collisions_blocking,
    "refs": mode_refs,
    "scope": mode_scope,
    "blocks": mode_blocks,
    "evidence": mode_evidence,
    "no-merge": mode_no_merge,
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    args = parser.parse_args(argv)
    root = Path.cwd()
    result = MODES[args.mode](root)
    reason_code = None
    if len(result) == 3:
        failures, diagnostics, outcome = result
        if outcome == _report.BLOCKED:
            reason_code = "integration_blocked_by_open_collision"
    else:
        failures, diagnostics = result
        outcome = _report.PASSED if not failures else _report.FAILED
    return _report.emit(outcome, failures, diagnostics, reason_code=reason_code)


if __name__ == "__main__":
    sys.exit(main())
