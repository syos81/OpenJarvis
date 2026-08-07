"""The guard decision pipeline.

Layers, in this order. A later layer can never overrule an earlier one:

0. **integrity** — established by the bootstrap before this module is even
   imported. An owner command exception can never reach it.
1. **hard denies** — argument based, with a raw text backstop.
2. **owner exception** — consulted only for a layer 1 deny, only for the
   exact canonicalised command, only once. The layer 1 decision is built and
   held *before* this layer runs: an exception object may replace it with an
   allow or leave it alone, and may never alter it. An expired or version
   foreign object is neither, so it is recorded as diagnosis and the layer 1
   decision is returned byte identical.
2a. **target bound fixture rule** — consulted only for an eligible layer 1
   deny, and only released when the target fully resolves into a throwaway
   bare repository below the declared fixture root. Unlike an exception it
   needs no present owner, which is why a gate may depend on it.
3. **worktree protection** — a mutating target that canonicalises into a
   different worktree of the same repository escalates to ``ask``.
4. **normal work** — a mutating target inside the current worktree is
   allowed; a mutating request in an undeterminable repository state is
   denied, never released.

The guard never reads a file from the worktree it protects.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import errors
from . import fixture
from . import observed
from . import owner_exception
from . import rules as rules_module

DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_ASK = "ask"

FILE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
READ_TOOLS = ("Read",)

GIT_BINARY = "/usr/bin/git"


class Context:
    """Everything the decision needs, all of it owner controlled."""

    __slots__ = (
        "rules",
        "pending_dir",
        "spent_dir",
        "log_path",
        "guard_version",
        "now",
        "git_binary",
        "exceptions_enabled",
        "observed_dir",
    )

    def __init__(
        self,
        *,
        rules,
        pending_dir=None,
        spent_dir=None,
        log_path=None,
        guard_version="",
        now=0,
        git_binary=GIT_BINARY,
        exceptions_enabled=True,
        observed_dir=None,
    ):
        self.rules = rules
        self.pending_dir = pending_dir
        self.spent_dir = spent_dir
        self.log_path = log_path
        self.guard_version = guard_version
        self.now = now
        self.git_binary = git_binary
        self.exceptions_enabled = exceptions_enabled
        #: Where non decision bearing observations are recorded. ``None``
        #: disables recording and changes no decision.
        self.observed_dir = observed_dir


class Decision:
    """One decision plus everything the protocol is allowed to record."""

    #: ``local_*`` fields never enter the protected protocol. They exist for
    #: the gitignored repository side raw log, which may name paths.
    __slots__ = (
        "decision",
        "reason_code",
        "message",
        "detection_layer",
        "exception_nonce_digest",
        "worktree_id",
        "command_digest",
        "request_excerpt",
        "tool",
        "local_current_worktree",
        "local_canonical_target",
        "local_foreign_worktree",
        "local_original_target",
    )

    def __init__(
        self,
        decision,
        reason_code,
        *,
        message="",
        detection_layer="",
        exception_nonce_digest="",
        worktree_id="",
        command_digest="",
        request_excerpt="",
        tool="",
        local_current_worktree="",
        local_canonical_target="",
        local_foreign_worktree="",
        local_original_target="",
    ):
        self.decision = decision
        self.reason_code = reason_code
        self.message = message or errors.message(reason_code, reason_code)
        self.detection_layer = detection_layer
        self.exception_nonce_digest = exception_nonce_digest
        self.worktree_id = worktree_id
        self.command_digest = command_digest
        self.request_excerpt = request_excerpt
        self.tool = tool
        self.local_current_worktree = local_current_worktree
        self.local_canonical_target = local_canonical_target
        self.local_foreign_worktree = local_foreign_worktree
        self.local_original_target = local_original_target


def _run_git(context, args, cwd):
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [context.git_binary] + list(args),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return completed.returncode, completed.stdout.decode("utf-8", "replace")


def worktree_lookup(context, cwd):
    """Return ``(current_worktree, all_worktrees)``; ``None`` when unknown."""
    code, out = _run_git(context, ["rev-parse", "--show-toplevel"], cwd)
    if code != 0 or not out.strip():
        return None, []
    try:
        current = Path(out.strip()).resolve()
    except OSError:  # pragma: no cover - defensive
        return None, []
    code, out = _run_git(context, ["worktree", "list", "--porcelain"], cwd)
    if code != 0:
        return current, [current]
    found = []
    for line in out.splitlines():
        if line.startswith("worktree "):
            try:
                found.append(Path(line[len("worktree "):].strip()).resolve())
            except OSError:  # pragma: no cover - defensive
                continue
    return current, found or [current]


def canonicalize(raw_path, base_dir):
    """Canonicalise a target through its nearest existing parent."""
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


def _tool_target(tool_input):
    return str(
        tool_input.get("file_path")
        or tool_input.get("notebook_path")
        or tool_input.get("path")
        or ""
    )


def decide(payload, context):
    """Decide on one PreToolUse request. Always returns a :class:`Decision`."""
    if not isinstance(payload, dict):
        return Decision(DECISION_DENY, errors.GUARD_INPUT_MALFORMED)
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input")
    if tool_input is None:
        tool_input = {}
    if not isinstance(tool_input, dict):
        return Decision(DECISION_DENY, errors.GUARD_INPUT_MALFORMED, tool=tool_name)
    cwd = str(payload.get("cwd") or os.getcwd())

    rules = context.rules

    # -- layer 1: hard denies ---------------------------------------------
    if tool_name in FILE_TOOLS + READ_TOOLS:
        target = _tool_target(tool_input)
        code = rules_module.evaluate_path(rules, target)
        if code:
            return Decision(
                DECISION_DENY,
                code,
                message=rules.message(code),
                detection_layer="argv",
                tool=tool_name,
                request_excerpt=target,
                local_original_target=target,
            )
    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        code, layer = rules_module.evaluate_command(rules, command, cwd=cwd)
        if code:
            # -- layer 1 result, complete and final on its own ---------------
            # The base decision is built here, before any exception object is
            # looked at. Everything below may replace it with an allow or
            # leave it alone; nothing below may alter it.
            base = Decision(
                DECISION_DENY,
                code,
                message=rules.message(code),
                detection_layer=layer,
                tool=tool_name,
                command_digest=owner_exception.command_digest(command),
                request_excerpt=command,
                worktree_id=_safe_worktree_id(cwd),
                local_original_target=command,
            )
            verdict = fixture.evaluate(
                rules,
                code,
                command,
                cwd,
                lambda args, where: _run_git(context, args, where),
            )
            if verdict.granted:
                return Decision(
                    DECISION_ALLOW,
                    errors.ALLOW_FIXTURE_TARGET,
                    detection_layer="fixture",
                    tool=tool_name,
                    command_digest=owner_exception.command_digest(command),
                    request_excerpt=command,
                    worktree_id=_safe_worktree_id(cwd),
                    local_original_target=command,
                    local_canonical_target=verdict.local_target,
                )
            # -- layer 2: override attempt, and only that --------------------
            outcome = _consult_exception(context, cwd, command)
            if outcome is not None:
                # Diagnosis is recorded after the base decision exists and
                # before it is returned, so a failure here cannot influence
                # what is returned. record_all never raises.
                observed.record_all(
                    context.observed_dir, outcome.observations, now=None
                )
            if outcome is not None and outcome.granted:
                return Decision(
                    DECISION_ALLOW,
                    "owner_exception_consumed",
                    message="Released once by an owner exception.",
                    detection_layer=layer,
                    exception_nonce_digest=outcome.nonce_digest,
                    tool=tool_name,
                    command_digest=owner_exception.command_digest(command),
                    request_excerpt=command,
                    worktree_id=_safe_worktree_id(cwd),
                    local_original_target=command,
                )
            # No override. The base decision is returned unchanged — a non
            # candidate object contributes no nonce digest, so this is byte
            # identical to the decision reached with no objects at all.
            base.exception_nonce_digest = (
                outcome.nonce_digest if outcome is not None else ""
            )
            return base
        if layer == "unparseable":
            return Decision(
                DECISION_DENY,
                errors.DENY_UNPARSEABLE_COMMAND,
                detection_layer=layer,
                tool=tool_name,
                request_excerpt=command,
                worktree_id=_safe_worktree_id(cwd),
                local_original_target=command,
            )

    # -- layer 3/4: worktree protection ------------------------------------
    if tool_name in FILE_TOOLS:
        raw_targets = [_tool_target(tool_input)]
        ambiguous = not raw_targets[0]
        mutating = True
        excerpt = raw_targets[0]
        original = raw_targets[0]
    elif tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        raw_targets, ambiguous, mutating = rules_module.command_targets(
            rules, command
        )
        excerpt = command
        original = command
    else:
        return Decision(None, "not_applicable_tool", tool=tool_name)

    if not mutating:
        return Decision(
            None, "non_mutating", tool=tool_name, local_original_target=original
        )

    current, worktrees = worktree_lookup(context, cwd)
    if current is None:
        return Decision(
            DECISION_DENY,
            errors.DENY_WORKTREE_UNDETERMINED,
            detection_layer="worktree",
            tool=tool_name,
            request_excerpt=excerpt,
            local_original_target=original,
        )

    identifier = owner_exception.worktree_id(current)
    for raw in raw_targets:
        if not raw:
            continue
        canonical = canonicalize(raw, cwd)
        for candidate in worktrees:
            if candidate == current:
                continue
            if _is_inside(canonical, candidate):
                return Decision(
                    DECISION_ASK,
                    errors.ASK_FOREIGN_WORKTREE,
                    detection_layer="worktree",
                    tool=tool_name,
                    worktree_id=identifier,
                    request_excerpt=excerpt,
                    local_original_target=original,
                    local_current_worktree=str(current),
                    local_canonical_target=str(canonical),
                    local_foreign_worktree=str(candidate),
                )

    if ambiguous:
        return Decision(
            DECISION_ASK,
            errors.ASK_AMBIGUOUS_TARGET,
            detection_layer="worktree",
            tool=tool_name,
            worktree_id=identifier,
            request_excerpt=excerpt,
            local_original_target=original,
            local_current_worktree=str(current),
        )

    first = ""
    for raw in raw_targets:
        if raw:
            first = str(canonicalize(raw, cwd))
            break
    return Decision(
        DECISION_ALLOW,
        "current_worktree_mutation",
        message="Target is inside the current worktree.",
        detection_layer="worktree",
        tool=tool_name,
        worktree_id=identifier,
        local_original_target=original,
        local_current_worktree=str(current),
        local_canonical_target=first,
    )


def _safe_worktree_id(cwd):
    try:
        return owner_exception.worktree_id(cwd)
    except OSError:  # pragma: no cover - defensive
        return ""


def _consult_exception(context, cwd, command):
    """Consult the owner exception area. ``None`` when it is not configured.

    A corrupt exception object propagates: the caller must block rather than
    decide while the exception state is unknown.
    """
    if not context.exceptions_enabled:
        return None
    if not context.pending_dir or not context.spent_dir:
        return None
    return owner_exception.consume(
        pending_dir=context.pending_dir,
        spent_dir=context.spent_dir,
        worktree=cwd,
        command=command,
        now=context.now,
        policy=context.rules.exception_policy,
        guard_version=context.guard_version,
    )
