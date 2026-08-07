"""Repository scoped ``PreToolUse`` guard — **not** the trust anchor.

Since B0a-4 there is exactly one guard implementation: ``tools/guard``. This
module is a thin adapter over it and exists for two reasons:

* it keeps the B0a-1 public surface (``decide``, ``canonicalize``,
  ``log_decision``, the gitignored hook raw log) so the inherited features
  stay verifiable on the current line,
* it drives the repository side hook, which is a *second*, defence in depth
  layer only.

The repository side layer is deliberately declared non authoritative: it
lives inside the guarded worktree and is therefore modifiable by the guarded
session. The authoritative guard is the owner installed copy outside every
worktree, registered through the protected policy settings. Nothing here may
ever be presented as the protection boundary.

Decision layers, results and reason codes are the ones of ``tools/guard``;
the legacy reason codes are preserved through :data:`LEGACY_REASON_CODES` so
inherited evidence keeps its meaning.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.guard import GUARD_VERSION  # noqa: E402
from tools.guard import audit as guard_audit  # noqa: E402
from tools.guard import decide as guard_decide  # noqa: E402
from tools.guard import errors as guard_errors  # noqa: E402
from tools.guard import rules as guard_rules  # noqa: E402

from . import gitutil
from . import paths as gate_paths
from . import sanitize

DECISION_ALLOW = guard_decide.DECISION_ALLOW
DECISION_DENY = guard_decide.DECISION_DENY
DECISION_ASK = guard_decide.DECISION_ASK

FILE_TOOLS = guard_decide.FILE_TOOLS
READ_TOOLS = guard_decide.READ_TOOLS

#: Canonical location of the repository side rule configuration.
RULES_PATH = Path(__file__).resolve().parents[1] / "guard" / "rules.json"

#: New reason code -> B0a-1 reason code. Only names are mapped; a decision is
#: never rewritten here.
LEGACY_REASON_CODES = {
    guard_errors.ASK_FOREIGN_WORKTREE: "foreign_worktree_mutation",
    guard_errors.ASK_AMBIGUOUS_TARGET: "ambiguous_mutating_command",
    guard_errors.DENY_WORKTREE_UNDETERMINED: "worktree_undetermined",
    guard_errors.DENY_UNPARSEABLE_COMMAND: "unparseable_command",
}


#: Where the owner installed, authoritative guard lives, and where its
#: registration must be found. Both are read only from here.
ACTIVE_INSTALL_ROOT = Path("/usr/local/jarvis-guard")  # gate-allow: absolute_user_path
ACTIVE_POLICY_FILE = Path(
    "/Library/Application Support/ClaudeCode/managed-settings.json"
)


def authoritative_guard_active(
    install_root=ACTIVE_INSTALL_ROOT, policy_file=ACTIVE_POLICY_FILE
):
    """True when the owner installed guard is present *and* registered.

    Both conditions are required. A wrapper that exists but is not registered
    guards nothing, and a registration that points somewhere else is not this
    guard. Everything checked here is root owned; the session cannot make this
    function return ``True`` by writing anything it is allowed to write.
    """
    wrapper = Path(install_root) / "bootstrap.sh"
    try:
        for path in (Path(install_root), wrapper, Path(policy_file)):
            info = os.lstat(str(path))
            if info.st_uid != 0:
                return False
        registration = json.loads(
            Path(policy_file).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return False
    groups = registration.get("hooks", {}).get("PreToolUse", [])
    if not isinstance(groups, list):
        return False
    for group in groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks", []) or []:
            if not isinstance(hook, dict):
                continue
            if str(hook.get("command", "")) == str(wrapper):
                return True
    return False


_RULES_CACHE = []


def _rules():
    """Load the repository side rule configuration once per process."""
    if not _RULES_CACHE:
        _RULES_CACHE.append(guard_rules.load_rules(RULES_PATH))
    return _RULES_CACHE[0]


def _context(now=None):
    return guard_decide.Context(
        rules=_rules(),
        guard_version=GUARD_VERSION,
        now=int(now if now is not None else time.time()),
        exceptions_enabled=False,
    )


#: Every hard deny code the active rule set can produce, with its sentence.
#: Kept as a tuple so the B0a-1 consistency test keeps its shape.
#:
#: All three are computed on access rather than at import. This layer
#: declares itself non authoritative and abstains whenever the owner
#: installed guard is active — but it used to read its own rule
#: configuration while being imported, so an unusable configuration made
#: it block every request before it could abstain. A deference that only
#: takes effect after loading the very thing it renounces is not a
#: deference, so the loading moved behind it.
def hard_deny_command_rules():
    rules = _rules()
    return tuple((code, rules.message(code)) for code in rules.codes())


def rewrite_classes():
    """Declared classification of the local history rewrite operations.

    The audit of comparable operations lives in
    ``config/guard/history-rewrite-matrix.json``.
    """
    return _rules().rewrite_classes()


_EXTRA_REASON_TEXT = (
    {
        "foreign_worktree_mutation": (
            "This would modify a different worktree of the same repository. "
            "Escalating to Lukas; the request is recorded in the local hook log."
        ),
        "ambiguous_mutating_command": (
            "Mutating command whose targets cannot be determined with confidence."
        ),
        "worktree_undetermined": (
            "The current worktree could not be determined; a mutating request "
            "is blocked instead of released."
        ),
        "unparseable_command": "The command could not be parsed safely.",
        "current_worktree_mutation": "Target is inside the current worktree.",
    }
)


def reason_text():
    text = dict(_rules().reason_text)
    text.update(_EXTRA_REASON_TEXT)
    return text


def __getattr__(name):
    """Keep the previous module attributes working, but lazily.

    Reading one of them still loads the configuration; importing the
    module no longer does.
    """
    if name == "HARD_DENY_COMMAND_RULES":
        return hard_deny_command_rules()
    if name == "REWRITE_CLASSES":
        return rewrite_classes()
    if name == "REASON_TEXT":
        return reason_text()
    raise AttributeError(name)


def canonicalize(raw_path, base_dir):
    """Canonicalise a target through its nearest existing parent."""
    return guard_decide.canonicalize(raw_path, base_dir)


def hard_deny_reason(tool_name, tool_input):
    """Return a hard deny reason code, or ``None``."""
    rules = _rules()
    if tool_name in FILE_TOOLS + READ_TOOLS:
        target = str(
            tool_input.get("file_path")
            or tool_input.get("notebook_path")
            or tool_input.get("path")
            or ""
        )
        code = guard_rules.evaluate_path(rules, target)
        if code:
            return code
    if tool_name == "Bash":
        code, _layer = guard_rules.evaluate_command(
            rules, str(tool_input.get("command", ""))
        )
        return code
    return None


def decide(payload, *, worktree_lookup=None):
    """Decide on one PreToolUse request.

    Returns ``(decision, reason_code, record)``. ``reason_code`` uses the
    B0a-1 vocabulary where one exists.
    """
    context = _context()
    if worktree_lookup is not None:
        original = guard_decide.worktree_lookup

        def patched(_context, cwd):
            return worktree_lookup(cwd)

        guard_decide.worktree_lookup = patched
        try:
            decision = guard_decide.decide(payload, context)
        finally:
            guard_decide.worktree_lookup = original
    else:
        decision = guard_decide.decide(payload, context)

    record = {
        "tool": decision.tool,
        "original_target": (
            guard_audit.scrub(decision.local_original_target, max_length=200)
            if decision.tool == "Bash"
            else decision.local_original_target
        ),
        "canonical_target": decision.local_canonical_target,
        "current_worktree": decision.local_current_worktree,
        "foreign_worktree": decision.local_foreign_worktree,
    }
    reason = LEGACY_REASON_CODES.get(decision.reason_code, decision.reason_code)
    return decision.decision, reason, record


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
            "permissionDecisionReason": reason_text().get(
                reason_code, reason_code
            ),
        }
    }


def main(argv=None, *, stdin=None, stdout=None, authoritative=None):
    """Repository side entry point. Fail closed on every error path.

    ``authoritative`` is the predicate that decides whether the owner
    installed guard has already ruled. It is injectable so the tests can
    exercise this layer in isolation; production passes nothing.
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        raw = stdin.read()
    except Exception:  # noqa: BLE001 - unreadable input must not release
        stdout.write(json.dumps(_deny(guard_errors.GUARD_INPUT_MALFORMED)) + "\n")
        return 0
    try:
        payload = json.loads(raw) if raw and raw.strip() else None
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        stdout.write(json.dumps(_deny(guard_errors.GUARD_INPUT_MALFORMED)) + "\n")
        return 0

    # The authoritative guard applies the same rules on a verified package and
    # additionally knows the owner exceptions. Deciding here as well would let
    # this session writable layer veto an owner decision it cannot see. It
    # therefore abstains — but only when the owner installed guard is really
    # installed *and* really registered, both checked on root owned files.
    is_authoritative = authoritative or authoritative_guard_active
    if is_authoritative():
        stdout.write(
            json.dumps(
                {
                    "guardOutcome": "no_opinion",
                    "deferredTo": "authoritative_guard",
                },
                sort_keys=True,
            )
            + "\n"
        )
        return 0

    try:
        decision, reason_code, record = decide(payload)
    except Exception:  # noqa: BLE001 - an internal error must never release
        stdout.write(json.dumps(_deny(guard_errors.GUARD_INTERNAL_ERROR)) + "\n")
        return 0

    if decision in (DECISION_ASK, DECISION_DENY):
        cwd = str(payload.get("cwd") or os.getcwd())
        try:
            worktree = gitutil.toplevel(cwd)
        except gitutil.GitError:
            worktree = None
        try:
            log_decision(decision, reason_code, record, worktree=worktree)
        except OSError:  # pragma: no cover - the raw log must not break the hook
            pass
    if decision is None:
        stdout.write(json.dumps({"guardOutcome": "no_opinion"}) + "\n")
        return 0
    stdout.write(json.dumps(build_response(decision, reason_code)) + "\n")
    return 0


def _deny(code):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": DECISION_DENY,
            "permissionDecisionReason": code + ": " + guard_errors.message(code),
        }
    }


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
