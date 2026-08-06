#!/bin/bash
# Registered PreToolUse wrapper of the external guard — installed template.
#
# The owner installer substitutes @@GUARD_ROOT@@ and @@GUARD_PYTHON@@ and
# writes the result into the owner controlled installation root. Only
# absolute paths are used: no PATH, no alias, no PYTHONPATH, no working
# directory, no user writable wrapper.
#
# Fail closed: the wrapper releases a request only when the guard produced a
# document that either carries a permission decision or explicitly states
# that the guard has no opinion. Anything else — a crash, a truncated
# document, a missing interpreter, an empty output — blocks.

set -euo pipefail

export LC_ALL=C
export LANG=C
export TZ=UTC
export PYTHONDONTWRITEBYTECODE=1

readonly GUARD_ROOT="@@GUARD_ROOT@@"
readonly GUARD_PYTHON="@@GUARD_PYTHON@@"

readonly DENY_BOOTSTRAP='{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"GUARD_BOOTSTRAP_FAILED: the guard bootstrap could not produce a decision"}}'
readonly DENY_INTERPRETER='{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"GUARD_INTERPRETER_MISSING: no owner controlled interpreter is available"}}'

if [ ! -x "${GUARD_PYTHON}" ]; then
  printf '%s\n' "${DENY_INTERPRETER}"
  exit 0
fi

if [ ! -f "${GUARD_ROOT}/bootstrap.py" ]; then
  printf '%s\n' "${DENY_BOOTSTRAP}"
  exit 0
fi

GUARD_OUTPUT=""
if ! GUARD_OUTPUT="$("${GUARD_PYTHON}" -I -B "${GUARD_ROOT}/bootstrap.py" 2>/dev/null)"; then
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
    printf '%s\n' "${DENY_BOOTSTRAP}"
    ;;
esac

exit 0
