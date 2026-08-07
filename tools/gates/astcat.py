"""Closed exclusion vocabulary for the disposition register (block B0f).

Block B0e excluded 123 candidates with free-text reasons. Free text can be
read, but it cannot be *falsified*: nothing breaks when the stated mechanism
quietly disappears from the code. This module replaces the load-bearing role
of that text with a closed vocabulary of categories, each of which makes one
machine-readable claim and carries one mechanical check that can refute it
against the current source. The free text survives only as annotation.

Every category declares:

``rule``       R9 or R10 — the vocabularies are disjoint because the rules'
               semantics are disjoint.
``claim``      the general technical fact the category asserts. It names no
               file, product, module or test; candidate-specific facts live
               in the entry's ``category_proof``.
``criterion``  how the claim is checked mechanically. The checks below fall
               into three families: structural facts read from the current
               syntax tree of the anchoring unit (and, where the claim spans
               units, of proof-named consumer units); execution probes that
               run a single test with the perturbation neutralised and
               require it to fail; and rejection probes that delete the
               claimed key from the bound document and require the R4-bound
               reader to reject the mutilated copy.

``validate_entry`` re-checks one register entry. ``""`` means the category
holds at the current candidate; any other value is a machine readable code
and means the exclusion is *not* substantiated — which is a finding, never a
formatting problem. There is deliberately no catch-all category: a candidate
that fits nothing goes back to normative treatment.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import astcorpus, configload

RULE_R9 = "R9"
RULE_R10 = "R10"

_TOLERANCE_KEYWORDS = ("missing_ok", "ignore_errors", "exist_ok")
_EXIST_CHECKS = ("exists", "is_file", "is_dir")
_REMOVALS = ("unlink", "rmtree", "remove", "rmdir", "removedirs")
_OBSERVING_CALLS = ("mkdir", "open", "read_text", "read_bytes", "stat", "areas")

CATEGORIES = {
    "r9_injection_load_bearing": {
        "rule": RULE_R9,
        "claim": (
            "The test's asserted outcome cannot occur without the injected "
            "disturbance taking effect."
        ),
        "criterion": (
            "Execution probe: the named test is run once with the injection "
            "neutralised through an import-time syntax tree rewrite bound to "
            "the anchor fingerprint; the probe holds only when that run "
            "fails. A test that stays green without its injection refutes "
            "the category."
        ),
        "proof_fields": ("test",),
    },
    "r9_post_judgment_position": {
        "rule": RULE_R9,
        "claim": (
            "The perturbation runs after every judgment-forming statement of "
            "its unit; nothing the unit asserts, raises or collects as a "
            "failure can depend on its effect."
        ),
        "criterion": (
            "Structural: below the anchor's line inside the unit there is no "
            "assert statement, no assert*-call, no raise and no write to a "
            "failure collection that the unit emits or returns."
        ),
        "proof_fields": (),
    },
    "r9_after_state_observed": {
        "rule": RULE_R9,
        "claim": (
            "A later statement of the same unit observes the perturbation's "
            "intended after-state mechanically: it asserts over the target "
            "or performs a strict call on it that raises when the "
            "perturbation did not take effect."
        ),
        "criterion": (
            "Structural: after the anchor, an assert referencing the "
            "target's base name exists, or a call on that base name from the "
            "observing set runs without any tolerance keyword."
        ),
        "proof_fields": (),
    },
    "r9_reraising_error_path": {
        "rule": RULE_R9,
        "claim": (
            "The perturbation sits on an error path that always re-raises; "
            "no run that reaches it can end in a positive verdict."
        ),
        "criterion": (
            "Structural: the anchor's innermost except handler contains a "
            "bare raise, and no return leaves the handler before it."
        ),
        "proof_fields": (),
    },
    "r9_both_outcomes_judged": {
        "rule": RULE_R9,
        "claim": (
            "Both outcomes of the perturbation are judged: the exception "
            "path and the success path each record a distinct verdict, so "
            "an ineffective perturbation cannot pass silently."
        ),
        "criterion": (
            "Structural: the anchor sits in a try statement whose handler "
            "body and whose else/success body each write to a judgment sink "
            "(failure collection, diagnostics-verdict or assert)."
        ),
        "proof_fields": (),
    },
    "r9_property_established_at_creation": {
        "rule": RULE_R9,
        "claim": (
            "The property the anchor appears to establish was already "
            "established when the target was created earlier in the same "
            "unit; the anchor only re-tightens it."
        ),
        "criterion": (
            "Structural: before the anchor, a creating call on the same "
            "base name carries an explicit octal mode constant, or the unit "
            "gates on os.geteuid() == 0 before creating the target."
        ),
        "proof_fields": ("via",),
    },
    "r9_loud_guarded_removal": {
        "rule": RULE_R9,
        "claim": (
            "The guard condition is exactly the intended after-state: the "
            "removal runs only when the target exists and raises on "
            "failure, so target-absent is guaranteed either way."
        ),
        "criterion": (
            "Structural: the anchor is a removal without tolerance keywords "
            "inside an if whose test calls an existence check on the same "
            "base name, with no swallowing handler in between."
        ),
        "proof_fields": (),
    },
    "r9_target_unconsumed_after": {
        "rule": RULE_R9,
        "claim": (
            "Nothing after the perturbation reads or consumes the perturbed "
            "target within the unit; whatever the operation did or failed "
            "to do can no longer influence any judgment."
        ),
        "criterion": (
            "Structural: below the anchor's line, no expression of the unit "
            "references the target's dotted chain."
        ),
        "proof_fields": (),
    },
    "r9_conditional_import_target": {
        "rule": RULE_R9,
        "claim": (
            "The patched attribute is optional by construction: the target "
            "module binds it inside a try whose handler catches "
            "ImportError, so absence is a designed state and the tolerant "
            "patch cannot mask a rename."
        ),
        "criterion": (
            "Structural, cross-file: in the proof-named module the "
            "attribute is assigned or imported inside a try statement with "
            "an ImportError handler."
        ),
        "proof_fields": ("module", "attribute"),
    },
    "r10_required_key_prevalidated": {
        "rule": RULE_R10,
        "claim": (
            "The walked key cannot be silently absent: deleting it from the "
            "governing document makes the document's R4-bound reader reject "
            "the document before any walk runs."
        ),
        "criterion": (
            "Rejection probe: a copy of the proof-named document with the "
            "proof-named key path deleted is fed to the reader bound by "
            "config/governance/config-loaders.json; the probe holds only "
            "when the reader rejects the copy."
        ),
        "proof_fields": ("document", "key_path"),
    },
    "r10_emptiness_fails_closed": {
        "rule": RULE_R10,
        "claim": (
            "An empty walk cannot carry a positive judgment here: the unit "
            "turns emptiness into a failure, a mismatch against a non-empty "
            "expectation, a visible skip or a conservative non-success "
            "return."
        ),
        "criterion": (
            "Structural, per proof mechanism: an emptiness guard over the "
            "walked or accumulated name feeding a judgment sink; a "
            "post-walk membership/equality/length pin against a non-empty "
            "constant; a reverse walk flagging unmatched rows; a "
            "fall-through return of a non-success constant; or a direct "
            "failure yielded from the empty walk path."
        ),
        "proof_fields": ("mechanism", "names"),
    },
    "r10_excusal_only_flow": {
        "rule": RULE_R10,
        "claim": (
            "The walked value only ever excuses or suppresses findings: "
            "every consumption is a membership test that skips a finding or "
            "a mask that blanks declared content, so emptiness can only "
            "make the check stricter."
        ),
        "criterion": (
            "Structural, across proof-named consumer units: every use of "
            "the bound name is the container side of an in/not-in "
            "comparison, or flows only into the mask-building path named by "
            "the proof."
        ),
        "proof_fields": ("names", "consumers"),
    },
    "r10_diagnostics_only_flow": {
        "rule": RULE_R10,
        "claim": (
            "The walk feeds only diagnostics, labels or a discarded return; "
            "the unit's verdict is computed without it."
        ),
        "criterion": (
            "Structural: writes fed by the walk reach only the proof-named "
            "sink, and that sink appears in no failure position: it is "
            "passed to the report emitter only as its diagnostics argument, "
            "used only in label fields, or the value is discarded at the "
            "proof-named consumer."
        ),
        "proof_fields": ("mechanism", "names"),
    },
    "r10_runtime_emptyset_guarded": {
        "rule": RULE_R10,
        "claim": (
            "The counts this walk produces are consumed through the "
            "engine's empty-set rule with an independently derived "
            "expectation, so a vacuous walk becomes blocked, never pass."
        ),
        "criterion": (
            "Structural, cross-unit: the proof-named consumer calls the "
            "anchor's enclosing function and routes the result through "
            "emptyset.verdict or emptyset.require_non_empty."
        ),
        "proof_fields": ("consumer",),
    },
}


class CategoryError(ValueError):
    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


# ---------------------------------------------------------------- helpers


def _call_name(node):
    return getattr(node.func, "id", "") or getattr(node.func, "attr", "")


def _ident(node):
    """A node's name or attribute label; empty for anonymous nodes."""
    return getattr(node, "id", "") or getattr(node, "attr", "")


def _base_name(node):
    """Leftmost name of an attribute/subscript chain or call target."""
    current = node
    while True:
        if isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, (ast.Attribute, ast.Subscript)):
            current = current.value
        elif isinstance(current, ast.Name):
            return current.id
        else:
            return ""


def _dotted(node):
    """Dotted chain of an expression: ``self.area.mkdir`` → that string.

    Wrapping converter calls (``str(x)``, ``Path(x)``) are unwrapped so the
    chain names the state-carrying expression, not the conversion."""
    if isinstance(node, ast.Call):
        name = getattr(node.func, "id", "")
        if name in ("str", "Path") and node.args:
            return _dotted(node.args[0])
        return _dotted(node.func)
    parts = []
    current = node
    while isinstance(current, (ast.Attribute, ast.Subscript)):
        if isinstance(current, ast.Attribute):
            parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


_RECEIVER_METHODS = frozenset(
    {
        "write_text",
        "write_bytes",
        "chmod",
        "unlink",
        "mkdir",
        "rmdir",
        "touch",
        "rename",
        "replace",
        "truncate",
    }
)
_MODULE_BASES = frozenset({"os", "shutil", "pathlib", "subprocess"})


def _anchor_target_chain(anchor):
    if isinstance(anchor, ast.Call):
        if isinstance(anchor.func, ast.Attribute):
            receiver = _dotted(anchor.func.value)
            if (
                anchor.func.attr in _RECEIVER_METHODS
                and receiver
                and receiver.split(".", 1)[0] not in _MODULE_BASES
            ):
                return receiver
        if anchor.args:
            chain = _dotted(anchor.args[0])
            if chain:
                return chain
        chain = _dotted(anchor.func)
        if "." in chain:
            return chain.rsplit(".", 1)[0]
        return chain
    return _dotted(anchor)


def _references_chain(node, target):
    """True when the subtree contains the target chain or an extension."""
    for inner in ast.walk(node):
        chain = _dotted(inner)
        if chain and (chain == target or chain.startswith(target + ".")):
            return True
    return False


def _fingerprint(node):
    from . import astscan

    return astscan._fingerprint(node)


def locate_anchor(root, entry):
    """Find the entry's anchoring node in the current tree.

    Returns ``(tree, unit, node)`` or raises :class:`CategoryError` — a
    vanished anchor means the binding broke and the entry must be re-decided
    (that case is already a validate() failure upstream).
    """
    target = Path(root) / entry["file"]
    if not target.is_file():
        raise CategoryError("anchor_file_missing", entry["file"])
    try:
        tree = ast.parse(target.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise CategoryError("anchor_file_unparseable", entry["file"]) from exc
    for unit in astcorpus.collect_units(tree):
        if unit.qualname != entry["unit"]:
            continue
        seen = 0
        for node in ast.walk(unit.node):
            if _fingerprint(node) == entry["fingerprint"]:
                if seen == entry["occurrence"]:
                    return tree, unit, node
                seen += 1
    raise CategoryError("anchor_not_found", entry["candidate_id"])


def _statements_after(unit, anchor):
    """Nodes of the unit that start strictly below the anchor's line."""
    return [
        node
        for node in ast.walk(unit.node)
        if getattr(node, "lineno", 0) > anchor.lineno
    ]


def _failure_sink_names(unit):
    """Names whose contents the unit emits or returns as its judgment."""
    names = set()
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Return) and node.value is not None:
            for inner in ast.walk(node.value):
                if isinstance(inner, ast.Name):
                    names.add(inner.id)
        if isinstance(node, ast.Call) and _call_name(node) in ("emit", "_emit"):
            for argument in node.args[:2]:
                for inner in ast.walk(argument):
                    if isinstance(inner, ast.Name):
                        names.add(inner.id)
    return names


def _is_assertion(node):
    if isinstance(node, ast.Assert):
        return True
    return isinstance(node, ast.Call) and _call_name(node).startswith("assert")


def _has_tolerance(call):
    for keyword in call.keywords:
        if keyword.arg in _TOLERANCE_KEYWORDS:
            if isinstance(keyword.value, ast.Constant) and keyword.value.value:
                return True
    return False


# ------------------------------------------------------------- validators


def _check_injection_load_bearing(root, entry, proof):
    reference = str(proof.get("test", ""))
    file_part, _, test_part = reference.partition("::")
    if not file_part or not test_part or file_part != entry["file"]:
        return "probe_reference_invalid"
    node_id = f"{file_part}::{test_part.replace('.', '::')}"
    with tempfile.NamedTemporaryFile(
        prefix="b0f-neuter-", suffix=".marker", delete=False
    ) as handle:
        marker_path = handle.name
    # The neuter plugin lives beside this validator; the probed project
    # (which may be a fixture worktree) need not contain it.
    engine_root = str(Path(__file__).resolve().parents[2])
    python_path = os.environ.get("PYTHONPATH", "")
    if python_path:
        python_path = engine_root + os.pathsep + python_path
    else:
        python_path = engine_root
    environment = dict(os.environ)
    environment.update(
        {
            "B0F_NEUTER_FILE": str(Path(root) / entry["file"]),
            "B0F_NEUTER_FINGERPRINT": entry["fingerprint"],
            "B0F_NEUTER_OCCURRENCE": str(entry["occurrence"]),
            "B0F_NEUTER_MARKER": marker_path,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": python_path,
        }
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                node_id,
                "-q",
                "-x",
                "-p",
                "tools.gates.b0fneuter",
                "-p",
                "no:cacheprovider",
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
        )
        marker = Path(marker_path).read_text(encoding="utf-8")
    finally:
        Path(marker_path).unlink()
    if marker != "applied":
        # Rule R9 for the probe: without evidence that the rewrite occurred,
        # a failing run proves nothing.
        return "neutering_did_not_apply"
    if completed.returncode == 0:
        # The test stayed green without its injection: the category claim
        # is refuted and the exclusion is unsubstantiated.
        return "test_green_without_injection"
    return ""


def _check_post_judgment_position(root, entry, proof):
    _tree, unit, anchor = locate_anchor(root, entry)
    sinks = _failure_sink_names(unit)
    for node in _statements_after(unit, anchor):
        if _is_assertion(node) or isinstance(node, ast.Raise):
            return "judgment_after_anchor"
        if (
            isinstance(node, ast.Call)
            and _call_name(node) in ("append", "extend")
            and isinstance(node.func, ast.Attribute)
            and _base_name(node.func.value) in sinks
        ):
            return "judgment_after_anchor"
    return ""


def _check_after_state_observed(root, entry, proof):
    _tree, unit, anchor = locate_anchor(root, entry)
    target = _anchor_target_chain(anchor)
    if not target:
        return "anchor_target_unresolved"
    for node in _statements_after(unit, anchor):
        if isinstance(node, ast.Assert) and _references_chain(node, target):
            return ""
        if isinstance(node, ast.Call) and _call_name(node).startswith("assert"):
            if any(_references_chain(argument, target) for argument in node.args):
                return ""
        if isinstance(node, ast.Call) and _call_name(node) in _OBSERVING_CALLS:
            if _has_tolerance(node):
                continue
            func_chain = _dotted(node.func)
            if func_chain.startswith(target + "."):
                return ""
            if node.args and _dotted(node.args[0]) == target:
                return ""
    return "no_observation_after_anchor"


def _enclosing(unit, anchor, kinds):
    """Innermost enclosing node of the given kinds containing the anchor."""
    best = None
    for node in ast.walk(unit.node):
        if isinstance(node, kinds):
            span_start = getattr(node, "lineno", 0)
            span_end = getattr(node, "end_lineno", span_start)
            if span_start <= anchor.lineno <= span_end:
                if best is None or span_start >= getattr(best, "lineno", 0):
                    best = node
    return best


def _check_reraising_error_path(root, entry, proof):
    _tree, unit, anchor = locate_anchor(root, entry)
    handler = _enclosing(unit, anchor, (ast.ExceptHandler,))
    if handler is None:
        return "anchor_not_in_handler"
    raises = any(isinstance(node, ast.Raise) for node in ast.walk(ast.Module(body=handler.body, type_ignores=[])))
    returns = any(isinstance(node, ast.Return) for node in ast.walk(ast.Module(body=handler.body, type_ignores=[])))
    if raises and not returns:
        return ""
    return "handler_does_not_reraise"


def _writes_sink(nodes, sinks):
    for node in nodes:
        if _is_assertion(node):
            return True
        if (
            isinstance(node, ast.Call)
            and _call_name(node) in ("append", "extend")
            and isinstance(node.func, ast.Attribute)
            and _base_name(node.func.value) in sinks
        ):
            return True
    return False


def _check_both_outcomes_judged(root, entry, proof):
    _tree, unit, anchor = locate_anchor(root, entry)
    try_node = _enclosing(unit, anchor, (ast.Try,))
    if try_node is None:
        return "anchor_not_in_try"
    sinks = _failure_sink_names(unit) | {"diagnostics"}
    handler_nodes = [
        node
        for handler in try_node.handlers
        for node in ast.walk(ast.Module(body=handler.body, type_ignores=[]))
    ]
    success_bodies = list(try_node.orelse)
    success_bodies.extend(
        stmt for stmt in try_node.body if getattr(stmt, "lineno", 0) > anchor.lineno
    )
    success_nodes = [
        node for node in ast.walk(ast.Module(body=success_bodies, type_ignores=[]))
    ]
    if _writes_sink(handler_nodes, sinks) and _writes_sink(success_nodes, sinks):
        return ""
    return "outcomes_not_both_judged"


def _check_property_established_at_creation(root, entry, proof):
    _tree, unit, anchor = locate_anchor(root, entry)
    target = _anchor_target_chain(anchor)
    via = str(proof.get("via", "creation_mode"))
    before = [
        node
        for node in ast.walk(unit.node)
        if getattr(node, "lineno", 0) and node.lineno < anchor.lineno
    ]
    if via == "root_gate":
        gate_unit = unit
        site = proof.get("site")
        if site:
            gate_unit = _resolve_unit(root, site)
            if gate_unit is None:
                return "proof_site_unresolved"
        for node in ast.walk(gate_unit.node):
            if isinstance(node, ast.Compare):
                names = {_call_name(n) for n in ast.walk(node) if isinstance(n, ast.Call)}
                if "geteuid" in names:
                    return ""
        return "root_gate_not_found"
    for node in before:
        if isinstance(node, ast.Call) and _call_name(node) in ("open", "mkdir"):
            references_target = (
                _base_name(node.func) == target
                or any(_base_name(argument) == target for argument in node.args)
                or any(
                    target == inner.id
                    for argument in node.args
                    for inner in ast.walk(argument)
                    if isinstance(inner, ast.Name)
                )
            )
            has_mode = any(
                isinstance(argument, ast.Constant)
                and isinstance(argument.value, int)
                for argument in node.args
            ) or any(keyword.arg == "mode" for keyword in node.keywords)
            if references_target and has_mode:
                return ""
    return "creating_call_not_found"


def _check_loud_guarded_removal(root, entry, proof):
    _tree, unit, anchor = locate_anchor(root, entry)
    if not isinstance(anchor, ast.Call) or _call_name(anchor) not in _REMOVALS:
        return "anchor_not_a_removal"
    if _has_tolerance(anchor):
        return "removal_is_tolerant"
    guard = _enclosing(unit, anchor, (ast.If,))
    if guard is None:
        return "anchor_not_guarded"
    target = _anchor_target_chain(anchor)
    guard_checks = [
        node
        for node in ast.walk(guard.test)
        if isinstance(node, ast.Call) and _call_name(node) in _EXIST_CHECKS
    ]
    if not any(
        _base_name(check.func) == target
        or (check.args and _base_name(check.args[0]) == target)
        for check in guard_checks
    ):
        return "guard_does_not_check_target"
    try_node = _enclosing(unit, anchor, (ast.Try,))
    if try_node is not None and getattr(try_node, "lineno", 0) >= guard.lineno:
        for handler in try_node.handlers:
            if all(isinstance(s, (ast.Pass, ast.Continue)) for s in handler.body):
                return "removal_swallowed"
    return ""


def _check_target_unconsumed_after(root, entry, proof):
    _tree, unit, anchor = locate_anchor(root, entry)
    target = _anchor_target_chain(anchor)
    if not target:
        return "anchor_target_unresolved"
    anchor_end = getattr(anchor, "end_lineno", anchor.lineno)
    for node in ast.walk(unit.node):
        if getattr(node, "lineno", 0) <= anchor_end:
            continue
        chain = _dotted(node)
        if chain and (chain == target or chain.startswith(target + ".")):
            return "target_consumed_after_anchor"
    return ""


def _check_conditional_import_target(root, entry, proof):
    module_path = Path(root) / str(proof.get("module", ""))
    attribute = str(proof.get("attribute", ""))
    if not module_path.is_file() or not attribute:
        return "probe_reference_invalid"
    try:
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return "target_module_unparseable"
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches_import_error = False
        for handler in node.handlers:
            if handler.type is None:
                continue
            handler_names = {_ident(n) for n in ast.walk(handler.type)}
            if "ImportError" in handler_names:
                catches_import_error = True
        if not catches_import_error:
            continue
        for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if isinstance(inner, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == attribute for t in inner.targets
            ):
                return ""
            if isinstance(inner, (ast.Import, ast.ImportFrom)) and any(
                (alias.asname or alias.name).split(".")[0] == attribute
                for alias in inner.names
            ):
                return ""
    return "attribute_not_conditionally_bound"


def _delete_key_path(document, key_path):
    cursor = document
    for key in key_path[:-1]:
        cursor = cursor[key] if not isinstance(cursor, list) else cursor[int(key)]
    final = key_path[-1]
    if isinstance(cursor, list):
        del cursor[int(final)]
    else:
        del cursor[final]


def _check_required_key_prevalidated(root, entry, proof):
    document_rel = str(proof.get("document", ""))
    key_path = list(proof.get("key_path", []))
    source = Path(root) / document_rel
    if not source.is_file() or not key_path:
        return "probe_reference_invalid"
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
        _delete_key_path(document, key_path)
    except (ValueError, KeyError, IndexError, TypeError):
        return "probe_key_path_invalid"
    bindings = configload.load_bindings(root)
    assignment, _uncovered, _ambiguous = configload.assign(root, bindings)
    binding_id = assignment.get(document_rel)
    if binding_id is None:
        return "document_not_bound"
    binding = next(
        b for b in bindings["bindings"] if b["binding_id"] == binding_id
    )
    staging = Path(tempfile.mkdtemp(prefix="b0f-keyprobe-"))
    try:
        target = staging / document_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document), encoding="utf-8")
        if binding["kind"] == configload.KIND_STRUCTURAL:
            problem = configload._apply_structural(staging, binding, document_rel)
        else:
            problem = configload._apply_callable(staging, binding, document_rel)
    finally:
        shutil.rmtree(staging)
        if staging.exists():
            raise CategoryError("probe_staging_not_removed", str(staging))
    if problem == "":
        # The reader accepted the document without the key: the claimed
        # guarantee does not exist and the exclusion is unsubstantiated.
        return "reader_accepts_absent_key"
    return ""


def _resolve_unit(root, site):
    target = Path(root) / str(site.get("file", ""))
    if not target.is_file():
        return None
    try:
        tree = ast.parse(target.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for unit in astcorpus.collect_units(tree):
        if unit.qualname == str(site.get("unit", "")):
            return unit
    return None


def _name_uses(unit, names):
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Name) and node.id in names:
            yield node


def _check_emptiness_fails_closed(root, entry, proof):
    mechanism = str(proof.get("mechanism", ""))
    names = set(proof.get("names", []))
    site = proof.get("site") or {"file": entry["file"], "unit": entry["unit"]}
    unit = _resolve_unit(root, site)
    if unit is None:
        return "proof_site_unresolved"
    if not names:
        return "probe_reference_invalid"

    if mechanism == "guard":
        for node in ast.walk(unit.node):
            if not isinstance(node, ast.If):
                continue
            negated_names = {
                name.id
                for negation in ast.walk(node.test)
                if isinstance(negation, ast.UnaryOp)
                and isinstance(negation.op, ast.Not)
                for name in ast.walk(negation.operand)
                if isinstance(name, ast.Name)
            }
            if negated_names & names:
                body = list(ast.walk(ast.Module(body=node.body, type_ignores=[])))
                if _writes_sink(body, _failure_sink_names(unit) | {"problems", "failures"}) or any(
                    isinstance(n, (ast.Raise, ast.Return)) for n in body
                ):
                    return ""
        return "guard_not_found"
    if mechanism in ("membership_pin", "equality_pin", "length_pin"):
        for node in ast.walk(unit.node):
            if not isinstance(node, ast.Compare):
                continue
            involved = {
                n.id for n in ast.walk(node) if isinstance(n, ast.Name)
            } & names
            if not involved:
                continue
            operators = node.ops
            if mechanism == "membership_pin" and any(
                isinstance(op, (ast.In, ast.NotIn)) for op in operators
            ):
                return ""
            if mechanism == "equality_pin" and any(
                isinstance(op, (ast.Eq, ast.NotEq)) for op in operators
            ):
                comparators = [node.left, *node.comparators]
                for comparator in comparators:
                    if _ident(comparator) in names:
                        continue
                    if isinstance(
                        comparator, (ast.List, ast.Set, ast.Dict, ast.Tuple)
                    ) and not (
                        getattr(comparator, "elts", None)
                        or getattr(comparator, "keys", None)
                    ):
                        # Equality against an empty literal pins nothing.
                        continue
                    if isinstance(
                        comparator,
                        (ast.List, ast.Set, ast.Dict, ast.Tuple, ast.Constant,
                         ast.Call, ast.Name, ast.Attribute),
                    ):
                        return ""
            if mechanism == "length_pin":
                calls = {
                    _call_name(n) for n in ast.walk(node) if isinstance(n, ast.Call)
                }
                if "len" in calls:
                    return ""
        return "pin_not_found"
    if mechanism == "fallthrough_nonsuccess":
        last = unit.node.body[-1]
        returns = [n for n in ast.walk(unit.node) if isinstance(n, ast.Return)]
        for node in returns:
            value = node.value
            if value is None:
                return ""
            if isinstance(value, ast.Constant) and value.value in (False, None, ""):
                return ""
            if isinstance(value, ast.Tuple) and any(
                isinstance(e, ast.Constant) and e.value in (False, None, "")
                for e in value.elts
            ):
                return ""
        if isinstance(last, ast.Raise):
            return ""
        return "fallthrough_not_nonsuccess"
    if mechanism == "reverse_walk":
        for node in ast.walk(unit.node):
            if isinstance(node, (ast.For, ast.AsyncFor)):
                body = list(ast.walk(ast.Module(body=node.body, type_ignores=[])))
                compares = [
                    n
                    for n in body
                    if isinstance(n, ast.Compare)
                    and any(isinstance(op, (ast.In, ast.NotIn)) for op in n.ops)
                    and ({m.id for m in ast.walk(n) if isinstance(m, ast.Name)} & names)
                ]
                if compares and _writes_sink(
                    body, _failure_sink_names(unit) | {"problems", "failures"}
                ):
                    return ""
        return "reverse_walk_not_found"
    if mechanism == "empty_yields_failure":
        for node in ast.walk(unit.node):
            if _is_assertion(node) and (
                {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} & names
            ):
                return ""
            if isinstance(node, (ast.Yield, ast.Return, ast.Call)) and (
                {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} & names
            ):
                continue
        for node in ast.walk(unit.node):
            if isinstance(node, ast.Compare) and any(
                isinstance(op, (ast.In, ast.NotIn)) for op in node.ops
            ) and ({n.id for n in ast.walk(node) if isinstance(n, ast.Name)} & names):
                return ""
        return "failure_path_not_found"
    if mechanism == "visible_skip":
        for node in ast.walk(unit.node):
            if isinstance(node, ast.Call) and _call_name(node) in ("skip", "skipif"):
                return ""
        for node in ast.walk(unit.node):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and node.value.value is False:
                return ""
        return "skip_not_found"
    return "mechanism_unknown"


_EXCUSAL_CALLS = ("sub", "union", "update", "difference", "get", "escape")
_FOREIGN_MUTATORS = (
    "remove",
    "discard",
    "pop",
    "clear",
    "append",
    "extend",
    "add",
    "update",
)


def _check_excusal_only_flow(root, entry, proof):
    names = set(proof.get("names", []))
    consumers = list(proof.get("consumers", []))
    if not names or not consumers:
        return "probe_reference_invalid"
    for site in consumers:
        unit = _resolve_unit(root, site)
        if unit is None:
            return "proof_site_unresolved"
        for use in _name_uses(unit, names):
            if isinstance(use.ctx, ast.Store):
                continue
            allowed = False
            for node in ast.walk(unit.node):
                if isinstance(node, ast.Compare) and any(
                    isinstance(op, (ast.In, ast.NotIn)) for op in node.ops
                ):
                    if any(use is n for n in ast.walk(node)):
                        allowed = True
                if isinstance(node, ast.Call) and _call_name(node) in _EXCUSAL_CALLS:
                    if any(use is n for n in ast.walk(node)):
                        allowed = True
                if isinstance(node, ast.Assign) and any(
                    use is n for n in ast.walk(node.value)
                ):
                    # Building a derived container from the excusal set.
                    allowed = True
                if isinstance(node, (ast.For, ast.comprehension)):
                    if any(use is n for n in ast.walk(node.iter)):
                        # Walking the excusal set is excusal only while the
                        # walk does not mutate a judgment sink: an iteration
                        # that removes findings from the emitted failure
                        # collection is a judgment effect, not a
                        # suppression. Labels and derived containers stay
                        # legitimate.
                        # Failure sinks only — a returned diagnostics label
                        # list is not a judgment sink for this rule.
                        sinks = {"failures", "problems"}
                        for inner in ast.walk(unit.node):
                            if isinstance(inner, ast.Call) and _call_name(
                                inner
                            ) in ("emit", "_emit"):
                                for argument in inner.args[:2]:
                                    for name_node in ast.walk(argument):
                                        if isinstance(name_node, ast.Name):
                                            sinks.add(name_node.id)
                        body = node.body if isinstance(node, ast.For) else []
                        sink_mutation = any(
                            isinstance(inner, ast.Call)
                            and isinstance(inner.func, ast.Attribute)
                            and inner.func.attr in _FOREIGN_MUTATORS
                            and _base_name(inner.func.value) in sinks
                            and _base_name(inner.func.value) not in names
                            for statement in body
                            for inner in ast.walk(statement)
                        )
                        if not sink_mutation:
                            allowed = True
            if not allowed:
                return "non_excusal_use_found"
    return ""


def _check_diagnostics_only_flow(root, entry, proof):
    mechanism = str(proof.get("mechanism", "emit_diagnostics_arg"))
    names = set(proof.get("names", []))
    site = proof.get("site") or {"file": entry["file"], "unit": entry["unit"]}
    unit = _resolve_unit(root, site)
    if unit is None:
        return "proof_site_unresolved"
    if not names:
        return "probe_reference_invalid"
    if mechanism == "discarded_return":
        consumer = proof.get("consumer")
        if not consumer:
            return "probe_reference_invalid"
        consumer_unit = _resolve_unit(root, consumer)
        if consumer_unit is None:
            return "proof_site_unresolved"
        for node in ast.walk(consumer_unit.node):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                called = _call_name(node.value)
                if called in names:
                    return ""
        return "discarding_call_not_found"
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Call) and _call_name(node) in ("emit", "_emit"):
            for argument in node.args[:2]:
                if {
                    n.id for n in ast.walk(argument) if isinstance(n, ast.Name)
                } & names:
                    return "diagnostics_name_in_failure_position"
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Return) and node.value is not None:
            returned = {
                n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)
            }
            if returned & names and mechanism == "emit_diagnostics_arg":
                return "diagnostics_name_returned"
    return ""


def _check_runtime_emptyset_guarded(root, entry, proof):
    consumer = proof.get("consumer")
    if not consumer:
        return "probe_reference_invalid"
    unit = _resolve_unit(root, consumer)
    if unit is None:
        return "proof_site_unresolved"
    enclosing_function = entry["unit"].rsplit(".", 1)[-1]
    calls = {
        _call_name(node) for node in ast.walk(unit.node) if isinstance(node, ast.Call)
    }
    if enclosing_function not in calls:
        return "consumer_does_not_call_function"
    if not calls & {"verdict", "require_non_empty"}:
        return "consumer_lacks_emptyset_rule"
    return ""


_VALIDATORS = {
    "r9_injection_load_bearing": _check_injection_load_bearing,
    "r9_post_judgment_position": _check_post_judgment_position,
    "r9_after_state_observed": _check_after_state_observed,
    "r9_reraising_error_path": _check_reraising_error_path,
    "r9_both_outcomes_judged": _check_both_outcomes_judged,
    "r9_property_established_at_creation": _check_property_established_at_creation,
    "r9_loud_guarded_removal": _check_loud_guarded_removal,
    "r9_target_unconsumed_after": _check_target_unconsumed_after,
    "r9_conditional_import_target": _check_conditional_import_target,
    "r10_required_key_prevalidated": _check_required_key_prevalidated,
    "r10_emptiness_fails_closed": _check_emptiness_fails_closed,
    "r10_excusal_only_flow": _check_excusal_only_flow,
    "r10_diagnostics_only_flow": _check_diagnostics_only_flow,
    "r10_runtime_emptyset_guarded": _check_runtime_emptyset_guarded,
}


def validate_entry(root, entry):
    """Re-check one exclusion entry's category. ``""`` means it holds."""
    category = str(entry.get("category", ""))
    if category not in CATEGORIES:
        return "category_unknown"
    if CATEGORIES[category]["rule"] != entry["rule"]:
        return "category_rule_mismatch"
    proof = entry.get("category_proof")
    if not isinstance(proof, dict):
        return "category_proof_missing"
    try:
        return _VALIDATORS[category](root, entry, proof)
    except CategoryError as error:
        return error.code
