#!/usr/bin/env python3
"""Repository guard: working tree state, raw logs, product changes, canaries.

Modes:

``state``  the runtime area is ignored, no raw log is tracked, no canary
           marker appears in a tracked artifact
``final``  additionally: the guard base is derived mechanically from the git
           history, the manifest declaration is validated against it, and the
           *complete* range from the line origin to the current state is
           classified against the manifest's product guard.

The examined range is never narrowed to the current block's delta. It covers
every commit in ``base..HEAD``, the union of all paths touched inside that
range, the cumulative tree difference, the index, the working tree and
untracked candidate files — so a product change that was later reverted stays
visible.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import canaries  # noqa: E402
from tools.gates import gitutil  # noqa: E402
from tools.gates import guardbase  # noqa: E402
from tools.gates import manifest as manifest_module  # noqa: E402
from tools.gates import paths as gate_paths  # noqa: E402
from tools.gates import statuses  # noqa: E402
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


def collect_examined_paths(root, base_commit):
    """Union of every path the guarded range touches, from five sources."""
    sources = {
        "commit_history": ["log", "--name-only", "--no-renames", "--pretty=format:",
                           f"{base_commit}..HEAD"],
        "cumulative_tree": ["diff", "--name-only", "--no-renames", base_commit, "HEAD"],
        "index": ["diff", "--name-only", "--cached", "HEAD"],
        "worktree": ["diff", "--name-only", "HEAD"],
        "untracked": ["ls-files", "--others", "--exclude-standard"],
    }
    examined = {}
    for source, args in sorted(sources.items()):
        code, out, _ = gitutil.run_git(args, cwd=root)
        if code != 0:
            continue
        for line in out.splitlines():
            path = line.strip()
            if path:
                examined.setdefault(path, set()).add(source)
    return examined


def check_product_changes(root, manifest, failures, diagnostics):
    """Derive the guard base, validate the declaration, classify the range."""
    guard = manifest.data["product_guard"]
    try:
        derivation = guardbase.derive_for_repository(root)
    except guardbase.GuardBaseError as exc:
        failures.append(_fail("guard_base", exc.reason_code))
        return
    base_commit = derivation["base_commit"]
    diagnostics.append(f"guard_base={base_commit[:12]}")
    diagnostics.append(f"guard_base_derivation={derivation['derivation']}")

    status, reason = guardbase.validate_declared_base(
        guard.get("block_base_commit"), base_commit
    )
    if status != statuses.PASS:
        failures.append(_fail("guard_base.declared", reason))
    else:
        diagnostics.append(reason)

    examined = collect_examined_paths(root, base_commit)
    diagnostics.append(f"examined_paths={len(examined)}")
    code, out, _ = gitutil.run_git(
        ["rev-list", "--count", f"{base_commit}..HEAD"], cwd=root
    )
    if code == 0 and out.strip():
        diagnostics.append(f"examined_commits={out.strip()}")

    for path in sorted(examined):
        if any(
            fnmatch.fnmatch(path, pattern) for pattern in guard["forbidden_paths"]
        ):
            failures.append(_fail(f"product.{path}", "forbidden_path_changed"))
            continue
        if not any(
            fnmatch.fnmatch(path, pattern) for pattern in guard["allowed_paths"]
        ):
            failures.append(_fail(f"product.{path}", "product_change_detected"))


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
                check_product_changes(root, manifest, failures, diagnostics)

    outcome = _report.PASSED if not failures else _report.FAILED
    return _report.emit(outcome, failures, diagnostics)


if __name__ == "__main__":
    sys.exit(main())
