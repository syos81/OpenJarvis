#!/usr/bin/env python3
"""Repository guard: working tree state, raw logs, product changes, canaries.

Modes:

``state``  the runtime area is ignored, no raw log is tracked, no canary
           marker appears in a tracked artifact
``final``  additionally: every change stays inside the paths the block
           manifest allows, and no forbidden path was touched
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import canaries  # noqa: E402
from tools.gates import gitutil  # noqa: E402
from tools.gates import manifest as manifest_module  # noqa: E402
from tools.gates import paths as gate_paths  # noqa: E402
from tools.gates.runners import _report  # noqa: E402

BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".ico",
    ".icns",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".so",
    ".dylib",
    ".lock",
}


def _fail(identifier, code):
    return _report.failure(identifier, category="repo_guard", code=code)


def check_runtime_ignored(root, failures):
    runtime_name = gate_paths.RUNTIME_DIR_NAME
    probe = f"{runtime_name}/raw-logs/probe.log"
    if not gitutil.check_ignore(probe, cwd=root):
        failures.append(_fail("gitignore.runtime", "runtime_area_not_ignored"))
    tracked = gitutil.tracked_files(cwd=root)
    for path in tracked:
        if path.startswith(f"{runtime_name}/"):
            failures.append(_fail(f"tracked.{path}", "raw_log_tracked"))


def check_canaries(root, failures):
    marker = canaries.MARKER
    for path in gitutil.tracked_files(cwd=root):
        candidate = root / path
        if candidate.suffix.lower() in BINARY_SUFFIXES or not candidate.is_file():
            continue
        try:
            if candidate.stat().st_size > 2_000_000:
                continue
            content = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if marker in content:
            failures.append(_fail(f"canary.{path}", "canary_in_tracked_artifact"))


def check_product_changes(root, manifest, failures):
    """Compare against the commit the block itself started from.

    Only the block's own delta is judged — history that already existed on the
    branch before B0a-1 belongs to earlier blocks.
    """
    guard = manifest.data["product_guard"]
    changed, base_resolved = gitutil.changed_files(
        guard["block_base_commit"], cwd=root
    )
    if base_resolved is None:
        failures.append(_fail("product.base", "block_base_commit_unresolved"))
        return ["product_guard_base_commit_unresolved"]
    for path in changed:
        if any(fnmatch.fnmatch(path, pattern) for pattern in guard["forbidden_paths"]):
            failures.append(_fail(f"product.{path}", "forbidden_path_changed"))
            continue
        if not any(
            fnmatch.fnmatch(path, pattern) for pattern in guard["allowed_paths"]
        ):
            failures.append(_fail(f"product.{path}", "product_change_detected"))
    return []


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("state", "final"))
    parser.add_argument("--block", required=True)
    args = parser.parse_args(argv)

    root = Path.cwd()
    failures = []
    diagnostics = []
    check_runtime_ignored(root, failures)
    check_canaries(root, failures)

    if args.mode == "final":
        path = manifest_module.manifest_path_for(root, args.block)
        if not path.is_file():
            failures.append(_fail("manifest", "manifest_missing"))
        else:
            try:
                manifest = manifest_module.load(path)
            except manifest_module.ManifestError:
                failures.append(_fail("manifest", "manifest_invalid"))
            else:
                diagnostics.extend(check_product_changes(root, manifest, failures))

    outcome = _report.PASSED if not failures else _report.FAILED
    return _report.emit(outcome, failures, diagnostics)


if __name__ == "__main__":
    sys.exit(main())
