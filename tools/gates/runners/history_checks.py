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
K1_DEFINITION = Path("config/gates/k1/calendar-k1-definition.json")
K1_START_MATRIX = Path("config/gates/k1/calendar-k1-start-matrix.json")
R3_REVIEW = HISTORY_DIR / "r3-not-applicable-review.json"

#: Classification schemes that do not exist in this repository. They must
#: not appear as a per gate classification in any K1 document.
ABSENT_SCHEMES = (
    "Abnahmeprofil A",
    "Abnahmeprofil B",
    "Abnahmeprofil C",
    "Overlay P",
    "Overlay S",
    "Overlay H",
    "Overlays P, S und H",
)
K1_DOCUMENT_PATHS = (
    "config/gates/k1",
    "docs/personal-jarvis/modules/calendar.md",
)

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
        # Rule R10: an acceptance manifest without artifact bindings would
        # walk zero times and read as verified. Absence is a failure, never
        # an empty proof set.
        if not document.get("committed_artifacts"):
            failures.append(_fail(block, "manifest_without_committed_artifacts"))
            continue
        for artifact in document["committed_artifacts"]:
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
            failures.append(
                _fail(f"preserve.{prefix}", "preserved_feature_not_passing")
            )
        for feature in required:
            if not str(feature.get("current_location", "")).strip():
                failures.append(
                    _fail(feature["feature_id"], "feature_location_missing")
                )

    # Rule R10: the invariant class must not vanish silently. A preservation
    # document without invariants would pass on the feature counts alone
    # while checking none of the declared invariants.
    if not document.get("invariants"):
        failures.append(_fail("preservation", "invariant_set_missing_or_empty"))
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


def mode_k1_definition(args):
    """The K1 definition must be derived, bound and free of inventions."""
    root = Path.cwd()
    failures = []
    diagnostics = []
    definition = json.loads((root / K1_DEFINITION).read_text(encoding="utf-8"))
    matrix = json.loads((root / K1_START_MATRIX).read_text(encoding="utf-8"))

    if definition.get("kind") != "k1_definition":
        failures.append(_fail("definition", "not_a_k1_definition"))

    actual = hashlib.sha256(
        (root / K1_START_MATRIX).read_bytes()
    ).hexdigest()
    if definition["derived_from"].get("start_matrix_sha256") != actual:
        failures.append(_fail("derived_from", "start_matrix_binding_stale"))

    matrix_ids = {gate["gate_id"] for gate in matrix["gates"]}
    definition_ids = {gate["gate_id"] for gate in definition["gates"]}
    removed_ids = {item["gate_id"] for item in definition["removed_from_k1"]}
    invented = sorted(definition_ids - matrix_ids)
    for gate_id in invented:
        failures.append(_fail(gate_id, "gate_not_derived_from_matrix"))
    if definition_ids | removed_ids != matrix_ids:
        failures.append(_fail("definition", "gate_set_does_not_partition"))
    if definition_ids & removed_ids:
        failures.append(_fail("definition", "gate_both_kept_and_removed"))

    binding = definition["stage_binding"]
    expected = hashlib.sha256(
        "\n".join(sorted(definition_ids)).encode("utf-8")
    ).hexdigest()
    if binding.get("digest") != expected:
        failures.append(_fail("stage_binding", "digest_does_not_match_set"))
    if sorted(binding.get("gate_ids", [])) != sorted(definition_ids):
        failures.append(_fail("stage_binding", "gate_ids_do_not_match_set"))

    for gate in definition["gates"]:
        if gate.get("execution_class") not in ("offline", "live"):
            failures.append(_fail(gate["gate_id"], "execution_class_missing"))
        needs = gate.get("requires", [])
        if bool(needs) != (gate.get("execution_class") == "live"):
            failures.append(_fail(gate["gate_id"], "execution_class_not_derived"))

    for item in definition["removed_from_k1"]:
        if item.get("counts_as") != "neither_fulfilled_nor_open":
            failures.append(_fail(item["gate_id"], "removed_gate_still_counted"))

    split = definition["parity_contract_split"]
    if set(split["read_parity_in_k1"]) & set(split["write_parity_removed"]):
        failures.append(_fail("parity", "item_in_both_halves"))
    if not definition["invariant_conflict"].get(
        "documented_not_carried_as_open_gate"
    ):
        failures.append(_fail("invariant_conflict", "carried_as_open_gate"))

    write_decision = definition["separate_write_decision"]
    if write_decision.get("decision_id") is not None:
        failures.append(_fail("write_decision", "number_allocated_without_owner"))
    if not str(write_decision.get("placeholder", "")).startswith("{{"):
        failures.append(_fail("write_decision", "placeholder_not_marked"))

    schemes = definition["classification_schemes_not_used"]
    if schemes.get("acceptance_profile_a_b_c") or schemes.get("overlay_p_s_h"):
        failures.append(_fail("schemes", "absent_scheme_declared_used"))

    diagnostics.append(f"k1_gates={len(definition_ids)}")
    diagnostics.append(f"stage_digest={binding.get('digest', '')[:16]}")
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def find_scheme_usages(root):
    """Return ``(relative_path, token)`` for every absent scheme mention."""
    hits = []
    for relative in K1_DOCUMENT_PATHS:
        candidate = Path(root) / relative
        files = (
            [candidate]
            if candidate.is_file()
            else sorted(p for p in candidate.rglob("*") if p.is_file())
            if candidate.is_dir()
            else []
        )
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for token in ABSENT_SCHEMES:
                if token in text:
                    hits.append((str(path.relative_to(Path(root))), token))
    return sorted(set(hits))


def mode_classification_schemes(args):
    """A/B/C and P/S/H must not be used as a classification in K1 documents."""
    root = Path.cwd()
    failures = [
        _fail(f"{relative}:{token}", "absent_classification_scheme_used")
        for relative, token in find_scheme_usages(root)
    ]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures
    )


def mode_not_applicable_review(args):
    """Rule R3 — no silent not_applicable for a guaranteed artifact."""
    root = Path.cwd()
    failures = []
    diagnostics = []
    review = json.loads((root / R3_REVIEW).read_text(encoding="utf-8"))
    if review.get("rule") != "R3":
        failures.append(_fail("review", "not_an_r3_review"))

    for path in sorted((root / HISTORY_DIR).glob("*.acceptance.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        policy = document.get("reexecution_policy", {})
        if policy.get("runtime_evidence_absent") != "fail":
            failures.append(_fail(path.name, "guaranteed_artifact_defaults_na"))
        # Rule R10: a manifest must not escape the R3 review by declaring no
        # evidence at all — undeclared is the silent-absence pattern this
        # mode exists to forbid.
        if not document.get("runtime_evidence"):
            failures.append(_fail(path.name, "runtime_evidence_undeclared"))
        for entry in document.get("runtime_evidence", []):
            if entry.get("scope") != "committed_snapshot":
                failures.append(_fail(path.name, "evidence_not_a_snapshot"))
            if str(entry.get("path", "")).startswith(".gate-runtime"):
                failures.append(_fail(path.name, "evidence_bound_to_runtime_area"))
    diagnostics.append(f"reviewed_findings={len(review.get('findings', []))}")
    diagnostics.append(
        f"examined_and_cleared={len(review.get('examined_and_cleared', []))}"
    )
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def check_anchors(root, definition):
    """Return ``(gate_id, code)`` for every anchor that does not resolve.

    Rule R10 — prescribed by the register in block B0e and found
    unimplemented by the B0f blind review chain: an absent declaration must
    never read as an empty anchor set, because a definition whose open
    gates were justified by re-anchoring would silently pass with the
    declaration deleted. Emptiness is legitimate only when declared with a
    reason."""
    problems = []
    anchoring = definition.get("gate_anchoring")
    if not anchoring:
        return [("gate_anchoring", "gate_anchoring_undeclared")]
    anchors = anchoring.get("anchors")
    if anchors is None:
        return [("gate_anchoring", "gate_anchoring_undeclared")]
    if not anchors and not str(anchoring.get("declared_empty_reason", "")).strip():
        return [("gate_anchoring", "anchor_set_empty_without_reason")]
    for anchor in anchors:
        gate_id = anchor.get("gate_id", "<unnamed>")
        resolution = anchor.get("resolution")
        if resolution not in ("re_anchored", "removed_from_k1"):
            problems.append((gate_id, "unknown_resolution"))
            continue
        dangling = anchor.get("dangling_reference", {})
        if not dangling.get("evidence"):
            problems.append((gate_id, "dangling_reference_unproven"))
        if resolution != "re_anchored":
            continue
        sources = anchor.get("carrying_sources", [])
        if not sources:
            problems.append((gate_id, "no_carrying_source"))
        for source in sources:
            target = Path(root) / source.get("path", "")
            if not target.is_file():
                problems.append((gate_id, "carrying_source_missing"))
                continue
            text = target.read_text(encoding="utf-8", errors="replace")
            marker = str(source.get("quote_anchor", ""))
            if not marker or marker not in text:
                problems.append((gate_id, "carrying_source_does_not_carry"))
        if not anchor.get("criterion_after_anchoring"):
            problems.append((gate_id, "criterion_missing"))
        if anchor.get("status_after_anchoring") == "open" and not anchor.get(
            "remaining_work"
        ):
            problems.append((gate_id, "open_without_named_remaining_work"))
    return problems


def mode_gate_anchoring(args):
    """No K1 gate may rest on a reference that does not exist."""
    root = Path.cwd()
    definition = json.loads((root / K1_DEFINITION).read_text(encoding="utf-8"))
    failures = [
        _fail(gate_id, code) for gate_id, code in check_anchors(root, definition)
    ]
    anchors = definition.get("gate_anchoring", {}).get("anchors", [])
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED,
        failures,
        [f"anchors={len(anchors)}"],
    )


def mode_k1_status(args):
    """Determine the closing K1 matrix. The numbers come from here, never
    from a prompt.

    The rule is mechanical: a gate counts as fulfilled exactly when it is
    offline executable **and** carries a resolvable evidence reference.
    Everything else is open. Gates removed from K1 are not counted at all.
    """
    root = Path.cwd()
    failures = []
    definition = json.loads((root / K1_DEFINITION).read_text(encoding="utf-8"))
    matrix = json.loads((root / K1_START_MATRIX).read_text(encoding="utf-8"))
    recorded = {gate["gate_id"]: gate for gate in matrix["gates"]}

    anchors = {
        anchor["gate_id"]: anchor
        for anchor in definition.get("gate_anchoring", {}).get("anchors", [])
    }
    for gate_id, code in check_anchors(root, definition):
        failures.append(_fail(gate_id, code))

    rows = []
    for gate in definition["gates"]:
        gate_id = gate["gate_id"]
        source = recorded.get(gate_id, {})
        evidence = str(source.get("evidence_reference", "")).strip()
        offline = gate["execution_class"] == "offline"
        status = "fulfilled" if (offline and evidence) else "open"
        rows.append(
            {
                "gate_id": gate_id,
                "title": gate["title"],
                "execution_class": gate["execution_class"],
                "status": status,
                "evidence_reference": evidence,
                "blocking_reason": (
                    "" if status == "fulfilled"
                    else str(
                        anchors[gate_id]["status_reason"]
                        if gate_id in anchors
                        else source.get("offline_closable_reason", "")
                    )
                ),
                "anchored": gate_id in anchors,
            }
        )
        # The recorded expectation must agree with the derived status; a
        # divergence means the matrix and the definition drifted apart.
        if source.get("status_after_b0b") not in (None, status):
            failures.append(_fail(gate_id, "recorded_status_diverges"))
        if status == "fulfilled" and not evidence:
            failures.append(_fail(gate_id, "fulfilled_without_evidence"))

    counts = {
        "total": len(rows),
        "fulfilled": sum(1 for row in rows if row["status"] == "fulfilled"),
        "open": sum(1 for row in rows if row["status"] == "open"),
        "accepted_against_bound_baseline": 0,
        "blocked": 0,
        "removed_from_k1": len(definition["removed_from_k1"]),
    }
    if counts["fulfilled"] + counts["open"] != counts["total"]:
        failures.append(_fail("counts", "distribution_does_not_add_up"))

    target = root / ".gate-runtime" / "k1" / "calendar-k1-closing-matrix.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": 1,
        "kind": "k1_closing_matrix",
        "produced_by": "gate run",
        "stage_binding_digest": definition["stage_binding"]["digest"],
        "counts": counts,
        "gates": rows,
        "removed_from_k1": definition["removed_from_k1"],
        "completion_claim": (
            "K1 ist nicht offline abgeschlossen." if counts["open"]
            else "K1 ist offline abgeschlossen."
        ),
    }
    target.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    diagnostics = [
        f"k1_total={counts['total']}",
        f"k1_fulfilled={counts['fulfilled']}",
        f"k1_open={counts['open']}",
        f"k1_accepted_against_bound_baseline={counts['accepted_against_bound_baseline']}",
        f"k1_blocked={counts['blocked']}",
        f"k1_removed={counts['removed_from_k1']}",
        f"k1_offline_complete={counts['open'] == 0}",
    ]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


MODES = {
    "base-commit-unchanged": mode_base_commit_unchanged,
    "gate-anchoring": mode_gate_anchoring,
    "k1-status": mode_k1_status,
    "classification-schemes": mode_classification_schemes,
    "k1-definition": mode_k1_definition,
    "not-applicable-review": mode_not_applicable_review,
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
