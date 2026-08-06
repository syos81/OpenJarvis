#!/usr/bin/env bash
# Public interface of the decision number reservation register.
#
#   scripts/dec-reservations.sh <subcommand> [options]
#
# Subcommands: verify, status, next-free, scan, reserve, assign, release,
# plan-push. Every one of them writes exactly one machine readable JSON
# document to stdout.
#
# This wrapper only discovers the worktree and a suitable Python interpreter.
# Every decision — validity, transitions, freeness, freshness — is made by the
# deterministic model in tools/decreg/.
#
# No eval, no composed shell strings, no interactive selection, no silent
# defaults. The register is never pushed by this tool: plan-push prints the
# single exact owner command and performs nothing.

set -euo pipefail

export LC_ALL=C
export LANG=C
export TZ=UTC
export PYTHONHASHSEED=0
export PYTHONDONTWRITEBYTECODE=1
export PYTHONIOENCODING=utf-8

readonly EXIT_BLOCKED=3

emit_blocked() {
  # $1 = reason_code, $2 = message
  printf '{\n  "schema_version": 1,\n  "ok": false,\n  "reason_code": "%s",\n  "detail": "%s"\n}\n' "$1" "$2"
  exit "${EXIT_BLOCKED}"
}

if ! WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  emit_blocked "worktree_undetermined" "not inside a git worktree"
fi
readonly WORKTREE_ROOT

if [ ! -d "${WORKTREE_ROOT}/tools/decreg" ]; then
  emit_blocked "engine_missing" "tools/decreg is not present in this worktree"
fi

# Interpreter resolution: explicit override, local virtualenv, then the
# highest supported interpreter found on PATH. No user path is hard coded.
DECREG_PYTHON="${DECREG_PYTHON:-}"
if [ -z "${DECREG_PYTHON}" ] && [ -x "${WORKTREE_ROOT}/.venv/bin/python" ]; then
  DECREG_PYTHON="${WORKTREE_ROOT}/.venv/bin/python"
fi
if [ -z "${DECREG_PYTHON}" ]; then
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      if "${candidate}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        DECREG_PYTHON="$(command -v "${candidate}")"
        break
      fi
    fi
  done
fi
if [ -z "${DECREG_PYTHON}" ]; then
  emit_blocked "python_missing" "no Python 3.10+ interpreter found on PATH"
fi
readonly DECREG_PYTHON

# The repository the register lives in defaults to this worktree. A caller may
# point the tool at a throwaway fixture instead by passing --repo explicitly.
DECREG_REPO="${WORKTREE_ROOT}"
for argument in "$@"; do
  if [ "${argument}" = "--repo" ]; then
    DECREG_REPO=""
    break
  fi
done

cd "${WORKTREE_ROOT}"
if [ -n "${DECREG_REPO}" ]; then
  PYTHONPATH="${WORKTREE_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" \
    exec "${DECREG_PYTHON}" -m tools.decreg.cli --repo "${DECREG_REPO}" "$@"
fi
PYTHONPATH="${WORKTREE_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" \
  exec "${DECREG_PYTHON}" -m tools.decreg.cli "$@"
