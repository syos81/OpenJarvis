"""Repository local ``PreToolUse`` guard.

Three layers, in this order:

1. **Hard denies** — ``git push``, ``git reset --hard``, ``git rebase``,
   ``git clean``, ``git stash drop``, ``rm -rf`` and reading ``.env`` files.
   They always win and are never downgraded to ``ask``.
2. **Foreign worktree protection** — a mutating target that canonicalises
   into another worktree of the same repository escalates to ``ask``; it is
   never allowed automatically. Direct, relative and symlinked paths are
   treated alike, and a not yet existing target is canonicalised through its
   nearest existing parent.
3. **Normal work** — a mutating target inside the current worktree is
   allowed; anything the guard cannot classify with confidence escalates to
   ``ask``.

Every ``ask`` and every ``deny`` is written to the gitignored hook raw log
together with the observable request. Only what the hook actually observed is
recorded — no owner approval is ever invented.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shlex
import sys
from pathlib import Path

from . import gitutil
from . import paths as gate_paths
from . import sanitize

DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_ASK = "ask"

#: Hard deny rules on Bash command lines. Order is stable for reporting.
HARD_DENY_COMMAND_RULES = (
    ("git_push", re.compile(r"(^|[;&|]\s*)git(\s+-[^\s]+\s+\S+)*\s+push\b")),
    (
        "git_reset_hard",
        re.compile(r"(^|[;&|]\s*)git(\s+-[^\s]+\s+\S+)*\s+reset\b[^;&|]*--hard\b"),
    ),
    ("git_rebase", re.compile(r"(^|[;&|]\s*)git(\s+-[^\s]+\s+\S+)*\s+rebase\b")),
    ("git_clean", re.compile(r"(^|[;&|]\s*)git(\s+-[^\s]+\s+\S+)*\s+clean\b")),
    (
        "git_stash_drop",
        re.compile(r"(^|[;&|]\s*)git(\s+-[^\s]+\s+\S+)*\s+stash\s+drop\b"),
    ),
    ("rm_rf", re.compile(r"(^|[;&|]\s*)rm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rR]")),
)

_ENV_FILE_RE = re.compile(r"(^|/)\.env(\.|$)")

FILE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
READ_TOOLS = ("Read",)

MUTATING_COMMANDS = {
    "chmod",
    "chown",
    "cp",
    "dd",
    "install",
    "ln",
    "mkdir",
    "mv",
    "rm",
    "rmdir",
    "tee",
    "touch",
    "truncate",
}
MUTATING_GIT_SUBCOMMANDS = {
    "add",
    "am",
    "apply",
    "checkout",
    "cherry-pick",
    "commit",
    "merge",
    "mv",
    "reset",
    "restore",
    "revert",
    "rm",
    "stash",
    "switch",
    "worktree",
}
SHELL_CONTROL_TOKENS = (";", "&&", "||", "|", "$(", "`", ">", ">>")


def canonicalize(raw_path, base_dir):
    """Canonicalise a target: expand, absolutise, normalise, resolve links.

    A not yet existing target is canonicalised through its nearest existing
    parent, so a new file below a foreign worktree is still recognised.
    """
    candidate = Path(os.path.expanduser(str(raw_path)))
    if not candidate.is_absolute():
        candidate = Path(base_dir) / candidate
    candidate = Path(os.path.normpath(str(candidate)))
    remainder = []
    existing = candidate
    while not existing.exists():
        parent = existing.parent
        if parent == existing:
            break
        remainder.append(existing.name)
        existing = parent
    try:
        resolved = existing.resolve()
    except OSError:  # pragma: no cover - defensive
        resolved = existing
    for part in reversed(remainder):
        resolved = resolved / part
    return resolved


def _is_inside(path, root):
    try:
        Path(path).relative_to(Path(root))
    except ValueError:
        return False
    return True


def hard_deny_reason(tool_name, tool_input):
    """Return a hard deny reason code, or ``None``."""
    if tool_name in FILE_TOOLS + READ_TOOLS:
        target = str(
            tool_input.get("file_path")
            or tool_input.get("notebook_path")
            or tool_input.get("path")
            or ""
        )
        if target and _ENV_FILE_RE.search(target):
            return "env_file_access"
    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        for code, pattern in HARD_DENY_COMMAND_RULES:
            if pattern.search(command):
                return code
        if re.search(r"(^|[\s;&|<>])(cat|less|more|head|tail|bat)\s+[^\s;&|]*", command):
            for token in re.findall(r"[^\s;&|<>]+", command):
                if _ENV_FILE_RE.search(token):
                    return "env_file_access"
    return None


def _bash_targets(command):
    """Return ``(targets, ambiguous, mutating)`` for a Bash command line."""
    ambiguous = any(token in command for token in SHELL_CONTROL_TOKENS)
    try:
        tokens = shlex.split(command)
    except ValueError:
        return [], True, True
    if not tokens:
        return [], False, False
    mutating = False
    targets = []
    head = Path(tokens[0]).name
    if head in MUTATING_COMMANDS:
        mutating = True
    if head == "git":
        index = 1
        while index < len(tokens) and tokens[index].startswith("-"):
            if tokens[index] == "-C" and index + 1 < len(tokens):
                targets.append(tokens[index + 1])
                index += 2
                continue
            index += 1
        if index < len(tokens) and tokens[index] in MUTATING_GIT_SUBCOMMANDS:
            mutating = True
    if any(token in (">", ">>") for token in tokens):
        mutating = True
    for token in tokens[1:]:
        if token.startswith("-"):
            continue
        if "/" in token or token in (".", ".."):
            targets.append(token)
    return targets, ambiguous, mutating


def decide(payload, *, worktree_lookup=None):
    """Decide on one PreToolUse request.

    Returns ``(decision, reason_code, record)`` where ``record`` carries the
    observable detail for the gitignored hook log.
    """
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") or {}
    cwd = str(payload.get("cwd") or os.getcwd())
    record = {
        "tool": tool_name,
        "original_target": "",
        "canonical_target": "",
        "current_worktree": "",
        "foreign_worktree": "",
    }

    hard = hard_deny_reason(tool_name, tool_input)
    if hard:
        record["original_target"] = str(
            tool_input.get("file_path") or tool_input.get("command") or ""
        )
        return DECISION_DENY, hard, record

    if tool_name in FILE_TOOLS:
        raw_targets = [
            str(
                tool_input.get("file_path")
                or tool_input.get("notebook_path")
                or tool_input.get("path")
                or ""
            )
        ]
        ambiguous = not raw_targets[0]
        mutating = True
        record["original_target"] = raw_targets[0]
    elif tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        raw_targets, ambiguous, mutating = _bash_targets(command)
        record["original_target"] = sanitize.scrub(command, max_length=200)
    else:
        return None, "not_applicable_tool", record

    if not mutating:
        return None, "non_mutating", record

    lookup = worktree_lookup or _default_worktree_lookup
    current_worktree, worktrees = lookup(cwd)
    record["current_worktree"] = str(current_worktree or "")

    if current_worktree is None:
        return DECISION_ASK, "worktree_undetermined", record

    for raw in raw_targets:
        if not raw:
            continue
        canonical = canonicalize(raw, cwd)
        for candidate in worktrees:
            if candidate == current_worktree:
                continue
            if _is_inside(canonical, candidate):
                record["canonical_target"] = str(canonical)
                record["foreign_worktree"] = str(candidate)
                return DECISION_ASK, "foreign_worktree_mutation", record

    if ambiguous:
        return DECISION_ASK, "ambiguous_mutating_command", record

    if raw_targets:
        record["canonical_target"] = str(canonicalize(raw_targets[0], cwd))
    return DECISION_ALLOW, "current_worktree_mutation", record


def _default_worktree_lookup(cwd):
    try:
        current = gitutil.toplevel(cwd).resolve()
    except gitutil.GitError:
        return None, []
    try:
        worktrees = [
            Path(record["worktree"]).resolve()
            for record in gitutil.worktree_list(cwd=cwd)
        ]
    except gitutil.GitError:  # pragma: no cover - defensive
        worktrees = [current]
    return current, worktrees


def log_decision(decision, reason_code, record, *, worktree, now=None):
    """Append the observable request to the gitignored hook raw log."""
    if worktree is None:
        return None
    directory = gate_paths.ensure_private_dir(gate_paths.hook_log_dir(worktree))
    stamp = now or datetime.datetime.now(datetime.timezone.utc)
    entry = {
        "timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "current_worktree": record.get("current_worktree", ""),
        "tool": record.get("tool", ""),
        "original_target": record.get("original_target", ""),
        "canonical_target": record.get("canonical_target", ""),
        "foreign_worktree": record.get("foreign_worktree", ""),
        "decision": decision,
        "reason_code": reason_code,
    }
    target = directory / f"hook-{stamp.strftime('%Y-%m-%d')}.jsonl"
    with open(
        os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600),
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")

    summary_path = directory / "summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        summary = {}
    key = f"{decision}.{reason_code}"
    summary[key] = int(summary.get(key, 0)) + 1
    sanitize.assert_clean(summary, "$hook_summary")
    summary_path.write_text(
        json.dumps(summary, sort_keys=True, indent=2), encoding="utf-8"
    )
    return target


def build_response(decision, reason_code):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": REASON_TEXT.get(reason_code, reason_code),
        }
    }


REASON_TEXT = {
    "env_file_access": "Hard deny: .env files are never read by tooling.",
    "git_push": "Hard deny: git push requires an explicit owner decision.",
    "git_reset_hard": "Hard deny: git reset --hard is not permitted.",
    "git_rebase": "Hard deny: git rebase is not permitted.",
    "git_clean": "Hard deny: git clean is not permitted.",
    "git_stash_drop": "Hard deny: git stash drop is not permitted.",
    "rm_rf": "Hard deny: recursive rm is not permitted.",
    "foreign_worktree_mutation": (
        "This would modify a different worktree of the same repository. "
        "Escalating to Lukas; the request is recorded in the local hook log."
    ),
    "ambiguous_mutating_command": (
        "Mutating command whose targets cannot be determined with confidence."
    ),
    "worktree_undetermined": "The current worktree could not be determined.",
    "current_worktree_mutation": "Target is inside the current worktree.",
}


def main(argv=None, *, stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        payload = json.load(stdin)
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    decision, reason_code, record = decide(payload)
    if decision in (DECISION_ASK, DECISION_DENY):
        cwd = str(payload.get("cwd") or os.getcwd())
        try:
            worktree = gitutil.toplevel(cwd)
        except gitutil.GitError:
            worktree = None
        try:
            log_decision(decision, reason_code, record, worktree=worktree)
        except OSError:  # pragma: no cover - logging must never break the hook
            pass
    if decision is None:
        return 0
    stdout.write(json.dumps(build_response(decision, reason_code)) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
