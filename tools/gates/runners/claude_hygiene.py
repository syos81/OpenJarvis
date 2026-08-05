#!/usr/bin/env python3
"""Gitignore convention and file hygiene for the versioned project rules.

Checks:

* ``git check-ignore --no-index`` for positive and negative path cases,
* only the released ``.claude`` paths are tracked,
* ``settings.local.json`` stays ignored and untracked,
* every tracked, staged and still untracked candidate of the released paths is
  scanned for credentials, private keys, tokens, embedded login data and
  machine dependent absolute paths,
* raw logs and real evidence are excluded from the index.

A finding is reported with path and rule id only — never with the value.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import gitutil  # noqa: E402
from tools.gates import hygiene  # noqa: E402
from tools.gates import paths as gate_paths  # noqa: E402
from tools.gates.runners import _report  # noqa: E402


def _fail(identifier, code):
    return _report.failure(identifier, category="hygiene", code=code)


def check_ignore_no_index(path, cwd):
    code, _, _ = gitutil.run_git(
        ["check-ignore", "--no-index", "--quiet", str(path)], cwd=cwd
    )
    return code == 0


def candidate_files(root):
    """Tracked, staged and untracked candidates of the released paths."""
    candidates = set(gitutil.tracked_files(cwd=root))
    for args in (
        ["diff", "--name-only", "--cached", "HEAD"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        code, out, _ = gitutil.run_git(args, cwd=root)
        if code == 0:
            candidates.update(line.strip() for line in out.splitlines() if line.strip())
    return sorted(path for path in candidates if hygiene.released(path))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="all", choices=("all",))
    parser.parse_args(argv)

    root = Path.cwd()
    failures = []
    diagnostics = []

    for path in hygiene.MUST_BE_TRACKABLE:
        if check_ignore_no_index(path, root):
            failures.append(_fail(path, "released_path_is_ignored"))
    for path in hygiene.MUST_BE_IGNORED:
        if not check_ignore_no_index(path, root):
            failures.append(_fail(path, "unreleased_path_is_not_ignored"))

    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        failures.append(_fail(".gitignore", "gitignore_missing"))
    else:
        for line_number in hygiene.blanket_exception_lines(
            gitignore.read_text(encoding="utf-8")
        ):
            failures.append(_fail(f".gitignore:{line_number}", "blanket_exception"))

    tracked = gitutil.tracked_files(cwd=root)
    for path in tracked:
        if path.startswith(".claude/") and not hygiene.released(path):
            failures.append(_fail(path, "unreleased_claude_path_tracked"))
        if path.startswith(f"{gate_paths.RUNTIME_DIR_NAME}/"):
            failures.append(_fail(path, "raw_log_in_index"))
    if ".claude/settings.local.json" in tracked:
        failures.append(_fail(".claude/settings.local.json", "local_settings_tracked"))

    candidates = candidate_files(root)
    for path in candidates:
        for rule_id, line_number in hygiene.scan_file(root / path):
            failures.append(_fail(f"{path}:{line_number}", rule_id))
    diagnostics.append(f"released_candidates={len(candidates)}")
    diagnostics.append(f"released_patterns={len(hygiene.RELEASED_PATTERNS)}")

    outcome = _report.PASSED if not failures else _report.FAILED
    return _report.emit(outcome, failures, diagnostics)


if __name__ == "__main__":
    sys.exit(main())
