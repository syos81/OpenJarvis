#!/usr/bin/env python3
"""Preflight runners: prerequisites of the block, nothing else.

Modes:

``worktree``      expected worktree and branch, registered in this repository
``tools``         locally required tools are present and usable
``platform``      declared platform and architecture requirements
``baseline``      the declared baseline commit object exists locally
``claude-config`` required, non-secret project configuration is in place
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import gitutil  # noqa: E402
from tools.gates import manifest as manifest_module  # noqa: E402
from tools.gates.runners import _report  # noqa: E402

REQUIRED_DENIES = (
    "Read(**/.env*)",
    "Bash(git push:*)",
    "Bash(git reset --hard:*)",
    "Bash(git rebase:*)",
    "Bash(git clean:*)",
    "Bash(git stash drop:*)",
    "Bash(rm -rf:*)",
)


def _fail(identifier, code):
    return _report.failure(identifier, category="preflight", code=code)


def mode_worktree(args):
    failures = []
    worktree = Path.cwd()
    try:
        toplevel = gitutil.toplevel(worktree)
    except gitutil.GitError:
        return _report.emit(_report.ERROR, [_fail("worktree.toplevel", "no_worktree")])
    if toplevel.resolve() != worktree.resolve():
        failures.append(_fail("worktree.toplevel", "not_worktree_root"))
    branch = gitutil.current_branch(cwd=worktree)
    if args.expected_branch and branch != args.expected_branch:
        failures.append(_fail("worktree.branch", "unexpected_branch"))
    registered = {
        str(Path(record["worktree"]).resolve())
        for record in gitutil.worktree_list(cwd=worktree)
    }
    if str(toplevel.resolve()) not in registered:
        failures.append(_fail("worktree.registration", "worktree_not_registered"))
    return _report.emit(_report.PASSED if not failures else _report.FAILED, failures)


def mode_tools(args):
    import shutil

    failures = []
    for tool in args.require_tool:
        if shutil.which(tool) is None:
            failures.append(_fail(f"tool.{tool}", "tool_missing"))
    if sys.version_info < tuple(int(part) for part in args.min_python.split(".")):
        failures.append(_fail("tool.python", "python_too_old"))
    try:
        import hashlib

        hashlib.sha256(b"gate")
    except Exception:  # pragma: no cover - stdlib always available
        failures.append(_fail("tool.sha256", "sha256_unavailable"))
    return _report.emit(_report.PASSED if not failures else _report.FAILED, failures)


def mode_platform(args):
    import platform as platform_module

    failures = []
    system = platform_module.system()
    machine = platform_module.machine()
    if args.systems and system not in args.systems:
        failures.append(_fail("platform.system", "unsupported_system"))
    if args.architectures and machine not in args.architectures:
        failures.append(_fail("platform.architecture", "unsupported_architecture"))
    return _report.emit(_report.PASSED if not failures else _report.FAILED, failures)


def mode_baseline(args):
    failures = []
    if not gitutil.commit_exists(args.commit, cwd=Path.cwd()):
        failures.append(_fail("baseline.commit", "baseline_commit_missing"))
    return _report.emit(_report.PASSED if not failures else _report.FAILED, failures)


def mode_claude_config(args):
    failures = []
    worktree = Path.cwd()
    for relative in args.require_file:
        if not (worktree / relative).is_file():
            failures.append(_fail(f"config.{relative}", "required_file_missing"))
    settings_path = worktree / ".claude" / "settings.json"
    if not settings_path.is_file():
        failures.append(_fail("config.settings", "settings_missing"))
        return _report.emit(_report.FAILED, failures)
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except ValueError:
        return _report.emit(
            _report.FAILED, [_fail("config.settings", "settings_unparseable")]
        )
    deny = settings.get("permissions", {}).get("deny", [])
    for rule in REQUIRED_DENIES:
        if rule not in deny:
            failures.append(_fail(f"config.deny.{rule}", "deny_rule_missing"))
    hooks = settings.get("hooks", {}).get("PreToolUse", [])
    commands = []
    for group in hooks if isinstance(hooks, list) else []:
        for hook in group.get("hooks", []) if isinstance(group, dict) else []:
            if isinstance(hook, dict) and hook.get("type") == "command":
                commands.append(str(hook.get("command", "")))
    if not commands:
        failures.append(_fail("config.hook", "pretooluse_hook_missing"))
    for command in commands:
        relative = command.replace("$CLAUDE_PROJECT_DIR/", "").replace(
            "${CLAUDE_PROJECT_DIR}/", ""
        )
        if not (worktree / relative).is_file():
            failures.append(_fail("config.hook.script", "hook_script_missing"))
    return _report.emit(_report.PASSED if not failures else _report.FAILED, failures)


def mode_manifest(args):
    worktree = Path.cwd()
    path = manifest_module.manifest_path_for(worktree, args.block)
    if not path.is_file():
        return _report.emit(
            _report.FAILED, [_fail("manifest.file", "manifest_missing")]
        )
    try:
        manifest_module.load(path)
    except manifest_module.ManifestError as exc:
        failures = [
            _report.failure(f"manifest.{code}", category="manifest", code=code)
            for code, _ in exc.issues
        ]
        return _report.emit(_report.FAILED, failures)
    return _report.emit(_report.PASSED)


def build_parser():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--mode",
        required=True,
        choices=(
            "worktree",
            "tools",
            "platform",
            "baseline",
            "claude-config",
            "manifest",
        ),
    )
    parser.add_argument("--expected-branch", default="")
    parser.add_argument("--require-tool", action="append", default=[])
    parser.add_argument("--min-python", default="3.10")
    parser.add_argument("--systems", action="append", default=[])
    parser.add_argument("--architectures", action="append", default=[])
    parser.add_argument("--commit", default="")
    parser.add_argument("--require-file", action="append", default=[])
    parser.add_argument("--block", default="")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {
        "worktree": mode_worktree,
        "tools": mode_tools,
        "platform": mode_platform,
        "baseline": mode_baseline,
        "claude-config": mode_claude_config,
        "manifest": mode_manifest,
    }
    return handlers[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())
