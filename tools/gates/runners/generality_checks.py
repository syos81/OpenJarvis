#!/usr/bin/env python3
"""Generality runner for B0a-2 §10.

Modes:

``organization-scan``   token exact, unicode normalised organisation name scan
``provider-gate``       provider terms only inside released adapter paths
``literal-comparisons`` AST check against hard coded literal comparisons
``configuration-test``  activation state of the positive configuration test

The organisation scan is baseline comparable: a finding that already exists at
the baseline commit with an identical structural cause is excused by the
baseline engine, a new or additional finding is not.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import generality  # noqa: E402
from tools.gates import gitutil  # noqa: E402
from tools.gates.runners import _report  # noqa: E402

SCOPE = Path("config/governance/generality-scope.json")
CONTRACT = Path("config/governance/generality-fixtures/contract.json")


def _fail(identifier, code, category):
    return _report.failure(identifier, category=category, code=code)


def engine_root(root):
    """Where the *steering* configuration lives.

    The scanned tree is the working directory — for a baseline run that is the
    baseline worktree. The rules themselves always come from the current
    engine, so an old tree can never weaken or redefine them.
    """
    declared = os.environ.get("GATE_ENGINE_ROOT")
    return Path(declared) if declared else Path(root)


def load_scope(root):
    return json.loads((engine_root(root) / SCOPE).read_text(encoding="utf-8"))


def scoped_files(root, scope):
    tracked = set(gitutil.tracked_files(cwd=root))
    code, out, _ = gitutil.run_git(
        ["ls-files", "--others", "--exclude-standard"], cwd=root
    )
    if code == 0:
        tracked.update(line.strip() for line in out.splitlines() if line.strip())
    return generality.candidate_files(root, tracked, scope["scan_scope"])


def mode_organization_scan(root):
    scope = load_scope(root)
    files = scoped_files(root, scope)
    declared = scope.get("declared_identifiers", [])
    findings = generality.scan_terms(
        root, files, scope["organization_terms"], declared=declared
    )
    exceptions = {entry["path"] for entry in scope.get("exceptions", [])}
    failures = [
        _fail(
            f"{finding['path']}#{finding['term_id']}#{finding['location']}",
            f"organization_name_in_product_surface_x{finding['count']}",
            "organization_scan",
        )
        for finding in findings
        if finding["path"] not in exceptions
    ]
    # A declaration that no longer matches reality is itself a finding.
    for identifier_id, path, code in generality.check_declared_identifiers(
        root, declared
    ):
        failures.append(_fail(f"{path}#{identifier_id}", code, "organization_scan"))
    diagnostics = [f"scanned_files={len(files)}"]
    for term_id in generality.pending_terms(scope["organization_terms"]):
        diagnostics.append(f"organization_term_pending_owner_input={term_id}")
    for entry in declared:
        if entry.get("owner") == "pending_owner_decision":
            diagnostics.append(
                f"declared_identifier_pending_owner_decision={entry['identifier_id']}"
            )
    return failures, diagnostics


def mode_provider_gate(root):
    scope = load_scope(root)
    files = scoped_files(root, scope)
    findings = generality.scan_terms(root, files, scope["provider_terms"])
    violations = generality.provider_violations(
        findings, scope["provider_allowed_paths"]
    )
    failures = [
        _fail(
            f"{finding['path']}#{finding['term_id']}",
            "provider_term_outside_released_path",
            "provider_gate",
        )
        for finding in violations
    ]
    diagnostics = [
        f"scanned_files={len(files)}",
        f"released_paths={len(scope['provider_allowed_paths'])}",
        f"provider_findings={len(findings)}",
    ]
    return failures, diagnostics


def mode_literal_comparisons(root):
    scope = load_scope(root)
    sensitive = [marker.lower() for marker in scope["sensitive_identifiers"]]
    provider_values = []
    for term in scope["provider_terms"]:
        provider_values.extend(term.get("variants") or [])
    failures = []
    # Rule R10: provider terms whose variants vanished would silently turn
    # the provider half of this check off with a green outcome.
    if scope["provider_terms"] and not provider_values:
        failures.append(
            _fail(
                "provider_terms",
                "provider_term_without_variants",
                "literal_comparison",
            )
        )
    inspected = 0
    for pattern in scope["core_paths"]:
        if not pattern.endswith(".py"):
            continue
        for target in sorted(Path(root).glob(pattern)):
            if not target.is_file():
                continue
            inspected += 1
            relative = target.relative_to(root)
            source = target.read_text(encoding="utf-8", errors="ignore")
            for finding in generality.find_literal_comparisons(
                source, sensitive, filename=str(relative),
                provider_values=provider_values,
            ):
                failures.append(
                    _fail(
                        f"{relative}#{finding['identifier']}",
                        "hard_coded_literal_comparison",
                        "literal_comparison",
                    )
                )
    return failures, [f"inspected_core_files={inspected}"]


def mode_configuration_test(root):
    scope = load_scope(root)
    contract_path = engine_root(root) / CONTRACT
    failures = []
    diagnostics = []
    if not contract_path.is_file():
        return (
            [_fail(str(CONTRACT), "configuration_contract_missing", "configuration")],
            diagnostics,
        )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    for fixture in contract["fixtures"]:
        if not (contract_path.parent / fixture).is_file():
            failures.append(
                _fail(fixture, "configuration_fixture_missing", "configuration")
            )

    try:
        state, paths = generality.activation_state(root, scope["process_activation"])
    except generality.ActivationError as error:
        failures.append(
            _fail("process_activation", error.code, "configuration")
        )
        return failures, diagnostics
    diagnostics.append(f"process_activation={state}")
    diagnostics.append(f"process_paths={len(paths)}")
    if state == "active":
        # A real process path exists: the positive product test is mandatory
        # and may no longer be reported as non-applicable.
        marker = engine_root(root) / "tests" / "tooling" / "gates" / "test_generality_product.py"
        if not marker.is_file():
            failures.append(
                _fail(
                    "positive_configuration_test",
                    "positive_test_required_but_absent",
                    "configuration",
                )
            )
        for path in paths[:10]:
            diagnostics.append(f"activating_path={path}")
    mechanism = engine_root(root) / "tests" / "tooling" / "gates" / "test_generality.py"
    if not mechanism.is_file():
        failures.append(
            _fail("mechanism_test", "mechanism_test_missing", "configuration")
        )
    return failures, diagnostics


MODES = {
    "organization-scan": mode_organization_scan,
    "provider-gate": mode_provider_gate,
    "literal-comparisons": mode_literal_comparisons,
    "configuration-test": mode_configuration_test,
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
