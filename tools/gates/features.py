"""Feature lineage: every mandatory predecessor feature must be evidenced.

A consolidated artifact (prompt, plan, register, handoff) is only complete
when every mandatory feature of its *immediate predecessor* is individually
mapped and evidenced. This module is the machine validator behind that rule:

* the feature list comes from the predecessor artifact, not from the new one,
* the predecessor list is pinned by SHA-256,
* renamed, moved or split features need an explicit mapping,
* an unmapped or missing mandatory feature is always ``fail``,
* a mandatory feature may never be declared ``not_applicable``,
* a missing predecessor or predecessor list is ``blocked`` — completeness may
  not be claimed in that case,
* a deliberately changed or dropped requirement needs a concrete owner
  decision; without one it counts as missing.

A pure text or length comparison is explicitly not sufficient and is not
implemented here.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import FEATURE_SCHEMA_VERSION
from . import sanitize
from . import statuses

LINEAGE_FIELDS = (
    "schema_version",
    "artifact_id",
    "artifact_version",
    "predecessor_artifact_id",
    "predecessor_feature_list_sha256",
    "features",
)
FEATURE_FIELDS = (
    "feature_id",
    "required",
    "description",
    "current_location",
    "verification",
    "status",
)
FEATURE_OPTIONAL_FIELDS = ("predecessor_feature_id", "owner_decision")
PREDECESSOR_FIELDS = ("artifact_id", "artifact_version", "features")
#: A lineage file may itself serve as the predecessor feature list.
PREDECESSOR_OPTIONAL_FIELDS = (
    "schema_version",
    "predecessor_artifact_id",
    "predecessor_feature_list_sha256",
)
PREDECESSOR_FEATURE_FIELDS = ("feature_id", "required", "description")
VERIFICATION_TYPES = ("gate_check", "test", "file")

_FEATURE_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,31}$")


class FeatureLineageError(ValueError):
    pass


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def predecessor_digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_shape(lineage, predecessor):
    issues = []
    unknown = sorted(set(lineage) - set(LINEAGE_FIELDS))
    if unknown:
        issues.append(f"unknown lineage field(s): {unknown}")
    missing = sorted(set(LINEAGE_FIELDS) - set(lineage))
    if missing:
        issues.append(f"missing lineage field(s): {missing}")
    if lineage.get("schema_version") != FEATURE_SCHEMA_VERSION:
        issues.append("unsupported feature lineage schema_version")
    unknown_pred = sorted(
        set(predecessor) - set(PREDECESSOR_FIELDS + PREDECESSOR_OPTIONAL_FIELDS)
    )
    if unknown_pred:
        issues.append(f"unknown predecessor field(s): {unknown_pred}")
    missing_pred = sorted(set(PREDECESSOR_FIELDS) - set(predecessor))
    if missing_pred:
        issues.append(f"missing predecessor field(s): {missing_pred}")
    return issues


def _verify_feature(feature, *, worktree, manifest):
    """Return ``(ok, reason_code)`` for one feature's evidence pointer."""
    verification = feature.get("verification")
    if not isinstance(verification, dict):
        return False, "feature_verification_malformed"
    if sorted(verification) != ["ref", "type"]:
        return False, "feature_verification_malformed"
    kind = verification.get("type")
    ref = verification.get("ref")
    if kind not in VERIFICATION_TYPES or not isinstance(ref, str) or not ref:
        return False, "feature_verification_malformed"
    if ref.startswith("/") or "/Users/" in ref:  # gate-allow: absolute_user_path
        return False, "feature_verification_absolute_path"
    if kind == "gate_check":
        if manifest is not None and ref in manifest.checks_by_id:
            return True, "feature_verified"
        # An inherited feature may be evidenced by the check of the block that
        # introduced it; every block manifest in the repository counts.
        blocks = Path(worktree) / "config" / "gates" / "blocks"
        if blocks.is_dir():
            for candidate in sorted(blocks.glob("*.json")):
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for check in data.get("checks", []):
                    if check.get("check_id") == ref:
                        return True, "feature_verified"
        return False, "feature_verification_unresolved"
    if kind == "file":
        target = Path(worktree) / ref
        return (
            (True, "feature_verified")
            if target.exists()
            else (False, "feature_verification_unresolved")
        )
    file_part, _, test_part = ref.partition("::")
    target = Path(worktree) / file_part
    if not target.is_file():
        return False, "feature_verification_unresolved"
    if test_part:
        content = target.read_text(encoding="utf-8", errors="replace")
        for fragment in test_part.split("."):
            if fragment and fragment not in content:
                return False, "feature_verification_unresolved"
    return True, "feature_verified"


def validate_own_features(lineage, *, prefix, worktree, manifest):
    """Validate the features a block adds on top of its predecessor.

    Returns ``(counts, entries)``. A mandatory own feature that is missing,
    unverifiable or not ``pass`` counts as missing — exactly like a dropped
    predecessor feature.
    """
    entries = []
    verified = 0
    missing = 0
    for feature in lineage.get("features", []):
        if not isinstance(feature, dict):
            continue
        identifier = str(feature.get("feature_id", ""))
        if not identifier.startswith(prefix):
            continue
        if not feature.get("required"):
            missing += 1
            entries.append(
                {
                    "feature_id": identifier,
                    "status": statuses.FAIL,
                    "reason_code": "own_feature_not_required",
                }
            )
            continue
        if feature.get("status") == statuses.NOT_APPLICABLE:
            missing += 1
            entries.append(
                {
                    "feature_id": identifier,
                    "status": statuses.FAIL,
                    "reason_code": "required_feature_declared_not_applicable",
                }
            )
            continue
        ok, reason = _verify_feature(feature, worktree=worktree, manifest=manifest)
        if not ok or feature.get("status") != statuses.PASS:
            missing += 1
            entries.append(
                {
                    "feature_id": identifier,
                    "status": statuses.FAIL,
                    "reason_code": reason if not ok else "feature_not_passing",
                }
            )
            continue
        verified += 1
        entries.append(
            {
                "feature_id": identifier,
                "status": statuses.PASS,
                "reason_code": reason,
            }
        )
    counts = {
        "prefix": prefix,
        "expected": verified + missing,
        "verified": verified,
        "missing": missing,
    }
    return counts, sorted(entries, key=lambda item: item["feature_id"])


def validate_lineage(
    *, lineage_path, predecessor_path, worktree, manifest=None, own_prefix=None
):
    """Validate a lineage file against its predecessor's feature list."""
    lineage_file = Path(lineage_path)
    predecessor_file = Path(predecessor_path)

    if not lineage_file.is_file():
        return {
            "status": statuses.FAIL,
            "reason_code": "feature_lineage_missing",
            "counts": {"expected": 0, "mapped": 0, "changed": 0, "missing": 0},
            "features": [],
            "issues": ["lineage file not found"],
        }
    if not predecessor_file.is_file():
        # Completeness must not be claimed without the predecessor list.
        return {
            "status": statuses.BLOCKED,
            "reason_code": "predecessor_feature_list_missing",
            "counts": {"expected": 0, "mapped": 0, "changed": 0, "missing": 0},
            "features": [],
            "issues": ["predecessor feature list not found"],
        }

    try:
        lineage = _load_json(lineage_file)
        predecessor = _load_json(predecessor_file)
    except ValueError as exc:
        return {
            "status": statuses.FAIL,
            "reason_code": "feature_lineage_unreadable",
            "counts": {"expected": 0, "mapped": 0, "changed": 0, "missing": 0},
            "features": [],
            "issues": [sanitize.scrub(str(exc))],
        }

    issues = _validate_shape(lineage, predecessor)
    if issues:
        return {
            "status": statuses.FAIL,
            "reason_code": "feature_lineage_invalid",
            "counts": {"expected": 0, "mapped": 0, "changed": 0, "missing": 0},
            "features": [],
            "issues": sorted(issues),
        }

    actual_digest = predecessor_digest(predecessor_file)
    if lineage["predecessor_feature_list_sha256"] != actual_digest:
        return {
            "status": statuses.FAIL,
            "reason_code": "predecessor_feature_list_hash_mismatch",
            "counts": {"expected": 0, "mapped": 0, "changed": 0, "missing": 0},
            "features": [],
            "issues": ["predecessor feature list digest does not match"],
        }
    if lineage["predecessor_artifact_id"] != predecessor["artifact_id"]:
        return {
            "status": statuses.FAIL,
            "reason_code": "predecessor_artifact_mismatch",
            "counts": {"expected": 0, "mapped": 0, "changed": 0, "missing": 0},
            "features": [],
            "issues": ["predecessor artifact id does not match"],
        }

    mapping = {}
    feature_reports = []
    seen_ids = set()
    for feature in lineage["features"]:
        if not isinstance(feature, dict):
            issues.append("feature entries must be objects")
            continue
        unknown = sorted(set(feature) - set(FEATURE_FIELDS + FEATURE_OPTIONAL_FIELDS))
        if unknown:
            issues.append(f"unknown feature field(s): {unknown}")
        missing = sorted(set(FEATURE_FIELDS) - set(feature))
        if missing:
            issues.append(f"missing feature field(s): {missing}")
            continue
        feature_id = feature["feature_id"]
        if not _FEATURE_ID_RE.match(str(feature_id)):
            issues.append(f"invalid feature_id: {feature_id}")
            continue
        if feature_id in seen_ids:
            issues.append(f"duplicate feature_id: {feature_id}")
            continue
        seen_ids.add(feature_id)
        mapping[feature_id] = feature
        predecessor_ref = feature.get("predecessor_feature_id")
        if predecessor_ref:
            mapping.setdefault(predecessor_ref, feature)

    expected = [
        entry
        for entry in predecessor["features"]
        if isinstance(entry, dict) and entry.get("required")
    ]
    missing_features = []
    changed_features = []
    mapped_features = []
    blocked = False

    for entry in sorted(expected, key=lambda item: str(item.get("feature_id"))):
        predecessor_id = entry.get("feature_id")
        feature = mapping.get(predecessor_id)
        if feature is None:
            missing_features.append(predecessor_id)
            feature_reports.append(
                {
                    "feature_id": predecessor_id,
                    "status": statuses.FAIL,
                    "reason_code": "required_feature_unmapped",
                }
            )
            continue
        if feature.get("feature_id") != predecessor_id or feature.get(
            "predecessor_feature_id"
        ):
            changed_features.append(predecessor_id)
        status = feature.get("status")
        if status not in statuses.ALL_STATUSES:
            missing_features.append(predecessor_id)
            feature_reports.append(
                {
                    "feature_id": predecessor_id,
                    "status": statuses.FAIL,
                    "reason_code": "feature_status_invalid",
                }
            )
            continue
        if not feature.get("required"):
            if not str(feature.get("owner_decision", "")).strip():
                missing_features.append(predecessor_id)
                feature_reports.append(
                    {
                        "feature_id": predecessor_id,
                        "status": statuses.FAIL,
                        "reason_code": "requirement_dropped_without_owner_decision",
                    }
                )
                continue
            changed_features.append(predecessor_id)
        if status == statuses.NOT_APPLICABLE and feature.get("required"):
            missing_features.append(predecessor_id)
            feature_reports.append(
                {
                    "feature_id": predecessor_id,
                    "status": statuses.FAIL,
                    "reason_code": "required_feature_declared_not_applicable",
                }
            )
            continue
        if not str(feature.get("current_location", "")).strip():
            missing_features.append(predecessor_id)
            feature_reports.append(
                {
                    "feature_id": predecessor_id,
                    "status": statuses.FAIL,
                    "reason_code": "feature_location_missing",
                }
            )
            continue
        ok, reason = _verify_feature(feature, worktree=worktree, manifest=manifest)
        if not ok:
            missing_features.append(predecessor_id)
            feature_reports.append(
                {
                    "feature_id": predecessor_id,
                    "status": statuses.FAIL,
                    "reason_code": reason,
                }
            )
            continue
        if status == statuses.FAIL:
            missing_features.append(predecessor_id)
            feature_reports.append(
                {
                    "feature_id": predecessor_id,
                    "status": statuses.FAIL,
                    "reason_code": "feature_declared_failed",
                }
            )
            continue
        if status == statuses.BLOCKED:
            blocked = True
            feature_reports.append(
                {
                    "feature_id": predecessor_id,
                    "status": statuses.BLOCKED,
                    "reason_code": "feature_declared_blocked",
                }
            )
            continue
        mapped_features.append(predecessor_id)
        feature_reports.append(
            {
                "feature_id": predecessor_id,
                "status": status,
                "reason_code": reason,
            }
        )

    counts = {
        "expected": len(expected),
        "mapped": len(sorted(set(mapped_features))),
        "changed": len(sorted(set(changed_features))),
        "missing": len(sorted(set(missing_features))),
    }
    own_counts = None
    if own_prefix:
        own_counts, own_entries = validate_own_features(
            lineage, prefix=own_prefix, worktree=worktree, manifest=manifest
        )
        feature_reports.extend(own_entries)
        if own_counts["missing"]:
            missing_features.extend(
                entry["feature_id"]
                for entry in own_entries
                if entry["status"] != statuses.PASS
            )
            counts["missing"] = len(sorted(set(missing_features)))

    if issues:
        status = statuses.FAIL
        reason_code = "feature_lineage_invalid"
    elif counts["missing"]:
        status = statuses.FAIL
        reason_code = "required_feature_missing"
    elif blocked:
        status = statuses.BLOCKED
        reason_code = "feature_verification_blocked"
    else:
        status = statuses.PASS
        reason_code = "feature_lineage_complete"

    report = {
        "status": status,
        "reason_code": reason_code,
        "counts": counts,
        "features": sorted(feature_reports, key=lambda item: item["feature_id"]),
        "issues": sorted(sanitize.scrub(issue) for issue in issues),
    }
    if own_counts is not None:
        report["own_counts"] = own_counts
    sanitize.assert_clean(report, "$feature_lineage")
    return report
