#!/bin/bash
# Owner tool for the exception objects the running guard decided to ignore.
#
#   scripts/guard-collect.sh status       [--target <dir>]
#   scripts/guard-collect.sh verify       [--target <dir>] [--area <name>]
#                                         [--path <dir>]
#   scripts/guard-collect.sh plan-collect [--target <dir>]
#   sudo /bin/bash scripts/guard-collect.sh collect [--target <dir>] --confirm
#
# The first three are read only and may be run by anyone who can read the
# installation, the guarded session included. They open no file for writing.
#
# ``collect`` moves every structurally sound non candidate out of the
# protected pending area into ``var/exceptions/collected``. It refuses unless
# it is root, so the guarded session cannot run it — and ``plan-collect``
# exists precisely so the session can prepare it without running it.
#
# Nothing here ever deletes an exception object, edits one, or touches a
# candidate. A corrupt object is reported and deliberately left where it is:
# it is the one kind of object that still blocks every decision, and moving it
# would repair a block nobody has looked at.

set -euo pipefail

export LC_ALL=C
export LANG=C
export TZ=UTC
export PYTHONDONTWRITEBYTECODE=1

readonly DEFAULT_TARGET="/usr/local/jarvis-guard"
# Same reasoning as the installer: /usr/bin/python3 resolves into a bundle
# that can belong to the ordinary user. This one is root owned along its
# whole ancestor chain.
readonly GUARD_PYTHON="/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9"

readonly EXIT_UNUSABLE=2
readonly EXIT_REFUSED=3

die() {
  printf 'guard-collect: %s\n' "$1" >&2
  exit "${EXIT_UNUSABLE}"
}

[ "$#" -ge 1 ] || die "a subcommand is required: status, verify, plan-collect, collect"

SUBCOMMAND="$1"
shift

case "${SUBCOMMAND}" in
  status | verify | plan-collect | collect) : ;;
  *) die "unknown subcommand: ${SUBCOMMAND}" ;;
esac

TARGET="${DEFAULT_TARGET}"
AREA="pending"
AREA_PATH=""
GUARD_SOURCE="active"
CONFIRM="no"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --area) AREA="${2:-}"; shift 2 ;;
    --path) AREA_PATH="${2:-}"; shift 2 ;;
    --guard-source) GUARD_SOURCE="${2:-}"; shift 2 ;;
    --confirm) CONFIRM="yes"; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "${TARGET}" ] || die "--target must not be empty"
[ -x "${GUARD_PYTHON}" ] || die "system interpreter not available: ${GUARD_PYTHON}"

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
readonly SCRIPT_DIR
WORKTREE="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly WORKTREE
[ -f "${WORKTREE}/tools/guardops/collect.py" ] || die "tool source not found in this worktree"

# The refusal is stated here as well as inside the tool. Two independent
# refusals, because this one is the one the owner reads before typing sudo.
if [ "${SUBCOMMAND}" = "collect" ]; then
  if [ "$(id -u)" != "0" ]; then
    printf 'guard-collect: collect is an owner action and requires root\n' >&2
    printf 'guard-collect: run plan-collect first; it prints the exact command\n' >&2
    exit "${EXIT_REFUSED}"
  fi
  if [ "${CONFIRM}" != "yes" ]; then
    printf 'guard-collect: re-run with --confirm to move the objects\n' >&2
    exit "${EXIT_REFUSED}"
  fi
fi

ARGUMENTS=("${SUBCOMMAND}" --target "${TARGET}" --worktree "${WORKTREE}"
           --guard-source "${GUARD_SOURCE}")
if [ "${SUBCOMMAND}" = "verify" ]; then
  ARGUMENTS+=(--area "${AREA}")
  if [ -n "${AREA_PATH}" ]; then
    ARGUMENTS+=(--path "${AREA_PATH}")
  fi
fi
if [ "${SUBCOMMAND}" = "collect" ] && [ "${CONFIRM}" = "yes" ]; then
  ARGUMENTS+=(--confirm)
fi

exec "${GUARD_PYTHON}" -I -B "${WORKTREE}/tools/guardops/collect.py" "${ARGUMENTS[@]}"
