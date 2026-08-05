#!/usr/bin/env bash
# PreToolUse guard: hard denies, path canonicalisation, foreign worktree
# protection. The decision logic lives in tools/gates/hookguard.py so it can be
# tested in isolated temporary repositories.
#
# The hook must never break the session: if no interpreter is available it
# stays silent (exit 0) and the normal permission rules from settings.json
# — including the hard denies — remain in force.

set -euo pipefail

export LC_ALL=C
export LANG=C
export TZ=UTC
export PYTHONDONTWRITEBYTECODE=1

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}"
if [ -z "${PROJECT_DIR}" ]; then
  PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "${PROJECT_DIR}" ] || [ ! -d "${PROJECT_DIR}/tools/gates" ]; then
  exit 0
fi

GUARD_PYTHON="${GATE_PYTHON:-}"
if [ -z "${GUARD_PYTHON}" ] && [ -x "${PROJECT_DIR}/.venv/bin/python" ]; then
  GUARD_PYTHON="${PROJECT_DIR}/.venv/bin/python"
fi
if [ -z "${GUARD_PYTHON}" ]; then
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      if "${candidate}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        GUARD_PYTHON="$(command -v "${candidate}")"
        break
      fi
    fi
  done
fi
if [ -z "${GUARD_PYTHON}" ]; then
  exit 0
fi

PYTHONPATH="${PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
  exec "${GUARD_PYTHON}" -m tools.gates.hookguard
