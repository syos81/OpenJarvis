"""B0f checks: exclusion identity, the blind sample and the method findings.

``baseline``
    reconstructs the B0e inventory from the register, requires a non-empty,
    fully categorised exclusion population and the unique resolution of the
    Slack handoff reference.
``sample``
    requires the pre-declared plan, re-derives the deterministic draw from
    the current commit and holds the stored sample record to it.
``blind``
    regenerates the blind dataset from the commit, enforces the allowlist
    and leakage screen, consumes the stored independent reviews under rule
    R10 and enforces the consequence path for rejected exclusions.
``method``
    validates the unit-locality classification against its required proofs
    and executes the Slack network-isolation proof without any real network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import astcat, astscan, b0fsample, gitutil  # noqa: E402
from tools.gates.runners import _report  # noqa: E402

SAMPLE_RECORD = "config/gates/history/b0f-sample-record.json"
BLIND_DATASET = "config/gates/history/b0f-blind-dataset.json"
BLIND_REVIEWS = "config/gates/history/b0f-blind-reviews.json"
UNBLINDING = "config/gates/history/b0f-unblinding.json"
REREVIEW = "config/gates/history/b0f-category-rereview.json"
UNIT_LOCALITY = "config/governance/b0f-unit-locality.json"
SLACK_PROOF = "tests/server/test_connectors_network_isolation.py"
HANDOFF = "docs/governance/b0e-handoff.md"


def _fail(identifier, code):
    return _report.failure(identifier, category="b0f", code=code)


def _head(root):
    code, out, _err = gitutil.run_git(["rev-parse", "HEAD"], cwd=root)
    if code != 0:
        return None
    return out.strip()


def _load_json(root, relative):
    target = Path(root) / relative
    if not target.is_file():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def mode_baseline(args):
    root = Path.cwd()
    failures = []
    diagnostics = []
    try:
        register = astscan.load_register(root)
    except astscan.RegisterError as error:
        return _report.emit(
            _report.BLOCKED, [_fail(astscan.REGISTER, error.code)],
            reason_code="register_unusable",
        )
    entries = register["dispositions"]
    exclusions = [e for e in entries if e["disposition"] == "exclude_with_reason"]
    if not exclusions:
        # Rule R10: an empty exclusion population cannot be reviewed green.
        return _report.emit(
            _report.BLOCKED, [_fail("population", "exclusion_population_empty")],
            reason_code="population_empty",
        )
    categorised = [e for e in exclusions if e["category"] in astcat.CATEGORIES]
    if len(categorised) != len(exclusions):
        failures.append(_fail("identity", "exclusions_not_fully_categorised"))
    for rule in astscan.RULES:
        total = sum(1 for e in exclusions if e["rule"] == rule)
        done = sum(1 for e in categorised if e["rule"] == rule)
        diagnostics.append(f"{rule.lower()}_exclusions={total}")
        if total != done:
            failures.append(_fail(rule, "rule_identity_broken"))
    diagnostics.append(f"dispositions={len(entries)}")
    diagnostics.append(f"exclusions={len(exclusions)}")
    diagnostics.append(
        f"categories_used={len({e['category'] for e in categorised})}"
    )
    handoff = Path(root) / HANDOFF
    if not handoff.is_file():
        failures.append(_fail(HANDOFF, "handoff_missing"))
    else:
        text = handoff.read_text(encoding="utf-8")
        reference = "tests/server/test_connectors_router.py::test_connect_slack_bot_token_returns_400"
        if reference not in text:
            failures.append(_fail(HANDOFF, "slack_reference_unresolved"))
        else:
            file_part, _, function = reference.partition("::")
            source = (Path(root) / file_part).read_text(encoding="utf-8")
            if function not in source:
                failures.append(_fail(reference, "slack_reference_unresolved"))
            else:
                diagnostics.append("slack_reference=resolved")
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_sample(args):
    root = Path.cwd()
    failures = []
    diagnostics = []
    try:
        b0fsample.load_plan(root)
    except b0fsample.SampleError as error:
        return _report.emit(
            _report.BLOCKED, [_fail(b0fsample.PLAN, error.code)],
            reason_code="plan_unusable",
        )
    commit = _head(root)
    if commit is None:
        return _report.emit(
            _report.BLOCKED, [_fail("git", "head_unresolved")],
            reason_code="head_unresolved",
        )
    try:
        seed, drawn = b0fsample.draw(root, commit)
    except (b0fsample.SampleError, astscan.RegisterError) as error:
        return _report.emit(
            _report.BLOCKED, [_fail("draw", error.code)], reason_code="draw_blocked"
        )
    drawn_ids = {
        rule: [entry["candidate_id"] for entry in drawn[rule]] for rule in drawn
    }
    total = sum(len(ids) for ids in drawn_ids.values())
    diagnostics.append(f"seed={seed[:16]}")
    diagnostics.append(f"drawn_total={total}")
    for rule in sorted(drawn_ids):
        diagnostics.append(f"drawn_{rule.lower()}={len(drawn_ids[rule])}")
    if total <= 0:
        failures.append(_fail("sample", "sample_empty"))
    record = _load_json(root, SAMPLE_RECORD)
    if record is None:
        return _report.emit(
            _report.BLOCKED, [_fail(SAMPLE_RECORD, "sample_record_missing")],
            diagnostics, reason_code="sample_record_missing",
        )
    if record.get("commit") != commit:
        failures.append(_fail(SAMPLE_RECORD, "sample_record_commit_mismatch"))
    if record.get("seed") != seed:
        failures.append(_fail(SAMPLE_RECORD, "sample_record_seed_mismatch"))
    if record.get("drawn") != drawn_ids:
        # The stored draw and the deterministic re-draw must be identical:
        # a manipulated population changes the register blob, the seed and
        # therefore the draw.
        failures.append(_fail(SAMPLE_RECORD, "sample_record_draw_mismatch"))
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_blind(args):
    root = Path.cwd()
    failures = []
    diagnostics = []
    commit = _head(root)
    dataset_document = _load_json(root, BLIND_DATASET)
    reviews_document = _load_json(root, BLIND_REVIEWS)
    comparison = _load_json(root, UNBLINDING)
    dataset = (dataset_document or {}).get("records")
    reviews = (reviews_document or {}).get("records")
    if not dataset or not reviews or comparison is None:
        return _report.emit(
            _report.BLOCKED,
            [_fail("blind", "review_artifacts_missing")],
            reason_code="review_artifacts_missing",
        )
    try:
        register = astscan.load_register(root)
        seed, drawn = b0fsample.draw(root, commit, register=register)
        rebuilt = b0fsample.build_blind(root, commit, seed, drawn)
    except (b0fsample.SampleError, astscan.RegisterError) as error:
        return _report.emit(
            _report.BLOCKED, [_fail("blind", error.code)], reason_code="draw_blocked"
        )
    if rebuilt != dataset:
        failures.append(_fail(BLIND_DATASET, "blind_dataset_not_reproducible"))
    for identifier, code in b0fsample.validate_blind(root, dataset, register=register):
        failures.append(_fail(identifier, code))
    review_failures, summary = b0fsample.consume_reviews(
        root, commit, reviews=reviews, comparison=comparison, register=register
    )
    for identifier, code in review_failures:
        failures.append(_fail(identifier, code))
    for name, value in sorted(summary.items()):
        diagnostics.append(f"{name}={value}")
    if summary.get("reject_exclusion"):
        rereview = _load_json(root, REREVIEW)
        if rereview is None:
            failures.append(_fail(REREVIEW, "category_rereview_missing"))
        else:
            affected = set(rereview.get("affected_categories", []))
            by_candidate = {
                e["candidate_id"]: e for e in register["dispositions"]
            }
            # The affected set is derived from the rejected candidates, never
            # trusted from the record — and the rejected candidates are
            # derived from the digest-bound reviews through the deterministic
            # id map, never from the comparison rows: a rejected candidate
            # that is still an exclusion binds its category into the duty,
            # and one that is no longer an exclusion must have been
            # re-dispositioned.
            id_map = {
                b0fsample.review_id(seed, entry["candidate_id"]): entry["candidate_id"]
                for rule in drawn
                for entry in drawn[rule]
            }
            for review in reviews:
                if review.get("verdict") != "reject_exclusion":
                    continue
                candidate_id = id_map.get(str(review.get("review_id", "")))
                if candidate_id is None:
                    continue  # already failed as review_unexpected upstream
                entry = by_candidate.get(candidate_id)
                if entry is None:
                    failures.append(
                        _fail(candidate_id, "rejected_candidate_unknown")
                    )
                elif entry["disposition"] == "exclude_with_reason":
                    if entry["category"] not in affected:
                        failures.append(
                            _fail(candidate_id, "rejected_category_not_covered")
                        )
            for category in sorted(affected):
                if category not in astcat.CATEGORIES:
                    failures.append(_fail(category, "affected_category_unknown"))
            covered = {
                item["candidate_id"] for item in rereview.get("candidates", [])
            }
            expected = {
                e["candidate_id"]
                for e in register["dispositions"]
                if e["disposition"] == "exclude_with_reason"
                and e["category"] in affected
            }
            if affected and not expected:
                # Rule R10: a duty over an empty set discharges nothing.
                failures.append(_fail(REREVIEW, "category_rereview_vacuous"))
            if covered != expected:
                # A single-case fix is not a category-wide re-examination.
                failures.append(_fail(REREVIEW, "category_rereview_incomplete"))
    if summary.get("insufficient_evidence"):
        rereview = _load_json(root, REREVIEW)
        resolved = (rereview or {}).get("insufficient_evidence_resolution")
        if not resolved:
            failures.append(_fail(REREVIEW, "insufficient_evidence_unresolved"))
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_method(args):
    root = Path.cwd()
    failures = []
    diagnostics = []
    finding = _load_json(root, UNIT_LOCALITY)
    if finding is None:
        return _report.emit(
            _report.BLOCKED, [_fail(UNIT_LOCALITY, "finding_missing")],
            reason_code="finding_missing",
        )
    classification = finding.get("classification")
    diagnostics.append(f"unit_locality={classification}")
    if classification == "covered_elsewhere":
        named = finding.get("covering_check", {})
        reference = str(named.get("positive_test", ""))
        counter = str(named.get("negative_test", ""))
        for ref in (reference, counter):
            file_part = ref.partition("::")[0]
            if not file_part or not (Path(root) / file_part).is_file():
                failures.append(_fail(ref or "covering_check", "covering_proof_missing"))
    elif classification == "explicitly_out_of_contract":
        if not str(finding.get("owner_decision", "")).strip():
            # This classification exists only through an owner decision;
            # the tooling cannot create one.
            failures.append(_fail(UNIT_LOCALITY, "owner_decision_missing"))
    elif classification == "open_gap":
        demo = str(finding.get("minimal_case", {}).get("demonstration", ""))
        file_part, _, fragment = demo.partition("::")
        target = Path(root) / file_part
        if not target.is_file() or (fragment and fragment not in target.read_text(encoding="utf-8")):
            failures.append(_fail(demo or "minimal_case", "minimal_case_unresolved"))
    else:
        failures.append(_fail(str(classification), "classification_unknown"))

    proof = Path(root) / SLACK_PROOF
    if not proof.is_file():
        failures.append(_fail(SLACK_PROOF, "slack_proof_missing"))
    else:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", SLACK_PROOF, "-q", "-p", "no:cacheprovider"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if completed.returncode != 0:
            failures.append(_fail(SLACK_PROOF, "slack_proof_failed"))
        else:
            diagnostics.append("slack_isolation=proven_without_network")
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


MODES = {
    "baseline": mode_baseline,
    "sample": mode_sample,
    "blind": mode_blind,
    "method": mode_method,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    args = parser.parse_args(argv)
    return MODES[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())
