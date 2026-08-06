#!/usr/bin/env python3
"""Governance runner for B0a-2.

Modes:

``collisions``  every declared collision side is verified against its primary
                source at the declared commit, and the complete ID stock of
                both lines is compared so an unregistered collision or a
                silent cleanup cannot pass
``id-freeze``   no new DEC or ADR number, no new ADR file, no reservation
``ambient``     the placeholder is present everywhere it is required and was
                neither replaced nor assigned to an existing decision
``citations``   every DEC/ADR reference in normative governance prose carries
                line and exact title
``order``       the canonical delivery order satisfies every declared rule
``consistency`` document table and machine readable source agree
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import governance  # noqa: E402
from tools.gates import guardbase  # noqa: E402
from tools.gates import gitutil  # noqa: E402
from tools.gates.runners import _report  # noqa: E402

COLLISIONS = Path("config/governance/decision-collisions.json")
ID_MIGRATION = Path("config/governance/b0a-3-id-migration.json")
CITATIONS = Path("config/governance/decision-citations.json")
ORDER = Path("config/governance/delivery-order.json")
AMBIENT = Path("config/governance/ambient-placeholder.json")
ORDER_DOC = Path("docs/governance/b0a-2-delivery-order.md")
MERGE_ADDENDUM = Path("docs/governance/b0a-2-tooling-merge-addendum.md")
GOVERNANCE_DOCS = Path("docs/governance")


def _fail(identifier, code):
    return _report.failure(identifier, category="governance", code=code)


def mode_collisions(root):
    failures = []
    diagnostics = []
    registry = governance.load_json(root / COLLISIONS)

    if registry.get("status") == "resolved":
        # After the integration the registry is a historical resolution
        # record: it must prove zero open collisions, not describe them.
        for identifier, code in governance.verify_resolution(registry, root):
            failures.append(_fail(identifier, code))
        detected, error = governance.detect_collisions(registry, root)
        if error:
            failures.append(_fail("collision_detection", error))
        for identifier in sorted(detected):
            failures.append(_fail(identifier, "collision_still_open"))
        if registry.get("open_collisions") != 0:
            failures.append(_fail("registry", "open_collision_count_not_zero"))
        diagnostics.append(f"open_collisions={len(detected)}")
        diagnostics.append(
            f"historical_resolutions={len(registry.get('historical_resolution', []))}"
        )
        return failures, diagnostics

    for identifier, code in governance.verify_collision_sides(registry, root):
        failures.append(_fail(identifier, code))

    registered = {collision["id"] for collision in registry["collisions"]}
    detected, error = governance.detect_collisions(registry, root)
    if error:
        failures.append(_fail("collision_detection", error))
    for identifier in sorted(detected - registered):
        failures.append(_fail(identifier, "collision_unregistered"))
    for identifier in sorted(registered - detected):
        failures.append(_fail(identifier, "collision_silently_resolved"))
    diagnostics.append(f"registered_collisions={len(registered)}")
    diagnostics.append(f"detected_collisions={len(detected)}")
    if registry.get("resolution", {}).get("resolved_in_b0a_2") is not False:
        failures.append(_fail("resolution", "collision_resolved_in_b0a_2"))
    return failures, diagnostics


def mode_id_freeze(root):
    failures = []
    diagnostics = []
    citations = governance.load_json(root / CITATIONS)
    known = {entry["id"] for entry in citations["citations"]}

    try:
        base = guardbase.derive_for_repository(root)["base_commit"]
    except guardbase.GuardBaseError as exc:
        return [_fail("guard_base", exc.reason_code)], diagnostics

    # An approved, fixed renumbering declares exactly which decision paths it
    # may touch. Without such a declaration nothing may touch them at all.
    migration_path = root / ID_MIGRATION
    allowed_decision_paths = set()
    declared_ids = set()
    if migration_path.is_file():
        migration = governance.load_json(migration_path)
        for entry in migration.get("mappings", []):
            declared_ids.add(entry["new_id"])
            for key in ("old_path", "new_path"):
                if entry.get(key):
                    allowed_decision_paths.add(entry[key])
        allowed_decision_paths.add(governance.REGISTER_PATH)
        diagnostics.append(f"declared_renumberings={len(migration.get('mappings', []))}")

    touched = set()
    for args in (
        ["log", "--name-only", "--no-renames", "--pretty=format:", f"{base}..HEAD"],
        ["diff", "--name-only", "--cached", "HEAD"],
        ["diff", "--name-only", "HEAD"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        code, out, _ = gitutil.run_git(args, cwd=root)
        if code == 0:
            touched.update(line.strip() for line in out.splitlines() if line.strip())
    for path in sorted(touched):
        if path.startswith("docs/adr/") and path not in allowed_decision_paths:
            failures.append(_fail(path, "new_adr_file"))
        if path == governance.REGISTER_PATH and path not in allowed_decision_paths:
            failures.append(_fail(path, "decision_register_modified"))
    diagnostics.append(f"touched_paths={len(touched)}")

    # No ADR id may exist that neither existed at the guard base nor is a
    # declared renumbering target.
    base_adr = governance.adr_entries(base, root) or {}
    for adr_file in sorted((root / "docs" / "adr").glob("ADR-*.md")):
        match = re.match(r"^(ADR-\d{4})-", adr_file.name)
        if not match:
            continue
        identifier = match.group(1)
        if identifier not in base_adr and identifier not in declared_ids:
            failures.append(_fail(adr_file.name, "unknown_adr_file"))
    diagnostics.append(f"adr_ids_at_base={len(base_adr)}")

    excluded = governance.normative_exclusions(root)
    for document in sorted(root.glob(f"{GOVERNANCE_DOCS}/*.md")):
        relative = document.relative_to(root)
        if str(relative) in excluded:
            continue
        text = document.read_text(encoding="utf-8")
        for line in text.splitlines():
            if governance.DEC_ROW_RE.match(line.strip()):
                failures.append(_fail(str(relative), "new_decision_row_defined"))
                break
        prose = governance.strip_code(text)
        for match in list(governance.DEC_TOKEN_RE.finditer(prose)) + list(
            governance.ADR_TOKEN_RE.finditer(prose)
        ):
            if match.group(0) not in known:
                failures.append(_fail(str(relative), "unknown_decision_id"))
                break
        if re.search(r"reserv\w*\s+(?:für\s+)?ADR-\d{4}", prose, re.IGNORECASE):
            failures.append(_fail(str(relative), "adr_reservation"))
    return failures, diagnostics


def mode_ambient(root):
    failures = []
    diagnostics = []
    config = governance.load_json(root / AMBIENT)
    placeholder = config["placeholder"]
    if placeholder != governance.AMBIENT_PLACEHOLDER:
        failures.append(_fail("placeholder", "ambient_placeholder_replaced"))
    for relative in config["required_locations"]:
        target = root / relative
        if not target.is_file():
            failures.append(_fail(relative, "ambient_location_missing"))
            continue
        if placeholder not in target.read_text(encoding="utf-8"):
            failures.append(_fail(relative, "ambient_placeholder_missing"))
    diagnostics.append(f"required_locations={len(config['required_locations'])}")

    for adr_file in sorted((root / "docs" / "adr").glob("*.md")):
        if "ambient" in adr_file.name.lower():
            failures.append(_fail(adr_file.name, "ambient_adr_file_created"))

    order = governance.load_json(root / ORDER)
    forbidden_decision = config["forbidden"]["assigned_to_decision"]
    for element in order["elements"]:
        if element["canonical_name"] != "Ambient Interaction V1":
            continue
        ids = {source.get("id") for source in element["normative_sources"]}
        if forbidden_decision in ids:
            failures.append(_fail("ambient", "ambient_assigned_to_blocking_gates"))
        if placeholder not in ids:
            failures.append(_fail("ambient", "ambient_source_not_the_placeholder"))
        if element["fachmodul_number"] is not None:
            failures.append(_fail("ambient", "fachmodul_number_present"))
        if element["owns_domain_data"]["value"]:
            failures.append(_fail("ambient", "domain_data_ownership_present"))

    not_assigned = {
        entry["id"] for entry in order.get("not_assigned_to_tooling_merge", [])
    }
    if forbidden_decision not in not_assigned:
        failures.append(_fail("tooling_merge", "dec_050_not_declared_unassigned"))
    addendum = root / MERGE_ADDENDUM
    if not addendum.is_file():
        failures.append(_fail(str(MERGE_ADDENDUM), "merge_addendum_missing"))
    elif "**Ausdrücklich nicht zugeordnet** ist" not in addendum.read_text(
        encoding="utf-8"
    ):
        failures.append(_fail(str(MERGE_ADDENDUM), "dec_050_not_declared_unassigned"))
    return failures, diagnostics


def mode_citations(root):
    failures = []
    diagnostics = []
    citations = governance.load_json(root / CITATIONS)
    index = governance.citation_index(citations)

    # The registry itself must match the primary sources.
    for entry in citations["citations"]:
        if entry["kind"] == "DEC":
            titles = governance.register_titles(entry["commit"], root)
            if titles is None or titles.get(entry["id"]) != entry["title"]:
                failures.append(_fail(entry["id"], "citation_title_mismatch"))
        else:
            entries = governance.adr_entries(entry["commit"], root)
            if entries is None or entry["id"] not in entries:
                failures.append(_fail(entry["id"], "citation_source_missing"))
                continue
            filename, h1 = entries[entry["id"]]
            if governance.cited_adr_title(h1, entry["id"]) != entry["title"]:
                failures.append(_fail(entry["id"], "citation_title_mismatch"))
            if entry["primary_source"] != f"{governance.ADR_DIR}/{filename}":
                failures.append(_fail(entry["id"], "citation_primary_source_mismatch"))

    excluded = governance.normative_exclusions(root)
    documents = [
        document
        for document in sorted((root / GOVERNANCE_DOCS).glob("*.md"))
        if str(document.relative_to(root)) not in excluded
    ]
    if not documents:
        failures.append(_fail(str(GOVERNANCE_DOCS), "governance_documents_missing"))
    for document in documents:
        text = document.read_text(encoding="utf-8")
        relative = str(document.relative_to(root))
        for identifier, code in governance.check_document_citations(text, index):
            failures.append(_fail(f"{relative}#{identifier}", code))
    diagnostics.append(f"documents={len(documents)}")
    diagnostics.append(f"citations={len(citations['citations'])}")
    return failures, diagnostics


def mode_order(root):
    order = governance.load_json(root / ORDER)
    failures = [
        _fail(subject, code) for subject, code in governance.check_delivery_order(order)
    ]
    return failures, [f"elements={len(order.get('elements', []))}"]


def mode_consistency(root):
    order = governance.load_json(root / ORDER)
    document = root / ORDER_DOC
    if not document.is_file():
        return [_fail(str(ORDER_DOC), "order_document_missing")], []
    failures = [
        _fail(subject, code)
        for subject, code in governance.check_document_consistency(
            order, document.read_text(encoding="utf-8")
        )
    ]
    return failures, ["consistency=document_vs_machine_source"]


def mode_b0a1_regression(root):
    """The complete B0a-1 tooling must still be present and functional."""
    from tools.gates import evidence as evidence_module
    from tools.gates import features as features_module
    from tools.gates import manifest as manifest_module
    from tools.gates import paths as gate_paths
    from tools.gates import statuses

    failures = []
    diagnostics = []

    if statuses.ALL_STATUSES != (
        "pass",
        "pass_with_baseline",
        "fail",
        "blocked",
        "not_applicable",
    ):
        failures.append(_fail("statuses", "b0a1_result_enum_changed"))
    if manifest_module.PHASES != (
        "preflight",
        "targeted",
        "offline-final",
        "platform-live",
        "module-final",
    ):
        failures.append(_fail("phases", "b0a1_phase_set_changed"))
    if len(evidence_module.ALLOWED_FIELDS) != 17:
        failures.append(_fail("evidence", "b0a1_evidence_allowlist_changed"))
    for module_name in (
        "baseline",
        "cache",
        "canaries",
        "cli",
        "engine",
        "evidence",
        "features",
        "gitutil",
        "hookguard",
        "manifest",
        "paths",
        "runner",
        "sanitize",
        "signature",
        "statuses",
    ):
        if not (root / "tools" / "gates" / f"{module_name}.py").is_file():
            failures.append(_fail(module_name, "b0a1_module_missing"))

    manifest_path = manifest_module.manifest_path_for(root, "b0a-1-tooling")
    if not manifest_path.is_file():
        failures.append(_fail("b0a-1-tooling", "b0a1_manifest_missing"))
        return failures, diagnostics
    try:
        manifest = manifest_module.load(manifest_path)
    except manifest_module.ManifestError:
        failures.append(_fail("b0a-1-tooling", "b0a1_manifest_invalid"))
        return failures, diagnostics

    lineage = manifest.data["feature_lineage"]
    report = features_module.validate_lineage(
        lineage_path=root / lineage["lineage_file"],
        predecessor_path=root / lineage["predecessor_file"],
        worktree=root,
        manifest=manifest,
    )
    counts = report["counts"]
    diagnostics.append(f"b0a1_features={counts['mapped']}/{counts['expected']}")
    if report["status"] != statuses.PASS or counts["expected"] != 24:
        failures.append(_fail("b0a-1-tooling", "b0a1_feature_lineage_not_complete"))

    result_path = (
        gate_paths.results_dir(root) / "b0a-1-tooling.module-final.json"
    )
    if not result_path.is_file():
        failures.append(_fail("b0a-1-tooling", "b0a1_module_final_missing"))
    else:
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except ValueError:
            failures.append(_fail("b0a-1-tooling", "b0a1_module_final_unreadable"))
        else:
            diagnostics.append(f"b0a1_module_final={result.get('status')}")
            if result.get("status") not in (
                statuses.PASS,
                statuses.PASS_WITH_BASELINE,
            ):
                failures.append(_fail("b0a-1-tooling", "b0a1_module_final_not_green"))
            if result.get("commit") != gitutil.head_commit(cwd=root):
                failures.append(_fail("b0a-1-tooling", "b0a1_module_final_stale"))
    return failures, diagnostics


MODES = {
    "b0a1-regression": mode_b0a1_regression,
    "collisions": mode_collisions,
    "id-freeze": mode_id_freeze,
    "ambient": mode_ambient,
    "citations": mode_citations,
    "order": mode_order,
    "consistency": mode_consistency,
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    args = parser.parse_args(argv)
    root = Path.cwd()
    failures, diagnostics = MODES[args.mode](root)
    outcome = _report.PASSED if not failures else _report.FAILED
    return _report.emit(outcome, failures, diagnostics)


if __name__ == "__main__":
    sys.exit(main())
