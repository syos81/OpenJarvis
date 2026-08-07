"""Rule R9 — an induced effect must be evidenced.

A test whose statement rests on a deliberate mutation, disturbance,
corruption or withdrawal must mechanically establish, *before* its actual
expectation, that the effect really occurred. If the effect fails to occur the
test must fail on that, not on its subject.

The rule exists because of a real defect. A test broke an installed package by
substituting the literal ``"1.0.0"`` and then asserted that the guard denied
the request. When ``config_version`` moved to ``1.1.0`` the substitution
became a no-op: the package stayed intact, the guard denied for an unrelated
and entirely correct reason, and the test kept passing while testing nothing.
Nothing in the suite could notice, because a passing test looks the same
either way.

The enforcement here is deliberately structural. For every declared function
the *first* assertion in its body must be the declared effect assertion. That
is read from the syntax tree, so an effect assertion that was moved below the
expectation, renamed or deleted fails here even while the test still passes.
Text matching would have the same weakness as the defect it is meant to catch.

Ordinary preparation is explicitly not in scope: the rule applies where the
induced effect is what the expectation is about.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

DECLARATION = "config/governance/effect-evidence.json"

VERDICTS = ("evidenced", "open_finding")

TOP_FIELDS = (
    "schema_version",
    "kind",
    "rule",
    "statement",
    "method",
    "scope",
    "examined",
    "open_findings",
)
SCOPE_FIELDS = ("block_id", "covers", "deferred", "not_claimed")
ENTRY_FIELDS = (
    "file",
    "function",
    "induced_effect",
    "effect_assertion",
    "verdict",
    "evidence",
    "reason",
)


class EffectEvidenceError(ValueError):
    """Raised with a machine readable code for an unusable declaration."""

    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def load(root, path=DECLARATION):
    """Load and validate the declaration itself."""
    target = Path(root) / path
    if not target.is_file():
        raise EffectEvidenceError("declaration_missing", str(path))
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise EffectEvidenceError("declaration_not_json", str(exc)[:80]) from exc
    if not isinstance(document, dict):
        raise EffectEvidenceError("declaration_not_an_object")
    if sorted(document) != sorted(TOP_FIELDS):
        raise EffectEvidenceError("declaration_field_set")
    if document["rule"] != "R9":
        raise EffectEvidenceError("declaration_rule_unexpected", str(document["rule"]))

    scope = document["scope"]
    if not isinstance(scope, dict) or sorted(scope) != sorted(SCOPE_FIELDS):
        raise EffectEvidenceError("scope_field_set")
    for field in SCOPE_FIELDS:
        if not str(scope[field]).strip():
            raise EffectEvidenceError("scope_field_empty", field)

    entries = document["examined"]
    if not isinstance(entries, list) or not entries:
        raise EffectEvidenceError("examined_empty")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or sorted(entry) != sorted(ENTRY_FIELDS):
            raise EffectEvidenceError("entry_field_set", str(entry.get("function", "")))
        key = (str(entry["file"]), str(entry["function"]))
        if key in seen:
            raise EffectEvidenceError("entry_duplicated", str(entry["function"]))
        seen.add(key)
        if entry["verdict"] not in VERDICTS:
            raise EffectEvidenceError("verdict_unknown", str(entry["function"]))
        for field in ("induced_effect", "effect_assertion", "evidence", "reason"):
            if not str(entry[field]).strip():
                raise EffectEvidenceError("entry_field_empty", f"{entry['function']}:{field}")
        if not str(entry["effect_assertion"]).startswith("assert"):
            # An effect assertion that is not an assertion cannot fail the
            # test, which is the whole mechanism.
            raise EffectEvidenceError(
                "effect_assertion_is_not_an_assertion", str(entry["function"])
            )
    if not isinstance(document["open_findings"], list):
        raise EffectEvidenceError("open_findings_not_a_list")
    return document


def _call_name(node):
    return getattr(node.func, "id", "") or getattr(node.func, "attr", "")


def first_assertion(function_node):
    """The name of the first assertion executed in ``function_node``.

    Walked in source order over the statements of the body, so an assertion
    inside the function is found and one in a nested helper is not.
    """
    for statement in function_node.body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name.startswith("assert"):
                    return name
            if isinstance(node, ast.Assert):
                return "assert"
    return ""


def find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def verify(root, entry):
    """Check one declared function. ``""`` means the rule holds for it."""
    target = Path(root) / str(entry["file"])
    if not target.is_file():
        return "declared_file_absent"
    try:
        tree = ast.parse(target.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return "declared_file_unparseable"
    function = find_function(tree, str(entry["function"]))
    if function is None:
        return "declared_function_absent"
    found = first_assertion(function)
    if not found:
        return "function_has_no_assertion"
    if found != str(entry["effect_assertion"]):
        # Either the effect assertion is gone, or something now asserts the
        # expectation before the effect is established. Both are the defect.
        return f"first_assertion_is_{found}_not_{entry['effect_assertion']}"
    return ""


def check(root, path=DECLARATION):
    """Full R9 check. Returns ``(failures, diagnostics)``."""
    try:
        document = load(root, path)
    except EffectEvidenceError as error:
        return [(path, error.code)], []

    failures = []
    diagnostics = []
    for entry in document["examined"]:
        identifier = f"{entry['file']}::{entry['function']}"
        if entry["verdict"] == "open_finding":
            # Declared as open, and therefore not silently counted as covered.
            diagnostics.append(f"{identifier}=open_finding")
            continue
        code = verify(root, entry)
        if code:
            failures.append((identifier, code))
        else:
            diagnostics.append(f"{identifier}=evidenced")
    diagnostics.append(f"examined={len(document['examined'])}")
    diagnostics.append(f"scope={document['scope']['block_id']}")
    # The corpus wide sweep deferred by B0d has run in block B0e; the
    # standing coverage is the disposition register and its validator, and
    # the report names that source so the division of labour stays visible.
    diagnostics.append("corpus_sweep=ast_disposition_register")
    return sorted(failures), sorted(diagnostics)
