#!/bin/bash
# Repository side PreToolUse hook — defence in depth, **not** the trust anchor.
#
# The authoritative guard is the owner installed copy outside every worktree,
# registered through the protected policy settings. This hook lives inside
# the guarded worktree and is therefore modifiable by the guarded session; it
# is never the protection boundary and must never be reported as one.
#
# Fail closed regardless: every error path — unresolvable project directory,
# missing guard source, missing interpreter, crashing decision, empty output
# — blocks the request. There is no silent exit 0 any more.

set -euo pipefail

export LC_ALL=C
export LANG=C
export TZ=UTC
export PYTHONDONTWRITEBYTECODE=1

readonly GUARD_PYTHON="/usr/bin/python3"

deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$1"
  exit 0
}

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}"
if [ -z "${PROJECT_DIR}" ] || [ ! -d "${PROJECT_DIR}/tools/guard" ]; then
  PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"
fi

if [ ! -d "${PROJECT_DIR}/tools/guard" ]; then
  deny "GUARD_PROJECT_DIR_UNRESOLVED: the repository side guard source is not reachable"
fi

if [ ! -x "${GUARD_PYTHON}" ]; then
  deny "GUARD_INTERPRETER_MISSING: no owner controlled interpreter is available"
fi

GUARD_OUTPUT=""
if ! GUARD_OUTPUT="$(cd "${PROJECT_DIR}" && PYTHONPATH="${PROJECT_DIR}" \
  "${GUARD_PYTHON}" -B -m tools.gates.hookguard 2>/dev/null)"; then
  GUARD_OUTPUT=""
fi

case "${GUARD_OUTPUT}" in
  *'"permissionDecision"'*)
    printf '%s\n' "${GUARD_OUTPUT}"
    ;;
  *'"guardOutcome"'*)
    : # the guard deliberately has no opinion
    ;;
  *)
    deny "GUARD_BOOTSTRAP_FAILED: the repository side guard could not produce a decision"
    ;;
esac

exit 0
