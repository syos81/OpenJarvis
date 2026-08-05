#!/usr/bin/env python3
"""Shell syntax scan — the baseline comparable check of this block.

It runs ``bash -n`` over every tracked shell script below the given
directory, in stable order, and reports one structural failure per broken
script. The check is meaningful at the candidate commit *and* at the baseline
commit, which is what makes a baseline comparison possible at all.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import gitutil  # noqa: E402
from tools.gates.runners import _report  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default="scripts")
    args = parser.parse_args(argv)

    root = Path.cwd()
    directory = root / args.directory
    failures = []
    scripts = sorted(directory.rglob("*.sh")) if directory.is_dir() else []
    for script in scripts:
        relative = script.relative_to(root)
        completed = subprocess.run(  # noqa: S603 - fixed argv
            ["bash", "-n", str(script)],
            env=gitutil.deterministic_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            failures.append(
                _report.failure(
                    str(relative),
                    category="shell_syntax",
                    error_class="ShellSyntaxError",
                    code=f"exit_{completed.returncode}",
                )
            )
    diagnostics = [] if scripts else ["no_shell_scripts_found"]
    outcome = _report.PASSED if not failures and scripts else _report.FAILED
    return _report.emit(outcome, failures, diagnostics)


if __name__ == "__main__":
    sys.exit(main())
