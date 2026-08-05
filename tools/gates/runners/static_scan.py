#!/usr/bin/env python3
"""Static rules for the tooling sources.

Deterministic, dependency free checks:

* every Python file parses,
* no ``eval``/``exec``/``os.system``/``shell=True``,
* no absolute user specific paths,
* no import of product code from the tooling,
* every shell script parses (``bash -n``), sets ``-euo pipefail`` and avoids
  ``eval``.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import gitutil  # noqa: E402
from tools.gates.runners import _report  # noqa: E402

FORBIDDEN_CALLS = {"eval", "exec", "compile"}
FORBIDDEN_ATTRIBUTES = {"system", "popen"}
FORBIDDEN_SUBSTRINGS = ("/Users/", "/home/", "$HOME")  # gate-allow: absolute_user_path
PRODUCT_IMPORT_PREFIXES = ("openjarvis", "personaljarvis")

#: A line may opt out of the absolute-path rule only with this explicit,
#: greppable marker — used by the guards that must name those prefixes.
ALLOW_MARKER = "gate-allow: absolute_user_path"


def _fail(identifier, code):
    return _report.failure(identifier, category="static", code=code)


def scan_python(path, relative, failures):
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(relative))
    except SyntaxError:
        failures.append(_fail(f"{relative}", "python_syntax_error"))
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                failures.append(_fail(f"{relative}#{func.id}", "forbidden_call"))
            if (
                isinstance(func, ast.Attribute)
                and func.attr in FORBIDDEN_ATTRIBUTES
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            ):
                failures.append(_fail(f"{relative}#os.{func.attr}", "forbidden_call"))
            for keyword in node.keywords:
                if keyword.arg == "shell" and not (
                    isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is False
                ):
                    failures.append(_fail(f"{relative}#shell", "shell_true"))
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in PRODUCT_IMPORT_PREFIXES:
                    failures.append(_fail(f"{relative}#{alias.name}", "product_import"))
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in PRODUCT_IMPORT_PREFIXES:
                failures.append(_fail(f"{relative}#{node.module}", "product_import"))
    for line_number, line in enumerate(source.splitlines(), start=1):
        if line.lstrip().startswith("#") or ALLOW_MARKER in line:
            continue
        for needle in FORBIDDEN_SUBSTRINGS:
            if needle in line:
                failures.append(
                    _fail(f"{relative}:{line_number}", "absolute_user_path")
                )


def scan_shell(path, relative, failures):
    completed = subprocess.run(  # noqa: S603 - fixed argv
        ["bash", "-n", str(path)],
        env=gitutil.deterministic_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        failures.append(_fail(f"{relative}", "shell_syntax_error"))
        return
    source = path.read_text(encoding="utf-8", errors="replace")
    if "set -euo pipefail" not in source:
        failures.append(_fail(f"{relative}", "missing_strict_mode"))
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("eval ") or " eval " in stripped:
            failures.append(_fail(f"{relative}:{line_number}", "eval_used"))
        if ALLOW_MARKER in stripped:
            continue
        for needle in FORBIDDEN_SUBSTRINGS:
            if needle in stripped:
                failures.append(
                    _fail(f"{relative}:{line_number}", "absolute_user_path")
                )


def collect(root, targets):
    files = []
    for target in targets:
        candidate = root / target
        if candidate.is_file():
            files.append(candidate)
        elif candidate.is_dir():
            files.extend(sorted(candidate.rglob("*.py")))
            files.extend(sorted(candidate.rglob("*.sh")))
    return sorted({path for path in files if "__pycache__" not in path.parts})


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", action="append", default=[], required=True)
    args = parser.parse_args(argv)
    root = Path.cwd()
    failures = []
    scanned = 0
    for path in collect(root, args.path):
        relative = path.relative_to(root)
        scanned += 1
        if path.suffix == ".py":
            scan_python(path, relative, failures)
        elif path.suffix == ".sh":
            scan_shell(path, relative, failures)
    diagnostics = [] if scanned else ["static_scan_no_files"]
    outcome = _report.PASSED if not failures and scanned else _report.FAILED
    return _report.emit(outcome, failures, diagnostics)


if __name__ == "__main__":
    sys.exit(main())
