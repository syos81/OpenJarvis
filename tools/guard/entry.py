"""Process entry of the active guard.

Reads one ``PreToolUse`` payload, produces exactly one response document and
never raises. Every unexpected condition ends in a deny with a machine
readable code.
"""

from __future__ import annotations

import json
import sys
import time

from . import GUARD_VERSION
from . import audit
from . import decide as decide_module
from . import errors
from . import owner_exception
from . import rules as rules_module


#: Emitted when the guard deliberately has no opinion. The wrapper needs a
#: positive signal for that case, otherwise it cannot tell abstention from a
#: crashed guard — and a crashed guard must always block.
NO_OPINION = {"guardOutcome": "no_opinion"}


def deny_response(code, detail=""):
    """Build a blocking response for ``code``."""
    reason = errors.message(code)
    if detail:
        reason = reason + " (" + str(detail) + ")"
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": code + ": " + reason,
        }
    }


def response_for(decision):
    if decision.decision is None:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision.decision,
            "permissionDecisionReason": decision.reason_code + ": " + decision.message,
        }
    }


def _log(context, decision, event):
    entry = audit.build_entry(
        event=event,
        decision=str(decision.decision),
        reason_code=decision.reason_code,
        tool=decision.tool,
        worktree_id=decision.worktree_id,
        command_digest=decision.command_digest,
        detection_layer=decision.detection_layer,
        request_excerpt=decision.request_excerpt,
        exception_nonce_digest=decision.exception_nonce_digest,
        guard_version=context.guard_version,
    )
    try:
        audit.assert_clean(entry)
    except ValueError:
        return False
    if not context.log_path:
        return False
    return audit.append_entry(context.log_path, entry)


def run(
    payload,
    *,
    rules_path,
    pending_dir=None,
    spent_dir=None,
    log_path=None,
    observed_dir=None,
    now=None,
    guard_version=GUARD_VERSION,
    exceptions_enabled=True,
):
    """Decide on one payload. Returns ``(response_or_None, decision)``."""
    try:
        rules = rules_module.load_rules(rules_path)
    except rules_module.ConfigError as exc:
        detail = exc.args[0] if exc.args else ""
        return deny_response(errors.GUARD_CONFIG_INVALID, detail), None
    except OSError:
        return deny_response(errors.GUARD_CONFIG_MISSING), None

    context = decide_module.Context(
        rules=rules,
        pending_dir=pending_dir,
        spent_dir=spent_dir,
        log_path=log_path,
        observed_dir=observed_dir,
        guard_version=guard_version,
        now=int(now if now is not None else time.time()),
        exceptions_enabled=exceptions_enabled,
    )

    try:
        decision = decide_module.decide(payload, context)
    except owner_exception.ExceptionCorrupt as exc:
        detail = exc.args[0] if exc.args else ""
        return deny_response(owner_exception.GUARD_EXCEPTION_CORRUPT, detail), None
    except Exception:  # noqa: BLE001 - an internal error must never release
        return deny_response(errors.GUARD_INTERNAL_ERROR), None

    if decision.decision in (
        decide_module.DECISION_ASK,
        decide_module.DECISION_DENY,
    ):
        _log(context, decision, "decision")
    elif decision.reason_code == "owner_exception_consumed":
        if not _log(context, decision, "exception_consumed"):
            # An exception that cannot be recorded is not granted.
            blocked = decide_module.Decision(
                decide_module.DECISION_DENY,
                errors.GUARD_LOG_UNAVAILABLE,
                tool=decision.tool,
            )
            return response_for(blocked), blocked
    return response_for(decision), decision


def main(
    *,
    rules_path,
    pending_dir=None,
    spent_dir=None,
    log_path=None,
    observed_dir=None,
    stdin=None,
    stdout=None,
    now=None,
    guard_version=GUARD_VERSION,
    exceptions_enabled=True,
):
    """Read stdin, decide, write the response. Always returns ``0``.

    ``observed_dir`` is threaded through to :func:`run` because a parameter
    that only the library entry point accepts is a parameter the installed
    guard never uses: the process entry is what the bootstrap calls.
    """
    stream_in = stdin if stdin is not None else sys.stdin
    stream_out = stdout if stdout is not None else sys.stdout
    try:
        raw = stream_in.read()
    except Exception:  # noqa: BLE001 - unreadable input must not release
        stream_out.write(json.dumps(deny_response(errors.GUARD_INPUT_MALFORMED)) + "\n")
        return 0
    try:
        payload = json.loads(raw) if raw and raw.strip() else None
    except ValueError:
        payload = None
    if payload is None or not isinstance(payload, dict):
        stream_out.write(json.dumps(deny_response(errors.GUARD_INPUT_MALFORMED)) + "\n")
        return 0

    response, _decision = run(
        payload,
        rules_path=rules_path,
        pending_dir=pending_dir,
        spent_dir=spent_dir,
        log_path=log_path,
        observed_dir=observed_dir,
        now=now,
        guard_version=guard_version,
        exceptions_enabled=exceptions_enabled,
    )
    document = response if response is not None else NO_OPINION
    stream_out.write(json.dumps(document, sort_keys=True) + "\n")
    return 0
