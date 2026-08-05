#!/usr/bin/env bash
# Public gate interface.
#
#   scripts/gate.sh --block <block-id> --phase <phase>
#
# Block and phase are mandatory. This wrapper only discovers the worktree and
# a suitable Python interpreter; every decision (phases, results, baseline,
# evidence) is made by the deterministic engine in tools/gates/.
#
# No eval, no composed shell strings, no interactive selection, no silent
# defaults. stdout carries exactly one machine readable JSON document.

set -euo pipefail

export LC_ALL=C
export LANG=C
export TZ=UTC
export PYTHONHASHSEED=0
export PYTHONDONTWRITEBYTECODE=1
export PYTHONIOENCODING=utf-8

readonly EXIT_BLOCKED=30

emit_blocked() {
  # $1 = reason_code, $2 = message
  printf '{\n  "schema_version": 1,\n  "error": true,\n  "reason_code": "%s",\n  "message": "%s",\n  "status": "blocked"\n}\n' "$1" "$2"
  exit "${EXIT_BLOCKED}"
}

if ! WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  emit_blocked "worktree_undetermined" "not inside a git worktree"
fi
readonly WORKTREE_ROOT

if [ ! -d "${WORKTREE_ROOT}/tools/gates" ]; then
  emit_blocked "engine_missing" "tools/gates is not present in this worktree"
fi

# Interpreter resolution: explicit override, local virtualenv, then the
# highest supported interpreter found on PATH. No user path is hard coded.
GATE_PYTHON="${GATE_PYTHON:-}"
if [ -z "${GATE_PYTHON}" ] && [ -x "${WORKTREE_ROOT}/.venv/bin/python" ]; then
  GATE_PYTHON="${WORKTREE_ROOT}/.venv/bin/python"
fi
if [ -z "${GATE_PYTHON}" ]; then
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      if "${candidate}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        GATE_PYTHON="$(command -v "${candidate}")"
        break
      fi
    fi
  done
fi
if [ -z "${GATE_PYTHON}" ]; then
  emit_blocked "python_missing" "no Python 3.10+ interpreter found on PATH"
fi
readonly GATE_PYTHON
export GATE_PYTHON

cd "${WORKTREE_ROOT}"
PYTHONPATH="${WORKTREE_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" \
  exec "${GATE_PYTHON}" -m tools.gates.cli "$@"
