"""Pre-declared, reproducible blind sampling of exclusions (block B0f).

The independent re-examination of B0e's exclusions must be immune to two
temptations: choosing the sample after seeing it, and letting the reviewer
see what the register already believes. Both are prevented mechanically:

* The plan (``config/governance/b0f-sample-plan.json``) declares population,
  strata, size formula, ordering, selection and seed derivation *before* any
  draw. The draw is a pure function of the normative commit: the seed is the
  sha256 of the plan's version tag, the commit id and the register's blob id
  inside that commit, and selection orders candidates by the keyed hash of
  their id. Same commit, same register — byte-identical sample, any number
  of times. No clock, no process id, no system entropy.

* The blind dataset carries, per drawn candidate, only the fields of a
  closed allowlist — rule, scanner class, anchor shape and source context —
  and never the original reason, the category, any prior verdict or any
  expected quota. ``validate_blind`` enforces the allowlist and screens the
  payload against every register reason and every category identifier, so a
  leak is a mechanical failure, not a reviewer's promise.

The independent evaluations are stored separately; ``consume_reviews``
checks the one-to-one coverage, the review-before-unblinding digest chain
and the verdict vocabulary, and applies rule R10: zero complaints count as a
result only when drawn > 0, evaluated == drawn and the blindness held.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from . import astcat, astscan, gitutil

PLAN = "config/governance/b0f-sample-plan.json"
PLAN_VERSION = "b0f-sample-v1"

VERDICTS = ("confirm_exclusion", "reject_exclusion", "insufficient_evidence")

BLIND_ALLOWED_FIELDS = (
    "review_id",
    "rule",
    "candidate_class",
    "anchor",
    "unit_source",
    "module_source",
    "auxiliary_sources",
    "task",
)

PLAN_FIELDS = (
    "schema_version",
    "kind",
    "block_id",
    "plan_version",
    "population",
    "strata",
    "size_rule",
    "ordering",
    "selection",
    "seed_rule",
    "blind_allowlist",
    "review_protocol",
)


class SampleError(ValueError):
    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def load_plan(root, path=PLAN):
    target = Path(root) / path
    if not target.is_file():
        raise SampleError("plan_missing", str(path))
    try:
        plan = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SampleError("plan_not_json", str(exc)[:80]) from exc
    if not isinstance(plan, dict) or sorted(plan) != sorted(PLAN_FIELDS):
        raise SampleError("plan_field_set")
    if plan["kind"] != "b0f_sample_plan":
        raise SampleError("plan_kind_unexpected")
    if plan["plan_version"] != PLAN_VERSION:
        raise SampleError("plan_version_unsupported", str(plan["plan_version"]))
    if sorted(plan["blind_allowlist"]) != sorted(BLIND_ALLOWED_FIELDS):
        raise SampleError("plan_allowlist_drifted")
    return plan


def register_blob_id(root, commit):
    code, out, err = gitutil.run_git(
        ["rev-parse", f"{commit}:{astscan.REGISTER}"], cwd=root
    )
    if code != 0:
        raise SampleError("register_blob_unresolved", err.decode()[:80] if isinstance(err, bytes) else str(err)[:80])
    return out.strip() if isinstance(out, str) else out.decode().strip()


def derive_seed(root, commit):
    """The seed is bound to the commit object and the register blob (R6)."""
    blob = register_blob_id(root, commit)
    return hashlib.sha256(
        f"{PLAN_VERSION}:{commit}:{blob}".encode("utf-8")
    ).hexdigest()


def population(register):
    entries = [
        entry
        for entry in register["dispositions"]
        if entry["disposition"] == "exclude_with_reason"
    ]
    return sorted(entries, key=lambda entry: entry["candidate_id"])


def stratum_size(count):
    """ceil(count / 5) for a populated stratum.

    A stratum with zero members is *derived* emptiness — the register, an
    independent source, declares no exclusions under that rule — so the
    stratum is skipped with that proof (the narrow R10 exception). Only an
    empty total population blocks the review."""
    if count <= 0:
        return 0
    return math.ceil(count / 5)


def selection_key(seed, candidate_id):
    return hashlib.sha256(f"{seed}:{candidate_id}".encode("utf-8")).hexdigest()


def review_id(seed, candidate_id):
    digest = hashlib.sha256(f"rev:{seed}:{candidate_id}".encode("utf-8")).hexdigest()
    return f"rev-{digest[:12]}"


def draw(root, commit, register=None):
    """The deterministic draw. Returns ``{rule: [entry, ...]}`` in key order."""
    if register is None:
        register = astscan.load_register(root)
    seed = derive_seed(root, commit)
    entries = population(register)
    if not entries:
        raise SampleError("population_empty")
    drawn = {}
    for rule in astscan.RULES:
        stratum = [entry for entry in entries if entry["rule"] == rule]
        size = stratum_size(len(stratum))
        ordered = sorted(
            stratum, key=lambda entry: selection_key(seed, entry["candidate_id"])
        )
        drawn[rule] = ordered[:size]
    return seed, drawn


def _module_source(root, commit, relative):
    code, out, _err = gitutil.run_git(
        ["show", f"{commit}:{relative}"], cwd=root
    )
    if code != 0:
        raise SampleError("blind_source_unresolved", relative)
    return out if isinstance(out, str) else out.decode()


def _unit_excerpt(module_source, unit_qualname):
    import ast as ast_module

    from . import astcorpus

    tree = ast_module.parse(module_source)
    for unit in astcorpus.collect_units(tree):
        if unit.qualname == unit_qualname:
            lines = module_source.splitlines()
            start = unit.node.lineno - 1
            end = getattr(unit.node, "end_lineno", start + 1)
            return "\n".join(lines[start:end]), start + 1
    raise SampleError("blind_unit_unresolved", unit_qualname)


_TASK = (
    "Judge independently, from the material in this record alone, whether "
    "this candidate may be excluded from its rule's findings: for R9, "
    "whether the perturbation's effect is mechanically established or "
    "provably irrelevant before any expectation; for R10, whether a missing "
    "input normalised to an empty walk can carry a positive judgment here. "
    "Answer confirm_exclusion when the material carries the exclusion; "
    "reject_exclusion when the material positively establishes that the "
    "exclusion is wrong — for example a concrete input or path on which the "
    "guarded outcome goes wrong; insufficient_evidence when the material "
    "can establish neither, including when validity would depend on facts "
    "outside this record. Give a technical justification either way. No "
    "particular distribution of answers is expected or desired."
)


def _leaks(payload_text, reasons, category_ids):
    for category in category_ids:
        if category in payload_text:
            return "blind_category_leaked"
    for reason in reasons:
        fragment = reason[:60]
        if len(fragment) >= 40 and fragment in payload_text:
            return "blind_reason_leaked"
    return ""


def _screen_inputs(register):
    reasons = [
        str(entry["reason"])
        for entry in register["dispositions"]
        if entry["disposition"] == "exclude_with_reason"
    ]
    return reasons, sorted(astcat.CATEGORIES)


def build_blind(root, commit, seed, drawn, register=None):
    """The blind dataset, derived from the commit's blobs only.

    A candidate that lives inside the vocabulary tooling itself has a module
    source that necessarily names categories; for such a record the context
    falls back deterministically to the unit excerpt, so the information
    barrier holds by construction instead of by exception."""
    if register is None:
        from . import astscan

        register = astscan.load_register(root)
    reasons, category_ids = _screen_inputs(register)
    records = []
    for rule in sorted(drawn):
        for entry in drawn[rule]:
            module_source = _module_source(root, commit, entry["file"])
            unit_source, unit_start = _unit_excerpt(module_source, entry["unit"])
            context = module_source
            if _leaks(module_source, reasons, category_ids):
                context = unit_source
            records.append(
                {
                    "review_id": review_id(seed, entry["candidate_id"]),
                    "rule": entry["rule"],
                    "candidate_class": entry["candidate_class"],
                    "anchor": {
                        "ast_class": entry["ast_class"],
                        "excerpt_line": entry["lineno"] - unit_start + 1,
                    },
                    "unit_source": unit_source,
                    "module_source": context,
                    "auxiliary_sources": [],
                    "task": _TASK,
                }
            )
    records.sort(key=lambda record: record["review_id"])
    return records


def validate_blind(root, records, register=None):
    """Allowlist plus leakage screen. Returns a list of ``(id, code)``."""
    if register is None:
        register = astscan.load_register(root)
    failures = []
    if not isinstance(records, list) or not records:
        return [("blind", "blind_dataset_empty")]
    reasons, category_ids = _screen_inputs(register)
    seen = set()
    for record in records:
        identifier = str(record.get("review_id", "?"))
        if not isinstance(record, dict) or sorted(record) != sorted(
            BLIND_ALLOWED_FIELDS
        ):
            failures.append((identifier, "blind_field_set"))
            continue
        if identifier in seen:
            failures.append((identifier, "blind_review_id_duplicated"))
        seen.add(identifier)
        code = _leaks(json.dumps(record, sort_keys=True), reasons, category_ids)
        if code:
            failures.append((identifier, code))
    return failures


def consume_reviews(root, commit, *, reviews, comparison=None, register=None):
    """Rule R10 over the review itself. Returns ``(failures, summary)``.

    ``reviews`` is the stored independent evaluation list; ``comparison``
    the unblinding record that binds the review file digest. Zero
    complaints count only after drawn > 0, evaluated == drawn, and every
    drawn review id evaluated exactly once.
    """
    failures = []
    seed, drawn = draw(root, commit, register=register)
    expected = {
        review_id(seed, entry["candidate_id"]): entry["candidate_id"]
        for rule in drawn
        for entry in drawn[rule]
    }
    if not expected:
        return [("sample", "sample_empty")], {}
    by_id = {}
    for record in reviews if isinstance(reviews, list) else []:
        identifier = str(record.get("review_id", ""))
        if identifier in by_id:
            failures.append((identifier, "review_duplicated"))
        by_id[identifier] = record
        if record.get("verdict") not in VERDICTS:
            failures.append((identifier, "verdict_unknown"))
        if not str(record.get("justification", "")).strip():
            failures.append((identifier, "justification_empty"))
    for identifier in sorted(set(expected) - set(by_id)):
        failures.append((identifier, "review_missing"))
    for identifier in sorted(set(by_id) - set(expected)):
        failures.append((identifier, "review_unexpected"))
    if comparison is not None:
        digest = hashlib.sha256(
            json.dumps(reviews, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if comparison.get("reviews_sha256") != digest:
            # The evaluations changed after the unblinding record was
            # written: post-unblinding tampering is a hard failure.
            failures.append(("comparison", "reviews_changed_after_unblinding"))
        if comparison.get("commit") != commit:
            failures.append(("comparison", "comparison_commit_mismatch"))
    summary = {
        "drawn": len(expected),
        "evaluated": len(set(by_id) & set(expected)),
        "confirm_exclusion": sum(
            1 for r in by_id.values() if r.get("verdict") == "confirm_exclusion"
        ),
        "reject_exclusion": sum(
            1 for r in by_id.values() if r.get("verdict") == "reject_exclusion"
        ),
        "insufficient_evidence": sum(
            1 for r in by_id.values() if r.get("verdict") == "insufficient_evidence"
        ),
    }
    if summary["drawn"] <= 0 or summary["evaluated"] != summary["drawn"]:
        failures.append(("review", "review_consumption_incomplete"))
    return sorted(set(failures)), summary
