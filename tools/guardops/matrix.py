#!/usr/bin/env python3
"""Reader and applier for the exception fixture and manipulation matrix.

The matrix declares, finitely, what happens to a well formed exception object
when a specific thing is done to it. It exists because the qualification layer
introduced in this block has three outcomes that are easy to confuse in prose
and impossible to confuse mechanically: an object can be *unreadable*, it can
be *readable but not applicable here*, and it can be *applicable*. Only the
last one may ever reach a decision.

Two rules shape this module.

**Rule R9 — an effect must be evidenced.** Every entry declares an
``effect_probe``: the mechanical statement that the manipulation really
happened. :func:`apply` returns that evidence alongside the manipulated bytes,
and a caller asserts it *before* it asserts anything about the guard. A
manipulation that silently did nothing must fail the test, not quietly pass
it — that is exactly how a test in this repository stopped testing anything by
substituting a literal that had moved.

**No literal substitution.** Every operation here is structural: a named
field, a document, a file name, a byte count. Nothing looks for a string that
happens to be in the file today.

The applier is a pure function over one payload. It never opens an area, never
writes into an installation, and never touches a real exception object.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

MATRIX_PATH = "config/guard/exception-manipulation-matrix.json"

#: The finite operation vocabulary. A matrix naming anything else is rejected.
OPERATIONS = (
    "add_field",
    "append_bytes",
    "delete_field",
    "none",
    "rename_file",
    "replace_document",
    "set_field",
    "set_fields",
    "truncate_bytes",
)

#: The finite evidence vocabulary for rule R9.
#: ``unchanged`` is the control's probe and the only one that asserts the
#: absence of an effect. It exists so the control cannot silently become a
#: manipulated case: an entry that does nothing must prove it did nothing.
PROBES = (
    "bytes_differ",
    "field_absent",
    "field_differs",
    "field_present",
    "fields_differ",
    "filename_differs",
    "unchanged",
)

#: What the structural layer may conclude.
STRUCTURES = ("structurally_sound", "structurally_corrupt")

#: What the qualification layer may conclude about a sound object.
CLASSIFICATIONS = ("candidate", "expired", "not_yet_valid", "version_mismatch")

#: What the owner collection tool does with it.
COLLECTIONS = ("collected", "left_in_place")

TOP_FIELDS = (
    "schema_version",
    "kind",
    "block_id",
    "description",
    "fixtures",
    "entries",
    "codes_not_reachable_by_manipulation",
)
ENTRY_FIELDS = (
    "entry_id",
    "manipulation",
    "effect_probe",
    "expected_structure",
    "expected_corruption_code",
    "expected_classification",
    "expected_decision_effect",
    "expected_collection",
    "rationale",
)
FIXTURE_FIELDS = ("root", "properties", "read_only_areas", "abuse_test")
UNREACHABLE_FIELDS = ("code", "reason")


class MatrixError(ValueError):
    """Raised with a machine readable code for an unusable matrix."""

    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def load_matrix(root, path=MATRIX_PATH):
    """Load and validate the matrix document itself."""
    target = Path(root) / path
    if not target.is_file():
        raise MatrixError("matrix_missing", str(path))
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise MatrixError("matrix_not_json", str(exc)[:80]) from exc
    if not isinstance(document, dict):
        raise MatrixError("matrix_not_an_object")
    missing = sorted(set(TOP_FIELDS) - set(document))
    if missing:
        raise MatrixError("matrix_missing_field", ",".join(missing))
    unknown = sorted(set(document) - set(TOP_FIELDS))
    if unknown:
        raise MatrixError("matrix_unknown_field", ",".join(unknown))

    fixtures = document["fixtures"]
    if not isinstance(fixtures, dict):
        raise MatrixError("fixtures_not_an_object")
    if sorted(fixtures) != sorted(FIXTURE_FIELDS):
        raise MatrixError("fixtures_field_set")
    if str(fixtures["root"]).startswith("/"):
        raise MatrixError("fixture_root_absolute", str(fixtures["root"]))

    entries = document["entries"]
    if not isinstance(entries, list) or not entries:
        raise MatrixError("entries_empty")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise MatrixError("entry_not_an_object")
        if sorted(entry) != sorted(ENTRY_FIELDS):
            raise MatrixError("entry_field_set", str(entry.get("entry_id", "")))
        identifier = str(entry["entry_id"])
        if identifier in seen:
            raise MatrixError("entry_id_duplicated", identifier)
        seen.add(identifier)
        _validate_manipulation(identifier, entry["manipulation"])
        if entry["effect_probe"] not in PROBES:
            raise MatrixError("effect_probe_unknown", identifier)
        # The control and its probe are bound to each other in both
        # directions, so neither can drift into the other's role.
        no_operation = entry["manipulation"]["operation"] == "none"
        if no_operation != (entry["effect_probe"] == "unchanged"):
            raise MatrixError("control_and_probe_disagree", identifier)
        if entry["expected_structure"] not in STRUCTURES:
            raise MatrixError("expected_structure_unknown", identifier)
        if entry["expected_collection"] not in COLLECTIONS:
            raise MatrixError("expected_collection_unknown", identifier)
        if entry["expected_structure"] == "structurally_corrupt":
            if not str(entry["expected_corruption_code"]).strip():
                raise MatrixError("corruption_code_missing", identifier)
            if entry["expected_classification"]:
                raise MatrixError("corrupt_object_may_not_be_classified", identifier)
            # A corrupt object still blocks every decision. Collecting it
            # would repair a block nobody has looked at.
            if entry["expected_collection"] != "left_in_place":
                raise MatrixError("corrupt_object_may_not_be_collected", identifier)
        else:
            if entry["expected_corruption_code"]:
                raise MatrixError("sound_object_carries_a_corruption_code", identifier)
            if entry["expected_classification"] not in CLASSIFICATIONS:
                raise MatrixError("expected_classification_unknown", identifier)
        if not isinstance(entry["expected_decision_effect"], bool):
            raise MatrixError("decision_effect_not_boolean", identifier)
        # Only a candidate may ever reach a decision. This is the one
        # invariant of the whole block, so the matrix may not even declare a
        # counterexample.
        if entry["expected_decision_effect"] and (
            entry["expected_classification"] != "candidate"
        ):
            raise MatrixError("non_candidate_declared_with_decision_effect", identifier)
        if not str(entry["rationale"]).strip():
            raise MatrixError("rationale_missing", identifier)

    unreachable = document["codes_not_reachable_by_manipulation"]
    if not isinstance(unreachable, list):
        raise MatrixError("unreachable_not_a_list")
    for item in unreachable:
        if not isinstance(item, dict) or sorted(item) != sorted(UNREACHABLE_FIELDS):
            raise MatrixError("unreachable_field_set")
        if not str(item["reason"]).strip():
            raise MatrixError("unreachable_reason_missing", str(item.get("code", "")))
    return document


def _validate_manipulation(identifier, manipulation):
    if not isinstance(manipulation, dict):
        raise MatrixError("manipulation_not_an_object", identifier)
    operation = manipulation.get("operation")
    if operation not in OPERATIONS:
        raise MatrixError("operation_unknown", f"{identifier}:{operation}")
    needed = {
        "add_field": ("field", "value"),
        "append_bytes": ("bytes",),
        "delete_field": ("field",),
        "none": (),
        "rename_file": ("stem",),
        "replace_document": ("document",),
        "set_field": ("field", "value"),
        "set_fields": ("fields",),
        "truncate_bytes": ("count",),
    }[operation]
    allowed = set(needed) | {"operation", "reseal", "relative_to", "offset_seconds"}
    if operation in ("set_field", "add_field") and "relative_to" in manipulation:
        # A temporal value is derived, not written down: declaring both would
        # allow the two to disagree.
        needed = tuple(name for name in needed if name != "value")
        if "value" in manipulation:
            raise MatrixError("value_and_relative_to_both_declared", identifier)
    if operation == "set_fields":
        assignments = manipulation.get("fields")
        if not isinstance(assignments, list) or not assignments:
            raise MatrixError("fields_empty", identifier)
        for assignment in assignments:
            if not isinstance(assignment, dict) or "field" not in assignment:
                raise MatrixError("field_assignment_malformed", identifier)
            unknown_keys = sorted(
                set(assignment) - {"field", "value", "relative_to", "offset_seconds"}
            )
            if unknown_keys:
                raise MatrixError(
                    "field_assignment_unknown_key", f"{identifier}:{','.join(unknown_keys)}"
                )
            if assignment.get("relative_to", "now") not in ("created_at", "now"):
                raise MatrixError("relative_to_unknown", identifier)
    missing = sorted(set(needed) - set(manipulation))
    if missing:
        raise MatrixError("manipulation_missing_field", f"{identifier}:{','.join(missing)}")
    unknown = sorted(set(manipulation) - allowed)
    if unknown:
        raise MatrixError("manipulation_unknown_field", f"{identifier}:{','.join(unknown)}")
    if "relative_to" in manipulation and manipulation["relative_to"] not in (
        "created_at",
        "now",
    ):
        raise MatrixError("relative_to_unknown", identifier)


class Applied:
    """One manipulated object plus the evidence that it was manipulated."""

    __slots__ = ("entry_id", "stem", "raw", "original_raw", "probe", "probe_holds", "probe_detail")

    def __init__(self, entry_id, stem, raw, original_raw, probe, probe_holds, probe_detail):
        self.entry_id = entry_id
        self.stem = stem
        self.raw = raw
        self.original_raw = original_raw
        self.probe = probe
        #: Rule R9. ``False`` means the manipulation did not happen, and the
        #: caller must fail on that rather than on the guard's answer.
        self.probe_holds = probe_holds
        self.probe_detail = probe_detail

    def digest(self):
        return hashlib.sha256(self.raw).hexdigest()


def _reseal(payload, integrity_digest):
    payload["integrity_sha256"] = ""
    payload["integrity_sha256"] = integrity_digest(payload)
    return payload


def apply(entry, payload, *, integrity_digest, now, stem):
    """Apply one entry to ``payload``. Pure: nothing on disk is touched.

    ``integrity_digest`` is the *guard's* own function, passed in rather than
    reimplemented, so a resealed object is sealed exactly the way the guard
    would seal it.
    """
    original = dict(copy.deepcopy(payload))
    original_raw = json.dumps(original, sort_keys=True, indent=2).encode("utf-8")
    manipulation = entry["manipulation"]
    operation = manipulation["operation"]
    working = copy.deepcopy(original)
    new_stem = stem
    raw = None

    if operation == "none":
        pass
    elif operation == "set_field":
        working[manipulation["field"]] = _value_of(manipulation, original, now)
    elif operation == "add_field":
        working[manipulation["field"]] = _value_of(manipulation, original, now)
    elif operation == "set_fields":
        for assignment in manipulation["fields"]:
            working[assignment["field"]] = _value_of(assignment, original, now)
    elif operation == "delete_field":
        working.pop(manipulation["field"], None)
    elif operation == "rename_file":
        new_stem = str(manipulation["stem"])
    elif operation == "replace_document":
        raw = str(manipulation["document"]).encode("utf-8")
    elif operation == "append_bytes":
        raw = original_raw + str(manipulation["bytes"]).encode("utf-8")
    elif operation == "truncate_bytes":
        raw = original_raw[: -int(manipulation["count"])]

    if raw is None:
        if manipulation.get("reseal"):
            working = _reseal(working, integrity_digest)
        raw = json.dumps(working, sort_keys=True, indent=2).encode("utf-8")

    holds, detail = _probe(entry, original, original_raw, working, raw, stem, new_stem)
    return Applied(
        str(entry["entry_id"]), new_stem, raw, original_raw, entry["effect_probe"], holds, detail
    )


def _value_of(manipulation, original, now):
    """Resolve a declared value, including the two temporal forms."""
    if "relative_to" not in manipulation:
        return manipulation["value"]
    offset = int(manipulation.get("offset_seconds", 0))
    if manipulation["relative_to"] == "now":
        return int(now) + offset
    return int(original[manipulation["relative_to"]]) + offset


def _probe(entry, original, original_raw, working, raw, stem, new_stem):
    """Rule R9. Did the declared manipulation actually take effect?"""
    probe = entry["effect_probe"]
    field = entry["manipulation"].get("field", "")
    if probe == "unchanged":
        return raw == original_raw and new_stem == stem, "raw_bytes"
    if probe == "bytes_differ":
        return raw != original_raw, "raw_bytes"
    if probe == "filename_differs":
        return new_stem != stem, "stem"
    if probe == "field_absent":
        return field in original and field not in working, field
    if probe == "field_present":
        return field not in original and field in working, field
    if probe == "field_differs":
        return (
            field in original
            and field in working
            and working[field] != original[field]
        ), field
    if probe == "fields_differ":
        names = [str(item["field"]) for item in entry["manipulation"]["fields"]]
        unchanged = [
            name
            for name in names
            if name not in original
            or name not in working
            or working[name] == original[name]
        ]
        return not unchanged, ",".join(names)
    return False, "unknown_probe"  # pragma: no cover - load_matrix rejects this


def reachable_codes(document):
    """Every corruption code the matrix claims to reach."""
    return sorted(
        {
            str(entry["expected_corruption_code"])
            for entry in document["entries"]
            if entry["expected_corruption_code"]
        }
    )


def declared_unreachable(document):
    return sorted(
        {str(item["code"]) for item in document["codes_not_reachable_by_manipulation"]}
    )
