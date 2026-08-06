#!/bin/bash
# Owner helper: create one narrow, single use guard exception.
#
# This is not a switch and not a bypass. It releases exactly one
# canonicalised command, in exactly one worktree, for at most ten minutes,
# exactly once. It never applies to a guard integrity failure — if the guard
# itself cannot be loaded or verified, the repair is a reinstallation, not an
# exception.
#
#   sudo /bin/bash scripts/guard-exception.sh \
#     --worktree <path> --command '<exact command>' --reason '<why>' \
#     [--ttl <seconds, max 600>] --confirm
#
# Claude Code must not run this script. It refuses to run unless it is root.

set -euo pipefail

export LC_ALL=C
export LANG=C
export TZ=UTC
export PYTHONDONTWRITEBYTECODE=1

readonly DEFAULT_TARGET="/usr/local/jarvis-guard"
readonly GUARD_PYTHON="/usr/bin/python3"
readonly MAX_TTL=600

TARGET="${DEFAULT_TARGET}"
WORKTREE=""
COMMAND_TEXT=""
REASON=""
TTL=600
CONFIRM="no"

die() {
  printf 'guard-exception: %s\n' "$1" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --worktree) WORKTREE="${2:-}"; shift 2 ;;
    --command) COMMAND_TEXT="${2:-}"; shift 2 ;;
    --reason) REASON="${2:-}"; shift 2 ;;
    --ttl) TTL="${2:-}"; shift 2 ;;
    --confirm) CONFIRM="yes"; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ "$(id -u)" = "0" ] || die "must run as root (use sudo); the guarded session cannot create an exception"
[ -n "${WORKTREE}" ] || die "--worktree is required"
[ -n "${COMMAND_TEXT}" ] || die "--command is required"
[ -n "${REASON}" ] || die "--reason is required; an exception without a reason is not created"
[ -d "${WORKTREE}" ] || die "worktree does not exist: ${WORKTREE}"
[ -d "${TARGET}/active/guard" ] || die "no active guard installation at ${TARGET}"
[ -x "${GUARD_PYTHON}" ] || die "system interpreter not available"
case "${TTL}" in
  *[!0-9]* | "") die "--ttl must be a positive integer" ;;
esac
[ "${TTL}" -gt 0 ] || die "--ttl must be positive"
[ "${TTL}" -le "${MAX_TTL}" ] || die "--ttl exceeds the hard limit of ${MAX_TTL} seconds"
case "${COMMAND_TEXT}" in
  *"*"* | *"?"*) die "wildcards are not permitted in an exception command" ;;
esac

PENDING="${TARGET}/var/exceptions/pending"
[ -d "${PENDING}" ] || die "exception area missing: ${PENDING}"

NONCE="$("${GUARD_PYTHON}" -I -B -c 'import secrets;print(secrets.token_hex(16))')"
readonly NONCE

PREVIEW="$("${GUARD_PYTHON}" -I -B -c '
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
from guard import GUARD_VERSION
from guard import owner_exception
payload = owner_exception.build(
    nonce=sys.argv[2],
    worktree=sys.argv[3],
    command=sys.argv[4],
    reason=sys.argv[5],
    created_at=int(time.time()),
    ttl_seconds=int(sys.argv[6]),
    guard_version=GUARD_VERSION,
)
print(json.dumps(payload, sort_keys=True, indent=2))
' "${TARGET}/active" "${NONCE}" "${WORKTREE}" "${COMMAND_TEXT}" "${REASON}" "${TTL}")"
readonly PREVIEW

printf 'guard-exception: the following single use exception will be created\n'
printf '%s\n' "${PREVIEW}" \
  | grep -v '"nonce"' \
  | grep -v '"integrity_sha256"'
printf 'guard-exception: validity %s seconds, single use, no wildcard, no renewal\n' "${TTL}"

if [ "${CONFIRM}" != "yes" ]; then
  printf 'guard-exception: re-run with --confirm to create it\n'
  exit 1
fi

# prune expired objects so the area stays small and auditable
"${GUARD_PYTHON}" -I -B -c '
import json, os, sys, time
pending = sys.argv[1]
now = int(time.time())
for name in sorted(os.listdir(pending)):
    if not name.endswith(".json"):
        continue
    path = os.path.join(pending, name)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        expired = int(payload["expires_at"]) <= now
    except Exception:
        expired = False
    if expired:
        os.unlink(path)
' "${PENDING}"

TARGET_FILE="${PENDING}/${NONCE}.json"
printf '%s\n' "${PREVIEW}" > "${TARGET_FILE}"
chown root:wheel "${TARGET_FILE}"
chmod 0444 "${TARGET_FILE}"

LOG="${TARGET}/var/activation.log"
touch "${LOG}"
chown root:wheel "${LOG}"
chmod 0600 "${LOG}"
printf '%s exception_created nonce_digest=%s ttl=%s reason_length=%s\n' \
  "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  "$("${GUARD_PYTHON}" -I -B -c \
     'import hashlib,sys;print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:16])' \
     "${NONCE}")" \
  "${TTL}" "${#REASON}" >> "${LOG}"

printf 'guard-exception: created, single use, expires in %s seconds\n' "${TTL}"
exit 0
