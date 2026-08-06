"""Rule R4 — schema before data.

When a configuration format is extended, the accepting reader or validator is
effective **first**, at the latest in the same commit. No configuration file
may carry a field its declared loader does not yet accept.

This module is the mechanical enforcement. It is deliberately general: it does
not know ``rules.json``, it knows *bindings*. Every configuration file below a
declared coverage root must be matched by exactly one binding, and every
binding names the reader that is authoritative for that file:

``callable``
    a real loader in the tooling, addressed as ``module:function``. The
    binding declares whether the file must be *accepted* or must be
    *rejected* — the invalid manifest fixtures exist precisely to be
    rejected, and a loader that silently accepts them is broken.
``structural``
    for a format whose accepting reader is the declared field set itself.
    The binding lists the keys the reader accepts; an unknown top-level key
    is a failure, which is exactly the class of defect R4 exists for.

Coverage is enforced in both directions. A configuration file that no binding
matches fails, so a new format cannot be introduced without naming its
reader. A file that two bindings match also fails, because then it is not
determined which reader is authoritative.

Nothing here executes a configuration. Loaders are imported and called on a
path; a loader that has side effects would be the defect, not this module.
"""

from __future__ import annotations

import glob
import importlib
import json
import os
from pathlib import Path

BINDINGS_PATH = "config/governance/config-loaders.json"

KIND_CALLABLE = "callable"
KIND_STRUCTURAL = "structural"
KINDS = (KIND_CALLABLE, KIND_STRUCTURAL)

ACCEPTED = "accepted"
REJECTED = "rejected"
EXPECTATIONS = (ACCEPTED, REJECTED)

STYLE_PATH = "path"
STYLE_ROOT_RELATIVE = "root_relative"
STYLES = (STYLE_PATH, STYLE_ROOT_RELATIVE)

BINDING_FIELDS = (
    "binding_id",
    "expectation",
    "kind",
    "pattern",
    "reason",
)
CALLABLE_FIELDS = ("call_style", "loader")
STRUCTURAL_FIELDS = ("optional_fields", "required_fields")


class BindingError(ValueError):
    """Raised with a machine readable code for an unusable binding set."""

    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def load_bindings(root, path=BINDINGS_PATH):
    """Load and validate the binding document itself."""
    target = Path(root) / path
    if not target.is_file():
        raise BindingError("bindings_missing", path)
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise BindingError("bindings_not_json", str(exc)[:80]) from exc
    if not isinstance(document, dict):
        raise BindingError("bindings_not_an_object")
    bindings = document.get("bindings")
    roots = document.get("coverage_roots")
    if not isinstance(bindings, list) or not bindings:
        raise BindingError("bindings_empty")
    if not isinstance(roots, list) or not roots:
        raise BindingError("coverage_roots_empty")

    seen = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise BindingError("binding_not_an_object")
        expected = set(BINDING_FIELDS)
        kind = binding.get("kind")
        if kind == KIND_CALLABLE:
            expected |= set(CALLABLE_FIELDS)
        elif kind == KIND_STRUCTURAL:
            expected |= set(STRUCTURAL_FIELDS)
        else:
            raise BindingError("binding_kind_unknown", str(kind))
        missing = sorted(expected - set(binding))
        if missing:
            raise BindingError("binding_missing_field", ",".join(missing))
        unknown = sorted(set(binding) - expected)
        if unknown:
            raise BindingError("binding_unknown_field", ",".join(unknown))
        if binding["expectation"] not in EXPECTATIONS:
            raise BindingError("binding_expectation_unknown", binding["binding_id"])
        if kind == KIND_CALLABLE and binding["call_style"] not in STYLES:
            raise BindingError("binding_call_style_unknown", binding["binding_id"])
        if not str(binding["reason"]).strip():
            raise BindingError("binding_reason_missing", binding["binding_id"])
        if binding["binding_id"] in seen:
            raise BindingError("binding_id_duplicated", binding["binding_id"])
        seen.add(binding["binding_id"])
    return document


def _matches(root, pattern):
    """Files a binding pattern matches, as worktree relative posix paths."""
    absolute = os.path.join(str(root), str(pattern))
    found = glob.glob(absolute, recursive=True)
    return {
        Path(item).relative_to(Path(root)).as_posix()
        for item in found
        if os.path.isfile(item)
    }


def covered_files(root, document):
    """Every configuration file below the declared coverage roots."""
    found = set()
    for entry in document["coverage_roots"]:
        base = Path(root) / str(entry)
        if not base.is_dir():
            continue
        for item in base.rglob("*.json"):
            if item.is_file():
                found.add(item.relative_to(Path(root)).as_posix())
    return found


def assign(root, document):
    """Map every covered file to its single binding.

    Returns ``(assignment, uncovered, ambiguous)``.
    """
    assignment = {}
    ambiguous = {}
    for binding in document["bindings"]:
        for relative in _matches(root, binding["pattern"]):
            if relative in assignment:
                ambiguous.setdefault(relative, [assignment[relative]]).append(
                    binding["binding_id"]
                )
                continue
            assignment[relative] = binding["binding_id"]
    uncovered = sorted(covered_files(root, document) - set(assignment))
    return assignment, uncovered, {key: sorted(set(value)) for key, value in ambiguous.items()}


def resolve_loader(specification):
    """Import ``module:function`` and return the callable."""
    module_name, separator, attribute = str(specification).partition(":")
    if not separator or not module_name or not attribute:
        raise BindingError("loader_specification_malformed", str(specification))
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise BindingError("loader_module_missing", str(exc)[:80]) from exc
    loader = getattr(module, attribute, None)
    if not callable(loader):
        raise BindingError("loader_attribute_missing", str(specification))
    return loader


def _apply_callable(root, binding, relative):
    """Return ``""`` when the file behaves as the binding declares."""
    loader = resolve_loader(binding["loader"])
    style = binding["call_style"]
    try:
        if style == STYLE_PATH:
            loader(str(Path(root) / relative))
        else:
            loader(str(root), relative)
    except Exception:  # noqa: BLE001 - any rejection counts as a rejection
        return "" if binding["expectation"] == REJECTED else "loader_rejected_the_file"
    return "" if binding["expectation"] == ACCEPTED else "loader_accepted_a_rejected_file"


def _apply_structural(root, binding, relative):
    target = Path(root) / relative
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "" if binding["expectation"] == REJECTED else "file_is_not_readable_json"
    if not isinstance(document, dict):
        return "" if binding["expectation"] == REJECTED else "file_is_not_an_object"
    required = set(binding["required_fields"])
    optional = set(binding["optional_fields"])
    problem = ""
    missing = sorted(required - set(document))
    if missing:
        problem = "declared_field_missing:" + ",".join(missing)
    elif "*" not in optional:
        unknown = sorted(set(document) - required - optional)
        if unknown:
            # Exactly the R4 defect: data carries a field the reader does
            # not accept.
            problem = "field_not_accepted_by_the_declared_reader:" + ",".join(unknown)
    if binding["expectation"] == REJECTED:
        return "" if problem else "reader_accepted_a_rejected_file"
    return problem


def apply(root, binding, relative):
    """Run one binding against one file. ``""`` means it behaved."""
    if binding["kind"] == KIND_CALLABLE:
        return _apply_callable(root, binding, relative)
    return _apply_structural(root, binding, relative)


def check(root, path=BINDINGS_PATH):
    """Full R4 check. Returns ``(failures, diagnostics)``.

    A failure is ``(relative_path, code)``. The binding document itself is
    validated first: an unusable binding set is a failure, never a silent
    pass.
    """
    failures = []
    try:
        document = load_bindings(root, path)
    except BindingError as exc:
        return [(path, exc.code)], []

    assignment, uncovered, ambiguous = assign(root, document)
    for relative in uncovered:
        failures.append((relative, "no_declared_loader"))
    for relative, ids in sorted(ambiguous.items()):
        failures.append((relative, "several_declared_loaders:" + ",".join(ids)))

    by_id = {binding["binding_id"]: binding for binding in document["bindings"]}
    used = set()
    for relative, binding_id in sorted(assignment.items()):
        used.add(binding_id)
        code = apply(root, by_id[binding_id], relative)
        if code:
            failures.append((relative, code))
    for binding_id in sorted(set(by_id) - used):
        # A binding that matches nothing is stale and would hide a gap.
        failures.append((by_id[binding_id]["pattern"], "binding_matches_nothing"))

    diagnostics = [
        f"bindings={len(by_id)}",
        f"configuration_files={len(assignment)}",
    ]
    return sorted(failures), diagnostics
