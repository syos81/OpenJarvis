"""Shared syntax tree scaffold for the R9 and R10 sweeps (block B0e).

Two distinct rules run over one derived corpus (:mod:`tools.gates.astcorpus`):

Rule R9 — an induced effect must be evidenced. The sweep looks for places
where a test or validator deliberately changes or withdraws state before its
actual expectation *in a form whose intended after-state is not guaranteed by
the operation itself*. A ``str.replace`` fed into a file write is the model
case: it silently does nothing when the needle is gone, which is exactly the
defect that created the rule.

Rule R10 — absence must not silently become emptiness when success can grow
out of it. The sweep looks for expressions that normalise a possibly missing
input into an empty container and flow, inside the same unit, into an
iteration or quantification that can carry a positive judgement.

Both rules only *find candidates*. No candidate is a finding by itself; the
normative decision is the explicit disposition in the committed register
(``config/governance/ast-dispositions.json``), exactly one per candidate.
The validator proves ``detected candidates == disposed candidates`` and fails
on both gaps: a candidate without a disposition and a disposition without a
candidate. A disposition is bound to its candidate through a position
independent fingerprint of the anchoring syntax tree node; when the node
changes, the binding breaks loudly and the candidate must be re-decided.

Class level boundaries are part of the rule declarations in the register,
not silent scanner behaviour: operations whose after-state is guaranteed by
their own semantics (``monkeypatch.delenv(..., raising=False)`` leaves the
variable absent, ``unlink(missing_ok=True)`` leaves the file absent) are
excluded as a class with a stated reason, and the exclusion is fixture
tested. The same holds for the R10 suppressors (a unit that judges
``len(...)`` of the normalised value judges its emptiness).
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from . import astcorpus, effectevidence

REGISTER = "config/governance/ast-dispositions.json"

RULE_R9 = "R9"
RULE_R10 = "R10"
RULES = (RULE_R9, RULE_R10)

DISPOSITIONS = {
    RULE_R9: ("mark_and_fix", "exclude_with_reason"),
    RULE_R10: ("repair", "exclude_with_reason"),
}

R9_CLASSES = (
    "silent_substitution",
    "tolerant_removal_unverified",
    "masking_patch",
    "unobserved_error_injection",
    "permission_withdrawal",
    "guarded_perturbation",
    "swallowed_perturbation",
)
R10_CLASSES = (
    "vacuous_loop_assertion",
    "empty_default_iteration",
    "vacuous_quantifier",
    "default_factory_judgment",
)

#: Reasons this short cannot carry a concrete technical ground.
MINIMUM_REASON_LENGTH = 40

TOP_FIELDS = (
    "schema_version",
    "kind",
    "block_id",
    "corpus_note",
    "rules",
    "dispositions",
)
RULE_FIELDS = ("statement", "candidate_classes", "class_boundaries")
ENTRY_FIELDS = (
    "candidate_id",
    "rule",
    "file",
    "unit",
    "candidate_class",
    "ast_class",
    "lineno",
    "fingerprint",
    "occurrence",
    "disposition",
    "reason",
    "repair_note",
    "resolved_by_removal",
    "source_digest",
)

_PERTURB_CALLS = frozenset(
    {
        "chmod",
        "chown",
        "unlink",
        "remove",
        "rmtree",
        "rename",
        "renames",
        "truncate",
        "rmdir",
        "removedirs",
    }
)
_WRITE_CALLS = frozenset({"write_text", "write_bytes"})
_EXIST_CHECKS = frozenset({"exists", "is_file", "is_dir"})
_MOCK_OBSERVATIONS = frozenset(
    {"call_count", "called", "call_args", "call_args_list", "mock_calls"}
)
_QUANTIFIERS = frozenset({"all", "any"})
_RAISE_EXPECTATIONS = frozenset({"raises", "assertRaises", "assertRaisesRegex"})


class RegisterError(ValueError):
    """Raised with a machine readable code for an unusable register."""

    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class Candidate:
    __slots__ = (
        "rule",
        "candidate_class",
        "file",
        "unit",
        "ast_class",
        "lineno",
        "fingerprint",
        "occurrence",
        "candidate_id",
    )

    def __init__(self, rule, candidate_class, file, unit, node, occurrence):
        self.rule = rule
        self.candidate_class = candidate_class
        self.file = file
        self.unit = unit
        self.ast_class = type(node).__name__
        self.lineno = getattr(node, "lineno", 0)
        self.fingerprint = _fingerprint(node)
        self.occurrence = occurrence
        digest = hashlib.sha256(
            "|".join(
                [rule, candidate_class, file, unit, self.fingerprint, str(occurrence)]
            ).encode("utf-8")
        ).hexdigest()
        self.candidate_id = f"{rule.lower()}-{digest[:16]}"

    def as_dict(self):
        return {
            "candidate_id": self.candidate_id,
            "rule": self.rule,
            "candidate_class": self.candidate_class,
            "file": self.file,
            "unit": self.unit,
            "ast_class": self.ast_class,
            "lineno": self.lineno,
            "fingerprint": self.fingerprint,
            "occurrence": self.occurrence,
        }


def _fingerprint(node):
    """Position independent digest of the anchoring node."""
    dump = ast.dump(node, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()[:24]


def _call_name(node):
    return getattr(node.func, "id", "") or getattr(node.func, "attr", "")


def _is_true(node):
    return isinstance(node, ast.Constant) and node.value is True


def _is_false(node):
    return isinstance(node, ast.Constant) and node.value is False


def _keyword(call, name):
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_empty_container(node):
    if isinstance(node, ast.Dict):
        return not node.keys
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
        return len(node.value) == 0
    if isinstance(node, ast.Call) and not node.args and not node.keywords:
        return _call_name(node) in ("dict", "list", "set", "tuple", "frozenset")
    return False


def _looks_exceptional(node):
    target = node.func if isinstance(node, ast.Call) else node
    name = getattr(target, "id", "") or getattr(target, "attr", "")
    return name.endswith(("Error", "Exception", "Interrupt", "Timeout", "Exit"))


def _statements(nodes):
    module = ast.Module(body=list(nodes), type_ignores=[])
    return ast.walk(module)


class _Sweep:
    """One unit, both rules. Collects candidates with stable occurrences."""

    def __init__(self, file, unit, in_tools):
        self.file = file
        self.unit = unit
        self.in_tools = in_tools
        self.candidates = []
        self._seen = {}

    def add(self, rule, candidate_class, node):
        key = (rule, candidate_class, _fingerprint(node))
        occurrence = self._seen.get(key, 0)
        self._seen[key] = occurrence + 1
        self.candidates.append(
            Candidate(rule, candidate_class, self.file, self.unit.qualname, node, occurrence)
        )

    # ---------------------------------------------------------------- R9

    def sweep_r9(self):
        function = self.unit.node
        calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
        names = {_call_name(call) for call in calls}
        has_raise_expectation = bool(names & _RAISE_EXPECTATIONS)
        observes_mock = any(
            name.startswith(("assert_called", "assert_any_call", "assert_has_calls"))
            or name == "assert_not_called"
            for name in names
        ) or any(
            isinstance(node, ast.Attribute) and node.attr in _MOCK_OBSERVATIONS
            for node in ast.walk(function)
        )

        for call in calls:
            name = _call_name(call)
            if name in _WRITE_CALLS:
                for argument in call.args:
                    for inner in ast.walk(argument):
                        if isinstance(inner, ast.Call) and _call_name(inner) in (
                            "replace",
                            "sub",
                        ):
                            self.add(RULE_R9, "silent_substitution", call)
            if name == "rmtree" and _is_true(_keyword(call, "ignore_errors")):
                self.add(RULE_R9, "tolerant_removal_unverified", call)
            if name in ("setattr", "setitem") and _is_false(_keyword(call, "raising")):
                self.add(RULE_R9, "masking_patch", call)
            if name in ("patch", "object") and _is_true(_keyword(call, "create")):
                self.add(RULE_R9, "masking_patch", call)
            if name == "chmod" and call.args:
                mode = call.args[-1]
                if (
                    self.unit.is_test_named
                    and isinstance(mode, ast.Constant)
                    and isinstance(mode.value, int)
                    and mode.value < 0o400
                ):
                    self.add(RULE_R9, "permission_withdrawal", call)
            if (
                self.unit.is_test_named
                and not has_raise_expectation
                and not observes_mock
            ):
                injected = _keyword(call, "side_effect")
                if injected is not None and _looks_exceptional(injected):
                    self.add(RULE_R9, "unobserved_error_injection", call)

        for node in ast.walk(function):
            if (
                isinstance(node, ast.Assign)
                and self.unit.is_test_named
                and not has_raise_expectation
                and not observes_mock
                and _looks_exceptional(node.value)
            ):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "side_effect":
                        self.add(RULE_R9, "unobserved_error_injection", node)
            if isinstance(node, ast.Try):
                swallowing = any(
                    all(isinstance(inner, (ast.Pass, ast.Continue)) for inner in handler.body)
                    for handler in node.handlers
                )
                if swallowing:
                    for inner in _statements(node.body):
                        if isinstance(inner, ast.Call) and _call_name(inner) in (
                            _PERTURB_CALLS | _WRITE_CALLS
                        ):
                            self.add(RULE_R9, "swallowed_perturbation", inner)
            if isinstance(node, ast.If) and not node.orelse:
                guards = {
                    _call_name(inner)
                    for inner in ast.walk(node.test)
                    if isinstance(inner, ast.Call)
                }
                if guards & _EXIST_CHECKS:
                    for inner in _statements(node.body):
                        if isinstance(inner, ast.Call) and _call_name(inner) in _PERTURB_CALLS:
                            self.add(RULE_R9, "guarded_perturbation", inner)

    # --------------------------------------------------------------- R10

    def sweep_r10(self):
        function = self.unit.node
        normalisations = []
        factory_names = set()
        for node in ast.walk(function):
            if (
                isinstance(node, ast.BoolOp)
                and isinstance(node.op, ast.Or)
                and _is_empty_container(node.values[-1])
            ):
                normalisations.append(node)
            elif (
                isinstance(node, ast.Call)
                and _call_name(node) == "get"
                and len(node.args) == 2
                and _is_empty_container(node.args[1])
            ):
                normalisations.append(node)
            elif (
                isinstance(node, ast.Call)
                and _call_name(node) == "getattr"
                and len(node.args) == 3
                and _is_empty_container(node.args[2])
            ):
                normalisations.append(node)
            elif isinstance(node, ast.Assign) and (
                isinstance(node.value, ast.Call)
                and _call_name(node.value) == "defaultdict"
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        factory_names.add(target.id)
        if not normalisations and not factory_names:
            return

        normalised_ids = {id(node) for node in normalisations}
        tainted = set(factory_names)
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and any(
                id(inner) in normalised_ids for inner in ast.walk(node.value)
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        tainted.add(target.id)

        def consumes(node):
            if isinstance(node, ast.Name) and node.id in tainted:
                return True
            return id(node) in normalised_ids

        length_judged = set()
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and _call_name(node) == "len"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in tainted
            ):
                length_judged.add(node.args[0].id)

        def suppressed(expression):
            names = {
                inner.id
                for inner in ast.walk(expression)
                if isinstance(inner, ast.Name) and inner.id in tainted
            }
            return bool(names) and names <= length_judged

        for node in ast.walk(function):
            if isinstance(node, (ast.For, ast.AsyncFor)) and any(
                consumes(inner) for inner in ast.walk(node.iter)
            ):
                if suppressed(node.iter):
                    continue
                factory_only = not any(
                    id(inner) in normalised_ids for inner in ast.walk(node.iter)
                ) and not (
                    {
                        inner.id
                        for inner in ast.walk(node.iter)
                        if isinstance(inner, ast.Name)
                    }
                    & (tainted - factory_names)
                )
                body_asserts = any(
                    isinstance(inner, ast.Assert)
                    or (
                        isinstance(inner, ast.Call)
                        and _call_name(inner).startswith("assert")
                    )
                    for inner in _statements(node.body)
                )
                if factory_only:
                    if self.in_tools:
                        self.add(RULE_R10, "default_factory_judgment", node)
                elif body_asserts and not self.in_tools:
                    self.add(RULE_R10, "vacuous_loop_assertion", node)
                elif self.in_tools:
                    self.add(RULE_R10, "empty_default_iteration", node)
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                for generator in node.generators:
                    if any(consumes(inner) for inner in ast.walk(generator.iter)):
                        if suppressed(generator.iter) or not self.in_tools:
                            continue
                        self.add(RULE_R10, "empty_default_iteration", node)
            if isinstance(node, ast.Call) and _call_name(node) in _QUANTIFIERS:
                if any(
                    consumes(inner)
                    for argument in node.args
                    for inner in ast.walk(argument)
                ) and not any(suppressed(argument) for argument in node.args):
                    self.add(RULE_R10, "vacuous_quantifier", node)


def scan_corpus(corpus):
    """Both sweeps over every unit of the derived corpus."""
    candidates = []
    for key in sorted(corpus.files):
        in_tools = key.split("/", 1)[0] in astcorpus.CLOSURE_ROOTS
        for unit in corpus.units[key]:
            sweep = _Sweep(key, unit, in_tools)
            sweep.sweep_r9()
            sweep.sweep_r10()
            candidates.extend(sweep.candidates)
    return candidates


def scan_source(relative_path, source, *, in_tools=None):
    """Both sweeps over one source text; for fixtures and tests."""
    if in_tools is None:
        in_tools = relative_path.split("/", 1)[0] in astcorpus.CLOSURE_ROOTS
    tree = ast.parse(source)
    candidates = []
    for unit in astcorpus.collect_units(tree):
        sweep = _Sweep(relative_path, unit, in_tools)
        sweep.sweep_r9()
        sweep.sweep_r10()
        candidates.extend(sweep.candidates)
    return candidates


# ------------------------------------------------------------------ register


def load_register(root, path=REGISTER):
    """Load and structurally validate the disposition register."""
    target = Path(root) / path
    if not target.is_file():
        raise RegisterError("register_missing", str(path))
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RegisterError("register_not_json", str(exc)[:80]) from exc
    if not isinstance(document, dict) or sorted(document) != sorted(TOP_FIELDS):
        raise RegisterError("register_field_set")
    if document["kind"] != "ast_disposition_register":
        raise RegisterError("register_kind_unexpected", str(document["kind"]))
    rules = document["rules"]
    if not isinstance(rules, dict) or sorted(rules) != sorted(RULES):
        raise RegisterError("register_rules_incomplete")
    declared_classes = {}
    for rule in RULES:
        section = rules[rule]
        if not isinstance(section, dict) or sorted(section) != sorted(RULE_FIELDS):
            raise RegisterError("rule_field_set", rule)
        if not str(section["statement"]).strip():
            raise RegisterError("rule_statement_empty", rule)
        classes = section["candidate_classes"]
        expected = R9_CLASSES if rule == RULE_R9 else R10_CLASSES
        if not isinstance(classes, dict) or sorted(classes) != sorted(expected):
            raise RegisterError("rule_classes_mismatch", rule)
        for name, description in classes.items():
            if not str(description).strip():
                raise RegisterError("rule_class_undescribed", name)
        boundaries = section["class_boundaries"]
        if not isinstance(boundaries, dict) or not boundaries:
            # The stated boundaries are part of the rule; an empty set would
            # silently widen the scanner's silence into a claim.
            raise RegisterError("rule_boundaries_missing", rule)
        for name, reason in boundaries.items():
            if len(str(reason).strip()) < MINIMUM_REASON_LENGTH:
                raise RegisterError("rule_boundary_undescribed", name)
        declared_classes[rule] = set(classes)
    entries = document["dispositions"]
    if not isinstance(entries, list):
        raise RegisterError("dispositions_not_a_list")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or sorted(entry) != sorted(ENTRY_FIELDS):
            raise RegisterError("entry_field_set", str(entry.get("candidate_id", "")))
        identifier = str(entry["candidate_id"])
        if identifier in seen:
            raise RegisterError("entry_duplicated", identifier)
        seen.add(identifier)
        rule = entry["rule"]
        if rule not in RULES:
            raise RegisterError("entry_rule_unknown", identifier)
        if entry["candidate_class"] not in declared_classes[rule]:
            raise RegisterError("entry_class_unknown", identifier)
        if entry["disposition"] not in DISPOSITIONS[rule]:
            raise RegisterError("entry_disposition_unknown", identifier)
        reason = str(entry["reason"]).strip()
        if len(reason) < MINIMUM_REASON_LENGTH:
            # "false positive" and "harmless" are shorter than any concrete
            # technical ground; the length floor rejects them mechanically.
            raise RegisterError("entry_reason_insufficient", identifier)
        if entry["disposition"] in ("mark_and_fix", "repair"):
            if not str(entry["repair_note"]).strip():
                raise RegisterError("entry_repair_note_empty", identifier)
        elif str(entry["repair_note"]):
            raise RegisterError("entry_repair_note_unexpected", identifier)
        if entry["resolved_by_removal"] not in (True, False):
            raise RegisterError("entry_resolution_not_boolean", identifier)
        if entry["resolved_by_removal"] and entry["disposition"] == "exclude_with_reason":
            # An excluded candidate is expected to stay; only a repair may
            # legitimately make its anchor disappear.
            raise RegisterError("entry_resolution_contradicts_disposition", identifier)
        if not isinstance(entry["lineno"], int) or not isinstance(entry["occurrence"], int):
            raise RegisterError("entry_position_invalid", identifier)
        for field in ("file", "unit", "ast_class", "fingerprint", "source_digest"):
            if not str(entry[field]).strip():
                raise RegisterError("entry_field_empty", f"{identifier}:{field}")
    return document


def validate(root, *, corpus=None, register_path=REGISTER):
    """Prove ``detected candidates == disposed candidates``.

    Returns ``(failures, diagnostics)`` where failures is a list of
    ``(identifier, code)`` pairs. The corpus is derived when not supplied.
    """
    root = Path(root)
    try:
        register = load_register(root, register_path)
    except RegisterError as error:
        return [(register_path, error.code)], []
    if corpus is None:
        try:
            corpus = astcorpus.derive(root)
        except astcorpus.CorpusError as error:
            # A missing or empty corpus is a non-evidence state, never a
            # clean sweep (rule R10 applied to the sweep itself).
            return [("corpus", error.code)], []

    candidates = scan_corpus(corpus)
    detected = {candidate.candidate_id: candidate for candidate in candidates}
    disposed = {entry["candidate_id"]: entry for entry in register["dispositions"]}

    failures = []
    for identifier in sorted(set(detected) - set(disposed)):
        candidate = detected[identifier]
        failures.append(
            (f"{candidate.file}::{candidate.unit}::{identifier}", "candidate_undisposed")
        )
    for identifier in sorted(set(disposed) - set(detected)):
        entry = disposed[identifier]
        if entry["resolved_by_removal"]:
            continue
        failures.append(
            (f"{entry['file']}::{entry['unit']}::{identifier}", "disposition_orphaned")
        )
    for identifier in sorted(set(disposed) & set(detected)):
        entry = disposed[identifier]
        if entry["resolved_by_removal"]:
            failures.append(
                (
                    f"{entry['file']}::{entry['unit']}::{identifier}",
                    "resolved_candidate_reappeared",
                )
            )

    # Every R9 mark_and_fix must be declared under rule R9's convention, so
    # the first-assertion enforcement covers the repaired test permanently.
    try:
        declaration = effectevidence.load(root)
        declared = {
            (str(entry["file"]), str(entry["function"]))
            for entry in declaration["examined"]
        }
    except effectevidence.EffectEvidenceError as error:
        declaration = None
        declared = set()
        failures.append((effectevidence.DECLARATION, error.code))
    if declaration is not None:
        for entry in register["dispositions"]:
            if entry["rule"] == RULE_R9 and entry["disposition"] == "mark_and_fix":
                if entry["file"].split("/", 1)[0] in astcorpus.CLOSURE_ROOTS:
                    # Validator code carries no assertions; its repair is the
                    # mechanical observation in the code itself, which the
                    # sweep re-checks on every run.
                    continue
                function = entry["unit"].rsplit(".", 1)[-1]
                if (entry["file"], function) not in declared:
                    failures.append(
                        (
                            f"{entry['file']}::{entry['unit']}",
                            "mark_without_declaration",
                        )
                    )

    counts = {rule: 0 for rule in RULES}
    for candidate in candidates:
        counts[candidate.rule] += 1
    by_disposition = {}
    for entry in register["dispositions"]:
        key = f"{entry['rule'].lower()}_{entry['disposition']}"
        by_disposition[key] = by_disposition.get(key, 0) + 1

    diagnostics = [
        f"corpus_files={corpus.counts['files']}",
        f"corpus_units={corpus.counts['units']}",
        f"corpus_test_units={corpus.counts['test_units']}",
        f"corpus_validator_units={corpus.counts['validator_units']}",
        f"corpus_ast_nodes={corpus.counts['ast_nodes']}",
        f"r9_candidates={counts[RULE_R9]}",
        f"r10_candidates={counts[RULE_R10]}",
        f"dispositions={len(register['dispositions'])}",
    ]
    diagnostics.extend(
        f"{key}={value}" for key, value in sorted(by_disposition.items())
    )
    return sorted(failures), sorted(diagnostics)
